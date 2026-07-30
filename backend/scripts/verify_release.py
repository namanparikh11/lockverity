"""Release validation script for the Lockverity v2.0 local-first release candidate.

The script runs the full backend + frontend verification suite
in the documented order. It is intentionally bounded: it
does not delete files, does not reset the demo database,
and does not call external providers.

The eleven real stages (:func:`build_step_plan`)
==============================================

The step plan is the single source of truth. Every stage
named in the docstring below must be present in
:func:`build_step_plan`; every stage in
:func:`build_step_plan` must be documented below. The
current eleven stages are:

  1. ``backend:pytest`` — ``pytest tests --ignore=tests/test_cli.py`` with the
     :func:`_block_external_network` autouse fixture
     patching :meth:`socket.socket.connect` to fail any
     test that opens a non-loopback socket. The
     :func:`fake_providers_for_scan_tests` autouse
     fixture in ``backend/tests/test_provider_fakes.py``
     replaces the real GitHub / OSV / deps.dev / OpenSSF
     Scorecard factories with in-process fakes that
     return ``ProviderUnavailable`` for every external
     call. The combination of the two fixtures means
     this step makes *no* outbound network calls. The
     ``tests/test_cli.py`` module is exercised by the
     dedicated ``backend:cli-tests`` step below.
  1a. ``backend:cli-tests`` — ``pytest tests/test_cli.py``
     in default collection order. The v2.1 Part B2
     CLI suite is order-independent on every supported
     host: each test isolates its runtime home, the
     conftest's autouse fixtures (settings cache reset,
     network guard, fake providers) clean up after
     themselves, and the cross-platform process
     identity checks use psutil instead of the
     fragile ``os.kill`` / ``subprocess.run`` interleaving
     that historically required a hand-curated class
     order on Windows.
  2. ``backend:ruff-check`` — static lint of the
     application, test, and scripts trees.
  3. ``backend:ruff-format`` — ``ruff format --check``
     on the same trees.
  4. ``backend:pip-check`` — dependency-resolution
     sanity check (``pip check``).
  5. ``frontend:test`` — ``vitest run`` on the full test
     suite.
  6. ``frontend:typecheck`` — ``tsc -b --noEmit``.
  7. ``frontend:lint`` — ``eslint . --max-warnings 0``.
  8. ``frontend:build`` — ``tsc -b && vite build``.
  9. ``frontend:audit-omit-dev`` — ``npm audit --omit=dev``.
  10. ``frontend:audit`` — ``npm audit``.

Stages 1-4 and 5-8 are CPU-bound and offline. Stages 9
and 10 require outbound network access to the public
npm advisory database at
``https://registry.npmjs.org/-/npm/v1/security/audits``
to fetch the current advisory feed; the auditor's
invocation is therefore not a "purely offline" step.
The auditor must be run from a host with registry
reachability; a sandboxed build that blocks the
registry cannot satisfy the audit gate. The backend
fixture-based network guard does not apply to the
auditor because the auditor runs as a sibling npm
process and not inside a pytest process.

External release-checklist checks (NOT in this verifier)
========================================================

The following items are *not* part of the eleven-stage
verifier and are not enumerated in the stages above.
The verifier does not run them; the operator runs
them separately during the release process.

A note on what ``backend:pytest`` already covers
------------------------------------------------

The ``backend:pytest`` stage runs the full backend
test suite, which already includes the repository's
automated migration tests. A failure of any of these
tests would fail ``backend:pytest`` and therefore the
verifier. The automated migration coverage in
``backend:pytest`` is:

- ``tests/test_migration_cycle.py`` — the pytest
  wrapper for the disposable upgrade / downgrade /
  re-upgrade round-trip against a fresh SQLite
  database. The pytest entry point is
  ``test_alembic_upgrade_downgrade_reupgrade``; the
  underlying script is
  ``tests.manual_migration_cycle`` which can also be
  invoked directly.
- ``tests/test_migration_f6a7b8c9d0e1.py`` — the
  v2.0.6 cycle-7-final migration's own dedicated
  regression tests. They pin the migration-local
  sanitiser, the backfill behaviour, the GitHub
  provenance preservation, the null-handling
  invariants, and the full upgrade / downgrade /
  re-upgrade cycle.

The items below are *operator-driven manual
confirmations* that complement (do not replace) the
automated coverage above.

- **Operator-driven manual migration round-trip
  confirmation.** The operator may additionally
  perform a manual upgrade / downgrade / re-upgrade
  confirmation as an explicit release-checklist
  step. The recommended command is documented in
  ``docs/release-checklist.md`` and is:

  .. code-block:: powershell

      cd backend
      .venv\\Scripts\\python.exe -m tests.manual_migration_cycle

  This is an *additional* operator confirmation; the
  automated pytest coverage above already runs the
  same upgrade / downgrade / re-upgrade cycle and
  must be green for the verifier to pass.
- **Smoke validation.** Run
  ``python scripts_smoke_v0_5.py`` to exercise the
  v0.5 integrated smoke flow (alembic upgrade, two-scan
  comparison, lifecycle events, comparison refresh,
  cross-workspace rejection, evidence-envelope
  validation, provider-cache preservation). The
  release checklist documents the exact command.
  This step is not part of the eleven-stage verifier.

Adding or reordering a stage requires updating both
:func:`build_step_plan` and this docstring in the same
change.

Network-isolation guarantee
===========================

The ``backend:pytest`` step runs offline because the
:func:`_block_external_network` autouse fixture in
``backend/tests/conftest.py` patches
:meth:`socket.socket.connect` to fail any test that
opens a non-loopback socket; the
:func:`fake_providers_for_scan_tests` autouse fixture
in ``backend/tests/test_provider_fakes.py`` replaces
the real provider factories with in-process fakes. A
test that forgets to apply the fakes would trip
:exc:`NetworkAccessBlocked` and fail. Stages 2, 3, 4,
5, 6, 7, and 8 are CPU-bound and make no HTTP calls.

Note on disk effects: the ``frontend:build`` step writes a
production bundle under ``frontend/dist/``. The ``dist/``
directory is gitignored (see the repository
``.gitignore``), so the working tree is not modified in
the eyes of Git, but the bundle is created on disk as a
side effect of the build. To keep the working tree
byte-identical, run the verifier in a temporary clone or
delete ``frontend/dist/`` after the run; the gitignored
status keeps the working tree clean by contract.

Exit status:

- ``0`` — every step passed;
- non-zero — at least one step failed. The failing step is
  printed to stderr with a non-zero step number; the script
  does not continue past a failure (it exits on the first
  failing step so the operator can fix and re-run without
  waiting for the full suite).

Prerequisites:

- Python 3.12 with the backend virtual environment at
  ``backend/.venv`` (``.venv\\Scripts\\python.exe`` on
  Windows);
- Node.js with the frontend dependencies installed
  (``npm install`` at least once);
- A clean working tree (the script does not enforce this; the
  operator is expected to start from a tagged commit).

Usage:

    cd backend
    .venv\\Scripts\\python.exe scripts/verify_release.py

The script is implemented as a thin CLI over the
:func:`build_step_plan` and :func:`run_step` helpers so the
step plan can be unit-tested in isolation. The step plan is
deterministic, uses subprocess argument arrays (no shell
string concatenation), and is the single source of truth for
the documented release verification command.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# Force UTF-8 on the operator's terminal so Unicode
# characters (arrows, em-dashes, etc.) emitted by
# vitest / ruff / pytest do not crash the cp1252
# default codec on Windows.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Project root is two parents up from this file
# (``backend/scripts/verify_release.py`` -> ``backend`` -> ``root``).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"


@dataclass(frozen=True, slots=True)
class Step:
    """A single verification step.

    Attributes:
        label: Short human label, e.g. ``"backend:pytest"``.
        argv: Subprocess argument list (no shell). The list is
            passed to :class:`subprocess.Popen` directly.
        cwd: Working directory for the step.
        timeout_seconds: Maximum wall-clock seconds before the
            step is force-killed. None means no timeout.
    """

    label: str
    argv: tuple[str, ...]
    cwd: Path
    timeout_seconds: int | None = None


def build_step_plan(
    *,
    python_executable: str = ".venv\\Scripts\\python.exe",
    npm_executable: str = "npm.cmd",
) -> tuple[Step, ...]:
    """Return the deterministic release-verification step plan.

    The order matches ``docs/release-checklist.md``. Adding or
    reordering a step requires updating the docs page in the
    same change.
    """
    return (
        # Backend: pytest, ruff check, ruff format --check, pip check
        Step(
            label="backend:pytest",
            argv=(
                python_executable,
                "-m",
                "pytest",
                "tests",
                # The ``tests/test_cli.py`` module covers
                # the v2.1 Part B2 CLI. The module is
                # exercised by the dedicated
                # ``backend:cli-tests`` step below so
                # the cross-platform process-identity
                # tests run with their own bounded
                # timeout. The two stages together cover
                # the full backend suite in default
                # collection order with no manual
                # class-order workarounds.
                "--ignore=tests/test_cli.py",
            ),
            cwd=BACKEND_DIR,
            timeout_seconds=1800,
        ),
        Step(
            label="backend:cli-tests",
            argv=(
                python_executable,
                "-m",
                "pytest",
                # The CLI suite runs in default
                # collection order on every host. The
                # explicit class list and ``-v`` flag
                # historically required to keep the
                # test process from hanging on Windows
                # are no longer necessary: every test
                # isolates its runtime home, the
                # conftest's autouse fixtures clean up
                # after themselves, and the
                # cross-platform process-identity
                # checks use psutil.
                "tests/test_cli.py",
            ),
            cwd=BACKEND_DIR,
            timeout_seconds=600,
        ),
        Step(
            label="backend:ruff-check",
            argv=(
                python_executable,
                "-m",
                "ruff",
                "check",
                "app",
                "tests",
                "scripts",
            ),
            cwd=BACKEND_DIR,
            timeout_seconds=120,
        ),
        Step(
            label="backend:ruff-format",
            argv=(
                python_executable,
                "-m",
                "ruff",
                "format",
                "--check",
                "app",
                "tests",
                "scripts",
            ),
            cwd=BACKEND_DIR,
            timeout_seconds=120,
        ),
        Step(
            label="backend:pip-check",
            argv=(
                python_executable,
                "-m",
                "pip",
                "check",
            ),
            cwd=BACKEND_DIR,
            timeout_seconds=120,
        ),
        # Frontend: vitest, typecheck, lint, build, audit
        Step(
            label="frontend:test",
            argv=(
                npm_executable,
                "test",
                "--",
                "--run",
            ),
            cwd=FRONTEND_DIR,
            timeout_seconds=1800,
        ),
        Step(
            label="frontend:typecheck",
            argv=(
                npm_executable,
                "run",
                "typecheck",
            ),
            cwd=FRONTEND_DIR,
            timeout_seconds=300,
        ),
        Step(
            label="frontend:lint",
            argv=(
                npm_executable,
                "run",
                "lint",
            ),
            cwd=FRONTEND_DIR,
            timeout_seconds=300,
        ),
        Step(
            label="frontend:build",
            argv=(
                npm_executable,
                "run",
                "build",
            ),
            cwd=FRONTEND_DIR,
            timeout_seconds=600,
        ),
        Step(
            label="frontend:audit-omit-dev",
            argv=(
                npm_executable,
                "audit",
                "--omit=dev",
            ),
            cwd=FRONTEND_DIR,
            timeout_seconds=120,
        ),
        Step(
            label="frontend:audit",
            argv=(
                npm_executable,
                "audit",
            ),
            cwd=FRONTEND_DIR,
            timeout_seconds=120,
        ),
    )


@dataclass(frozen=True, slots=True)
class StepResult:
    """The outcome of running a single step."""

    step: Step
    returncode: int
    duration_seconds: float
    timed_out: bool
    stdout_tail: str
    stderr_tail: str


def run_step(step: Step, *, env: Mapping[str, str] | None = None) -> StepResult:
    """Run ``step`` and return the outcome.

    The function uses :class:`subprocess.Popen` with an
    argument list (no shell) and a hard wall-clock timeout.
    The tail of stdout and stderr (last 4 KiB each) is
    captured so the caller can surface it in a concise
    summary without flooding the operator's terminal.
    """
    effective_env: dict[str, str] = dict(os.environ)
    if env:
        effective_env.update(env)
    # Force unbuffered Python output so the tail capture
    # is not silently held in the pipe buffer.
    effective_env.setdefault("PYTHONUNBUFFERED", "1")
    started = time.monotonic()
    timed_out = False
    process = subprocess.Popen(  # noqa: S603 - argv is built by us
        list(step.argv),
        cwd=str(step.cwd),
        env=effective_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = process.communicate(timeout=step.timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        timed_out = True
    duration = time.monotonic() - started
    return StepResult(
        step=step,
        returncode=process.returncode if not timed_out else 124,
        duration_seconds=duration,
        timed_out=timed_out,
        stdout_tail=_tail(stdout),
        stderr_tail=_tail(stderr),
    )


def _tail(text: str, *, limit: int = 4096) -> str:
    """Return at most ``limit`` bytes of ``text`` from the end.

    The function deliberately uses byte length rather than
    character length so a single emoji does not consume the
    whole tail budget.
    """
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return "...(truncated)...\n" + text[-limit:]


def run_step_plan(
    steps: Sequence[Step],
    *,
    env: Mapping[str, str] | None = None,
) -> list[StepResult]:
    """Run every step in order, stopping on the first failure.

    Returns one :class:`StepResult` per executed step. The
    caller iterates the returned list to render a summary.
    """
    results: list[StepResult] = []
    for index, step in enumerate(steps, start=1):
        print(f"[{index}/{len(steps)}] {step.label} ...", flush=True)
        result = run_step(step, env=env)
        results.append(result)
        if result.returncode != 0:
            print(
                f"  FAILED ({result.duration_seconds:.1f}s, "
                f"exit={result.returncode}, "
                f"timed_out={result.timed_out})",
                flush=True,
            )
            if result.stderr_tail:
                print("  --- stderr tail ---", flush=True)
                print(result.stderr_tail, flush=True)
            if result.stdout_tail:
                print("  --- stdout tail ---", flush=True)
                print(result.stdout_tail, flush=True)
            return results
        print(
            f"  OK ({result.duration_seconds:.1f}s)",
            flush=True,
        )
    return results


def render_summary(results: Sequence[StepResult]) -> str:
    """Render a concise summary table of every executed step."""
    lines: list[str] = []
    total_seconds = 0.0
    for result in results:
        status = "OK" if result.returncode == 0 else "FAIL"
        total_seconds += result.duration_seconds
        lines.append(f"  {result.step.label:32s}  {status:4s}  {result.duration_seconds:6.1f}s")
    lines.append("")
    lines.append(f"  total: {total_seconds:.1f}s  steps: {len(results)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the Lockverity v2.0 release verification "
            "suite. The script does not delete files, "
            "does not reset the demo database, does not "
            "call external providers, and does not mutate "
            "tracked repository files. The "
            "``frontend:build`` step writes a production "
            "bundle under ``frontend/dist/``; the directory "
            "is gitignored, so the working tree is unchanged "
            "in the eyes of Git, but the bundle is created "
            "on disk as a bounded side effect of the build. "
            "To keep the working tree byte-identical, run "
            "the verifier in a temporary clone or delete "
            "``frontend/dist/`` after the run."
        )
    )
    parser.add_argument(
        "--python",
        default=".venv\\Scripts\\python.exe",
        help="Python executable to use for backend steps.",
    )
    parser.add_argument(
        "--npm",
        default="npm.cmd",
        help="Node package manager executable for frontend steps.",
    )
    args = parser.parse_args(argv)
    steps = build_step_plan(
        python_executable=args.python,
        npm_executable=args.npm,
    )
    print(
        f"Lockverity v2.0 release verification: {len(steps)} step(s)",
        flush=True,
    )
    print(f"  project root: {PROJECT_ROOT}", flush=True)
    print(f"  backend dir : {BACKEND_DIR}", flush=True)
    print(f"  frontend dir: {FRONTEND_DIR}", flush=True)
    print(flush=True)
    results = run_step_plan(steps)
    print(flush=True)
    print(render_summary(results), flush=True)
    if any(r.returncode != 0 for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
