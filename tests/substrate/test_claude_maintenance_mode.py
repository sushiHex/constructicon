"""Credential-free bounded Claude maintenance mode observation."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, fields, replace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.substrate.executors import claude_maintenance_mode as maintenance
from constructicon.substrate.executors.claude_native import (
    ClaudeNativeRecipe,
    ClaudeNativeStoreMount,
)
from constructicon.substrate.executors.claude_native_events import exact_ui_invalidate
from constructicon.substrate.executors.claude_protocol import (
    ClaudeInitializeVerdict,
    ClaudeModeMismatchReason,
    ClaudePlan,
    initialize_request,
)
from constructicon.substrate.executors.linux import DEFAULT_PROCESS_LIMITS, ProcessResult
from constructicon.substrate.executors.operator_store import BindingCheck

CLEAN = ProcessResult(0, b"private-output", b"private-error", 0.1, payload_returncode=0)


def response(identifier: str, plan: str = "Claude Pro", **account: object) -> bytes:
    return json.dumps({"type": "control_response", "response": {
        "subtype": "success", "request_id": identifier,
        "response": {"claude_code_version": "2.1.296", "session_state": "idle",
                     "account": {"apiProvider": "firstParty", "subscriptionType": plan,
                                 **account}},
        "pending_permission_requests": [], "pending_user_dialog_requests": [],
    }}, separators=(",", ":")).encode() + b"\n"


def ui() -> bytes:
    return (b'{"type":"system","subtype":"ui_invalidate","event":"ui.render",'
            b'"uuid":"x","session_id":""}\n')


def test_shared_ui_discriminators_are_exact_before_consumer_validation():
    valid = json.loads(ui())
    assert exact_ui_invalidate(valid)
    assert not exact_ui_invalidate([])

    class DictSubclass(dict):
        pass

    assert not exact_ui_invalidate(DictSubclass(valid))
    assert not exact_ui_invalidate({**valid, "type": "not-system"})
    assert not exact_ui_invalidate({**valid, "subtype": "not-ui"})


class Channel:
    def __init__(self, answers: list[bytes], *, fragment: int = 8192) -> None:
        self.answers = answers
        self.fragment = fragment
        self.output = bytearray()
        self.changed = asyncio.Event()
        self.writes: list[bytes] = []
        self.reads = 0
        self.active_readers = 0
        self.max_readers = 0
        self.closed = False
        self.read_cancelled = False

    async def write(self, raw: bytes) -> None:
        request = json.loads(raw)
        assert request == {"type": "control_request", "request_id": request["request_id"],
                           "request": {"subtype": "initialize"}}
        self.writes.append(raw)
        if self.answers:
            self.output.extend(self.answers.pop(0).replace(b"@ID@", request["request_id"].encode()))
            self.changed.set()

    async def read(self, maximum: int = 8192) -> bytes:
        assert 1 <= maximum <= 8192
        self.active_readers += 1
        self.max_readers = max(self.max_readers, self.active_readers)
        self.reads += 1
        try:
            while not self.output and not self.closed:
                self.changed.clear()
                await self.changed.wait()
            size = min(len(self.output), maximum, self.fragment)
            chunk = bytes(self.output[:size])
            del self.output[:size]
            return chunk
        except asyncio.CancelledError:
            self.read_cancelled = True
            raise
        finally:
            self.active_readers -= 1

    async def close_stdin(self) -> None:
        self.closed = True
        self.changed.set()


class Launcher:
    def __init__(self, channel: Channel, *, result: ProcessResult = CLEAN,
                 recipe: ClaudeNativeRecipe = ClaudeNativeRecipe.STREAM_JSON) -> None:
        self.channel = channel
        self.result = result
        self.claude_recipe = recipe
        self.claude = type("Vendor", (), {"command": ("fixed-claude-stream",)})()
        self.limits = replace(DEFAULT_PROCESS_LIMITS, input_bytes=8192, stdout_bytes=512 * 1024)
        self.calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
        self.joined = False

    async def exchange(self, command: tuple[str, ...], **kwargs: object) -> ProcessResult:
        kwargs["native_store"].before_spawn()
        self.calls.append((command, kwargs))
        try:
            await kwargs["conversation"](self.channel)
            return self.result
        finally:
            self.joined = True


async def observe(
    channel: Channel, *, phase: maintenance.ClaudeMaintenancePhase | None = None,
    result: ProcessResult = CLEAN,
    recipe: ClaudeNativeRecipe = ClaudeNativeRecipe.STREAM_JSON,
    check=None, timeout: float = 5, input_bytes: int = 8192,
    plan: ClaudePlan = ClaudePlan.PRO,
) -> tuple[maintenance.ClaudeMaintenanceObservation, Launcher, list[bool]]:
    launcher = Launcher(channel, result=result, recipe=recipe)
    launcher.limits = replace(launcher.limits, input_bytes=input_bytes)
    checked: list[bool] = []
    binding = BindingCheck(digest("fake-claude-maintenance", 1, "same-object"))

    def custody() -> BindingCheck:
        checked.append(launcher.joined)
        return binding if check is None else check(len(checked))

    mount = ClaudeNativeStoreMount(17, 18, custody)
    report = await maintenance.observe_maintenance_mode(
        launcher, mount, phase=phase or maintenance.ClaudeMaintenancePhase.OBSERVE,
        selected_plan=plan, timeout_s=timeout,
    )
    return report, launcher, checked


@pytest.mark.parametrize("phase,count", [("OBSERVE", 2), ("RELOAD", 1)])
@pytest.mark.parametrize("plan", list(ClaudePlan))
async def test_first_positive_mode_closes_drains_and_joins_without_second_write(
    phase, count, plan,
):
    channel = Channel([ui() * 4 + response("@ID@", plan.value) + ui() * 4])
    report, launcher, checked = await observe(
        channel, phase=maintenance.ClaudeMaintenancePhase[phase], plan=plan,
    )
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.OBSERVED
    assert report.mode_verdict is ClaudeInitializeVerdict.MODE_MATCH
    assert report.mode_mismatch_reason is None
    assert report.classified_responses == 1
    assert report.request_writes == 1 and report.ui_records == 8
    assert report.stdin_closed and report.eof and launcher.joined
    assert channel.max_readers == 1 and len(channel.writes) < count + 1
    assert checked == [False, False, True]
    command, args = launcher.calls[0]
    assert command == launcher.claude.command and args["workspace"] is None
    assert args["guard_fds"] == (17,) and args["native_store"] is not None


@pytest.mark.parametrize("phase", list(maintenance.ClaudeMaintenancePhase))
async def test_login_recipe_refused_before_store_or_process(phase):
    channel = Channel([response("@ID@")])
    report, launcher, checked = await observe(channel, phase=phase,
                                               recipe=ClaudeNativeRecipe.LOGIN)
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert launcher.calls == [] and checked == [] and channel.writes == []


@pytest.mark.parametrize("raw", [response("@ID@", "Claude Max"),
                                  response("@ID@", "Claude API", tokenSource="none"),
                                  response("@ID@", "Claude API", email=None),
                                  b'{"type":"control_request"}\n',
                                  response("wrong-id", "Claude API")])
async def test_only_exact_ambiguous_api_shape_may_wait_for_another_request(raw):
    channel = Channel([raw])
    report, _, _ = await observe(channel)
    assert report.lifecycle is not maintenance.ClaudeMaintenanceLifecycle.OBSERVED
    assert report.request_writes == 1 and len(channel.writes) == 1


async def test_ambiguous_first_observation_can_reach_second_after_real_spacing(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(maintenance, "_monotonic", lambda: clock[0])
    channel = Channel([response("@ID@", "Claude API"), response("@ID@")])
    task = asyncio.create_task(observe(channel, timeout=120))
    for _ in range(100):
        if channel.reads >= 2:
            break
        await asyncio.sleep(0)
    assert len(channel.writes) == 1 and channel.active_readers == 1
    clock[0] = 29.0
    channel.output.extend(ui())
    channel.changed.set()
    for _ in range(100):
        if channel.reads >= 3:
            break
        await asyncio.sleep(0)
    assert len(channel.writes) == 1 and not task.done()
    clock[0] = 30.0
    channel.output.extend(ui())
    channel.changed.set()
    report, launcher, _ = await asyncio.wait_for(task, 1)
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.OBSERVED
    assert report.request_writes == 2 and report.ui_records == 2
    assert report.mode_mismatch_reason is None
    assert report.classified_responses == 2
    assert launcher.joined and channel.max_readers == 1


async def test_ambiguous_mode_is_never_a_reload_retry():
    channel = Channel([response("@ID@", "Claude API")])
    started = time.monotonic()
    report, launcher, _ = await observe(channel, phase=maintenance.ClaudeMaintenancePhase.RELOAD)
    assert time.monotonic() - started < 1
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert report.mode_verdict is ClaudeInitializeVerdict.MODE_MISMATCH
    assert report.mode_mismatch_reason is ClaudeModeMismatchReason.AMBIGUOUS_API
    assert report.request_writes == 1 and launcher.joined


@pytest.mark.parametrize("plan", list(ClaudePlan))
@pytest.mark.parametrize("second,expected_verdict,expected_reason", [
    ("selected", "MODE_MATCH", None),
    ("ambiguous", "MODE_MISMATCH", "AMBIGUOUS_API"),
    ("different", "MODE_MISMATCH", "SUBSCRIPTION_MISMATCH"),
    ("credential", "MODE_MISMATCH", "CREDENTIAL_SOURCE_PRESENT"),
    ("invalid", "RESPONSE_INVALID", None),
    ("write-failed", "MODE_MISMATCH", "AMBIGUOUS_API"),
    ("read-failed", "MODE_MISMATCH", "AMBIGUOUS_API"),
])
async def test_reason_describes_last_classified_reply_after_second_write(
    monkeypatch, plan, second, expected_verdict, expected_reason,
):
    clock = [0.0]
    monkeypatch.setattr(maintenance, "_monotonic", lambda: clock[0])
    answers = {
        "selected": response("@ID@", plan.value, email="private-email"),
        "ambiguous": response("@ID@", "Claude API", organization="private-organization"),
        "different": response("@ID@", "private-plan"),
        "credential": response("@ID@", "Claude API", tokenSource="private-source"),
        "invalid": b'{"type":"private-invalid"}\n',
        "write-failed": response("@ID@", plan.value),
        "read-failed": b"private-partial",
    }

    class SecondWrite(Channel):
        def __init__(self, answers):
            super().__init__(answers)
            self.waiting = asyncio.Event()

        async def write(self, raw):
            await super().write(raw)
            if second == "write-failed" and len(self.writes) == 2:
                raise OSError("private write failure")

        async def read(self, maximum=8192):
            if second == "read-failed" and len(self.writes) == 2:
                raise OSError("private read failure")
            if len(self.writes) == 1 and not self.output:
                self.waiting.set()
            return await super().read(maximum)

    channel = SecondWrite([response("@ID@", "Claude API"), answers[second]])
    task = asyncio.create_task(observe(channel, timeout=120, plan=plan))
    await asyncio.wait_for(channel.waiting.wait(), 1)
    assert len(channel.writes) == 1 and channel.active_readers == 1
    clock[0] = 30.0
    channel.output.extend(ui())
    channel.changed.set()
    report, launcher, _ = await asyncio.wait_for(task, 1)
    assert report.request_writes == 2 and len(channel.writes) == 2
    assert report.classified_responses == (1 if second.endswith("failed") else 2)
    assert report.mode_verdict is ClaudeInitializeVerdict[expected_verdict]
    assert report.mode_mismatch_reason is (
        None if expected_reason is None else ClaudeModeMismatchReason[expected_reason]
    )
    assert report.lifecycle is (
        maintenance.ClaudeMaintenanceLifecycle.OBSERVED if second == "selected"
        else maintenance.ClaudeMaintenanceLifecycle.REFUSED
    )
    assert launcher.joined and channel.active_readers == 0
    assert "private" not in repr(report)


def test_legacy_mismatch_constructor_preserves_unknown_reason():
    report = maintenance.ClaudeMaintenanceObservation(
        maintenance.ClaudeMaintenancePhase.OBSERVE, ClaudeInitializeVerdict.MODE_MISMATCH,
        maintenance.ClaudeMaintenanceLifecycle.REFUSED, 1, 0, False, False,
    )
    assert report.mode_mismatch_reason is None
    assert report.classified_responses is None


@pytest.mark.parametrize("raw,expected", [(response("id"), "MODE_MATCH"),
                                         (b'{"type":"private-invalid"}\n', "RESPONSE_INVALID")])
async def test_response_state_clears_prior_reason_before_report_validation(raw, expected):
    callback = maintenance.ClaudeMaintenanceConversation(
        phase=maintenance.ClaudeMaintenancePhase.OBSERVE, selected_plan=ClaudePlan.PRO,
        input_limit=8192, output_limit=512 * 1024, deadline=maintenance._monotonic() + 5,
    )
    callback._state = "running"
    callback.request_writes = 1
    callback._records = [response("id", "Claude API")]
    assert (await callback._response("id"))[0] is False
    assert callback.mode_mismatch_reason is ClaudeModeMismatchReason.AMBIGUOUS_API
    assert callback.classified_responses == 1
    callback.request_writes = 2
    callback._records = [raw]
    if expected == "MODE_MATCH":
        assert (await callback._response("id"))[0] is True
    else:
        with pytest.raises(maintenance._Refused):
            await callback._response("id")
    assert callback.mode_verdict is ClaudeInitializeVerdict[expected]
    assert callback.mode_mismatch_reason is None
    assert callback.classified_responses == 2


async def test_cancelled_spacing_preserves_last_classified_facts_and_joins_reader():
    class SpacingChannel(Channel):
        def __init__(self):
            super().__init__([response("@ID@", "Claude API")])
            self.waiting = asyncio.Event()

        async def read(self, maximum=8192):
            if self.writes and not self.output:
                self.waiting.set()
            return await super().read(maximum)

    channel = SpacingChannel()
    callback = maintenance.ClaudeMaintenanceConversation(
        phase=maintenance.ClaudeMaintenancePhase.OBSERVE, selected_plan=ClaudePlan.PRO,
        input_limit=8192, output_limit=512 * 1024, deadline=maintenance._monotonic() + 120,
    )
    task = asyncio.create_task(callback(channel))
    await asyncio.wait_for(channel.waiting.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert callback.mode_verdict is ClaudeInitializeVerdict.MODE_MISMATCH
    assert callback.mode_mismatch_reason is ClaudeModeMismatchReason.AMBIGUOUS_API
    assert callback.classified_responses == callback.request_writes == 1
    assert callback._owner is None and channel.active_readers == 0 and channel.read_cancelled


@pytest.mark.parametrize("change", [
    {"mode_mismatch_reason": "private"}, {"classified_responses": None},
    {"classified_responses": True}, {"classified_responses": 0},
    {"classified_responses": -1}, {"classified_responses": 2},
    {"mode_mismatch_reason": None, "mode_verdict": None},
])
def test_diagnostic_constructor_requires_closed_reason_and_affirmative_count(change):
    values = {
        "phase": maintenance.ClaudeMaintenancePhase.OBSERVE,
        "mode_verdict": ClaudeInitializeVerdict.MODE_MISMATCH,
        "lifecycle": maintenance.ClaudeMaintenanceLifecycle.REFUSED,
        "request_writes": 1, "ui_records": 0, "stdin_closed": False, "eof": False,
        "mode_mismatch_reason": ClaudeModeMismatchReason.AMBIGUOUS_API,
        "classified_responses": 1,
    }
    values.update(change)
    with pytest.raises(ValueError, match=r"^invalid Claude maintenance observation$"):
        maintenance.ClaudeMaintenanceObservation(**values)


@pytest.mark.parametrize("verdict", [None, ClaudeInitializeVerdict.MODE_MATCH,
                                    ClaudeInitializeVerdict.RESPONSE_INVALID])
def test_reason_requires_a_mode_mismatch(verdict):
    with pytest.raises(ValueError, match=r"^invalid Claude maintenance observation$"):
        maintenance.ClaudeMaintenanceObservation(
            maintenance.ClaudeMaintenancePhase.OBSERVE, verdict,
            maintenance.ClaudeMaintenanceLifecycle.REFUSED, 1, 0, False, False,
            ClaudeModeMismatchReason.AMBIGUOUS_API, 1,
        )


def test_exact_ambiguous_shape_is_only_one_narrow_mismatch():
    raw = response("fixed-id", "Claude API", email="private", organization="private")
    assert maintenance.exact_ambiguous_api_mode(
        raw, expected_request_id="fixed-id", selected_plan=ClaudePlan.PRO,
    )
    for mutation in ("wrong-id", "provider", "key-source", "unknown", "missing-type",
                     "pending", "running", "wrong-plan", "wrong-version", "optional-type"):
        value = json.loads(raw)
        envelope = value["response"]
        body = envelope["response"]
        account = body["account"]
        if mutation == "wrong-id":
            envelope["request_id"] = "other"
        elif mutation == "provider":
            account["apiProvider"] = "bedrock"
        elif mutation == "key-source":
            account["apiKeySource"] = "secret"
        elif mutation == "unknown":
            account["unknown"] = "secret"
        elif mutation == "missing-type":
            del account["subscriptionType"]
        elif mutation == "pending":
            envelope["pending_user_dialog_requests"] = [{"prompt": "private"}]
        elif mutation == "running":
            body["session_state"] = "running"
        elif mutation == "wrong-plan":
            account["subscriptionType"] = "Claude Max"
        elif mutation == "optional-type":
            account["email"] = None
        else:
            body["claude_code_version"] = "other"
        changed = json.dumps(value, separators=(",", ":")).encode() + b"\n"
        assert not maintenance.exact_ambiguous_api_mode(
            changed, expected_request_id="fixed-id", selected_plan=ClaudePlan.PRO,
        ), mutation


@pytest.mark.parametrize("extra", [response("@ID@", "Claude API"),
                                     b'{"type":"control_request"}\n', b"partial"])
async def test_duplicate_callback_or_partial_during_spacing_defeats_second_write(extra):
    channel = Channel([response("@ID@", "Claude API") + extra])
    started = time.monotonic()
    report, _, _ = await observe(channel)
    assert time.monotonic() - started < 1
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert report.request_writes == 1


@pytest.mark.parametrize("extra", [response("@ID@"), b'{"type":"control_request"}\n',
                                     b"partial", ui()])
async def test_tail_after_positive_is_consumed_before_positive_report(extra):
    channel = Channel([response("@ID@") + extra])
    report, _, _ = await observe(channel)
    assert report.lifecycle is (
        maintenance.ClaudeMaintenanceLifecycle.OBSERVED if extra == ui()
        else maintenance.ClaudeMaintenanceLifecycle.REFUSED
    )
    assert report.request_writes == 1


async def test_ninth_ui_record_refuses_across_prefix_and_tail():
    channel = Channel([ui() * 4 + response("@ID@") + ui() * 5], fragment=1)
    report, _, _ = await observe(channel)
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert report.ui_records == 8 and report.request_writes == 1


async def test_ninth_ui_record_refuses_inside_conversation_before_report_validation():
    channel = Channel([ui() * 9 + response("@ID@")])
    callback = maintenance.ClaudeMaintenanceConversation(
        phase=maintenance.ClaudeMaintenancePhase.OBSERVE, selected_plan=ClaudePlan.PRO,
        input_limit=8192, output_limit=512 * 1024,
        deadline=maintenance._monotonic() + 5,
    )
    with pytest.raises(maintenance._Refused):
        await callback(channel)
    assert callback.ui_records == 8 and callback.request_writes == 1
    assert channel.active_readers == 0


async def test_cumulative_stdout_limit_binds_before_eighth_ui_record():
    large_ui = json.dumps({"type": "system", "subtype": "ui_invalidate", "event": "ui.render",
                           "uuid": "x", "session_id": "", "instances": [
                               {"surface": "x" * 90000, "component": "", "instance_id": ""},
                           ]}, separators=(",", ":")).encode() + b"\n"
    channel = Channel([large_ui * 6 + response("@ID@")])
    report, _, _ = await observe(channel)
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert report.ui_records == 5 and report.mode_verdict is None


async def test_record_ceiling_accepts_exact_ui_frame_and_refuses_next_byte():
    raw = json.dumps({"type": "system", "subtype": "ui_invalidate", "event": "ui.render",
                      "uuid": "x", "session_id": "", "instances": [
                          {"surface": "", "component": "", "instance_id": ""},
                      ]}, separators=(",", ":")).encode() + b"\n"
    padded = raw.replace(b'"surface":""',
                         b'"surface":"' + b"x" * (256 * 1024 - len(raw)) + b'"')
    assert len(padded) == 256 * 1024
    report, _, _ = await observe(Channel([padded + response("@ID@")], fragment=8191))
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.OBSERVED
    assert report.ui_records == 1
    oversized = padded.replace(b'"surface":"', b'"surface":"x', 1)
    report, _, _ = await observe(Channel([oversized + response("@ID@")], fragment=8191))
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert report.ui_records == 0 and report.mode_verdict is None


async def test_eof_during_spacing_refuses_without_a_second_write():
    class EarlyEOF(Channel):
        async def read(self, maximum=8192):
            if not self.output:
                return b""
            return await super().read(maximum)

    started = time.monotonic()
    report, _, _ = await observe(EarlyEOF([response("@ID@", "Claude API")]))
    assert time.monotonic() - started < 1
    assert report.mode_verdict is ClaudeInitializeVerdict.MODE_MISMATCH
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert report.request_writes == 1 and not report.stdin_closed and report.eof


async def test_spacing_early_eof_uses_typed_refusal_before_reader_assertion():
    callback = maintenance.ClaudeMaintenanceConversation(
        phase=maintenance.ClaudeMaintenancePhase.OBSERVE, selected_plan=ClaudePlan.PRO,
        input_limit=8192, output_limit=512 * 1024,
        deadline=maintenance._monotonic() + 120,
    )
    callback._state = "running"
    callback.eof = True
    caught: BaseException | None = None
    try:
        await callback._spacing(maintenance._monotonic())
    except BaseException as error:
        caught = error
    assert type(caught) is maintenance._Refused


@pytest.mark.parametrize("raw", [b"", response("@ID@")[:-1], b"partial-json"])
async def test_eof_before_complete_first_mode_never_triggers_retry(raw):
    class EarlyEOF(Channel):
        async def read(self, maximum=8192):
            if not self.output:
                return b""
            return await super().read(maximum)

    channel = EarlyEOF([raw])
    report, _, _ = await observe(channel)
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert report.mode_verdict is None and report.request_writes == 1
    assert len(channel.writes) == 1 and report.eof and not report.stdin_closed


@pytest.mark.parametrize("damage", ["type", "chunk-bound"])
async def test_reader_contract_damage_refuses_before_mode_parsing(damage):
    class DamagedRead(Channel):
        async def read(self, maximum=8192):
            if damage == "type":
                return bytearray(response("@ID@"))
            return b"x" * (maximum + 1)

    report, _, _ = await observe(DamagedRead([response("@ID@")]))
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert report.mode_verdict is None and report.request_writes == 1


async def test_reentry_poison_survives_await_and_cancels_owned_reader():
    class PausedWrite(Channel):
        def __init__(self):
            super().__init__([response("@ID@")])
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def write(self, raw):
            await super().write(raw)
            self.entered.set()
            await self.release.wait()

    channel = PausedWrite()
    callback = maintenance.ClaudeMaintenanceConversation(
        phase=maintenance.ClaudeMaintenancePhase.OBSERVE, selected_plan=ClaudePlan.PRO,
        input_limit=8192, output_limit=512 * 1024,
        deadline=maintenance._monotonic() + 5,
    )
    first = asyncio.create_task(callback(channel))
    await asyncio.wait_for(channel.entered.wait(), 1)
    with pytest.raises(ContractViolation):
        await callback(Channel([]))
    channel.release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(first, 1)
    assert callback._state == "refused" and channel.active_readers == 0
    assert len(channel.writes) == 1


async def test_reentry_wakes_owner_blocked_on_silent_read_and_joins_it():
    channel = Channel([])
    callback = maintenance.ClaudeMaintenanceConversation(
        phase=maintenance.ClaudeMaintenancePhase.OBSERVE, selected_plan=ClaudePlan.PRO,
        input_limit=8192, output_limit=512 * 1024,
        deadline=maintenance._monotonic() + 120,
    )
    first = asyncio.create_task(callback(channel))
    for _ in range(100):
        if channel.active_readers == 1 and len(channel.writes) == 1:
            break
        await asyncio.sleep(0)
    assert channel.active_readers == 1
    second = asyncio.create_task(callback(Channel([])))
    try:
        done, _ = await asyncio.wait({second}, timeout=0.1)
        assert second in done, "reentry must refuse a second caller promptly"
        with pytest.raises(ContractViolation):
            await second
        done, _ = await asyncio.wait({first}, timeout=0.1)
        assert first in done, "reentry must wake the silent reader owner promptly"
        with pytest.raises(asyncio.CancelledError):
            await first
    finally:
        for task in (first, second):
            if not task.done():
                task.cancel()
        await asyncio.wait({first, second}, timeout=0.2)
    assert callback._state == "refused"
    assert channel.active_readers == 0 and channel.read_cancelled
    assert len(channel.writes) == 1


@pytest.mark.parametrize("external_cancel", [False, True])
async def test_reentry_and_concurrent_external_cancel_remain_cancelled_after_join(
    external_cancel,
):
    channel = Channel([])
    launcher = Launcher(channel)
    binding = BindingCheck(digest("fake-claude-maintenance", 1, "same-object"))
    mount = ClaudeNativeStoreMount(17, 18, lambda: binding)
    task = asyncio.create_task(maintenance.observe_maintenance_mode(
        launcher, mount, phase=maintenance.ClaudeMaintenancePhase.OBSERVE,
        selected_plan=ClaudePlan.PRO, timeout_s=120,
    ))
    for _ in range(100):
        if channel.active_readers == 1 and launcher.calls:
            break
        await asyncio.sleep(0)
    assert channel.active_readers == 1
    callback = launcher.calls[0][1]["conversation"]
    with pytest.raises(ContractViolation):
        await callback(Channel([]))
    if external_cancel:
        task.cancel("private-external-cancellation")
    with pytest.raises(asyncio.CancelledError) as caught:
        await asyncio.wait_for(task, 1)
    assert str(caught.value) == "Claude maintenance cancelled"
    assert launcher.joined and channel.active_readers == 0 and channel.read_cancelled
    assert len(channel.writes) == 1


async def test_reentry_after_callback_completion_cannot_cancel_later_owner_work():
    callback = maintenance.ClaudeMaintenanceConversation(
        phase=maintenance.ClaudeMaintenancePhase.OBSERVE, selected_plan=ClaudePlan.PRO,
        input_limit=8192, output_limit=512 * 1024,
        deadline=maintenance._monotonic() + 5,
    )
    finished = asyncio.Event()
    release = asyncio.Event()

    async def owner() -> None:
        await callback(Channel([response("@ID@")]))
        finished.set()
        await release.wait()  # Not part of the callback's owned work.

    task = asyncio.create_task(owner())
    await asyncio.wait_for(finished.wait(), 1)
    assert callback._state == "completed" and callback._owner is None
    with pytest.raises(ContractViolation):
        await callback(Channel([]))
    assert not task.done() and not task.cancelling()
    release.set()
    await asyncio.wait_for(task, 1)


async def test_cancellation_during_spacing_joins_reader_without_second_write():
    channel = Channel([response("@ID@", "Claude API")])
    task = asyncio.create_task(observe(channel, timeout=120))
    for _ in range(100):
        if channel.reads >= 2:
            break
        await asyncio.sleep(0)
    task.cancel("private-cancellation")
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    assert str(caught.value) == "Claude maintenance cancelled"
    assert len(channel.writes) == 1 and channel.active_readers == 0
    assert channel.read_cancelled


async def test_uncertain_write_and_close_failure_never_retry_or_publish_mode():
    class FailedWrite(Channel):
        async def write(self, raw):
            await super().write(raw)
            raise OSError("private write failure after partial delivery")

    channel = FailedWrite([response("@ID@")])
    report, launcher, _ = await observe(channel)
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert report.mode_verdict is None and report.request_writes == 1
    assert len(channel.writes) == 1 and channel.active_readers == 0 and launcher.joined

    class FailedClose(Channel):
        async def close_stdin(self):
            raise OSError("private close failure")

    channel = FailedClose([response("@ID@")])
    report, launcher, _ = await observe(channel)
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert report.mode_verdict is ClaudeInitializeVerdict.MODE_MATCH
    assert not report.stdin_closed and len(channel.writes) == 1
    assert channel.active_readers == 0 and launcher.joined


async def test_cancellation_after_close_while_waiting_for_eof_joins_reader():
    class DelayedEOF(Channel):
        def __init__(self):
            super().__init__([response("@ID@")])
            self.waiting = asyncio.Event()
            self.release = asyncio.Event()

        async def read(self, maximum=8192):
            if self.closed and not self.output:
                self.waiting.set()
                await self.release.wait()
            return await super().read(maximum)

    channel = DelayedEOF()
    task = asyncio.create_task(observe(channel))
    await asyncio.wait_for(channel.waiting.wait(), 1)
    task.cancel("private-cancellation")
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    assert str(caught.value) == "Claude maintenance cancelled"
    assert channel.active_readers == 0 and len(channel.writes) == 1


async def test_second_request_needs_a_new_identifier_after_spacing(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(maintenance, "_monotonic", lambda: clock[0])
    monkeypatch.setattr(maintenance.secrets, "token_hex", lambda size: "same-id")
    channel = Channel([response("@ID@", "Claude API"), response("@ID@")])
    task = asyncio.create_task(observe(channel, timeout=120))
    for _ in range(100):
        if channel.reads >= 2:
            break
        await asyncio.sleep(0)
    clock[0] = 30.0
    channel.output.extend(ui())
    channel.changed.set()
    report, launcher, _ = await asyncio.wait_for(task, 1)
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert report.request_writes == 1 and len(channel.writes) == 1
    assert launcher.joined and channel.active_readers == 0


async def test_input_budget_refuses_before_unattempted_write(monkeypatch):
    first = Channel([response("@ID@")])
    report, _, _ = await observe(first, input_bytes=1)
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert report.request_writes == 0 and first.writes == []

    clock = [0.0]
    monkeypatch.setattr(maintenance, "_monotonic", lambda: clock[0])
    channel = Channel([response("@ID@", "Claude API"), response("@ID@")])
    budget = len(initialize_request("a" * 32)) + 1
    task = asyncio.create_task(observe(channel, timeout=120, input_bytes=budget))
    for _ in range(100):
        if channel.reads >= 2:
            break
        await asyncio.sleep(0)
    clock[0] = 30.0
    channel.output.extend(ui())
    channel.changed.set()
    report, _, _ = await asyncio.wait_for(task, 1)
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert report.request_writes == 1 and len(channel.writes) == 1


async def test_phase_and_absolute_lifetime_are_bounded_before_launch():
    launcher = Launcher(Channel([]))
    mount = ClaudeNativeStoreMount(17, 18, lambda: BindingCheck(
        digest("fake-claude-maintenance", 1, "same-object")))
    for timeout in (0, 120.001, float("inf"), True):
        with pytest.raises(ValueError):
            await maintenance.observe_maintenance_mode(
                launcher, mount, phase=maintenance.ClaudeMaintenancePhase.OBSERVE,
                selected_plan=ClaudePlan.PRO, timeout_s=timeout,
            )
    assert launcher.calls == []


async def test_initial_binding_must_be_affirmative_before_exchange():
    class ForbiddenLauncher(Launcher):
        async def exchange(self, command, **kwargs):
            pytest.fail("no process exchange after a non-binding initial check")

    launcher = ForbiddenLauncher(Channel([response("@ID@")]))
    calls = []

    def wrong_binding():
        calls.append(True)
        return "not-a-binding"

    mount = ClaudeNativeStoreMount(17, 18, wrong_binding)
    report = await maintenance.observe_maintenance_mode(
        launcher, mount, phase=maintenance.ClaudeMaintenancePhase.OBSERVE,
        selected_plan=ClaudePlan.PRO, timeout_s=5,
    )
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert calls == [True] and report.request_writes == 0


async def test_clean_process_without_entered_callback_is_not_mode_evidence():
    class SkippingLauncher(Launcher):
        async def exchange(self, command, **kwargs):
            kwargs["native_store"].before_spawn()
            self.joined = True
            return CLEAN

    launcher = SkippingLauncher(Channel([]))
    binding = BindingCheck(digest("fake-claude-maintenance", 1, "same-object"))
    mount = ClaudeNativeStoreMount(17, 18, lambda: binding)
    report = await maintenance.observe_maintenance_mode(
        launcher, mount, phase=maintenance.ClaudeMaintenancePhase.OBSERVE,
        selected_plan=ClaudePlan.PRO, timeout_s=5,
    )
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.INCOMPLETE
    assert report.mode_verdict is None and report.request_writes == 0


async def test_deadline_expiring_during_write_refuses_before_response(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(maintenance, "_monotonic", lambda: clock[0])

    class DelayedWrite(Channel):
        async def write(self, raw):
            await super().write(raw)
            clock[0] = 6.0

    channel = DelayedWrite([response("@ID@")])
    report, _, _ = await observe(channel, timeout=5)
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert report.request_writes == 1 and len(channel.writes) == 1
    assert report.mode_verdict is None and not report.stdin_closed


async def test_process_failure_and_changed_custody_demote_positive_mode():
    channel = Channel([response("@ID@")])
    report, _, _ = await observe(channel, result=replace(CLEAN, payload_returncode=1))
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.PROCESS_REFUSED
    assert report.mode_verdict is ClaudeInitializeVerdict.MODE_MATCH

    def changed(count):
        return BindingCheck(digest("fake-claude-maintenance", 1, str(count)))

    report, launcher, checked = await observe(Channel([response("@ID@")]), check=changed)
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert launcher.calls == [] and checked == [False, False, False]

    def changed_after_join(count):
        return BindingCheck(digest("fake-claude-maintenance", 1,
                                   "changed" if count == 3 else "initial"))

    report, launcher, checked = await observe(Channel([response("@ID@")]),
                                              check=changed_after_join)
    assert report.mode_verdict is ClaudeInitializeVerdict.MODE_MATCH
    assert report.lifecycle is maintenance.ClaudeMaintenanceLifecycle.REFUSED
    assert launcher.joined and checked == [False, False, True]


async def test_public_report_is_finite_and_contains_no_private_values():
    report, _, _ = await observe(Channel([response("@ID@")]))
    values = asdict(report)
    assert {field.name for field in fields(report)} == set(values)
    assert set(values) == {"phase", "mode_verdict", "mode_mismatch_reason", "classified_responses",
                           "lifecycle", "request_writes",
                           "ui_records", "stdin_closed", "eof"}
    assert all(type(value) in (maintenance.ClaudeMaintenancePhase,
                               ClaudeInitializeVerdict, maintenance.ClaudeMaintenanceLifecycle,
                               ClaudeModeMismatchReason,
                               bool, int, type(None)) for value in values.values())
    assert 0 <= values["request_writes"] <= 2 and 0 <= values["ui_records"] <= 8
    assert all(len(value.value.encode()) <= 32 for value in values.values()
               if hasattr(value, "value"))
    assert "private" not in repr(report) and "account" not in repr(report)


@pytest.mark.parametrize("change", [
    {"request_writes": 3}, {"request_writes": True}, {"ui_records": 9},
    {"ui_records": True}, {"stdin_closed": "yes"}, {"stdin_closed": False},
    {"eof": 1}, {"eof": False}, {"phase": "observe"},
    {"mode_verdict": "private"}, {"mode_verdict": None}, {"lifecycle": "observed"},
    {"mode_mismatch_reason": "private"},
    {"mode_mismatch_reason": ClaudeModeMismatchReason.AMBIGUOUS_API},
    {"classified_responses": True}, {"classified_responses": -1},
    {"classified_responses": 2}, {"classified_responses": 0},
    {"phase": maintenance.ClaudeMaintenancePhase.RELOAD, "request_writes": 2},
])
def test_report_constructor_refuses_unbounded_or_coerced_fields(change):
    values = {"phase": maintenance.ClaudeMaintenancePhase.OBSERVE,
              "mode_verdict": ClaudeInitializeVerdict.MODE_MATCH,
              "lifecycle": maintenance.ClaudeMaintenanceLifecycle.OBSERVED,
              "request_writes": 1, "ui_records": 8, "stdin_closed": True, "eof": True}
    values.update(change)
    with pytest.raises(ValueError):
        maintenance.ClaudeMaintenanceObservation(**values)
