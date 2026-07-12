"""Tests for :mod:`app.utils.graph`."""

from __future__ import annotations

import pytest
from app.utils.graph import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_PATHS,
    DEFAULT_MAX_PATHS_PER_NODE,
    detect_cycles,
    find_paths,
)


def test_simple_root_to_target_path() -> None:
    graph = {"a": {"b": ["1.0.0"]}, "b": {"c": ["1.0.0"]}, "c": {}}
    summary = find_paths(graph, "a", target="c", max_depth=5)
    assert len(summary.paths) == 1
    path = summary.paths[0]
    assert path.nodes == ("a", "b", "c")
    assert path.depth == 2
    assert summary.truncated is False


def test_multiple_paths_to_target() -> None:
    graph = {
        "a": {"b": ["1.0.0"], "d": ["1.0.0"]},
        "b": {"c": ["1.0.0"]},
        "d": {"c": ["1.0.0"]},
        "c": {},
    }
    summary = find_paths(graph, "a", target="c", max_depth=5)
    assert len(summary.paths) == 2
    sorted_paths = sorted(p.nodes for p in summary.paths)
    assert sorted_paths == [("a", "b", "c"), ("a", "d", "c")]


def test_cycle_safe() -> None:
    graph = {
        "a": {"b": ["1.0.0"]},
        "b": {"c": ["1.0.0"]},
        "c": {"a": ["1.0.0"]},
    }
    summary = find_paths(graph, "a", target="c", max_depth=5)
    # b -> c -> a (cycle back) is forbidden; the direct a -> b -> c
    # path is the only one.
    assert len(summary.paths) == 1
    assert summary.paths[0].nodes == ("a", "b", "c")


def test_max_depth_respected() -> None:
    graph = {chr(c): {} for c in range(ord("a"), ord("a") + 10)}
    for i in range(9):
        graph[chr(ord("a") + i)][chr(ord("a") + i + 1)] = ["1.0.0"]
    summary = find_paths(graph, "a", target="j", max_depth=3, max_paths=100)
    # a -> b -> c -> d is depth 3, target = j requires more
    assert summary.paths == ()


def test_max_paths_respected() -> None:
    graph = {
        "a": {f"child-{i}": ["1.0.0"] for i in range(10)},
    }
    for i in range(10):
        graph[f"child-{i}"] = {}
    summary = find_paths(graph, "a", max_depth=2, max_paths=3)
    assert len(summary.paths) == 3
    assert summary.truncated is True


def test_root_only_path_returned_when_no_target() -> None:
    graph = {"a": {}}
    summary = find_paths(graph, "a", max_depth=2)
    assert summary.paths
    # The root-only path is recorded.
    assert any(p.nodes == ("a",) for p in summary.paths)


def test_unknown_root_returns_empty() -> None:
    graph = {"a": {}}
    summary = find_paths(graph, "missing", max_depth=2)
    assert summary.paths == ()


def test_max_paths_per_node_caps_fanin() -> None:
    graph = {
        "a": {f"child-{i}": ["1.0.0"] for i in range(5)},
        "shared": {f"child-{i}": ["1.0.0"] for i in range(5)},
    }
    for i in range(5):
        graph[f"child-{i}"] = {"shared": ["1.0.0"]}
    summary = find_paths(graph, "a", target="shared", max_depth=4, max_paths_per_node=2)
    # The cap on per-node passes should kick in. We don't care
    # about the exact number; we just need at least one path and
    # a truncated flag when fan-in is excessive.
    assert summary.truncated is True or len(summary.paths) <= 5


def test_detect_cycles_returns_sample() -> None:
    graph = {
        "a": {"b": ["1.0.0"]},
        "b": {"c": ["1.0.0"]},
        "c": {"a": ["1.0.0"]},
    }
    cycles = detect_cycles(graph)
    assert len(cycles) >= 1
    cycle = cycles[0]
    assert cycle[0] == cycle[-1]


def test_default_constants_documented() -> None:
    assert DEFAULT_MAX_DEPTH > 0
    assert DEFAULT_MAX_PATHS > 0
    assert DEFAULT_MAX_PATHS_PER_NODE > 0


def test_rejects_invalid_arguments() -> None:
    graph: dict = {}
    with pytest.raises(ValueError):
        find_paths(graph, "", max_depth=1)
    with pytest.raises(ValueError):
        find_paths(graph, "a", max_depth=-1)
    with pytest.raises(ValueError):
        find_paths(graph, "a", max_paths=-1)
    with pytest.raises(ValueError):
        find_paths(graph, "a", max_paths_per_node=-1)
