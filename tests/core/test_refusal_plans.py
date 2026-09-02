"""A plan that records a refusal names no domain fact.

Every operation may end in a refusal, and the refusal is planned like any other
outcome so that it becomes terminal and replays byte-for-byte. Two eras write it
two ways — a bare ``rejection`` before the typed envelope, a refusal ``kind``
inside it after — and both mean the same thing to anyone asking which fact the
command wrote: none.

Answering that question with damage is what stranded `runs_approve` commands
that refused after their claim, so the law is stated here at L0, where the
durable vocabulary lives, rather than in whichever projector happens to ask.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from constructicon.api import _control_commands
from constructicon.core.control import (
    APPROVE_SCOPE,
    REFUSAL_PLAN_KINDS,
    AuthenticatedActor,
    CommandRecord,
    ControlCode,
    ControlRejected,
    command_request_hash,
    plan_records_a_refusal,
)
from constructicon.core.human import decoded_human_command_plan
from constructicon.core.identity import Digest, JsonValue, json_value

ACTOR = AuthenticatedActor(
    actor_id="static:refusal",
    auth_method="static",
    scopes=frozenset({APPROVE_SCOPE}),
)

REFUSAL = ControlRejected.one_fault(
    ControlCode.RUN_UNKNOWN,
    "unknown run 'run-absent'",
    "bind the decision to an existing run",
)


def _command(operation: str, plan: JsonValue | None) -> CommandRecord:
    request = {"run_id": "run-absent"}
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return CommandRecord(
        command_id="cmd-refusal",
        actor=ACTOR,
        operation=operation,
        idempotency_key="refusal",
        request_hash=command_request_hash(request),
        request=request,
        state="rejected",
        plan=plan,
        response=json_value(REFUSAL.model_dump(mode="json")),
        owner_id=None,
        owner_epoch=1,
        lease_expires_at=None,
        created_at=now,
        updated_at=now + timedelta(seconds=1),
        completed_at=now + timedelta(seconds=1),
    )


def _enveloped(kind: str) -> JsonValue:
    return {
        "schema_version": 1,
        "plan": {
            "kind": kind,
            "command_id": "cmd-refusal",
            "operation": "runs_approve",
            "request_hash": str(Digest("sha256:" + "c" * 64)),
            "response": json_value(REFUSAL.model_dump(mode="json")),
        },
    }


def _legacy() -> JsonValue:
    return {"rejection": json_value(REFUSAL.model_dump(mode="json"))}


@pytest.mark.parametrize("kind", sorted(REFUSAL_PLAN_KINDS))
def test_every_refusal_kind_is_recognised_in_the_current_envelope(kind: str) -> None:
    assert plan_records_a_refusal(_enveloped(kind))


def test_the_era_before_the_envelope_is_recognised_too() -> None:
    assert plan_records_a_refusal(_legacy())


@pytest.mark.parametrize(
    "plan",
    [
        None,
        "not-an-object",
        {"approval": {}},
        {"schema_version": 1, "plan": {"kind": "channel_approval"}},
        {"schema_version": 1, "plan": "not-an-object"},
    ],
)
def test_a_plan_that_promises_a_mutation_is_not_a_refusal(plan: JsonValue | None) -> None:
    assert not plan_records_a_refusal(plan)


@pytest.mark.parametrize("operation", ["runs_approve", "channels_reply", "channels_ack"])
@pytest.mark.parametrize("plan", [_enveloped("control_reject"), _legacy()])
def test_a_human_command_that_refused_names_no_domain_fact(
    operation: str,
    plan: JsonValue,
) -> None:
    """Not damage: there is simply no fact for the projector to go looking for."""

    assert decoded_human_command_plan(_command(operation, plan)) is None


def test_the_control_plane_writes_only_kinds_this_vocabulary_knows() -> None:
    """The refusal families are named at L0; L4 may not drift away from them.

    A renamed `kind` would compile, store, and read back cleanly — and every
    command that refused after its claim would strand again, silently.
    """

    written = {
        _control_commands._AdmissionRejectPlan.model_fields["kind"].default,
        _control_commands._ControlRejectPlan.model_fields["kind"].default,
    }
    assert written == REFUSAL_PLAN_KINDS
