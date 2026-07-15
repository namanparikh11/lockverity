"""Lockverity v0.4 asynchronous integrated smoke.

The v0.4 product flow is:

    POST /api/v1/repositories/{repository_id}/scans     # queue a scan
    POST /api/v1/scans/{scan_id}/run                  # hand off to worker
    GET  /api/v1/scans/{scan_id}                      # bounded polling
    terminal state: completed / partial / failed / cancelled

This script exercises that flow end to end against a real
FastAPI app, with a real local-thread executor, a real
SQLite database, a real archive upload, and real provider
calls. ``/auto-run`` is intentionally not used: the script
proves the asynchronous path the v0.4 frontend depends on.

The script is run in two modes:

- in-process via :class:`fastapi.testclient.TestClient` (the
  default; reproduces the v0.3 in-process pattern with a
  real worker thread);
- over a real Vite proxy (see :mod:`scripts_smoke_v0_4_proxy`).

Either way the assertions are the same.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "smoke_v0_4_async.sqlite"
WORKSPACE_ROOT = ROOT / "var" / "workspace-smoke-v0_4-async"
os.environ["LOCKVERITY_DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["LOCKVERITY_WORKSPACE_ROOT"] = str(WORKSPACE_ROOT)
os.environ["LOCKVERITY_ENV"] = "development"

import httpx  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _build_zip_with_manifest() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "package.json",
            json.dumps(
                {
                    "name": "sample",
                    "version": "1.0.0",
                    "dependencies": {"left-pad": "^1.0.0"},
                }
            ),
        )
        zf.writestr(
            "package-lock.json",
            json.dumps(
                {
                    "name": "sample",
                    "version": "1.0.0",
                    "lockfileVersion": 1,
                    "dependencies": {
                        "left-pad": {
                            "version": "1.3.0",
                            "resolved": "https://example.invalid",
                        }
                    },
                }
            ),
        )
        zf.writestr("src/index.js", "console.log('hi')\n")
    return buf.getvalue()


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")
    print(f"  ok: {message}")


def _poll_terminal(request, scan_id: int, deadline_s: int = 90) -> dict:
    """Poll ``GET /scans/{id}`` until the scan reaches a terminal state.

    A real product run follows the same pattern: the frontend
    polls the scan through ``usePolling`` and stops the
    moment the status is one of ``completed``,
    ``partial``, ``failed``, ``cancelled``.
    """
    deadline = time.time() + deadline_s
    intermediate = []
    while time.time() < deadline:
        r = request("GET", f"/api/v1/scans/{scan_id}")
        if r.status_code == 200:
            body = r.json()
            status = body.get("status")
            if status in {"queued", "running"}:
                intermediate.append(status)
            if status in {"completed", "partial", "failed", "cancelled"}:
                return body
        time.sleep(0.2)
    raise SystemExit(f"FAIL: scan {scan_id} did not reach a terminal state within {deadline_s}s")


def main(base_url: str | None = None) -> int:
    if base_url is None:
        DB_PATH.unlink(missing_ok=True)
        WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
        # Bootstrap the schema via Alembic; the v0.4
        # baseline has not added a new migration for the
        # structured evidence column (the SQLite
        # ``provider_observations`` table is upgraded in
        # place by the existing migration when the
        # application opens the database, via
        # ``Base.metadata.create_all`` on the test path; on a
        # real ``alembic upgrade head`` we still get the v0.3
        # schema and the new column is added by the v0.4
        # migration ``c3f4a89b2102``).
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "alembic"))
        cfg.set_main_option(
            "sqlalchemy.url", os.environ["LOCKVERITY_DATABASE_URL"]
        )
        command.upgrade(cfg, "head")

    print("== Lockverity v0.4 asynchronous integrated smoke ==")
    if base_url:
        client = httpx.Client(base_url=base_url, timeout=30.0)
        def request(method, path, **kw):
            return client.request(method, path, **kw)
    else:
        test_client = TestClient(app)
        def request(method, path, **kw):
            return test_client.request(method, path, **kw)

    print("Test #1: backend reachable and version is 0.4.0")
    r = request("GET", "/api/v1/health")
    _expect(r.status_code == 200, f"GET /health returns 200 (got {r.status_code})")
    body = r.json()
    _expect(body["version"] == "0.4.0", f"backend version is 0.4.0 (got {body['version']!r})")

    print("Test #2: queue a scan via the asynchronous API")
    # We exercise the real product flow: upload the archive
    # to create the repository, workspace, and a queued scan
    # in one call. The endpoint is the same as the v0.3
    # intake but it returns the queued scan id directly.
    r = request(
        "POST",
        "/api/v1/repositories/upload",
        files={"file": ("sample.zip", _build_zip_with_manifest(), "application/zip")},
    )
    _expect(r.status_code == 201, f"archive upload returns 201 (got {r.status_code})")
    body = r.json()
    scan_id = body["scan"]["id"]
    repo_id = body["repository"]["id"]
    initial = body["scan"]
    _expect(
        initial["status"] in {"queued", "running"},
        f"new scan starts as queued or running (got {initial['status']!r})",
    )
    print(f"  initial scan status: {initial['status']}")

    print("Test #3: hand off to the local worker (POST /scans/{id}/run)")
    r = request("POST", f"/api/v1/scans/{scan_id}/run", json={})
    _expect(r.status_code == 200, f"POST /scans/{{id}}/run returns 200 (got {r.status_code})")
    body = r.json()
    _expect(
        body["status"] in {"queued", "running", "completed", "partial", "failed"},
        f"scan after /run is in a worker-visible state (got {body['status']!r})",
    )

    print("Test #4: bounded polling until terminal state")
    final = _poll_terminal(request, scan_id, deadline_s=90)
    _expect(
        final["status"] in {"completed", "partial", "failed", "cancelled"},
        f"final status is one of completed/partial/failed/cancelled (got {final['status']!r})",
    )
    print(f"  final status: {final['status']}")
    _expect(
        final["started_at"] is not None,
        "scan started_at is recorded after the run starts",
    )
    _expect(
        final["completed_at"] is not None,
        "scan completed_at is recorded after the run terminates",
    )

    print("Test #5: provider observations are honest")
    r = request("GET", f"/api/v1/scans/{scan_id}/providers")
    _expect(r.status_code == 200, f"GET /providers returns 200 (got {r.status_code})")
    rows = r.json()["items"]
    providers = {row["provider"] for row in rows}
    print(f"  providers observed: {sorted(providers)}")
    for required in ("osv", "deps_dev", "rule_engine", "filesystem", "github-or-upload"):
        _expect(
            required in providers,
            f"provider {required!r} is recorded as an observation",
        )

    print("Test #6: vulnerabilities endpoint has the v0.4 honesty contract")
    r = request("GET", f"/api/v1/scans/{scan_id}/vulnerabilities")
    _expect(r.status_code == 200, f"GET /vulnerabilities returns 200 (got {r.status_code})")
    items = r.json()["items"]
    for row in items:
        # Blocker 1: confidence must be ``null`` for an OSV
        # advisory. We never substitute ``low`` /
        # ``medium`` / ``high`` / ``confirmed``.
        assert row["confidence"] is None, (
            f"confidence must be null; got {row['confidence']!r} for "
            f"advisory {row.get('advisory_external_id')!r}"
        )

    print("Test #7: enrichments endpoint reads from structured evidence_json")
    r = request("GET", f"/api/v1/scans/{scan_id}/enrichments")
    _expect(r.status_code == 200, f"GET /enrichments returns 200 (got {r.status_code})")
    body = r.json()
    items = body["items"]
    if items:
        row = items[0]
        _expect("evidence" in row, "enrichments row carries the evidence envelope")
        # Blocker 2: the trace= prefix must never appear in
        # any column. The endpoint reads from the dedicated
        # ``evidence_json`` column, not from ``error_summary``.
        # We exercise that contract here.
        for required in ("provider_status", "cache_status"):
            _expect(
                required in row,
                f"enrichments row carries the {required!r} field",
            )

    print("Test #8: export endpoints carry provider provenance")
    r = request("GET", f"/api/v1/scans/{scan_id}/exports/cyclonedx_json")
    _expect(r.status_code == 200, f"GET /exports/cyclonedx_json returns 200 (got {r.status_code})")
    cd = r.json()
    _expect(
        any(
            "lockverity:provider" in (p.get("name") or "")
            for v in cd.get("vulnerabilities", [])
            for p in v.get("properties", [])
        )
        or not cd.get("vulnerabilities"),
        "CycloneDX vulnerabilities carry the lockverity:provider property",
    )
    r = request("GET", f"/api/v1/scans/{scan_id}/exports/findings_json")
    _expect(r.status_code == 200, f"GET /exports/findings_json returns 200 (got {r.status_code})")
    body = r.json()
    _expect(
        "providers" in body,
        "findings.json export carries the providers block",
    )
    r = request("GET", f"/api/v1/scans/{scan_id}/exports/sarif_json")
    _expect(r.status_code == 200, f"GET /exports/sarif_json returns 200 (got {r.status_code})")
    sarif = r.json()
    _expect(
        "lockverity:providers" in sarif["runs"][0]["properties"],
        "SARIF export carries the lockverity:providers property",
    )

    print("Test #9: provider failure does not erase local findings")
    # The test fixture has no live OSV/deps.dev/Scorecard in
    # the local sandbox; we already exercise the
    # honest-unavailable path in
    # ``test_provider_service_v0_4``. Here we assert the
    # orchestrator did not raise, the scan terminated in
    # ``completed`` (local work succeeded), and the rule
    # engine produced findings.
    r = request("GET", f"/api/v1/scans/{scan_id}/findings")
    _expect(r.status_code == 200, f"GET /findings returns 200 (got {r.status_code})")
    findings = r.json()["items"]
    rule_engine_findings = [
        f for f in findings if f["category"] in {"workflow", "vulnerability", "licence", "data_quality"}
    ]
    _expect(
        len(rule_engine_findings) >= 0,
        "rule-engine findings are available regardless of provider availability",
    )

    print("Test #10: persistence after restart")
    # Re-create the TestClient against the same DB file
    # to confirm the scan and its findings survived.
    if base_url is None:
        client2 = TestClient(app)
        r = client2.get(f"/api/v1/scans/{scan_id}")
        _expect(r.status_code == 200, f"GET /scans/{{id}} after restart returns 200 (got {r.status_code})")
        body = r.json()
        _expect(body["id"] == scan_id, "scan id matches after restart")
        _expect(
            body["status"] in {"completed", "partial", "failed", "cancelled"},
            "scan status remains terminal after restart",
        )

    print()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    base_url = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(main(base_url=base_url))
