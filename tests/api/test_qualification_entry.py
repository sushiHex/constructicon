"""The qualification entry drives the real lifecycle of an unavailable provider.

Credential-free: the adapter suite's real codex provider over its portable
store, with the guard substituted (Linux proves the real flock separately).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.api import qualification
from constructicon.api.qualification import (
    EXECUTOR,
    FIXED,
    SCOPE,
    qualification_graph,
    qualify,
)
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorError, ExecutorFailure, ExecutorSuccess
from constructicon.core.identity import digest
from constructicon.core.manifest import source_graph_hash_for
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.run import RunStatus
from constructicon.runtime.walker import DEFAULT_LEASE_TTL_S
from constructicon.substrate.executors.codex import (
    UNQUALIFIED_PREREQUISITES,
    CodexOperatorHandle,
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
    clean_native,
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


def after_materialization(qualified: CodexOperatorProvider, then) -> None:
    """Materialize for real, then hand the live acquisition's context to ``then``."""
    acquire = qualified.acquire

    async def acquire_then(context):
        acquisition = await acquire(context)
        real = acquisition.materialize
        assert real is not None

        async def materialize_then():
            await real()
            await then(context)

        return replace(acquisition, materialize=materialize_then)

    qualified.acquire = acquire_then


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


async def test_a_lost_lease_record_answer_closes_the_qualification_row(
    tmp_path, portable_binding, substituted_guard, clock, monkeypatch
):
    """Lease recording: the row commits, its answer is lost; settled against
    the journal, it is closed under the fence (#131), and the run fails."""

    class AnswerLost(SqliteJournal):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            armed = [True]

            def probe(name: str) -> None:
                if name == "lease.after_record_commit" and armed:
                    armed.pop()
                    raise ConnectionError("the commit's answer was lost")

            self.fault_probe = probe

    monkeypatch.setattr(qualification, "SqliteJournal", AnswerLost)
    granted = authorization(tmp_path, portable_binding, clock)
    qualified = provider(tmp_path, portable_binding, granted)

    status = await qualify(provider=qualified, grants=GRANTS, timeout_s=30, now_fn=clock.now)

    assert status is RunStatus.FAILED
    assert rows(granted) == [(1, "closed", "discarded")]
    assert [handle.dispatch for handle in qualified.handles] == [False]


async def test_a_cancellation_mid_materialization_discards_and_cancels(
    tmp_path, portable_binding, substituted_guard, clock
):
    granted = authorization(tmp_path, portable_binding, clock)
    qualified = provider(tmp_path, portable_binding, granted)

    async def cancel(context):
        SqliteJournal(granted.journal, now_fn=clock.now).request_cancel(granted.run_id)
        context.check_control()

    after_materialization(qualified, cancel)
    status = await qualify(provider=qualified, grants=GRANTS, timeout_s=30, now_fn=clock.now)

    assert status is RunStatus.CANCELLED
    assert rows(granted) == [(1, "closed", "discarded")]
    (handle,) = qualified.handles
    assert handle._store_lock is None and handle._guard_owner is None


async def test_an_ownership_loss_relinquishes_and_a_successor_completes(
    tmp_path, portable_binding, substituted_guard, clock
):
    """Loss of ownership mid-materialization: the loser relinquishes its custody
    and closes nothing (#130); the successor reconciles and, within a budget of
    three (the thief's claim spends one), acquires again and completes."""
    granted = authorization(tmp_path, portable_binding, clock, max_epoch=3)
    loser = provider(tmp_path, portable_binding, granted)

    async def lose(context):
        thief = SqliteJournal(granted.journal, now_fn=clock.now)
        clock.advance(DEFAULT_LEASE_TTL_S + 1)
        thief.claim_run(granted.run_id, owner_id="thief", ttl_s=DEFAULT_LEASE_TTL_S)
        while True:  # the heartbeat latches the loss; control then observes it
            context.check_control()
            await asyncio.sleep(0.1)

    after_materialization(loser, lose)
    with pytest.raises(TimeoutError):
        await qualify(provider=loser, grants=GRANTS, timeout_s=20, now_fn=clock.now)
    (handle,) = loser.handles
    assert handle.closed and handle._store_lock is None and handle._guard_owner is None
    assert not portable_binding[2].is_closed(handle.paths), "the loser disposed durably"
    assert rows(granted) == [(1, "active", None)]

    # The budget counts ownership claims: the thief's claim spent epoch 2, so
    # this successor claims epoch 3, which a budget of three admits.
    clock.advance(DEFAULT_LEASE_TTL_S + 1)
    successor = provider(tmp_path, portable_binding, granted)
    status = await qualify(provider=successor, grants=GRANTS, timeout_s=30, now_fn=clock.now)
    assert status is RunStatus.SUCCEEDED
    assert rows(granted) == [(1, "closed", "discarded"), (3, "closed", "released")]


async def test_a_journal_holding_another_run_is_refused_before_recovery(
    tmp_path, portable_binding, clock
):
    """The journal is the qualification's alone: its RunHost would resume
    whatever the journal holds, so a foreign run refuses the whole entry."""
    first = authorization(tmp_path, portable_binding, clock)
    assert await qualify(
        provider=provider(tmp_path, portable_binding, first), grants=GRANTS,
        timeout_s=30, now_fn=clock.now,
    ) in (RunStatus.SUCCEEDED, RunStatus.FAILED)
    second = authorization(tmp_path, portable_binding, clock, idempotency_key="another")
    with pytest.raises(ContractViolation, match="not this qualification's"):
        await qualify(
            provider=provider(tmp_path, portable_binding, second), grants=GRANTS,
            timeout_s=30, now_fn=clock.now,
        )


async def test_the_same_run_id_carrying_another_graph_is_refused_before_recovery(
    tmp_path, portable_binding, clock
):
    """A run id names only an actor and a key: a stored run with the authorized
    id but another graph is not this qualification's, and is never recovered."""
    first = authorization(tmp_path, portable_binding, clock)
    await qualify(
        provider=provider(tmp_path, portable_binding, first), grants=GRANTS,
        timeout_s=30, now_fn=clock.now,
    )
    other = "codex-other"
    regraphed = authorization(
        tmp_path, portable_binding, clock, capability_id=other,
        source_graph_hash=source_graph_hash_for(qualification_graph(other)),
    )
    assert regraphed.run_id == first.run_id
    with pytest.raises(ContractViolation, match="not this qualification's"):
        await qualify(
            provider=provider(tmp_path, portable_binding, regraphed), grants=GRANTS,
            timeout_s=30, now_fn=clock.now,
        )


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


def read_stage(tmp_path: Path, binding, journal: str = "read.sqlite"):
    """A read authorization over a scripted native client that answers once."""
    plain = provider(tmp_path, binding)
    granted = QualificationAuthorization(
        authorization_id="ci-read",
        stage="qualification-read",
        actor_id="operator:qualification",
        idempotency_key="stage3",
        scope=FIXED["qualification-read"].scope,
        binding=EXECUTOR,
        source_graph_hash=source_graph_hash_for(
            qualification_graph(CAPABILITY, "qualification-read"),
        ),
        capability_id=CAPABILITY,
        revision=plain.identity.revision,
        operator_binding_digest=plain.identity.store.operator_binding_digest,
        journal=str(tmp_path / journal),
        max_epoch=1,
        not_after=datetime.now(UTC) + timedelta(hours=2),
        grants=GRANTS,
        attempt_record=str(tmp_path / "stage3.attempt"),
    )
    reader = provider(tmp_path, binding, granted)
    reader.launcher = bare_launcher(clean_native())
    return reader, granted


async def test_the_read_run_dispatches_exactly_one_turn_and_records_it(
    tmp_path, portable_binding, substituted_guard, clock
):
    reader, granted = read_stage(tmp_path, portable_binding)
    status = await qualify(provider=reader, grants=GRANTS, timeout_s=30, now_fn=clock.now)
    assert status is RunStatus.SUCCEEDED
    (handle,) = reader.handles
    assert handle.dispatch is True and handle.executed
    assert rows(granted) == [(1, "closed", "released")]
    record = json.loads(Path(granted.attempt_record).read_text(encoding="utf-8"))
    assert (record["phase"], record["dispatch"]) == ("outcome", "completed")


async def test_a_reset_journal_cannot_spend_the_read_turn_again(
    tmp_path, portable_binding, substituted_guard, clock
):
    """The record, not the journal, spends the turn (S3-1)."""
    reader, _ = read_stage(tmp_path, portable_binding)
    await qualify(provider=reader, grants=GRANTS, timeout_s=30, now_fn=clock.now)
    again, _ = read_stage(tmp_path, portable_binding, journal="reset.sqlite")
    status = await qualify(provider=again, grants=GRANTS, timeout_s=30, now_fn=clock.now)
    assert status is RunStatus.FAILED and again.handles == []


def test_the_read_graph_pins_its_task_literal_in_the_node_source():
    """S3-3: the literal is inside the node, so the graph hash covers it."""
    source = inspect.getsource(qualification.qualification_read_node)
    (literal,) = re.findall(r'TaskSpec\(instruction="([^"]*)"\)', source)
    assert len(literal.encode("utf-8")) < 200
    graphs = {
        stage: source_graph_hash_for(qualification_graph(CAPABILITY, stage)) for stage in FIXED
    }
    assert len(set(graphs.values())) == len(FIXED)


@pytest.mark.parametrize(
    ("stage", "record"),
    [("qualification-read", []), ("qualification-no-dispatch", ["--attempt-record", "/x"])],
    ids=["read-without-record", "no-dispatch-with-record"],
)
def test_mint_requires_the_record_exactly_for_the_read_stage(
    tmp_path, stage, record, capsys, monkeypatch,
):
    flags = [
        "--session", "s", "--store-key", "k", "--sealed", "g", "--qualification", "q",
        "--state", "t", "--authorization-id", "a", "--actor", "o", "--key", "k",
        "--journal", "/j",
    ]
    # The parser refuses first; minting at all is the failure.
    monkeypatch.setattr(qualification, "mint", lambda _: pytest.fail("minted"))
    with pytest.raises(SystemExit) as stopped:
        qualification.main(["mint", *flags, "--stage", stage, *record])
    assert stopped.value.code == 2 and "--attempt-record" in capsys.readouterr().err


async def test_a_read_authorization_with_a_relative_record_is_not_this_qualification(
    tmp_path, portable_binding, substituted_guard, clock, monkeypatch,
):
    monkeypatch.chdir(tmp_path)  # a mutant without the check writes here, not the repo
    reader, granted = read_stage(tmp_path, portable_binding)
    reader.qualification = granted.model_copy(update={"attempt_record": "stage3.attempt"})
    with pytest.raises(ContractViolation, match="does not name this qualification"):
        await qualify(provider=reader, grants=GRANTS, timeout_s=30, now_fn=clock.now)
    assert not Path(granted.journal).exists()



@pytest.mark.parametrize(
    ("outcome", "answered"),
    [
        (ExecutorSuccess(output="done"), 4),
        (ExecutorFailure(output="salvaged", error=ExecutorError(kind="timeout", detail="t")), None),
        (ExecutorSuccess(output=None), None),
    ],
    ids=["answer", "salvaged-failure", "no-answer"],
)
async def test_the_read_node_reports_only_an_accepted_text_answer(outcome, answered):
    handle = object.__new__(CodexOperatorHandle)

    async def execute(task, *, workspace, grants):
        return outcome

    handle.execute = execute
    ctx = SimpleNamespace(capability=lambda alias: handle, grants=GRANTS)
    if answered is None:
        with pytest.raises(ContractViolation, match="the READ turn ended"):
            await qualification.qualification_read_node(ctx, {})
    else:
        report = await qualification.qualification_read_node(ctx, {})
        assert report == {"report": {"answer_bytes": answered}}
