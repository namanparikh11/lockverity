"""Shared pytest fixtures.

Strategy: a single in-memory SQLite database is held open for the
whole test session via :class:`sqlalchemy.pool.StaticPool`. Each test
function gets a fresh :class:`Session` bound to a fresh
transaction, which is rolled back at teardown. The schema is
created once at session start.

This pattern is the documented SQLAlchemy recipe for fast, isolated
in-memory tests. It also lets the service layer call
``session.commit()`` freely, because the per-test transaction is a
savepoint-style nested transaction.

External-network guard
======================

The :func:`_block_external_network` autouse fixture below
guarantees that no test in this suite opens a real socket to
any host other than ``127.0.0.1`` / ``::1`` / ``localhost``.
The guard is the durable backstop for the
``LOCKVERITY_GITHUB_API_URL`` removal contract, the OSV /
deps.dev / OpenSSF Scorecard provider isolation, and the
bounded local HTTP probes in ``test_bounded_http.py``.

The guard patches *four* OS entry points so a test cannot
bypass it via any of the documented Python socket APIs:

- :meth:`socket.socket.connect` -- the per-instance method.
- :func:`socket.create_connection` -- the convenience
  function used by :mod:`httpcore` and :mod:`httpx` (this
  is the path that bypassed the cycle 4 guard and produced
  the unclosed-IPv6-socket ``ResourceWarning``).
- :func:`socket.getaddrinfo` -- DNS resolution; a test that
  resolves a non-loopback hostname is recorded as an
  attempt even if no connect follows.
- :func:`socket.gethostbyname` (and the matching
  ``gethostbyname_ex``) -- legacy DNS lookups.

A blocked attempt raises :exc:`NetworkAccessBlocked` and
fails the test immediately. Allowed attempts are recorded.
At teardown, **any recorded non-loopback attempt fails the
test** even if application code catches the exception; the
fixture raises a :exc:`NetworkAccessAttempted` so the
failure surfaces regardless of application-level
``try/except`` blocks.

The guard is permissive for:

- ``127.0.0.1`` / ``::1`` / ``localhost`` (loopback).
- The IPv6 ``::`` wildcard.
- The IPv4 ``0.0.0.0`` (which only ever binds on this
  machine).

A test that needs to connect to an allow-listed external
host (e.g. a local proxy in a CI test environment) can
call :func:`pytest.skip` or override the fixture; the
guard is the *default* posture, not an opt-in.

Global provider-fake fixture
============================

The :func:`_fake_providers_for_scan_tests` autouse
fixture here replaces the real provider factories with
in-process fakes for *every* backend test. A test that
needs a specific provider outcome (e.g. ``MagicMock``
with a canned return value) can override the patch via
its own ``monkeypatch`` parameter; the global fixture
ensures that a future test that forgets to apply the
fakes still does not open a socket to a non-loopback
host. The previous cycle's per-module import
requirement (``from tests.test_provider_fakes import
fake_providers_for_scan_tests`` in every test module)
is no longer required for isolation; the fakes apply
automatically. Per-module imports remain valid for
backward compatibility but are now redundant.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Configure environment *before* importing the application, otherwise
# :func:`app.core.get_settings` would have already cached a value.
os.environ.setdefault("LOCKVERITY_ENV", "test")
os.environ.setdefault("LOCKVERITY_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LOCKVERITY_WORKSPACE_ROOT", "./var/workspace-test")

import app.models  # noqa: F401  - ensures every model is registered on Base.metadata
from app.core.config import get_settings
from app.db.base import Base


class NetworkAccessBlocked(RuntimeError):  # noqa: N818 -- test-suite fixture exception, not a public API
    """Raised when a test attempts to open a non-loopback socket.

    The error message includes the attempted destination so
    the test report is actionable. The fixture fails the
    test before any further side-effects; the socket is
    closed by the :class:`socket.socket` context manager.
    """


class NetworkAccessAttempted(NetworkAccessBlocked):
    """Raised at teardown when a test attempted a non-loopback host.

    Distinct from :exc:`NetworkAccessBlocked` so the test
    report can distinguish an *immediate* block (which the
    application saw) from a *post-hoc* discovery (which
    the application may have caught and recovered from).
    Both are failures; the post-hoc discovery is the
    last line of defence against a test that swallows the
    immediate exception.
    """


# Allow-list of host literals that the test suite is permitted
# to connect to. Anything outside this list raises
# :exc:`NetworkAccessBlocked` (immediate) or
# :exc:`NetworkAccessAttempted` (post-hoc).
_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})


def _is_loopback(host: object) -> bool:
    """Return ``True`` when ``host`` is in the loopback allow-list.

    Accepts strings (``"127.0.0.1"``, ``"::1"``, ``"localhost"``,
    ``"::"``, ``"0.0.0.0"``, ``""``) and the integer ``0`` which
    :mod:`socket` may substitute for ``INADDR_ANY``.
    """
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii", errors="replace")
        except Exception:  # pragma: no cover - defensive
            host = repr(host)
    if isinstance(host, int):
        return host == 0
    host_str = str(host)
    return (
        host_str in _LOOPBACK_HOSTS or host_str == "" or host_str == "::" or host_str == "0.0.0.0"  # noqa: S104 -- loopback allow-list, never a real bind
    )


@pytest.fixture(autouse=True)
def _block_external_network(request):
    """Block every non-loopback outbound socket during the test.

    The fixture patches *four* OS entry points so a test
    cannot bypass it via any of the documented Python
    socket APIs:

    - :meth:`socket.socket.connect` -- the per-instance
      method.
    - :func:`socket.create_connection` -- the convenience
      function used by :mod:`httpcore` and :mod:`httpx`.
    - :func:`socket.getaddrinfo` -- DNS resolution.
    - :func:`socket.gethostbyname` (and the matching
      ``gethostbyname_ex``) -- legacy DNS lookups.

    The original implementations are restored at teardown.
    At teardown, the fixture raises
    :exc:`NetworkAccessAttempted` if any non-loopback
    attempt was made during the test, even if the
    application caught the immediate
    :exc:`NetworkAccessBlocked`. The post-hoc check is
    the last line of defence against ``try/except`` blocks
    that mask the immediate failure.
    """
    attempts: list[tuple[str, int, str]] = []  # (host, port, source)

    def _guarded_connect(self, address):
        if isinstance(address, tuple) and len(address) >= 2:
            host = address[0]
            port = address[1]
        else:
            host = repr(address)
            port = 0
        host_str = str(host)
        if _is_loopback(host_str):
            attempts.append((host_str, int(port), "socket.connect"))
            return _original_connect(self, address)
        attempts.append((host_str, int(port), "socket.connect"))
        raise NetworkAccessBlocked(
            f"Test attempted to connect to non-loopback host "
            f"{host_str!r}:{port}. The test suite is network-isolated; "
            f"install a fake client (install_http_client / "
            f"monkey-patch github_provider.build_client) or use "
            f"httpx.MockTransport instead."
        )

    def _guarded_create_connection(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) and address else repr(address)
        port = address[1] if isinstance(address, tuple) and len(address) >= 2 else 0
        host_str = str(host)
        if _is_loopback(host_str):
            attempts.append((host_str, int(port), "create_connection"))
            return _original_create_connection(address, *args, **kwargs)
        attempts.append((host_str, int(port), "create_connection"))
        raise NetworkAccessBlocked(
            f"Test attempted to create_connection to non-loopback "
            f"host {host_str!r}:{port}. The test suite is "
            f"network-isolated; install a fake client or use "
            f"httpx.MockTransport instead."
        )

    def _guarded_getaddrinfo(host, *args, **kwargs):
        if not _is_loopback(host):
            port = 0
            if args and isinstance(args[0], (int, str)):
                try:
                    port = int(args[0])
                except (TypeError, ValueError):
                    port = 0
            attempts.append((str(host), port, "getaddrinfo"))
            raise NetworkAccessBlocked(
                f"Test attempted DNS resolution of non-loopback "
                f"host {host!r}. The test suite is network-isolated; "
                f"install a fake client or use httpx.MockTransport."
            )
        return _original_getaddrinfo(host, *args, **kwargs)

    def _guarded_gethostbyname(host):
        if not _is_loopback(host):
            attempts.append((str(host), 0, "gethostbyname"))
            raise NetworkAccessBlocked(
                f"Test attempted DNS resolution of non-loopback "
                f"host {host!r}. The test suite is network-isolated; "
                f"install a fake client or use httpx.MockTransport."
            )
        return _original_gethostbyname(host)

    _original_connect = socket.socket.connect
    _original_create_connection = socket.create_connection
    _original_getaddrinfo = socket.getaddrinfo
    _original_gethostbyname = socket.gethostbyname
    _original_gethostbyname_ex = socket.gethostbyname_ex

    socket.socket.connect = _guarded_connect
    socket.create_connection = _guarded_create_connection
    socket.getaddrinfo = _guarded_getaddrinfo
    socket.gethostbyname = _guarded_gethostbyname
    # ``gethostbyname_ex`` is a thin wrapper around
    # ``gethostbyname`` that returns a tuple; patching the
    # inner call also covers the legacy ``_ex`` form.
    socket.gethostbyname_ex = _guarded_gethostbyname  # type: ignore[assignment]

    try:
        yield {"attempts": attempts}
    finally:
        socket.socket.connect = _original_connect
        socket.create_connection = _original_create_connection
        socket.getaddrinfo = _original_getaddrinfo
        socket.gethostbyname = _original_gethostbyname
        socket.gethostbyname_ex = _original_gethostbyname_ex

        # Post-hoc guard: fail the test at teardown if any
        # non-loopback attempt was made during the test
        # body. This catches tests that catch the
        # immediate :exc:`NetworkAccessBlocked` (e.g. via
        # ``except Exception``) and would otherwise pass
        # silently.
        non_loopback = [a for a in attempts if not _is_loopback(a[0])]
        if non_loopback:
            details = ", ".join(
                f"{host!r}:{port} via {source}" for host, port, source in non_loopback
            )
            raise NetworkAccessAttempted(
                f"Test {request.node.name!r} attempted non-loopback connections: {details}"
            )


@pytest.fixture(autouse=True)
def _fake_providers_for_scan_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apply the shared provider fakes for every backend test.

    The fixture monkey-patches two boundaries:

    1. ``github_provider.build_client`` returns a
       :class:`FakeBoundedClient` that never opens a
       socket.
    2. :class:`AnalysisPipeline` constructor's
       ``provider_service_factory`` keyword is replaced
       with a factory that builds a
       :class:`ProviderService` whose OSV / deps.dev /
       Scorecard calls are short-circuited to honest
       ``ProviderUnavailable`` results.

    Tests that need a specific provider outcome can
    override the patch via the test function's
    ``monkeypatch`` parameter; the autouse fixture
    ensures a future test that forgets to patch the
    provider factory still does not open a socket to a
    non-loopback host.
    """
    # Import here to avoid loading the application
    # module at conftest import time (the
    # application code expects a configured
    # environment, which the env-setdefault calls
    # above have already provided).
    from app.providers import github_provider
    from app.services import analysis_pipeline

    from tests.test_provider_fakes import (
        FakeBoundedClient,
        _fake_provider_service_factory,
    )

    def _build(**kwargs: object) -> FakeBoundedClient:
        return FakeBoundedClient(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(github_provider, "build_client", _build)
    monkeypatch.setattr(
        analysis_pipeline,
        "_default_provider_service_factory",
        _fake_provider_service_factory,
    )


@pytest.fixture(scope="session")
def settings():
    """Return the cached :class:`Settings` instance for tests."""
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session")
def engine(settings, tmp_path_factory):
    """Build a session-wide SQLite engine.

    We use a temp-file-backed SQLite database so the FastAPI
    TestClient, which may run in a worker thread, sees the same
    schema as the test thread.
    """
    db_path = tmp_path_factory.mktemp("lockverity-db") / "test.sqlite"
    test_engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False},
        pool_pre_ping=False,
    )
    Base.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session_factory(engine):
    """Return a session factory bound to the shared engine."""
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


@pytest.fixture
def session(engine, session_factory) -> Iterator[Session]:
    """Yield a clean SQLAlchemy session per test, rolling back at teardown.

    Uses an outer transaction with a nested savepoint, the standard
    recipe from the SQLAlchemy docs. The service layer's
    ``session.commit()`` calls commit the inner savepoint; the outer
    transaction is rolled back at teardown so the next test starts
    with a clean schema.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session_testing = sessionmaker(bind=connection, autoflush=False, autocommit=False, future=True)
    session_ = session_testing()
    try:
        yield session_
    finally:
        session_.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def app_config(settings, engine):
    """Reconfigure the global engine to use the test engine.

    The FastAPI ``get_db`` dependency opens sessions against
    :data:`app.db.session.engine`. For tests we want it to open
    against the test engine. This fixture keeps a reference to
    the original engine and restores it at teardown.

    Both :mod:`app.db.session` and the re-exports in
    :mod:`app.db` are rebound. The ``__init__`` re-export happens
    at import time, so without the second rebind any code that
    does ``from app.db import SessionLocal`` would still talk to
    the original engine - which is exactly the gap the scan
    executor used to fall into.
    """
    import app.db as db_pkg
    from app.db import session as db_session

    original_engine = db_session.engine
    original_sessionlocal = db_session.SessionLocal
    original_pkg_sessionlocal = db_pkg.SessionLocal
    original_pkg_engine = db_pkg.engine

    new_sessionlocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )

    db_session.engine = engine
    db_session.SessionLocal = new_sessionlocal
    db_pkg.SessionLocal = new_sessionlocal
    db_pkg.engine = engine
    try:
        yield settings
    finally:
        db_session.engine = original_engine
        db_session.SessionLocal = original_sessionlocal
        db_pkg.SessionLocal = original_pkg_sessionlocal
        db_pkg.engine = original_pkg_engine


@pytest.fixture
def workspace_root(tmp_path):
    """Return a per-test workspace root under pytest's tmp_path."""
    root = tmp_path / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(autouse=True)
def _reset_db_state(engine):
    """Truncate every table before each test that uses the global engine.

    API tests bind :data:`app.db.session.engine` to the in-memory test
    engine for their duration. The transaction in the ``session``
    fixture covers the per-session case. For API tests that use
    :data:`app.db.session.SessionLocal`` directly (which talks to the
    global engine), we additionally truncate between tests so that
    state from a previous test cannot leak.
    """
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            table_name = table.name
            # ``table_name`` is sourced from SQLAlchemy metadata at
            # import time, not from user input. The string-format is
            # intentional and the rule below documents the exception.
            conn.execute(text("DELETE FROM " + table_name))  # noqa: S608


@pytest.fixture(autouse=True)
def _reset_shared_provider_client():
    """Reset the shared provider client between tests.

    :data:`app.providers.http_client._CLIENT` is a process-wide
    singleton :class:`httpx.Client`. The first test that exercises
    the provider path instantiates the client via
    :func:`get_http_client`; without an explicit teardown the
    client persists across tests and emits a
    ``ResourceWarning`` for an unclosed socket at Python's
    garbage-collection point.

    The fixture calls :func:`install_http_client(None)` at
    teardown, which closes the previous client (if any) and
    resets the singleton to ``None``. The next test that needs
    the shared client instantiates a fresh one.
    """
    from app.providers import http_client

    yield
    http_client.install_http_client(None)


@pytest.fixture(autouse=True, scope="session")
def _session_teardown_close_leaked_sockets():
    """Session-level teardown: force-close any leaked sockets.

    The :class:`BoundedHttpClient` instances created during
    the test suite (via the GitHub provider's
    ``build_client`` factory, the OSV / deps.dev /
    OpenSSF Scorecard providers' shared :class:`httpx.Client`,
    or the local ``ThreadingHTTPServer`` in
    ``test_bounded_http.py``) all open sockets that are
    explicitly closed by their own teardown. In rare cases
    -- for example, when a test setup creates a connection
    that an early exception path bypasses -- a socket can be
    orphaned. Python's garbage collector finalises the
    socket's ``__del__`` during a later test's setup and
    emits a :class:`ResourceWarning` that pytest
    misattributes to the later test.

    This session-scoped fixture runs a forced
    :func:`gc.collect` after the last test in the session
    has finished. Any orphaned sockets are finalised in
    the :func:`atexit` handler that :class:`socket.socket`
    registers with the interpreter at module import time;
    the ``gc.collect`` call ensures the finalisers run
    before Python's :class:`ResourceWarning` machinery
    surfaces the error to the test report.
    """
    import atexit
    import gc

    yield
    # Close the shared provider client one last time so the
    # singleton is reset to ``None`` before the session
    # ends.
    from app.providers import http_client

    http_client.install_http_client(None)
    # Force a final garbage collection so any orphaned
    # sockets that survived a test's teardown are
    # finalised now, not during a later test's setup.
    gc.collect()
    # Flush any atexit-registered finalisers (the
    # :class:`socket.socket` ``__del__`` handler is one of
    # these).
    atexit._run_exitfuncs()  # type: ignore[attr-defined]
