"""Fake-first N6b owned byte lifecycle; no vendor, credentials or network."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors import claude_initialize as initialization
from constructicon.substrate.executors.claude_protocol import (
    RECORD_BYTES,
    ClaudeInitializeVerdict,
    ClaudePlan,
)
from constructicon.substrate.executors.linux import (
    DEFAULT_PROCESS_LIMITS,
    ProcessExchangeError,
    ProcessResult,
)

CLEAN = ProcessResult(0, b"secret-captured-output", b"secret-captured-error", 0.1,
                      payload_returncode=0)
COMMAND = ("fixed-nonvendor-script", "secret-command-not-published")


def response(request_id, *, plan="Claude Pro"):
    return json.dumps({"type": "control_response", "response": {
        "subtype": "success", "request_id": request_id,
        "response": {"account": {"apiProvider": "firstParty", "subscriptionType": plan,
                                   "email": "secret-account", "organization": "secret-org"},
                     "claude_code_version": "2.1.296", "session_state": "idle"},
        "pending_permission_requests": [], "pending_user_dialog_requests": [],
    }}, separators=(",", ":")).encode() + b"\n"


class ScriptedIO:
    def __init__(self, *, transform=None, fragment=8192, block=None, failure=None):
        self.transform = transform or (lambda data: data)
        self.fragment = fragment
        self.block = block
        self.failure = failure
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.output = bytearray()
        self.writes = []
        self.bounds = []
        self.reads = 0
        self.closed = False
        self.active = True

    async def seam(self, phase):
        if not self.active:
            raise ContractViolation("secret-invalidated-channel")
        if self.failure and self.failure[0] == phase:
            raise self.failure[1]
        if self.block == phase:
            self.entered.set()
            await self.release.wait()

    async def write(self, data):
        self.writes.append(data)  # Actual prefix can precede a failed/cancelled drain.
        request = json.loads(data)
        assert request == {"type": "control_request", "request_id": request["request_id"],
                           "request": {"subtype": "initialize"}}
        self.output.extend(self.transform(response(request["request_id"])))
        await self.seam("write")

    async def read(self, maximum=8192):
        self.bounds.append(maximum)
        assert 1 <= maximum <= 8192
        self.reads += 1
        await self.seam("drain" if self.closed else "read")
        size = min(maximum, self.fragment, len(self.output))
        data = bytes(self.output[:size])
        del self.output[:size]
        return data

    async def close_stdin(self):
        await self.seam("close")
        self.closed = True


class ScriptedLauncher:
    """Existing exchange contract's genuine fake; not a containment proof."""

    def __init__(self, io=None, *, result=CLEAN, error=None, join_block=False, input_bytes=None):
        self.io = io or ScriptedIO()
        self.result = result
        self.error = error
        self.join_block = join_block
        self.join_entered = asyncio.Event()
        self.join_release = asyncio.Event()
        self.joined = False
        self.calls = []
        self.conversation = None
        self.limits = DEFAULT_PROCESS_LIMITS if input_bytes is None else replace(
            DEFAULT_PROCESS_LIMITS, input_bytes=input_bytes,
        )

    async def exchange(self, command, **arguments):
        self.calls.append((command, arguments))
        self.conversation = arguments["conversation"]
        try:
            await self.conversation(self.io)
            if self.join_block:
                self.join_entered.set()
                await self.join_release.wait()
            if self.error is not None:
                raise self.error
            return self.result
        finally:
            self.io.active = False
            self.joined = True


async def observe(launcher, *, plan=ClaudePlan.PRO):
    return await initialization.observe_initialization(
        launcher, COMMAND, selected_plan=plan, guard_fds=(17,), timeout_s=5,
    )


@pytest.mark.parametrize("plan", list(ClaudePlan))
@pytest.mark.parametrize("fragment", [1, 7, 8192])
async def test_owned_initialization_accepts_selected_plan_fragmented_eof_and_clean_process(
    plan, fragment,
):
    io = ScriptedIO(fragment=fragment, transform=lambda data: data.replace(
        b"Claude Pro", plan.value.encode(),
    ))
    launcher = ScriptedLauncher(io)
    report = await observe(launcher, plan=plan)
    assert report.lifecycle is initialization.ClaudeLifecycleVerdict.INITIALIZATION_OBSERVED
    assert report.mode_verdict is ClaudeInitializeVerdict.MODE_MATCH
    assert launcher.joined and io.closed and not io.active
    assert len(io.writes) == 1 and len(launcher.calls) == 1
    command, arguments = launcher.calls[0]
    assert command == COMMAND and arguments["workspace"] is None
    assert arguments["posture"].value == "read" and arguments["guard_fds"] == (17,)
    assert arguments["timeout_s"] == 5 and "native_store" not in arguments


async def test_host_ids_are_fresh_opaque_and_not_a_caller_argument():
    one, two = ScriptedLauncher(), ScriptedLauncher()
    await observe(one)
    await observe(two)
    identifiers = [json.loads(world.io.writes[0])["request_id"] for world in (one, two)]
    assert identifiers[0] != identifiers[1]
    assert all(type(value) is str and len(value) == 32 for value in identifiers)


@pytest.mark.parametrize("transform", [
    lambda raw: raw.replace(b'"request_id":"', b'"request_id":"wrong-'),
    lambda raw: raw.replace(b"Claude Pro", b"Claude Max"),
    lambda raw: b'{"type":"control_request","secret":"prompt"}\n',
    lambda raw: b"secret-invalid-json\n",
], ids=["wrong-id", "wrong-plan", "callback", "malformed"])
async def test_nonmatching_or_unsolicited_reply_refuses_without_extra_request(transform):
    launcher = ScriptedLauncher(ScriptedIO(transform=transform))
    report = await observe(launcher)
    assert report.lifecycle is initialization.ClaudeLifecycleVerdict.REFUSED
    assert report.mode_verdict is not ClaudeInitializeVerdict.MODE_MATCH
    assert len(launcher.io.writes) == 1 and launcher.joined


@pytest.mark.parametrize("transform", [lambda raw: raw + raw, lambda raw: raw + b"x",
                                      lambda raw: raw + b"\n"],
                         ids=["duplicate", "partial-extra", "empty-extra-record"])
@pytest.mark.parametrize("fragment", [1, 8192])
async def test_any_extra_bytes_refuse_even_after_mode_match(transform, fragment):
    report = await observe(ScriptedLauncher(ScriptedIO(transform=transform, fragment=fragment)))
    assert report.mode_verdict is ClaudeInitializeVerdict.MODE_MATCH
    assert report.lifecycle is initialization.ClaudeLifecycleVerdict.REFUSED


@pytest.mark.parametrize("transform", [lambda raw: b"", lambda raw: raw[:-1],
                                      lambda raw: raw[:19], lambda raw: b"\xf0\x9f"],
                         ids=["empty-eof", "missing-lf", "partial-json", "partial-utf8"])
async def test_eof_before_complete_record_stays_incomplete_and_mode_unknown(transform):
    report = await observe(ScriptedLauncher(ScriptedIO(transform=transform)))
    assert report.mode_verdict is None
    assert report.lifecycle is initialization.ClaudeLifecycleVerdict.INCOMPLETE


async def test_full_record_ceiling_without_lf_refuses_immediately_without_read_zero():
    io = ScriptedIO(transform=lambda raw: b"x" * RECORD_BYTES)
    try:
        report = await observe(ScriptedLauncher(io))
    except ContractViolation:
        pytest.fail("a full bounded record must refuse without attempting an invalid read")
    assert report.lifecycle is initialization.ClaudeLifecycleVerdict.REFUSED
    assert sum(io.bounds) == RECORD_BYTES and min(io.bounds) > 0
    assert io.reads == RECORD_BYTES // 8192


async def test_matching_frame_at_exact_ceiling_is_accepted():
    def pad(raw):
        return raw[:-1] + b" " * (RECORD_BYTES - len(raw)) + b"\n"

    io = ScriptedIO(transform=pad)
    report = await observe(ScriptedLauncher(io))
    assert report.lifecycle is initialization.ClaudeLifecycleVerdict.INITIALIZATION_OBSERVED
    assert report.mode_verdict is ClaudeInitializeVerdict.MODE_MATCH
    assert max(io.bounds) <= 8192


async def test_actual_configured_input_bound_refuses_before_write():
    launcher = ScriptedLauncher(input_bytes=1)

    async def forbidden_write(_data):
        pytest.fail("the configured input bound must refuse before any channel write")

    launcher.io.write = forbidden_write
    report = await observe(launcher)
    assert report.lifecycle is initialization.ClaudeLifecycleVerdict.REFUSED
    assert report.mode_verdict is None and launcher.io.writes == []


@pytest.mark.parametrize("damage", ["oversized", "bytearray"])
async def test_channel_chunk_shape_and_requested_bound_refuse_without_crediting_mode(damage):
    class DamagedIO(ScriptedIO):
        async def read(self, maximum=8192):
            if self.closed:
                return b""
            raw = bytes(self.output)
            self.output.clear()
            if damage == "bytearray":
                return bytearray(raw)
            return raw[:-1] + b" " * (8193 - len(raw)) + b"\n"

    report = await observe(ScriptedLauncher(DamagedIO()))
    assert report.lifecycle is initialization.ClaudeLifecycleVerdict.REFUSED
    assert report.mode_verdict is None


@pytest.mark.parametrize("tail", [None, bytearray()])
async def test_only_actual_empty_bytes_close_eof(tail):
    class WrongEOF(ScriptedIO):
        async def read(self, maximum=8192):
            return tail if self.closed else await super().read(maximum)

    report = await observe(ScriptedLauncher(WrongEOF()))
    assert report.mode_verdict is ClaudeInitializeVerdict.MODE_MATCH
    assert report.lifecycle is initialization.ClaudeLifecycleVerdict.REFUSED


async def test_clean_peer_result_cannot_replace_aborted_callback_completion():
    class AbortingLauncher(ScriptedLauncher):
        async def exchange(self, command, **arguments):
            self.conversation = arguments["conversation"]
            task = asyncio.create_task(self.conversation(self.io))
            await asyncio.wait_for(self.io.entered.wait(), 1)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            self.io.active = False
            self.joined = True
            return CLEAN

    launcher = AbortingLauncher(ScriptedIO(block="drain"))
    report = await observe(launcher)
    assert launcher.joined and launcher.conversation._state == "incomplete"
    assert report.mode_verdict is ClaudeInitializeVerdict.MODE_MATCH
    assert report.lifecycle is initialization.ClaudeLifecycleVerdict.INCOMPLETE


async def test_clean_peer_result_with_unentered_callback_is_not_positive_evidence():
    class SkippingLauncher(ScriptedLauncher):
        async def exchange(self, command, **arguments):
            self.conversation = arguments["conversation"]
            self.joined = True
            return CLEAN

    launcher = SkippingLauncher()
    report = await observe(launcher)
    assert launcher.conversation._state == "new" and launcher.io.writes == []
    assert report.mode_verdict is None
    assert report.lifecycle is initialization.ClaudeLifecycleVerdict.INCOMPLETE


async def test_callback_mode_refusal_is_latched_before_close_or_completion():
    conversation = initialization.ClaudeInitialization(selected_plan=ClaudePlan.PRO,
                                                       input_limit=1000)
    io = ScriptedIO(transform=lambda raw: raw.replace(b"Claude Pro", b"Claude Max"))
    await conversation(io)
    assert conversation._mode is ClaudeInitializeVerdict.MODE_MISMATCH
    assert conversation._state == "refused" and not io.closed


@pytest.mark.parametrize("phase", ["write", "read", "close", "drain"])
async def test_channel_failures_are_static_after_owned_join_not_retried(phase):
    launcher = ScriptedLauncher(ScriptedIO(failure=(phase, OSError("secret-channel-error"))))
    with pytest.raises(ContractViolation) as caught:
        await observe(launcher)
    assert str(caught.value) == "Claude initialization launch failed"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert launcher.joined and not launcher.io.active
    assert len(launcher.io.writes) == 1
    assert launcher.conversation._state != "completed"


@pytest.mark.parametrize("phase", ["write", "read", "close", "drain", "join"])
async def test_cancellation_at_every_await_cannot_publish_or_retry(phase):
    launcher = ScriptedLauncher(ScriptedIO(block=phase), join_block=phase == "join")
    task = asyncio.create_task(observe(launcher))
    entered = launcher.join_entered if phase == "join" else launcher.io.entered
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel("secret-cancel-message")
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    assert str(caught.value) == "Claude initialization cancelled"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert launcher.joined and not launcher.io.active
    assert len(launcher.io.writes) == 1
    assert launcher.conversation._state == ("completed" if phase == "join" else "incomplete")


@pytest.mark.parametrize("phase", ["write", "read", "close", "drain"])
async def test_overlapping_reentry_poison_cannot_be_overwritten_after_resume(phase):
    conversation = initialization.ClaudeInitialization(selected_plan=ClaudePlan.PRO,
                                                       input_limit=DEFAULT_PROCESS_LIMITS.input_bytes)
    io = ScriptedIO(block=phase)
    first = asyncio.create_task(conversation(io))
    await asyncio.wait_for(io.entered.wait(), 1)
    other = ScriptedIO()
    try:
        with pytest.raises(ContractViolation):
            await conversation(other)
    finally:
        io.release.set()
        await asyncio.wait_for(first, 1)
    assert conversation._state == "refused"
    assert other.writes == [] and len(io.writes) == 1


async def test_completed_conversation_reentry_has_no_second_write_or_reused_success():
    conversation = initialization.ClaudeInitialization(selected_plan=ClaudePlan.PRO,
                                                       input_limit=DEFAULT_PROCESS_LIMITS.input_bytes)
    await conversation(ScriptedIO())
    assert conversation._state == "completed"
    second = ScriptedIO()
    with pytest.raises(ContractViolation):
        await conversation(second)
    assert conversation._state == "refused" and second.writes == []


@pytest.mark.parametrize("changes", [
    {"returncode": 1}, {"payload_returncode": 1}, {"payload_returncode": None},
    {"returncode": False}, {"payload_returncode": False}, {"timed_out": True},
    {"timed_out": None}, {"bound_exceeded": "stdout"},
], ids=["supervisor", "payload", "unknown-payload", "bool-supervisor", "bool-payload",
        "timeout", "unknown-timeout", "bound"])
async def test_mode_and_eof_do_not_replace_exact_clean_process_evidence(changes):
    report = await observe(ScriptedLauncher(result=replace(CLEAN, **changes)))
    assert report.mode_verdict is ClaudeInitializeVerdict.MODE_MATCH
    assert report.lifecycle is initialization.ClaudeLifecycleVerdict.PROCESS_REFUSED


@pytest.mark.parametrize("error", [
    ProcessExchangeError(CLEAN), ValueError("secret-setup"), OSError("secret-cleanup"),
    ExceptionGroup("secret-group", [ValueError("secret-inner"), OSError("secret-inner-2")]),
], ids=["private-result", "setup", "cleanup", "ordinary-group"])
async def test_failed_launch_never_forwards_private_exception_result_or_chain(error):
    error.__cause__ = ValueError("secret-cause")
    launcher = ScriptedLauncher(error=error)
    with pytest.raises(ContractViolation) as caught:
        await observe(launcher)
    assert str(caught.value) == "Claude initialization launch failed"
    assert caught.value is not error and not hasattr(caught.value, "result")
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert launcher.joined


@pytest.mark.parametrize("nested", [False, True])
async def test_mixed_cancellation_group_is_cancelled_not_normalized_to_report(nested):
    cancellation = asyncio.CancelledError("secret-cancel")
    errors = [ValueError("secret-cleanup"), cancellation]
    if nested:
        errors = [BaseExceptionGroup("secret-inner-group", errors)]
    error = BaseExceptionGroup("secret-outer-group", errors)
    launcher = ScriptedLauncher(error=error)
    caught = None
    try:
        await observe(launcher)
    except BaseException as error_observed:
        caught = error_observed
    assert type(caught) is asyncio.CancelledError  # Public error category is part of its contract.
    assert str(caught) == "Claude initialization cancelled"
    assert caught.__cause__ is None and caught.__context__ is None
    assert launcher.joined


async def test_direct_cancellation_private_cause_is_not_forwarded():
    original = asyncio.CancelledError("secret-original-cancel")
    original.__cause__ = ValueError("secret-private-cause")
    with pytest.raises(asyncio.CancelledError) as caught:
        await observe(ScriptedLauncher(error=original))
    assert caught.value is not original and str(caught.value) == "Claude initialization cancelled"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


async def test_fatal_noncancellation_groups_are_not_converted_to_operational_report():
    original = BaseExceptionGroup("operator interruption", [KeyboardInterrupt("operator stop")])
    caught = None
    try:
        await observe(ScriptedLauncher(error=original))
    except BaseException as error_observed:
        caught = error_observed
    assert caught is original


def test_ordinary_failure_is_not_cancellation():
    assert initialization._cancelled(ValueError("private-error")) is False


def test_process_evidence_must_be_actual_contract_type():
    class OtherResult:
        returncode = 0
        payload_returncode = 0
        timed_out = False
        bound_exceeded = None

    assert initialization._clean(OtherResult()) is False


async def test_all_public_report_fields_are_bounded_static_and_frozen():
    report = await observe(ScriptedLauncher())
    assert set(asdict(report)) == {"mode_verdict", "lifecycle"}
    assert all(type(value) in (ClaudeInitializeVerdict, initialization.ClaudeLifecycleVerdict)
               for value in asdict(report).values())
    assert all(len(value.value.encode()) <= 24 for value in asdict(report).values())
    assert "secret" not in json.dumps(asdict(report))
    with pytest.raises(FrozenInstanceError):
        report.lifecycle = initialization.ClaudeLifecycleVerdict.REFUSED


@pytest.mark.parametrize("mode", [None, ClaudeInitializeVerdict.MODE_MISMATCH, "secret-mode"])
def test_affirmative_report_requires_typed_mode_match(mode):
    with pytest.raises(ValueError):
        initialization.ClaudeInitializationObservation(
            mode_verdict=mode,
            lifecycle=initialization.ClaudeLifecycleVerdict.INITIALIZATION_OBSERVED,
        )


@pytest.mark.parametrize("limit", [None, True, 0, -1, 1.5])
def test_callback_input_budget_is_exact_positive_integer(limit):
    with pytest.raises(ValueError, match="invalid Claude initialization parameters"):
        initialization.ClaudeInitialization(selected_plan=ClaudePlan.PRO, input_limit=limit)


@pytest.mark.parametrize("plan", [None, True, "Claude Pro"])
def test_callback_selected_plan_is_exact_host_enum(plan):
    with pytest.raises(ValueError, match="invalid Claude initialization parameters"):
        initialization.ClaudeInitialization(selected_plan=plan, input_limit=100)


@pytest.mark.parametrize("field", ["mode_verdict", "lifecycle"])
def test_observation_fields_refuse_unbounded_or_coerced_values(field):
    values = {"mode_verdict": ClaudeInitializeVerdict.MODE_MATCH,
              "lifecycle": initialization.ClaudeLifecycleVerdict.REFUSED}
    values[field] = "secret-unbounded-fact" * 1000
    with pytest.raises(ValueError):
        initialization.ClaudeInitializationObservation(**values)


@pytest.mark.parametrize(("mode", "lifecycle"), [
    (None, "INCOMPLETE"), (None, "REFUSED"), (None, "PROCESS_REFUSED"),
    (ClaudeInitializeVerdict.MODE_MATCH, "INCOMPLETE"),
    (ClaudeInitializeVerdict.MODE_MATCH, "PROCESS_REFUSED"),
    (ClaudeInitializeVerdict.MODE_MISMATCH, "REFUSED"),
])
def test_finite_unknown_partial_and_refusal_observations_remain_permitted(mode, lifecycle):
    report = initialization.ClaudeInitializationObservation(
        mode_verdict=mode, lifecycle=initialization.ClaudeLifecycleVerdict[lifecycle],
    )
    assert report.mode_verdict is mode and report.lifecycle.name == lifecycle
