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

ROUTES = {
    CodexOperatorProvider: (CodexOperatorHandle, "codex_fresh_thread_total_v1"),
    ClaudeOperatorProvider: (ClaudeOperatorHandle, "claude_main_loop_v1"),
}
OTHER = {CodexOperatorProvider: ClaudeOperatorHandle, ClaudeOperatorProvider: CodexOperatorHandle}


def bare(cls):
    """An instance of exactly ``cls`` with no state; only its type is asked."""
    return object.__new__(cls)


def test_the_table_names_each_route_once_with_its_own_handle_and_source():
    routes = _metered_native._ROUTES
    assert isinstance(routes, tuple)
    assert {route.provider: (route.handle, route.source) for route in routes} == ROUTES
    assert len(routes) == len(ROUTES)
    # Every source the core vocabulary admits has exactly one route, and no other.
    assert sorted(route.source for route in routes) == sorted(get_args(MeteringSource))


class Journal:
    def __init__(self, events):
        self.events = events

    def executor_meter(self, context, *, revision, source, configured_model):
        self.events.append(("meter", revision, source, configured_model))
        return ("writer", source)


class Identity:
    revision = "revision"


class Acquisition:
    def __init__(self, resource):
        self.resource = resource


class Vendor:
    model = "model-a"


class Launcher:
    def __init__(self, claude):
        self.claude = claude


@pytest.fixture
def events(monkeypatch):
    """One ordered trace of every side effect; both vendors' classes are stubbed."""
    trace: list[object] = []

    async def acquire(self, context):
        trace.append("acquire")
        return Acquisition(self.handle)

    async def relinquish(self, acquisition):
        trace.append("relinquish")

    for provider, handle in ((CodexOperatorProvider, CodexOperatorHandle),
                             (ClaudeOperatorProvider, ClaudeOperatorHandle)):
        monkeypatch.setattr(provider, "identity", Identity())
        monkeypatch.setattr(provider, "acquire", acquire)
        monkeypatch.setattr(provider, "relinquish", relinquish)
        monkeypatch.setattr(
            handle, "install_meter",
            lambda self, meter, name=handle.__name__: trace.append(("install", name, meter)),
        )
    return trace


def provider_of(cls, handle_cls):
    provider = bare(cls)
    provider.configured_model = "model-a"
    provider.launcher = Launcher(Vendor())
    provider.handle = bare(handle_cls)
    return provider


def acquire(provider, events):
    return asyncio.run(MeteredNativeOperator(Journal(events), provider).acquire(object()))


@pytest.mark.parametrize("cls", list(ROUTES))
def test_a_route_installs_its_meter_on_its_own_handle(events, cls):
    handle_cls, source = ROUTES[cls]
    provider = provider_of(cls, handle_cls)
    assert is_metered_route(provider)
    assert acquire(provider, events).resource is provider.handle
    assert events == [
        ("meter", "revision", source, "model-a"),
        "acquire",
        ("install", handle_cls.__name__, ("writer", source)),
    ]


@pytest.mark.parametrize("cls", list(ROUTES))
def test_a_route_never_meters_the_other_routes_handle(events, cls):
    provider = provider_of(cls, OTHER[cls])
    with pytest.raises(ContractViolation, match="exact supported native handle"):
        acquire(provider, events)
    # The acquisition is given back, and no handle of either vendor got a meter.
    assert events[1:] == ["acquire", "relinquish"] and len(events) == 3


@pytest.mark.parametrize("cls", list(ROUTES))
def test_a_subclass_of_a_route_is_refused_before_any_meter_or_acquisition(events, cls):
    class Relabelled(cls):
        pass

    provider = provider_of(Relabelled, ROUTES[cls][0])
    assert not is_metered_route(provider)
    with pytest.raises(ContractViolation, match="exact supported native adapter"):
        acquire(provider, events)
    assert events == []


@pytest.mark.parametrize("cls", list(ROUTES))
def test_a_class_that_only_equals_a_route_is_refused(events, cls):
    """Admission is class identity: equality and hashing never stand in for it."""

    class Equal(type):
        def __hash__(self):
            return hash(cls)

        def __eq__(self, other):
            return other is cls or other is self

    class Impostor(cls, metaclass=Equal):
        pass

    assert Impostor == cls and hash(Impostor) == hash(cls)
    provider = provider_of(Impostor, ROUTES[cls][0])
    assert not is_metered_route(provider)
    with pytest.raises(ContractViolation, match="exact supported native adapter"):
        acquire(provider, events)
    assert events == []


def test_a_resource_whose_class_cannot_be_hashed_is_simply_not_a_route():
    class Unhashable(type):
        __hash__ = None  # type: ignore[assignment]

    class Resource(metaclass=Unhashable):
        pass

    assert not is_metered_route(Resource())
    assert not is_metered_route(object())


def test_a_claude_operator_with_no_fixed_model_is_refused_before_any_meter(events):
    provider = provider_of(ClaudeOperatorProvider, ClaudeOperatorHandle)
    provider.launcher = Launcher(None)
    with pytest.raises(ContractViolation, match="has no fixed model"):
        acquire(provider, events)
    assert events == []
