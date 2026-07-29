"""Self-test for the conftest external-network guard.

These tests verify the *predicate* and the *guard fixtures*
without triggering the post-hoc teardown failure that
would normally fail a test which actually opens a
non-loopback socket. The goal is a unit-level proof that
the guard recognises the right inputs, not a behaviour
test of the actual network call (which would fail at
teardown by design).

The behaviour contract for the *autouse* guard is
covered end-to-end by the rest of the backend suite,
which runs under the guard and must not open any
non-loopback socket. The
``tests/test_github_provider.py`` and
``tests/test_providers_*.py`` files use real ``httpx``
transport probes against ``127.0.0.1`` servers to prove
the guard does not interfere with the in-process
loopback fixtures.
"""

from __future__ import annotations

import socket

import pytest

from tests.conftest import (
    _LOOPBACK_HOSTS,
    NetworkAccessAttempted,
    NetworkAccessBlocked,
    _is_loopback,
)


class TestLoopbackPredicate:
    """Unit tests for the :func:`_is_loopback` helper.

    The helper is the single source of truth for "is this
    host allowed?". Both the immediate block and the
    post-hoc teardown use it; if any of these unit tests
    fail the test suite is broken in a way that no
    network test can recover from.
    """

    def test_ipv4_loopback_is_allowed(self) -> None:
        assert _is_loopback("127.0.0.1") is True

    def test_ipv6_loopback_is_allowed(self) -> None:
        assert _is_loopback("::1") is True

    def test_dns_loopback_alias_is_allowed(self) -> None:
        assert _is_loopback("localhost") is True

    def test_ipv4_any_is_allowed(self) -> None:
        # ``0.0.0.0`` is the bind-side wildcard for this
        # machine; the guard treats it as loopback.
        assert _is_loopback("0.0.0.0") is True  # noqa: S104 — loopback allow-list literal

    def test_ipv6_any_is_allowed(self) -> None:
        assert _is_loopback("::") is True

    def test_empty_string_is_allowed(self) -> None:
        # An empty host is the convention for the
        # ``AF_UNIX`` family; the guard permits it.
        assert _is_loopback("") is True

    def test_integer_zero_is_allowed(self) -> None:
        # :mod:`socket` may substitute the integer 0
        # for ``INADDR_ANY``.
        assert _is_loopback(0) is True

    def test_bytes_loopback_is_allowed(self) -> None:
        assert _is_loopback(b"127.0.0.1") is True

    def test_github_api_is_rejected(self) -> None:
        assert _is_loopback("api.github.com") is False

    def test_scorecard_api_is_rejected(self) -> None:
        assert _is_loopback("api.securityscorecards.dev") is False

    def test_osv_api_is_rejected(self) -> None:
        assert _is_loopback("api.osv.dev") is False

    def test_deps_dev_api_is_rejected(self) -> None:
        assert _is_loopback("api.deps.dev") is False


class TestGuardExceptions:
    """The guard exposes two exception types with distinct meanings."""

    def test_network_access_blocked_is_subclass_of_runtime_error(self) -> None:
        # The immediate-block exception must be catchable
        # as a RuntimeError so application-level
        # ``except RuntimeError`` handlers see it.
        assert issubclass(NetworkAccessBlocked, RuntimeError)

    def test_network_access_attempted_is_subclass_of_blocked(self) -> None:
        # The post-hoc teardown exception must be a
        # subclass of the immediate one so a single
        # ``except NetworkAccessBlocked`` in a test
        # catches both. (Tests that want to distinguish
        # the two can catch the specific subclasses.)
        assert issubclass(NetworkAccessAttempted, NetworkAccessBlocked)


class TestLoopbackHostsConstant:
    """The :data:`_LOOPBACK_HOSTS` constant is the source of truth."""

    def test_constant_contains_ipv4_loopback(self) -> None:
        assert "127.0.0.1" in _LOOPBACK_HOSTS

    def test_constant_contains_ipv6_loopback(self) -> None:
        assert "::1" in _LOOPBACK_HOSTS

    def test_constant_contains_dns_loopback(self) -> None:
        assert "localhost" in _LOOPBACK_HOSTS

    def test_constant_does_not_contain_external_hosts(self) -> None:
        # Defensive: an accidental addition of a public
        # host to the allow-list would silently disable
        # the network guard for that host.
        for forbidden in (
            "api.github.com",
            "api.osv.dev",
            "api.deps.dev",
            "api.securityscorecards.dev",
            "google.com",
            "example.com",
        ):
            assert forbidden not in _LOOPBACK_HOSTS


class TestGuardImmediateBlock:
    """The guard raises :exc:`NetworkAccessBlocked` immediately.

    These tests use a *real* ``socket.create_connection``
    call so the bypass path used by ``httpcore`` /
    ``httpx`` is exercised. The post-hoc teardown
    would normally fail any test that triggers a
    non-loopback attempt, so each test clears the
    fixture's ``attempts`` list at the end of the body
    to opt out of the post-hoc re-raise. The
    *immediate* ``NetworkAccessBlocked`` is the
    behaviour under test; the test asserts on that
    raise. The post-hoc contract is documented in the
    conftest docstring and exercised by the full
    backend suite (every other test is offline).
    """

    def _clear_attempts(self, request: pytest.FixtureRequest) -> None:
        """Drop the autouse fixture's recorded attempts.

        Called at the end of a test body to opt out of
        the post-hoc teardown raise. This is the
        documented escape hatch for the self-test:
        the test deliberately triggers the guard to
        verify the immediate block, and explicitly
        acknowledges the post-hoc block via the
        teardown clear.
        """
        state = request.getfixturevalue("_block_external_network")
        if isinstance(state, dict) and "attempts" in state:
            state["attempts"].clear()

    def test_create_connection_to_non_loopback_raises_immediately(
        self, request: pytest.FixtureRequest
    ) -> None:
        try:
            with pytest.raises(NetworkAccessBlocked) as exc_info:
                socket.create_connection(("api.securityscorecards.dev", 443), timeout=0.1)
            assert "non-loopback" in str(exc_info.value).lower()
            assert "api.securityscorecards.dev" in str(exc_info.value)
        finally:
            self._clear_attempts(request)

    def test_socket_connect_to_non_loopback_raises_immediately(
        self, request: pytest.FixtureRequest
    ) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            try:
                with pytest.raises(NetworkAccessBlocked) as exc_info:
                    s.connect(("api.github.com", 443))
                assert "non-loopback" in str(exc_info.value).lower()
            finally:
                s.close()
        finally:
            self._clear_attempts(request)

    def test_getaddrinfo_for_non_loopback_raises_immediately(
        self, request: pytest.FixtureRequest
    ) -> None:
        # DNS resolution is caught by the guard before
        # any socket is opened. This is the path that
        # would otherwise let a test resolve a
        # non-loopback hostname and then proceed to
        # ``socket.connect`` against the resolved IP
        # without the guard ever firing.
        try:
            with pytest.raises(NetworkAccessBlocked):
                socket.getaddrinfo("api.deps.dev", 443)
        finally:
            self._clear_attempts(request)

    def test_gethostbyname_for_non_loopback_raises_immediately(
        self, request: pytest.FixtureRequest
    ) -> None:
        try:
            with pytest.raises(NetworkAccessBlocked):
                socket.gethostbyname("api.osv.dev")
        finally:
            self._clear_attempts(request)

    def test_loopback_create_connection_is_permitted(self) -> None:
        # The guard must not block legitimate loopback
        # traffic. ``127.0.0.1:1`` is the canonical
        # "no server listening" probe; the ``connect``
        # attempt times out (because port 1 is closed)
        # but the guard does not raise.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # The connect will raise ``ConnectionRefusedError``
            # or ``TimeoutError``; it must NOT raise
            # ``NetworkAccessBlocked``.
            try:
                s.connect(("127.0.0.1", 1))
            except (ConnectionRefusedError, TimeoutError, OSError):
                pass
            else:  # pragma: no cover - depends on the host
                pass
        finally:
            s.close()
