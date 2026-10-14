"""Result v2 makes proven capability accounting visible on ordinary reads."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.control import (
    READ_SCOPE,
    AuthenticatedActor,
    ControlCode,
    ControlRejected,
    RunResultPreview,
    RunResultPreviewV2,
    parse_run_result_preview,
)
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import RunStatus
from constructicon.core.workspace import lease_id_for
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.migrations.test_sqlite_v7_to_v8 import historical_database
from tests.run_worlds import create_test_run, start_test_run
from tests.substrate.journal.test_capability_accounting_snapshot import acquire

READER = AuthenticatedActor(
    actor_id="static:accounting-reader", auth_method="static", scopes=frozenset({READ_SCOPE})
)
RUN = RunId("run-accounting-result")


def test_running_result_returns_versioned_accounting_and_chunked_detail(world, journal) -> None:
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="result-worker")
    path = ExecutionPath(scope=ScopePath(segments=("leased",)))
    lease = CapabilityLease(
        lease_id=lease_id_for(RUN, path, "workspace"),
        acquisition_epoch=worker.epoch,
        run_id=RUN,
        binding_id="workspace",
        path=path,
        state="active",
    )
    journal.record_capability_lease(worker, lease)
    control = ControlPlane(system=world, store=journal)
    result = control.runs_result(READER, RUN)
    assert not isinstance(result, ControlRejected)
    assert hasattr(result, "result_schema_version")
    assert result.result_schema_version == 2
    accounting = result.capability_accounting
    assert accounting.active_count == 1
    assert accounting.disposed_count == accounting.opaque_lost_count == accounting.lost_count == 0
    assert accounting.through_event_seq == 2
    assert result.detail is None
    assert result.failures_partial is False
    with pytest.raises(ValidationError):
        RunResultPreview.model_validate_json(result.model_dump_json())
    chunk = control.details_read(READER, accounting.detail, max_bytes=64_000)
    assert not isinstance(chunk, ControlRejected)
    payload = json.loads(chunk.text)
    assert payload["through_event_seq"] == 2
    assert payload["items"][0]["lease_id"] == lease.lease_id
    assert isinstance(parse_run_result_preview(result.model_dump_json()), RunResultPreviewV2)


@pytest.mark.parametrize("count,partial", ((20, False), (21, True)))
def test_result_failure_item_partiality_binds_at_twenty(world, journal, count, partial):
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="result-worker")
    for index in range(count):
        path = ExecutionPath(scope=ScopePath(segments=(f"failure-{index:02}",)))
        journal.append_event(worker, "NodeFailed", path=path, payload={"error": f"error-{index}"})
    result = ControlPlane(system=world, store=journal).runs_result(READER, RUN)
    assert isinstance(result, RunResultPreviewV2)
    assert len(result.failures) == 20
    assert result.failures_partial is partial
    assert list(result.failures) == sorted(result.failures)


@pytest.mark.parametrize("total,partial", ((1_000, False), (1_001, True)))
def test_result_failure_scan_partiality_has_affirmative_extra_event(world, journal, total, partial):
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="result-worker")
    for _ in range(total - 2):
        journal.append_event(worker, "FixtureProgress")
    path = ExecutionPath(scope=ScopePath(segments=("last-failure",)))
    journal.append_event(worker, "NodeFailed", path=path, payload={"error": "bound-binds"})
    result = ControlPlane(system=world, store=journal).runs_result(READER, RUN)
    assert isinstance(result, RunResultPreviewV2)
    assert result.failures_partial is partial
    assert result.failures == ({} if partial else {path.render(): "bound-binds"})


def test_accounting_chunks_keep_old_cut_after_close_resume_and_reopen(world, journal):
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="result-worker")
    lease = acquire(journal, worker, "unicode-é界")
    control = ControlPlane(system=world, store=journal)
    result = control.runs_result(READER, RUN)
    assert isinstance(result, RunResultPreviewV2)
    reference = result.capability_accounting.detail
    first = control.details_read(READER, reference, max_bytes=7)
    assert not isinstance(first, ControlRejected) and first.next_cursor is not None
    journal.transition_capability_lease(
        worker,
        lease_id=lease.lease_id,
        acquisition_epoch=lease.acquisition_epoch,
        expected=frozenset({"active"}),
        target="closed",
        disposition="released",
    )
    journal.transition_run(
        worker,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.FAILED,
        event_kind="RunFailed",
    )
    journal.release_run(worker)
    resumed = journal.claim_run(RUN, owner_id="resumed-worker", ttl_s=30)
    journal.transition_run(
        resumed,
        expected=frozenset({RunStatus.FAILED}),
        target=RunStatus.RUNNING,
        event_kind="RunResumed",
    )
    acquire(journal, resumed, "later")
    # Reopen proves the same cut without a process-local accounting cache.
    reopened = SqliteJournal(journal._db_path)
    control = ControlPlane(system=Constructicon(journal=reopened), store=reopened)
    current = control.runs_result(READER, RUN)
    assert isinstance(current, RunResultPreviewV2)
    assert current.capability_accounting.detail != reference
    text = first.text
    cursor = first.next_cursor
    while cursor is not None:
        chunk = control.details_read(READER, reference, cursor=cursor, max_bytes=7)
        assert not isinstance(chunk, ControlRejected)
        assert len(chunk.text.encode("utf-8")) <= 7
        assert chunk.digest == reference.digest
        text += chunk.text
        cursor = chunk.next_cursor
    payload = json.loads(text)
    assert payload["through_event_seq"] == 2
    assert len(payload["items"]) == 1 and payload["items"][0]["state"] == "active"
    assert set(payload) == {"run_id", "through_event_seq", "items"}
    assert set(payload["items"][0]) == {
        "lease_id",
        "acquisition_epoch",
        "binding_id",
        "path",
        "state",
        "disposition",
        "acquisition_event_seq",
        "loss",
        "physical_cleanup",
        "disposal_receipt",
    }


def test_accounting_family_authorizes_before_lookup(world, journal, monkeypatch):
    no_read = AuthenticatedActor(actor_id="static:denied", auth_method="static", scopes=frozenset())
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("unauthorized accounting lookup")

    control = ControlPlane(system=world, store=journal)
    monkeypatch.setattr(journal, "capability_accounting_snapshot", forbidden)
    result = control.runs_result(no_read, RUN)
    detail = control.resource_read(no_read, f"constructicon://runs/{RUN}/accounting/0")
    assert isinstance(result, ControlRejected) and isinstance(detail, ControlRejected)
    assert result.faults[0].code is detail.faults[0].code is ControlCode.AUTH_REQUIRED_SCOPE
    assert calls == []


def test_result_summary_and_detail_are_complete_beyond_a_hundred(world, journal):
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="result-worker")
    for index in range(101):
        acquire(journal, worker, index)
    control = ControlPlane(system=world, store=journal)
    result = control.runs_result(READER, RUN)
    assert isinstance(result, RunResultPreviewV2)
    assert result.capability_accounting.active_count == 101
    assert result.capability_accounting.lost_count == 0
    chunk = control.details_read(READER, result.capability_accounting.detail, max_bytes=64_000)
    assert not isinstance(chunk, ControlRejected) and chunk.next_cursor is None
    assert len(json.loads(chunk.text)["items"]) == 101


def test_result_reports_opaque_historical_loss_without_inventing_disposal(tmp_path):
    database = tmp_path / "opaque-result.db"
    historical_database(database, "schema6-initial-lifecycle.sql")
    journal = SqliteJournal(database)
    control = ControlPlane(system=Constructicon(journal=journal), store=journal)
    run = RunId("run-historical-capabilities")
    result = control.runs_result(READER, run)
    assert isinstance(result, RunResultPreviewV2)
    summary = result.capability_accounting
    assert summary.active_count == 1
    assert summary.opaque_lost_count == summary.lost_count == 1
    assert summary.disposed_count == 0
    chunk = control.details_read(READER, summary.detail, max_bytes=64_000)
    assert not isinstance(chunk, ControlRejected)
    lost = next(item for item in json.loads(chunk.text)["items"] if item["state"] == "lost")
    assert lost["loss"] == "opaque_lost" and lost["physical_cleanup"] == "unknown"
    assert lost["disposal_receipt"] is None and lost["acquisition_event_seq"] is None
