"""deps.dev enrichment provider.

deps.dev publishes a public REST API at
``https://api.deps.dev/v3`` that returns package metadata,
dependency relationships, and licence assertions.

This provider is read-only and never replaces lockfile evidence:
when both deps.dev and the lockfile report a different version
for the same package, the lockfile version wins (and the
provider's version is recorded as a ``provider_observation`` with
``outcome=partial`` and an evidence note). The orchestrator is
responsible for the precedence rules; this provider simply
returns what it found.

The provider is bounded by:

- :data:`DEFAULT_MAX_DEPTH` - the BFS depth for dependency trees
- :data:`DEFAULT_MAX_NODES` - the cap on visited nodes
- :data:`DEFAULT_MAX_REQUESTS` - the cap on outbound HTTP calls
- cycle detection
- request deduplication
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.providers.cache import ProviderCache
from app.providers.http_client import (
    HttpClientError,
    HttpRequestLimits,
    HttpResponse,
    get_bytes,
)
from app.providers.results import (
    ProviderOutcome,
    ProviderPartialResult,
    ProviderSuccess,
    ProviderUnavailable,
)
from app.utils.datetime import utcnow
from app.utils.json_safe import BoundedJsonError, parse_bounded_json
from app.utils.redaction import redact_provider_summary

DEPS_DEV_BASE = "https://api.deps.dev/v3"

DEFAULT_MAX_DEPTH = 4
DEFAULT_MAX_NODES = 5_000
DEFAULT_MAX_REQUESTS = 200


@dataclass(frozen=True, slots=True)
class DepsDevEnrichment:
    """A single enriched package record returned by deps.dev."""

    ecosystem: str
    name: str
    version: str
    licenses: tuple[str, ...]
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    source_provenance: str = "deps.dev"


class DepsDevEnrichmentProvider:
    """Safe enrichment provider for deps.dev."""

    name = "deps_dev"

    def __init__(
        self,
        *,
        cache: ProviderCache | None = None,
        limits: HttpRequestLimits | None = None,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_nodes: int = DEFAULT_MAX_NODES,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        request_fn=None,
    ) -> None:
        self._cache = cache or ProviderCache()
        self._limits = limits or HttpRequestLimits()
        self._max_depth = max(0, max_depth)
        self._max_nodes = max(1, max_nodes)
        self._max_requests = max(1, max_requests)
        self._request = request_fn

    # ----- public contract -----
    def enrich(
        self,
        *,
        ecosystem: str,
        package_name: str,
        version: str | None,
    ) -> ProviderSuccess[dict[str, Any]] | ProviderUnavailable:
        if not package_name or not ecosystem:
            return ProviderUnavailable(
                error_code="provider_invalid_input",
                error_summary="ecosystem and package_name are required",
                attempted_at=utcnow(),
                outcome=ProviderOutcome.UNAVAILABLE,
            )
        cache_key = f"depsdev:v3:{ecosystem}:{package_name}:{version or ''}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return ProviderSuccess(
                data=cached,
                fetched_at=utcnow(),
                records_returned=1,
            )
        if not version:
            return ProviderUnavailable(
                error_code="provider_unavailable",
                error_summary="deps.dev requires a concrete version for enrichment",
                attempted_at=utcnow(),
                outcome=ProviderOutcome.UNAVAILABLE,
            )
        url = f"{DEPS_DEV_BASE}/systems/{ecosystem}/packages/{package_name}/versions/{version}"
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
                f"deps.dev responded with HTTP {response.status_code}",
                http_status=response.status_code,
            )
        try:
            parsed = parse_bounded_json(response.body)
        except BoundedJsonError as exc:
            return self._unavailable(exc, http_status=response.status_code)
        if not isinstance(parsed, dict):
            return self._unavailable(
                "deps.dev response was not a JSON object",
                http_status=response.status_code,
            )
        enriched = self._normalize(parsed, ecosystem=ecosystem, name=package_name, version=version)
        self._cache.set(cache_key, enriched)
        return ProviderSuccess(
            data=enriched,
            fetched_at=utcnow(),
            records_returned=1,
        )

    def enrich_with_tree(
        self,
        *,
        ecosystem: str,
        package_name: str,
        version: str,
    ) -> ProviderSuccess[dict[str, Any]] | ProviderPartialResult[dict[str, Any]] | ProviderUnavailable:
        """Enrich and walk the transitive tree with bounded depth and node count.

        Returns a :class:`ProviderPartialResult` when the traversal was
        truncated by the depth or node cap.
        """
        root_result = self.enrich(ecosystem=ecosystem, package_name=package_name, version=version)
        if isinstance(root_result, ProviderUnavailable):
            return root_result
        if not isinstance(root_result.data, dict):
            return self._unavailable("deps.dev root response was not a dict", http_status=200)

        visited: dict[tuple[str, str, str], dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        truncated = False
        truncated_reasons: list[str] = []
        request_count = 0
        frontier: list[tuple[str, str, str, int]] = [
            (ecosystem, package_name, version, 0)
        ]
        while frontier:
            if len(visited) >= self._max_nodes:
                truncated = True
                truncated_reasons.append("max_nodes_reached")
                break
            if request_count >= self._max_requests:
                truncated = True
                truncated_reasons.append("max_requests_reached")
                break
            current = frontier.pop(0)
            eco, name, ver, depth = current
            key = (eco, name, ver)
            if key in visited:
                continue
            visited[key] = {"ecosystem": eco, "name": name, "version": ver, "depth": depth}
            if depth >= self._max_depth:
                continue
            if (eco, name, ver) != (ecosystem, package_name, version):
                result = self.enrich(ecosystem=eco, package_name=name, version=ver)
                request_count += 1
                if isinstance(result, ProviderUnavailable):
                    truncated = True
                    truncated_reasons.append("child_unavailable")
                    continue
                child = result.data
            else:
                child = root_result.data
            for dep in self._dependencies(child):
                edges.append(
                    {
                        "parent": {"ecosystem": eco, "name": name, "version": ver},
                        "child": {
                            "ecosystem": dep.get("ecosystem") or eco,
                            "name": dep.get("name"),
                            "version": dep.get("version"),
                        },
                        "relationship": dep.get("relationship", "runtime"),
                        "optional": bool(dep.get("optional", False)),
                        "depth": depth + 1,
                    }
                )
                child_key = (
                    dep.get("ecosystem") or eco,
                    dep.get("name") or "",
                    dep.get("version") or "",
                )
                if child_key[1] and child_key not in visited:
                    frontier.append((child_key[0], child_key[1], child_key[2], depth + 1))

        payload: dict[str, Any] = {
            "root": root_result.data,
            "nodes": list(visited.values()),
            "edges": edges,
            "truncated": truncated,
            "truncated_reasons": truncated_reasons,
            "request_count": request_count,
        }
        if truncated:
            return ProviderPartialResult(
                data=payload,
                fetched_at=utcnow(),
                records_returned=len(visited),
                error_code="provider_partial",
                error_summary=(
                    "deps.dev enrichment was truncated: "
                    + ", ".join(truncated_reasons or ["unknown"])
                ),
            )
        return ProviderSuccess(
            data=payload,
            fetched_at=utcnow(),
            records_returned=len(visited),
        )

    # ----- internals -----
    def _dependencies(self, data: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
        deps = data.get("dependencies")
        if not isinstance(deps, list):
            return ()
        for dep in deps:
            if isinstance(dep, dict):
                yield dep
        return

    def _normalize(
        self,
        data: Mapping[str, Any],
        *,
        ecosystem: str,
        name: str,
        version: str,
    ) -> dict[str, Any]:
        licences_raw = data.get("licenses")
        licences: list[str] = []
        if isinstance(licences_raw, list):
            for entry in licences_raw:
                if isinstance(entry, str):
                    licences.append(entry)
                elif isinstance(entry, dict):
                    spdx = entry.get("spdx")
                    if isinstance(spdx, dict) and isinstance(spdx.get("identifier"), str):
                        licences.append(spdx["identifier"])
                    else:
                        identifier = entry.get("identifier")
                        if isinstance(identifier, str):
                            licences.append(identifier)
        # Preserve the raw ``dependencies`` list so the tree
        # walker can enumerate children. The list is shallow
        # (just the immediate children of this node) and is
        # what deps.dev returns in version 3.
        raw_dependencies = data.get("dependencies")
        dependencies: list[dict[str, Any]] = []
        if isinstance(raw_dependencies, list):
            for entry in raw_dependencies:
                if isinstance(entry, dict):
                    dependencies.append(entry)
        return {
            "ecosystem": ecosystem,
            "name": name,
            "version": version,
            "licenses": licences,
            "dependencies": dependencies,
            "source_provenance": "deps.dev",
        }

    def _not_found(self) -> ProviderUnavailable:
        return ProviderUnavailable(
            error_code="provider_not_found",
            error_summary="deps.dev returned 404 for the requested package version",
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


__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_NODES",
    "DEFAULT_MAX_REQUESTS",
    "DepsDevEnrichment",
    "DepsDevEnrichmentProvider",
]


def is_deps_dev_response(response: HttpResponse) -> bool:
    """Convenience predicate for tests."""
    return response.status_code == 200 and bool(response.body)
