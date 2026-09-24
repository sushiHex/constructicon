"""N3c's remaining Codex matrix rows: overage, the WRITE pre-gate and no fallback.

Portable and credential-free. The scripted peer is a byte channel, not a Codex,
so these cases pin the adapter's own requests and published facts. What the
pinned client does at a real included limit is N4.
"""

from __future__ import annotations

import inspect
import json

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.core.grants import Posture
from constructicon.core.identity import digest
from constructicon.substrate.executors.codex import (
    OVERAGE_NOT_ENFORCED,
    STORE_NOT_ESTABLISHED,
    CodexConversation,
    CodexOperatorProvider,
    launch_identity,
)
from constructicon.substrate.executors.codex_protocol import (
    CONTAINED_PYTHON_CATALOG,
    ExpectedAccount,
    account_faults,
    unavailable_outcome,
)
from tests.native_operator_world import native_egress, native_store
from tests.substrate.test_codex_adapter import (
    ACQUISITION_ROOT,
    BINARY,
    CAPABILITY,
    CONFIGURATION,
    EMPTY_RESULT,
    EXPECTED,
    FINISHED,
    GRANTS,
    MANAGED_RESULT,
    SWITCHED_RESULT,
    ScriptedNative,
    bare_launcher,
    clean_native,
    codex_profile,
    context,
    converse,
    descriptor_of,
    materialized,
)
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_adapter import substituted_guard as substituted_guard
from tests.substrate.test_codex_protocol import (
    PLANTED,
    assert_published_surfaces_are_bounded,
    completed,
)
from tests.substrate.test_codex_write import (
    WriteNative,
    run_write_conversation,
    write_native,
    write_profile,
)

SIX = [
    "initialize", "initialized", "account/read", "thread/start", "turn/start", "account/read",
]
"""Every request a clean conversation sends, in order; nothing follows the last."""


# --- overage ---------------------------------------------------------------


def overage_provider(posture, overage, plan, *, binding=None):
    base = codex_profile() if posture is Posture.READ else write_profile()
    profile = base.model_copy(update={"subscription_overage": overage})
    catalog = () if posture is Posture.READ else CONTAINED_PYTHON_CATALOG
    launcher = bare_launcher()
    return CodexOperatorProvider(
        launcher=launcher, profile=profile,
        identity=launch_identity(
            launcher=launcher, profile=profile, egress=native_egress(),
            store=native_store() if binding is None else binding[0].sealed,
            executable_digest=digest("test-codex-executable", 1, BINARY),
            configuration=CONFIGURATION, catalog=catalog,
            authenticated_startup_conformance_revision=digest("test-codex-startup", 1, "x"),
            subscription_mode_conformance_revision=digest("test-codex-mode", 1, "x"),
        ),
        expected_account=ExpectedAccount(plan_type=plan), binary=BINARY,
        configuration=CONFIGURATION, catalog=catalog,
        acquisition_root=ACQUISITION_ROOT if binding is None else binding[2],
        unavailable_reasons=(),
        binding_store=None if binding is None else binding[0],
        closure=None if binding is None else binding[1],
    )


@pytest.mark.parametrize("posture", [Posture.READ, Posture.WRITE], ids=["read", "write"])
@pytest.mark.parametrize("plan", ["pro", "plus"])
@pytest.mark.parametrize("bound", [True, False], ids=["bound", "unbound"])
@pytest.mark.parametrize("overage", ["forbidden", "operator_authorized"])
async def test_only_the_overage_literal_forces_unavailability(
    tmp_path, request, posture, plan, bound, overage,
):
    # Only a bound case pays for the git-seeded binding fixture.
    binding = (
        (*request.getfixturevalue("portable_binding")[1:], tmp_path / "acquisitions")
        if bound else None
    )
    provider = overage_provider(posture, overage, plan, binding=binding)
    expected = () if bound else (STORE_NOT_ESTABLISHED,)
    if overage == "forbidden":
        expected += (OVERAGE_NOT_ENFORCED,)
    assert provider.unavailable_reasons == expected
    if expected:
        with pytest.raises(ContractViolation, match="unavailable operator provider cannot acquire"):
            await provider.acquire(context())
    else:
        acquired = await provider.acquire(context())
        assert acquired.materialize is not None
        await provider.close(acquired, "discard")


def test_a_caller_reason_tuple_cannot_clear_or_duplicate_the_overage_reason(tmp_path):
    provider = overage_provider(Posture.READ, "forbidden", "pro")
    assert provider.unavailable_reasons == (STORE_NOT_ESTABLISHED, OVERAGE_NOT_ENFORCED)
    listed = CodexOperatorProvider(
        launcher=provider.launcher, profile=provider.profile, identity=provider.identity,
        expected_account=EXPECTED, binary=BINARY, configuration=CONFIGURATION, catalog=(),
        acquisition_root=ACQUISITION_ROOT,
        unavailable_reasons=("assembly reason", OVERAGE_NOT_ENFORCED),
    )
    assert listed.unavailable_reasons == (
        "assembly reason", OVERAGE_NOT_ENFORCED, STORE_NOT_ESTABLISHED,
    )


@pytest.mark.parametrize("overage", ["forbidden", "operator_authorized"])
def test_describe_publishes_the_forced_overage_reason(journal, overage):
    provider = overage_provider(Posture.READ, overage, "pro")
    system = Constructicon(
        journal=journal, catalog={CAPABILITY: descriptor_of(provider)},
        capabilities={CAPABILITY: provider}, root_grants=GRANTS,
    )
    (described,) = system.describe().capabilities
    assert described.available is False
    assert (OVERAGE_NOT_ENFORCED in described.unavailable_reasons) is (overage == "forbidden")


# --- WRITE pre-turn refusal --------------------------------------------------


@pytest.mark.parametrize("early", [False, True], ids=["plain", "early-callback"])
async def test_a_write_refused_before_the_turn_never_offers_its_tools(early):
    callback = WriteNative._callback_for("server-1", "call-1", "must not run")
    native = ScriptedNative(accounts=[{"result": EMPTY_RESULT}], early=[callback] if early else [])
    calls: list[str] = []

    async def worker(program: str) -> str:
        calls.append(program)
        return "unexpected"

    conversation = await run_write_conversation(native, worker)
    # An early callback is refused before the account is even read.
    assert native.methods == ["initialize", "initialized"] + ([] if early else ["account/read"])
    assert b"dynamicTools" not in b"".join(native.raw_received)
    assert calls == [] and conversation.faults
    if not early:
        assert conversation.faults == account_faults({"result": EMPTY_RESULT}, EXPECTED)


async def test_a_clean_write_reading_offers_its_tools_and_dispatches_once():
    native = write_native(program="print('changed')")
    calls: list[str] = []

    async def worker(program: str) -> str:
        calls.append(program)
        return "done"

    conversation = await run_write_conversation(native, worker)
    assert conversation.faults == ()
    assert native.methods[:5] == SIX[:5] and native.methods[-1] == "account/read"
    assert b"dynamicTools" in b"".join(native.raw_received)
    assert calls == ["print('changed')"]


# --- no fallback after a mode refusal ----------------------------------------


@pytest.mark.parametrize("switched", [False, True], ids=["clean", "api-key"])
async def test_a_mode_switch_is_refused_with_no_further_request_and_one_launch(
    tmp_path, portable_binding, substituted_guard, switched,
):
    second = SWITCHED_RESULT if switched else MANAGED_RESULT
    launcher = bare_launcher(
        clean_native(accounts=[{"result": MANAGED_RESULT}, {"result": second}]),
    )
    handle = await materialized(launcher, tmp_path, portable_binding[1:])
    outcome = await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert launcher.native.methods == SIX
    assert len(launcher.calls) == 1 and len(launcher.commands) == 1
    if switched:
        assert outcome.status == "failure" and outcome.error.kind == "unavailable"
        assert "apiKey" in outcome.error.detail
        assert outcome.output is None and outcome.raw_reply is None
    else:
        assert outcome.status == "success"


async def test_the_pinned_rate_limit_notification_discards_the_turn():
    """The pinned name, read from source rather than guessed.

    ``account/rateLimits/updated`` is declared at
    ``codex-rs/app-server-protocol/src/protocol/common.rs:1907`` at ``3d2ee51``
    (tag ``rust-v0.153.4``), read with ``gh api`` for the N3c state review; the
    independent reviewer could not reach it. The params below are not the pinned
    shape: the adapter refuses the ``account/`` namespace whatever they carry.
    This is the recorded forward cost, pinned rather than fixed.
    """

    notice = {"method": "account/rateLimits/updated", "params": {"rateLimits": {"x": 1}}}
    native = clean_native(records=[notice, completed(output={"summary": "done"})])
    conversation = await converse(native)
    assert any("account/rateLimits/updated" in fault for fault in conversation.faults)
    outcome = unavailable_outcome(
        conversation.faults, conversation.observation, FINISHED, requested_model="gpt-5.6-sol",
    )
    assert outcome.status == "failure" and outcome.output is None
    control = await converse(clean_native(records=[completed(output={"summary": "done"})]))
    assert control.faults == ()


# --- a turn that reaches its limit -------------------------------------------


def limit_reached() -> dict:
    return completed(status="failed", error={
        "message": PLANTED + " usage limit", "codexErrorInfo": "usageLimitExceeded",
    })


class GenerousNative(ScriptedNative):
    """A peer that would answer spend and login requests, if any were sent."""

    def _respond(self, raw: bytes) -> None:
        request = json.loads(raw)
        if request.get("method") in {"account/rateLimitResetCredit/consume",
                                     "account/login/start"}:
            self.received.append(request)
            self._emit({"id": request["id"], "result": {"ok": True}})
            return
        super()._respond(raw)


@pytest.mark.parametrize("status", ["completed", "failed"])
async def test_a_limit_reached_turn_is_not_success_and_asks_for_nothing_more(
    tmp_path, portable_binding, substituted_guard, status,
):
    record = (
        completed(output={"summary": "done"}, model="gpt-5.6-sol")
        if status == "completed" else limit_reached()
    )
    native = GenerousNative(
        accounts=[{"result": MANAGED_RESULT}, {"result": MANAGED_RESULT}], records=[record],
    )
    launcher = bare_launcher(native)
    handle = await materialized(launcher, tmp_path, portable_binding[1:])
    outcome = await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert native.methods == SIX and len(launcher.calls) == 1
    raw = b"".join(native.raw_received)
    assert b"rateLimitResetCredit" not in raw and b"login" not in raw
    # No rateLimits object was emitted, so no overage fact exists: None, never False.
    assert outcome.rate_limit is None
    assert_published_surfaces_are_bounded(outcome)
    if status == "completed":
        assert outcome.status == "success"
        return
    assert outcome.status == "partial"
    assert "failed" in outcome.damage.first_error
    assert PLANTED not in outcome.damage.first_error


async def test_the_limit_reached_conversation_takes_no_overage_input():
    parameters = inspect.signature(CodexConversation).parameters
    assert not any("overage" in name or "profile" in name for name in parameters)
    first, second = clean_native(records=[limit_reached()]), clean_native(records=[limit_reached()])
    await converse(first)
    await converse(second)
    assert first.raw_received == second.raw_received and first.methods == SIX
