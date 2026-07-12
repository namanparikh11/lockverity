"""GitHub URL and ref helpers.

This module is the only place in the application that knows
about GitHub-specific path layouts. The intake layer builds a
:func:`github_tarball_url` and a :func:`github_api_repo_url` from
a :class:`NormalizedRepositoryUrl`. The HTTP client validates
the resulting URLs against the allowlist before issuing any
request.
"""

from __future__ import annotations

import re

from app.utils.repo_url import NormalizedRepositoryUrl

# A SHA-1 commit ref is exactly 40 lowercase hex characters. A
# branch or tag name follows the loose Git ref rules: alnum,
# dot, dash, underscore, slash. We additionally reject the
# obvious injection vectors: anything starting with a dash, and
# anything that contains a path traversal segment.
_REF_RE = re.compile(r"^(?![-/])[A-Za-z0-9._/-]{1,255}$")
_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")


def is_valid_ref(ref: str) -> bool:
    """Return True if ``ref`` is a syntactically valid Git ref."""
    if not isinstance(ref, str) or not ref:
        return False
    if "\x00" in ref:
        return False
    if ".." in ref:
        return False
    if ref.startswith(("refs/", "/")):
        return False
    return _REF_RE.match(ref) is not None


def is_commit_sha(ref: str) -> bool:
    """Return True if ``ref`` looks like a commit SHA."""
    return isinstance(ref, str) and bool(_SHA_RE.match(ref))


def github_api_repo_url(normalized: NormalizedRepositoryUrl) -> str:
    """Build the public GitHub repository metadata URL."""
    return f"https://api.github.com/repos/{normalized.owner}/{normalized.name}"


def github_tarball_url(
    normalized: NormalizedRepositoryUrl,
    ref: str | None = None,
) -> str:
    """Build the GitHub tarball archive URL.

    GitHub serves tarballs at ``codeload.github.com`` so the
    download host is distinct from the API host. The download
    client must include both ``api.github.com`` and
    ``codeload.github.com`` in its allowlist.
    """
    target = ref or "HEAD"
    return f"https://codeload.github.com/{normalized.owner}/{normalized.name}/tar.gz/{target}"


GITHUB_DOWNLOAD_HOSTS: frozenset[str] = frozenset(
    {
        "api.github.com",
        "codeload.github.com",
    }
)
