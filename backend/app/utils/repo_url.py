"""Repository URL normalization for public GitHub repositories.

Lockverity is intentionally narrow at v0.1: it accepts a fixed shape of
public GitHub URL and rejects everything else. Adding new providers is a
deliberate change that should bump a configuration flag, not silently
broaden the parser.

Accepted forms
--------------

- ``https://github.com/{owner}/{name}``
- ``https://github.com/{owner}/{name}.git``

Rejected
--------

- non-GitHub hosts
- embedded credentials (``user:pass@``)
- invalid owner or repository names (per GitHub's rules)
- additional path segments (``/tree/main``, ``/blob/...``, etc.)
- non-https schemes (``git://``, ``ssh://``, ``http://``)
- fragments and query strings (defence in depth; we never need them)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

# GitHub username rules: alphanumeric or single hyphens, cannot start or
# end with a hyphen, max 39 characters.
_GITHUB_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
# GitHub repository name rules: alphanumeric, hyphens, underscores, dots;
# cannot start or end with a special character, max 100 characters.
_GITHUB_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
# Forbidden consecutive special characters in repo names.
_GITHUB_NAME_BAD_SEQ_RE = re.compile(r"(\.\.)|(--)|(__)")


class RepositoryUrlError(ValueError):
    """Raised when a URL cannot be normalized to a public GitHub repo."""


@dataclass(frozen=True, slots=True)
class NormalizedRepositoryUrl:
    """A canonical, validated GitHub URL.

    Attributes:
        host: Always ``github.com``.
        owner: Lowercased owner login.
        name: Lowercased repository name (without the ``.git`` suffix).
        canonical_url: The canonical HTTPS URL.
    """

    host: str
    owner: str
    name: str
    canonical_url: str


def normalize_github_url(url: str) -> NormalizedRepositoryUrl:
    """Normalize and validate a public GitHub repository URL.

    Raises :class:`RepositoryUrlError` for any input that does not match
    the accepted shape.
    """
    if not isinstance(url, str) or not url.strip():
        raise RepositoryUrlError("Repository URL is required.")

    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise RepositoryUrlError(f"Could not parse URL: {exc}") from exc

    if parts.scheme.lower() != "https":
        raise RepositoryUrlError("Only https:// URLs are accepted for public GitHub repositories.")
    if parts.fragment:
        raise RepositoryUrlError("URL fragments are not accepted.")
    if parts.query:
        raise RepositoryUrlError("URL query strings are not accepted.")
    if parts.username or parts.password:
        raise RepositoryUrlError("Embedded credentials are not accepted.")
    if parts.hostname is None or parts.hostname.lower() != "github.com":
        raise RepositoryUrlError("Only github.com hosts are accepted.")
    if parts.port is not None:
        raise RepositoryUrlError("Port components are not accepted.")

    path = parts.path.strip("/")
    if not path:
        raise RepositoryUrlError("Repository path is empty.")

    segments = [seg for seg in path.split("/") if seg]
    if len(segments) > 2:
        raise RepositoryUrlError("Additional path segments after /owner/name are not accepted.")
    if len(segments) < 2:
        raise RepositoryUrlError("URL must include both an owner and a repository name.")

    owner_raw, name_raw = segments
    owner = owner_raw
    name = name_raw

    # Strip a trailing .git from the repository name. Reject any other
    # suffix - it indicates a non-canonical URL we should not normalize.
    if name.lower().endswith(".git"):
        name = name[: -len(".git")]
        if not name:
            raise RepositoryUrlError("Repository name cannot be empty.")

    owner_l = owner
    name_l = name

    if not _GITHUB_OWNER_RE.match(owner_l):
        raise RepositoryUrlError(f"Invalid GitHub owner name: {owner!r}.")
    if not _GITHUB_NAME_RE.match(name_l):
        raise RepositoryUrlError(f"Invalid GitHub repository name: {name!r}.")
    if _GITHUB_NAME_BAD_SEQ_RE.search(name_l):
        raise RepositoryUrlError(f"Repository name contains forbidden sequences: {name!r}.")

    canonical = urlunsplit(("https", "github.com", f"{owner_l}/{name_l}", "", ""))
    return NormalizedRepositoryUrl(
        host="github.com",
        owner=owner_l,
        name=name_l,
        canonical_url=canonical,
    )
