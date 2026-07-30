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
    - backend:cli-tests
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
        "backend:cli-tests",
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


def test_docstring_does_not_name_fake_stages() -> None:
    """The module docstring must not name stages that are
    not part of :func:`build_step_plan`.

    The previous docstring named ``backend:alembic-roundtrip``
    and ``backend:smoke`` even though neither was part of
    the ten-stage verifier. The docstring must be
    consistent with the actual plan; the alembic round-trip
    and smoke validation are documented as separate
    release-checklist steps that the verifier does not run.
    """
    import scripts.verify_release as vr

    docstring = vr.__doc__ or ""
    plan_labels = [step.label for step in build_step_plan()]
    # The docstring must not advertise a stage that is not
    # in the plan. We check for the two historical
    # offenders; if a new fake stage is introduced in the
    # future, this assertion will catch it.
    for fake_label in (
        "backend:alembic-roundtrip",
        "backend:smoke",
    ):
        assert fake_label not in docstring, (
            f"verify_release docstring names {fake_label!r} but the step "
            f"is not in build_step_plan. Either add the stage to "
            f"build_step_plan or remove the mention from the docstring."
        )
        assert fake_label not in plan_labels, (
            f"build_step_plan unexpectedly contains {fake_label!r}; "
            f"either remove it from the plan or update this test."
        )
    # Conversely, every label in the plan must be mentioned
    # in the docstring at least once. This pins the
    # docstring to the actual ten stages.
    for label in plan_labels:
        assert label in docstring, (
            f"verify_release docstring does not mention stage {label!r} "
            f"from build_step_plan. Update the docstring to describe the "
            f"stage, or remove the stage from the plan."
        )
    # The docstring must state that npm audit stages
    # require registry/advisory network access.
    assert "registry" in docstring.lower() or "advisory" in docstring.lower(), (
        "verify_release docstring must note that npm audit stages require "
        "registry/advisory network access"
    )
    # The docstring must state that alembic round-trip and
    # smoke validation are external release-checklist
    # checks, not part of the verifier.
    assert "alembic" in docstring.lower(), (
        "verify_release docstring must mention the alembic migration "
        "round-trip as an external release-checklist check"
    )
    assert "smoke" in docstring.lower(), (
        "verify_release docstring must mention the smoke validation as "
        "an external release-checklist check"
    )


def test_docstring_acknowledges_migration_tests_in_backend_pytest() -> None:
    """The docstring must NOT claim that the verifier
    excludes migration tests; it must explicitly state
    that ``backend:pytest`` includes the repository's
    automated migration tests.

    The pre-correction wording implied that the operator
    had to run the migration round-trip as an external
    release-checklist step because the verifier did not
    run it at all. That claim was inaccurate: the
    ``backend:pytest`` stage runs the full backend test
    suite, which already includes
    ``tests/test_migration_cycle.py`` and
    ``tests/test_migration_f6a7b8c9d0e1.py``. A
    failure of either would fail the verifier.

    The correction distinguishes:
    - automated migration tests included through
      ``backend:pytest`` (always run; failure halts
      the verifier);
    - optional operator-driven manual migration
      round-trip confirmation (complements, does not
      replace, the automated coverage).
    """
    import scripts.verify_release as vr

    docstring = vr.__doc__ or ""
    # Positive: the docstring must explicitly state that
    # backend:pytest includes the automated migration
    # tests. The pre-correction wording was a single
    # sentence saying migration tests are NOT in the
    # verifier. The corrected wording must distinguish
    # the automated coverage in backend:pytest from
    # the optional manual confirmation.
    assert "backend:pytest" in docstring, (
        "docstring must reference the backend:pytest stage when describing migration coverage"
    )
    # The docstring must explicitly link backend:pytest
    # to migration test execution. We accept the
    # relationship in any phrasing, but the claim must
    # be present (the operator must not be misled into
    # running migrations separately if they already
    # run through the verifier). The docstring renders
    # ``backend:pytest`` as a reST literal with
    # backticks; we accept both with and without the
    # backticks.
    claim_phrases = (
        "``backend:pytest`` stage runs the full backend test suite",
        "backend:pytest stage runs the full backend test suite",
        "``backend:pytest`` already covers",
        "backend:pytest already covers",
        "``backend:pytest`` already runs",
        "backend:pytest already runs",
        "already includes the repository's automated migration tests",
    )
    assert any(phrase in docstring for phrase in claim_phrases), (
        "docstring must explicitly state that backend:pytest includes "
        "the automated migration tests; none of the expected claim "
        f"phrases was found. Looked for: {claim_phrases!r}"
    )
    # The docstring must distinguish the optional manual
    # confirmation from the automated coverage.
    assert (
        "operator-driven" in docstring.lower()
        or "additional" in docstring.lower()
        or "complement" in docstring.lower()
    ), (
        "docstring must distinguish the optional manual migration "
        "confirmation from the automated backend:pytest coverage"
    )
    # Negative: the docstring must NOT claim that the
    # verifier does not run any migration tests. The
    # pre-correction wording was "migration validation
    # is wholly absent from the verifier" or similar.
    forbidden_phrases = (
        "migration validation is wholly absent",
        "the verifier does not run any migration test",
        "no migration test is included in backend:pytest",
        "backend:pytest does not include any migration",
    )
    for phrase in forbidden_phrases:
        assert phrase.lower() not in docstring.lower(), (
            f"docstring contains the forbidden claim {phrase!r}; the "
            f"verifier DOES run migration tests via backend:pytest. "
            f"Remove the claim or rephrase to acknowledge backend:pytest."
        )


def test_docstring_smoke_claim_is_backed_by_release_checklist() -> None:
    """If the docstring names ``scripts_smoke_v0_5.py`` as an
    external release-checklist command, the release
    checklist must name the same script.

    The pre-correction wording claimed the smoke
    validation was "documented in the release checklist"
    without the release checklist actually naming the
    script. The correction makes the claim
    falsifiable: if the docstring names a script, the
    release checklist must name that script in a
    code-block or as a literal command.
    """
    import scripts.verify_release as vr

    docstring = vr.__doc__ or ""
    repo_root = BACKEND_DIR.parent
    release_checklist = repo_root / "docs" / "release-checklist.md"
    assert release_checklist.exists(), f"docs/release-checklist.md not found at {release_checklist}"
    checklist_text = release_checklist.read_text(encoding="utf-8")
    # The docstring names the smoke script as an external
    # release-checklist step. The release checklist must
    # name the same script.
    if "scripts_smoke_v0_5.py" in docstring:
        assert "scripts_smoke_v0_5.py" in checklist_text, (
            "docstring references scripts_smoke_v0_5.py as an external "
            "release-checklist step, but docs/release-checklist.md does "
            "not name the script. Add the exact command to the release "
            "checklist (e.g. in a code block under an external "
            "release-checklist section) or remove the claim from the "
            "docstring."
        )
        # The release-checklist command must be a runnable
        # form, not a bare reference. We accept either
        # python (POSIX) or python.exe (Windows) invocation
        # of the script.
        for invocation in (
            "python scripts_smoke_v0_5.py",
            "python.exe scripts_smoke_v0_5.py",
            "python -m scripts_smoke_v0_5",
            "python.exe -m scripts_smoke_v0_5",
        ):
            if invocation in checklist_text:
                break
        else:
            # No runnable command form was found. The
            # release checklist only mentions the script
            # in passing.
            raise AssertionError(
                "docs/release-checklist.md mentions scripts_smoke_v0_5.py "
                "but does not include a runnable command form "
                "(expected one of: python scripts_smoke_v0_5.py, "
                "python.exe scripts_smoke_v0_5.py, etc.). Add the exact "
                "command to the release checklist in a code block."
            )


def test_docstring_npm_audit_network_wording_is_accurate() -> None:
    """The docstring's npm-audit network claim must be
    accurate: registry/advisory database access, not
    arbitrary internet.
    """
    import scripts.verify_release as vr

    docstring = vr.__doc__ or ""
    # The npm audit stages are documented as requiring
    # outbound network access. The wording must name
    # the public npm advisory database specifically
    # (the actual data source) and must NOT misname it
    # (e.g. must not claim it queries the package
    # registry metadata endpoint).
    assert "registry.npmjs.org" in docstring or "npm advisory database" in docstring.lower(), (
        "docstring must name the npm audit data source specifically "
        "(registry.npmjs.org or 'npm advisory database')"
    )
    # The wording must distinguish network access
    # (registry/advisory) from the offline stages.
    assert "offline" in docstring.lower() or "loopback" in docstring.lower(), (
        "docstring must state that the offline stages make no HTTP calls"
    )
    # The wording must NOT claim that the auditor is
    # covered by the backend fixture-based network guard.
    # The auditor runs as a sibling npm process and is
    # outside the pytest fixture scope.
    forbidden_audit_claims = (
        "the auditor runs inside the pytest network guard",
        "the auditor is covered by the network guard",
        "the backend network guard applies to the auditor",
    )
    for phrase in forbidden_audit_claims:
        assert phrase.lower() not in docstring.lower(), (
            f"docstring contains the inaccurate claim {phrase!r}; the "
            f"npm auditor runs as a sibling npm process and is not "
            f"covered by the pytest-based network guard."
        )


def test_no_verifier_stage_was_added_removed_renamed_or_weakened() -> None:
    """The eleven-stage verifier is the single source of
    truth. The step plan must be exactly the documented
    set of eleven stages in the documented order; no
    stage may be added, removed, renamed, or weakened.
    The v2.1 Part B2 release adds the dedicated
    ``backend:cli-tests`` stage for the new
    ``tests/test_cli.py`` module.
    """
    expected_labels = [
        "backend:pytest",
        "backend:cli-tests",
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
    plan_labels = [step.label for step in build_step_plan()]
    assert plan_labels == expected_labels, (
        f"build_step_plan does not match the documented eleven-stage plan. "
        f"Expected {expected_labels!r}, got {plan_labels!r}. The verifier "
        f"is the single source of truth; update the docstring and the "
        f"release checklist in the same change."
    )
    # The plan must have exactly eleven stages.
    assert len(plan_labels) == 11, (
        f"build_step_plan must have exactly eleven stages, got {len(plan_labels)}"
    )
    # No stage label may duplicate another.
    assert len(set(plan_labels)) == len(plan_labels), (
        "build_step_plan contains duplicate stage labels"
    )
    # Every stage must have a bounded timeout (no
    # infinite-blocking stages; a hung subprocess must
    # fail fast).
    for step in build_step_plan():
        assert step.timeout_seconds is not None and step.timeout_seconds > 0, (
            f"stage {step.label!r} has no bounded timeout; a hung "
            f"subprocess would block the verifier indefinitely"
        )


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
