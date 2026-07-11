"""Service layer.

Services own business rules. They call :mod:`app.repositories` for
queries and wraps them with:

- URL normalization and validation
- Lifecycle transition enforcement
- Audit metadata
- Cross-model invariants (e.g. the same scan owning both a stage and
  a finding)

Services must not import from :mod:`app.api`. The API layer is
allowed to depend on services, never the other way around.
"""

from __future__ import annotations

__all__: list[str] = []
