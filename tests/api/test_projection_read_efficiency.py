"""Public references reuse validated facts without weakening fresh reads."""

from __future__ import annotations

import sqlite3

import pytest

from constructicon.api.control import ControlPlane
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.control import ControlCode, ControlRejected, DetailRef
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import canonical_json, digest
from tests.api.test_channel_reads import ALICE, BOB, CHANNEL_ID, _intent
from tests.channel_commands import reply_with_command
from tests.channel_requests import AttestedMailboxChannel
from tests.run_worlds import create_test_run, start_test_run

RUN = RunId("run-public-projection-efficiency")
PATH = ExecutionPath(scope=ScopePath(segments=("review", "inspect")))


@pytest.fixture
def event_world(system, journal):
    create_test_run(journal, RUN)
    lease = start_test_run(journal, RUN, owner_id="projection-producer")
    evidence = journal.append_event(
        lease, "ReviewEvidence", path=PATH, payload={"value": "original", "text": "λ🙂"},
    )
    journal.append_event(lease, "ReviewProgress", path=PATH, payload={"count": 2})
    events = journal.events(RUN)
    assert len(events) == 3 and evidence in events
    return ControlPlane(system=system, store=journal), lease, events


@pytest.fixture
def channel_world(system, journal):
    channel = AttestedMailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(port="projection-question"), "projection-send")
    reply = reply_with_command(
        channel, request_id=request.message_id, actor_id=ALICE.actor_id,
        payload={"verdict": "retain λ🙂"}, idempotency_key="projection-reply",
    )
    return ControlPlane(system=system, store=journal), request, reply


def read_exact_detail(control: ControlPlane, reference: DetailRef, expected: dict) -> None:
    """Compare the entire chunked document with its producer, including UTF-8."""
    expected_text = canonical_json(expected)
    assert reference.digest == digest("detail", 1, expected)
    cursor = None
    pieces = []
    consumed = 0
    for _ in range(1_000):
        chunk = control.details_read(ALICE, reference, cursor=cursor, max_bytes=97)
        assert not isinstance(chunk, ControlRejected)
        raw = chunk.text.encode("utf-8")
        assert chunk.text and len(raw) <= 97
        assert chunk.offset == consumed
        assert chunk.total_bytes == len(expected_text.encode("utf-8"))
        assert chunk.digest == reference.digest and chunk.uri == reference.uri
        pieces.append(chunk.text)
        consumed += len(raw)
        cursor = chunk.next_cursor
        if cursor is None:
            break
    else:
        raise AssertionError("detail cursor never reached its declared EOF")
    assert "".join(pieces) == expected_text
    assert consumed == len(expected_text.encode("utf-8"))


def test_event_references_keep_complete_producer_bytes_and_the_original_cursor_cut(
    event_world, journal,
) -> None:
    control, lease, events = event_world
    first = control.runs_events(ALICE, RUN, limit=2)
    assert not isinstance(first, ControlRejected)
    assert first.page.next_cursor is not None
    assert [event.seq for event in first.items] == [event.seq for event in events[:2]]
    assert first.through_seq == events[-1].seq
    late = journal.append_event(lease, "CommittedAfterPage", path=PATH, payload={"late": True})

    second = control.runs_events(ALICE, RUN, limit=2, cursor=first.page.next_cursor)
    assert not isinstance(second, ControlRejected)
    assert second.through_seq == first.through_seq
    assert second.page.snapshot_digest == first.page.snapshot_digest
    assert second.page.next_cursor is None
    rows = (*first.items, *second.items)
    assert [row.seq for row in rows] == [event.seq for event in events]
    assert late.seq not in [row.seq for row in rows]
    for row, produced in zip(rows, events, strict=True):
        assert row.payload == produced.payload
        assert row.path == (produced.path.render() if produced.path else None)
        assert row.created_at == produced.created_at and row.kind == produced.kind
        read_exact_detail(control, row.detail, produced.model_dump(mode="json"))

    stolen = control.runs_events(BOB, RUN, limit=2, cursor=first.page.next_cursor)
    assert isinstance(stolen, ControlRejected)
    assert stolen.faults[0].code is ControlCode.CURSOR_QUERY_MISMATCH
    fresh = control.runs_events(ALICE, RUN, limit=10)
    assert not isinstance(fresh, ControlRejected)
    assert [row.seq for row in fresh.items] == [event.seq for event in events] + [late.seq]


def test_event_page_does_not_point_read_its_already_validated_event_rows(
    event_world, journal, monkeypatch: pytest.MonkeyPatch,
) -> None:
    control, _lease, events = event_world
    point_reads = []
    original = journal.event

    def counted(run_id, seq):
        point_reads.append((run_id, seq))
        return original(run_id, seq)

    monkeypatch.setattr(journal, "event", counted)
    page = control.runs_events(ALICE, RUN, limit=2)
    assert not isinstance(page, ControlRejected)
    assert len(page.items) == 2 and page.page.next_cursor is not None
    reads_for_page = tuple(point_reads)
    for row, produced in zip(page.items, events[:2], strict=True):
        assert row.payload == produced.payload
        read_exact_detail(control, row.detail, produced.model_dump(mode="json"))
    # Detail reads above intentionally revalidate. Only creation of references
    # from the already validated page should add no exact event rereads.
    assert reads_for_page == ()


@pytest.mark.parametrize("kind,bound", [("request", 1), ("reply", 2)])
def test_addressed_channel_reference_reads_only_the_message_and_its_governing_request(
    channel_world, journal, monkeypatch: pytest.MonkeyPatch, kind: str, bound: int,
) -> None:
    control, request, reply = channel_world
    message = request if kind == "request" else reply
    point_reads = []
    original = journal.channel_delivery

    def counted(*, message_id, actor_id):
        point_reads.append((message_id, actor_id))
        return original(message_id=message_id, actor_id=actor_id)

    monkeypatch.setattr(journal, "channel_delivery", counted)
    summary = control.channels_message(ALICE, message.message_id)
    assert not isinstance(summary, ControlRejected)
    assert summary.message_id == message.message_id and summary.kind == kind
    assert summary.run_id == message.envelope.run_id
    reads_for_summary = tuple(point_reads)
    read_exact_detail(control, summary.detail, message.model_dump(mode="json"))
    stranger = control.details_read(BOB, summary.detail)
    assert isinstance(stranger, ControlRejected)
    assert stranger.faults[0].code is ControlCode.AUTH_REQUIRED_SCOPE
    expected_ids = {request.message_id} if kind == "request" else {
        request.message_id, reply.message_id,
    }
    assert {message_id for message_id, _actor in reads_for_summary} == expected_ids
    assert {actor for _message_id, actor in reads_for_summary} == {ALICE.actor_id}
    assert len(reads_for_summary) <= bound


def test_a_warm_event_projection_cannot_hide_a_validly_rewritten_durable_fact(
    event_world, journal,
) -> None:
    control, _lease, events = event_world
    target = events[1]
    warm = control.runs_events(ALICE, RUN)
    assert not isinstance(warm, ControlRejected)
    reference = next(row.detail for row in warm.items if row.seq == target.seq)
    read_exact_detail(control, reference, target.model_dump(mode="json"))
    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "UPDATE events SET payload = ? WHERE run_id = ? AND seq = ?",
            (canonical_json({"value": "rewritten", "text": "λ🙂"}), str(RUN), target.seq),
        )

    with pytest.raises(JournalDamaged, match="positive seal"):
        control.runs_events(ALICE, RUN)
    with pytest.raises(JournalDamaged, match="positive seal"):
        control.details_read(ALICE, reference)


def test_a_warm_reply_reference_cannot_hide_its_deleted_atomic_acknowledgement(
    channel_world, journal,
) -> None:
    control, request, reply = channel_world
    warm = control.channels_message(ALICE, reply.message_id)
    assert not isinstance(warm, ControlRejected)
    read_exact_detail(control, warm.detail, reply.model_dump(mode="json"))
    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "DELETE FROM channel_acks WHERE message_id = ? AND actor_id = ?",
            (str(request.message_id), ALICE.actor_id),
        )

    for read in (
        lambda: control.channels_message(ALICE, reply.message_id),
        lambda: control.details_read(ALICE, warm.detail),
    ):
        with pytest.raises(JournalDamaged, match=r"acknowledgement|append-only history"):
            read()
