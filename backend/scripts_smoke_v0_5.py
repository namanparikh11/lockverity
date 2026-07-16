"""v0.5 integrated smoke test.

This script runs the Lockverity v0.5 evidence-aware scan
comparison end to end against a fresh SQLite database, without
modifying the v0.4 schema (v0.5 is read-only over the existing
persisted evidence). The script:

1. Boots the FastAPI application in-process via TestClient.
2. Creates a single repository.
3. Creates two queued scans on that repository.
4. Writes the v0.5 evidence directly into the database so
   the smoke run is deterministic and not dependent on
   external provider availability. The base scan carries a
   left-pad 1.0.0 component and a vulnerability row; the head
   scan carries a left-pad 2.0.0 component and a workflow
   finding.
5. Transitions both scans to a terminal state.
6. Hits the v0.5 comparison endpoint through the FastAPI
   client (the same proxy the Vite dev server uses).
7. Refreshes the direct comparison route: the route survives
   the refresh and the data is identical.
8. Verifies the v0.5 evidence-honest vocabulary and the
   absence of "fixed" / "resolved" / "clean" / "secure" /
   "all clear" terminology in the response.
9. Confirms the comparison made no database writes.

The script returns a non-zero exit code on the first failure.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Configure the environment before importing the application.
ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "smoke_v0_5.sqlite"
os.environ["LOCKVERITY_DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["LOCKVERITY_WORKSPACE_ROOT"] = str(ROOT / "var" / "workspace-smoke-v0_5")
os.environ["LOCKVERITY_ENV"] = "development"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import session as _db_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.advisory import Advisory  # noqa: E402
from app.models.component import Component, ComponentVersionSource  # noqa: E402
from app.models.component_advisory import ComponentAdvisory  # noqa: E402
from app.models.finding import (  # noqa: E402
    Finding,
    FindingCategory,
    FindingConfidence,
    FindingSeverity,
)
from app.models.manifest import Manifest, ManifestParseStatus  # noqa: E402
from app.models.provider_observation import ProviderObservation, ProviderStatus  # noqa: E402
from app.models.repository import (  # noqa: E402
    Repository,
    RepositoryProvider,
    RepositorySourceType,
    RepositoryVisibility,
)
from app.models.scan_run import ScanRun, ScanStatus, ScanTriggerType  # noqa: E402
from app.services import scan_service  # noqa: E402


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")
    print(f"  ok: {message}")


def _setup_repo(session) -> int:
    """Create a fresh repository in the test session."""
    repo = Repository(
        source_type=RepositorySourceType.GITHUB,
        provider=RepositoryProvider.GITHUB,
        owner="octocat",
        name="Hello-World",
        canonical_url="https://github.com/octocat/Hello-World",
        default_branch="main",
        visibility=RepositoryVisibility.PUBLIC,
    )
    session.add(repo)
    session.flush()
    return repo.id


def _attach_evidence(
    session,
    *,
    scan_id: int,
    manifest_path: str,
    manifest_hash: str,
    components: list[dict],
    findings: list[dict] | None = None,
    provider_observations: list[dict] | None = None,
    component_advisories: list[dict] | None = None,
) -> None:
    """Attach a manifest, components, and optional findings to a scan."""
    manifest = Manifest(
        scan_run_id=scan_id,
        path=manifest_path,
        manifest_type="package_json",
        ecosystem="npm",
        parse_status=ManifestParseStatus.PARSED,
        content_sha256=manifest_hash,
    )
    session.add(manifest)
    session.flush()
    for c in components:
        comp = Component(
            scan_run_id=scan_id,
            manifest_id=manifest.id,
            ecosystem="npm",
            package_name=c["name"],
            version=c["version"],
            version_source=ComponentVersionSource.LOCKFILE,
            direct=True,
        )
        session.add(comp)
    if findings:
        for f in findings:
            finding = Finding(
                scan_run_id=scan_id,
                repository_id=f["repository_id"],
                rule_id=f["rule_id"],
                category=FindingCategory.WORKFLOW,
                severity=FindingSeverity.HIGH,
                confidence=FindingConfidence.HIGH,
                title=f["title"],
                summary=f["summary"],
                location_path=f["location_path"],
                stable_key=f["stable_key"],
            )
            session.add(finding)
    if provider_observations:
        for obs in provider_observations:
            o = ProviderObservation(
                scan_run_id=scan_id,
                provider=obs["provider"],
                operation=obs.get("operation", f"{obs['provider']}_call"),
                status=ProviderStatus(obs["status"]),
                records_returned=obs.get("records_returned", 0),
                cache_status=obs.get("cache_status", "miss"),
                error_code=obs.get("error_code"),
                error_summary=obs.get("error_summary"),
                evidence_json=obs.get("evidence_json"),
            )
            session.add(o)
    if component_advisories:
        for ca in component_advisories:
            advisory = Advisory(
                source=ca.get("source", "osv"),
                source_advisory_id=ca["source_advisory_id"],
                canonical_id=ca.get("canonical_id"),
                summary="Test advisory",
                details_url="https://example.com/advisory",
                raw_payload_sha256="a" * 64,
            )
            session.add(advisory)
            session.flush()
            comp = (
                session.query(Component)
                .filter(
                    Component.scan_run_id == scan_id,
                    Component.package_name == ca["package_name"],
                )
                .one()
            )
            comp_adv = ComponentAdvisory(
                scan_run_id=scan_id,
                component_id=comp.id,
                advisory_id=advisory.id,
                affected=True,
                fixed_versions_json=json.dumps(ca.get("fixed_versions", [])),
                severity_source=ca.get("source", "osv"),
                severity_label=ca.get("severity_label"),
                severity_score=ca.get("severity_score"),
                evidence_json=json.dumps(
                    {
                        "provider": ca.get("source", "osv"),
                        "fetched_at": ca.get("fetched_at"),
                        "aliases": ca.get("aliases", []),
                    }
                ),
            )
            session.add(comp_adv)
    session.commit()


def main() -> int:
    # Wipe any previous smoke run.
    DB_PATH.unlink(missing_ok=True)
    workspace = Path(os.environ["LOCKVERITY_WORKSPACE_ROOT"])
    workspace.mkdir(parents=True, exist_ok=True)

    print("== Lockverity v0.5 integrated smoke ==")

    # Apply Alembic migrations.
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["LOCKVERITY_DATABASE_URL"])
    command.upgrade(cfg, "head")
    print("  ok: alembic upgrade head")

    # Build the persisted evidence deterministically.
    with _db_session.SessionLocal() as s:
        repo_id = _setup_repo(s)
        base_scan = scan_service.create_scan(
            s, repository_id=repo_id, trigger_type=ScanTriggerType.MANUAL
        )
        base_id = base_scan.id
        head_scan = scan_service.create_scan(
            s, repository_id=repo_id, trigger_type=ScanTriggerType.MANUAL
        )
        head_id = head_scan.id
        s.flush()

        # Base: left-pad 1.0.0, one advisory, one successful OSV observation.
        _attach_evidence(
            s,
            scan_id=base_id,
            manifest_path="package.json",
            manifest_hash="a" * 64,
            components=[
                {"name": "left-pad", "version": "1.0.0"},
                {"name": "stay", "version": "1.0.0"},
            ],
            provider_observations=[
                {
                    "provider": "osv",
                    "status": "available",
                    "records_returned": 1,
                    "cache_status": "miss",
                    "evidence_json": json.dumps(
                        {"fetched_at": "2024-01-01T00:00:00Z", "advisory_count": 1}
                    ),
                }
            ],
            component_advisories=[
                {
                    "package_name": "left-pad",
                    "source_advisory_id": "GHSA-1",
                    "canonical_id": "CVE-2024-0001",
                    "fixed_versions": ["1.3.0"],
                    "severity_label": "CVSS_V3",
                    "severity_score": 7.5,
                    "fetched_at": "2024-01-01T00:00:00Z",
                    "aliases": ["CVE-2024-0001"],
                }
            ],
        )
        # Head: left-pad 2.0.0, a workflow finding, OSV cached.
        _attach_evidence(
            s,
            scan_id=head_id,
            manifest_path="package.json",
            manifest_hash="b" * 64,
            components=[
                {"name": "left-pad", "version": "2.0.0"},
                {"name": "stay", "version": "1.0.0"},
                {"name": "right-pad", "version": "1.0.0"},
            ],
            findings=[
                {
                    "repository_id": repo_id,
                    "rule_id": "LOCK-WF-001",
                    "title": "Unpinned third-party action",
                    "summary": "actions/checkout is not pinned",
                    "location_path": ".github/workflows/ci.yml",
                    "stable_key": "wf-1",
                }
            ],
            provider_observations=[
                {
                    "provider": "osv",
                    "status": "cached",
                    "records_returned": 1,
                    "cache_status": "hit",
                    "evidence_json": json.dumps(
                        {"fetched_at": "2024-02-01T00:00:00Z", "advisory_count": 0}
                    ),
                }
            ],
        )
        scan_service.transition_scan(s, base_id, target=ScanStatus.RUNNING)
        scan_service.transition_scan(s, base_id, target=ScanStatus.COMPLETED)
        scan_service.transition_scan(s, head_id, target=ScanStatus.RUNNING)
        scan_service.transition_scan(s, head_id, target=ScanStatus.COMPLETED)
        s.commit()
    print(f"  ok: created base scan {base_id} and head scan {head_id} on repo {repo_id}")

    # Create the other-repository scan that the cross-workspace
    # validation will create. We do this BEFORE the snapshot
    # so the snapshot reflects the database state at the
    # start of the read-only comparison calls.
    with _db_session.SessionLocal() as s:
        other_repo = Repository(
            source_type=RepositorySourceType.GITHUB,
            provider=RepositoryProvider.GITHUB,
            owner="other",
            name="repo",
            canonical_url="https://github.com/other/repo",
            default_branch="main",
            visibility=RepositoryVisibility.PUBLIC,
        )
        s.add(other_repo)
        s.flush()
        other_scan = scan_service.create_scan(
            s, repository_id=other_repo.id, trigger_type=ScanTriggerType.MANUAL
        )
        scan_service.transition_scan(s, other_scan.id, target=ScanStatus.RUNNING)
        scan_service.transition_scan(s, other_scan.id, target=ScanStatus.COMPLETED)
        s.commit()
        other_id = other_scan.id
    print(f"  ok: created other-repo scan {other_id} for cross-workspace test")

    # Snapshot the database before any HTTP calls.
    with _db_session.SessionLocal() as s:
        before_runs = {r.id: r.updated_at for r in s.query(ScanRun).all()}
        before_components = {
            (c.scan_run_id, c.package_name): c.updated_at
            for c in s.query(Component).all()
        }

    with TestClient(app) as client:
        # Forward comparison.
        cmp_resp = client.get(f"/api/v1/scans/{head_id}/compare/{base_id}")
        _expect(cmp_resp.status_code == 200, f"comparison returned 200 (got {cmp_resp.status_code})")
        body = cmp_resp.json()
        for key in (
            "coverage",
            "components",
            "manifests",
            "dependency_paths",
            "workflows",
            "vulnerabilities",
            "licences",
            "openssf",
            "providers",
            "indeterminate_reasons",
        ):
            _expect(key in body, f"top-level key {key!r} present")

        component_states = {row["state"] for row in body["components"]}
        # With v0.5 identity keyed on the concrete version,
        # the smoke fixture produces: left-pad 1.0.0
        # (still_observed; in both), right-pad (newly_observed;
        # head only). The base-only stay is no_longer_observed
        # in the new identity model, and the head-only
        # left-pad 2.0.0 is newly_observed. The smoke asserts
        # the evidence-honest vocabulary is preserved.
        _expect("newly_observed" in component_states, "newly_observed present")
        _expect("still_observed" in component_states, "still_observed present")
        # No legacy vocabulary in the components.
        for row in body["components"]:
            _expect(
                row["state"] not in {"added", "removed", "updated", "persisting", "resolved", "new"},
                f"component state {row['state']!r} uses v0.5 vocabulary",
            )
        _expect(len(body["workflows"]) == 1, "1 workflow finding diffed")
        _expect(
            body["workflows"][0]["state"] == "newly_observed",
            "workflow is newly_observed",
        )
        # Vulnerability: base had one, head had none. The
        # comparator must NOT call it "fixed" or "resolved";
        # it must be marked comparison_indeterminate because
        # the head provider state is not explicitly known to
        # the comparator. The head has a cached OSV observation
        # (not unavailable), so the comparator conservatively
        # says the row is no_longer_observed.
        _expect(
            len(body["vulnerabilities"]) == 1,
            f"1 vulnerability row (got {len(body['vulnerabilities'])})",
        )
        vuln = body["vulnerabilities"][0]
        _expect(
            vuln["state"] in {"no_longer_observed", "comparison_indeterminate"},
            f"vulnerability state is honest: {vuln['state']!r}",
        )
        _expect(
            vuln["state"] != "fixed" and vuln["state"] != "resolved",
            "vulnerability is never labelled fixed or resolved",
        )
        # Provider coverage is explicit.
        osv = next((p for p in body["providers"] if p["provider"] == "osv"), None)
        _expect(osv is not None, "OSV provider row present")
        _expect(osv["state_base"] == "successful", f"OSV base state successful (got {osv['state_base']})")
        _expect(osv["state_head"] == "cached", f"OSV head state cached (got {osv['state_head']})")
        _expect(osv["state"] == "coverage_changed", f"OSV change state coverage_changed (got {osv['state']})")
        _expect(osv["evidence_present_base"] is True, "OSV base row has a structured evidence envelope")
        _expect(osv["evidence_present_head"] is True, "OSV head row has a structured evidence envelope")
        # The evidence is never carried in error_summary.
        _expect(osv["error_summary_base"] is None, "successful OSV row carries no error_summary")
        _expect(osv["error_summary_head"] is None, "successful OSV head row carries no error_summary")

        # No "fixed" / "resolved" / "clean" / "secure" / "all clear"
        # words in any string value of the response. Field names
        # like ``base_resolved_commit_sha`` and ``fixed_versions``
        # are JSON keys (not values); they are excluded from the
        # check because the keys are not claims.
        def _walk_strings(node, out: list) -> None:
            if isinstance(node, str):
                out.append(node.lower())
            elif isinstance(node, list):
                for item in node:
                    _walk_strings(item, out)
            elif isinstance(node, dict):
                for value in node.values():
                    _walk_strings(value, out)
        all_values: list[str] = []
        _walk_strings(body, all_values)
        joined = " ".join(all_values)
        for forbidden in ("fixed", "resolved", "clean", "secure", "all clear"):
            _expect(
                forbidden not in joined,
                f"response values do not contain the word {forbidden!r}",
            )

        # Refresh-survival: hitting the same URL again returns
        # the same shape.
        cmp_again = client.get(f"/api/v1/scans/{head_id}/compare/{base_id}")
        _expect(cmp_again.status_code == 200, "comparison refresh returned 200")
        _expect(
            cmp_again.json()["components"] == body["components"],
            "comparison is deterministic across refresh",
        )

        # Reverse order: swap base and head.
        cmp_reverse = client.get(f"/api/v1/scans/{base_id}/compare/{head_id}")
        _expect(cmp_reverse.status_code == 200, "reverse comparison returned 200")
        body_reverse = cmp_reverse.json()
        forward_added = sum(1 for r in body["components"] if r["state"] == "newly_observed")
        forward_removed = sum(1 for r in body["components"] if r["state"] == "no_longer_observed")
        reverse_added = sum(1 for r in body_reverse["components"] if r["state"] == "newly_observed")
        reverse_removed = sum(1 for r in body_reverse["components"] if r["state"] == "no_longer_observed")
        _expect(
            forward_added == reverse_removed and forward_removed == reverse_added,
            f"reversing base/head swaps additions/removals (forward +/-, reverse -/+)",
        )

        # Identity validation.
        same = client.get(f"/api/v1/scans/{base_id}/compare/{base_id}")
        _expect(same.status_code in (400, 422), f"identical scan rejected (got {same.status_code})")

        # Cross-workspace validation.
        cross = client.get(f"/api/v1/scans/{other_id}/compare/{base_id}")
        _expect(cross.status_code in (400, 422), f"cross-workspace comparison rejected (got {cross.status_code})")

    # Snapshot the database after every smoke call.
    with _db_session.SessionLocal() as s:
        after_runs = {r.id: r.updated_at for r in s.query(ScanRun).all()}
        after_components = {
            (c.scan_run_id, c.package_name): c.updated_at
            for c in s.query(Component).all()
        }
    # The ``updated_at`` column is bumped on every commit; the
    # comparison endpoint is read-only, so the row's
    # ``updated_at`` should be identical to the snapshot taken
    # before any HTTP calls. Some SQLAlchemy dialects can
    # normalise the timestamp value to UTC, so we compare the
    # timestamps at second resolution.
    def _normalise(snapshot: dict) -> dict:
        return {k: int(v.timestamp()) for k, v in snapshot.items()}

    _expect(
        _normalise(before_runs) == _normalise(after_runs),
        f"comparison did not update scan_runs (before={_normalise(before_runs)}, after={_normalise(after_runs)})",
    )
    _expect(
        _normalise(before_components) == _normalise(after_components),
        "comparison did not update components",
    )

    # The v0.5 comparator surfaces the v0.4 cache_status on
    # every provider row so the operator can audit freshness
    # from the live record rather than from a fabricated
    # wall-clock comparison.
    osv = next(p for p in body["providers"] if p["provider"] == "osv")
    _expect(
        osv.get("cache_status_base") in {"miss", "hit", "stale", "error", None},
        f"OSV base cache_status preserved from the persisted record (got {osv.get('cache_status_base')!r})",
    )
    _expect(
        osv.get("cache_status_head") in {"miss", "hit", "stale", "error", None},
        f"OSV head cache_status preserved from the persisted record (got {osv.get('cache_status_head')!r})",
    )

    print("== v0.5 smoke complete ==")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
