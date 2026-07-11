"""API tests for the repository endpoints."""

from __future__ import annotations

import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client(app_config):
    return TestClient(app)


def test_create_repository_201(client) -> None:
    r = client.post(
        "/api/v1/repositories",
        json={"canonical_url": "https://github.com/octocat/Hello-World"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["owner"] == "octocat"
    assert body["name"] == "Hello-World"
    assert body["canonical_url"] == "https://github.com/octocat/Hello-World"
    assert body["provider"] == "github"
    assert body["source_type"] == "github"


def test_create_repository_idempotent(client) -> None:
    payload = {"canonical_url": "https://github.com/octocat/Hello-World"}
    a = client.post("/api/v1/repositories", json=payload)
    b = client.post("/api/v1/repositories", json=payload)
    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["id"] == b.json()["id"]


def test_create_repository_rejects_non_github(client) -> None:
    r = client.post(
        "/api/v1/repositories",
        json={"canonical_url": "https://example.com/foo/bar"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_create_repository_rejects_extra_path(client) -> None:
    r = client.post(
        "/api/v1/repositories",
        json={"canonical_url": "https://github.com/octocat/Hello-World/tree/main"},
    )
    assert r.status_code == 422


def test_create_repository_rejects_credentials(client) -> None:
    r = client.post(
        "/api/v1/repositories",
        json={"canonical_url": "https://user:pass@github.com/octocat/Hello-World"},
    )
    assert r.status_code == 422


def test_create_repository_rejects_empty_body(client) -> None:
    r = client.post("/api/v1/repositories", json={})
    assert r.status_code == 422


def test_list_repositories_pagination(client) -> None:
    for i in range(3):
        client.post(
            "/api/v1/repositories",
            json={"canonical_url": f"https://github.com/o{i}/r{i}"},
        )
    r = client.get("/api/v1/repositories?page=1&page_size=2")
    assert r.status_code == 200
    body = r.json()
    assert body["pagination"]["total"] == 3
    assert len(body["items"]) == 2


def test_list_repositories_clamps_oversized_page_size(client) -> None:
    r = client.get("/api/v1/repositories?page=1&page_size=999999")
    assert r.status_code == 200
    assert r.json()["pagination"]["page_size"] <= 200


def test_get_repository_404(client) -> None:
    r = client.get("/api/v1/repositories/9999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_get_repository_ok(client) -> None:
    r = client.post(
        "/api/v1/repositories",
        json={"canonical_url": "https://github.com/octocat/Hello-World"},
    )
    rid = r.json()["id"]
    r2 = client.get(f"/api/v1/repositories/{rid}")
    assert r2.status_code == 200
    assert r2.json()["id"] == rid
