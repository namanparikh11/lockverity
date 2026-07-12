"""OpenSSF Scorecard importer.

Lockverity imports published Scorecard JSON; it does **not** run
the Scorecard binary. The official public endpoint is
``https://api.securityscorecards.dev/projects/{platform}/{org}/{repo}``.

The importer preserves:

- ``check`` names
- ``score`` (0-10)
- ``reason`` (free text)
- ``evidence`` (URL list, when present)
- ``source timestamp`` (date the record was generated)
- availability state ("not_found" is not zero score)

The importer never treats a missing result as a zero score; a
missing result is :class:`ProviderUnavailable` and the
finding-rule layer will surface it as a ``provider_availability``
observation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.providers.cache import ProviderCache
from app.providers.http_client import (
    HttpClientError,
    HttpRequestLimits,
    get_bytes,
)
from app.providers.results import (
    ProviderOutcome,
    ProviderSuccess,
    ProviderUnavailable,
)
from app.utils.datetime import utcnow
from app.utils.json_safe import BoundedJsonError, parse_bounded_json
from app.utils.redaction import redact_provider_summary

SCORECARD_BASE = "https://api.securityscorecards.dev"
DEFAULT_TTL_SECONDS = 24 * 60 * 60  # scorecards update slowly


class ScorecardImporter:
    """Importer for published OpenSSF Scorecard results."""

    name = "openssf_scorecard"

    def __init__(
        self,
        *,
        cache: ProviderCache | None = None,
        limits: HttpRequestLimits | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        request_fn=None,
    ) -> None:
        self._cache = cache or ProviderCache()
        self._limits = limits or HttpRequestLimits()
        self._ttl_seconds = ttl_seconds
        self._request = request_fn

    # ----- public contract -----
    def read(self, canonical_url: str) -> ProviderSuccess[dict[str, Any]] | ProviderUnavailable:
        platform, org, repo = self._parse_canonical(canonical_url)
        if platform is None:
            return ProviderUnavailable(
                error_code="provider_invalid_input",
                error_summary="canonical URL must be github.com/{owner}/{name}",
                attempted_at=utcnow(),
                outcome=ProviderOutcome.UNAVAILABLE,
            )
        cache_key = f"scorecard:v1:{platform}:{org}:{repo}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return ProviderSuccess(
                data=cached,
                fetched_at=utcnow(),
                records_returned=1,
            )
        url = f"{SCORECARD_BASE}/projects/{platform}/{org}/{repo}"
        try:
            if self._request is not None:
                response = self._request("GET", url, b"", {})
            else:
                response = get_bytes(url, limits=self._limits)
        except HttpClientError as exc:
            return self._unavailable(exc, http_status=None)
        if response.status_code == 404:
            return self._not_found()
        if response.status_code >= 400:
            return self._unavailable(
                f"Scorecard API responded with HTTP {response.status_code}",
                http_status=response.status_code,
            )
        try:
            parsed = parse_bounded_json(response.body)
        except BoundedJsonError as exc:
            return self._unavailable(exc, http_status=response.status_code)
        if not isinstance(parsed, dict):
            return self._unavailable(
                "Scorecard response was not a JSON object",
                http_status=response.status_code,
            )
        normalized = self._normalize(parsed)
        self._cache.set(cache_key, normalized, ttl_seconds=self._ttl_seconds)
        return ProviderSuccess(
            data=normalized,
            fetched_at=utcnow(),
            records_returned=1,
        )

    # ----- internals -----
    @staticmethod
    def _parse_canonical(canonical_url: str) -> tuple[str | None, str | None, str | None]:
        if not isinstance(canonical_url, str) or not canonical_url:
            return None, None, None
        prefix = "https://github.com/"
        if not canonical_url.startswith(prefix):
            return None, None, None
        rest = canonical_url[len(prefix):].strip("/")
        parts = rest.split("/")
        if len(parts) < 2:
            return None, None, None
        return "github.com", parts[0], parts[1]

    def _normalize(self, data: Mapping[str, Any]) -> dict[str, Any]:
        checks_raw = data.get("checks")
        checks: list[dict[str, Any]] = []
        if isinstance(checks_raw, list):
            for entry in checks_raw:
                if not isinstance(entry, dict):
                    continue
                checks.append(self._normalize_check(entry))
        return {
            "score": data.get("score"),
            "scorecard_version": data.get("scorecard", {}).get("version")
            if isinstance(data.get("scorecard"), dict)
            else None,
            "commit": data.get("repo", {}).get("commit") if isinstance(data.get("repo"), dict) else None,
            "date": data.get("date"),
            "checks": checks,
            "source_provenance": "openssf_scorecard",
        }

    def _normalize_check(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        evidence: list[str] = []
        raw_evidence = entry.get("evidence")
        if isinstance(raw_evidence, list):
            for ev in raw_evidence:
                if isinstance(ev, str):
                    evidence.append(ev)
        return {
            "name": entry.get("name"),
            "score": entry.get("score"),
            "reason": entry.get("reason"),
            "evidence": evidence,
            "source_timestamp": entry.get("source_timestamp") or entry.get("last_updated"),
        }

    def _not_found(self) -> ProviderUnavailable:
        return ProviderUnavailable(
            error_code="provider_not_found",
            error_summary="Scorecard API returned 404; no published result for this repository",
            attempted_at=utcnow(),
            http_status=404,
            outcome=ProviderOutcome.UNAVAILABLE,
        )

    def _unavailable(
        self,
        exc_or_message: Any,
        *,
        http_status: int | None,
    ) -> ProviderUnavailable:
        raw = str(exc_or_message)
        return ProviderUnavailable(
            error_code="provider_unavailable",
            error_summary=redact_provider_summary(raw, max_length=500) or raw,
            attempted_at=utcnow(),
            http_status=http_status,
            outcome=ProviderOutcome.UNAVAILABLE,
        )


__all__ = ["SCORECARD_BASE", "ScorecardImporter"]


def scorecard_check_names() -> tuple[str, ...]:
    """Return the canonical Scorecard check names documented for v0.2.

    The tuple is informational; importers do not require them to
    be present (a future Scorecard release may add new checks).
    """
    return (
        "Binary-Artifacts",
        "Branch-Protection",
        "CI-Tests",
        "Code-Review",
        "Dangerous-Workflow",
        "Dependency-Update-Tool",
        "Fuzzing",
        "License",
        "Pinned-Dependencies",
        "SAST",
        "Security-Policy",
        "Signed-Releases",
        "Token-Permissions",
        "Vulnerabilities",
        "Webhooks",
    )


def missing_check_names(
    scorecard: Mapping[str, Any],
    expected: Iterable[str] = scorecard_check_names(),
) -> tuple[str, ...]:
    """Return the check names from ``expected`` that are not present in ``scorecard``."""
    present = {check.get("name") for check in scorecard.get("checks", []) if isinstance(check, dict)}
    return tuple(name for name in expected if name not in present)
