"""Process-wide singletons.

The application holds a single executor and a single
:class:`IntakeService` factory. Tests can replace the executor
via dependency overrides.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.config import get_settings
from app.services.executor_service import (
    InlineScanExecutor,
    LocalThreadScanExecutor,
    ScanExecutor,
)

logger = logging.getLogger("lockverity.singletons")

_lock = threading.Lock()
_executor: ScanExecutor | None = None
_intake_factory: Any | None = None


def get_executor() -> ScanExecutor:
    """Return the process-wide executor, creating it on first use."""
    global _executor
    with _lock:
        if _executor is None:
            settings = get_settings()
            _executor = LocalThreadScanExecutor(max_workers=settings.scan_worker_concurrency)
        return _executor


def set_executor(executor: ScanExecutor) -> None:
    """Replace the process-wide executor (intended for tests)."""
    global _executor
    with _lock:
        if _executor is not None and _executor is not executor:
            try:
                _executor.shutdown(wait=False)
            except Exception:  # pragma: no cover - defensive
                logger.warning("executor shutdown raised; ignoring", exc_info=True)
        _executor = executor


def reset_executor_for_tests() -> None:
    """Reset the executor to a fresh inline executor (test only)."""
    set_executor(InlineScanExecutor())


__all__ = ["get_executor", "reset_executor_for_tests", "set_executor"]
