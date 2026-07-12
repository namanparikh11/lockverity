"""Tests for the executor abstraction."""

from __future__ import annotations

import threading

import pytest
from app.services.executor_service import (
    ExecutorState,
    InlineScanExecutor,
    LocalThreadScanExecutor,
    ScanTask,
)


def test_inline_executor_runs_synchronously() -> None:
    executor = InlineScanExecutor()
    ran = threading.Event()
    handle = executor.submit(
        ScanTask(scan_id=1, task_key="t1", callback=ran.set, description="sync")
    )
    assert ran.is_set()
    assert handle.state == ExecutorState.COMPLETED


def test_inline_executor_records_failure() -> None:
    executor = InlineScanExecutor()

    def boom() -> None:
        raise RuntimeError("explode")

    with pytest.raises(RuntimeError):
        executor.submit(ScanTask(scan_id=2, task_key="t2", callback=boom))
    assert executor.status(2) == ExecutorState.FAILED


def test_local_thread_executor_runs_callback() -> None:
    executor = LocalThreadScanExecutor(max_workers=2)
    try:
        ran = threading.Event()
        executor.submit(ScanTask(scan_id=10, task_key="lt1", callback=ran.set, description="async"))
        assert ran.wait(timeout=5.0)
    finally:
        executor.shutdown(wait=True)


def test_local_thread_executor_supports_concurrency() -> None:
    executor = LocalThreadScanExecutor(max_workers=2)
    try:
        running = threading.Event()
        release = threading.Event()
        held = threading.Semaphore(0)

        def hold() -> None:
            running.set()
            held.release()
            assert release.wait(timeout=2.0)

        executor.submit(ScanTask(scan_id=20, task_key="h1", callback=hold))
        executor.submit(ScanTask(scan_id=21, task_key="h2", callback=hold))
        # Both callbacks should reach the ``running`` event
        # before either is released.
        assert held.acquire(timeout=2.0)
        assert held.acquire(timeout=2.0)
        release.set()
    finally:
        executor.shutdown(wait=True)


def test_local_thread_executor_cancel() -> None:
    executor = LocalThreadScanExecutor(max_workers=1)
    try:
        assert executor.cancel(scan_id=999) is False
    finally:
        executor.shutdown(wait=True)
