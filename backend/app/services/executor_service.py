"""Scan executor abstraction.

v0.2 introduces a small, in-process executor. The interface is
deliberately narrow:

- :class:`ScanTask` describes a unit of work.
- :class:`ScanExecutor` schedules, polls, and cancels the work.

Two implementations are provided:

- :class:`InlineScanExecutor` runs every task synchronously on
  the calling thread. It is the implementation used in tests.
- :class:`LocalThreadScanExecutor` schedules tasks onto a
  bounded :class:`ThreadPoolExecutor`. It is the default in
  development and CI.

Neither implementation spawns uncontrolled background
processes. Both honour an explicit ``shutdown`` call and a
graceful ``cancel`` for the running tasks.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("lockverity.executor")


class ExecutorState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class ScanTask:
    """A unit of work for the executor."""

    scan_id: int
    task_key: str
    callback: Callable[[], None] = field(compare=False, repr=False)
    description: str = ""


class ScanExecutor(ABC):
    """The executor interface used by the API and the orchestrator."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def submit(self, task: ScanTask) -> ScanTaskHandle: ...

    @abstractmethod
    def cancel(self, scan_id: int) -> bool: ...

    @abstractmethod
    def shutdown(self, *, wait: bool = True) -> None: ...

    @abstractmethod
    def heartbeat(self, scan_id: int) -> None: ...

    @abstractmethod
    def status(self, scan_id: int) -> ExecutorState: ...


class ScanTaskHandle:
    """A handle to a submitted task."""

    def __init__(self, task: ScanTask, future: Future | None = None) -> None:
        self.task = task
        self.future = future
        self._state: ExecutorState = ExecutorState.IDLE
        self._lock = threading.Lock()

    @property
    def state(self) -> ExecutorState:
        with self._lock:
            return self._state

    def set_state(self, value: ExecutorState) -> None:
        with self._lock:
            self._state = value

    def cancel(self) -> bool:
        with self._lock:
            if self._state in {
                ExecutorState.COMPLETED,
                ExecutorState.CANCELLED,
                ExecutorState.FAILED,
            }:
                return False
            self._state = ExecutorState.CANCELLED
        if self.future is not None:
            self.future.cancel()
        return True


class InlineScanExecutor(ScanExecutor):
    """Runs every task synchronously on the calling thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[int, ScanTaskHandle] = {}
        self._last_heartbeat: dict[int, float] = {}

    @property
    def name(self) -> str:
        return "inline"

    def submit(self, task: ScanTask) -> ScanTaskHandle:
        with self._lock:
            handle = ScanTaskHandle(task)
            self._tasks[task.scan_id] = handle
        handle.set_state(ExecutorState.RUNNING)
        self._last_heartbeat[task.scan_id] = time.monotonic()
        try:
            task.callback()
        except Exception:
            handle.set_state(ExecutorState.FAILED)
            raise
        else:
            if handle.state == ExecutorState.CANCELLED:
                return handle
            handle.set_state(ExecutorState.COMPLETED)
        return handle

    def cancel(self, scan_id: int) -> bool:
        with self._lock:
            handle = self._tasks.get(scan_id)
        if handle is None:
            return False
        return handle.cancel()

    def shutdown(self, *, wait: bool = True) -> None:
        return None

    def heartbeat(self, scan_id: int) -> None:
        self._last_heartbeat[scan_id] = time.monotonic()

    def status(self, scan_id: int) -> ExecutorState:
        with self._lock:
            handle = self._tasks.get(scan_id)
        if handle is None:
            return ExecutorState.IDLE
        return handle.state


class LocalThreadScanExecutor(ScanExecutor):
    """Schedules tasks onto a bounded :class:`ThreadPoolExecutor`."""

    def __init__(self, *, max_workers: int = 2) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self._max_workers = max_workers
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="lockverity-scan"
        )
        self._lock = threading.Lock()
        self._tasks: dict[int, ScanTaskHandle] = {}
        self._last_heartbeat: dict[int, float] = {}
        self._owner_pid = os.getpid()

    @property
    def name(self) -> str:
        return "local-thread"

    @property
    def max_workers(self) -> int:
        return self._max_workers

    def submit(self, task: ScanTask) -> ScanTaskHandle:
        with self._lock:
            handle = ScanTaskHandle(task)
            self._tasks[task.scan_id] = handle
        future = self._pool.submit(self._run, task, handle)
        handle.future = future
        return handle

    def _run(self, task: ScanTask, handle: ScanTaskHandle) -> None:
        handle.set_state(ExecutorState.RUNNING)
        self._last_heartbeat[task.scan_id] = time.monotonic()
        try:
            task.callback()
        except Exception:
            if handle.state != ExecutorState.CANCELLED:
                handle.set_state(ExecutorState.FAILED)
            raise
        else:
            if handle.state == ExecutorState.CANCELLED:
                return
            handle.set_state(ExecutorState.COMPLETED)

    def cancel(self, scan_id: int) -> bool:
        with self._lock:
            handle = self._tasks.get(scan_id)
        if handle is None:
            return False
        return handle.cancel()

    def shutdown(self, *, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)

    def heartbeat(self, scan_id: int) -> None:
        self._last_heartbeat[scan_id] = time.monotonic()

    def status(self, scan_id: int) -> ExecutorState:
        with self._lock:
            handle = self._tasks.get(scan_id)
        if handle is None:
            return ExecutorState.IDLE
        return handle.state


def new_executor_id() -> str:
    """Return a fresh, unguessable executor task identifier."""
    return secrets.token_urlsafe(16)


__all__ = [
    "ExecutorState",
    "InlineScanExecutor",
    "LocalThreadScanExecutor",
    "ScanExecutor",
    "ScanTask",
    "ScanTaskHandle",
    "new_executor_id",
]
