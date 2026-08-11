"""Immutable request-scoped external evidence provider selection."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExternalEvidenceProviders:
    """Providers an operator requested for one scan execution attempt.

    Every provider remains enabled by default for backward compatibility.
    The frozen value is captured by the executor callback and cannot be
    mutated while a queued scan is waiting to run.
    """

    osv: bool = True
    deps_dev: bool = True
    openssf: bool = True


__all__ = ["ExternalEvidenceProviders"]
