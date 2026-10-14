"""The maintenance exception is a closed exact-attempt authority, not N5."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from constructicon.core.address import ExecutionPath, ScopePath
from constructicon.core.control import command_id_for, run_id_for_command
from constructicon.core.grants import EffectiveGrants, Posture
from constructicon.core.identity import digest
from constructicon.core.maintenance import MaintenanceAttemptAuthorization, PlanManifestRequest
from constructicon.core.qualification import QualificationAuthorization

NOW = datetime(2026, 10, 14, tzinfo=UTC)
GRAPH = digest("test-maintenance", 1, "graph")
SCOPE = ScopePath(segments=("plan-manifest-maintenance", "writer"))
GRANTS = EffectiveGrants(
    posture=Posture.WRITE, model_selection={"kind": "explicit", "model": "gpt-5.6-sol"},
    effort="low", allowed_tools=("contained_python",), env_allowlist=(),
    network="allow", timeout_s=300,
)


def authorization(**changes):
    fields = {
        "authorization_id": "maintenance-one", "actor_id": "operator:maintenance",
        "idempotency_key": "one", "scope": SCOPE, "binding": "executor",
        "source_graph_hash": GRAPH, "capability_id": "maintenance-executor",
        "revision": str(digest("test-maintenance", 1, "executor")),
        "operator_binding_digest": digest("test-maintenance", 1, "binding"),
        "journal": "/var/lib/constructicon/maintenance.sqlite", "max_epoch": 1,
        "not_after": NOW + timedelta(hours=1), "grants": GRANTS,
        "attempt_record": "/var/lib/constructicon/maintenance.attempt",
        "request": PlanManifestRequest(
            repository="maintenance", target_ref="refs/heads/maintenance",
            base_commit="a" * 40, target_sha256="b" * 64,
            check_set_hash=digest("test-maintenance", 1, "checks"),
        ),
        "application_revision": digest("test-maintenance", 1, "application"),
        "workspace": {"capability_id": "workspace", "revision": GRAPH},
        "gate": {"capability_id": "gate", "revision": GRAPH},
    }
    return MaintenanceAttemptAuthorization(**{**fields, **changes})


def acquisition(**changes):
    granted = authorization()
    return {
        "run_id": granted.run_id, "path": ExecutionPath(scope=SCOPE), "binding": "executor",
        "source_graph_hash": GRAPH, "capability_id": granted.capability_id,
        "revision": granted.revision, "operator_binding_digest": granted.operator_binding_digest,
        "grants": GRANTS, "epoch": 1, "now": NOW, **changes,
    }


def test_exact_authority_accepts_and_roundtrips_without_n5_fields():
    granted = authorization()
    assert granted.run_id == run_id_for_command(
        command_id_for("operator:maintenance", "runs_start", "one"),
    )
    assert granted.acquisition_faults(**acquisition()) == ()
    assert MaintenanceAttemptAuthorization.model_validate_json(granted.model_dump_json()) == granted
    assert granted.purpose == "plan-manifest-maintenance"
    assert "stage" not in granted.model_dump()
    with pytest.raises(ValidationError):
        QualificationAuthorization.model_validate_json(granted.model_dump_json())


@pytest.mark.parametrize("change,fault", [
    ({"run_id": authorization(idempotency_key="other").run_id}, "a different run"),
    ({"path": ExecutionPath(scope=SCOPE.child("inner"))}, "a different invocation"),
    ({"binding": "other"}, "a different binding"),
    ({"source_graph_hash": None}, "a different source graph"),
    ({"source_graph_hash": digest("other", 1, "graph")}, "a different source graph"),
    ({"capability_id": "other"}, "a different capability"),
    ({"revision": "other"}, "a different adapter revision"),
    ({"operator_binding_digest": GRAPH}, "a different operator binding"),
    ({"grants": GRANTS.model_copy(update={"timeout_s": 299})}, "other grants"),
    ({"epoch": 0}, "an acquisition outside the authorized epoch"),
    ({"epoch": 2}, "an acquisition outside the authorized epoch"),
    ({"epoch": True}, "an acquisition outside the authorized epoch"),
    ({"now": NOW + timedelta(hours=1)}, "an expired authorization"),
])
def test_every_other_acquisition_refuses(change, fault):
    assert authorization().acquisition_faults(**acquisition(**change)) == (
        f"maintenance refuses {fault}",
    )


def test_admission_is_exact_and_timeless():
    granted = authorization(not_after=NOW)
    query = {"source_graph_hash": GRAPH, "capability_id": granted.capability_id,
             "revision": granted.revision}
    assert granted.admits(**query)
    for change in ({"source_graph_hash": digest("other", 1, "graph")},
                   {"capability_id": "other"}, {"revision": "other"}):
        assert not granted.admits(**{**query, **change})


@pytest.mark.parametrize("change", [
    {"purpose": "qualification-write"}, {"stage": "qualification-write"},
    {"max_epoch": 2}, {"max_epoch": True}, {"max_epoch": 1.0}, {"max_epoch": "1"},
    {"grants": None}, {"attempt_record": ""}, {"journal": ""},
    {"application_revision": "unsealed"}, {"request": None},
    {"workspace": {"capability_id": "workspace", "revision": GRAPH, "extra": 1}},
    {"not_after": datetime(2026, 10, 14)}, {"authorization_id": "x" * 257},
    {"idempotency_key": "x" * 201}, {"revision": "unsealed"},
])
def test_shape_refuses_missing_weak_or_foreign_authority(change):
    with pytest.raises(ValidationError):
        authorization(**change)


@pytest.mark.parametrize("change", [
    {"posture": Posture.READ}, {"allowed_tools": ()}, {"env_allowlist": ("SECRET",)},
    {"network": "deny"}, {"timeout_s": 600}, {"effort": None},
    {"model_selection": {"kind": "explicit", "model": ""}},
])
def test_grants_keep_the_bounded_write_shape(change):
    with pytest.raises(ValidationError):
        authorization(grants=EffectiveGrants.model_validate({**GRANTS.model_dump(), **change}))
