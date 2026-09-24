"""N4's conversation additions: the spend readbacks and the startup boundary.

Portable and scripted (M8-N4-state-review.md, sections 2 and 5). The startup
lane is the task conversation stopped after its first readback, so it sends
exactly the four methods the owner authorized and never a thread.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.substrate.executors import codex
from constructicon.substrate.executors.codex import CodexConversation
from constructicon.substrate.executors.codex_protocol import (
    CONTAINED_PYTHON_CATALOG,
    CREDITS_FAULT,
    GATE_INCOMPLETE_FAULT,
    SPEND_UNREADABLE_FAULT,
    ExpectedAccount,
    unavailable_outcome,
)
from tests.substrate.test_codex_adapter import (
    EXPECTED,
    FINISHED,
    GRANTS,
    MANAGED_RESULT,
    ScriptedNative,
    bare_launcher,
    clean_native,
    converse,
    materialized,
)
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_adapter import substituted_guard as substituted_guard
from tests.substrate.test_codex_matrix import EIGHT
from tests.substrate.test_codex_protocol import (
    ACCOUNT_ID,
    EMAIL,
    MANAGED,
    completed,
    spend_result,
)
from tests.substrate.test_codex_write import run_write_conversation, write_native

FOUR = EIGHT[:4]
"""The owner's N4 authorization: initialize, initialized, account/read and
account/rateLimits/read. No thread/start, no turn/start, no model request."""

UNREADABLE = {"error": {"code": -32600, "message": "codex account authentication required"}}
WITH_CREDITS = {"result": spend_result(credits={
    "hasCredits": True, "unlimited": False, "balance": "12.50",
})}


def startup(*, expected=EXPECTED) -> CodexConversation:
    return CodexConversation(
        task=TaskSpec(instruction="unused by the startup phase"), grants=GRANTS,
        expected=expected, input_limit=1024 * 1024, startup_only=True,
    )


async def run(conversation, native):
    await asyncio.wait_for(conversation(native), 5)
    return conversation


# --- the startup boundary ----------------------------------------------------


async def test_the_startup_phase_sends_exactly_the_four_authorized_methods():
    native = clean_native()
    conversation = await run(startup(), native)
    assert native.methods == FOUR
    assert conversation.faults == () and conversation.gate_completed is True
    assert conversation.observed_plan == "pro"
    assert conversation.before_spend is not None and conversation.after_spend is None
    assert conversation.before_spend.has_credits is False
    # Stdin closes after the readback: nothing else was written at all.
    assert native.stdin_closed and len(native.raw_received) == 3 + 1


@pytest.mark.parametrize("spend,fault", [
    (UNREADABLE, SPEND_UNREADABLE_FAULT), (WITH_CREDITS, CREDITS_FAULT),
], ids=["expired-or-error", "purchased-credits"])
async def test_a_refused_startup_readback_is_a_fault_and_never_a_thread(spend, fault):
    native = clean_native(spends=[spend])
    conversation = await run(startup(), native)
    assert native.methods == FOUR
    assert fault in conversation.faults and conversation.gate_completed is False


async def test_a_startup_whose_readback_never_arrives_is_refused_not_completed():
    native = clean_native(spends=[])
    conversation = await run(startup(), native)
    assert native.methods == FOUR
    assert conversation.faults and conversation.gate_completed is False


class ExplodingReadback(ScriptedNative):
    """A transport failure no layer catches, raised while the readback is due."""

    def _respond(self, raw: bytes) -> None:
        if json.loads(raw).get("method") == "account/rateLimits/read":
            self.received.append(json.loads(raw))
            self.armed = True
            self.changed.set()
            return
        super()._respond(raw)


async def test_an_abort_inside_the_startup_readback_never_looks_clean():
    native = ExplodingReadback(
        accounts=[{"result": MANAGED_RESULT}], read_fails=RuntimeError("transport exploded"),
        fails_on_nth_account=99,
    )
    conversation = startup()
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(conversation(native), 5)
    assert native.methods == FOUR
    assert conversation.gate_completed is False
    assert GATE_INCOMPLETE_FAULT in conversation.faults


@pytest.mark.parametrize("kwargs", [
    {"startup_only": 1}, {"startup_only": "yes"},
])
def test_the_startup_selector_is_exactly_boolean(kwargs):
    with pytest.raises(ContractViolation, match="boolean"):
        CodexConversation(
            task=TaskSpec(instruction="x"), grants=GRANTS, expected=EXPECTED,
            input_limit=1024, **kwargs,
        )


def test_a_startup_conversation_offers_no_callbacks():
    with pytest.raises(ContractViolation, match="offers no callbacks"):
        CodexConversation(
            task=TaskSpec(instruction="x"), grants=GRANTS, expected=EXPECTED,
            input_limit=1024, catalog=CONTAINED_PYTHON_CATALOG, startup_only=True,
        )


async def test_the_handle_never_runs_the_startup_phase(
    tmp_path, portable_binding, substituted_guard, monkeypatch,
):
    """Every production conversation continues to the turn."""

    constructed: list[dict] = []
    original = CodexConversation.__init__

    def spy(self, **kwargs):
        constructed.append(kwargs)
        original(self, **kwargs)

    monkeypatch.setattr(codex.CodexConversation, "__init__", spy)
    launcher = bare_launcher(clean_native())
    handle = await materialized(launcher, tmp_path, portable_binding[1:])
    outcome = await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert outcome.status == "success"
    assert len(constructed) == 1 and constructed[0].get("startup_only", False) is False
    assert launcher.native.methods == EIGHT


# --- the task conversation's readbacks ---------------------------------------


@pytest.mark.parametrize("spend,fault", [
    (UNREADABLE, SPEND_UNREADABLE_FAULT), (WITH_CREDITS, CREDITS_FAULT),
], ids=["expired-or-error", "purchased-credits"])
async def test_a_refused_pre_turn_readback_never_sends_a_thread(spend, fault):
    """The scripted expired login: ``account/read`` clean, the readback not."""

    native = clean_native(spends=[spend])
    conversation = await converse(native)
    assert native.methods == FOUR
    assert fault in conversation.faults and not conversation.observation.terminal
    outcome = unavailable_outcome(
        conversation.faults, conversation.observation, FINISHED, requested_model="gpt-5.6-sol",
    )
    assert outcome.status == "failure" and outcome.error.produced_output is False


async def test_a_refused_pre_turn_readback_never_offers_write_tools():
    native = write_native()
    native.spends = [WITH_CREDITS]
    calls: list[str] = []

    async def worker(program: str) -> str:
        calls.append(program)
        return "unexpected"

    conversation = await run_write_conversation(native, worker)
    assert native.methods == FOUR
    assert b"dynamicTools" not in b"".join(native.raw_received)
    assert calls == [] and CREDITS_FAULT in conversation.faults


async def test_a_post_turn_overage_change_discards_the_turn():
    native = clean_native(spends=[{"result": spend_result()}, WITH_CREDITS])
    conversation = await converse(native)
    assert native.methods == EIGHT and conversation.gate_completed
    assert "readback has credits changed across the turn" in conversation.faults
    assert CREDITS_FAULT in conversation.faults
    outcome = unavailable_outcome(
        conversation.faults, conversation.observation, FINISHED, requested_model="gpt-5.6-sol",
    )
    assert outcome.status == "failure" and outcome.output is None
    assert outcome.rate_limit is None  # a refusal publishes no readback


async def test_a_post_turn_readback_that_never_arrives_is_a_refusal():
    native = clean_native(spends=[{"result": spend_result()}])
    conversation = await converse(native)
    assert native.methods == EIGHT
    assert conversation.faults and conversation.gate_completed is False


async def test_the_accepting_turn_publishes_both_readbacks_and_no_identity(
    tmp_path, portable_binding, substituted_guard,
):
    after = {"result": spend_result(
        primary={"usedPercent": 7, "windowDurationMins": 300, "resetsAt": 1},
    )}
    native = clean_native(spends=[{"result": spend_result()}, after])
    launcher = bare_launcher(native)
    handle = await materialized(launcher, tmp_path, portable_binding[1:])
    outcome = await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert outcome.status == "success" and native.methods == EIGHT
    assert outcome.rate_limit.is_using_overage is None
    assert outcome.rate_limit.detail.get("before.primary_used_percent") == 3
    assert outcome.rate_limit.detail.get("after.primary_used_percent") == 7
    published = json.dumps(outcome.model_dump(mode="json"))
    for planted in (ACCOUNT_ID, EMAIL, "Codex"):
        assert planted not in published


async def test_a_provider_auth_recovery_mid_turn_discards_it():
    recovery = {"method": "modelProvider/authRecoveryCompleted", "params": {
        "threadId": "t", "turnId": "u", "provider": "Amazon Bedrock", "message": EMAIL,
    }}
    native = clean_native(records=[recovery, completed(output={"summary": "done"})])
    conversation = await converse(native)
    assert any("modelProvider/authRecoveryCompleted" in fault for fault in conversation.faults)
    assert not any("Bedrock" in fault or EMAIL in fault for fault in conversation.faults)


# --- the qualification plan set (orchestrator decision 1) --------------------


@pytest.mark.parametrize("plan", ["pro", "prolite"])
async def test_qualification_records_whichever_declared_literal_the_account_reports(plan):
    account = {"result": {"account": {**MANAGED, "planType": plan}, "requiresOpenaiAuth": True}}
    native = clean_native(accounts=[account], spends=[{"result": spend_result(planType=plan)}])
    conversation = await run(
        startup(expected=ExpectedAccount(plan_type="pro", alternatives=("prolite",))), native,
    )
    assert conversation.faults == () and conversation.observed_plan == plan


async def test_qualification_refuses_an_undeclared_plan_and_records_none():
    account = {"result": {"account": {**MANAGED, "planType": "plus"}, "requiresOpenaiAuth": True}}
    native = clean_native(accounts=[account])
    conversation = await run(
        startup(expected=ExpectedAccount(plan_type="pro", alternatives=("prolite",))), native,
    )
    assert conversation.faults and conversation.observed_plan is None
    assert native.methods == EIGHT[:3]
