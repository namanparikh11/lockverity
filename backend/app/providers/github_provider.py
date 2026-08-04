"""GitHub public-API provider.

This module implements the *intake*-only piece of the GitHub
provider:

- :func:`fetch_repository_metadata` resolves the default branch
  and the commit SHA for a requested ref, never touching the
  caller's branch or tag data beyond what the GitHub API
  reports.
- :func:`download_tarball` downloads a tarball for a specific
  commit SHA, never for an unverified ref. The ref is verified
  against the API first; the tarball URL embeds the SHA, not the
  user-supplied ref, so a repository whose default branch moves
  between two scans still produces deterministic archive
  contents.

The provider never:

- follows a redirect to a host outside the configured allowlist;
- reads from a URL embedded in repository-supplied data;
- exposes the configured token to the API layer or to the
  database.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.utils.bounded_http import (
    BoundedHttpClient,
    BoundedHttpError,
)
from app.utils.datetime import utcnow
from app.utils.github import (
    GITHUB_DOWNLOAD_HOSTS,
    github_api_repo_url,
    github_tarball_url,
    is_commit_sha,
)
from app.utils.json_safe import BoundedJsonError, parse_bounded_json
from app.utils.redaction import redact_provider_summary

logger = logging.getLogger("lockverity.github")

GITHUB_PROVIDER_NAME = "github"


class GitHubIntakeError(Exception):
    """Raised when the GitHub intake cannot complete safely."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}

    def redacted_summary(self, *, max_length: int = 500) -> str:
        return redact_provider_summary(self.message, max_length=max_length) or self.message


@dataclass(frozen=True, slots=True)
class GitHubRepositoryMetadata:
    owner: str
    name: str
    canonical_url: str
    default_branch: str
    resolved_commit_sha: str
    visibility: str
    archived: bool
    description: str | None


@dataclass(frozen=True, slots=True)
class GitHubTarball:
    body: bytes
    content_sha256: str
    content_length: int
    resolved_commit_sha: str
    etag: str | None
    last_modified: str | None


def build_client(
    *,
    token: str | None,
    user_agent: str,
    allowlist: Iterable[str] = GITHUB_DOWNLOAD_HOSTS,
) -> BoundedHttpClient:
    return BoundedHttpClient(
        token=token,
        user_agent=user_agent,
        allowlist=allowlist,
    )


def fetch_repository_metadata(
    client: BoundedHttpClient,
    *,
    owner: str,
    name: str,
    canonical_url: str,
    requested_ref: str | None,
) -> GitHubRepositoryMetadata:
    """Resolve a canonical repository to a default branch + commit SHA.

    If ``requested_ref`` is a commit SHA the metadata call is
    skipped; we trust the SHA exactly. Otherwise the repository
    metadata is fetched to discover the default branch and the
    requested ref is resolved via the branches or tags API.
    """
    # Case 1: caller supplied a full commit SHA. We do not
    # contact the API for metadata in this case; we only need
    # the tarball to succeed.
    if requested_ref is not None and is_commit_sha(requested_ref):
        return GitHubRepositoryMetadata(
            owner=owner,
            name=name,
            canonical_url=canonical_url,
            default_branch="",
            resolved_commit_sha=requested_ref,
            visibility="public",
            archived=False,
            description=None,
        )

    api_url = github_api_repo_url(
        # ``NormalizedRepositoryUrl`` is the only public type we
        # depend on; we build a duck-typed minimal instance.
        _stub_normalized(owner, name, canonical_url)
    )
    try:
        response = client.get_json(api_url)
    except BoundedHttpError as exc:
        raise GitHubIntakeError(
            _http_code_to_intake_code(exc.code, exc.message),
            exc.message,
            http_status=exc.http_status,
        ) from exc

    try:
        payload = parse_bounded_json(response.body)
    except BoundedJsonError as exc:
        raise GitHubIntakeError(
            "github_invalid_response",
            f"Could not parse repository metadata: {exc}",
        ) from exc

    if not isinstance(payload, dict):
        raise GitHubIntakeError(
            "github_invalid_response",
            "Repository metadata response was not a JSON object.",
        )

    default_branch = str(payload.get("default_branch") or "").strip()
    if not default_branch:
        raise GitHubIntakeError(
            "github_no_default_branch",
            "Repository metadata did not include a default branch.",
        )
    visibility = str(payload.get("visibility") or "public").lower()
    archived = bool(payload.get("archived", False))
    description = payload.get("description")

    # If the user did not supply a ref, the SHA is HEAD on the
    # default branch. We need the actual commit SHA; ask the
    # API for it.
    ref = requested_ref or default_branch
    resolved = _resolve_ref_to_sha(client, owner, name, ref)
    return GitHubRepositoryMetadata(
        owner=owner,
        name=name,
        canonical_url=canonical_url,
        default_branch=default_branch,
        resolved_commit_sha=resolved,
        visibility=visibility,
        archived=archived,
        description=description if isinstance(description, str) else None,
    )


def _resolve_ref_to_sha(
    client: BoundedHttpClient,
    owner: str,
    name: str,
    ref: str,
) -> str:
    """Resolve ``ref`` (branch or tag) to a full commit SHA.

    v2.1.1: ``_resolve_ref_to_sha`` is called AFTER
    :func:`fetch_repository_metadata` has already
    succeeded, so the repository itself is known to
    exist and be public. A 404 from the branches API
    or the tags API in this scope therefore means the
    ref does not exist on a known-existing repository,
    not that the repository is private or absent. The
    helper raises ``github_invalid_ref`` in that case
    so the API response can carry a distinct,
    actionable user message and a separate
    ``invalid_ref`` envelope code (the "private
    repository" and "URL is wrong" cases are surfaced
    upstream as ``github_not_found`` and are not
    conflated with the missing-ref case here).
    """
    # The branches API returns the commit SHA; this is the
    # documented public endpoint. The tags API is consulted
    # only when the branch lookup fails with 404 - tags share
    # the namespace with branches and the two endpoints may
    # answer differently depending on how the repository is
    # configured.
    branch_url = f"https://api.github.com/repos/{owner}/{name}/branches/{ref}"
    branch_404 = False
    try:
        branch_response = client.get_json(branch_url)
    except BoundedHttpError as exc:
        if exc.code != "http_not_found":
            raise GitHubIntakeError(
                _http_code_to_intake_code(exc.code, exc.message),
                exc.message,
                http_status=exc.http_status,
            ) from exc
        branch_response = None
        branch_404 = True

    if branch_response is not None:
        try:
            payload = parse_bounded_json(branch_response.body)
        except BoundedJsonError as exc:
            raise GitHubIntakeError(
                "github_invalid_response",
                f"Could not parse branch response: {exc}",
            ) from exc
        if not isinstance(payload, dict):
            raise GitHubIntakeError(
                "github_invalid_response",
                "Branch response was not a JSON object.",
            )
        commit = payload.get("commit")
        if not isinstance(commit, dict):
            raise GitHubIntakeError(
                "github_invalid_response",
                "Branch response did not include a commit.",
            )
        sha = commit.get("sha")
        if not isinstance(sha, str) or not is_commit_sha(sha):
            raise GitHubIntakeError(
                "github_invalid_response",
                "Branch response did not include a commit SHA.",
            )
        return sha

    # v2.1.1: the ref was not found as a branch. Try the
    # tags endpoint, but distinguish "tag endpoint
    # returned 404" from any other failure so we can map
    # the "neither branch nor tag" case to
    # ``github_invalid_ref`` (not ``github_not_found``).
    tag_url = f"https://api.github.com/repos/{owner}/{name}/git/refs/tags/{ref}"
    tag_404 = False
    try:
        tag_response = client.get_json(tag_url)
    except BoundedHttpError as exc:
        if exc.code == "http_not_found":
            tag_404 = True
            tag_response = None
        else:
            raise GitHubIntakeError(
                _http_code_to_intake_code(exc.code, exc.message),
                exc.message,
                http_status=exc.http_status,
            ) from exc

    if branch_404 and tag_404:
        # Both endpoints returned 404. The repository
        # metadata fetch already succeeded, so the
        # repository exists and is public; the ref
        # simply does not exist on it. The ``details``
        # envelope below carries the requested ref
        # (already a known-safe string by the time it
        # reached this code path) and the
        # ``http_status=422`` mapping gives the client
        # a distinct, actionable envelope code.
        raise GitHubIntakeError(
            "github_invalid_ref",
            f"Ref {ref!r} not found on the repository "
            f"({owner}/{name}). The ref may be a branch, "
            "tag, or full commit SHA; the value did not "
            "match any of the three namespaces.",
            http_status=422,
        )

    assert tag_response is not None  # only reachable when not tag_404
    try:
        payload = parse_bounded_json(tag_response.body)
    except BoundedJsonError as exc:
        raise GitHubIntakeError(
            "github_invalid_response",
            f"Could not parse tag response: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise GitHubIntakeError(
            "github_invalid_response",
            "Tag response was not a JSON object.",
        )
    object_ = payload.get("object")
    if not isinstance(object_, dict):
        raise GitHubIntakeError(
            "github_invalid_response",
            "Tag response did not include an object.",
        )
    obj_type = object_.get("type")
    sha = object_.get("sha")
    if obj_type == "commit" and isinstance(sha, str) and is_commit_sha(sha):
        return sha
    if obj_type == "tag" and isinstance(sha, str) and is_commit_sha(sha):
        # Annotated tag: dereference once more.
        deref_url = f"https://api.github.com/repos/{owner}/{name}/git/tags/{sha}"
        deref = client.get_json(deref_url)
        deref_payload = parse_bounded_json(deref.body)
        if not isinstance(deref_payload, dict):
            raise GitHubIntakeError(
                "github_invalid_response",
                "Tag dereference response was not a JSON object.",
            )
        target = deref_payload.get("object")
        if not isinstance(target, dict):
            raise GitHubIntakeError(
                "github_invalid_response",
                "Tag dereference did not include an object.",
            )
        target_sha = target.get("sha")
        if not isinstance(target_sha, str) or not is_commit_sha(target_sha):
            raise GitHubIntakeError(
                "github_invalid_response",
                "Tag dereference did not include a commit SHA.",
            )
        return target_sha
    raise GitHubIntakeError(
        "github_invalid_response",
        "Tag response did not include a recognizable commit SHA.",
    )


def download_tarball(
    client: BoundedHttpClient,
    *,
    owner: str,
    name: str,
    commit_sha: str,
    max_response_bytes: int,
    timeout_seconds: float,
) -> GitHubTarball:
    """Download the tarball for ``commit_sha``.

    The URL embeds the SHA, not a branch or tag name, so the
    download is deterministic for a given commit.
    """
    if not is_commit_sha(commit_sha):
        raise GitHubIntakeError(
            "github_invalid_ref",
            "Refused to download a tarball for a non-SHA ref.",
        )
    # Build a stub normalized URL purely for the URL builder.
    stub = _stub_normalized(owner, name, f"https://github.com/{owner}/{name}")
    tarball_url = github_tarball_url(stub, ref=commit_sha)
    try:
        response = client.download(
            tarball_url,
            max_response_bytes=max_response_bytes,
            timeout_seconds=timeout_seconds,
        )
    except BoundedHttpError as exc:
        raise GitHubIntakeError(
            _http_code_to_intake_code(exc.code, exc.message),
            exc.message,
            http_status=exc.http_status,
        ) from exc
    import hashlib

    sha = hashlib.sha256(response.body).hexdigest()
    return GitHubTarball(
        body=response.body,
        content_sha256=sha,
        content_length=len(response.body),
        resolved_commit_sha=commit_sha,
        etag=response.headers.get("ETag") or response.headers.get("etag"),
        last_modified=response.headers.get("Last-Modified")
        or response.headers.get("last-modified"),
    )


def _http_code_to_intake_code(code: str, message: str) -> str:
    if code == "http_not_found":
        return "github_not_found"
    if code == "http_rate_limited":
        return "github_rate_limited"
    if code == "http_unauthorized":
        return "github_unauthorized"
    if code == "http_forbidden":
        return "github_forbidden"
    if code in {"http_timeout", "http_connection_error"}:
        return "github_unavailable"
    if code == "http_response_too_large":
        return "github_response_too_large"
    if code.startswith("http_host_forbidden") or code.startswith("http_redirect_forbidden"):
        return "github_host_forbidden"
    return "github_unavailable"


@dataclass(frozen=True, slots=True)
class _NormalizedStub:
    owner: str
    name: str
    canonical_url: str


def _stub_normalized(owner: str, name: str, canonical_url: str) -> _NormalizedStub:
    return _NormalizedStub(owner=owner, name=name, canonical_url=canonical_url)


__all__ = [
    "GITHUB_PROVIDER_NAME",
    "GitHubIntakeError",
    "GitHubRepositoryMetadata",
    "GitHubTarball",
    "build_client",
    "download_tarball",
    "fetch_repository_metadata",
]


# Reference utcnow so static analyzers see the dependency.
_ = utcnow
