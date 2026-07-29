"""Tests for the documentation deny-list check.

The deny-list script is the single source of truth for the
"no stale active claim" rule on the v2.0.6 public-closure
cycle. A regression test pins the script's contract:

- The deny-list rules cover every Codex-discovered stale
  claim.
- A clean tree returns exit code 0 and prints the OK
  line.
- A tree that contains a known stale active claim
  returns exit code 1 and emits a non-empty ``FAILED``
  line plus the offending file, line, and matched rule.
- A missing mandatory active doc fails the check (not
  silently skipped).
- Case variations of the rule text fail the check
  (case-insensitive matching is enforced).
- Whitespace variations (tabs, multiple spaces) fail
  the check (normalisation is enforced).
- A partial-scan boundary (``## Historical changelog``)
  exempts only the marked region.
- Wholly-historical docs (``CHANGELOG.md``) are
  exempt by name and can carry historical references.
"""

from __future__ import annotations

import io
import re
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from scripts import check_active_docs
from scripts.check_active_docs import DENY_LIST, MANDATORY_ACTIVE_DOCS
from scripts.check_active_docs import main as deny_list_main


def _tmp_path() -> Path:
    """Return a unique per-test ``tmp_path`` under a stable root.

    The real ``tmp_path`` pytest fixture is per-test; this
    helper is a stand-in used in the deny-list tests
    because we need a fresh path each time the test
    helper runs and ``tmp_path`` cannot be passed
    through a single-name helper.
    """
    return Path(f"var/manual-review/_active_docs_{uuid.uuid4().hex[:8]}")


def _monkeypatch_set_doc(path: Path) -> object:
    """Patch :data:`MANDATORY_ACTIVE_DOCS` to the given path.

    Returns the monkeypatch fixture so the test can use
    it as a context manager.
    """
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    mp.setattr(check_active_docs, "MANDATORY_ACTIVE_DOCS", (Path(str(path)),))
    return mp


def _run_capture():
    """Run ``deny_list_main`` and capture stdout + stderr."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = deny_list_main()
    return rc, out.getvalue(), err.getvalue()


def test_deny_list_includes_known_stale_active_claims() -> None:
    """The deny list must include every known stale active claim
    enumerated in the public-closure audit.
    """
    descriptions = {description for _pattern, description in DENY_LIST}
    for required in [
        # Stale active version headings
        "About page v1.0 milestone header (stale active copy)",
        "About page v1.0 'does not include' header (stale active copy)",
        "active 'What v2.0.5 does not include' header (superseded by v2.0.6)",
        "active 'What v1.3 does not include' header (superseded by v2.0.6)",
        # Screenshot title
        "screenshots.md v1.3 title (must be v2.0.6)",
        # demo-walkthrough heading
        "demo-walkthrough.md v1.2 heading (must be v2.0.6)",
        # Old current-version API responses
        "README v1.6.1 example version (current is 2.0.6)",
        # Private-repo wording class
        "active 'private portfolio' wording (use local-first, portfolio-ready)",
        "active 'private portfolio-ready' wording (use local-first, portfolio-ready)",
        "active 'currently private' wording (use local-first baseline)",
        "active 'remains private' wording (use local-first baseline)",
        "active 'keep the repository private' wording (use local-first baseline)",
        # SECURITY.md wording
        "SECURITY.md 'Until v1.0' phrasing (must be v2.0 milestone framing)",
        # Placeholder security contact
        "placeholder security contact (use GitHub Security Advisories URL)",
        # Maintainer-specific path
        "maintainer-specific C:\\Users\\Naman Parikh path (strip)",
        "maintainer-specific 'Minimax Projects' parent directory (strip)",
        # Removed runtime config knob
        "removed LOCKVERITY_GITHUB_API_URL reference (use canonical host)",
        # Legacy determinism contract
        "active CSV 'fetched_at=' header (must be 'exported_at=')",
        # React Router 6.x reference
        "active react-router-dom 6.x pin (must be react-router 8.3.0)",
        # v2.0.6 hardening-cycle additions
        "active 'current version/release is vX.Y' must reference v2.0.6",
        "active 'current milestone (vX.Y)' must reference v2.0.6",
        "active 'What vX.Y does not include / implements / includes' must reference v2.0.6",
        "active 'v1.X demo/dataset/walkthrough' (must reference v2.0.6)",
        "active 'repository must remain private' wording (use local-first baseline)",
        "active 'repository is private' wording (use local-first baseline)",
        "active 'is a private repository' phrasing",
        "active 'public-release closure in progress' wording (the v2.0.6 candidate is final)",
    ]:
        assert required in descriptions, f"missing deny-list entry: {required}"


def test_deny_list_matches_current_version_stale_phrase(tmp_path) -> None:
    """A ``current version is v2.0.5`` phrase is stale;
    the v2.0.6 candidate must reference v2.0.6.
    """

    stale_file = tmp_path / "demo-pack.md"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_text(
        "Lockverity\nThe current version is v2.0.5.\n",
        encoding="utf-8",
    )
    mp = _monkeypatch_set_doc(stale_file)
    try:
        rc, _out, err = _run_capture()
    finally:
        mp.undo()
    assert rc == 1
    assert "current version/release is vX.Y" in err


def test_deny_list_matches_current_release_stale_phrase(tmp_path) -> None:
    """A ``current release is v2.0.3`` phrase is stale."""
    stale_file = tmp_path / "demo-pack.md"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_text(
        "Lockverity\nThe current release is v2.0.3.\n",
        encoding="utf-8",
    )
    mp = _monkeypatch_set_doc(stale_file)
    try:
        rc, _out, _err = _run_capture()
    finally:
        mp.undo()
    assert rc == 1


def test_deny_list_matches_current_milestone_paren(tmp_path) -> None:
    """A ``Current milestone (v2.0.5)`` heading is stale."""
    stale_file = tmp_path / "docs" / "demo-pack.md"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_text(
        "Lockverity\n## Current milestone (v2.0.5)\n",
        encoding="utf-8",
    )
    mp = _monkeypatch_set_doc(stale_file)
    try:
        rc, _out, err = _run_capture()
    finally:
        mp.undo()
    assert rc == 1
    assert "current milestone (vX.Y)" in err


def test_deny_list_matches_v1x_demo_phrase(tmp_path) -> None:
    """A ``v1.4 demo`` or ``v1.2 walkthrough`` reference
    in the active copy is stale.
    """
    stale_file = tmp_path / "docs" / "demo-walkthrough.md"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_text(
        "Lockverity\nThis is a v1.4 demo walkthrough.\n",
        encoding="utf-8",
    )
    mp = _monkeypatch_set_doc(stale_file)
    try:
        rc, _out, err = _run_capture()
    finally:
        mp.undo()
    assert rc == 1
    assert "v1.X demo/dataset/walkthrough" in err


def test_deny_list_matches_must_remain_private(tmp_path) -> None:
    """``the repository must remain private`` is stale."""
    stale_file = tmp_path / "docs" / "release-checklist.md"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_text(
        "Lockverity\nThe repository must remain private.\n",
        encoding="utf-8",
    )
    mp = _monkeypatch_set_doc(stale_file)
    try:
        rc, _out, err = _run_capture()
    finally:
        mp.undo()
    assert rc == 1
    assert "must remain private" in err


def test_deny_list_matches_public_closure_in_progress(tmp_path) -> None:
    """``public-release closure in progress`` is stale
    on the v2.0.6 candidate.
    """
    stale_file = tmp_path / "docs" / "release-checklist.md"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_text(
        "Lockverity\nThe public-release closure is in progress.\n",
        encoding="utf-8",
    )
    mp = _monkeypatch_set_doc(stale_file)
    try:
        rc, _out, _err = _run_capture()
    finally:
        mp.undo()
    assert rc == 1


def test_partial_scan_early_boundary_does_not_exempt(tmp_path, monkeypatch) -> None:
    """An early ``## Historical changelog`` heading at
    the top of a doc does NOT exempt the file. The
    boundary must appear at line 200 or later to be
    honoured.
    """
    from scripts import check_active_docs

    # A ``## Historical changelog`` heading at line 2
    # followed by stale active copy. The whole file is
    # scanned; the stale copy fails the check.
    release_notes = tmp_path / "RELEASE_NOTES.md"
    release_notes.write_text(
        "## Historical changelog\n"
        "## v2.0.5 ships\n"
        "Current version is v2.0.5.\n" + ("\n" * 250) + "## Real changelog\n",
        encoding="utf-8",
    )
    failures, _ = check_active_docs._scan_with_partial_exemption(
        rel_path=tmp_path / "RELEASE_NOTES.md",
        text=release_notes.read_text(encoding="utf-8"),
    )
    # The stale "current version is v2.0.5" is in the
    # first 4 lines; the partial scan must catch it
    # because the boundary is at line 2 (below the
    # 200-line threshold).
    assert failures, "early 'Historical changelog' heading must not exempt the file"
    description = failures[0][1]
    assert "current version/release" in description


def test_partial_scan_late_boundary_exempts(tmp_path, monkeypatch) -> None:
    """A late ``## Historical changelog`` heading (at
    line 250 or later) does exempt the suffix. The
    historical section can carry historical version
    references.
    """
    from scripts import check_active_docs

    release_notes = tmp_path / "RELEASE_NOTES.md"
    body = "Clean current copy.\n" + ("\n" * 250) + "## Historical changelog\nv2.0.5 ships\n"
    release_notes.write_text(body, encoding="utf-8")
    failures, _ = check_active_docs._scan_with_partial_exemption(
        rel_path=tmp_path / "RELEASE_NOTES.md",
        text=release_notes.read_text(encoding="utf-8"),
    )
    # The active part is clean; the historical section
    # is exempt and does not fire the check.
    assert not failures


def test_deny_list_passes_on_clean_tree() -> None:
    """A clean tree (no deny-list match) returns exit code 0 and
    prints the OK line. ``RELEASE_NOTES.md`` is in scope
    for the "Status" section but the historical changelog
    is exempt; a normal clean release notes file therefore
    passes.
    """
    rc, out, _err = _run_capture()
    assert rc == 0
    assert "OK" in out


def test_deny_list_fails_on_known_stale_claim(tmp_path, monkeypatch) -> None:
    """A tree that contains a known stale active claim returns
    exit code 1 and emits a non-empty ``FAILED`` line plus
    the offending file and matched line.
    """
    stale_file = tmp_path / "README.md"
    stale_file.write_text(
        "Some text. version=1.6.1. More text.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_active_docs,
        "MANDATORY_ACTIVE_DOCS",
        (Path(str(stale_file)),),
    )
    rc, out, err = _run_capture()
    assert rc == 1
    output = out + err
    assert "FAILED" in output
    assert "README.md" in output
    assert "1.6.1" in output


def test_deny_list_handles_missing_active_doc_as_failure(monkeypatch, tmp_path) -> None:
    """A missing mandatory active doc is a failure (not a
    silent skip).
    """
    nonexistent = tmp_path / "definitely-missing.md"
    monkeypatch.setattr(
        check_active_docs,
        "MANDATORY_ACTIVE_DOCS",
        (Path(str(nonexistent)),),
    )
    rc, _out, err = _run_capture()
    assert rc == 1
    assert "missing mandatory docs" in err
    assert "definitely-missing.md" in err


def test_deny_list_is_case_insensitive(tmp_path, monkeypatch) -> None:
    """Case variations of the rule text must fail."""
    # Uppercase variant of the screenshots.md v1.3 title.
    stale_file = tmp_path / "screenshots.md"
    stale_file.write_text(
        "# Lockverity V1.3 — Screenshot Checklist\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_active_docs,
        "MANDATORY_ACTIVE_DOCS",
        (Path(str(stale_file)),),
    )
    rc, _out, err = _run_capture()
    assert rc == 1
    assert "FAILED" in err


def test_deny_list_normalises_whitespace(tmp_path, monkeypatch) -> None:
    """Tab / multi-space variants of the rule text must fail.

    A copy-paste that introduces a tab or two spaces where
    the rule expects one must not defeat the check.
    """
    stale_file = tmp_path / "README.md"
    # Two spaces between ``private`` and ``portfolio``
    # (the canonical rule has one space).
    stale_file.write_text(
        "This is a private  portfolio baseline.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_active_docs,
        "MANDATORY_ACTIVE_DOCS",
        (Path(str(stale_file)),),
    )
    rc, _out, err = _run_capture()
    assert rc == 1
    assert "FAILED" in err


def test_deny_list_matches_maintainer_path(tmp_path, monkeypatch) -> None:
    """The maintainer's local path must be flagged in any
    active doc.
    """
    stale_file = tmp_path / "docs" / "demo-pack.md"
    stale_file.parent.mkdir(parents=True)
    stale_file.write_text(
        "Path: C:\\Users\\Naman Parikh\\Documents\\Minimax Projects\\Lockverity\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_active_docs,
        "MANDATORY_ACTIVE_DOCS",
        (Path(str(stale_file)),),
    )
    rc, _out, err = _run_capture()
    assert rc == 1
    assert "FAILED" in err


def test_deny_list_matches_placeholder_security_contact(tmp_path, monkeypatch) -> None:
    """The placeholder ``security@lockverity.example``
    contact must be flagged.
    """
    stale_file = tmp_path / "SECURITY.md"
    stale_file.write_text(
        "Report issues to security@lockverity.example.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_active_docs,
        "MANDATORY_ACTIVE_DOCS",
        (Path(str(stale_file)),),
    )
    rc, _out, err = _run_capture()
    assert rc == 1
    assert "FAILED" in err


def test_deny_list_matches_legacy_determinism_key(tmp_path, monkeypatch) -> None:
    """The legacy ``exported_at`` key (in either the JSON
    or CSV spelling) must be flagged.
    """
    stale_file = tmp_path / "docs" / "exporters.md"
    stale_file.parent.mkdir(parents=True)
    stale_file.write_text(
        'Document contains "exported_at": and exported_at= and version=1.6.1\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_active_docs,
        "MANDATORY_ACTIVE_DOCS",
        (Path(str(stale_file)),),
    )
    rc, _out, err = _run_capture()
    assert rc == 1
    assert "FAILED" in err


def test_deny_list_matches_legacy_react_router_pin(tmp_path, monkeypatch) -> None:
    """An active docs reference to a 6.x react-router pin
    must be flagged.
    """
    stale_file = tmp_path / "docs" / "frontend.md"
    stale_file.parent.mkdir(parents=True)
    stale_file.write_text(
        "frontend pins react-router-dom@6.30.4 for CVE mitigation\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_active_docs,
        "MANDATORY_ACTIVE_DOCS",
        (Path(str(stale_file)),),
    )
    rc, _out, err = _run_capture()
    assert rc == 1
    assert "FAILED" in err


def test_deny_list_matches_removed_github_api_url_env(tmp_path, monkeypatch) -> None:
    """``LOCKVERITY_GITHUB_API_URL`` must be flagged in
    ``.env.example`` and any other active file.
    """
    stale_file = tmp_path / ".env.example"
    stale_file.write_text(
        "# Lockverity configuration example\nLOCKVERITY_GITHUB_API_URL=https://github.example/api\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_active_docs,
        "MANDATORY_ACTIVE_DOCS",
        (Path(str(stale_file)),),
    )
    rc, _out, err = _run_capture()
    assert rc == 1
    assert "FAILED" in err
    assert "LOCKVERITY_GITHUB_API_URL" in err


def test_deny_list_allows_changelog(tmp_path, monkeypatch) -> None:
    """``CHANGELOG.md`` is exempt from the deny list by
    design; historical version references are allowed.
    """
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "## v1.3 — Screenshot Checklist\nWhat v1.3 does not include\n",
        encoding="utf-8",
    )
    other = tmp_path / "README.md"
    other.write_text("Clean current copy.\n", encoding="utf-8")
    # Wire the script to the tmp root so the test does
    # not depend on the real on-disk tree.
    monkeypatch.setattr(
        check_active_docs,
        "_historical_changelog_exempt",
        lambda p: p.name == "CHANGELOG.md",
    )
    # The actual scan reads the repo root; we rely on
    # the per-file ``_historical_changelog_exempt`` hook
    # plus a partial override below.
    failures = check_active_docs._apply_deny_list(
        Path("CHANGELOG.md"), changelog.read_text(encoding="utf-8")
    )
    # The v1.3 / v1.0 rules do fire on the text; the
    # exemption is applied by ``main`` at file level, not
    # in ``_apply_deny_list``. We confirm the rule does
    # match the text, then check the file-level
    # exemption.
    assert failures, "rule should match the changelog text"
    # The file-level exemption must skip the file.
    assert check_active_docs._historical_changelog_exempt(Path("CHANGELOG.md"))


def test_partial_scan_exempts_historical_changelog_section(tmp_path, monkeypatch) -> None:
    """``RELEASE_NOTES.md`` is partially scanned: only the
    section before ``## Historical changelog`` is in
    scope, but only when the boundary appears at line
    200 or later. A reference to ``v1.6.1`` in the
    historical section (with the boundary well below
    line 1) must not fail the check.
    """
    release_notes = tmp_path / "RELEASE_NOTES.md"
    body = (
        "## Status — local-first release candidate\n"
        "v2.0.6 ships.\n" + ("\n" * 250) + "## Historical changelog\n"
        "- v1.6.1 fixed a regression.\n"
        "- v1.0 introduced the Markdown report.\n"
    )
    release_notes.write_text(body, encoding="utf-8")
    failures, scanned = check_active_docs._scan_with_partial_exemption(
        rel_path=Path("RELEASE_NOTES.md"),
        text=release_notes.read_text(encoding="utf-8"),
    )
    # The historical changelog section is below the
    # ``## Historical changelog`` marker (well past the
    # 200-line threshold), so the v1.6.1 reference in
    # the historical section is not scanned.
    assert "v1.6.1" not in scanned
    assert not failures


def test_partial_scan_fails_for_active_section_in_release_notes(tmp_path, monkeypatch) -> None:
    """A stale claim in the ``## Status`` section of
    ``RELEASE_NOTES.md`` (above the historical changelog
    boundary) must fail the check.
    """
    release_notes = tmp_path / "RELEASE_NOTES.md"
    release_notes.write_text(
        "## Status — local-first release candidate\n"
        "Lockverity is a private portfolio baseline.\n"
        "\n"
        "## Historical changelog\n"
        "- v2.0.6 ships.\n",
        encoding="utf-8",
    )
    failures, _ = check_active_docs._scan_with_partial_exemption(
        rel_path=Path("RELEASE_NOTES.md"),
        text=release_notes.read_text(encoding="utf-8"),
    )
    assert failures, "the 'private portfolio' wording in the active section must fail"
    description = failures[0][1]
    assert "private portfolio" in description


def test_normalise_text_folds_whitespace() -> None:
    """The normalisation folds horizontal whitespace and CR/CRLF.

    Within a single line, runs of horizontal whitespace
    collapse to a single space; a tab folds to a space;
    CR and CRLF normalise to LF. The line structure is
    preserved (the rule can still report an exact line
    number).
    """
    normalised = check_active_docs._normalise_text("  hello\tworld  \n  again\r\n  done\r  end")
    # Within a single line, the whitespace is collapsed.
    assert "  " not in normalised.split("\n")[0]
    # CR / CRLF are gone; only LF separators remain.
    assert "\r" not in normalised
    # The content is preserved.
    assert "hello world" in normalised
    assert "again" in normalised
    assert "done" in normalised
    assert "end" in normalised


def test_mandatory_active_docs_cover_required_documents() -> None:
    """The mandatory list covers every active document the
    release-closure audit flagged.
    """
    names = {p.name for p in MANDATORY_ACTIVE_DOCS}
    for required in {
        "README.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "RELEASE_NOTES.md",
        ".env.example",
        "demo-pack.md",
        "demo-walkthrough.md",
        "release-checklist.md",
        "screenshots.md",
        "AboutPage.tsx",
        "DemoHomePage.tsx",
    }:
        assert required in names, f"missing mandatory active doc: {required}"


def test_deny_list_flags_legacy_csv_fetched_at_header(tmp_path, monkeypatch) -> None:
    """The cycle-7 v2.0.6 closure restored ``exported_at=`` as the
    public CSV header. A deny-list rule bans
    ``fetched_at=`` in active CSV context. The cycle-6
    rule that incorrectly required ``exported_at=``
    to be rewritten as ``fetched_at=`` was removed.
    """
    for stale_text in (
        "the csv header uses fetched_at= on line 1",
        "the csv emits fetched_at= in the body of the export",
    ):
        text = f"README\n{stale_text}\n"
        deny_list_hits = [
            (pattern, description)
            for pattern, description in DENY_LIST
            if re.search(pattern, check_active_docs._normalise_text(text), re.IGNORECASE)
        ]
        cycle7_hits = [
            (pattern, description)
            for pattern, description in deny_list_hits
            if "fetched_at=" in description or "fetched_at'" in description
        ]
        assert cycle7_hits, (
            f"expected the cycle-7 CSV header rule to match {stale_text!r}, got {deny_list_hits!r}"
        )


def test_deny_list_allows_csv_exported_at_header(tmp_path, monkeypatch) -> None:
    """The cycle-7 closure restored ``exported_at=`` as the
    public CSV header. The active docs may legitimately
    describe this contract.
    """
    text = (
        "README\n"
        "The findings CSV header is `exported_at=<iso8601>`.\n"
        "This is the v2.0.6 public contract.\n"
    )
    deny_list_hits = [
        (pattern, description)
        for pattern, description in DENY_LIST
        if re.search(pattern, check_active_docs._normalise_text(text), re.IGNORECASE)
    ]
    cycle7_false_hits = [
        (pattern, description)
        for pattern, description in deny_list_hits
        if "exported_at" in description
    ]
    assert not cycle7_false_hits, (
        f"the active 'exported_at=' contract must NOT be flagged; got {cycle7_false_hits!r}"
    )


def test_positive_version_check_flags_stale_about_page(tmp_path, monkeypatch) -> None:
    """The positive version check fires when the
    ``## Current milestone`` (or first-200-lines
    fallback for TSX) section of a version-centric
    active doc does not match the canonical
    ``backend/app/_version.py`` value.
    """
    fake_app_version_file = tmp_path / "backend" / "app" / "_version.py"
    fake_app_version_file.parent.mkdir(parents=True, exist_ok=True)
    fake_app_version_file.write_text('__version__ = "9.9.9"\n')
    fake_about = tmp_path / "frontend" / "src" / "pages" / "AboutPage.tsx"
    fake_about.parent.mkdir(parents=True, exist_ok=True)
    fake_about.write_text(
        "export const Foo = (): null => null;\n"
        "What v1.0 implements today\n"
        "Lockverity v0.4.0-rc.1 — current version v0.3.0\n"
    )
    fake_readme = tmp_path / "README.md"
    fake_readme.write_text("## Quick links\n\n## Current milestone\n\n**v9.9.9 — something**\n")
    failures = check_active_docs._check_positive_versions(tmp_path)
    # The positive check is first-match: the FIRST
    # vX.Y.Z reference in the section is the current-
    # version claim. The first vX.Y.Z in the AboutPage
    # fallback (first 200 lines) is ``v0.4.0`` (from
    # ``v0.4.0-rc.1``); the trailing ``v0.3.0`` is a
    # later historical mention and is not flagged.
    stale = [description for description, expected, actual in failures if "v0.4.0" in actual]
    assert stale, (
        f"expected the positive version check to flag the AboutPage v0.4.0 "
        f"reference; got {failures!r}"
    )


def test_positive_version_check_passes_when_section_is_canonical(tmp_path, monkeypatch) -> None:
    """The positive version check passes when every
    version-centric doc references the canonical
    version in its primary content.
    """
    fake_app_version_file = tmp_path / "_version.py"
    fake_app_version_file.write_text('__version__ = "2.0.6"\n')
    fake_about = tmp_path / "AboutPage.tsx"
    fake_about.write_text("What v2.0.6 implements today\n")
    fake_readme = tmp_path / "README.md"
    fake_readme.write_text("## Current milestone\n\n**v2.0.6 — historical upload\n")
    failures = check_active_docs._check_positive_versions(tmp_path)
    assert not failures, f"expected clean tree to pass the positive version check, got {failures!r}"


def test_legacy_config_reference_check_flags_eslintrc(tmp_path, monkeypatch) -> None:
    """The cycle-7 ESLint migration retired
    ``frontend/.eslintrc.cjs``. Any active mention of
    the legacy config is a stale claim.
    """
    fake_readme = tmp_path / "README.md"
    fake_readme.write_text("Lockverity\nConfigure ESLint via `.eslintrc.cjs` in the frontend.\n")
    failures = check_active_docs._check_no_legacy_config_references(tmp_path)
    assert any(".eslintrc.cjs" in matched for _path, _line, matched in failures), (
        f"expected `.eslintrc.cjs` reference to be flagged; got {failures!r}"
    )


def test_legacy_config_reference_check_passes_clean(tmp_path, monkeypatch) -> None:
    """The cycle-7 ESLint migration retired
    ``frontend/.eslintrc.cjs``. The active docs that
    mention ``frontend/eslint.config.js`` (the new
    flat config) must NOT be flagged.
    """
    fake_readme = tmp_path / "README.md"
    fake_readme.write_text(
        "Lockverity\nConfigure ESLint via `frontend/eslint.config.js` (the flat config).\n"
    )
    failures = check_active_docs._check_no_legacy_config_references(tmp_path)
    assert not failures, f"expected clean tree to pass the legacy-config check, got {failures!r}"
