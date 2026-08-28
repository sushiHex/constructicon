"""M6 pages are stable, actor-bound snapshots with exact detail recovery."""

from __future__ import annotations

import json

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.core.address import RunId
from constructicon.core.control import (
    READ_SCOPE,
    AuthenticatedActor,
    ControlCode,
    ControlRejected,
)
from constructicon.core.identity import canonical_json, digest
from constructicon.core.run import RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import pipeline_graph

ALICE = AuthenticatedActor(
    actor_id="static:alice",
    auth_method="static",
    scopes=frozenset({READ_SCOPE}),
)
BOB = AuthenticatedActor(
    actor_id="static:bob",
    auth_method="static",
    scopes=frozenset({READ_SCOPE}),
)


def _prepare(world, suffix: str) -> RunId:
    inputs = {"issue": {"title": suffix}}
    manifest = world.validate(pipeline_graph(), inputs)
    run_id = RunId(f"run-{suffix}")
    world.prepare(manifest, run_id=run_id, inputs=inputs)
    return run_id


def test_run_cursor_excludes_later_rows_and_is_actor_bound(
    world,
    journal: SqliteJournal,
) -> None:
    _prepare(world, "a")
    _prepare(world, "b")
    control = ControlPlane(system=world, store=journal, run_host=RunHost(world))
    first = control.runs_list(ALICE, limit=1)
    assert not isinstance(first, ControlRejected)
    assert [str(item.run_id) for item in first.items] == ["run-a"]
    assert first.page.next_cursor is not None

    _prepare(world, "z")  # after the first page's captured upper bound
    second = control.runs_list(ALICE, limit=1, cursor=first.page.next_cursor)
    assert not isinstance(second, ControlRejected)
    assert [str(item.run_id) for item in second.items] == ["run-b"]
    assert second.page.next_cursor is None

    wrong_actor = control.runs_list(BOB, limit=1, cursor=first.page.next_cursor)
    assert isinstance(wrong_actor, ControlRejected)
    assert wrong_actor.faults[0].code is ControlCode.CURSOR_QUERY_MISMATCH


def test_event_cursor_is_snapshot_stable(world, journal: SqliteJournal) -> None:
    run_id = _prepare(world, "events")
    lease = journal.claim_run(run_id, owner_id="events-writer", ttl_s=30)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    journal.append_event(lease, "One")
    journal.append_event(lease, "Two")
    control = ControlPlane(system=world, store=journal)
    first = control.runs_events(ALICE, run_id, limit=1)
    assert not isinstance(first, ControlRejected)
    assert [event.kind for event in first.items] == ["RunStarted"]
    assert first.page.next_cursor is not None
    through = first.through_seq

    journal.append_event(lease, "ThreeAfterSnapshot")
    second = control.runs_events(
        ALICE, run_id, limit=10, cursor=first.page.next_cursor
    )
    assert not isinstance(second, ControlRejected)
    assert second.through_seq == through
    assert "ThreeAfterSnapshot" not in [event.kind for event in second.items]

    fresh = control.runs_events(ALICE, run_id, limit=10)
    assert not isinstance(fresh, ControlRejected)
    assert "ThreeAfterSnapshot" in [event.kind for event in fresh.items]


def test_detail_chunks_reconstruct_canonical_bytes(world, journal: SqliteJournal) -> None:
    run_id = _prepare(world, "detail")
    control = ControlPlane(system=world, store=journal)
    uri = f"constructicon://runs/{run_id}/manifest"
    reference = control.details.reference(ALICE, uri)
    assert not isinstance(reference, ControlRejected)
    pieces: list[str] = []
    cursor: str | None = None
    digest_text = None
    while True:
        chunk = control.details_read(ALICE, reference, cursor=cursor, max_bytes=97)
        assert not isinstance(chunk, ControlRejected)
        pieces.append(chunk.text)
        digest_text = str(chunk.digest)
        cursor = chunk.next_cursor
        if cursor is None:
            break
    full = "".join(pieces)
    manifest = world.manifest_for_run(run_id)
    assert full == canonical_json(manifest.model_dump(mode="json"))
    canonical = canonical_json(json.loads(full))
    assert digest_text == str(digest("detail", 1, json.loads(canonical)))
