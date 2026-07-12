"""Tests for the GitHub Actions workflow analyzer."""

from __future__ import annotations

from app.analyzers.github_actions import GitHubActionsAnalyzer

from tests.fixtures import read_fixture_bytes


def _analyze_workflow(rel_path: str):
    files = [(rel_path, read_fixture_bytes(rel_path))]
    analyzer = GitHubActionsAnalyzer()
    return analyzer.analyze(files=files, scan_run_id=1)


def test_safe_workflow_emits_no_findings() -> None:
    result = _analyze_workflow("workflows/safe/.github/workflows/safe.yml")
    assert result.findings == ()


def test_unsafe_workflow_emits_all_rule_findings() -> None:
    result = _analyze_workflow("workflows/unsafe/.github/workflows/unsafe.yml")
    rule_ids = {f.rule_id for f in result.findings}
    for expected in (
        "LOCK-WF-001",
        "LOCK-WF-002",
        "LOCK-WF-003",
        "LOCK-WF-004",
        "LOCK-WF-005",
        "LOCK-WF-006",
        "LOCK-WF-007",
        "LOCK-WF-008",
        "LOCK-WF-009",
        "LOCK-WF-010",
        "LOCK-WF-011",
        "LOCK-WF-012",
        "LOCK-WF-013",
        "LOCK-WF-014",
        "LOCK-WF-015",
    ):
        assert expected in rule_ids, f"missing rule {expected}"


def test_yaml_aliases_fixture_parses() -> None:
    result = _analyze_workflow("workflows/yaml_aliases/.github/workflows/aliased.yml")
    # The aliased file should not crash and should not emit any
    # finding (it is a clean workflow with a defaults alias).
    assert result.findings == ()


def test_malformed_workflow_emits_finding() -> None:
    result = _analyze_workflow("workflows/malformed/.github/workflows/broken.yml")
    assert any(f.rule_id == "LOCK-WF-MALFORMED" for f in result.findings)


def test_unpinned_action_is_pinned_when_first_party() -> None:
    content = b"""
name: ci
on: push
permissions: { contents: read }
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
"""
    analyzer = GitHubActionsAnalyzer(first_party_owners=frozenset({"actions"}))
    result = analyzer.analyze(files=[("ci.yml", content)], scan_run_id=1)
    # actions/checkout is a first-party action; even if unpinned it
    # should not fire 001 by default in the strict first-party list.
    # The default first_party includes "actions", so this is a
    # negative test for the strict mode.
    assert all(f.rule_id != "LOCK-WF-001" for f in result.findings)


def test_first_party_owner_can_be_extended() -> None:
    content = b"""
name: ci
on: push
permissions: { contents: read }
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: my-org/internal-action@v1
"""
    analyzer = GitHubActionsAnalyzer(first_party_owners=frozenset({"actions", "my-org"}))
    result = analyzer.analyze(files=[("ci.yml", content)], scan_run_id=1)
    assert all(f.rule_id != "LOCK-WF-001" for f in result.findings)


def test_unpinned_third_party_action_fires_001() -> None:
    content = b"""
name: ci
on: push
permissions: { contents: read }
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: some-org/setup@v1
"""
    analyzer = GitHubActionsAnalyzer()
    result = analyzer.analyze(files=[(".github/workflows/ci.yml", content)], scan_run_id=1)
    rule_001 = [f for f in result.findings if f.rule_id == "LOCK-WF-001"]
    assert rule_001, "expected at least one LOCK-WF-001 finding"


def test_dangerous_prt_with_untrusted_ref_fires_005() -> None:
    content = b"""
name: ci
on: pull_request_target
permissions: { contents: read }
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
"""
    analyzer = GitHubActionsAnalyzer()
    result = analyzer.analyze(files=[(".github/workflows/ci.yml", content)], scan_run_id=1)
    assert any(f.rule_id == "LOCK-WF-005" for f in result.findings)


def test_workflow_run_on_self_hosted_fires_010() -> None:
    content = b"""
name: ci
on: workflow_run
permissions: { contents: read }
jobs:
  build:
    runs-on: self-hosted
    steps:
      - run: echo
"""
    analyzer = GitHubActionsAnalyzer()
    result = analyzer.analyze(files=[(".github/workflows/ci.yml", content)], scan_run_id=1)
    assert any(f.rule_id == "LOCK-WF-010" for f in result.findings)


def test_secret_in_run_block_fires_011_without_echoing_value() -> None:
    content = b"""
name: ci
on: push
permissions: { contents: read }
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Use secret
        run: 'curl -H "Authorization: ${{ secrets.MY_SECRET }}" https://internal'
"""
    analyzer = GitHubActionsAnalyzer()
    result = analyzer.analyze(files=[(".github/workflows/ci.yml", content)], scan_run_id=1)
    rule_011 = [f for f in result.findings if f.rule_id == "LOCK-WF-011"]
    assert rule_011
    # The raw evidence must not contain the secret name value
    # (it contains the variable name, which is fine).
    raw_evidence = rule_011[0].raw
    assert raw_evidence["observed"]["secret_names"] == ["MY_SECRET"]


def test_untrusted_expression_in_run_fires_007() -> None:
    content = b"""
name: ci
on: push
permissions: { contents: read }
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Echo
        run: 'echo "${{ github.event.issue.title }}"'
"""
    analyzer = GitHubActionsAnalyzer()
    result = analyzer.analyze(files=[(".github/workflows/ci.yml", content)], scan_run_id=1)
    assert any(f.rule_id == "LOCK-WF-007" for f in result.findings)


def test_broad_trigger_fires_013() -> None:
    content = b"""
name: ci
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo
"""
    analyzer = GitHubActionsAnalyzer()
    result = analyzer.analyze(files=[(".github/workflows/ci.yml", content)], scan_run_id=1)
    assert any(f.rule_id == "LOCK-WF-013" for f in result.findings)


def test_write_all_permissions_fire_003() -> None:
    content = b"""
name: ci
on: push
permissions: write-all
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo
"""
    analyzer = GitHubActionsAnalyzer()
    result = analyzer.analyze(files=[(".github/workflows/ci.yml", content)], scan_run_id=1)
    assert any(f.rule_id == "LOCK-WF-003" for f in result.findings)


def test_missing_explicit_permissions_fire_004() -> None:
    content = b"""
name: ci
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo
"""
    analyzer = GitHubActionsAnalyzer()
    result = analyzer.analyze(files=[(".github/workflows/ci.yml", content)], scan_run_id=1)
    assert any(f.rule_id == "LOCK-WF-004" for f in result.findings)


def test_self_hosted_with_untrusted_trigger_fires_015() -> None:
    content = b"""
name: ci
on: pull_request_target
permissions: { contents: read }
jobs:
  build:
    runs-on: self-hosted
    steps:
      - run: echo
"""
    analyzer = GitHubActionsAnalyzer()
    result = analyzer.analyze(files=[(".github/workflows/ci.yml", content)], scan_run_id=1)
    assert any(f.rule_id == "LOCK-WF-015" for f in result.findings)


def test_id_token_write_fires_009() -> None:
    content = b"""
name: ci
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
    steps:
      - run: echo
"""
    analyzer = GitHubActionsAnalyzer()
    result = analyzer.analyze(files=[(".github/workflows/ci.yml", content)], scan_run_id=1)
    assert any(f.rule_id == "LOCK-WF-009" for f in result.findings)


def test_artifact_path_with_expression_fires_012() -> None:
    content = b"""
name: ci
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@v4
        with:
          path: ${{ github.event.pull_request.head.ref }}
"""
    analyzer = GitHubActionsAnalyzer()
    result = analyzer.analyze(files=[(".github/workflows/ci.yml", content)], scan_run_id=1)
    assert any(f.rule_id == "LOCK-WF-012" for f in result.findings)


def test_safe_workflow_with_sha_pin_does_not_fire() -> None:
    content = b"""
name: ci
on: push
permissions: { contents: read }
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11
      - uses: some-org/setup@1234567890abcdef1234567890abcdef12345678
"""
    analyzer = GitHubActionsAnalyzer()
    result = analyzer.analyze(files=[(".github/workflows/ci.yml", content)], scan_run_id=1)
    assert not any(f.rule_id == "LOCK-WF-001" for f in result.findings)
    assert not any(f.rule_id == "LOCK-WF-014" for f in result.findings)


def test_each_finding_has_evidence() -> None:
    content = b"""
name: ci
on: push
permissions: write-all
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
"""
    analyzer = GitHubActionsAnalyzer()
    result = analyzer.analyze(files=[(".github/workflows/ci.yml", content)], scan_run_id=1)
    for finding in result.findings:
        assert finding.raw
        assert "title" in finding.raw
        assert "summary" in finding.raw
        assert "remediation" in finding.raw
        assert "limitations" in finding.raw
        assert "stable_key" in finding.raw
        assert finding.location_path
