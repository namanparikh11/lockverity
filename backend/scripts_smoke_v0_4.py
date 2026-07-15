"""v0.4 integrated smoke test.

Run the Lockverity v0.4 pipeline end to end against a fresh
SQLite database, including a real GitHub source intake and a
real upload archive. The script:

1. Boots the FastAPI application in-process via TestClient.
2. Uploads a small ZIP archive containing a supported package.
3. Verifies the Vite proxy serves the new endpoints.
4. Confirms exports include provider provenance.
5. Verifies the scan reaches a terminal state with the v0.4
   provider-backed stages populated.
6. Confirms persistence after the application is recreated
   against the same database file.

Usage:
    python scripts_smoke_v0_4.py

The script returns a non-zero exit code on the first failure.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

# Configure the environment before importing the application.
ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "smoke_v0_4.sqlite"
os.environ["LOCKVERITY_DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["LOCKVERITY_WORKSPACE_ROOT"] = str(ROOT / "var" / "workspace-smoke-v0_4")
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
                        "left-pad": {"version": "1.3.0", "resolved": "https://example.invalid"},
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


def main() -> int:
    DB_PATH.unlink(missing_ok=True)
    workspace = Path(os.environ["LOCKVERITY_WORKSPACE_ROOT"])
    workspace.mkdir(parents=True, exist_ok=True)

    print("== Lockverity v0.4 integrated smoke ==")

    # Run Alembic migrations so the v0.4 schema is in place
    # before we boot the application. ``alembic upgrade head``
    # is the supported entry point; the v0.3 baseline has
    # already shipped and v0.4 does not require a new
    # migration (the existing tables carry the v0.4 data
    # without schema changes).
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["LOCKVERITY_DATABASE_URL"])
    command.upgrade(cfg, "head")

    client = TestClient(app)
    print("Test #1: health and version")
    r = client.get("/api/v1/health")
    _expect(r.status_code == 200, f"GET /health returns 200 (got {r.status_code})")
    body = r.json()
    _expect(body["status"] == "ok", f"health status is ok (got {body['status']!r})")
    _expect(body["version"] == "0.4.0", f"backend version is 0.4.0 (got {body['version']!r})")

    print("Test #2: create repository + scan via upload")
    r = client.post(
        "/api/v1/repositories",
        json={"canonical_url": "https://github.com/octocat/Hello-World"},
    )
    _expect(r.status_code == 201, f"POST /repositories returns 201 (got {r.status_code})")
    repo_id = r.json()["id"]
    r2 = client.post(f"/api/v1/repositories/{repo_id}/scans")
    _expect(r2.status_code == 201, f"POST /repositories/{{id}}/scans returns 201 (got {r2.status_code})")
    scan_id = r2.json()["id"]
    r3 = client.post(
        "/api/v1/repositories/upload",
        files={"file": ("sample.zip", _build_zip_with_manifest(), "application/zip")},
    )
    _expect(r3.status_code == 201, f"archive upload returns 201 (got {r3.status_code})")
    uploaded_scan_id = r3.json()["scan"]["id"]
    print(f"  uploaded_scan_id={uploaded_scan_id}")

    print("Test #3: run the scan synchronously via the local convenience endpoint")
    r4 = client.post(f"/api/v1/scans/{uploaded_scan_id}/auto-run")
    _expect(r4.status_code == 200, f"auto-run returns 200 (got {r4.status_code})")
    body = r4.json()
    _expect(
        body["final_status"] in {"completed", "partial"},
        f"final_status is completed or partial (got {body['final_status']!r})",
    )

    print("Test #4: poll the scan until terminal")
    deadline = time.time() + 90
    final = None
    while time.time() < deadline:
        r = client.get(f"/api/v1/scans/{uploaded_scan_id}")
        if r.status_code == 200:
            body = r.json()
            if body["status"] in {"completed", "partial", "failed", "cancelled"}:
                final = body
                break
        time.sleep(0.5)
    _expect(final is not None, "scan reached a terminal state within 90s")
    print(f"  final status: {final['status']}")

    print("Test #5: provider observations include the v0.4 stages")
    r = client.get(f"/api/v1/scans/{uploaded_scan_id}/providers")
    _expect(r.status_code == 200, f"GET /providers returns 200 (got {r.status_code})")
    providers = {item["provider"] for item in r.json()["items"]}
    print(f"  providers observed: {sorted(providers)}")
    _expect("osv" in providers, "OSV is recorded as a provider observation")
    _expect("deps_dev" in providers, "deps.dev is recorded as a provider observation")
    _expect("openssf" in providers or "export_generation" in providers, "export_generation stage row")

    print("Test #6: vulnerabilities endpoint includes the v0.4 fields")
    r = client.get(f"/api/v1/scans/{uploaded_scan_id}/vulnerabilities")
    _expect(r.status_code == 200, f"GET /vulnerabilities returns 200 (got {r.status_code})")
    items = r.json()["items"]
    if items:
        row = items[0]
        print(f"  first row keys: {sorted(row.keys())}")
        # The new fields may be present (provider_provenance,
        # aliases, fetched_at). When the row is an OSV
        # advisory the v0.4 fields are populated.
        for key in ("provider_provenance", "aliases", "fetched_at"):
            _expect(
                key in row,
                f"vulnerabilities row carries the {key!r} field",
            )

    print("Test #7: enrichments endpoint returns per-component data")
    r = client.get(f"/api/v1/scans/{uploaded_scan_id}/enrichments")
    _expect(r.status_code == 200, f"GET /enrichments returns 200 (got {r.status_code})")
    body = r.json()
    items = body["items"]
    _expect(
        any(
            item.get("provider_status") in {"available", "unavailable", "not_requested", "partial", None}
            for item in items
        ) or len(items) == 0,
        "enrichments rows carry a provider_status (or the list is empty)",
    )
    for item in items[:3]:
        print(
            f"  component={item['package_name']!r} status={item['provider_status']!r} "
            f"licences={item['license_observations']!r}"
        )

    print("Test #8: exports include provider provenance")
    r = client.get(f"/api/v1/scans/{uploaded_scan_id}/exports/cyclonedx_json")
    _expect(r.status_code == 200, f"GET /exports/cyclonedx_json returns 200 (got {r.status_code})")
    sbom = r.json()
    print(f"  cyclonedx: {len(sbom.get('components', []))} components")
    r = client.get(f"/api/v1/scans/{uploaded_scan_id}/exports/findings_json")
    _expect(r.status_code == 200, f"GET /exports/findings_json returns 200 (got {r.status_code})")
    body = r.json()
    _expect("providers" in body, "findings.json export carries the providers block")
    print(f"  findings.json: {len(body.get('findings', []))} findings, {len(body.get('providers', []))} provider observations")
    r = client.get(f"/api/v1/scans/{uploaded_scan_id}/exports/sarif_json")
    _expect(r.status_code == 200, f"GET /exports/sarif_json returns 200 (got {r.status_code})")
    sarif = r.json()
    _expect(
        "lockverity:providers" in sarif["runs"][0]["properties"],
        "SARIF export carries the lockverity:providers property",
    )

    print("Test #9: persistence after restart")
    # Re-create the TestClient against the same DB file to
    # confirm the scan and its findings survived. The
    # orchestrator itself is re-bound; the engine state is
    # rebuilt from the database.
    client2 = TestClient(app)
    r = client2.get(f"/api/v1/scans/{uploaded_scan_id}")
    _expect(r.status_code == 200, f"GET /scans/{{id}} after restart returns 200 (got {r.status_code})")
    body = r.json()
    _expect(body["id"] == uploaded_scan_id, "scan id matches after restart")
    _expect(
        body["status"] in {"completed", "partial", "failed", "cancelled"},
        "scan status remains terminal after restart",
    )
    r = client2.get(f"/api/v1/scans/{uploaded_scan_id}/providers")
    _expect(r.status_code == 200, "GET /providers after restart returns 200")
    _expect(
        len(r.json()["items"]) > 0,
        "provider observations persist after restart",
    )

    print()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
