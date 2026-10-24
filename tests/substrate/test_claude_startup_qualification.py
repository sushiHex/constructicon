"""Credential-free, no-dispatch startup qualification conversation."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors.claude_maintenance_mode import _Refused as _ModeRefused
from constructicon.substrate.executors.claude_protocol import ClaudePlan
from constructicon.substrate.executors.claude_startup import (
    ClaudeSettingsMismatchReason,
    ClaudeStartupVerdict,
)
from constructicon.substrate.executors.claude_startup_qualification import (
    ClaudeQualificationLifecycle,
    ClaudeStartupQualification,
    _Refused,
)


def _wire(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode() + b"\n"


def _response(identifier: str, body: dict[str, object]) -> bytes:
    return _wire({"type": "control_response", "response": {
        "subtype": "success", "request_id": identifier, "response": body,
    }})


class Channel:
    def __init__(self, *, mode: str = "Claude Pro", tail: bytes = b"",
                 ui_after_initialize: bool = False) -> None:
        self.mode, self.tail = mode, tail
        self.ui_after_initialize = ui_after_initialize
        self.output = bytearray()
        self.changed = asyncio.Event()
        self.closed = False
        self.writes: list[str] = []
        self.readers = 0
        self.max_readers = 0

    async def write(self, raw: bytes) -> None:
        value = json.loads(raw)
        identifier = value["request_id"]
        kind = value["request"]["subtype"]
        self.writes.append(kind)
        if kind == "initialize":
            body = {"claude_code_version": "2.1.296", "session_state": "idle",
                    "account": {"apiProvider": "firstParty", "subscriptionType": self.mode}}
            response = {"type": "control_response", "response": {
                "subtype": "success", "request_id": identifier, "response": body,
                "pending_permission_requests": [], "pending_user_dialog_requests": [],
            }}
            self.output.extend(_wire(response))
            if self.ui_after_initialize:
                self.output.extend(
                    b'{"type":"system","subtype":"ui_invalidate","event":"ui.render",'
                    b'"uuid":"x","session_id":""}\n'
                )
        elif kind == "get_settings":
            body = {"effective": {"forceRemoteSettingsRefresh": True,
                                  "deniedMcpServers": [{"serverUrl": "*"}]},
                    "sources": [{"source": "policySettings", "settings": {
                        "forceRemoteSettingsRefresh": True,
                        "deniedMcpServers": [{"serverUrl": "*"}]}}],
                    "applied": {"model": "claude-sonnet-4-6", "effort": "low",
                                "advisor": None, "ultracode": False,
                                "ultracodeRequested": False, "ultracodeAvailable": False}}
            self.output.extend(_response(identifier, body))
        else:
            body = {"events": [], "hooks": [], "eventCatalog": [{
                "name": "PreToolUse", "summary": "x", "supportsMatcher": True}],
                "policy": {"disabledByPolicy": False, "managedOnly": False,
                           "pluginOnly": False, "allDisabled": False,
                           "policyHookCount": 0},
                "safeMode": {"managedHooksStillApply": True,
                             "exitHint": "restart without --safe-mode"}}
            self.output.extend(_response(identifier, body) + self.tail)
        self.changed.set()

    async def read(self, maximum: int = 8192) -> bytes:
        self.readers += 1
        self.max_readers = max(self.max_readers, self.readers)
        try:
            while not self.output and not self.closed:
                self.changed.clear()
                await self.changed.wait()
            chunk = bytes(self.output[:maximum])
            del self.output[:maximum]
            return chunk
        finally:
            self.readers -= 1

    async def close_stdin(self) -> None:
        self.closed = True
        self.changed.set()


@pytest.mark.asyncio
async def test_three_observations_accept_without_dispatch() -> None:
    channel = Channel()
    conversation = ClaudeStartupQualification(
        selected_plan=ClaudePlan.PRO, model="claude-sonnet-4-6", effort="low",
        input_limit=8192, output_limit=512 * 1024,
        deadline=asyncio.get_running_loop().time() + 5,
    )
    await conversation(channel)
    assert channel.writes == ["initialize", "get_settings", "get_hooks_listing"]
    facts = conversation.facts
    assert facts.lifecycle is ClaudeQualificationLifecycle.QUALIFIED
    assert facts.settings_mismatch_reason is None
    assert (facts.request_writes, facts.stdin_closed, facts.eof,
            facts.ui_records) == (3, True, True, 0)
    assert channel.max_readers == 1


@pytest.mark.asyncio
async def test_exact_ui_after_first_response_is_consumed_before_next_write() -> None:
    channel = Channel(ui_after_initialize=True)
    conversation = ClaudeStartupQualification(
        selected_plan=ClaudePlan.PRO, model="claude-sonnet-4-6", effort="low",
        input_limit=8192, output_limit=512 * 1024,
        deadline=asyncio.get_running_loop().time() + 5,
    )
    try:
        await conversation(channel)
    except (_Refused, _ModeRefused):
        pytest.fail("an exact queued UI frame must not block the next control")
    assert channel.writes == ["initialize", "get_settings", "get_hooks_listing"]
    assert conversation.facts.lifecycle is ClaudeQualificationLifecycle.QUALIFIED
    assert conversation.facts.ui_records == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,tail", [("Claude API", b""),
                                       ("Claude Pro", b'{"type":"assistant"}\n')])
async def test_mode_ambiguity_and_tail_refuse(mode: str, tail: bytes) -> None:
    channel = Channel(mode=mode, tail=tail)
    conversation = ClaudeStartupQualification(
        selected_plan=ClaudePlan.PRO, model="claude-sonnet-4-6", effort="low",
        input_limit=8192, output_limit=512 * 1024,
        deadline=asyncio.get_running_loop().time() + 5,
    )
    with pytest.raises((_Refused, _ModeRefused)):
        await conversation(channel)
    assert conversation.facts.lifecycle is ClaudeQualificationLifecycle.REFUSED
    assert conversation.facts.settings_mismatch_reason is None
    if mode == "Claude API":
        assert channel.writes == ["initialize"]
    else:
        assert channel.writes == ["initialize", "get_settings", "get_hooks_listing"]


@pytest.mark.asyncio
async def test_wrong_correlated_id_refuses_before_next_control() -> None:
    class WrongID(Channel):
        async def write(self, raw: bytes) -> None:
            await super().write(raw)
            if len(self.writes) == 2:
                identifier = json.loads(raw)["request_id"].encode()
                self.output[:] = self.output.replace(identifier, b"wrong-id")

    channel = WrongID()
    conversation = ClaudeStartupQualification(
        selected_plan=ClaudePlan.PRO, model="claude-sonnet-4-6", effort="low",
        input_limit=8192, output_limit=512 * 1024,
        deadline=asyncio.get_running_loop().time() + 5,
    )
    with pytest.raises(_Refused):
        await conversation(channel)
    assert channel.writes == ["initialize", "get_settings"]
    assert conversation.facts.request_writes == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["get_settings", "get_hooks_listing"])
async def test_each_startup_judge_must_match(kind: str) -> None:
    class Mismatch(Channel):
        async def write(self, raw: bytes) -> None:
            await super().write(raw)
            if self.writes[-1] == kind:
                if kind == "get_settings":
                    self.output[:] = self.output.replace(b'"effort":"low"',
                                                         b'"effort":"high"')
                else:
                    self.output[:] = self.output.replace(b'"hooks":[]',
                                                         b'"hooks":[{}]')

    channel = Mismatch()
    conversation = ClaudeStartupQualification(
        selected_plan=ClaudePlan.PRO, model="claude-sonnet-4-6", effort="low",
        input_limit=8192, output_limit=512 * 1024,
        deadline=asyncio.get_running_loop().time() + 5,
    )
    with pytest.raises(_Refused):
        await conversation(channel)
    assert channel.writes == ["initialize", "get_settings"] + (
        ["get_hooks_listing"] if kind == "get_hooks_listing" else []
    )
    assert conversation.facts.lifecycle is ClaudeQualificationLifecycle.REFUSED
    assert conversation.facts.settings_mismatch_reason is (
        ClaudeSettingsMismatchReason.EFFORT_MISMATCH if kind == "get_settings" else None
    )
    assert channel.readers == 0


def test_incomplete_and_mismatched_settings_reasons_are_truthful():
    conversation = ClaudeStartupQualification(
        selected_plan=ClaudePlan.PRO, model="claude-sonnet-4-6", effort="low",
        input_limit=8192, output_limit=512 * 1024, deadline=10.0,
    )
    facts = conversation.facts
    assert facts.lifecycle is ClaudeQualificationLifecycle.INCOMPLETE
    assert facts.settings_verdict is facts.settings_mismatch_reason is None
    refused = replace(
        facts, lifecycle=ClaudeQualificationLifecycle.REFUSED,
        settings_verdict=ClaudeStartupVerdict.CONFIGURATION_MISMATCH,
        settings_mismatch_reason=ClaudeSettingsMismatchReason.EFFORT_MISMATCH,
    )
    for change in ({"settings_verdict": None}, {"settings_verdict": ClaudeStartupVerdict.MATCH},
                   {"settings_mismatch_reason": "effort-mismatch"},
                   {"settings_mismatch_reason": None}):
        with pytest.raises(ValueError, match="invalid Claude qualification facts"):
            replace(refused, **change)


@pytest.mark.asyncio
async def test_partial_frame_before_next_control_refuses_without_next_write() -> None:
    class Partial(Channel):
        async def write(self, raw: bytes) -> None:
            await super().write(raw)
            if self.writes[-1] == "initialize":
                self.output.extend(b"{")

    channel = Partial()
    conversation = ClaudeStartupQualification(
        selected_plan=ClaudePlan.PRO, model="claude-sonnet-4-6", effort="low",
        input_limit=8192, output_limit=512 * 1024,
        deadline=asyncio.get_running_loop().time() + 5,
    )
    with pytest.raises((_Refused, _ModeRefused)):
        await conversation(channel)
    assert channel.writes == ["initialize"]
    assert conversation.facts.request_writes == 1


@pytest.mark.asyncio
async def test_reentry_aborts_silent_owner_and_joins_reader() -> None:
    channel = Channel()

    async def silent_write(raw: bytes) -> None:
        channel.writes.append(json.loads(raw)["request"]["subtype"])

    channel.write = silent_write  # type: ignore[method-assign]
    conversation = ClaudeStartupQualification(
        selected_plan=ClaudePlan.PRO, model="claude-sonnet-4-6", effort="low",
        input_limit=8192, output_limit=512 * 1024,
        deadline=asyncio.get_running_loop().time() + 5,
    )
    owner = asyncio.create_task(conversation(channel))
    for _ in range(10):
        if channel.writes:
            break
        await asyncio.sleep(0)
    try:
        with pytest.raises(ContractViolation):
            await conversation(channel)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(owner, 1)
        assert channel.readers == 0
        assert conversation.facts.lifecycle is ClaudeQualificationLifecycle.REFUSED
    finally:
        if not owner.done():
            owner.cancel()
            with pytest.raises(asyncio.CancelledError):
                await owner


@pytest.mark.asyncio
async def test_cleanup_failure_after_matching_settings_never_invents_a_reason():
    class CloseFailure(Channel):
        async def close_stdin(self):
            raise OSError("private-sentinel")
    channel = CloseFailure()
    conversation = ClaudeStartupQualification(
        selected_plan=ClaudePlan.PRO, model="claude-sonnet-4-6", effort="low",
        input_limit=8192, output_limit=512 * 1024,
        deadline=asyncio.get_running_loop().time() + 5,
    )
    with pytest.raises(OSError):
        await conversation(channel)
    assert conversation.facts.lifecycle is ClaudeQualificationLifecycle.REFUSED
    assert conversation.facts.settings_verdict is ClaudeStartupVerdict.MATCH
    assert conversation.facts.settings_mismatch_reason is None
    assert conversation.facts.stdin_closed is False
    assert channel.readers == 0
