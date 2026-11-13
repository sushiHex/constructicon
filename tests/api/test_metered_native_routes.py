"""The metered native routes are one table of exact classes (ADR 0024)."""

from __future__ import annotations

import asyncio
from typing import get_args

import pytest

from constructicon.api import _metered_native
from constructicon.api._metered_native import MeteredNativeOperator, is_metered_route
from constructicon.core.errors import ContractViolation
from constructicon.core.metering import MeteringSource
from constructicon.substrate.executors.claude_provider import (
    ClaudeOperatorHandle,
    ClaudeOperatorProvider,
)
from constructicon.substrate.executors.codex import CodexOperatorHandle, CodexOperatorProvider


def bare(cls):
    """An instance of exactly ``cls`` with no state; only its type is asked."""
    return object.__new__(cls)


def test_the_table_names_each_route_once_with_its_own_handle_and_source():
    routes = _metered_native._ROUTES
    assert set(routes) == {CodexOperatorProvider, ClaudeOperatorProvider}
    assert routes[CodexOperatorProvider].handle is CodexOperatorHandle
    assert routes[ClaudeOperatorProvider].handle is ClaudeOperatorHandle
    assert routes[CodexOperatorProvider].source == "codex_fresh_thread_total_v1"
    assert routes[ClaudeOperatorProvider].source == "claude_main_loop_v1"
    # Every source the core vocabulary admits has exactly one route, and no other.
    assert sorted(route.source for route in routes.values()) == sorted(get_args(MeteringSource))
    with pytest.raises(TypeError):
        routes[object] = routes[CodexOperatorProvider]  # type: ignore[index]


@pytest.mark.parametrize("cls", [CodexOperatorProvider, ClaudeOperatorProvider])
def test_admission_is_by_exact_class_never_by_subclass(cls):
    class Relabelled(cls):
        pass

    assert is_metered_route(bare(cls))
    assert not is_metered_route(bare(Relabelled))
    assert not is_metered_route(object())


class Journal:
    def __init__(self):
        self.meters = []

    def executor_meter(self, context, *, revision, source, configured_model):
        self.meters.append((revision, source, configured_model))
        return ("meter", source)


class Identity:
    revision = "revision"


class Acquisition:
    def __init__(self, resource):
        self.resource = resource


@pytest.fixture
def codex(monkeypatch):
    """A provider of exactly the Codex class whose acquire returns a chosen handle."""
    events: list[object] = []

    async def acquire(self, context):
        events.append("acquire")
        return Acquisition(self.handle)

    async def relinquish(self, acquisition):
        events.append("relinquish")

    monkeypatch.setattr(CodexOperatorProvider, "identity", Identity())
    monkeypatch.setattr(CodexOperatorProvider, "acquire", acquire)
    monkeypatch.setattr(CodexOperatorProvider, "relinquish", relinquish)
    monkeypatch.setattr(
        CodexOperatorHandle, "install_meter", lambda self, meter: events.append(meter),
    )
    monkeypatch.setattr(
        ClaudeOperatorHandle, "install_meter", lambda self, meter: events.append("wrong"),
    )
    provider = bare(CodexOperatorProvider)
    provider.configured_model = "model-a"
    return provider, events


def test_a_route_installs_the_meter_on_its_own_handle(codex):
    provider, events = codex
    provider.handle = bare(CodexOperatorHandle)
    journal = Journal()
    acquisition = asyncio.run(MeteredNativeOperator(journal, provider).acquire(object()))
    assert acquisition.resource is provider.handle
    assert events == ["acquire", ("meter", "codex_fresh_thread_total_v1")]
    assert journal.meters == [("revision", "codex_fresh_thread_total_v1", "model-a")]


def test_a_route_never_meters_another_routes_handle(codex):
    provider, events = codex
    provider.handle = bare(ClaudeOperatorHandle)
    with pytest.raises(ContractViolation, match="exact supported native handle"):
        asyncio.run(MeteredNativeOperator(Journal(), provider).acquire(object()))
    # The acquisition is given back, and the other vendor's handle got no meter.
    assert events == ["acquire", "relinquish"]


def test_an_unlisted_provider_is_refused_before_any_meter_or_acquisition():
    journal = Journal()
    operator = MeteredNativeOperator(journal, object())  # type: ignore[arg-type]
    with pytest.raises(ContractViolation, match="exact supported native adapter"):
        asyncio.run(operator.acquire(object()))
    assert journal.meters == []
