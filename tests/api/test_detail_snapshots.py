"""Attempt-bound result detail is immutable, exact, and bounded to read."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from constructicon.api.cursor import CursorCodec
from constructicon.api.detail import DetailAddress, DetailResolver
from constructicon.core.address import RunId
from constructicon.core.component import ComponentMetadata, LearningProfile
from constructicon.core.control import (
    READ_SCOPE,
    AuthenticatedActor,
    ControlCode,
    ControlRejected,
    DetailRef,
)
from constructicon.core.graph import Ref
from constructicon.core.identity import digest
from constructicon.core.run import RunLease, RunStatus
from constructicon.runtime.registry import ComponentRegistry
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import pipeline_graph, triage_impl

ACTOR = AuthenticatedActor(
    actor_id="static:detail-reader",
    auth_method="static",
    scopes=frozenset({READ_SCOPE}),
)
TERMINAL_KINDS = {
    RunStatus.SUCCEEDED: "RunSucceeded",
    RunStatus.FAILED: "RunFailed",
    RunStatus.PARKED: "RunParked",
    RunStatus.CANCELLED: "RunCancelled",
}


def _prepare(world, suffix: str) -> RunId:
    inputs = {"issue": {"title": suffix}}
    manifest = world.validate(pipeline_graph(), inputs)
    run_id = RunId(f"run-detail-{suffix}")
    world._prepare_run(manifest, run_id=run_id, inputs=inputs)
    return run_id


def _resolver(world, journal: SqliteJournal) -> DetailResolver:
    return DetailResolver(
        system=world,
        store=journal,
        cursors=CursorCodec(),
        journal=journal,
        registry=ComponentRegistry(store=journal),
    )


def _terminalize(
    journal: SqliteJournal,
    run_id: RunId,
    status: RunStatus,
    *,
    owner: str = "detail-worker",
) -> RunLease:
    lease = journal.claim_run(run_id, owner_id=owner, ttl_s=30)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=status,
        event_kind=TERMINAL_KINDS[status],
        payload={"attempt": owner},
    )
    return lease


def _reference(
    resolver: DetailResolver,
    run_id: RunId,
) -> DetailRef:
    result = resolver.reference(ACTOR, DetailAddress.result(run_id))
    assert isinstance(result, DetailRef)
    return result


def _read(resolver: DetailResolver, reference: DetailRef, *, max_bytes: int = 64_000):
    result = resolver.read(ACTOR, reference, max_bytes=max_bytes)
    assert not isinstance(result, ControlRejected)
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("status", tuple(TERMINAL_KINDS))
async def test_every_terminal_outcome_has_attempt_bound_result_detail(
    world,
    journal: SqliteJournal,
    status: RunStatus,
) -> None:
    run_id = _prepare(world, status.value)
    lease = None
    if status is RunStatus.SUCCEEDED:
        result = await world._run_prepared(run_id)
        assert result.status is status
    else:
        lease = _terminalize(journal, run_id, status)

    resolver = _resolver(world, journal)
    reference = _reference(resolver, run_id)
    terminal = journal.latest_terminal_event(run_id)
    assert terminal is not None
    assert reference.uri == DetailAddress.result(run_id, terminal.seq)

    chunk = _read(resolver, reference)
    payload = json.loads(chunk.text)
    assert payload["run"]["status"] == status.value
    assert payload["terminal_event"]["kind"] == TERMINAL_KINDS[status]
    assert {
        "owner_id",
        "lease_expires_at",
        "liveness",
        "cancel_requested",
    }.isdisjoint(payload["run"])
    if lease is not None:
        journal.release_run(lease)


def test_failed_result_ref_survives_resume_and_later_terminal_attempt(
    world,
    journal: SqliteJournal,
) -> None:
    run_id = _prepare(world, "resume")
    first_lease = _terminalize(journal, run_id, RunStatus.FAILED, owner="attempt-one")
    resolver = _resolver(world, journal)
    first_ref = _reference(resolver, run_id)
    first_bytes = _read(resolver, first_ref).text
    journal.release_run(first_lease)

    second_lease = journal.claim_run(run_id, owner_id="attempt-two", ttl_s=30)
    journal.transition_run(
        second_lease,
        expected=frozenset({RunStatus.FAILED}),
        target=RunStatus.RUNNING,
        event_kind="RunResumed",
    )
    assert _read(resolver, first_ref).text == first_bytes

    journal.transition_run(
        second_lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.PARKED,
        event_kind="RunParked",
        payload={"attempt": "attempt-two"},
    )
    second_ref = _reference(resolver, run_id)
    journal.release_run(second_lease)

    assert second_ref.uri != first_ref.uri
    assert second_ref.digest != first_ref.digest
    assert _read(resolver, first_ref).text == first_bytes
    assert json.loads(_read(resolver, second_ref).text)["run"]["status"] == "parked"


def test_lease_release_does_not_change_terminal_result_digest(
    world,
    journal: SqliteJournal,
) -> None:
    run_id = _prepare(world, "lease-release")
    lease = _terminalize(journal, run_id, RunStatus.FAILED)
    resolver = _resolver(world, journal)
    reference = _reference(resolver, run_id)
    before = _read(resolver, reference)

    journal.release_run(lease)

    after = _read(resolver, reference)
    assert after.digest == before.digest == reference.digest
    assert after.text == before.text


def test_result_detail_rejects_digest_mismatch(
    world,
    journal: SqliteJournal,
) -> None:
    run_id = _prepare(world, "digest-mismatch")
    lease = _terminalize(journal, run_id, RunStatus.CANCELLED)
    journal.release_run(lease)
    resolver = _resolver(world, journal)
    reference = _reference(resolver, run_id)
    tampered = reference.model_copy(
        update={"digest": digest("test-wrong-detail", 1, {"wrong": True})}
    )

    rejected = resolver.read(ACTOR, tampered)

    assert isinstance(rejected, ControlRejected)
    assert rejected.faults[0].code is ControlCode.DETAIL_DIGEST_MISMATCH


def test_detail_ref_refuses_caller_controlled_media_type() -> None:
    with pytest.raises(ValidationError):
        DetailRef(
            uri="constructicon://runs/run-media/manifest",
            media_type="text/html",
            digest=digest("test-detail", 1, {"media": "json"}),
        )


def test_detail_read_never_echoes_unvalidated_media_type(
    world,
    journal: SqliteJournal,
) -> None:
    run_id = _prepare(world, "media-type")
    resolver = _resolver(world, journal)
    reference = resolver.reference(ACTOR, DetailAddress.manifest(run_id))
    assert isinstance(reference, DetailRef)
    tampered = reference.model_copy(update={"media_type": "text/html"})

    chunk = resolver.read(ACTOR, tampered)

    assert not isinstance(chunk, ControlRejected)
    assert chunk.media_type == "application/json"


def test_result_alias_refuses_prepared_and_running_runs(
    world,
    journal: SqliteJournal,
) -> None:
    run_id = _prepare(world, "nonterminal")
    resolver = _resolver(world, journal)

    prepared = resolver.reference(ACTOR, DetailAddress.result(run_id))
    assert isinstance(prepared, ControlRejected)
    assert prepared.faults[0].code is ControlCode.DETAIL_NOT_IMMUTABLE

    lease = journal.claim_run(run_id, owner_id="running-worker", ttl_s=30)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    running = resolver.reference(ACTOR, DetailAddress.result(run_id))
    assert isinstance(running, ControlRejected)
    assert running.faults[0].code is ControlCode.DETAIL_NOT_IMMUTABLE
    journal.release_run(lease)


def test_result_chunks_use_only_bounded_point_reads(
    world,
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = _prepare(world, "bounded")
    lease = journal.claim_run(run_id, owner_id="bounded-worker", ttl_s=30)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    for index in range(1_101):
        journal.append_event(lease, "AttemptNoise", payload={"index": index})
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.FAILED,
        event_kind="RunFailed",
        payload={"attempt": "bounded"},
    )
    journal.release_run(lease)

    def unbounded_events(*args, **kwargs):
        raise AssertionError("result detail must not page through run history")

    exact_reads = 0
    original_event = journal.event

    def counted_event(event_run_id: RunId, seq: int):
        nonlocal exact_reads
        exact_reads += 1
        return original_event(event_run_id, seq)

    monkeypatch.setattr(journal, "events", unbounded_events)
    monkeypatch.setattr(journal, "event", counted_event)
    resolver = _resolver(world, journal)
    reference = _reference(resolver, run_id)

    chunks = 0
    cursor = None
    while True:
        result = resolver.read(ACTOR, reference, cursor=cursor, max_bytes=97)
        assert not isinstance(result, ControlRejected)
        chunks += 1
        cursor = result.next_cursor
        if cursor is None:
            break

    assert exact_reads == chunks + 1  # one mint read, then one exact read per chunk


def test_unicode_detail_chunks_always_advance_at_minimum_budget(
    world,
    journal: SqliteJournal,
) -> None:
    run_id = _prepare(world, "unicode-chunks")
    lease = journal.claim_run(run_id, owner_id="unicode-worker", ttl_s=30)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    event = journal.append_event(
        lease,
        "UnicodeEvidence",
        payload={"text": "before🙂after"},
    )
    journal.release_run(lease)
    resolver = _resolver(world, journal)
    reference = resolver.reference(ACTOR, DetailAddress.event(run_id, event.seq))
    assert isinstance(reference, DetailRef)

    too_small = resolver.read(ACTOR, reference, max_bytes=3)
    assert isinstance(too_small, ControlRejected)
    assert too_small.faults[0].code is ControlCode.REQUEST_INVALID

    cursor = None
    offsets: list[int] = []
    pieces: list[str] = []
    for _ in range(1_000):
        chunk = resolver.read(ACTOR, reference, cursor=cursor, max_bytes=4)
        assert not isinstance(chunk, ControlRejected)
        assert chunk.text
        offsets.append(chunk.offset)
        pieces.append(chunk.text)
        cursor = chunk.next_cursor
        if cursor is None:
            break
    else:  # pragma: no cover - protects this regression test from hanging
        raise AssertionError("detail cursor did not reach EOF")

    assert offsets == sorted(set(offsets))
    assert "🙂" in "".join(pieces)


def test_component_detail_sorts_unordered_metadata(
    world,
    journal: SqliteJournal,
) -> None:
    stable = world._registry.snapshot().stable_version("test/triage")
    assert stable is not None
    source = world._registry.snapshot().get("test/triage", stable)
    assert source is not None
    learning = LearningProfile(
        change_surfaces=frozenset({"prompt", "model_artifact", "code"}),
        experience_policy=Ref(component="policy/experience"),
        evaluator=Ref(component="policy/evaluator"),
        promotion_policy=Ref(component="policy/promotion"),
    )
    definition = source.definition.model_copy(
        update={
            "name": "test/detail-canonical",
            "metadata": ComponentMetadata(
                labels=frozenset({"zeta", "alpha", "middle"}),
                learning=learning,
            ),
        }
    )
    version = world._register(definition, triage_impl)
    resolver = _resolver(world, journal)
    reference = resolver.reference(
        ACTOR,
        DetailAddress.component(definition.name, version),
    )
    assert isinstance(reference, DetailRef)

    payload = json.loads(_read(resolver, reference).text)

    metadata = payload["definition"]["metadata"]
    assert metadata["labels"] == ["alpha", "middle", "zeta"]
    assert metadata["learning"]["change_surfaces"] == [
        "code",
        "model_artifact",
        "prompt",
    ]
