"""The qualification authorization's shape and predicates (L0, no I/O)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from constructicon.core.address import ExecutionPath, ScopePath
from constructicon.core.control import command_id_for, run_id_for_command
from constructicon.core.identity import digest
from constructicon.core.qualification import QualificationAuthorization

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
GRAPH = digest("test-graph", 1, "qualification")
BINDING = digest("test-binding", 1, "store")
SCOPE = ScopePath(segments=("qualification", "qualify"))


def authorization(**changes) -> QualificationAuthorization:
    fields = {
        "authorization_id": "ci-fixture",
        "stage": "qualification-no-dispatch",
        "actor_id": "operator",
        "idempotency_key": "stage1",
        "scope": SCOPE,
        "binding": "executor",
        "source_graph_hash": GRAPH,
        "capability_id": "codex-operator",
        "revision": "rev-1",
        "operator_binding_digest": BINDING,
        "journal": "/var/lib/constructicon/qualification.sqlite",
        "max_epoch": 1,
        "not_after": NOW + timedelta(hours=2),
    }
    return QualificationAuthorization(**{**fields, **changes})


def acquisition(**changes) -> dict:
    granted = authorization()
    return {
        "run_id": granted.run_id,
        "path": ExecutionPath(scope=SCOPE),
        "binding": "executor",
        "source_graph_hash": GRAPH,
        "capability_id": "codex-operator",
        "revision": "rev-1",
        "operator_binding_digest": BINDING,
        "epoch": 1,
        "now": NOW,
        **changes,
    }


def test_the_run_is_the_one_runs_start_derives_from_actor_and_key():
    command = command_id_for("operator", "runs_start", "stage1")
    assert authorization().run_id == run_id_for_command(command)
    assert authorization(idempotency_key="another").run_id != authorization().run_id


def test_exactly_the_authorized_acquisition_is_admitted():
    assert authorization().acquisition_faults(**acquisition()) == ()


@pytest.mark.parametrize(
    ("change", "fault"),
    [
        ({"run_id": authorization(actor_id="someone").run_id}, "a different run"),
        ({"path": ExecutionPath(scope=SCOPE.child("inner"))}, "a different invocation"),
        ({"binding": "other"}, "a different binding"),
        ({"source_graph_hash": digest("test-graph", 1, "other")}, "a different source graph"),
        ({"source_graph_hash": None}, "a different source graph"),
        ({"capability_id": "another"}, "a different capability"),
        ({"revision": "rev-2"}, "a different adapter revision"),
        ({"operator_binding_digest": GRAPH}, "a different operator binding"),
        ({"epoch": 2}, "an acquisition beyond the authorized epochs"),
        ({"now": NOW + timedelta(hours=2)}, "an expired authorization"),
    ],
)
def test_every_other_acquisition_is_refused_for_its_reason(change, fault):
    assert authorization().acquisition_faults(**acquisition(**change)) == (
        f"qualification refuses {fault}",
    )


def test_max_epoch_permits_exactly_that_many_epochs():
    granted = authorization(max_epoch=2)
    assert granted.acquisition_faults(**acquisition(epoch=2)) == ()
    assert granted.acquisition_faults(**acquisition(epoch=3)) != ()


def test_admission_is_timeless_and_names_graph_capability_and_revision():
    granted = authorization(not_after=NOW - timedelta(days=1))
    assert granted.admits(source_graph_hash=GRAPH, capability_id="codex-operator", revision="rev-1")
    for change in (
        {"source_graph_hash": BINDING},
        {"capability_id": "another"},
        {"revision": "rev-2"},
    ):
        query = {"source_graph_hash": GRAPH, "capability_id": "codex-operator", "revision": "rev-1"}
        assert not granted.admits(**{**query, **change})


@pytest.mark.parametrize(
    "change",
    [
        {"stage": "qualification-dispatch"},
        {"max_epoch": 0},
        {"not_after": datetime(2026, 10, 8, 12)},
        {"unexpected": "field"},
    ],
)
def test_the_shape_is_closed(change):
    with pytest.raises(ValidationError):
        authorization(**change)
