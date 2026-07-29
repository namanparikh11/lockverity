"""Shared provider-fake helpers for the backend test suite.

This module exposes the deterministic in-process fakes
used by the :func:`conftest._fake_providers_for_scan_tests`
autouse fixture:

- :class:`FakeBoundedClient` -- an in-process stand-in for
  the :class:`BoundedHttpClient` interface. Every call to
  ``get_json`` / ``download`` returns a 200 OK with a
  canned body. The GitHub provider's ``build_client``
  factory is monkey-patched to return this fake so the
  GitHub provider never opens a real socket.

- :func:`_fake_provider_service_factory` -- a factory
  that builds a real :class:`ProviderService` whose
  ``_osv`` / ``_deps_dev`` / ``_scorecard`` providers are
  replaced by ``_UnavailableXxx`` classes. The
  :class:`AnalysisPipeline` constructor's
  ``provider_service_factory`` keyword is monkey-patched
  to use this factory so the OSV / deps.dev / OpenSSF
  Scorecard calls are short-circuited to honest
  ``ProviderUnavailable`` results.

The autouse fixture itself lives in
:mod:`tests.conftest` since the v2.0.6 cycle 5 closure
moved it to the global conftest so every backend test
receives the isolation guarantee automatically. This
module is now a *helper* module: it provides the building
blocks for the global fixture and for any test that
needs to install a custom provider client (e.g. via
``monkeypatch.setattr(analysis_pipeline,
"_default_provider_service_factory", _factory)`` in
its own scope).

A test that needs to assert a specific provider outcome
(``ProviderSuccess`` with canned data, for example) can
override the factory in its own scope; the global
fixture only applies when no override is set.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

import pytest
from app.providers import github_provider
from app.providers.http_client import HttpResponse
from app.providers.results import (
    ProviderOutcome,
    ProviderUnavailable,
)


class FakeBoundedClient:
    """An in-process fake for the ``BoundedHttpClient`` interface.

    The GitHub provider's ``build_client`` factory is
    monkey-patched to return this fake. Every call to
    ``get_json`` / ``download`` returns a 200 OK with a
    canned body; the test harness can override the
    responses by setting the ``responses`` dict.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.calls: list[str] = []
        self.responses: dict[str, HttpResponse] = {}
        self.closed = False

    def get_json(self, url: str, **_: Any) -> HttpResponse:
        from urllib.parse import urlsplit

        self.calls.append(urlsplit(url).path)
        if url in self.responses:
            return self.responses[url]
        path = urlsplit(url).path
        if path in self.responses:
            return self.responses[path]
        return HttpResponse(
            200,
            {},
            b'{"default_branch":"main","visibility":"public","archived":false}',
            0.0,
            1,
        )

    def download(self, url: str, **_: Any) -> HttpResponse:
        from urllib.parse import urlsplit

        self.calls.append(urlsplit(url).path)
        if url in self.responses:
            return self.responses[url]
        path = urlsplit(url).path
        if path in self.responses:
            return self.responses[path]
        return HttpResponse(200, {}, b"", 0.0, 1)

    def close(self) -> None:
        self.closed = True


def _fake_provider_service_factory(**kwargs: Any):
    """Return a factory that builds :class:`ProviderService` with fakes.

    The :class:`AnalysisPipeline` accepts a
    ``provider_service_factory`` keyword. The factory
    returned here builds a ``ProviderService`` whose
    OSV / deps.dev / Scorecard calls all return
    ``ProviderUnavailable`` so the orchestrator records
    honest ``not_requested`` / ``provider_unavailable``
    observations without ever opening a socket.
    """

    def _factory(session: Any) -> Any:
        from datetime import datetime

        from app.services.provider_service import ProviderService

        service = ProviderService(session, settings=kwargs.get("settings"))

        def _unavailable(*, provider: str, **_kwargs: Any) -> Any:
            return ProviderUnavailable(
                error_code="provider_unavailable",
                error_summary=("external provider faked as unavailable in test"),
                attempted_at=datetime.now(UTC),
                outcome=ProviderOutcome.UNAVAILABLE,
            )

        class _UnavailableOsv:
            def query_batch(self, *_args: Any, **_kwargs: Any) -> Any:
                return _unavailable(provider="osv")

            def query(self, *_args: Any, **_kwargs: Any) -> Any:
                return _unavailable(provider="osv")

        class _UnavailableDeps:
            def lookup(self, *_args: Any, **_kwargs: Any) -> Any:
                return _unavailable(provider="deps_dev")

            def enrich(self, *_args: Any, **_kwargs: Any) -> Any:
                return _unavailable(provider="deps_dev")

            def enrich_with_tree(self, *_args: Any, **_kwargs: Any) -> Any:
                return _unavailable(provider="deps_dev")

        class _UnavailableScorecard:
            def import_scorecard(self, *_args: Any, **_kwargs: Any) -> Any:
                return _unavailable(provider="openssf")

            def read(self, *_args: Any, **_kwargs: Any) -> Any:
                return _unavailable(provider="openssf")

        service._osv = _UnavailableOsv()  # type: ignore[assignment]
        service._deps_dev = _UnavailableDeps()  # type: ignore[assignment]
        service._scorecard = _UnavailableScorecard()  # type: ignore[assignment]
        return service

    return _factory


def install_fake_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply the shared fakes via the supplied ``monkeypatch``.

    Helper for tests that want to re-apply the fakes after
    they have overridden the global autouse fixture. The
    call is a no-op once the global fixture in
    :mod:`tests.conftest` has already applied the fakes;
    calling it again is harmless because the same
    :class:`FakeBoundedClient` factory and factory
    closure are installed both times.
    """
    from app.services import analysis_pipeline

    def _build(**kwargs: Any) -> FakeBoundedClient:
        return FakeBoundedClient(**kwargs)

    monkeypatch.setattr(github_provider, "build_client", _build)
    monkeypatch.setattr(
        analysis_pipeline,
        "_default_provider_service_factory",
        _fake_provider_service_factory,
    )


__all__ = [
    "FakeBoundedClient",
    "_fake_provider_service_factory",
    "install_fake_providers",
]
