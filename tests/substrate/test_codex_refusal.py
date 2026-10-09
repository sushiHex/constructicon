"""H7 refusal evidence, with the real conversation and a scripted byte channel."""

from __future__ import annotations

import json

import pytest

from constructicon.substrate.executors.codex_protocol import (
    ACCOUNT_NOTICE_FAULT,
    DUPLICATE_REPLY_FAULT,
    IDENTITY_FAULT,
    ExpectedAccount,
    account_notice_faults,
)
from tests.substrate.test_codex_adapter import (
    UPDATED_FAULT,
    ScriptedNative,
    converse,
    exact_update,
)
from tests.substrate.test_codex_lane import FOUR, gate, startup
from tests.substrate.test_codex_lane import substituted as substituted
from tests.substrate.test_codex_protocol import EMAIL, IDENTITY, completed, managed

TERMINAL = {
    "the startup gate did not complete",
    "the startup did not send exactly the four authorized methods",
    "no spend readback was judged",
}
READING_FAULT = "account plan 'pro' is not the expected 'plus'"
NOTICE_FAULT = "account/updated plan 'pro' is not the expected 'plus'"


class AccountNoticeNative(ScriptedNative):
    """Emit the notice only after receiving the actual account request."""

    def __init__(self, *, notice=None, order="before", account=None, duplicate=False,
                 read_limit=None, reply_override=None, accounts=None, notice_on=1):
        super().__init__(accounts=[{"result": managed() if account is None else account}]
                         if accounts is None else accounts, read_limit=read_limit,
                         records=[completed()])
        self.notice = exact_update() if notice is None else notice
        self.order = order
        self.duplicate_account = duplicate
        self.reply_override = reply_override
        self.notice_on = notice_on

    def _respond(self, raw):
        request = json.loads(raw)
        notifying = request.get("method") == "account/read" and (
            self.accounts_seen + 1 == self.notice_on
        )
        if notifying and self.order == "before":
            self._emit(self.notice)
        if request.get("method") == "account/read" and self.reply_override is not None:
            self.received.append(request)
            self.accounts_seen += 1
            self._emit({"id": request["id"], **self.reply_override})
        else:
            super()._respond(raw)
        if request.get("method") == "account/read":
            if self.duplicate_account:
                self._emit({"id": request["id"], "result": managed()})
            if notifying and self.order == "after":
                self._emit(self.notice)


@pytest.mark.parametrize("order", ["before", "after"])
@pytest.mark.parametrize("read_limit", [None, 1], ids=["same-chunk", "split"])
async def test_exact_wrong_plan_notice_and_reading_are_affirmative(tmp_path, order, read_limit):
    native = AccountNoticeNative(order=order, read_limit=read_limit)
    _, evidence = await startup(tmp_path, native, expected=ExpectedAccount(
        plan_type="plus", identity=IDENTITY,
    ))
    assert set(evidence["faults"]) == TERMINAL | {READING_FAULT, NOTICE_FAULT}
    assert len(evidence["faults"]) == 5
    assert evidence["methods_sent"] == FOUR[:3]
    assert evidence["gate"] == gate(False, None)
    assert evidence["readback"] is None
    assert evidence["observation"] == {"malformed_records": 0, "first_error": False}
    assert native.stdin_closed and native.accounts_seen == 1


@pytest.mark.parametrize("order", ["before", "after"])
@pytest.mark.parametrize("read_limit", [None, 1], ids=["same-chunk", "split"])
async def test_matching_notice_and_reading_still_complete(tmp_path, order, read_limit):
    _, evidence = await startup(tmp_path, AccountNoticeNative(order=order, read_limit=read_limit))
    assert evidence["faults"] == []
    assert evidence["methods_sent"] == FOUR and evidence["gate"] == gate(True, "pro")


@pytest.mark.parametrize("notice", [
    {"method": "account/updated", "params": {"authMode": "apikey", "planType": "pro"}},
    {"method": "account/updated", "params": {"authMode": "chatgpt", "planType": "pro",
                                               "extra": EMAIL}},
    {"method": "account/updated", "params": {"authMode": "chatgpt", "planType": "unknown"}},
    {"method": "account/updated", "params": {"authMode": "chatgpt", "planType": ["pro"]}},
    {"method": "account/updated", "params": {"authMode": "chatgpt", "planType": "pro"},
     "result": {}},
    {"method": "account/updated", "params": {"authMode": "chatgpt", "planType": "pro"},
     "error": {}},
], ids=["wrong-auth", "extra-key", "unknown-plan", "non-string-plan", "result", "error"])
async def test_only_an_exact_approved_notice_can_supply_plan_evidence(tmp_path, notice):
    _, evidence = await startup(tmp_path, AccountNoticeNative(notice=notice),
                                expected=ExpectedAccount(plan_type="plus", identity=IDENTITY))
    assert ACCOUNT_NOTICE_FAULT.format(method="'account/updated'") in evidence["faults"]
    assert NOTICE_FAULT not in evidence["faults"]
    assert EMAIL not in json.dumps(evidence) and "unknown" not in json.dumps(evidence)


async def test_a_pending_account_reply_is_judged_for_the_sealed_identity(tmp_path):
    _, evidence = await startup(tmp_path, AccountNoticeNative(account=managed(email="other")),
                                expected=ExpectedAccount(plan_type="plus", identity=IDENTITY))
    assert IDENTITY_FAULT in evidence["faults"]
    assert evidence["gate"]["account"] != IDENTITY.root
    assert not evidence["gate"]["completed"] and evidence["readback"] is None


async def test_a_pending_account_reply_cannot_answer_twice(tmp_path):
    _, evidence = await startup(tmp_path, AccountNoticeNative(duplicate=True),
                                expected=ExpectedAccount(plan_type="plus", identity=IDENTITY))
    assert DUPLICATE_REPLY_FAULT in evidence["faults"]


async def test_an_allocated_but_unsent_account_reply_is_still_unsolicited(tmp_path):
    native = ScriptedNative(accounts=[{"result": managed()}], early=[
        exact_update(), {"id": 2, "result": managed()},
    ])
    _, evidence = await startup(tmp_path, native,
                                expected=ExpectedAccount(plan_type="plus", identity=IDENTITY))
    assert any("before the request it claims to answer" in fault for fault in evidence["faults"])
    assert evidence["methods_sent"] == FOUR[:2]
    assert evidence["gate"]["account"] is None


@pytest.mark.parametrize("reply", [
    {"id": 2.0, "result": managed()}, {"id": True, "result": managed()},
    {"id": [], "result": managed()}, {"id": "2", "result": managed()},
    {"id": None, "result": managed()}, {"method": "account/updated", "result": managed()},
    {"result": managed(), "error": {}}, {}, {"result": []}, {"error": {}},
], ids=["float", "boolean", "array", "string", "null", "native-request", "both",
        "neither", "non-object-result", "error"])
async def test_a_pending_reply_still_requires_the_exact_response_contract(tmp_path, reply):
    _, evidence = await startup(tmp_path, AccountNoticeNative(reply_override=reply),
                                expected=ExpectedAccount(plan_type="plus", identity=IDENTITY))
    assert set(evidence["faults"]) != TERMINAL | {READING_FAULT, NOTICE_FAULT}
    assert evidence["gate"]["account"] is None
    assert not evidence["gate"]["completed"] and evidence["readback"] is None
    if "method" not in reply and ("result" in reply) == ("error" in reply):
        assert "the 'account/read' reply carries neither a result nor an error" in (
            evidence["faults"]
        )


def test_an_id_bearing_notice_cannot_supply_exact_plan_evidence():
    faults = account_notice_faults({"id": 2, **exact_update()},
                                   ExpectedAccount(plan_type="plus", identity=IDENTITY))
    assert faults == (ACCOUNT_NOTICE_FAULT.format(method="'account/updated'"),)


async def test_cleanup_checks_the_plan_latched_before_the_pending_reading(tmp_path):
    class ContradictingNative(AccountNoticeNative):
        def _respond(self, raw):
            if json.loads(raw).get("method") == "account/read":
                self._emit(exact_update("pro"))
            super()._respond(raw)

    native = ContradictingNative(account=managed(planType="prolite"), notice={
        "method": "account/login/completed", "params": {},
    })
    _, evidence = await startup(tmp_path, native, expected=ExpectedAccount(
        plan_type="pro", alternatives=("prolite",), identity=IDENTITY,
    ))
    assert UPDATED_FAULT in evidence["faults"]
    assert not evidence["gate"]["completed"] and evidence["readback"] is None


async def test_cleanup_never_overwrites_the_first_readings_identity():
    native = AccountNoticeNative(notice=exact_update("prolite"), notice_on=2, accounts=[
        {"result": managed()}, {"result": managed(email="other")},
    ])
    conversation = await converse(native)
    assert conversation.observed_account == IDENTITY
    assert IDENTITY_FAULT in conversation.faults


async def test_cleanup_cannot_correlate_a_reply_started_before_its_request(tmp_path):
    class FragmentNative(ScriptedNative):
        fragment = (json.dumps({"id": 2, "result": managed()}) + "\n").encode()

        def _respond(self, raw):
            request = json.loads(raw)
            if request.get("method") == "account/read":
                self.received.append(request)
                self.accounts_seen += 1
                self.pending.extend(self.fragment[25:])
                return
            super()._respond(raw)
            if request.get("method") == "initialize":
                self.pending.extend(self.fragment[:25])

        async def read(self, maximum=8192):
            if self.accounts_seen and not self.stdin_closed:
                raise OSError("abort before consuming the forged remainder")
            return await super().read(maximum)

    _, evidence = await startup(tmp_path, FragmentNative(accounts=[]),
                                expected=ExpectedAccount(plan_type="plus", identity=IDENTITY))
    assert any("before the request it claims to answer" in fault for fault in evidence["faults"])
    assert evidence["gate"]["account"] is None
    assert READING_FAULT not in evidence["faults"]
