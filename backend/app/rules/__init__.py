"""Rules package.

Concrete rules implement :class:`app.providers.contracts.FindingRule`.
The orchestrator iterates the rule registry and applies each
rule to the per-scan evidence.
"""

from __future__ import annotations

from app.rules.base import BaseRule
from app.rules.licence import (
    LicenceInventoryRule,
    LicenceMultipleAssertionsRule,
    LicenceProviderUnavailableRule,
    LicenceReviewRequiredRule,
    LicenceUnknownRule,
)
from app.rules.vulnerability import (
    DirectVulnerableDependencyRule,
    MissingLockfileRule,
    MultipleDependencyPathsRule,
    NoFixedVersionRule,
    PartialProviderDataRule,
    ProviderUnavailableRule,
    TransitiveVulnerableDependencyRule,
    UnresolvedVersionRule,
    VulnerableDevelopmentDependencyRule,
    WithdrawnAdvisoryRule,
)

# Order matters: rules are registered in the order the orchestrator
# applies them. The orchestrator is free to reorder at runtime.
DEFAULT_RULES: tuple[BaseRule, ...] = (
    DirectVulnerableDependencyRule(),
    TransitiveVulnerableDependencyRule(),
    NoFixedVersionRule(),
    WithdrawnAdvisoryRule(),
    UnresolvedVersionRule(),
    PartialProviderDataRule(),
    ProviderUnavailableRule(),
    MultipleDependencyPathsRule(),
    VulnerableDevelopmentDependencyRule(),
    MissingLockfileRule(),
    LicenceUnknownRule(),
    LicenceMultipleAssertionsRule(),
    LicenceReviewRequiredRule(),
    LicenceProviderUnavailableRule(),
    LicenceInventoryRule(),
)


def default_rules() -> tuple[BaseRule, ...]:
    """Return a fresh tuple of the default rule instances."""
    return tuple(DEFAULT_RULES)


__all__ = [
    "DEFAULT_RULES",
    "BaseRule",
    "default_rules",
]
