"""The diagnostic's channel stored-reply task is an explicit second case, not a wildcard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.run_worlds import sealed_test_manifest
from tests.substrate.journal.test_maintenance_diagnostic import (
    AUTH,
    CANDIDATE,
    PRIVATE,
    REQUEST,
    RUN,
    _snapshot,
)
from tests.substrate.journal.test_maintenance_diagnostic import (
    windows_birthtime_boundary as windows_birthtime_boundary,
)

from constructicon.core.address import ExecutionPath, GitSha, ScopePath
from constructicon.core.gates import MergeEvaluation
from constructicon.core.identity import digest
from constructicon.core.maintenance import ChannelReplyRequest, ChannelReplyResult
from constructicon.core.manifest import manifest_hash_for
from constructicon.core.workspace import acquisition_id_for, lease_id_for
from constructicon.substrate.journal import maintenance_diagnostic as diagnostic
from constructicon.substrate.journal.sqlite import SqliteJournal

CHANNEL_REQUEST = ChannelReplyRequest(repository=PRIVATE, target_ref="refs/heads/maintenance",
    base_commit=GitSha("a" * 40), target_sha256="b" * 64,
    check_set_hash=digest("maintenance-test-checks", 1, {}))


def _journal(root: Path, graph_name: str, request) -> None:
    root.mkdir()
    journal = SqliteJournal(root / "maintenance.sqlite")
    inputs = {"request": request.model_dump(mode="json")}
    manifest = sealed_test_manifest(inputs)
    graph = manifest.source_graph.model_copy(update={"name": graph_name})
    manifest = manifest.model_copy(update={"source_graph": graph,
        "source_graph_hash": digest("graph", 1, graph.model_dump(mode="json"))})
    manifest = manifest.model_copy(update={"manifest_hash": manifest_hash_for(manifest)})
    journal.create_run(RUN, manifest_json=manifest.model_dump_json(),
        manifest_hash=manifest.manifest_hash, input_hash=manifest.input_hash, inputs=inputs)


def _attempt(root: Path, purpose: str, graph_name: str) -> None:
    writer = ExecutionPath(scope=ScopePath(segments=(graph_name, "writer")))
    (root / "maintenance-attempt.json").write_text(json.dumps({
        "authorization_id": AUTH, "run_id": RUN, "epoch": 1, "purpose": purpose,
        "phase": "acquired", "at": "2026-11-08T00:00:00+00:00",
        "acquisition_id": acquisition_id_for(lease_id_for(RUN, writer, "executor"), 1),
    }), encoding="utf-8")


def _result(root: Path, *, purpose: str | None) -> None:
    result = ChannelReplyResult(run_id=RUN, candidate=CANDIDATE,
        evaluation=MergeEvaluation(subject=None, attestation_id=None, checks=()),
        base_sha256="a" * 64, candidate_sha256="b" * 64)
    record: dict[str, object] = {"schema_version": 1,
        "meaning": "historical-application-acceptance",
        "authorization_digest": "sha256:" + "c" * 64, "result": result.model_dump(mode="json")}
    if purpose is not None:
        record["purpose"] = purpose
    (root / "maintenance-result.json").write_text(json.dumps(record), encoding="utf-8")


def test_channel_journal_attempt_and_result_are_observed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _journal(source, diagnostic.CHANNEL_GRAPH, CHANNEL_REQUEST)
    _attempt(source, "channel-stored-reply", diagnostic.CHANNEL_GRAPH)
    _result(source, purpose="channel-stored-reply")
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "capture"), RUN, AUTH)
    assert report["complete"] is True, report
    assert report["journal"]["observation"] == "selected-facts-validated"
    assert report["attempt"]["observation"] == "identity-matched"
    assert report["result"] == "historical-acceptance-observed"
    assert PRIVATE not in json.dumps(report)


@pytest.mark.parametrize(("graph", "request_model", "stage"), [
    ("constructicon-channel-stored-reply", "plan", "journal"),
    ("constructicon-plan-manifest-maintenance", "channel", "journal"),
    ("constructicon-other-maintenance", "channel", "journal"),
])
def test_a_journal_outside_the_two_cases_is_refused(tmp_path, graph, request_model, stage):
    source = tmp_path / "source"
    _journal(source, graph, REQUEST if request_model == "plan" else CHANNEL_REQUEST)
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "capture"), RUN, AUTH)
    assert report == {"schema_version": 1, "complete": False, "stage": stage,
                      "error": "diagnostic refused or incomplete"}


@pytest.mark.parametrize(("purpose", "graph"), [
    ("plan-manifest-maintenance", "constructicon-channel-stored-reply"),
    ("channel-stored-reply", "constructicon-plan-manifest-maintenance"),
    ("other-task", "constructicon-channel-stored-reply"),
])
def test_an_attempt_purpose_binds_its_own_graph(tmp_path, purpose, graph):
    source = tmp_path / "source"
    source.mkdir()
    _attempt(source, purpose, graph)
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "capture"), RUN, AUTH)
    assert report["complete"] is False and report["stage"] == "attempt"


@pytest.mark.parametrize("sections", [
    ("plan-journal", "channel-attempt"),
    ("plan-attempt", "channel-result"),
    ("plan-journal", "channel-result"),
    ("channel-journal", "plan-attempt"),
])
def test_sections_naming_different_tasks_are_refused_as_one_task(tmp_path, sections):
    # Each section alone is a valid observation; together they name two tasks.
    source = tmp_path / "source"
    source.mkdir()
    for section in sections:
        task, kind = section.split("-")
        graph = diagnostic.CHANNEL_GRAPH if task == "channel" else diagnostic.GRAPH
        purpose = "channel-stored-reply" if task == "channel" else "plan-manifest-maintenance"
        if kind == "journal":
            source.rmdir()
            _journal(source, graph, CHANNEL_REQUEST if task == "channel" else REQUEST)
        elif kind == "attempt":
            _attempt(source, purpose, graph)
        else:
            _result(source, purpose="channel-stored-reply")
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "capture"), RUN, AUTH)
    assert report == {"schema_version": 1, "complete": False, "stage": "task",
                      "error": "diagnostic refused or incomplete"}


@pytest.mark.parametrize("purpose", [None, "plan-manifest-maintenance"])
def test_a_channel_result_never_reads_as_the_plan_result(tmp_path, purpose):
    source = tmp_path / "source"
    source.mkdir()
    _result(source, purpose=purpose)
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "capture"), RUN, AUTH)
    assert report["complete"] is False and report["stage"] == "result"
