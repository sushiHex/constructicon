"""Administrative abandonment is one durable command, never provider cleanup."""

from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.control import (
    ADMIN_SCOPE,
    OPERATE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    CapabilityAcquisitionPair,
    CapabilityDisposalResult,
    ControlCode,
    ControlRejected,
    RunResultPreviewV2,
)
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import canonical_json
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import FakeClock, InjectedCrash
from tests.migrations.test_sqlite_v7_to_v8 import historical_database
from tests.run_worlds import create_test_run, start_test_run
from tests.substrate.journal.test_capability_accounting_snapshot import acquire

RUN = RunId("run-disposal-fixture")
ADMIN = AuthenticatedActor(actor_id="static:disposal-admin", auth_method="static",
                           scopes=frozenset({ADMIN_SCOPE}))
READER = AuthenticatedActor(actor_id="static:disposal-reader", auth_method="static",
                            scopes=frozenset({READ_SCOPE}))
OPERATOR = AuthenticatedActor(actor_id="static:disposal-operator", auth_method="static",
                              scopes=frozenset({OPERATE_SCOPE}))


@dataclass
class DisposalWorld:
    journal: SqliteJournal
    clock: FakeClock
    system: Constructicon
    host: RunHost
    control: ControlPlane
    run_id: RunId
    pairs: tuple[CapabilityAcquisitionPair, ...]
    executions: list[object]
    database: Path


@asynccontextmanager
async def disposal_world(tmp_path: Path, *, historical: bool = False):
    assert callable(getattr(ControlPlane, "runs_dispose_capabilities", None)), (
        "the typed administrative disposal facade is required"
    )
    database = tmp_path / "disposal-api.db"
    historical_database(database, "schema6-initial-lifecycle.sql" if historical
                        else "schema8-disposal-baseline.sql")
    clock = FakeClock()
    journal = SqliteJournal(database, now_fn=clock.now)
    run_id = RunId("run-historical-capabilities") if historical else RUN
    system = Constructicon(journal=journal)
    executions = []

    async def unexpected_execution(*args, **kwargs):
        executions.append((args, kwargs))
        raise AssertionError("disposal must not invoke a worker or its providers")

    system._run_prepared = unexpected_execution
    host = RunHost(system, journal=journal, now_fn=clock.now)
    # This is the already observed cleanup-failure state, not startup recovery.
    with sqlite3.connect(database) as connection:
        host._deferred.update(
            RunId(row[0]) for row in connection.execute("SELECT run_id FROM runs")
        )
    pairs = tuple(sorted((CapabilityAcquisitionPair(
        lease_id=row.lease_id, acquisition_epoch=row.acquisition_epoch,
    ) for row in journal.capability_leases(run_id)),
        key=lambda pair: (pair.lease_id, pair.acquisition_epoch)))
    control = ControlPlane(system=system, store=journal, run_host=host, owner_id="disposal-api")
    world = DisposalWorld(
        journal, clock, system, host, control, run_id, pairs, executions, database,
    )
    await host.startup()
    assert executions == []
    try:
        yield world
    finally:
        await world.control.shutdown()
        assert executions == []


async def recover_control(world: DisposalWorld, owner_id: str) -> None:
    await world.control.shutdown()
    host = RunHost(world.system, journal=world.journal, now_fn=world.clock.now)
    with sqlite3.connect(world.database) as connection:
        host._deferred.update(
            RunId(row[0]) for row in connection.execute("SELECT run_id FROM runs")
        )
    world.host = host
    world.control = ControlPlane(system=world.system, store=world.journal, run_host=host,
                                 owner_id=owner_id)
    await host.startup()
    assert world.executions == []


async def dispose(world: DisposalWorld, *, key="dispose-api", reason="cleanup unavailable",
                  pairs=None, actor=ADMIN):
    return await world.control.runs_dispose_capabilities(
        actor, run_id=world.run_id, pairs=world.pairs if pairs is None else pairs,
        reason=reason, idempotency_key=key,
    )


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from walk(child)
    elif isinstance(value, str) and value.startswith(("{", "[")):
        try:
            decoded = json.loads(value)
        except ValueError:
            return
        yield from walk(decoded)


def diagnostic_pairs(response: ControlRejected):
    return {(node["lease_id"], node["acquisition_epoch"])
            for node in walk(response.model_dump(mode="json"))
            if isinstance(node, dict) and {"lease_id", "acquisition_epoch"} <= node.keys()}


def public_bundle(world: DisposalWorld, result: CapabilityDisposalResult):
    events = world.control.runs_events(READER, world.run_id, limit=100)
    preview = world.control.runs_result(READER, world.run_id)
    assert not isinstance(events, ControlRejected)
    assert isinstance(preview, RunResultPreviewV2)
    receipt = world.control.details_read(READER, result.receipt, max_bytes=64_000)
    accounting = world.control.details_read(
        READER, preview.capability_accounting.detail, max_bytes=64_000,
    )
    assert not isinstance(receipt, ControlRejected)
    assert not isinstance(accounting, ControlRejected)
    assert receipt.next_cursor is accounting.next_cursor is None
    event_details = []
    for event in events.items:
        detail = world.control.details_read(READER, event.detail, max_bytes=64_000)
        assert not isinstance(detail, ControlRejected)
        assert detail.next_cursor is None
        event_details.append(detail.model_dump(mode="json"))
    return {
        "result": result.model_dump(mode="json"), "events": events.model_dump(mode="json"),
        "preview": preview.model_dump(mode="json"),
        "receipt": receipt.model_dump(mode="json"),
        "accounting": accounting.model_dump(mode="json"), "event_details": event_details,
    }


async def test_admin_disposal_commits_one_receipt_and_replays_without_provider_work(tmp_path):
    async with disposal_world(tmp_path) as world:
        before = world.journal.run_head(world.run_id)
        result = await dispose(world, pairs=[pair.model_dump(mode="json")
                                           for pair in reversed(world.pairs)])
        assert isinstance(result, CapabilityDisposalResult)
        assert result.pairs == world.pairs and result.count == 2
        assert result.command.replayed is False and result.physical_cleanup == "unverified"
        after = world.journal.run_head(world.run_id)
        assert after.record == before.record and after.event_seq == before.event_seq + 3
        assert world.run_id in world.host._deferred
        assert all(row.state == "lost" and row.disposition is None
                   for row in world.journal.capability_leases(world.run_id))
        replay = await dispose(world)
        assert isinstance(replay, CapabilityDisposalResult)
        assert replay.command.command_id == result.command.command_id
        assert replay.command.replayed is True and replay.receipt == result.receipt
        assert world.journal.run_head(world.run_id) == after
        bundle = public_bundle(world, result)
        assert json.loads(bundle["receipt"]["text"])["pairs"] == [
            pair.model_dump(mode="json") for pair in world.pairs
        ]
        preview = world.control.runs_result(READER, world.run_id)
        assert preview.capability_accounting.disposed_count == 2
        assert preview.capability_accounting.opaque_lost_count == 0


@pytest.mark.parametrize("actor", (OPERATOR, READER))
async def test_disposal_admin_gate_precedes_startup_and_claim(tmp_path, actor, monkeypatch):
    async with disposal_world(tmp_path) as world:
        touched = []

        async def startup():
            touched.append("startup")
            raise AssertionError("an unauthorized disposal cannot start lifecycle work")

        def claim(**kwargs):
            touched.append("claim")
            raise AssertionError("an unauthorized disposal cannot claim a command")

        monkeypatch.setattr(world.control, "_admit_mutation", startup)
        monkeypatch.setattr(world.journal, "claim_command", claim)
        result = await dispose(world, actor=actor)
        assert isinstance(result, ControlRejected)
        assert result.faults[0].code is ControlCode.AUTH_REQUIRED_SCOPE
        assert touched == []


@pytest.mark.parametrize("bad", ("duplicate", "empty_reason", "bad_key"))
async def test_invalid_disposal_request_spends_no_command(tmp_path, bad, monkeypatch):
    async with disposal_world(tmp_path) as world:
        touched = []
        original = world.journal.claim_command

        def claim(**kwargs):
            touched.append(kwargs)
            return original(**kwargs)

        monkeypatch.setattr(world.journal, "claim_command", claim)
        result = await dispose(
            world, pairs=(world.pairs[0], world.pairs[0]) if bad == "duplicate" else world.pairs,
            reason="" if bad == "empty_reason" else "cleanup unavailable",
            key="" if bad == "bad_key" else "invalid-disposal",
        )
        assert isinstance(result, ControlRejected)
        assert result.faults[0].code is ControlCode.REQUEST_INVALID
        assert touched == []


async def test_disposal_refuses_even_an_expired_nonnull_worker_owner(tmp_path):
    async with disposal_world(tmp_path) as world:
        worker = world.journal.claim_run(world.run_id, owner_id="unreleased-worker", ttl_s=30)
        world.clock.advance(31)
        before = world.journal.run_head(world.run_id)
        try:
            result = await dispose(world)
        except (ContractViolation, JournalDamaged) as exc:
            pytest.fail(f"an owned run must receive a typed disposal refusal, not {exc!r}")
        assert isinstance(result, ControlRejected)
        assert world.journal.run_head(world.run_id) == before
        assert all(row.state == "active" for row in world.journal.capability_leases(world.run_id))
        world.journal.release_run(worker)
        assert canonical_json(await dispose(world)) == canonical_json(result)
        assert all(row.state == "active" for row in world.journal.capability_leases(world.run_id))


async def test_disposal_itemizes_every_bad_pair_and_preserves_the_entire_batch(tmp_path):
    async with disposal_world(tmp_path, historical=True) as world:
        foreign = RunId("foreign-disposal-pair")
        create_test_run(world.journal, foreign)
        world.host._deferred.add(foreign)
        worker = start_test_run(world.journal, foreign, owner_id="foreign-worker")
        row = acquire(world.journal, worker, "foreign")
        wrong = CapabilityAcquisitionPair(lease_id=row.lease_id,
                                         acquisition_epoch=row.acquisition_epoch)
        missing = CapabilityAcquisitionPair(lease_id="missing-disposal-pair", acquisition_epoch=1)
        historical_bad = tuple(pair for pair in world.pairs if next(
            item.state for item in world.journal.capability_leases(world.run_id)
            if item.lease_id == pair.lease_id) != "active")
        bad = (*historical_bad, wrong, missing)
        before = world.journal.capability_leases(world.run_id)
        result = await dispose(world, pairs=bad)
        assert isinstance(result, ControlRejected)
        assert diagnostic_pairs(result) == {(pair.lease_id, pair.acquisition_epoch) for pair in bad}
        details = result.faults[0].details
        assert details["run_faults"] == []
        diagnostics = {(item["lease_id"], item["acquisition_epoch"]): item
                       for item in details["pairs"]}
        for item in before:
            if item.state in {"closed", "lost"}:
                observed = diagnostics[(item.lease_id, item.acquisition_epoch)]
                assert observed["problem"] == (
                    "closed" if item.state == "closed" else "opaque_lost"
                )
                assert observed["state"] == item.state
                assert observed["disposition"] == item.disposition
        assert diagnostics[(wrong.lease_id, wrong.acquisition_epoch)]["problem"] == "wrong_run"
        assert diagnostics[(missing.lease_id, missing.acquisition_epoch)]["problem"] == (
            "missing_pair"
        )
        assert world.journal.capability_leases(world.run_id) == before
        assert not any(event.kind == "CapabilityDisposalRecorded"
                       for event in world.journal.events(world.run_id))
        replay = await dispose(world, pairs=bad)
        assert canonical_json(replay) == canonical_json(result)


async def test_disposal_changed_reason_conflicts_and_fresh_lost_request_has_public_receipt(
    tmp_path,
):
    async with disposal_world(tmp_path) as world:
        first = await dispose(world)
        assert isinstance(first, CapabilityDisposalResult)
        fence = world.journal.max_event_seq(world.run_id)
        conflict = await dispose(world, reason="different administrative reason")
        assert isinstance(conflict, ControlRejected)
        assert conflict.faults[0].code is ControlCode.IDEMPOTENCY_CONFLICT
        rejected = await dispose(world, key="fresh-key")
        assert isinstance(rejected, ControlRejected)
        assert diagnostic_pairs(rejected) == {
            (p.lease_id, p.acquisition_epoch) for p in world.pairs
        }
        assert rejected.faults[0].details["run_faults"] == []
        assert all(item["problem"] == "already_disposed" and item["state"] == "lost"
                   and item["disposition"] is None for item in rejected.faults[0].details["pairs"])
        references = [node for node in walk(rejected.model_dump(mode="json"))
                      if isinstance(node, dict) and node.get("uri") == first.receipt.uri]
        assert references
        assert all(node["digest"] == str(first.receipt.digest) for node in references)
        assert world.journal.max_event_seq(world.run_id) == fence


@pytest.mark.parametrize(
    "seam", ("after_plan", "after_domain_mutation", "after_command_completion"),
)
async def test_disposal_each_commit_seam_replays_one_domain_batch(tmp_path, seam):
    async with disposal_world(tmp_path) as world:
        reached = []

        def crash(name):
            if name == "runs_dispose_capabilities." + seam:
                reached.append(name)
                raise InjectedCrash()

        world.control._commands._fault_probe = crash
        before = world.journal.max_event_seq(world.run_id)
        with pytest.raises(InjectedCrash):
            await dispose(world)
        assert reached == ["runs_dispose_capabilities." + seam]
        expected = before + (0 if seam == "after_plan" else 3)
        assert world.journal.max_event_seq(world.run_id) == expected
        if seam != "after_plan":
            # A lawful worker handoff cannot invalidate the command's historical receipt.
            worker = world.journal.claim_run(world.run_id, owner_id="intervening-worker", ttl_s=30)
            world.journal.release_run(worker)
            assert world.journal.max_event_seq(world.run_id) == before + 3
        world.clock.advance(31)
        await recover_control(world, "recovered-disposal-api")
        recovered = await dispose(world)
        assert isinstance(recovered, CapabilityDisposalResult)
        assert recovered.command.replayed is (seam == "after_command_completion")
        assert world.journal.max_event_seq(world.run_id) == before + 3
        assert sum(event.kind == "CapabilityDisposalRecorded"
                   for event in world.journal.events(world.run_id)) == 1
        assert world.journal.command(recovered.command.command_id).state == "committed"
        assert isinstance(await dispose(world), CapabilityDisposalResult)
        assert world.journal.max_event_seq(world.run_id) == before + 3


async def test_superseded_disposal_comparison_crash_uses_plan_refusal_after_later_release(tmp_path):
    responses = []
    for interrupted in (False, True):
        directory = tmp_path / str(interrupted)
        directory.mkdir()
        async with disposal_world(directory) as world:
            reached = []
            with sqlite3.connect(world.database) as connection:
                baseline_epoch = connection.execute(
                    "SELECT owner_epoch FROM runs WHERE run_id=?", (world.run_id,),
                ).fetchone()[0]

            def probe(name, *, reached=reached, interrupted=interrupted):
                if name == "runs_dispose_capabilities.after_plan":
                    worker = world.journal.claim_run(world.run_id, owner_id="superseding-worker",
                                                    ttl_s=30)
                    world.journal.release_run(worker)
                    reached.append("superseded")
                if name == "runs_dispose_capabilities.after_domain_comparison" and interrupted:
                    reached.append("comparison")
                    raise InjectedCrash()

            world.control._commands._fault_probe = probe
            if interrupted:
                with pytest.raises(InjectedCrash):
                    await dispose(world)
                assert reached == ["superseded", "comparison"]
                later = world.journal.claim_run(world.run_id, owner_id="later-worker", ttl_s=30)
                world.journal.release_run(later)
                world.clock.advance(31)
                await recover_control(world, "recovered-refusal")
                try:
                    result = await dispose(world)
                except (ContractViolation, JournalDamaged) as exc:
                    pytest.fail(f"a superseded plan must replay a typed refusal, not {exc!r}")
            else:
                try:
                    result = await dispose(world)
                except (ContractViolation, JournalDamaged) as exc:
                    pytest.fail(
                        f"a released superseding worker must yield a typed refusal, not {exc!r}"
                    )
                assert reached == ["superseded"]
            assert isinstance(result, ControlRejected)
            with sqlite3.connect(world.database) as connection:
                assert connection.execute(
                    "SELECT owner_id,owner_epoch FROM runs WHERE run_id=?", (world.run_id,),
                ).fetchone() == (None, baseline_epoch + (2 if interrupted else 1))
            assert all(row.state == "active"
                       for row in world.journal.capability_leases(world.run_id))
            assert not any(event.kind == "CapabilityDisposalRecorded"
                           for event in world.journal.events(world.run_id))
            responses.append(canonical_json(result))
            assert canonical_json(await dispose(world)) == responses[-1]
    assert responses[0] == responses[1]


async def test_public_disposal_bytes_and_hashes_cannot_enumerate_private_reasons(tmp_path):
    bundles = []
    private = []
    reasons = ("administrative private reason alpha", "administrative private reason beta")
    for index, reason in enumerate(reasons):
        directory = tmp_path / str(index)
        directory.mkdir()
        async with disposal_world(directory) as world:
            result = await dispose(world, reason=reason)
            assert isinstance(result, CapabilityDisposalResult)
            command = world.journal.command(result.command.command_id)
            assert command.request["reason"] == reason
            assert reason in canonical_json(command.plan)
            bundle = public_bundle(world, result)
            raw = canonical_json(bundle)
            with sqlite3.connect(world.database) as connection:
                private_hashes = [row[0] for row in connection.execute(
                    "SELECT fact_hash FROM durable_fact_seals"
                    " WHERE family IN ('command_claim', 'command_plan', 'capability_disposal')"
                ).fetchall()]
            assert str(command.request_hash) not in raw
            assert all(str(value) not in raw for value in private_hashes)
            assert all(reason not in raw for reason in reasons)
            forbidden = {
                "request_hash", "plan_hash", "request_digest", "plan_digest", "reason_hash",
                "request", "plan", "reason", "actor", "actor_id", "private_relationship",
            }
            assert not any(forbidden.intersection(node) for node in walk(bundle)
                           if isinstance(node, dict))
            denied = world.control.commands_status(READER, result.command.command_id)
            assert isinstance(denied, ControlRejected)
            command_uri = f"constructicon://commands/{result.command.command_id}"
            assert isinstance(world.control.resource_read(READER, command_uri), ControlRejected)
            privileged = world.control.resource_read(ADMIN, command_uri, max_bytes=64_000)
            assert not isinstance(privileged, ControlRejected)
            assert json.loads(privileged.text)["request"]["reason"] == reason
            private.append(str(command.request_hash))
            bundles.append(raw)
    assert private[0] != private[1]
    assert bundles[0] == bundles[1]
