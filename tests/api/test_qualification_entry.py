"""The qualification entry drives the real lifecycle of an unavailable provider.

Credential-free: the adapter suite's real codex provider over its portable
store, with the guard substituted (Linux proves the real flock separately).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from constructicon.api.qualification import (
    EXECUTOR,
    SCOPE,
    qualification_graph,
    qualify,
)
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.core.manifest import source_graph_hash_for
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.run import RunStatus
from constructicon.substrate.executors.codex import (
    UNQUALIFIED_PREREQUISITES,
    CodexOperatorProvider,
)
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import FakeClock, InjectedCrash
from tests.substrate import test_codex_adapter as adapter
from tests.substrate.test_codex_adapter import (
    BINARY,
    CAPABILITY,
    CONFIGURATION,
    EXPECTED,
    GRANTS,
    bare_launcher,
    codex_profile,
    identity_for,
)

portable_binding = adapter.portable_binding
substituted_guard = adapter.substituted_guard


def provider(tmp_path: Path, binding, qualification=None) -> CodexOperatorProvider:
    launcher = bare_launcher()
    return CodexOperatorProvider(
        launcher=launcher, profile=codex_profile(),
        identity=identity_for(launcher, store_identity=binding[1].sealed),
        expected_account=EXPECTED, binary=BINARY, configuration=CONFIGURATION, catalog=(),
        acquisition_root=tmp_path / "acquisitions",
        binding_store=binding[1], closure=binding[2], qualification=qualification,
    )


def authorization(tmp_path: Path, binding, clock: FakeClock, **changes):
    plain = provider(tmp_path, binding)
    fields = {
        "authorization_id": "ci-fixture",
        "stage": "qualification-no-dispatch",
        "actor_id": "operator:qualification",
        "idempotency_key": "stage1",
        "scope": SCOPE,
        "binding": EXECUTOR,
        "source_graph_hash": source_graph_hash_for(qualification_graph(CAPABILITY)),
        "capability_id": CAPABILITY,
        "revision": plain.identity.revision,
        "operator_binding_digest": plain.identity.store.operator_binding_digest,
        "journal": str(tmp_path / "qualification.sqlite"),
        "max_epoch": 1,
        "not_after": datetime.now(UTC) + timedelta(hours=2),
    }
    return QualificationAuthorization(**{**fields, **changes})


def rows(granted) -> list[tuple[int, str, str | None]]:
    journal = SqliteJournal(granted.journal)
    return [
        (row.acquisition_epoch, row.state, row.disposition)
        for row in journal.capability_leases(granted.run_id)
    ]


def dying_after_materialization(qualified: CodexOperatorProvider) -> None:
    """Materialize for real, then die as a process does: no handler runs, so the
    recorded row stays active and the handle keeps its custody."""
    acquire = qualified.acquire

    async def acquire_then_die(context):
        acquisition = await acquire(context)
        real = acquisition.materialize
        assert real is not None

        async def materialize_then_die():
            await real()
            raise InjectedCrash("process death after materialization")

        return replace(acquisition, materialize=materialize_then_die)

    qualified.acquire = acquire_then_die


async def test_the_authorized_run_materializes_and_closes_without_dispatching(
    tmp_path, portable_binding, substituted_guard, clock
):
    granted = authorization(tmp_path, portable_binding, clock)
    qualified = provider(tmp_path, portable_binding, granted)

    status = await qualify(provider=qualified, grants=GRANTS, timeout_s=30, now_fn=clock.now)

    assert status is RunStatus.SUCCEEDED
    assert qualified.unavailable_reasons == UNQUALIFIED_PREREQUISITES
    (handle,) = qualified.handles
    assert handle.entered and handle.dispatch is False and not handle.executed
    assert rows(granted) == [(1, "closed", "released")]


async def test_a_rerun_replays_the_same_run_and_acquires_nothing_more(
    tmp_path, portable_binding, substituted_guard, clock
):
    granted = authorization(tmp_path, portable_binding, clock)
    assert await qualify(
        provider=provider(tmp_path, portable_binding, granted),
        grants=GRANTS, timeout_s=30, now_fn=clock.now,
    ) is RunStatus.SUCCEEDED
    again = provider(tmp_path, portable_binding, granted)
    assert await qualify(
        provider=again, grants=GRANTS, timeout_s=30, now_fn=clock.now,
    ) is RunStatus.SUCCEEDED
    assert again.handles == [] and rows(granted) == [(1, "closed", "released")]


@pytest.mark.parametrize(
    ("max_epoch", "outcome", "expected"),
    [
        (1, RunStatus.FAILED, [(1, "closed", "discarded")]),
        (2, RunStatus.SUCCEEDED, [(1, "closed", "discarded"), (2, "closed", "released")]),
    ],
    ids=["budget-spent", "one-recovery-permitted"],
)
async def test_a_successor_reconciles_and_acquires_only_within_the_budget(
    tmp_path, portable_binding, substituted_guard, clock, max_epoch, outcome, expected
):
    """A run abandoned holding its materialized acquisition, as by process death.
    The successor reconciles it; a new acquisition needs an authorized epoch."""
    granted = authorization(tmp_path, portable_binding, clock, max_epoch=max_epoch)
    first = provider(tmp_path, portable_binding, granted)
    dying_after_materialization(first)
    with pytest.raises(TimeoutError):
        await qualify(provider=first, grants=GRANTS, timeout_s=2, now_fn=clock.now)
    assert rows(granted) == [(1, "active", None)]
    assert first.handles[0].ready, "the dead owner's handle still holds its custody"

    clock.advance(timedelta(minutes=5).total_seconds())
    successor = provider(tmp_path, portable_binding, granted)
    status = await qualify(provider=successor, grants=GRANTS, timeout_s=30, now_fn=clock.now)

    assert status is outcome
    assert rows(granted) == expected
    assert all(handle.dispatch is False for handle in successor.handles)


async def test_an_unauthorized_provider_or_invocation_is_refused_before_any_journal(
    tmp_path, portable_binding, clock
):
    with pytest.raises(ContractViolation, match="assembled with its authorization"):
        await qualify(provider=provider(tmp_path, portable_binding), grants=GRANTS, timeout_s=1)
    elsewhere = authorization(
        tmp_path, portable_binding, clock,
        source_graph_hash=digest("test-graph", 1, "another"),
    )
    with pytest.raises(ContractViolation, match="does not name this qualification"):
        await qualify(
            provider=provider(tmp_path, portable_binding, elsewhere), grants=GRANTS, timeout_s=1,
        )
    assert not Path(elsewhere.journal).exists()


async def test_an_expired_authorization_admits_but_never_acquires(
    tmp_path, portable_binding, substituted_guard, clock
):
    granted = authorization(
        tmp_path, portable_binding, clock, not_after=datetime.now(UTC) - timedelta(seconds=1),
    )
    qualified = provider(tmp_path, portable_binding, granted)
    status = await qualify(provider=qualified, grants=GRANTS, timeout_s=30, now_fn=clock.now)
    assert status is RunStatus.FAILED and qualified.handles == [] and rows(granted) == []


def test_the_fixed_graph_is_one_executor_node_without_loops():
    graph = qualification_graph(CAPABILITY)
    (node,) = graph.nodes
    assert (graph.name, node.id) == tuple(SCOPE.segments)
    assert node.body.bind == {EXECUTOR: CAPABILITY} and node.body.version
