"""Documentation deny-list check.

The script scans the user-facing active documentation for
known-stale version references and active-private-repository
phrasing. It is run as part of the public-release closure
so a stale active claim cannot silently return.

Active (this script scans):

- ``README.md`` (the current release reference)
- ``SECURITY.md`` (the security policy; mandatory active doc)
- ``CONTRIBUTING.md`` (the contribution policy; mandatory)
- ``RELEASE_NOTES.md`` (the current release notes; the
  current "Status" section is in scope, the historical
  changelog entries are out of scope)
- ``docs/demo-pack.md`` (the 60-second demo script)
- ``docs/demo-walkthrough.md`` (the reviewer walkthrough)
- ``docs/release-checklist.md`` (the release-validation
  checklist)
- ``docs/screenshots.md`` (the manual-capture guide)
- ``docs/orchestration.md`` (the worker / executor config
  table)
- ``docs/security-boundaries.md``, ``docs/provider-honesty.md``,
  ``docs/archive-safety.md``, ``docs/threat-model.md``,
  ``docs/finding-model.md``, ``docs/architecture.md``,
  ``docs/analysis-engine.md`` (the bounded-positioning docs)
- ``frontend/src/pages/AboutPage.tsx`` (the in-app current
  milestone copy)
- ``frontend/src/pages/DemoHomePage.tsx`` (the demo-home
  current-status copy)
- ``.env.example`` (active configuration)

Exempted (this script does NOT scan):

- ``CHANGELOG.md`` (intentional historical release-line
  text; the previous release names must be mentioned by
  design)
- ``backend/var/manual-review/`` (release-closure notes
  and merge-msg files)
- Test files and committed fixtures.

Exemption within a scanned file is restricted to a
narrow marked region. ``RELEASE_NOTES.md`` is the only
file that is partially scanned: the current ``## Status``
section and the per-release notes (e.g. ``**v2.0.5**``)
are in scope; the historical changelog at the bottom
is exempt. The script recognises the boundary by the
``## Historical changelog`` heading if present; in the
absence of an explicit boundary marker, the entire file
is scanned.

Failure: the script exits non-zero with every match so a
stale active claim blocks the release. The output prints
the file, the 1-based line number, the matched rule
description, and the offending text so the operator can
fix the issue without re-running a regex search.

Hardening (v2.0.6 public-closure cycle 2):

- Mandatory active documents that are missing from the
  working tree fail the check (not skipped).
- Pattern matching is case-insensitive; whitespace is
  normalised before the regex fires (tabs and multiple
  spaces are folded to a single space) so a copy-paste
  with subtle whitespace cannot defeat the rule.
- The active-private / private-repo / private-portfolio
  family is matched as a class: ``private portfolio``,
  ``currently private``, ``remains private``, ``keep
  private``, ``is a private`` and the standalone
  ``private repository`` (only in non-historical
  contexts).
- Stale active version headings (e.g. ``What v2.0.5
  does not include`` in the active docs) are matched.
- Maintainer-specific filesystem paths (``C:\\Users\\Naman
  Parikh`` and similar) are matched; the rule fires
  anywhere in a scanned file.
- Placeholder security contacts
  (``security@lockverity.example`` and the like) are
  matched in active docs.
- Old current-version API responses (e.g. a
  ``"version": "1.6.1"`` literal) are matched in the
  active README and demo-walkthrough.
- Removed runtime configuration knobs
  (``LOCKVERITY_GITHUB_API_URL``) are matched in
  active files.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MANDATORY_ACTIVE_DOCS: tuple[Path, ...] = (
    Path("README.md"),
    Path("SECURITY.md"),
    Path("CONTRIBUTING.md"),
    Path("RELEASE_NOTES.md"),
    Path(".env.example"),
    Path("docs/demo-pack.md"),
    Path("docs/demo-walkthrough.md"),
    Path("docs/release-checklist.md"),
    Path("docs/screenshots.md"),
    Path("docs/orchestration.md"),
    Path("docs/security-boundaries.md"),
    Path("docs/provider-honesty.md"),
    Path("docs/archive-safety.md"),
    Path("docs/threat-model.md"),
    Path("docs/finding-model.md"),
    Path("docs/architecture.md"),
    Path("docs/analysis-engine.md"),
    Path("frontend/src/pages/AboutPage.tsx"),
    Path("frontend/src/pages/DemoHomePage.tsx"),
)


def _historical_changelog_exempt(path: Path) -> bool:
    """Return ``True`` if ``path`` is a wholly-historical doc.

    The only such file is ``CHANGELOG.md``; the rule is
    centralised here so the deny-list body remains a
    pure data table.
    """
    return path.name == "CHANGELOG.md"


# Active-claim deny-list. A match is a stale active claim
# that blocks the release. The pattern is a precompiled
# :class:`re.Pattern` and ``re.IGNORECASE`` is applied
# at match time; whitespace normalisation happens before
# the regex is applied, so a rule does not need to spell
# out every spacing variant.
#
# Each entry is ``(pattern, description)``. The pattern
# is a *raw* regular expression. Substring matches are
# anchored to the normalised text.
DENY_LIST: tuple[tuple[str, str], ...] = (
    # --- Stale active version headings -----------------------------
    # The README / About / demo-pack / demo-walkthrough must
    # not have a "What v1.x does not include" / "What v2.0.5
    # does not include" / "What v0.1 implements today"
    # section in the active copy.
    (
        r"what v1\.0 implements today",
        "About page v1.0 milestone header (stale active copy)",
    ),
    (
        r"what v1\.0 does not include",
        "About page v1.0 'does not include' header (stale active copy)",
    ),
    (
        r"what v0\.1 includes",
        "About page v0.1 'includes' header (stale active copy)",
    ),
    (
        r"what v0\.1 does not include",
        "About page v0.1 'does not include' header (stale active copy)",
    ),
    (
        r"what v2\.0\.5 does not include",
        "active 'What v2.0.5 does not include' header (superseded by v2.0.6)",
    ),
    (
        r"what v1\.3 does not include",
        "active 'What v1.3 does not include' header (superseded by v2.0.6)",
    ),
    (
        r"what v1\.4 does not include",
        "active 'What v1.4 does not include' header (superseded by v2.0.6)",
    ),
    (
        r"what v1\.4\.0 does not include",
        "active 'What v1.4.0 does not include' header (superseded by v2.0.6)",
    ),
    (
        r"what v1\.2 does not include",
        "active 'What v1.2 does not include' header (superseded by v2.0.6)",
    ),
    (
        r"what v1\.2\.1 does not include",
        "active 'What v1.2.1 does not include' header (superseded by v2.0.6)",
    ),
    # Screenshot title / demo-walkthrough / demo-pack
    # version headers must reference v2.0.6.
    (
        r"# Lockverity v1\.3 — Screenshot Checklist",
        "screenshots.md v1.3 title (must be v2.0.6)",
    ),
    (
        r"# Lockverity v1\.2 demo walkthrough",
        "demo-walkthrough.md v1.2 heading (must be v2.0.6)",
    ),
    (
        r"# Lockverity v1\.4 demo walkthrough",
        "demo-walkthrough.md v1.4 heading (must be v2.0.6)",
    ),
    (
        r"the v1\.3 release ships a screenshot",
        "README v1.3 screenshot ships line (must reference v2.0.6)",
    ),
    # --- Old current-version API responses ------------------------
    (
        r'"version":\s*"1\.6\.1"',
        "README v1.6.1 example version (current is 2.0.6)",
    ),
    (
        r"version=1\.6\.1",
        "README v1.6.1 example version (bash form)",
    ),
    (
        r"version[\"']?\s*[:=]\s*[\"']?1\.6\.1",
        "active docs v1.6.1 example version",
    ),
    # --- Active private-repository / private-portfolio wording ---
    # The codebase is suitable for publication but the
    # visibility change is the operator's call (via
    # ``gh repo edit --visibility``). The active copy
    # must not assert a "private" posture.
    (
        r"private\s+portfolio",
        "active 'private portfolio' wording (use local-first, portfolio-ready)",
    ),
    (
        r"private\s+portfolio-ready",
        "active 'private portfolio-ready' wording (use local-first, portfolio-ready)",
    ),
    (
        r"private\s+portfolio\s+baseline",
        "active 'private portfolio baseline' wording (use local-first baseline)",
    ),
    (
        r"is\s+a\s+private\s+portfolio",
        "active 'is a private portfolio' phrasing (use local-first, portfolio-ready)",
    ),
    (
        r"currently\s+private",
        "active 'currently private' wording (use local-first baseline)",
    ),
    (
        r"remains\s+private",
        "active 'remains private' wording (use local-first baseline)",
    ),
    (
        r"keep\s+(?:the\s+)?repository\s+private",
        "active 'keep the repository private' wording (use local-first baseline)",
    ),
    (
        r"the\s+repository\s+remains\s+private",
        "active 'the repository remains private' wording (use local-first baseline)",
    ),
    (
        r"the\s+repository\s+is\s+private",
        "active 'the repository is private' wording (use local-first baseline)",
    ),
    (
        r"the\s+repository\s+stays\s+private",
        "active 'the repository stays private' wording (use local-first baseline)",
    ),
    # --- Stale SECURITY.md wording ---------------------------------
    # The ``Until v1.0`` phrasing pre-dates the v2.0 release
    # line and must be replaced with the v2.0-specific
    # milestone framing.
    (
        r"until\s+`?v1\.0`?",
        "SECURITY.md 'Until v1.0' phrasing (must be v2.0 milestone framing)",
    ),
    # --- Placeholder security contacts ----------------------------
    # The old placeholder address is replaced with the
    # GitHub Security Advisories URL. A reappearance is a
    # regression.
    (
        r"security@lockverity\.example",
        "placeholder security contact (use GitHub Security Advisories URL)",
    ),
    (
        r"security@lockverity",
        "placeholder security contact (use GitHub Security Advisories URL)",
    ),
    # --- Maintainer-specific filesystem paths ---------------------
    # The maintainer's local home directory must never
    # appear in active docs. The pattern matches the
    # Windows-specific path shape that the maintainer's
    # local environment produces.
    (
        r"c:\\users\\naman\s+parikh",
        "maintainer-specific C:\\Users\\Naman Parikh path (strip)",
    ),
    (
        r"c:\\users\\namanparikh",
        "maintainer-specific C:\\Users\\NamanParikh path (strip)",
    ),
    (
        r"/Users/naman",
        "maintainer-specific /Users/naman POSIX path (strip)",
    ),
    (
        r"minimax\s+projects",
        "maintainer-specific 'Minimax Projects' parent directory (strip)",
    ),
    # --- Removed runtime configuration knobs ----------------------
    # ``LOCKVERITY_GITHUB_API_URL`` was removed in the
    # v2.0.6 public-closure cycle. Active configuration
    # and active comments must not reference it. A
    # historical changelog mention is allowed only when
    # it is in a clearly-historical section (handled by
    # the ``RELEASE_NOTES.md`` partial-scan logic below).
    (
        r"LOCKVERITY_GITHUB_API_URL",
        "removed LOCKVERITY_GITHUB_API_URL reference (use canonical host)",
    ),
    # --- CSV / JSON determinism contract ------------------------
    # The public CSV header is ``exported_at=`` (the
    # historical name). The v2.0.5 cycle 6 pass
    # incorrectly renamed it to ``fetched_at=``; an
    # active doc that claims ``fetched_at=`` is the
    # contract is stale. The findings JSON schema keeps
    # its own field name (the JSON response object uses
    # ``fetched_at`` as the operation-timestamp field;
    # the CSV-level public name is ``exported_at``).
    (
        r"\bcsv[^.\n]{0,40}fetched_at\s*=",
        "active CSV 'fetched_at=' header (must be 'exported_at=')",
    ),
    # --- React Router version pin ---------------------------------
    # The cycle 6 active docs named 7.18.1. The cycle
    # 7 dependency migration moved to the
    # ``react-router@8.3.0`` direct package; the
    # ``react-router-dom@6.x`` line is the legacy
    # cycle 1-5 reference and an active mention is
    # stale.
    (
        r"react-router-dom@6\.",
        "active react-router-dom 6.x pin (must be react-router 8.3.0)",
    ),
    # --- "Current version" / "Current release" / "What vX does not include"
    # The active copy must point to v2.0.6 (or the v2.0
    # release line in general). A specific older
    # version in the "current" position is a stale
    # active claim. The rule matches the literal
    # string after ``current version is`` /
    # ``current release is`` / ``current milestone``
    # phrases; an older version other than 2.0.6
    # (e.g. v2.0.5, v2.0.3, v1.x) fires the rule.
    (
        r"current\s+(?:version|release|milestone)\s+is\s+(?:v?2\.0\.[0-5]|v?1\.[0-9]+|v?0\.[0-9]+)\b",
        "active 'current version/release is vX.Y' must reference v2.0.6",
    ),
    # A bare ``Current milestone (vX.Y)`` heading or
    # a ``Current version: vX.Y`` field is stale when
    # the version is not v2.0.6. The rule matches the
    # version after a colon / em-dash / paren.
    (
        r"current\s+(?:version|release|milestone)\s*[:\-(]\s*v?(?:2\.0\.[0-5]|1\.[0-9]+|0\.[0-9]+)\b",
        "active 'current milestone (vX.Y)' must reference v2.0.6",
    ),
    # Arbitrary "What vX.Y does not include" / "What vX.Y
    # implements today" / "What vX.Y includes" headings
    # that do not match v2.0.6 are stale active copy.
    (
        r"what\s+v(?:2\.0\.[0-5]|1\.[0-9]+|0\.[0-9]+)\s+(?:implements|does\s+not\s+include|includes)\b",
        "active 'What vX.Y does not include / implements / includes' must reference v2.0.6",
    ),
    # --- v1.x demo / v1.x dataset / v1.x walkthrough in active copy
    (
        r"v1\.\d(?:\.\d)?\s+(?:demo|dataset|walkthrough|milestone)\b",
        "active 'v1.X demo/dataset/walkthrough' (must reference v2.0.6)",
    ),
    # --- "must remain private" / "is private" / "is a private"
    (
        r"repository\s+must\s+remain\s+private",
        "active 'repository must remain private' wording (use local-first baseline)",
    ),
    (
        r"repository\s+is\s+private",
        "active 'repository is private' wording (use local-first baseline)",
    ),
    (
        r"is\s+a\s+private\s+repository",
        "active 'is a private repository' phrasing",
    ),
    # --- Phase 1 public-closure release-blocking wording
    # The active checklist must not assert the closure
    # cycle is "in progress" or "pending" or "blocked";
    # the v2.0.6 candidate is a release candidate, not
    # an in-flight cycle. The rule matches the literal
    # "in progress" / "pending" / "blocked" within
    # ~20 characters after "public-release closure".
    (
        r"public-release\s+closure\s+(?:is\s+)?(?:in\s+progress|pending|blocked|not\s+yet\s+complete)\b",
        "active 'public-release closure in progress' wording (the v2.0.6 candidate is final)",
    ),
    # --- Runtime contract: Node.js >=22.22.0 floor
    # ``react-router@8.3.0`` requires Node >=22.22.0.
    # The active docs must not advertise a lower
    # minimum. The rule matches the old, pre-React
    # Router 8 phrasing (``Node.js 20 or 22``,
    # ``Node 20+``) and the looser ``Node 22``
    # without the 22.22.0 qualifier. The exact
    # ``Node.js >=22.22.0`` form is allowed; the
    # historical changelog is exempt via the standard
    # ``RELEASE_NOTES.md`` partial-scan logic.
    (
        r"node\.?js\s+20\s+or\s+22",
        "active 'Node.js 20 or 22' wording (must be 'Node.js >=22.22.0')",
    ),
    (
        r"node\.?js\s+20(?!\.|[0-9])",
        "active 'Node.js 20' (no qualifier) wording (must be 'Node.js >=22.22.0')",
    ),
    (
        r"\bnode\s+20\+\b",
        "active 'Node 20+' wording (must be 'Node.js >=22.22.0')",
    ),
    # ``Node 22`` without the 22.22.0 floor is too
    # loose; the rule matches the standalone form
    # only when the surrounding context does not
    # already include the 22.22 qualifier. The
    # negative lookahead rules out the precise
    # ``>=22.22.0`` shape (and ``Node.js 22.22.0+``).
    (
        r"(?<![\d.])(?:node\.?js\s+22|node\s+22)(?![\d.])",
        "active 'Node.js 22' (no 22.22 qualifier) wording (must be 'Node.js >=22.22.0')",
    ),
)


def _normalise_text(text: str) -> str:
    """Return ``text`` with whitespace folded and case-folded.

    The deny-list rules are applied to the normalised
    text so a copy-paste with a different tab / space
    ratio cannot defeat the rule. The normalisation is
    intentionally aggressive: every run of horizontal
    whitespace (``[ \t]+``) within a line is collapsed
    to a single space, and lines are joined with a
    single newline. Unicode case-folding is delegated
    to ``re.IGNORECASE``.
    """
    out = text.replace("\r\n", "\n").replace("\r", "\n")
    out = "\n".join(re.sub(r"[ \t]+", " ", line) for line in out.split("\n"))
    return out


def _scan_with_partial_exemption(
    *,
    rel_path: Path,
    text: str,
) -> tuple[list[tuple[str, str, int, str]], str]:
    """Apply the deny-list to ``text``; return ``(failures, scanned_text)``.

    For files with a marked historical region
    (``RELEASE_NOTES.md`` after a ``## Historical
    changelog`` heading), only the prefix up to the
    boundary is scanned. For other files the whole text
    is scanned.
    """
    if rel_path.name == "RELEASE_NOTES.md":
        # The historical changelog at the bottom of
        # ``RELEASE_NOTES.md`` is exempt by design.
        # The boundary is honoured only when it appears
        # at line 200 or later. A heading at the top of
        # the file would otherwise let an active doc
        # silently hide its content behind a single
        # marker; the ``200`` threshold is a defensive
        # floor that ensures the heading sits well into
        # the file (where a real transition from active
        # copy to a historical changelog would appear).
        boundary = text.find("## Historical changelog")
        if boundary >= 0:
            line_before = text.count("\n", 0, boundary) + 1
            if line_before >= 200:
                scanned = text[:boundary]
                return _apply_deny_list(rel_path, scanned), scanned
            # Boundary is too early; the whole file is
            # treated as active and scanned.
    return _apply_deny_list(rel_path, text), text


def _apply_deny_list(
    rel_path: Path,
    text: str,
) -> list[tuple[str, str, int, str]]:
    """Apply every deny-list pattern to ``text`` and return the failures.

    A failure is a 4-tuple ``(rel_path, description,
    line_no, matched)``. The line number is the
    1-based line in the original (un-normalised) text;
    the normalisation does not change the line count
    (whitespace within a line is folded, not removed),
    so the line number in the normalised text maps
    directly to the same line in the original.
    """
    failures: list[tuple[str, str, int, str]] = []
    normalised = _normalise_text(text)
    for pattern, description in DENY_LIST:
        compiled = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        for match in compiled.finditer(normalised):
            line_no = normalised.count("\n", 0, match.start()) + 1
            failures.append(
                (
                    str(rel_path),
                    description,
                    line_no,
                    match.group(0),
                )
            )
    return failures


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    failures: list[tuple[str, str, int, str]] = []
    missing_mandatory: list[Path] = []
    for rel_path in MANDATORY_ACTIVE_DOCS:
        path = repo_root / rel_path
        if not path.exists():
            missing_mandatory.append(rel_path)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _historical_changelog_exempt(rel_path):
            continue
        local_failures, _ = _scan_with_partial_exemption(rel_path=rel_path, text=text)
        failures.extend(local_failures)
    if missing_mandatory:
        print(
            "Documentation deny-list check FAILED: missing mandatory docs:",
            file=sys.stderr,
        )
        for rel_path in missing_mandatory:
            print(f"  MISSING: {rel_path}", file=sys.stderr)
    if failures:
        print(
            "Documentation deny-list check FAILED:",
            file=sys.stderr,
        )
        for rel_path, description, line_no, matched in failures:
            print(
                f"  {rel_path}:{line_no} [{description}]: {matched!r}",
                file=sys.stderr,
            )
        return 1
    # Positive checks: the active docs and source code
    # must agree on the current application version and
    # the current React Router version. These checks
    # complement the deny-list above: the deny-list blocks
    # stale *text*; the positive checks block stale
    # *metadata* (the published package version and the
    # installed dependency tree).
    positive_failures = _check_positive_versions(repo_root)
    if positive_failures:
        print(
            "Documentation positive-version check FAILED:",
            file=sys.stderr,
        )
        for description, expected, actual in positive_failures:
            print(
                f"  [{description}]: expected {expected!r}, found {actual!r}",
                file=sys.stderr,
            )
        return 1
    # Positive checks: an active doc must not reference a
    # config file that has been retired. The cycle-7
    # ESLint migration retired ``frontend/.eslintrc.cjs``
    # in favour of ``frontend/eslint.config.js``; any
    # active mention of the legacy file is a stale claim.
    config_failures = _check_no_legacy_config_references(repo_root)
    if config_failures:
        print(
            "Documentation positive-config check FAILED:",
            file=sys.stderr,
        )
        for rel_path, line_no, matched in config_failures:
            print(
                f"  {rel_path}:{line_no}: references retired config '{matched}'",
                file=sys.stderr,
            )
        return 1
    if missing_mandatory:
        return 1
    print("Documentation deny-list check OK: no stale active claims found.")
    return 0


def _read_application_version(repo_root: Path) -> tuple[str, ...]:
    """Return the application version strings, in priority order.

    Reads the canonical ``backend/app/_version.py`` and
    the fallback ``backend/app/__init__.py`` ``__version__``
    module attribute. The frontend exposes the same value
    through the ``version_about`` test (see
    ``backend/tests/test_version.py``); the script does
    not import the frontend test runner here because the
    active-docs check is intended to be fast and
    self-contained.
    """
    candidates: list[str] = []
    version_file = repo_root / "backend" / "app" / "_version.py"
    if version_file.exists():
        text = version_file.read_text(encoding="utf-8", errors="replace")
        match = re.search(
            r"^__version__\s*=\s*[\"']([^\"']+)[\"']",
            text,
            flags=re.MULTILINE,
        )
        if match:
            candidates.append(match.group(1))
    init_file = repo_root / "backend" / "app" / "__init__.py"
    if init_file.exists():
        text = init_file.read_text(encoding="utf-8", errors="replace")
        match = re.search(
            r"^__version__\s*=\s*[\"']([^\"']+)[\"']",
            text,
            flags=re.MULTILINE,
        )
        if match:
            candidates.append(match.group(1))
    return tuple(candidates)


def _read_router_version(repo_root: Path) -> str | None:
    """Return the installed ``react-router`` version, or ``None``.

    Reads ``frontend/package.json`` (declared version).
    The package-lock is the runtime source of truth but
    it is large and versionally noisy; the declared
    version in ``package.json`` is the contract.
    """
    package_json = repo_root / "frontend" / "package.json"
    if not package_json.exists():
        return None
    try:
        data = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None
    deps = data.get("dependencies") or {}
    if "react-router" in deps:
        return str(deps["react-router"]).lstrip("^~=")
    return None


def _check_positive_versions(repo_root: Path) -> list[tuple[str, str, str]]:
    """Return a list of ``(description, expected, actual)`` triples.

    A non-empty list means at least one positive check
    failed. The ``expected`` value is the canonical
    authoritative source; the ``actual`` value is what
    the check found.
    """
    failures: list[tuple[str, str, str]] = []
    # 1. Application version: every reference in the
    # mandatory active docs must match the canonical
    # ``_version.py`` value. We intentionally keep this
    # narrow: only the active docs we already scan are
    # included, and the regex is constrained to
    # ``v<digits>.<digits>.<digits>`` so we do not
    # over-match.
    app_versions = _read_application_version(repo_root)
    if app_versions:
        canonical = app_versions[0]
        # The positive version check is intentionally
        # narrow: only docs whose primary content IS the
        # current version statement are checked. Other
        # active docs may reference historical versions in
        # narrative text without firing the rule.
        version_centric_docs = (
            Path("README.md"),
            Path("frontend/src/pages/AboutPage.tsx"),
            Path("frontend/src/pages/DemoHomePage.tsx"),
        )
        for rel_path in version_centric_docs:
            path = repo_root / rel_path
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            # Find the ``## Current milestone`` (or
            # ``Current version``) section. The TSX pages
            # do not use ``##`` headings; they use
            # component-text headers that the section
            # detector would miss. The TSX check therefore
            # falls back to scanning the first 200 lines
            # for the canonical version string.
            section_start = _find_current_milestone_section(text)
            if section_start is not None:
                section_end = _find_next_section_start(text, section_start + 1)
                section_text = text[
                    section_start : section_end if section_end is not None else None
                ]
            else:
                # TSX fallback: check the first 200 lines.
                section_text = "\n".join(text.splitlines()[:200])
            match = re.search(
                r"v(\d+\.\d+\.\d+)",
                section_text,
            )
            if not match:
                failures.append(
                    (
                        f"active doc {rel_path!s} has no vX.Y.Z version reference",
                        f"v{canonical}",
                        "(missing)",
                    )
                )
                continue
            # The "current" version is the FIRST vX.Y.Z
            # reference in the section (closest to the
            # current-version / current-milestone marker).
            # Later references in narrative text (e.g.
            # historical changelog narrative ``v1.0.1
            # was a public-readiness pass``) are
            # intentionally ignored: they are
            # version-history context, not a current
            # version claim. The positive check is
            # therefore deliberately conservative: it
            # only fires on the version claim that opens
            # the section.
            found = match.group(1)
            if found != canonical:
                failures.append(
                    (
                        f"active doc {rel_path!s} version reference is stale",
                        f"v{canonical}",
                        f"v{found}",
                    )
                )
    # 2. React Router version: every mandatory active
    # doc that names React Router must name the installed
    # version (``react-router@8.3.0`` is the current pin;
    # ``react-router-dom@6.x`` or ``react-router@7.18.1``
    # are stale). The deny-list above already bans
    # ``react-router-dom@6.``; this positive check
    # verifies that the documented version matches
    # ``frontend/package.json``.
    router = _read_router_version(repo_root)
    if router:
        canonical_router = f"react-router@{router}"
        for rel_path in MANDATORY_ACTIVE_DOCS:
            path = repo_root / rel_path
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(
                r"react-router(?:[- ]?dom)?@(\d+\.\d+\.\d+)",
                text,
            ):
                found = match.group(0)
                expected = canonical_router
                if found != expected and not found.endswith(
                    "@" + router,
                ):
                    failures.append(
                        (
                            f"active doc {rel_path!s} pins React Router at {found!r}",
                            expected,
                            found,
                        )
                    )
    return failures


def _is_in_historical_block(text: str, offset: int) -> bool:
    """Return True if ``offset`` is inside a historical changelog block."""
    lower = text.lower()
    historical_idx = lower.rfind("## historical changelog")
    if historical_idx < 0:
        return False
    return offset > historical_idx


def _find_current_milestone_section(text: str) -> int | None:
    """Return the offset of the ``## Current milestone`` section.

    Accepts the variants ``## Current milestone`` and
    ``## Current version``. Returns ``None`` if no such
    section exists.
    """
    for match in re.finditer(
        r"^##\s+(?:current milestone|current version|current release|milestone)\b",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    ):
        return match.start()
    return None


def _find_next_section_start(text: str, start: int) -> int | None:
    """Return the offset of the next ``## `` heading after ``start``."""
    match = re.search(
        r"^##\s+",
        text[start:],
        flags=re.MULTILINE,
    )
    if match is None:
        return None
    return start + match.start()


def _check_no_legacy_config_references(
    repo_root: Path,
) -> list[tuple[Path, int, str]]:
    """Return a list of ``(rel_path, line_no, matched_token)`` triples.

    An active doc must not reference a configuration file
    that has been retired. The cycle-7 ESLint migration
    retired ``frontend/.eslintrc.cjs``; any active mention
    is a stale claim. Other legacy config filenames
    (``.eslintrc``, ``.eslintrc.js``) are also rejected
    so a future re-introduction does not silently drift
    the active docs.
    """
    legacy_config_names: tuple[str, ...] = (
        ".eslintrc",
        ".eslintrc.js",
        ".eslintrc.cjs",
        ".eslintrc.yaml",
        ".eslintrc.yml",
        ".eslintrc.json",
    )
    failures: list[tuple[Path, int, str]] = []
    for rel_path in MANDATORY_ACTIVE_DOCS:
        path = repo_root / rel_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _historical_changelog_exempt(rel_path):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for legacy_name in legacy_config_names:
                if legacy_name in line:
                    failures.append((rel_path, line_no, legacy_name))
    return failures


if __name__ == "__main__":
    sys.exit(main())
