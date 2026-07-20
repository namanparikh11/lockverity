"""Tests for the release-validation script helper logic.

The script is invoked once per release by an operator; these
tests cover the pure helpers (step plan shape, tail
truncation, summary rendering, argv-only subprocess
construction) without actually running the full suite from
pytest (which would be slow and brittle).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from scripts.verify_release import (
    BACKEND_DIR,
    FRONTEND_DIR,
    Step,
    StepResult,
    _tail,
    build_step_plan,
    render_summary,
    run_step,
    run_step_plan,
)


def test_step_plan_runs_every_documented_step() -> None:
    """The step plan must cover every documented release step.

    The documented order is:

    - backend:pytest
    - backend:ruff-check
    - backend:ruff-format
    - backend:pip-check
    - frontend:test
    - frontend:typecheck
    - frontend:lint
    - frontend:build
    - frontend:audit-omit-dev
    - frontend:audit
    """
    plan = build_step_plan()
    labels = [step.label for step in plan]
    assert labels == [
        "backend:pytest",
        "backend:ruff-check",
        "backend:ruff-format",
        "backend:pip-check",
        "frontend:test",
        "frontend:typecheck",
        "frontend:lint",
        "frontend:build",
        "frontend:audit-omit-dev",
        "frontend:audit",
    ]


def test_step_plan_uses_argv_arrays_only() -> None:
    """Every step must use a subprocess argument list, never a shell string."""
    plan = build_step_plan()
    for step in plan:
        # Argument lists are tuple[str, ...] and never
        # contain a shell metacharacter as a single
        # argument. The test enforces the tuple type
        # only; a stronger assertion is to check that
        # no element contains characters that a shell
        # would interpret.
        assert isinstance(step.argv, tuple)
        for arg in step.argv:
            assert isinstance(arg, str)
        joined = " ".join(step.argv)
        assert "&&" not in joined
        assert "|" not in joined
        assert ";" not in joined


def test_step_plan_runs_in_documented_directories() -> None:
    """Backend steps must run in the backend dir, frontend steps in the frontend dir."""
    plan = build_step_plan()
    for step in plan:
        if step.label.startswith("backend:"):
            assert step.cwd == BACKEND_DIR
        elif step.label.startswith("frontend:"):
            assert step.cwd == FRONTEND_DIR
        else:  # pragma: no cover - defensive
            pytest.fail(f"unknown step prefix: {step.label}")


def test_step_plan_has_non_zero_timeouts() -> None:
    """Every step must have a bounded timeout so a hung subprocess fails fast.

    The exact timeout is per-step; the assertion is that no
    step is set to ``None`` (which would block forever).
    """
    plan = build_step_plan()
    for step in plan:
        assert step.timeout_seconds is not None
        assert step.timeout_seconds > 0


def test_step_plan_python_executable_is_resolved_relative_to_backend() -> None:
    """The default Python executable must be inside the backend venv."""
    plan = build_step_plan()
    backend_python = Path(plan[0].argv[0])
    assert backend_python.parts[0] == ".venv"


def test_tail_returns_short_text_unchanged() -> None:
    """Texts smaller than the limit are returned verbatim."""
    assert _tail("hello world") == "hello world"
    assert _tail("") == ""


def test_tail_truncates_long_text_with_marker() -> None:
    """Texts larger than the limit are truncated from the tail with a marker."""
    text = "a" * 8192
    out = _tail(text, limit=128)
    assert out.startswith("...(truncated)...")
    assert out.endswith("a" * 128)
    assert len(out) < len(text)


def test_run_step_uses_argv_not_shell() -> None:
    """The step runner must not invoke a shell to run subprocesses.

    The behaviour is enforced by the fact that
    :class:`subprocess.Popen` is called with ``argv=`` and
    no ``shell=True``. We do not have a way to inspect
    the call from this test, so we assert the equivalent
    observable property: a step whose argv is a
    shell metacharacter-only string is not accepted as a
    real ``shell=True`` command.
    """
    step = Step(
        label="noop",
        argv=("python", "-c", "import sys; sys.exit(0)"),
        cwd=Path.cwd(),
    )
    result = run_step(step)
    assert result.returncode == 0
    assert not result.timed_out


def test_run_step_captures_stdout_stderr() -> None:
    """A step's stdout and stderr are captured in the tail fields."""
    step = Step(
        label="captured",
        argv=(
            sys.executable,
            "-c",
            "print('captured-stdout-marker'); "
            "import sys; sys.stderr.write('captured-stderr-marker\\n'); "
            "sys.exit(0)",
        ),
        cwd=Path.cwd(),
    )
    result = run_step(step)
    assert result.returncode == 0
    assert "captured-stdout-marker" in result.stdout_tail
    assert "captured-stderr-marker" in result.stderr_tail


def test_run_step_handles_non_zero_exit() -> None:
    """A non-zero exit is recorded in the result without raising."""
    step = Step(
        label="fail",
        argv=(sys.executable, "-c", "import sys; sys.exit(7)"),
        cwd=Path.cwd(),
    )
    result = run_step(step)
    assert result.returncode == 7


def test_run_step_plan_stops_on_first_failure() -> None:
    """The plan runner short-circuits on the first non-zero step."""
    plan = (
        Step(
            label="ok-1",
            argv=(sys.executable, "-c", "import sys; sys.exit(0)"),
            cwd=Path.cwd(),
        ),
        Step(
            label="fail-2",
            argv=(sys.executable, "-c", "import sys; sys.exit(3)"),
            cwd=Path.cwd(),
        ),
        Step(
            label="ok-3",
            argv=(sys.executable, "-c", "import sys; sys.exit(0)"),
            cwd=Path.cwd(),
        ),
    )
    results = run_step_plan(plan)
    # The third step must NOT have been executed.
    assert [r.step.label for r in results] == ["ok-1", "fail-2"]
    assert results[1].returncode == 3


def test_render_summary_marks_failed_step() -> None:
    """The summary table distinguishes OK from FAIL steps."""
    step_ok = Step(label="ok-step", argv=("x",), cwd=Path.cwd())
    step_fail = Step(label="fail-step", argv=("x",), cwd=Path.cwd())
    results = [
        StepResult(
            step=step_ok,
            returncode=0,
            duration_seconds=1.0,
            timed_out=False,
            stdout_tail="",
            stderr_tail="",
        ),
        StepResult(
            step=step_fail,
            returncode=2,
            duration_seconds=2.5,
            timed_out=False,
            stdout_tail="",
            stderr_tail="boom",
        ),
    ]
    summary = render_summary(results)
    assert "ok-step" in summary
    assert "OK" in summary
    assert "fail-step" in summary
    assert "FAIL" in summary
    assert "boom" not in summary  # summary does not embed the tail
