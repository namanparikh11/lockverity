"""Bounded graph traversal for dependency paths.

The dependency graph in Lockverity is built from manifest and
lockfile data. It is naturally prone to:

- cycles (npm lockfiles frequently have them via peer-dep hoisting;
  Poetry is also cycle-prone)
- unbounded depth (long flat chains of ``a -> b -> c -> d -> ...``)
- large fan-out (a single dev dep can pull thousands of packages)

This module provides cycle-safe DFS with explicit depth and
returned-path caps and a deterministic, stable ordering. None of
the algorithms in here mutate the input graph.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

# Defaults. These are deliberately conservative.
DEFAULT_MAX_DEPTH = 10
DEFAULT_MAX_PATHS = 100
DEFAULT_MAX_PATHS_PER_NODE = 5


@dataclass(frozen=True, slots=True)
class PathNode:
    """A single hop in a returned path.

    ``node_id`` must be hashable and unique within a graph. ``depth``
    is the number of edges traversed from the root to this node.
    """

    node_id: str
    depth: int


@dataclass(frozen=True, slots=True)
class GraphPath:
    """A concrete root-to-leaf path through the graph."""

    nodes: tuple[str, ...]
    truncated: bool = False

    @property
    def depth(self) -> int:
        return max(0, len(self.nodes) - 1)


@dataclass(frozen=True, slots=True)
class TraversalSummary:
    """Summary of a full traversal."""

    paths: tuple[GraphPath, ...] = field(default_factory=tuple)
    truncated: bool = False
    total_paths_truncated: int = 0
    cycles_detected: tuple[tuple[str, ...], ...] = field(default_factory=tuple)


def _bfs_cycle_scan(graph: Mapping[str, Mapping[str, object]]) -> tuple[tuple[str, ...], ...]:
    """Find a sample of cycles by walking the graph from each node.

    This is intentionally best-effort: a real-world dependency graph
    can contain millions of cycles, and we only need to record that
    *some* cycle exists so the finding rules can flag it. The
    function returns at most one representative cycle per starting
    node to bound the output.
    """
    seen_cycles: list[tuple[str, ...]] = []

    def neighbors(node: str) -> Iterable[str]:
        value = graph.get(node, {})
        if not isinstance(value, Mapping):
            return ()
        for child in value:
            if isinstance(child, str):
                yield child

    def _walk(start: str, current: str, stack: list[str], depth_left: int) -> None:
        if depth_left <= 0:
            return
        for child in neighbors(current):
            if child == start and len(stack) >= 1:
                seen_cycles.append((*stack, child))
                return
            if child in stack:
                # A back-edge but not to ``start``; we still record a
                # trimmed cycle starting at the previous occurrence.
                if start in stack:
                    idx = stack.index(start)
                    seen_cycles.append((*stack[idx:], child))
                return
            stack.append(child)
            _walk(start, child, stack, depth_left - 1)
            stack.pop()

    for node in graph:
        _walk(node, node, [node], DEFAULT_MAX_DEPTH)
        if len(seen_cycles) >= 25:
            break
    return tuple(seen_cycles)


def find_paths(
    graph: Mapping[str, Mapping[str, object]],
    root: str,
    *,
    target: str | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_paths: int = DEFAULT_MAX_PATHS,
    max_paths_per_node: int = DEFAULT_MAX_PATHS_PER_NODE,
) -> TraversalSummary:
    """Return all bounded root-to-target paths in ``graph``.

    If ``target`` is ``None``, the traversal is a bounded root-to-leaf
    enumeration. The traversal is cycle-safe (a node that is already
    on the current path is not revisited) and depth-bounded
    (``max_depth`` edges from the root).

    ``max_paths`` is the absolute cap on the number of paths returned.
    ``max_paths_per_node`` is the cap on the number of paths that may
    pass through a single intermediate node. Both caps are
    deliberate defences against a deliberately hostile lockfile.
    """
    if not isinstance(root, str) or not root:
        raise ValueError("root must be a non-empty string.")
    if max_depth < 0:
        raise ValueError("max_depth must be non-negative.")
    if max_paths < 0:
        raise ValueError("max_paths must be non-negative.")
    if max_paths_per_node < 0:
        raise ValueError("max_paths_per_node must be non-negative.")

    if root not in graph:
        return TraversalSummary()

    paths: list[GraphPath] = []
    node_pass_count: dict[str, int] = {}
    total_truncated = 0
    truncated = False

    def _record(path_nodes: list[str], *, was_truncated: bool) -> None:
        nonlocal total_truncated, truncated, paths
        if was_truncated:
            total_truncated += 1
            truncated = True
        if len(paths) >= max_paths:
            truncated = True
            return
        paths.append(GraphPath(tuple(path_nodes), truncated=was_truncated))

    def neighbors(node: str) -> list[str]:
        value = graph.get(node, {})
        if not isinstance(value, Mapping):
            return []
        result: list[str] = []
        for child in value:
            if isinstance(child, str):
                result.append(child)
        # Stable ordering. The manifest scanner already de-duplicates
        # and sorts, so this just needs to be deterministic.
        return sorted(result)

    def _walk(current: str, path: list[str], depth_left: int) -> None:
        nonlocal total_truncated, truncated, paths, node_pass_count
        if len(paths) >= max_paths:
            truncated = True
            return
        # We are about to commit this hop; check the per-node cap.
        for node in path:
            count = node_pass_count.get(node, 0)
            if count >= max_paths_per_node:
                total_truncated += 1
                truncated = True
                return
        for node in path:
            node_pass_count[node] = node_pass_count.get(node, 0) + 1

        if target is None:
            # Record this path as a leaf path. We always record the
            # root-only path (depth 0) and every intermediate.
            _record(path, was_truncated=False)

        for child in neighbors(current):
            if child in path:
                # Back-edge: this is a cycle. We do not descend.
                continue
            if depth_left == 0:
                total_truncated += 1
                truncated = True
                continue
            new_path = [*path, child]
            if target is not None and child == target:
                _record(new_path, was_truncated=False)
                # Continue looking for more target paths, but do not
                # descend past a target hit.
                continue
            _walk(child, new_path, depth_left - 1)

    _walk(root, [root], max_depth)

    cycles = _bfs_cycle_scan(graph)
    return TraversalSummary(
        paths=tuple(paths),
        truncated=truncated,
        total_paths_truncated=total_truncated,
        cycles_detected=cycles,
    )


def detect_cycles(graph: Mapping[str, Mapping[str, object]]) -> tuple[tuple[str, ...], ...]:
    """Return a sample of cycles in ``graph``.

    The function delegates to the cycle scan used by
    :func:`find_paths` and exists as a public API for rules that
    need cycle evidence without performing a full path search.
    """
    return _bfs_cycle_scan(graph)
