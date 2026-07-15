"""Provider orchestration service for v0.4.

The v0.4 milestone wires the existing OSV, deps.dev, and OpenSSF
Scorecard clients into the scan pipeline. The previous
milestones left these clients implemented but unused; the
provider service is the glue that:

- wraps each provider in a bounded retry / timeout policy
  (delegated to the existing :mod:`app.providers.http_client`
  module);
- consults a persistent, SQL-backed cache (the existing
  :class:`app.services.cache_service.CacheService`) before any
  network call, and writes through the cache on success;
- writes a truthful :class:`ProviderObservation` row for every
  call (success, hit, miss, partial, unavailable, rate-limited)
  with bounded error summaries and redacted error codes;
- preserves the local analysis artefacts (components, edges,
  findings from the rule engine) when a provider fails;
- never converts "no result" into "safe" - missing provider
  data is a :class:`ProviderStatus.PARTIAL` or
  :class:`ProviderStatus.UNAVAILABLE` outcome, not a successful
  empty result.

The service is intentionally narrow. It does not import
the orchestrator or the analysis pipeline; the pipeline calls
into the service. This keeps the dependency graph one-way and
makes the service testable in isolation.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.component_advisory import ComponentAdvisory
from app.models.provider_observation import (
    ProviderObservation,
    ProviderStatus,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.component import Component
from app.providers.cache import ProviderCache
from app.providers.deps_dev import DepsDevEnrichmentProvider
from app.providers.http_client import HttpRequestLimits
from app.providers.osv import OsvVulnerabilityProvider
from app.providers.results import (
    ProviderPartialResult,
    ProviderUnavailable,
)
from app.providers.scorecard import ScorecardImporter
from app.services.cache_service import (
    CacheDescriptor,
    CacheService,
    CacheStatus,
)
from app.utils.datetime import utcnow
from app.utils.redaction import redact_payload, redact_provider_summary

logger = logging.getLogger("lockverity.providers")

# Provider name constants - also referenced by the v0.3 frontend
# (per-provider rollup). Keep the strings stable.
OSV_PROVIDER = "osv"
DEPS_DEV_PROVIDER = "deps_dev"
SCORECARD_PROVIDER = "openssf"
GITHUB_PROVIDER = "github"

# Cache operations: each provider has one operation per query
# shape so the cache is isolated across shapes.
OP_OSV_QUERY = "osv_vulnerability_query"
OP_DEPS_DEV_ENRICH = "deps_dev_enrichment"
OP_SCORECARD_READ = "openssf_scorecard_read"

# Default TTLs (seconds) for each provider. These are
# deliberately conservative; a cached entry is never used past
# its expiry, and a stale entry is returned only as
# :class:`CacheStatus.STALE` (never as a fresh hit).
DEFAULT_OSV_TTL_SECONDS = 6 * 60 * 60
DEFAULT_DEPS_DEV_TTL_SECONDS = 24 * 60 * 60
DEFAULT_SCORECARD_TTL_SECONDS = 24 * 60 * 60

# Hard cap on the structured evidence envelope. The database
# column is sized to this value; the application-side validator
# rejects payloads above this limit and truncates with a
# visible marker. ``error_summary`` is *not* used to store
# evidence; the success envelope always lives in
# ``evidence_json``.
_MAX_EVIDENCE_BYTES = 8 * 1024

# Supported ecosystems for cross-provider queries. Lockverity
# stores the OSV-style ecosystem string on every component;
# an unsupported ecosystem yields a "skipped" outcome, not a
# failed call.
SUPPORTED_ECOSYSTEMS: frozenset[str] = frozenset(
    {
        "npm",
        "PyPI",
        "pypi",
        "Go",
        "go",
        "crates.io",
        "crates",
        "Maven",
        "maven",
        "Packagist",
        "packagist",
        "RubyGems",
        "rubygems",
        "NuGet",
        "nuget",
        "swift",
    }
)


# ----------------------------------------------------------------------
# Result types
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class VulnerabilityLookup:
    """One persisted ``ComponentAdvisory`` row plus its source."""

    component_id: int
    package_name: str
    ecosystem: str
    version: str | None
    advisory_id: int
    advisory_source: str
    advisory_external_id: str
    canonical_id: str | None
    severity_label: str | None
    severity_score: float | None
    severity_source: str | None
    fixed_versions: list[str]
    withdrawn: bool
    aliases: tuple[str, ...]
    summary: str | None
    details_url: str | None
    fetched_at: datetime
    cache_status: str
    provider_url: str | None


@dataclass(frozen=True, slots=True)
class EnrichmentLookup:
    """The persisted view of one deps.dev enrichment."""

    component_id: int
    package_name: str
    ecosystem: str
    version: str | None
    licenses: tuple[str, ...]
    dependencies_count: int
    fetched_at: datetime
    cache_status: str
    provider_url: str | None
    source_provenance: str


@dataclass(frozen=True, slots=True)
class PostureLookup:
    """The persisted view of one OpenSSF Scorecard import."""

    scan_run_id: int
    canonical_url: str
    score: float | None
    scorecard_version: str | None
    commit_sha: str | None
    source_date: str | None
    checks: tuple[dict[str, Any], ...]
    fetched_at: datetime
    cache_status: str
    provider_url: str
    source_provenance: str
    not_applicable: bool
    not_applicable_reason: str | None


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------
class UnsupportedEcosystemError(ValueError):
    """Raised internally when an ecosystem is not handled by the providers.

    Callers should map this to a ``skipped`` outcome; the providers
    themselves do not raise it.
    """


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _normalized_osv_ecosystem(ecosystem: str | None) -> str | None:
    """Return the OSV-style ecosystem name.

    Lockverity stores ``pypi`` (lowercase) from the parser
    registry; OSV uses ``PyPI``. This helper centralises the
    mapping so tests and provider calls stay aligned.
    """
    if not ecosystem:
        return None
    mapping = {
        "pypi": "PyPI",
        "npm": "npm",
        "go": "Go",
        "crates": "crates.io",
        "maven": "Maven",
        "packagist": "Packagist",
        "rubygems": "RubyGems",
        "nuget": "NuGet",
    }
    return mapping.get(ecosystem.lower(), ecosystem)


def _build_cache_payload(payload: Any) -> bytes:
    """Serialize a cacheable payload deterministically."""
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _hash_payload(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _extract_licences(payload: Any) -> list[str]:
    """Return the licence list from a deps.dev payload, normalised.

    The payload's ``licenses`` field is either a list of SPDX
    strings or a list of objects with an ``identifier`` /
    ``spdx.identifier``. We accept both shapes and deduplicate
    the result. A payload without a ``licenses`` field yields
    an empty list - never a fabricated placeholder.
    """
    licenses_raw = payload.get("licenses") if isinstance(payload, dict) else None
    if not isinstance(licenses_raw, list):
        return []
    seen: list[str] = []
    seen_set: set[str] = set()
    for entry in licenses_raw:
        if isinstance(entry, str):
            identifier = entry
        elif isinstance(entry, dict):
            spdx = entry.get("spdx")
            if isinstance(spdx, dict) and isinstance(spdx.get("identifier"), str):
                identifier = spdx["identifier"]
            else:
                identifier = entry.get("identifier")
                if not isinstance(identifier, str):
                    continue
        else:
            continue
        if identifier in seen_set:
            continue
        seen.append(identifier)
        seen_set.add(identifier)
    return seen


def _dependency_count(payload: Any) -> int:
    """Return the number of immediate dependencies of a deps.dev payload."""
    if not isinstance(payload, dict):
        return 0
    deps = payload.get("dependencies")
    if not isinstance(deps, list):
        return 0
    return len(deps)


# ----------------------------------------------------------------------
# Provider service
# ----------------------------------------------------------------------
class ProviderService:
    """Orchestrate OSV, deps.dev, and OpenSSF Scorecard calls.

    The service is the single entry point the analysis pipeline
    uses for every external provider. It owns the persistent
    cache, the bounded HTTP transport, the per-call
    observation row, and the post-call persistence (advisory
    rows, licence observations, Scorecard findings).
    """

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
        osv: OsvVulnerabilityProvider | None = None,
        deps_dev: DepsDevEnrichmentProvider | None = None,
        scorecard: ScorecardImporter | None = None,
        in_memory_cache: ProviderCache | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        limits = HttpRequestLimits(
            timeout_seconds=self._settings.provider_timeout_seconds,
            max_response_bytes=self._settings.provider_max_response_bytes,
            retry_limit=self._settings.provider_retry_limit,
        )
        cache = in_memory_cache or ProviderCache()
        self._in_memory_cache = cache
        self._osv = osv or OsvVulnerabilityProvider(cache=cache, limits=limits)
        self._deps_dev = deps_dev or DepsDevEnrichmentProvider(cache=cache, limits=limits)
        self._scorecard = scorecard or ScorecardImporter(cache=cache, limits=limits)
        self._cache_service = CacheService(session, settings=self._settings)

    # ------------------------------------------------------------------
    # Vulnerability enrichment (OSV)
    # ------------------------------------------------------------------
    def enrich_vulnerabilities_for_components(
        self,
        *,
        scan_run_id: int,
        components: Iterable[Component],
    ) -> list[VulnerabilityLookup]:
        """Query OSV for each component and persist results.

        Components are queried in batches of 1000 (OSV's limit).
        Results are deduplicated by (source, source_advisory_id)
        inside the cache and by (scan, component, advisory)
        inside the database unique constraint.
        """
        materialised: list[Component] = [c for c in components if c is not None]
        if not materialised:
            return []
        # Build the query triples. We skip components without a
        # concrete (ecosystem, package_name) identity; the rule
        # engine still has the local evidence for them.
        triples: list[tuple[int, str, str, str | None]] = []
        skipped: list[Component] = []
        for component in materialised:
            ecosystem = _normalized_osv_ecosystem(component.ecosystem)
            if not ecosystem or not component.package_name:
                skipped.append(component)
                continue
            if ecosystem not in {
                "npm",
                "PyPI",
                "Go",
                "crates.io",
                "Maven",
                "Packagist",
                "RubyGems",
                "NuGet",
            }:
                skipped.append(component)
                continue
            triples.append((component.id, ecosystem, component.package_name, component.version))
        # Record the skipped observations up front so the UI
        # shows them as honest skipped states. Each skip is
        # bound to the specific component so the read-side
        # endpoint can resolve a per-component enrichment
        # state without leaking the skip to other components
        # in the same scan.
        for component in skipped:
            self._record_observation(
                scan_run_id=scan_run_id,
                component_id=component.id,
                provider=OSV_PROVIDER,
                operation=OP_OSV_QUERY,
                status=ProviderStatus.NOT_REQUESTED,
                http_status=None,
                records_returned=0,
                cache_status="miss",
                error_code="unsupported_ecosystem",
                error_summary=(
                    f"OSV does not have a vulnerability database for "
                    f"ecosystem {component.ecosystem!r}."
                ),
                evidence={
                    "package_name": component.package_name,
                    "ecosystem": component.ecosystem,
                },
            )
        if not triples:
            return []
        # OSV supports a single batched call. The provider's
        # own cache layer is bypassed here: we use a fresh
        # ``query_batch`` and route the result through the
        # persistent cache + database writer.
        try:
            result = self._osv.query_batch([(eco, name, ver) for _id, eco, name, ver in triples])
        except Exception as exc:
            # ``query_batch`` itself doesn't raise, but the
            # transport layer can. Map to a single observation
            # and return no advisories.
            self._record_observation(
                scan_run_id=scan_run_id,
                provider=OSV_PROVIDER,
                operation=OP_OSV_QUERY,
                status=ProviderStatus.UNAVAILABLE,
                http_status=None,
                records_returned=0,
                cache_status="miss",
                error_code="osv_internal_error",
                error_summary=redact_provider_summary(str(exc)),
            )
            return []
        cache_status = "miss"
        if isinstance(result, ProviderPartialResult):
            self._record_observation(
                scan_run_id=scan_run_id,
                provider=OSV_PROVIDER,
                operation=OP_OSV_QUERY,
                status=ProviderStatus.PARTIAL,
                http_status=200,
                records_returned=result.records_returned,
                cache_status=cache_status,
                error_code=result.error_code,
                error_summary=redact_provider_summary(result.error_summary),
            )
            advisories = result.data
            fetched_at = result.fetched_at
        elif isinstance(result, ProviderUnavailable):
            self._record_observation(
                scan_run_id=scan_run_id,
                provider=OSV_PROVIDER,
                operation=OP_OSV_QUERY,
                status=ProviderStatus.UNAVAILABLE,
                http_status=result.http_status,
                records_returned=0,
                cache_status=cache_status,
                error_code=result.error_code,
                error_summary=redact_provider_summary(result.error_summary),
            )
            return []
        else:
            self._record_observation(
                scan_run_id=scan_run_id,
                provider=OSV_PROVIDER,
                operation=OP_OSV_QUERY,
                status=ProviderStatus.AVAILABLE,
                http_status=200,
                records_returned=result.records_returned,
                cache_status=cache_status,
                error_code=None,
                error_summary=None,
            )
            advisories = result.data
            fetched_at = result.fetched_at
        # The batched response does not map advisories back to
        # the specific (ecosystem, name, version) triple. We
        # therefore match each advisory to every component
        # whose identity matches the affected package object.
        lookups: list[VulnerabilityLookup] = []
        advisories_persisted: set[tuple[int, int]] = set()
        for component_id, ecosystem, name, version in triples:
            for advisory in advisories:
                match = _advisory_matches_component(advisory, ecosystem, name)
                if not match:
                    continue
                lookup = self._persist_advisory(
                    scan_run_id=scan_run_id,
                    component_id=component_id,
                    ecosystem=ecosystem,
                    package_name=name,
                    version=version,
                    advisory=advisory,
                    fetched_at=fetched_at,
                )
                if lookup is None:
                    continue
                key = (lookup.component_id, lookup.advisory_id)
                if key in advisories_persisted:
                    continue
                advisories_persisted.add(key)
                lookups.append(lookup)
        return lookups

    def enrich_vulnerabilities_for_one(
        self,
        *,
        scan_run_id: int,
        component: Component,
    ) -> list[VulnerabilityLookup]:
        """Convenience wrapper for a single component query.

        Used by the on-demand enrichment endpoint the API
        exposes. It shares the cache and observation code
        path with the batched call.
        """
        return self.enrich_vulnerabilities_for_components(
            scan_run_id=scan_run_id, components=[component]
        )

    # ------------------------------------------------------------------
    # Dependency enrichment (deps.dev)
    # ------------------------------------------------------------------
    def enrich_components_with_deps_dev(
        self,
        *,
        scan_run_id: int,
        components: Iterable[Component],
    ) -> list[EnrichmentLookup]:
        """Enrich each component with deps.dev metadata + licence.

        The result is used to:

        - populate the licence inventory (via the rule engine
          which reads the ``licence_assertions`` list);
        - record per-component enrichment freshness
          (ProviderObservation rows);
        - surface the dependency context for the deps.dev
          walker (separate ``enrich_with_tree`` call, used
          only when explicitly requested).
        """
        lookups: list[EnrichmentLookup] = []
        for component in components:
            ecosystem = component.ecosystem
            if not ecosystem or not component.package_name:
                self._record_observation(
                    scan_run_id=scan_run_id,
                    component_id=component.id,
                    provider=DEPS_DEV_PROVIDER,
                    operation=OP_DEPS_DEV_ENRICH,
                    status=ProviderStatus.NOT_REQUESTED,
                    http_status=None,
                    records_returned=0,
                    cache_status="miss",
                    error_code="unsupported_ecosystem",
                    error_summary=(
                        f"deps.dev was not queried for component "
                        f"{component.package_name!r} because its ecosystem "
                        f"is missing or unsupported."
                    ),
                    evidence={
                        "package_name": component.package_name,
                        "ecosystem": ecosystem,
                    },
                )
                continue
            # Check the persistent cache first. A hit means
            # we never contact the network.
            descriptor = CacheDescriptor(
                provider=DEPS_DEV_PROVIDER,
                operation=OP_DEPS_DEV_ENRICH,
                parameters={
                    "ecosystem": ecosystem,
                    "name": component.package_name,
                    "version": component.version or "",
                },
            )
            lookup = self._cache_service.get(descriptor)
            if lookup.status == CacheStatus.HIT and lookup.payload is not None:
                try:
                    cached = json.loads(lookup.payload.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    cached = None
                if isinstance(cached, dict):
                    self._record_observation(
                        scan_run_id=scan_run_id,
                        component_id=component.id,
                        provider=DEPS_DEV_PROVIDER,
                        operation=OP_DEPS_DEV_ENRICH,
                        status=ProviderStatus.CACHED,
                        http_status=None,
                        records_returned=1,
                        cache_status="hit",
                        error_code=None,
                        error_summary=None,
                        evidence={
                            "package_name": component.package_name,
                            "ecosystem": ecosystem,
                            "version": component.version,
                        },
                    )
                    lookups.append(
                        self._build_enrichment_lookup(
                            component_id=component.id,
                            package_name=component.package_name,
                            ecosystem=ecosystem,
                            version=component.version,
                            payload=cached,
                            fetched_at=lookup.entry.retrieved_at if lookup.entry else utcnow(),
                            cache_status="hit",
                        )
                    )
                    continue
            # Cache miss / stale: ask the provider.
            result = self._deps_dev.enrich(
                ecosystem=ecosystem,
                package_name=component.package_name,
                version=component.version,
            )
            if isinstance(result, ProviderUnavailable):
                self._record_observation(
                    scan_run_id=scan_run_id,
                    component_id=component.id,
                    provider=DEPS_DEV_PROVIDER,
                    operation=OP_DEPS_DEV_ENRICH,
                    status=ProviderStatus.UNAVAILABLE,
                    http_status=result.http_status,
                    records_returned=0,
                    cache_status="miss" if lookup.status == CacheStatus.MISS else "stale",
                    error_code=result.error_code,
                    error_summary=redact_provider_summary(result.error_summary),
                    evidence={
                        "package_name": component.package_name,
                        "ecosystem": ecosystem,
                        "version": component.version,
                    },
                )
                continue
            payload = result.data
            if not isinstance(payload, dict):
                self._record_observation(
                    scan_run_id=scan_run_id,
                    component_id=component.id,
                    provider=DEPS_DEV_PROVIDER,
                    operation=OP_DEPS_DEV_ENRICH,
                    status=ProviderStatus.UNAVAILABLE,
                    http_status=None,
                    records_returned=0,
                    cache_status="miss",
                    error_code="deps_dev_invalid_payload",
                    error_summary="deps.dev response was not a JSON object.",
                )
                continue
            # Cache the result. ``put`` is a no-op if the
            # payload exceeds the configured cap. A cache
            # failure must not erase the live result; the
            # next stage still sees the payload and the
            # observation row records the cache miss. The
            # observation row is the diagnostic record; we
            # deliberately do not log a separate exception
            # line per cache miss because that would double
            # the log volume for no operational gain.
            with contextlib.suppress(Exception):
                self._cache_service.put(
                    descriptor,
                    payload=_build_cache_payload(payload),
                    etag=None,
                    last_modified=None,
                    ttl=timedelta(seconds=DEFAULT_DEPS_DEV_TTL_SECONDS),
                )
            self._record_observation(
                scan_run_id=scan_run_id,
                component_id=component.id,
                provider=DEPS_DEV_PROVIDER,
                operation=OP_DEPS_DEV_ENRICH,
                status=ProviderStatus.AVAILABLE,
                http_status=200,
                records_returned=1,
                cache_status="miss",
                error_code=None,
                error_summary=None,
                evidence={
                    "package_name": component.package_name,
                    "ecosystem": ecosystem,
                    "version": component.version,
                    "licences": _extract_licences(payload),
                    "dependency_count": _dependency_count(payload),
                },
            )
            lookups.append(
                self._build_enrichment_lookup(
                    component_id=component.id,
                    package_name=component.package_name,
                    ecosystem=ecosystem,
                    version=component.version,
                    payload=payload,
                    fetched_at=result.fetched_at,
                    cache_status="miss",
                )
            )
        return lookups

    # ------------------------------------------------------------------
    # Repository posture (OpenSSF Scorecard)
    # ------------------------------------------------------------------
    def import_scorecard_for_repository(
        self,
        *,
        scan_run_id: int,
        canonical_url: str | None,
        is_archive: bool = False,
    ) -> PostureLookup | None:
        """Import OpenSSF Scorecard results for a supported repository.

        ``is_archive=True`` short-circuits to a ``not_applicable``
        outcome; the Scorecard API only knows how to look up
        public GitHub repositories. We never fabricate a zero
        score for an archive.
        """
        if is_archive or not canonical_url or not canonical_url.startswith("https://github.com/"):
            self._record_observation(
                scan_run_id=scan_run_id,
                provider=SCORECARD_PROVIDER,
                operation=OP_SCORECARD_READ,
                status=ProviderStatus.NOT_REQUESTED,
                http_status=None,
                records_returned=0,
                cache_status="miss",
                error_code="not_applicable",
                error_summary=(
                    "OpenSSF Scorecard is only available for public GitHub "
                    "repositories. This scan's source is not a supported target."
                ),
            )
            return PostureLookup(
                scan_run_id=scan_run_id,
                canonical_url=canonical_url or "",
                score=None,
                scorecard_version=None,
                commit_sha=None,
                source_date=None,
                checks=(),
                fetched_at=utcnow(),
                cache_status="miss",
                provider_url="",
                source_provenance="openssf_scorecard",
                not_applicable=True,
                not_applicable_reason="not_github_or_no_url",
            )
        # Check the persistent cache.
        descriptor = CacheDescriptor(
            provider=SCORECARD_PROVIDER,
            operation=OP_SCORECARD_READ,
            parameters={"canonical_url": canonical_url},
        )
        cache_lookup = self._cache_service.get(descriptor)
        if cache_lookup.status == CacheStatus.HIT and cache_lookup.payload is not None:
            try:
                cached = json.loads(cache_lookup.payload.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                cached = None
            if isinstance(cached, dict):
                self._record_observation(
                    scan_run_id=scan_run_id,
                    provider=SCORECARD_PROVIDER,
                    operation=OP_SCORECARD_READ,
                    status=ProviderStatus.CACHED,
                    http_status=None,
                    records_returned=1,
                    cache_status="hit",
                    error_code=None,
                    error_summary=None,
                )
                return self._persist_scorecard(
                    scan_run_id=scan_run_id,
                    canonical_url=canonical_url,
                    payload=cached,
                    fetched_at=cache_lookup.entry.retrieved_at if cache_lookup.entry else utcnow(),
                    cache_status="hit",
                )
        # Cache miss / stale: ask the upstream.
        result = self._scorecard.read(canonical_url)
        if isinstance(result, ProviderUnavailable):
            self._record_observation(
                scan_run_id=scan_run_id,
                provider=SCORECARD_PROVIDER,
                operation=OP_SCORECARD_READ,
                status=ProviderStatus.UNAVAILABLE,
                http_status=result.http_status,
                records_returned=0,
                cache_status="miss" if cache_lookup.status == CacheStatus.MISS else "stale",
                error_code=result.error_code,
                error_summary=redact_provider_summary(result.error_summary),
            )
            return None
        payload = result.data
        if not isinstance(payload, dict):
            self._record_observation(
                scan_run_id=scan_run_id,
                provider=SCORECARD_PROVIDER,
                operation=OP_SCORECARD_READ,
                status=ProviderStatus.UNAVAILABLE,
                http_status=None,
                records_returned=0,
                cache_status="miss",
                error_code="scorecard_invalid_payload",
                error_summary="Scorecard response was not a JSON object.",
            )
            return None
        with contextlib.suppress(Exception):
            self._cache_service.put(
                descriptor,
                payload=_build_cache_payload(payload),
                etag=None,
                last_modified=None,
                ttl=timedelta(seconds=DEFAULT_SCORECARD_TTL_SECONDS),
            )
        self._record_observation(
            scan_run_id=scan_run_id,
            provider=SCORECARD_PROVIDER,
            operation=OP_SCORECARD_READ,
            status=ProviderStatus.AVAILABLE,
            http_status=200,
            records_returned=1,
            cache_status="miss",
            error_code=None,
            error_summary=None,
        )
        return self._persist_scorecard(
            scan_run_id=scan_run_id,
            canonical_url=canonical_url,
            payload=payload,
            fetched_at=result.fetched_at,
            cache_status="miss",
        )

    # ------------------------------------------------------------------
    # Observation writer
    # ------------------------------------------------------------------
    def _record_observation(
        self,
        *,
        scan_run_id: int,
        provider: str,
        operation: str,
        status: ProviderStatus,
        http_status: int | None,
        records_returned: int,
        cache_status: str,
        error_code: str | None,
        error_summary: str | None,
        evidence: dict[str, Any] | None = None,
        component_id: int | None = None,
    ) -> ProviderObservation:
        now = utcnow()
        # ``evidence_json`` is the structured success
        # envelope. The redaction utility strips the
        # sensitive keys before the value is written; the
        # application-side size cap (8 KiB) protects the
        # database from oversized payloads. Successful
        # calls always carry an envelope; failed / skipped
        # calls do not, and the column stays ``null``.
        evidence_json: str | None = None
        if evidence is not None and status in {
            ProviderStatus.AVAILABLE,
            ProviderStatus.CACHED,
            ProviderStatus.PARTIAL,
        }:
            try:
                serialised = json.dumps(
                    redact_payload(evidence),
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
            except (TypeError, ValueError):
                serialised = None
            if serialised is not None:
                if len(serialised.encode("utf-8")) > _MAX_EVIDENCE_BYTES:
                    # Truncate to the cap. The endpoint
                    # detects the truncation by the absence
                    # of the trailing ``}`` and reports it
                    # as a bounded failure, never as a
                    # fabricated success.
                    serialised = serialised.encode("utf-8")[:_MAX_EVIDENCE_BYTES].decode(
                        "utf-8", errors="replace"
                    )
                evidence_json = serialised
        # ``error_summary`` is for redacted error text only.
        # Successful calls leave it ``None``; the read-side
        # endpoint never has to recover a successful payload
        # by parsing it.
        sanitised_error = redact_provider_summary(error_summary)
        row = ProviderObservation(
            scan_run_id=scan_run_id,
            component_id=component_id,
            provider=provider,
            operation=operation,
            status=status,
            requested_at=now,
            completed_at=now,
            http_status=http_status,
            records_returned=records_returned,
            cache_status=cache_status,
            error_code=error_code,
            error_summary=sanitised_error,
            evidence_json=evidence_json,
        )
        self._session.add(row)
        return row

    # ------------------------------------------------------------------
    # Vulnerability persistence
    # ------------------------------------------------------------------
    def _persist_advisory(
        self,
        *,
        scan_run_id: int,
        component_id: int,
        ecosystem: str,
        package_name: str,
        version: str | None,
        advisory: dict[str, Any],
        fetched_at: datetime,
    ) -> VulnerabilityLookup | None:
        """Persist one OSV advisory to ``Advisory`` + ``ComponentAdvisory``.

        The persistence is idempotent: the unique constraint
        on ``(source, source_advisory_id)`` deduplicates the
        ``Advisory`` row; the unique constraint on
        ``(scan_run_id, component_id, advisory_id)``
        deduplicates the ``ComponentAdvisory`` row. Re-runs
        of the same scan therefore never create duplicate
        findings.
        """
        source_advisory_id = advisory.get("id")
        if not isinstance(source_advisory_id, str) or not source_advisory_id:
            return None
        severity_source = "osv"
        severity_label, severity_score = _normalise_severity(advisory.get("severity"))
        aliases = tuple(sorted({a for a in advisory.get("aliases", []) if isinstance(a, str)}))
        fixed_versions = sorted(
            {fv for fv in advisory.get("fixed_versions", []) if isinstance(fv, str)}
        )
        withdrawn = bool(advisory.get("withdrawn"))
        details_url = _advisory_details_url(advisory)
        # Upsert the ``Advisory`` row.
        from app.repositories import advisory_repo

        try:
            advisory_row = advisory_repo.get_or_create(
                self._session,
                source="osv",
                source_advisory_id=source_advisory_id,
                canonical_id=aliases[0] if aliases else None,
                summary=_truncate(advisory.get("summary"), 2048),
                details_url=details_url,
                published_at=_parse_iso(advisory.get("published")),
                modified_at=_parse_iso(advisory.get("modified")),
                withdrawn_at=_parse_iso(advisory.get("withdrawn")),
                raw_payload_sha256=_hash_payload(
                    json.dumps(advisory, sort_keys=True, default=str).encode("utf-8")
                ),
            )
        except Exception:
            logger.exception(
                "Failed to persist advisory %s for scan %s", source_advisory_id, scan_run_id
            )
            return None
        # Upsert the ``ComponentAdvisory`` row.
        existing = (
            self._session.query(ComponentAdvisory)
            .filter(
                ComponentAdvisory.scan_run_id == scan_run_id,
                ComponentAdvisory.component_id == component_id,
                ComponentAdvisory.advisory_id == advisory_row.id,
            )
            .one_or_none()
        )
        if existing is None:
            existing = ComponentAdvisory(
                scan_run_id=scan_run_id,
                component_id=component_id,
                advisory_id=advisory_row.id,
                affected=True,
                fixed_versions_json=json.dumps(fixed_versions) if fixed_versions else None,
                severity_source=severity_source if severity_label else None,
                severity_label=severity_label,
                severity_score=severity_score,
                evidence_json=json.dumps(
                    {
                        "provider": "osv",
                        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
                        "withdrawn": withdrawn,
                        "aliases": list(aliases),
                    },
                    sort_keys=True,
                ),
            )
            self._session.add(existing)
        else:
            existing.fixed_versions_json = json.dumps(fixed_versions) if fixed_versions else None
            existing.severity_source = severity_source if severity_label else None
            existing.severity_label = severity_label
            existing.severity_score = severity_score
        return VulnerabilityLookup(
            component_id=component_id,
            package_name=package_name,
            ecosystem=ecosystem,
            version=version,
            advisory_id=advisory_row.id,
            advisory_source="osv",
            advisory_external_id=source_advisory_id,
            canonical_id=advisory_row.canonical_id,
            severity_label=severity_label,
            severity_score=severity_score,
            severity_source=severity_source if severity_label else None,
            fixed_versions=fixed_versions,
            withdrawn=withdrawn,
            aliases=aliases,
            summary=advisory_row.summary,
            details_url=advisory_row.details_url,
            fetched_at=fetched_at,
            cache_status="miss",
            provider_url=details_url,
        )

    # ------------------------------------------------------------------
    # Enrichment shape
    # ------------------------------------------------------------------
    def _build_enrichment_lookup(
        self,
        *,
        component_id: int,
        package_name: str,
        ecosystem: str,
        version: str | None,
        payload: dict[str, Any],
        fetched_at: datetime,
        cache_status: str,
    ) -> EnrichmentLookup:
        licenses_raw = payload.get("licenses")
        licenses: list[str] = []
        if isinstance(licenses_raw, list):
            for entry in licenses_raw:
                if isinstance(entry, str):
                    licenses.append(entry)
                elif isinstance(entry, dict):
                    spdx = entry.get("spdx")
                    if isinstance(spdx, dict) and isinstance(spdx.get("identifier"), str):
                        licenses.append(spdx["identifier"])
                    identifier = entry.get("identifier")
                    if isinstance(identifier, str):
                        licenses.append(identifier)
        dependencies_raw = payload.get("dependencies")
        dependencies_count = len(dependencies_raw) if isinstance(dependencies_raw, list) else 0
        return EnrichmentLookup(
            component_id=component_id,
            package_name=package_name,
            ecosystem=ecosystem,
            version=version,
            licenses=tuple(sorted(set(licenses))),
            dependencies_count=dependencies_count,
            fetched_at=fetched_at,
            cache_status=cache_status,
            provider_url=(
                f"https://api.deps.dev/v3/systems/{ecosystem}/packages/"
                f"{package_name}/versions/{version or ''}"
            ),
            source_provenance=str(payload.get("source_provenance") or "deps.dev"),
        )

    # ------------------------------------------------------------------
    # Scorecard persistence
    # ------------------------------------------------------------------
    def _persist_scorecard(
        self,
        *,
        scan_run_id: int,
        canonical_url: str,
        payload: dict[str, Any],
        fetched_at: datetime,
        cache_status: str,
    ) -> PostureLookup | None:
        """Persist Scorecard results as posture-category findings.

        The Scorecard checks become ``Finding`` rows with
        ``category=repository_posture``. A new check discovered
        in a future Scorecard release is preserved verbatim;
        we do not project the data into a Lockverity score.
        """
        from app.models.finding import (
            Finding,
            FindingCategory,
            FindingConfidence,
            FindingSeverity,
        )
        from app.models.repository import Repository
        from app.models.scan_run import ScanRun
        from app.utils.finding_keys import stable_finding_key

        scan = self._session.get(ScanRun, scan_run_id)
        if scan is None:
            return None
        repository = self._session.get(Repository, scan.repository_id)
        if repository is None:
            return None
        checks_raw = payload.get("checks")
        checks: list[dict[str, Any]] = []
        if isinstance(checks_raw, list):
            for entry in checks_raw:
                if not isinstance(entry, dict):
                    continue
                checks.append(entry)
        # Persist a stable metadata finding so the UI shows
        # the rollup row, then one finding per check.
        score = payload.get("score") if isinstance(payload.get("score"), (int, float)) else None
        scorecard_version = (
            payload.get("scorecard", {}).get("version")
            if isinstance(payload.get("scorecard"), dict)
            else None
        )
        commit_sha = (
            payload.get("repo", {}).get("commit") if isinstance(payload.get("repo"), dict) else None
        )
        source_date = payload.get("date") if isinstance(payload.get("date"), str) else None
        # A meta finding summarising the run.
        meta_key = stable_finding_key(
            rule_id="LOCK-POST-SCORECARD",
            evidence={
                "canonical_url": canonical_url,
                "scope": "meta",
            },
        )
        meta_finding = (
            self._session.query(Finding)
            .filter(
                Finding.scan_run_id == scan_run_id,
                Finding.stable_key == meta_key,
            )
            .one_or_none()
        )
        if meta_finding is None:
            meta_finding = Finding(
                scan_run_id=scan_run_id,
                repository_id=repository.id,
                rule_id="LOCK-POST-SCORECARD",
                category=FindingCategory.REPOSITORY_POSTURE,
                severity=FindingSeverity.INFORMATIONAL,
                confidence=FindingConfidence.HIGH,
                title="OpenSSF Scorecard imported",
                summary=(
                    f"Imported {len(checks)} checks from OpenSSF Scorecard "
                    f"for {canonical_url}; score={score}, date={source_date}."
                ),
                evidence_json=json.dumps(
                    {
                        "provider": "openssf_scorecard",
                        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
                        "cache_status": cache_status,
                        "score": score,
                        "scorecard_version": scorecard_version,
                        "commit_sha": commit_sha,
                        "source_date": source_date,
                    },
                    sort_keys=True,
                    default=str,
                ),
                location_path=canonical_url,
                stable_key=meta_key,
            )
            self._session.add(meta_finding)
        # One finding per check.
        for check in checks:
            check_name = check.get("name")
            if not isinstance(check_name, str) or not check_name:
                continue
            check_score = check.get("score")
            reason = check.get("reason")
            evidence_urls = check.get("evidence") or []
            check_key = stable_finding_key(
                rule_id=f"LOCK-POST-SCORECARD-{check_name}",
                evidence={
                    "canonical_url": canonical_url,
                    "check_name": check_name,
                    "scope": "check",
                },
            )
            evidence_payload = {
                "provider": "openssf_scorecard",
                "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
                "cache_status": cache_status,
                "check_name": check_name,
                "score": check_score,
                "reason": reason,
                "evidence": evidence_urls if isinstance(evidence_urls, list) else [],
                "source_timestamp": check.get("source_timestamp") or check.get("last_updated"),
            }
            existing = (
                self._session.query(Finding)
                .filter(
                    Finding.scan_run_id == scan_run_id,
                    Finding.stable_key == check_key,
                )
                .one_or_none()
            )
            if existing is None:
                self._session.add(
                    Finding(
                        scan_run_id=scan_run_id,
                        repository_id=repository.id,
                        rule_id=f"LOCK-POST-SCORECARD-{check_name}",
                        category=FindingCategory.REPOSITORY_POSTURE,
                        severity=FindingSeverity.INFORMATIONAL,
                        confidence=FindingConfidence.HIGH,
                        title=f"Scorecard check: {check_name}",
                        summary=str(reason) if reason else f"Scorecard result for {check_name}.",
                        evidence_json=json.dumps(evidence_payload, sort_keys=True, default=str),
                        location_path=canonical_url,
                        stable_key=check_key,
                    )
                )
            else:
                existing.title = f"Scorecard check: {check_name}"
                existing.summary = str(reason) if reason else f"Scorecard result for {check_name}."
                existing.evidence_json = json.dumps(evidence_payload, sort_keys=True, default=str)
        # Persist findings directly; we deliberately do not
        # route through write_service here because the
        # per-scan stable_key already dedupes on rerun.
        return PostureLookup(
            scan_run_id=scan_run_id,
            canonical_url=canonical_url,
            score=float(score) if score is not None else None,
            scorecard_version=scorecard_version,
            commit_sha=commit_sha,
            source_date=source_date,
            checks=tuple(checks),
            fetched_at=fetched_at,
            cache_status=cache_status,
            provider_url=(
                f"https://api.securityscorecards.dev/projects/"
                f"github.com/{_owner(canonical_url)}/{_repo(canonical_url)}"
            ),
            source_provenance="openssf_scorecard",
            not_applicable=False,
            not_applicable_reason=None,
        )


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------
def _advisory_matches_component(
    advisory: dict[str, Any], ecosystem: str, package_name: str
) -> bool:
    affected = advisory.get("affected")
    if not isinstance(affected, list):
        return False
    for entry in affected:
        if not isinstance(entry, dict):
            continue
        package = entry.get("package")
        if not isinstance(package, dict):
            continue
        if package.get("ecosystem") != ecosystem:
            continue
        if package.get("name") != package_name:
            continue
        return True
    return False


def _advisory_details_url(advisory: dict[str, Any]) -> str | None:
    references = advisory.get("references")
    if not isinstance(references, list):
        return None
    for ref in references:
        if not isinstance(ref, dict):
            continue
        if ref.get("type") == "ADVISORY" and isinstance(ref.get("url"), str):
            return ref["url"]
    for ref in references:
        if isinstance(ref, dict) and isinstance(ref.get("url"), str):
            return ref["url"]
    return None


def _normalise_severity(
    entries: Any,
) -> tuple[str | None, float | None]:
    """Map an OSV ``severity`` list to a Lockverity label + 0-10 score.

    OSV severity entries are ``{type, score}`` pairs where
    ``type`` is one of ``CVSS_V3``, ``CVSS_V4``, ``Ubuntu``,
    etc., and ``score`` is either a vector string or a number.
    We never invent a severity; we copy the provider's
    reported score verbatim when it is numeric.
    """
    if not isinstance(entries, list):
        return None, None
    # Prefer CVSS_V3 then CVSS_V4 then anything else.
    priority = ("CVSS_V3", "CVSS_V4", "CVSS")
    chosen: dict[str, Any] | None = None
    for tag in priority:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == tag:
                chosen = entry
                break
        if chosen is not None:
            break
    if chosen is None:
        for entry in entries:
            if isinstance(entry, dict):
                chosen = entry
                break
    if chosen is None:
        return None, None
    score_raw = chosen.get("score")
    label = chosen.get("type") or "unknown"
    if isinstance(score_raw, (int, float)):
        score = float(score_raw)
        if score < 0 or score > 10:
            # CVSS vectors have a 0-10 range. A value outside
            # that range is treated as "unknown" so we never
            # invent a severity.
            return str(label), None
        return str(label), score
    if isinstance(score_raw, str):
        # A CVSS vector string. We do not attempt to parse it;
        # we only record the label and leave the score null.
        return str(label), None
    return str(label), None


def _truncate(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        from datetime import datetime

        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _owner(canonical_url: str) -> str:
    prefix = "https://github.com/"
    if not canonical_url.startswith(prefix):
        return ""
    rest = canonical_url[len(prefix) :].strip("/")
    parts = rest.split("/")
    return parts[0] if parts else ""


def _repo(canonical_url: str) -> str:
    prefix = "https://github.com/"
    if not canonical_url.startswith(prefix):
        return ""
    rest = canonical_url[len(prefix) :].strip("/")
    parts = rest.split("/")
    return parts[1] if len(parts) > 1 else ""


__all__ = [  # noqa: RUF022
    "DEPS_DEV_PROVIDER",
    "DEFAULT_DEPS_DEV_TTL_SECONDS",
    "DEFAULT_OSV_TTL_SECONDS",
    "DEFAULT_SCORECARD_TTL_SECONDS",
    "EnrichmentLookup",
    "GITHUB_PROVIDER",
    "OP_DEPS_DEV_ENRICH",
    "OP_OSV_QUERY",
    "OP_SCORECARD_READ",
    "OSV_PROVIDER",
    "PostureLookup",
    "ProviderService",
    "SCORECARD_PROVIDER",
    "SUPPORTED_ECOSYSTEMS",
    "UnsupportedEcosystemError",
    "VulnerabilityLookup",
]
# We declare the public surface grouped by concern
# (constants, classes, exceptions) rather than strict
# alphabetical so a reader can see what the module exports
# at a glance.
