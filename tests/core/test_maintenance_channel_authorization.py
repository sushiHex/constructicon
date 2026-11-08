"""The second closed task leaves the plan-manifest wire unchanged and stays disjoint."""

from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from constructicon.core.identity import canonical_json, digest
from constructicon.core.maintenance import (
    MAINTENANCE_AUTHORIZATIONS,
    ChannelReplyAttemptAuthorization,
    ChannelReplyRequest,
    MaintenanceAttemptAuthorization,
    PlanManifestRequest,
)
from tests.core.test_maintenance_authorization import (
    GRANTS,
    NOW,
    acquisition,
    authorization,
)

# Captured at b0d2c0b's source (this branch's base, before any code change) by
# validating this exact wire with the unmodified model. Never regenerated.
GOLDEN_WIRE = (
    '{"actor_id":"operator:golden","application_revision":"sha256:8c6ecaaebb1951d26c418109d0'
    '91cc83da18daefd97e69ef2f470a98a3665e19","attempt_record":"/var/lib/constructicon/mainten'
    'ance/maintenance-attempt.json","authorization_id":"golden-plan-manifest","binding":"exec'
    'utor","capability_id":"codex-operator","gate":{"capability_id":"maintenance-gate","revis'
    'ion":"sha256:f510d7bd97131a803ed900fbbba485ca773b906fd2c278af3c8131a55fc28db5"},"grants"'
    ':{"allowed_tools":["contained_python"],"effort":"low","env_allowlist":[],"model_selectio'
    'n":{"kind":"explicit","model":"gpt-golden"},"network":"allow","posture":"write","timeout'
    '_s":300},"idempotency_key":"golden","journal":"/var/lib/constructicon/maintenance/mainte'
    'nance.sqlite","max_epoch":1,"not_after":"2026-11-01T00:00:00+00:00","operator_binding_di'
    'gest":"sha256:a1a15f882849c4258860be23e20729f898b898348dcb451379d2d3736c30ad7f","purpose'
    '":"plan-manifest-maintenance","request":{"base_commit":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    'aaaaaaaa","check_set_hash":"sha256:967f39e485c6ae95a7c8f43b60fcc8beaf9b2bf1ea0807475f759'
    'c6f3f5d23f0","repository":"/var/lib/constructicon/maintenance/authority.git","schema_ver'
    'sion":1,"target_ref":"refs/heads/maintenance","target_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbb'
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","vector_path":"tests/vectors/plan_manifest.json'
    '"},"revision":"sha256:f83d027889bdca9c660228e1333a98dbe9be0008b8fc42e4ad5aad19a54fa833",'
    '"scope":{"segments":["constructicon-plan-manifest-maintenance","writer"]},"source_graph_'
    'hash":"sha256:5649fd7dd51f3a6957ec4b67514a3e1b7c74397ad79f81ac9faf91c36f681ed0","workspa'
    'ce":{"capability_id":"maintenance-workspace","revision":"sha256:897bf2f79ba6cdf87ce9ccfa'
    '153ffc34c9a0251315294f01144e362e83cbb07e"}}'
)
GOLDEN_FIELDS = [
    "purpose", "authorization_id", "actor_id", "idempotency_key", "scope", "binding",
    "source_graph_hash", "capability_id", "revision", "operator_binding_digest", "journal",
    "max_epoch", "not_after", "grants", "attempt_record", "request", "application_revision",
    "workspace", "gate",
]
GOLDEN_CANONICAL_SHA256 = "230f69a950ef87d1d16e97be507559ec97d4b898022ade772bb758ab86e0db93"
GOLDEN_DIGEST = "sha256:e39f208d38e116b5412f91e3255e5b8d4174b8b0c2d80c7c74ed2f6977781427"
GOLDEN_SCHEMA_SHA256 = "79099579f878b9a8c821fc4c03b3c08e4b17ad1c80d8e5d53cca96307a39aa4d"
GOLDEN_RUN_ID = "run-c9c3ac627c1f629db4899178f0663f34"


def channel_request(**changes):
    return ChannelReplyRequest(**{
        "repository": "maintenance", "target_ref": "refs/heads/maintenance",
        "base_commit": "a" * 40, "target_sha256": "b" * 64,
        "check_set_hash": digest("test-maintenance", 1, "checks"), **changes,
    })


def channel_authorization(**changes):
    fields = authorization().model_dump()
    fields.pop("purpose")
    fields["request"] = channel_request()
    return ChannelReplyAttemptAuthorization(**{**fields, **changes})


def test_old_plan_manifest_wire_parses_to_the_same_model_and_digest():
    model = MaintenanceAttemptAuthorization.model_validate_json(GOLDEN_WIRE)
    assert type(model) is MaintenanceAttemptAuthorization
    assert list(MaintenanceAttemptAuthorization.model_fields) == GOLDEN_FIELDS
    assert json.dumps(model.model_dump(mode="json"), sort_keys=True,
                      separators=(",", ":")) == GOLDEN_WIRE.replace(
        "2026-11-01T00:00:00+00:00", "2026-11-01T00:00:00Z")
    assert hashlib.sha256(canonical_json(model).encode()).hexdigest() == GOLDEN_CANONICAL_SHA256
    assert str(digest("maintenance-authorization", 1, model.model_dump(mode="json"))) \
        == GOLDEN_DIGEST
    assert hashlib.sha256(json.dumps(MaintenanceAttemptAuthorization.model_json_schema(),
        sort_keys=True).encode()).hexdigest() == GOLDEN_SCHEMA_SHA256
    assert str(model.run_id) == GOLDEN_RUN_ID
    assert type(model.request) is PlanManifestRequest


def test_channel_authority_keeps_the_same_exact_attempt_law():
    granted = channel_authorization()
    assert granted.purpose == "channel-stored-reply"
    assert ChannelReplyAttemptAuthorization.model_validate_json(granted.model_dump_json()) \
        == granted
    assert granted.acquisition_faults(**acquisition()) == ()
    assert granted.acquisition_faults(**acquisition(epoch=2)) == (
        "maintenance refuses an acquisition outside the authorized epoch",)
    with pytest.raises(ValidationError):
        channel_authorization(grants=GRANTS.model_copy(update={"timeout_s": 600}))
    with pytest.raises(ValidationError):
        channel_authorization(max_epoch=2)
    expected = (MaintenanceAttemptAuthorization, ChannelReplyAttemptAuthorization)
    assert expected == MAINTENANCE_AUTHORIZATIONS


def test_neither_task_parses_as_the_other():
    plan, channel = authorization(), channel_authorization()
    with pytest.raises(ValidationError):
        ChannelReplyAttemptAuthorization.model_validate_json(plan.model_dump_json())
    with pytest.raises(ValidationError):
        MaintenanceAttemptAuthorization.model_validate_json(channel.model_dump_json())
    swapped = json.loads(channel.model_dump_json())
    swapped["purpose"] = "plan-manifest-maintenance"
    with pytest.raises(ValidationError):
        MaintenanceAttemptAuthorization.model_validate(swapped)
    with pytest.raises(ValidationError):
        PlanManifestRequest.model_validate(channel.request.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        ChannelReplyRequest.model_validate(plan.request.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        channel_request(target_path="scripts/regen_plan_manifest.py")
    assert not isinstance(channel, MaintenanceAttemptAuthorization)
    assert not isinstance(plan, ChannelReplyAttemptAuthorization)
    assert channel.not_after > NOW
