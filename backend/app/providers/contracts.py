"""Provider and analyzer protocol definitions.

A protocol is a structural type: anything that implements the right
attributes and methods satisfies it. Services depend on these
protocols; concrete implementations live in later milestones.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.providers.results import (
    AnalyzerResult,
    FindingEvidence,
    ParserResult,
    ProviderSuccess,
    ProviderUnavailable,
)


@runtime_checkable
class RepositorySourceProvider(Protocol):
    """A source of repository contents (e.g. GitHub download)."""

    name: str

    def fetch_archive(
        self, canonical_url: str, *, ref: str | None = None
    ) -> ProviderSuccess[bytes] | ProviderUnavailable: ...

    def get_metadata(
        self, canonical_url: str
    ) -> ProviderSuccess[dict[str, Any]] | ProviderUnavailable: ...


@runtime_checkable
class ManifestParser(Protocol):
    """A parser for a single ecosystem's manifest format."""

    ecosystem: str
    manifest_type: str

    def parse(self, *, content: bytes, path: str) -> ParserResult[list[dict[str, Any]]]: ...


@runtime_checkable
class DependencyEnrichmentProvider(Protocol):
    """Resolves package metadata (deps.dev-style lookups)."""

    name: str

    def enrich(
        self, *, ecosystem: str, package_name: str, version: str | None
    ) -> ProviderSuccess[dict[str, Any]] | ProviderUnavailable: ...


@runtime_checkable
class VulnerabilityProvider(Protocol):
    """Queries a vulnerability database (OSV, GHSA, NVD, ...)."""

    name: str

    def query(
        self, *, ecosystem: str, package_name: str, version: str | None
    ) -> ProviderSuccess[list[dict[str, Any]]] | ProviderUnavailable: ...


@runtime_checkable
class RepositoryPostureProvider(Protocol):
    """Reads non-code repository signals (visibility, default branch, ...)."""

    name: str

    def read(self, canonical_url: str) -> ProviderSuccess[dict[str, Any]] | ProviderUnavailable: ...


@runtime_checkable
class StaticAnalyzer(Protocol):
    """Runs on already-extracted repository content (manifests, workflows)."""

    name: str

    def analyze(
        self,
        *,
        files: list[tuple[str, bytes]],
        scan_run_id: int,
    ) -> AnalyzerResult: ...


@runtime_checkable
class FindingRule(Protocol):
    """A single deterministic, evidence-backed rule."""

    rule_id: str
    category: str

    def evaluate(
        self,
        *,
        evidence: dict[str, Any],
        scan_run_id: int,
        repository_id: int,
    ) -> tuple[FindingEvidence, ...]: ...


@runtime_checkable
class ReportExporter(Protocol):
    """Serializes a scan to an external format (CycloneDX, SARIF, CSV, ...)."""

    format: str

    def export(self, *, scan_run_id: int) -> ProviderSuccess[bytes] | ProviderUnavailable: ...
