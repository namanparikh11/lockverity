"""API tests for the health and system-info endpoints."""

from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient


def test_health_ok(app_config) -> None:
    client = TestClient(app)
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["version"] == "0.1.0"
    assert body["environment"]
    assert "timestamp" in body


def test_health_does_not_fake_providers(app_config) -> None:
    client = TestClient(app)
    r = client.get("/api/v1/health")
    # The health endpoint must not include provider status payloads.
    assert "providers" not in r.json()
    assert "scans" not in r.json()


def test_system_info_shape(app_config) -> None:
    client = TestClient(app)
    r = client.get("/api/v1/system/info")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Lockverity"
    assert body["tagline"] == "Evidence-first software supply-chain assurance"
    assert body["api_prefix"] == "/api/v1"
    assert "archive_limits" in body
    assert "pagination" in body
    assert "provider_safety" in body
