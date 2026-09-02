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


def _cancel_with(**fields: JsonValue) -> JsonValue:
    inner = dict(_cancel("already_terminal", observed=False)["plan"])  # type: ignore[index]
    inner.update(fields)
    return _enveloped(inner)


@pytest.mark.parametrize("status", ["pending", "running"])
def test_a_cancellation_no_writer_could_have_observed_is_not_history(status: str) -> None:
    """The migration witnesses history; it must not bless the impossible.

    Every writer that ever recorded `already_terminal` observed a terminal
    status. The shape alone is not the era — a combination no writer produced
    gets no witness, and without one it is judged as a current plan.
    """

    assert not domain_plan_requires_historical_evidence(
        _command("runs_cancel", _cancel_with(observed_status=status, response_status=status))
    )
    # And the two statuses must agree, as the plan law already demands.
    assert not domain_plan_requires_historical_evidence(
        _command("runs_cancel", _cancel_with(response_status="succeeded"))
    )


RAW_PROMOTION: dict[str, JsonValue] = {
    "component": "test/component",
    "baseline": None,
    "version": "sha256:" + "a" * 64,
    "attestation_id": "att-raw",
}
RAW_ROLLBACK: dict[str, JsonValue] = {
    "component": "test/component",
    "expected_stable": "sha256:" + "a" * 64,
    "target": "sha256:" + "b" * 64,
}


@pytest.mark.parametrize(
    ("operation", "raw"),
    [("registry_promote", RAW_PROMOTION), ("registry_rollback", RAW_ROLLBACK)],
)
def test_the_raw_pre_envelope_promotion_shape_is_historical(
    operation: str,
    raw: dict[str, JsonValue],
) -> None:
    """The first registry writer stored bare objects; they are an era too."""

    assert domain_plan_requires_historical_evidence(_command(operation, raw))
    # A raw refusal under the same operation is another family's concern.
    assert not domain_plan_requires_historical_evidence(
        _command(operation, {"rejection": {"status": "rejected"}})
    )
    # Only these two operations ever had a raw shape.
    assert not domain_plan_requires_historical_evidence(
        _command("registry_promote_initial", raw)
    )
    assert not domain_plan_requires_historical_evidence(_command("runs_cancel", raw))


@pytest.mark.parametrize(
    ("operation", "plan"),
    [
        ("registry_promote", None),
        ("registry_promote", "not-an-object"),
        ("registry_promote_initial", {"kind": "initial_promotion", "component": "c"}),
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
    """Refusals, shapes no writer ever stored raw, and other operations."""

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
