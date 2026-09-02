"""Which stored domain plans predate the exact proofs they now answer to.

Classified from bytes alone, so the substrate and the control plane agree on
the era of a plan without either importing the other's models — the same
arrangement the resume family already uses, and for the same reason: the
classifier is the one thing both sides must share.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from constructicon.core.control import (
    OPERATE_SCOPE,
    AuthenticatedActor,
    CommandRecord,
    command_request_hash,
    domain_plan_requires_historical_evidence,
    validated_new_domain_command_plan,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import JsonValue

ACTOR = AuthenticatedActor(
    actor_id="static:domain-era",
    auth_method="static",
    scopes=frozenset({OPERATE_SCOPE}),
)


def _command(operation: str, plan: JsonValue | None) -> CommandRecord:
    request = {"probe": operation}
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return CommandRecord(
        command_id="cmd-domain-era",
        actor=ACTOR,
        operation=operation,
        idempotency_key="domain-era",
        request_hash=command_request_hash(request),
        request=request,
        state="prepared",
        plan=plan,
        response=None,
        owner_id="test:domain-era",
        owner_epoch=1,
        lease_expires_at=now + timedelta(seconds=30),
        created_at=now,
        updated_at=now,
        completed_at=None,
    )


def _enveloped(inner: dict[str, JsonValue]) -> JsonValue:
    return {"schema_version": 1, "plan": inner}


def _promotion(kind: str, *, exact: bool) -> JsonValue:
    inner: dict[str, JsonValue] = {
        "kind": kind,
        "component": "test/component",
        "baseline": None,
        "target": "sha256:" + "a" * 64,
        "attestation_id": "att-domain-era",
    }
    if exact:
        inner["terminal_rejection_policy"] = "exact-v1"
    return _enveloped(inner)


def _cancel(outcome: str, *, observed: bool) -> JsonValue:
    inner: dict[str, JsonValue] = {
        "kind": "cancel",
        "run_id": "run-domain-era",
        "observed_status": "failed",
        "outcome": outcome,
        "response_status": "failed",
    }
    if observed:
        inner["observed_event_seq"] = 1
    return _enveloped(inner)


@pytest.mark.parametrize(
    ("operation", "kind"),
    [
        ("registry_promote_initial", "initial_promotion"),
        ("registry_promote", "promotion"),
        ("registry_rollback", "rollback"),
    ],
)
def test_a_promotion_plan_without_its_exact_proof_is_historical(
    operation: str,
    kind: str,
) -> None:
    assert domain_plan_requires_historical_evidence(
        _command(operation, _promotion(kind, exact=False))
    )
    assert not domain_plan_requires_historical_evidence(
        _command(operation, _promotion(kind, exact=True))
    )


def test_an_already_terminal_cancellation_without_its_observation_is_historical() -> None:
    assert domain_plan_requires_historical_evidence(
        _command("runs_cancel", _cancel("already_terminal", observed=False))
    )
    assert not domain_plan_requires_historical_evidence(
        _command("runs_cancel", _cancel("already_terminal", observed=True))
    )
    # A cancel request never observed a terminal event, so there is nothing
    # for it to have omitted.
    assert not domain_plan_requires_historical_evidence(
        _command("runs_cancel", _cancel("cancel_requested", observed=False))
    )


@pytest.mark.parametrize(
    ("operation", "plan"),
    [
        ("registry_promote", None),
        ("registry_promote", "not-an-object"),
        ("registry_promote", {"kind": "promotion", "component": "c"}),
        ("registry_promote", {"rejection": {"status": "rejected"}}),
        (
            "registry_promote",
            {"schema_version": 1, "plan": {"kind": "control_reject", "response": {}}},
        ),
        ("runs_resume", _cancel("already_terminal", observed=False)),
        ("runs_start", _promotion("promotion", exact=False)),
    ],
)
def test_other_plans_are_not_this_family(operation: str, plan: JsonValue | None) -> None:
    """Refusals, raw pre-envelope plans, and other operations belong elsewhere."""

    assert not domain_plan_requires_historical_evidence(_command(operation, plan))


def test_a_current_writer_may_not_mint_the_historical_shape() -> None:
    with pytest.raises(JournalDamaged, match="cannot mint a historical domain plan era"):
        validated_new_domain_command_plan(
            _command("registry_promote", _promotion("promotion", exact=False))
        )
    with pytest.raises(JournalDamaged, match="cannot mint a historical domain plan era"):
        validated_new_domain_command_plan(
            _command("runs_cancel", _cancel("already_terminal", observed=False))
        )
    validated_new_domain_command_plan(
        _command("registry_promote", _promotion("promotion", exact=True))
    )
    validated_new_domain_command_plan(
        _command("runs_cancel", _cancel("already_terminal", observed=True))
    )
