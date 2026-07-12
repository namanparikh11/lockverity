"""Tests for the intake API endpoints (GitHub + upload)."""

from __future__ import annotations

import io
import json
import tarfile
import zipfile
from typing import Any

import pytest
from app.main import app
from app.providers import github_provider
from fastapi.testclient import TestClient


class _FakeResponse:
    def __init__(
        self, status_code: int, body: bytes, headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.responses: dict[str, list[_FakeResponse]] = {}

    def queue(self, path: str, response: _FakeResponse) -> None:
        self.responses.setdefault(path, []).append(response)

    def _consume(self, url: str) -> _FakeResponse:
        from urllib.parse import urlsplit

        path = urlsplit(url).path
        self.calls.append(path)
        queue = self.responses.get(path, [])
        if not queue:
            return _FakeResponse(500, b"", {})
        return queue.pop(0)

    def get_json(self, url: str, **_: Any) -> _FakeResponse:
        from app.utils.bounded_http import BoundedHttpError

        response = self._consume(url)
        if response.status_code == 404:
            raise BoundedHttpError("http_not_found", "Upstream returned 404 Not Found.")
        if 500 <= response.status_code < 600:
            raise BoundedHttpError(
                "http_server_error",
                f"Upstream returned {response.status_code}.",
                http_status=response.status_code,
            )
        return response

    def download(self, url: str, **_: Any) -> _FakeResponse:
        from app.utils.bounded_http import BoundedHttpError

        response = self._consume(url)
        if 500 <= response.status_code < 600:
            raise BoundedHttpError(
                "http_server_error",
                f"Upstream returned {response.status_code}.",
                http_status=response.status_code,
            )
        return response

    def close(self) -> None:
        return None


@pytest.fixture
def fake_client(monkeypatch) -> _FakeClient:
    client = _FakeClient()

    def _build(**kwargs):
        return client

    monkeypatch.setattr(github_provider, "build_client", _build)
    return client


@pytest.fixture
def client(app_config):
    return TestClient(app)


def _build_tarball_bytes() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"# hi"
        info = tarfile.TarInfo("README.md")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_github_endpoint_creates_repository_scan_and_workspace(client, fake_client) -> None:
    sha = "0123456789abcdef0123456789abcdef01234567"
    fake_client.queue(
        "/repos/octocat/Hello-World",
        _FakeResponse(
            200,
            json.dumps(
                {
                    "default_branch": "main",
                    "visibility": "public",
                    "archived": False,
                }
            ).encode("utf-8"),
            {"Content-Type": "application/json"},
        ),
    )
    fake_client.queue(
        "/repos/octocat/Hello-World/branches/main",
        _FakeResponse(
            200,
            json.dumps({"name": "main", "commit": {"sha": sha}}).encode("utf-8"),
            {"Content-Type": "application/json"},
        ),
    )
    fake_client.queue(
        f"/octocat/Hello-World/tar.gz/{sha}",
        _FakeResponse(
            200,
            _build_tarball_bytes(),
            {"Content-Type": "application/x-gzip"},
        ),
    )
    response = client.post(
        "/api/v1/repositories/github",
        json={"canonical_url": "https://github.com/octocat/Hello-World"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["repository"]["provider"] == "github"
    assert body["scan"]["status"] == "queued"
    assert body["workspace"]["kind"] == "github"
    assert body["workspace"]["state"] == "ready"
    assert body["intake_summary"]["resolved_commit_sha"] == sha


def test_github_endpoint_rejects_non_github_url(client) -> None:
    response = client.post(
        "/api/v1/repositories/github",
        json={"canonical_url": "https://example.com/octocat/Hello-World"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_github_endpoint_rejects_unsafe_request_ref(client) -> None:
    response = client.post(
        "/api/v1/repositories/github",
        json={
            "canonical_url": "https://github.com/octocat/Hello-World",
            "requested_ref": "../etc",
        },
    )
    assert response.status_code == 422


def test_upload_endpoint_creates_scan_and_workspace(client) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", b"hi")
    body = buf.getvalue()
    response = client.post(
        "/api/v1/repositories/upload",
        files={"file": ("hello.zip", body, "application/zip")},
    )
    assert response.status_code == 201
    result = response.json()
    assert result["workspace"]["kind"] == "uploaded_archive"
    assert result["workspace"]["state"] == "ready"
    assert result["workspace"]["file_count"] == 1


def test_upload_endpoint_rejects_non_zip_extension(client) -> None:
    body = b"not a zip"
    response = client.post(
        "/api/v1/repositories/upload",
        files={"file": ("hello.txt", body, "application/zip")},
    )
    assert response.status_code == 422


def test_upload_endpoint_rejects_traversal(client) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.txt", b"evil")
    body = buf.getvalue()
    response = client.post(
        "/api/v1/repositories/upload",
        files={"file": ("evil.zip", body, "application/zip")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "archive_unsafe"
