"""Analyzers package.

Concrete analyzers in this package implement the
:class:`app.providers.contracts.StaticAnalyzer` protocol (or
return a plain :class:`AnalyzerResult`-shaped value that the
orchestrator can consume).
"""

from __future__ import annotations

from app.analyzers.github_actions import GitHubActionsAnalyzer
from app.analyzers.manifest_discovery import ManifestDiscoveryAnalyzer

__all__ = [
    "GitHubActionsAnalyzer",
    "ManifestDiscoveryAnalyzer",
]
