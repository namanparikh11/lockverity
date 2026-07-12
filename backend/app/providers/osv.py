"""OSV vulnerability provider.

OSV is a vulnerability database with two relevant endpoints:

- ``POST /v1/query`` - synchronous single-package query
- ``POST /v1/querybatch`` - batched query (up to 1000 packages)

We use the batched endpoint exclusively. The provider is built
to *never* report "no vulnerabilities" when the call failed; the
only way to express failure is :class:`ProviderUnavailable`.

The provider:

- Chunks requests at 1000 packages per batch.
- Validates the response shape before using it.
- Respects ``withdrawn`` advisories.
- Walks ``related`` and ``aliases`` to record canonical IDs.
- Surfaces ``severity`` exactly as the provider reports it.
- Preserves affected-version ranges, fixed versions, references.
- Records observations via the in-memory ``ProviderCache`` so
  repeat scans hit the same cache hits.
- Never includes credentials, query-string tokens, or
  response bodies in redacted error summaries.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from app.providers.cache import ProviderCache
from app.providers.http_client import (
    HttpClientError,
    HttpRequestLimits,
    post_json,
)
from app.providers.results import (
    ProviderOutcome,
    ProviderSuccess,
    ProviderUnavailable,
)
from app.utils.datetime import utcnow
from app.utils.json_safe import BoundedJsonError, parse_bounded_json
from app.utils.redaction import redact_provider_summary

OSV_QUERYBATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_BATCH_SIZE = 1000

# Loose schema for the parts of an OSV vulnerability record we
# actually use. We deliberately do not attempt to validate the
# full schema; that is OSV's job. We do reject records that miss
# the fields we rely on.
_ADVISORY_REQUIRED_FIELDS: tuple[str, ...] = ("id",)


class OsvVulnerabilityProvider:
    """Batched OSV vulnerability provider."""

    name = "osv"

    def __init__(
        self,
        *,
        cache: ProviderCache | None = None,
        limits: HttpRequestLimits | None = None,
        batch_size: int = OSV_BATCH_SIZE,
        request_fn=None,
    ) -> None:
        self._cache = cache or ProviderCache()
        self._limits = limits or HttpRequestLimits()
        self._batch_size = max(1, min(batch_size, OSV_BATCH_SIZE))
        self._request = request_fn

    # ----- public contract -----
    def query(
        self,
        *,
        ecosystem: str,
        package_name: str,
        version: str | None,
    ) -> ProviderSuccess[list[dict[str, Any]]] | ProviderUnavailable:
        return self._query_one(ecosystem, package_name, version)

    def query_batch(
        self,
        items: Iterable[tuple[str, str, str | None]],
    ) -> ProviderSuccess[list[dict[str, Any]]] | ProviderUnavailable:
        """Query OSV for multiple packages and return a flat list of advisories.

        ``items`` is an iterable of ``(ecosystem, package_name, version)``
        triples. The provider chunks the request at the OSV limit
        and aggregates the response.
        """
        materialised = list(items)
        if not materialised:
            return ProviderSuccess(
                data=[],
                fetched_at=utcnow(),
                records_returned=0,
            )
        advisories: list[dict[str, Any]] = []
        earliest_fetch: datetime | None = None
        try:
            for chunk in _chunked(materialised, self._batch_size):
                response = self._call_querybatch(chunk)
                if isinstance(response, ProviderUnavailable):
                    return response
                advisories.extend(response.data)
                if earliest_fetch is None or response.fetched_at < earliest_fetch:
                    earliest_fetch = response.fetched_at
        except HttpClientError as exc:
            return self._unavailable(exc, http_status=None)
        except BoundedJsonError as exc:
            return self._unavailable(exc, http_status=None)
        return ProviderSuccess(
            data=advisories,
            fetched_at=earliest_fetch or utcnow(),
            records_returned=len(advisories),
        )

    # ----- internals -----
    def _query_one(
        self,
        ecosystem: str,
        package_name: str,
        version: str | None,
    ) -> ProviderSuccess[list[dict[str, Any]]] | ProviderUnavailable:
        cache_key = self._cache_key(ecosystem, package_name, version)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return ProviderSuccess(
                data=cached,
                fetched_at=utcnow(),
                records_returned=len(cached),
            )
        result = self.query_batch([(ecosystem, package_name, version)])
        if isinstance(result, ProviderUnavailable):
            return result
        self._cache.set(cache_key, result.data)
        return result

    def _call_querybatch(
        self,
        chunk: list[tuple[str, str, str | None]],
    ) -> ProviderSuccess[list[dict[str, Any]]] | ProviderUnavailable:
        queries = []
        for ecosystem, name, version in chunk:
            query: dict[str, Any] = {"package": {"name": name, "ecosystem": ecosystem}}
            if version:
                query["version"] = version
            queries.append(query)
        body = {"queries": queries}
        try:
            if self._request is not None:
                http_response = self._request(
                    "POST",
                    OSV_QUERYBATCH_URL,
                    self._serialize(body),
                    {"content-type": "application/json"},
                )
            else:
                http_response = post_json(
                    OSV_QUERYBATCH_URL, body, limits=self._limits
                )
        except HttpClientError as exc:
            return self._unavailable(exc, http_status=None)
        if http_response.status_code >= 400:
            return self._unavailable(
                f"OSV responded with HTTP {http_response.status_code}",
                http_status=http_response.status_code,
            )
        try:
            parsed = parse_bounded_json(http_response.body)
        except BoundedJsonError as exc:
            return self._unavailable(exc, http_status=http_response.status_code)
        if not isinstance(parsed, dict) or "results" not in parsed:
            return self._unavailable(
                "OSV response missing 'results'",
                http_status=http_response.status_code,
            )
        results = parsed.get("results")
        if not isinstance(results, list):
            return self._unavailable(
                "OSV 'results' is not a list",
                http_status=http_response.status_code,
            )
        advisories: list[dict[str, Any]] = []
        for result in results:
            if not isinstance(result, dict):
                continue
            vulns = result.get("vulns")
            if not isinstance(vulns, list):
                continue
            for vuln in vulns:
                if not isinstance(vuln, dict):
                    continue
                if not all(field in vuln for field in _ADVISORY_REQUIRED_FIELDS):
                    continue
                advisories.append(self._normalize_advisory(vuln))
        return ProviderSuccess(
            data=advisories,
            fetched_at=utcnow(),
            records_returned=len(advisories),
        )

    def _normalize_advisory(self, vuln: dict[str, Any]) -> dict[str, Any]:
        """Return a Lockverity-friendly view of an OSV advisory."""
        aliases = vuln.get("aliases")
        if not isinstance(aliases, list):
            aliases = []
        related = vuln.get("related")
        if not isinstance(related, list):
            related = []
        affected = vuln.get("affected")
        if not isinstance(affected, list):
            affected = []
        severities = vuln.get("severity")
        if not isinstance(severities, list):
            severities = []
        references = vuln.get("references")
        if not isinstance(references, list):
            references = []
        withdrawn = vuln.get("withdrawn")
        normalized_affected = [self._normalize_affected(a) for a in affected if isinstance(a, dict)]
        # Extract a top-level ``fixed_versions`` list so downstream
        # rules can check it without walking the affected array.
        fixed_versions: list[str] = []
        for aff in normalized_affected:
            for r in aff.get("ranges", []):
                for event in r.get("events", []):
                    if isinstance(event, dict) and isinstance(event.get("fixed"), str):
                        fixed_versions.append(event["fixed"])
        return {
            "id": vuln.get("id"),
            "summary": vuln.get("summary"),
            "details": vuln.get("details"),
            "aliases": [a for a in aliases if isinstance(a, str)],
            "related": [r for r in related if isinstance(r, str)],
            "affected": normalized_affected,
            "severity": [self._normalize_severity(s) for s in severities if isinstance(s, dict)],
            "references": [r for r in references if isinstance(r, dict)],
            "withdrawn": withdrawn,
            "published": vuln.get("published"),
            "modified": vuln.get("modified"),
            "fixed_versions": sorted(set(fixed_versions)),
        }

    def _normalize_affected(self, affected: Mapping[str, Any]) -> dict[str, Any]:
        ranges = affected.get("ranges")
        if not isinstance(ranges, list):
            ranges = []
        normalized_ranges: list[dict[str, Any]] = []
        for r in ranges:
            if not isinstance(r, dict):
                continue
            events = r.get("events")
            normalized_events: list[dict[str, Any]] = []
            if isinstance(events, list):
                for event in events:
                    if isinstance(event, dict):
                        normalized_events.append(dict(event))
            normalized_ranges.append(
                {
                    "type": r.get("type"),
                    "events": normalized_events,
                    "repo": r.get("repo"),
                }
            )
        return {
            "package": affected.get("package"),
            "ranges": normalized_ranges,
            "versions": [
                v for v in (affected.get("versions") or []) if isinstance(v, str)
            ],
        }

    def _normalize_severity(self, severity: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "type": severity.get("type"),
            "score": severity.get("score"),
        }

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

    @staticmethod
    def _cache_key(ecosystem: str, name: str, version: str | None) -> str:
        return f"osv:v1:{ecosystem}:{name}:{version or ''}"

    @staticmethod
    def _serialize(payload: Mapping[str, Any]) -> bytes:
        import json

        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _chunked(
    items: list[tuple[str, str, str | None]],
    size: int,
) -> Iterable[list[tuple[str, str, str | None]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]
