"""The batch client uses the public detail page budget without changing bytes."""

from __future__ import annotations

import pytest
from examples import change_review_batch as batch
from examples.change_review import OPERATOR

from constructicon.api.control import ControlPlane
from constructicon.api.detail import MAX_DETAIL_BYTES as MAX_DETAIL_CHUNK_BYTES
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.control import ControlRejected
from constructicon.core.identity import canonical_json, digest
from tests.run_worlds import create_test_run, start_test_run


def test_batch_detail_reader_uses_the_allowed_page_budget_for_complete_utf8_evidence(
    system, journal, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = RunId("run-batch-detail-budget")
    create_test_run(journal, run_id)
    worker = start_test_run(journal, run_id, owner_id="detail-evidence-producer")
    produced = journal.append_event(
        worker, "RetainedReviewEvidence",
        path=ExecutionPath(scope=ScopePath(segments=("review", "evidence"))),
        payload={"evidence": "λ🙂" * 12_000},
    )
    expected = produced.model_dump(mode="json")
    expected_bytes = canonical_json(expected).encode("utf-8")
    assert MAX_DETAIL_CHUNK_BYTES < len(expected_bytes) < 2 * MAX_DETAIL_CHUNK_BYTES
    control = ControlPlane(system=system, store=journal)
    page = control.runs_events(OPERATOR, run_id)
    assert not isinstance(page, ControlRejected)
    row = next(item for item in page.items if item.seq == produced.seq)
    assert row.payload == produced.payload
    reference = row.detail
    assert reference.digest == digest("detail", 1, expected)
    original = control.details_read
    requests = []
    chunks = []

    def observed_read(actor, supplied_reference, *, cursor, max_bytes):
        assert actor == OPERATOR and supplied_reference == reference
        chunk = original(actor, supplied_reference, cursor=cursor, max_bytes=max_bytes)
        assert not isinstance(chunk, ControlRejected)
        requests.append((cursor, max_bytes))
        chunks.append(chunk)
        return chunk

    monkeypatch.setattr(control, "details_read", observed_read)
    reconstructed = batch.read_detail(control, reference)
    assert reconstructed == expected
    assert canonical_json(reconstructed).encode("utf-8") == expected_bytes
    assert digest("detail", 1, reconstructed) == reference.digest
    assert b"".join(chunk.text.encode("utf-8") for chunk in chunks) == expected_bytes
    offset = 0
    cursor = None
    for chunk, (requested_cursor, budget) in zip(chunks, requests, strict=True):
        raw = chunk.text.encode("utf-8")
        assert requested_cursor == cursor
        assert chunk.uri == reference.uri and chunk.digest == reference.digest
        assert chunk.offset == offset and chunk.total_bytes == len(expected_bytes)
        assert raw and len(raw) <= budget <= MAX_DETAIL_CHUNK_BYTES
        offset += len(raw)
        cursor = chunk.next_cursor
    assert offset == len(expected_bytes) and cursor is None
    # The producer made more than one allowed chunk of actual UTF-8 evidence.
    # These work bounds follow successful reconstruction through the real API.
    assert len(chunks) == 2
    assert all(budget == MAX_DETAIL_CHUNK_BYTES for _cursor, budget in requests)
    assert len(chunks[0].text.encode("utf-8")) >= MAX_DETAIL_CHUNK_BYTES - 3
