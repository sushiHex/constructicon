"""Credential-free diagnostic facts, never subscription or startup admission."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.ci import observe_m8_claude_startup as diagnostic

from constructicon.core.identity import Digest, digest
from constructicon.substrate.executors.claude_native import (
    ClaudeNativeStoreMount,
    ClaudeNativeVendor,
)
from constructicon.substrate.executors.claude_protocol import RECORD_BYTES
from constructicon.substrate.executors.linux import (
    DEFAULT_PROCESS_LIMITS,
    LinuxLauncher,
    ProcessResult,
)
from constructicon.substrate.executors.operator_store import BindingCheck
from tests.substrate.test_claude_native_read import wire_peer as wire_peer
from tests.substrate.test_native_codex_mediation import write_evidence


def response(identifier, *, mode="noauth"):
    account = {"apiProvider": "firstParty", "tokenSource": "none"}
    if mode == "subscription":
        account = {"apiProvider": "firstParty", "subscriptionType": "Claude Pro"}
    return json.dumps({"type": "control_response", "response": {
        "subtype": "success", "request_id": identifier,
        "response": {"claude_code_version": "2.1.296", "session_state": "idle",
                     "account": account, "models": [{"private": "unpublished-model-metadata"}]},
        "pending_permission_requests": [], "pending_user_dialog_requests": [],
    }}, separators=(",", ":")).encode() + b"\n"


class Channel:
    def __init__(self, transform=lambda raw: raw, *, fragment=8192, fault=None):
        self.transform, self.fragment, self.fault = transform, fragment, fault
        self.output = bytearray()
        self.writes = []
        self.closed = False
        self.close_attempts = 0
        self.entered = asyncio.Event()

    async def seam(self, stage):
        if self.fault == stage:
            raise OSError("private native failure")
        if self.fault == "block-" + stage:
            self.entered.set()
            await asyncio.Future()

    async def write(self, raw):
        self.writes.append(raw)
        value = json.loads(raw)
        assert value == {"type": "control_request", "request_id": value["request_id"],
                         "request": {"subtype": "initialize"}}
        self.output.extend(self.transform(response(value["request_id"])))
        await self.seam("write")

    async def read(self, maximum=8192):
        assert 1 <= maximum <= 8192
        await self.seam("tail" if self.closed else "read")
        size = min(maximum, self.fragment, len(self.output))
        value = bytes(self.output[:size])
        del self.output[:size]
        return value

    async def close_stdin(self):
        self.close_attempts += 1
        await self.seam("close")
        self.closed = True


class Launcher:
    def __init__(self, channel=None, *, result=None, error=None):
        self.claude = ClaudeNativeVendor(Path("/fixed"), "fixture-startup", "low",
                                        digest("diagnostic-test", 1, "vendor"))
        self.limits = DEFAULT_PROCESS_LIMITS
        self.channel = channel or Channel()
        self.result = result or ProcessResult(0, b"private stdout", b"private stderr", .1,
                                             payload_returncode=0)
        self.error = error
        self.joined = self.spawned = False

    async def exchange(self, command, **arguments):
        assert command == self.claude.command and arguments["workspace"] is None
        assert arguments["posture"].value == "read" and arguments["guard_fds"] == (42,)
        try:
            await asyncio.sleep(0)
            arguments["native_store"].before_spawn()
            self.spawned = True
            await arguments["conversation"](self.channel)
            if self.error is not None:
                raise self.error
            return self.result
        finally:
            self.joined = True


async def observe(launcher, *, values=None, timeout=1):
    checked = []
    initial = BindingCheck(digest("diagnostic-test", 1, "binding"))

    def check():
        checked.append(launcher.joined)
        return initial if values is None else values[len(checked) - 1]

    mount = ClaudeNativeStoreMount(42, 43, check)
    report = await diagnostic.observe_startup(launcher, mount, timeout_s=timeout)
    assert mount.before_spawn is check
    return report, checked


def ui_record(**changes):
    value = {"type": "system", "subtype": "ui_invalidate", "event": "ui.render",
             "uuid": "private arbitrary non-UUID", "session_id": ""}
    value.update(changes)
    return json.dumps(value, separators=(",", ":")).encode() + b"\n"


@pytest.mark.parametrize("fragment", [1, 8192])
@pytest.mark.parametrize("prefix,tail", [(0, 0), (8, 0), (0, 8), (4, 4)])
@pytest.mark.parametrize("coalesced", [False, True])
async def test_only_exact_ui_records_share_one_budget_across_response_and_eof(
    fragment, prefix, tail, coalesced,
):
    ui = ui_record(instances=[{"surface": "private", "component": "", "instance_id": "任意"}])
    channel = Channel(lambda raw: ui * prefix + raw + (ui * tail if coalesced else b""),
                      fragment=fragment)
    original_close = channel.close_stdin

    async def close():
        await original_close()
        if not coalesced:
            channel.output.extend(ui * tail)

    channel.close_stdin = close
    report, checked = await observe(Launcher(channel))
    assert diagnostic.successful(report), report
    assert report["accepted_ui_records"] == prefix + tail
    assert channel.close_attempts == 1 and len(channel.writes) == 1
    assert checked == [False, False, True] and report["eof"] is True
    assert "private" not in json.dumps(report) and "任意" not in json.dumps(report)
    assert_report(report)


@pytest.mark.parametrize("fragment", [1, 8192])
@pytest.mark.parametrize("case", ["ui-only", "ninth-prefix", "ninth-tail", "ninth-split",
                                    "partial-ui", "duplicate", "callback", "other-system"])
async def test_ui_framing_never_substitutes_for_response_or_resets_budget(case, fragment):
    ui = ui_record()

    def transform(raw):
        return {"ui-only": ui * 8, "ninth-prefix": ui * 9 + raw,
                "ninth-tail": raw + ui * 9, "ninth-split": ui * 4 + raw + ui * 5,
                "partial-ui": raw + ui[:-1], "duplicate": raw + raw,
                "callback": ui + b'{"type":"control_request"}\n' + raw,
                "other-system": ui + b'{"type":"system","subtype":"ui_status"}\n' + raw}[case]

    launcher = Launcher(Channel(transform, fragment=fragment))
    report, _ = await observe(launcher)
    assert not diagnostic.successful(report), report
    assert report["protocol"] == ("incomplete" if case == "ui-only" else "invalid")
    assert report["accepted_ui_records"] == (8 if case.startswith("ninth") or case == "ui-only"
                                              else 1 if case in {"callback", "other-system"}
                                              else 0)
    assert report["protocol_reason"] == (
        "eof-before-frame" if case == "ui-only" else "ui-bound" if case.startswith("ninth")
        else "unexpected-control-request" if case == "callback"
        else "system-ui_status" if case == "other-system" else "extra-output"
    )
    assert launcher.channel.close_attempts == 1 and launcher.joined
    assert_report(report)


@pytest.mark.parametrize("case", ["missing-event", "extra", "event", "uuid", "session",
                                    "instances-type", "entry-type", "entry-extra", "entry-missing",
                                    "surface", "component", "instance-id"])
async def test_ui_schema_is_exact_and_refused_stream_is_never_reparsed(case, monkeypatch):
    value = json.loads(ui_record(instances=[{"surface": "private", "component": "private",
                                            "instance_id": "private"}]))
    if case == "missing-event":
        del value["event"]
    elif case == "extra":
        value["private"] = []
    elif case in {"event", "uuid", "session"}:
        value[{"session": "session_id"}.get(case, case)] = (
            "private.event" if case == "event" else ["private"])
    elif case == "instances-type":
        value["instances"] = {}
    elif case == "entry-type":
        value["instances"] = [7]
    elif case == "entry-extra":
        value["instances"][0]["private"] = "private"
    elif case == "entry-missing":
        del value["instances"][0]["surface"]
    else:
        value["instances"][0][{"instance-id": "instance_id"}.get(case, case)] = 7
    first = json.dumps(value, separators=(",", ":")).encode() + b"\n"
    seen = []
    original = diagnostic.classify

    def classify(record, identifier):
        seen.append(record)
        return original(record, identifier)

    monkeypatch.setattr(diagnostic, "classify", classify)
    report, _ = await observe(Launcher(Channel(lambda raw: first + ui_record() + raw)))
    assert report["protocol"] == "invalid" and report["protocol_reason"] == "ui-shape"
    assert report["accepted_ui_records"] == 0 and seen == [first]
    assert not diagnostic.successful(report) and report["eof"] is True
    assert "private" not in json.dumps(report)
    assert_report(report)


@pytest.mark.parametrize("stage", ["write", "read", "close", "tail", "eof"])
@pytest.mark.parametrize("coalesced", [False, True])
async def test_reentry_poison_survives_every_resume_and_buffered_frame(stage, coalesced):
    channel = Channel(lambda raw: ui_record() + raw + (ui_record() if coalesced else b""))
    probe = diagnostic._Probe(deadline=asyncio.get_running_loop().time() + 2,
                              input_limit=8192, output_limit=RECORD_BYTES)
    fired, recursive_failure = [], []
    original_close = channel.close_stdin

    async def close():
        await original_close()
        channel.output.extend(ui_record())

    channel.close_stdin = close

    async def seam(current):
        actual = "eof" if current == "tail" and not channel.output else current
        if actual == stage and not fired:
            fired.append(True)
            try:
                await probe(channel)
            except BaseException as error:
                recursive_failure.append(error)

    channel.seam = seam
    failure = None
    try:
        await probe(channel)
    except BaseException as error:
        failure = error
    assert fired and len(recursive_failure) == 1
    assert isinstance(recursive_failure[0], diagnostic._Refused)
    assert isinstance(failure, diagnostic._Refused)
    assert probe.protocol == "invalid" and probe.reason == "single-use"
    assert not probe.eof and len(channel.writes) == 1
    assert channel.close_attempts == int(stage in {"close", "tail", "eof"})


async def test_first_protocol_refusal_survives_opaque_drain_bound():
    channel = Channel(lambda raw: raw.replace(b"2.1.296", b"2.1.295") + b"x" * 100,
                      fragment=1)
    launcher = Launcher(channel)
    launcher.limits = replace(launcher.limits, stdout_bytes=len(response("0" * 32)) + 10)
    report, _ = await observe(launcher)
    assert report["protocol_reason"] == "version-mismatch"
    assert report["protocol"] == "invalid" and report["lifecycle"] == "failed"
    assert not diagnostic.successful(report) and launcher.joined
    assert_report(report)


@pytest.mark.parametrize("stage", ["write", "read", "close", "tail", "eof"])
async def test_ui_framing_cancellation_joins_without_another_protocol_operation(stage):
    channel = Channel(lambda raw: ui_record() + raw + ui_record())
    entered, operations = asyncio.Event(), []
    original_close = channel.close_stdin

    async def close():
        await original_close()
        channel.output.extend(ui_record())

    async def seam(current):
        actual = "eof" if current == "tail" and not channel.output else current
        operations.append(actual)
        if actual == stage:
            entered.set()
            await asyncio.Future()

    channel.close_stdin, channel.seam = close, seam
    launcher = Launcher(channel)
    task = asyncio.create_task(observe(launcher))
    await asyncio.wait_for(entered.wait(), 1)
    suspended = list(operations)
    task.cancel()
    failure = None
    try:
        await task
    except BaseException as error:
        failure = error
    assert isinstance(failure, asyncio.CancelledError)
    assert launcher.joined and operations == suspended
    assert len(channel.writes) == 1
    assert channel.close_attempts == int(stage in {"close", "tail", "eof"})


@pytest.mark.parametrize("tail", [False, True])
async def test_ui_record_and_cumulative_bounds_bind_without_publishing_private_fields(tail):
    ui = ui_record(uuid="private" + "x" * RECORD_BYTES)
    report, _ = await observe(Launcher(Channel(lambda raw: (raw + ui) if tail else (ui + raw))))
    assert report["protocol"] == "invalid" and report["protocol_reason"] == "record-bound"
    assert report["accepted_ui_records"] == 0 and not diagnostic.successful(report)
    assert "private" not in json.dumps(report)
    assert_report(report)
    # Each record fits; the combined stream exceeds the existing cumulative cap.
    ui = ui_record(uuid="private" + "x" * (RECORD_BYTES // 2))
    report, _ = await observe(Launcher(Channel(lambda raw: ui * 8 + raw)))
    assert report["protocol"] == "invalid" and report["protocol_reason"] == "output-bound"
    assert not diagnostic.successful(report) and 0 < report["accepted_ui_records"] < 8
    assert_report(report)


@pytest.mark.parametrize("fragment", [1, 7, 8192])
@pytest.mark.parametrize("damage,reason", [("none", "none"), ("version", "version-mismatch"),
                                           ("extra", "extra-output"),
                                           ("version-extra", "version-mismatch")])
async def test_protocol_reason_is_fragmentation_stable_within_output_budget(
    damage, reason, fragment,
):
    def transform(raw):
        if damage.startswith("version"):
            raw = raw.replace(b"2.1.296", b"2.1.295")
        return raw + b"private surplus\n" if "extra" in damage else raw

    report, _ = await observe(Launcher(Channel(transform, fragment=fragment)))
    assert "protocol_reason" in report
    assert report["protocol_reason"] == reason
    assert diagnostic.successful(report) is (damage == "none")
    assert "private" not in json.dumps(report)
    assert_report(report)


@pytest.mark.parametrize("fragment,reason", [(1, "version-mismatch"), (8192, "output-bound")])
async def test_output_bound_precedes_parsing_a_whole_overbudget_read(fragment, reason):
    channel = Channel(lambda raw: raw.replace(b"2.1.296", b"2.1.295") + b"x" * 100,
                      fragment=fragment)
    launcher = Launcher(channel)
    launcher.limits = replace(launcher.limits, stdout_bytes=len(response("0" * 32)) + 10)
    report, checked = await observe(launcher)
    assert not diagnostic.successful(report)
    assert report["protocol"] == "invalid" and report["protocol_reason"] == reason
    assert report["lifecycle"] == "failed"
    assert launcher.joined and checked == [False, False, True]
    assert_report(report)


SOURCE_SYSTEM_SUBTYPES = frozenset({
    "agents_killed", "api_error", "api_retry", "away_summary", "background_tasks_changed",
    "bridge_state", "bridge_status", "cloud_session_delta", "cloud_session_status",
    "code_change_published", "commands_changed", "compact_boundary", "control_request_progress",
    "dev_intent", "elicitation_complete", "feedback_draft_queued", "file_attachments_missing",
    "file_snapshot", "files_persisted", "hook_progress", "hook_response", "hook_started",
    "informational", "init", "init_milestone", "instruction_size_warning", "local_command",
    "local_command_output", "memory_recall", "memory_saved", "mirror_error",
    "model_consent_fallback", "model_fallback", "model_refusal_fallback",
    "model_refusal_no_fallback", "notification", "peer_message_hold", "per_turn_effort_changed",
    "permission_check_status", "permission_denied", "permission_retry", "plugin_install",
    "post_turn_summary", "scheduled_task_fire", "session_metadata", "session_state_changed",
    "session_title_changed", "status", "stop_hook_summary", "task_notification", "task_progress",
    "task_started", "task_summary", "task_updated", "thinking", "thinking_tokens",
    "tool_host_result", "turn_duration", "turn_handoff_available", "turn_preempted",
    "turn_starting", "ui_focus", "ui_invalidate", "ui_log", "ui_panes", "ui_scroll", "ui_status",
    "ui_toast", "upgrade_relay_marker", "vcs_state_changed", "worker_shutting_down",
    "workflow_launch_result",
})
LEGACY_SYSTEM_REASONS = {
    "init": "unexpected-system-init", "notification": "unexpected-system-notification",
    "status": "unexpected-system-status", "session_state_changed": "unexpected-system-state",
    "hook_started": "unexpected-system-hook-started",
    "hook_progress": "unexpected-system-hook-progress",
    "hook_response": "unexpected-system-hook-response",
    "session_metadata": "unexpected-system-metadata",
}


@pytest.mark.parametrize("fragment", [1, 8192])
@pytest.mark.parametrize("subtype", sorted(SOURCE_SYSTEM_SUBTYPES))
async def test_all_source_literal_system_subtypes_remain_closed_refusals(subtype, fragment):
    assert len(SOURCE_SYSTEM_SUBTYPES) == 72
    frame = {"type": "system", "subtype": subtype, "text": "private text",
             "account": {"private": "metadata"}}
    first = json.dumps(frame, separators=(",", ":")).encode() + b"\n"
    launcher = Launcher(Channel(lambda raw: first + raw, fragment=fragment))
    report, _ = await observe(launcher)
    assert report["protocol"] == "invalid"
    assert report["protocol_reason"] == (
        "ui-shape" if subtype == "ui_invalidate"
        else LEGACY_SYSTEM_REASONS.get(subtype, "system-" + subtype)
    )
    assert diagnostic.SYSTEM_SUBTYPES == SOURCE_SYSTEM_SUBTYPES
    assert type(diagnostic.SYSTEM_SUBTYPES) is frozenset
    assert not diagnostic.successful(report)  # The following valid reply cannot authorize.
    assert report["request_writes"] == 1 and launcher.channel.close_attempts == 1
    assert report["eof"] is True and launcher.joined
    assert "private" not in json.dumps(report)
    assert_report(report)


@pytest.mark.parametrize("fragment", [1, 8192])
@pytest.mark.parametrize("case", [
    "init", "notification", "status", "session_state_changed", "hook_started", "hook_progress",
    "hook_response", "session_metadata", "model-effort-cap", "model-context-window",
    "missing-subtype", "private-subtype", "list-subtype", "dict-subtype", "null-subtype",
    "int-subtype", "unlisted-subtype", "private-key",
    "list-key", "dict-key", "missing-key", "key-outside-notification",
])
async def test_system_discriminators_are_finite_refusals_not_skipped_frames(case, fragment):
    reasons = {
        "init": "unexpected-system-init", "notification": "unexpected-system-notification",
        "status": "unexpected-system-status", "session_state_changed": "unexpected-system-state",
        "hook_started": "unexpected-system-hook-started",
        "hook_progress": "unexpected-system-hook-progress",
        "hook_response": "unexpected-system-hook-response",
        "session_metadata": "unexpected-system-metadata",
        "model-effort-cap": "system-model-effort-warning",
        "model-context-window": "system-model-context-warning",
    }
    frame = {"type": "system", "text": "private text", "account": {"private": "metadata"}}
    if case in {"model-effort-cap", "model-context-window"}:
        frame.update(subtype="notification", key=case)
        reason = reasons[case]
    elif case in reasons:
        frame["subtype"] = case
        reason = reasons[case]
    elif case in {"private-key", "list-key", "dict-key", "missing-key"}:
        frame["subtype"] = "notification"
        if case != "missing-key":
            frame["key"] = {"private-key": "private arbitrary key" * 8,
                            "list-key": ["private"], "dict-key": {"private": []}}[case]
        reason = "unexpected-system-notification"
    elif case == "key-outside-notification":
        frame.update(subtype="init", key="model-effort-cap")
        reason = "unexpected-system-init"
    else:
        if case != "missing-subtype":
            frame["subtype"] = {"private-subtype": "private arbitrary subtype" * 8,
                                "list-subtype": ["private"], "dict-subtype": {"private": []},
                                "null-subtype": None, "int-subtype": 7,
                                "unlisted-subtype": "not_in_source"}[case]
        reason = ("system-subtype-missing" if case == "missing-subtype"
                  else "system-subtype-unlisted" if case in {"private-subtype", "unlisted-subtype"}
                  else "system-subtype-nonstr")
    first = json.dumps(frame, separators=(",", ":")).encode() + b"\n"
    launcher = Launcher(Channel(lambda raw: first + raw, fragment=fragment))
    report, _ = await observe(launcher)
    assert report["protocol"] == "invalid" and report["protocol_reason"] == reason
    assert not diagnostic.successful(report)  # A later valid initialize is never accepted.
    assert report["request_writes"] == 1 and launcher.channel.close_attempts == 1
    assert report["eof"] is True and launcher.joined
    assert "private" not in json.dumps(report)
    assert_report(report)


@pytest.mark.parametrize("fragment", [1, 7, 8192])
async def test_exact_noauth_observation_requires_close_eof_join_and_three_bindings(fragment):
    launcher = Launcher(Channel(fragment=fragment))
    report, checked = await observe(launcher)
    assert diagnostic.successful(report)
    assert report["protocol"] == "correlated-noauth" and report["lifecycle"] == "clean"
    assert report["stdin_closed"] is True and report["eof"] is True
    assert report["request_writes"] == 1 and report["binding_checks"] == 3
    assert checked == [False, False, True] and launcher.joined
    assert launcher.channel.close_attempts == 1
    assert report["production_available"] is report["subscription_qualified"] is False
    assert report["claude_qualified"] is False
    assert "private" not in json.dumps(report) and "metadata" not in json.dumps(report)
    assert_report(report)


REASONS = frozenset({
    "incomplete", "none", "record-type", "record-bound", "framing", "json", "outer-shape",
    "system-subtype-missing", "system-subtype-nonstr", "system-subtype-unlisted",
    "unexpected-result", "unexpected-assistant", "unexpected-control-request",
    "unexpected-system-init", "unexpected-system-notification", "unexpected-system-status",
    "unexpected-system-state", "unexpected-system-hook-started", "unexpected-system-hook-progress",
    "unexpected-system-hook-response", "unexpected-system-metadata", "system-model-effort-warning",
    "system-model-context-warning",
    "unexpected-other", "envelope-shape", "response-not-success", "request-mismatch",
    "pending-permissions", "pending-dialogs", "body-shape", "version-mismatch", "state-not-idle",
    "account-shape", "account-fields", "other-mode", "read-contract", "output-bound", "single-use",
    "input-bound", "eof-before-frame", "extra-output", "ui-shape", "ui-bound",
}) | frozenset(LEGACY_SYSTEM_REASONS.get(value, "system-" + value)
              for value in SOURCE_SYSTEM_SUBTYPES)
REASON_BYTES = 32
assert max(map(len, REASONS)) == REASON_BYTES


def assert_report(report, *, variant="base"):
    schema = {
        "schema_version": lambda value: type(value) is int and value == 1,
        "scope": lambda value: value == "credential_free_native_startup_observation",
        "protocol": lambda value: type(value) is str and value in {
            "correlated-noauth", "other-mode", "invalid", "incomplete"},
        "protocol_reason": lambda value: (type(value) is str and value in REASONS
                                          and len(value) <= REASON_BYTES),
        "lifecycle": lambda value: type(value) is str and value in {
            "clean", "failed", "timeout", "process-refused"},
        "request_writes": lambda value: type(value) is int and 0 <= value <= 1,
        "stdin_closed": lambda value: type(value) is bool,
        "eof": lambda value: type(value) is bool,
        "binding_checks": lambda value: type(value) is int and 0 <= value <= 3,
        "accepted_ui_records": lambda value: type(value) is int and 0 <= value <= 8,
        "supervisor_returncode": lambda value: value is None or (
            type(value) is int and -255 <= value <= 255),
        "payload_returncode": lambda value: value is None or (
            type(value) is int and 0 <= value <= 255),
        "process_timed_out": lambda value: value is None or type(value) is bool,
        "process_bound_exceeded": lambda value: value is None or type(value) is bool,
        "production_available": lambda value: value is False,
        "subscription_qualified": lambda value: value is False,
        "claude_qualified": lambda value: value is False,
    }
    if variant == "hosted":
        def sha256(value):
            return (type(value) is str and len(value) == 64
                    and all(character in "0123456789abcdef" for character in value))

        def identity_digest(value):
            return (type(value) is str and value.startswith("sha256:")
                    and sha256(value.removeprefix("sha256:")))

        schema.update({
            "proxy_accepted_connections": lambda value: type(value) is int and 0 <= value <= 9,
            "proxy_bound_exceeded": lambda value: type(value) is bool,
            "proxy_joined": lambda value: type(value) is bool,
            "launch_revision": identity_digest, "vendor_digest": identity_digest,
            "runtime_digest": identity_digest,
            "member_sha256": sha256, "archive_sha256": sha256,
            "member_size": lambda value: type(value) is int and value == 257068216,
            "version": lambda value: type(value) is str and value == "2.1.296",
        })
    elif variant == "failure":
        fields = {"schema_version", "scope", "lifecycle", "protocol_reason",
                  "production_available", "subscription_qualified", "claude_qualified"}
        schema = {key: predicate for key, predicate in schema.items() if key in fields}
    else:
        assert variant == "base"
    assert set(report) == set(schema)
    for key, value in report.items():
        assert schema[key](value), key
    if report.get("protocol") == "correlated-noauth":
        assert report["protocol_reason"] == "none"
    if report.get("protocol") == "incomplete":
        assert report["protocol_reason"] in {"incomplete", "input-bound", "eof-before-frame"}


@pytest.mark.parametrize("fragment", [1, 8192])
@pytest.mark.parametrize("damage", ["subscription", "wrong-id", "pending", "version",
                                    "running", "missing-none", "extra-account", "malformed",
                                    "duplicate", "partial-extra", "missing-lf", "empty",
                                    "oversized"])
async def test_non_noauth_damage_never_counts_as_observation_but_closes_stdin(damage, fragment):
    def transform(raw):
        if damage == "subscription":
            return raw.replace(b'"tokenSource":"none"', b'"subscriptionType":"Claude Pro"')
        if damage == "wrong-id":
            return raw.replace(b'"request_id":"', b'"request_id":"wrong-')
        if damage == "pending":
            return raw.replace(b'"pending_permission_requests":[]',
                               b'"pending_permission_requests":[{"private":"prompt"}]')
        if damage == "version":
            return raw.replace(b"2.1.296", b"2.1.295")
        if damage == "running":
            return raw.replace(b'"idle"', b'"running"')
        if damage == "missing-none":
            return raw.replace(b',"tokenSource":"none"', b"")
        if damage == "extra-account":
            return raw.replace(b'"tokenSource":"none"',
                               b'"tokenSource":"none","email":"private@example.invalid"')
        if damage == "malformed":
            return b"private malformed\n"
        if damage == "duplicate":
            return raw + raw
        if damage == "partial-extra":
            return raw + b"x"
        if damage == "missing-lf":
            return raw[:-1]
        if damage == "empty":
            return b""
        return raw[:-1] + b" " * RECORD_BYTES + b"\n"

    launcher = Launcher(Channel(transform, fragment=fragment))
    report, checked = await observe(launcher, timeout=10 if damage == "oversized" else 1)
    assert not diagnostic.successful(report), report
    assert report["protocol"] != "correlated-noauth", report
    expected = ("incomplete" if damage == "empty" else "other-mode"
                if damage in {"subscription", "missing-none", "extra-account"} else "invalid")
    assert report["protocol"] == expected, report
    reasons = {"subscription": "other-mode", "wrong-id": "request-mismatch",
               "pending": "pending-permissions", "version": "version-mismatch",
               "running": "state-not-idle", "missing-none": "other-mode",
               "extra-account": "other-mode", "malformed": "json",
               "duplicate": "extra-output", "partial-extra": "extra-output",
               "missing-lf": "framing", "empty": "eof-before-frame",
               "oversized": "record-bound"}
    assert report["protocol_reason"] == reasons[damage]
    assert launcher.channel.close_attempts == 1 and checked == [False, False, True]
    assert launcher.joined and len(launcher.channel.writes) == 1
    assert_report(report)


@pytest.mark.parametrize("stage", ["write", "read", "close", "tail"])
async def test_io_failures_cannot_publish_and_never_retry_write_or_close(stage):
    launcher = Launcher(Channel(fault=stage))
    report, checked = await observe(launcher)
    assert not diagnostic.successful(report)
    assert len(launcher.channel.writes) == 1
    assert launcher.channel.close_attempts == int(stage in {"close", "tail"})
    assert launcher.joined and checked == [False, False, True]
    assert_report(report)


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("absent", [False, True])
async def test_binding_change_or_absence_refuses_and_prespawn_change_cannot_recover(index, absent):
    initial = BindingCheck(digest("diagnostic-test", 1, "binding"))
    values = [initial, initial, initial]
    values[index] = None if absent else BindingCheck(digest("diagnostic-test", 1, "changed"))
    launcher = Launcher()
    report, checked = await observe(launcher, values=values)
    assert not diagnostic.successful(report)
    assert launcher.spawned is (index == 2)
    assert len(checked) == (1 if index == 0 and absent else 3)
    assert_report(report)


async def test_input_bound_binds_before_the_only_write():
    launcher = Launcher()
    launcher.limits = replace(launcher.limits, input_bytes=1)
    report, _ = await observe(launcher)
    assert not diagnostic.successful(report) and launcher.channel.writes == []
    assert launcher.channel.close_attempts == 0
    assert report["protocol_reason"] == "input-bound"
    assert_report(report)


@pytest.mark.parametrize("stage", ["write", "read", "close", "tail"])
async def test_cancellation_joins_and_checks_terminal_without_masking_primary(stage):
    launcher = Launcher(Channel(fault="block-" + stage))
    task = asyncio.create_task(observe(launcher))
    await asyncio.wait_for(launcher.channel.entered.wait(), 1)
    task.cancel()
    failure = None
    try:
        await task
    except BaseException as error:
        failure = error
    assert isinstance(failure, asyncio.CancelledError), failure
    assert launcher.joined and len(launcher.channel.writes) == 1
    assert launcher.channel.close_attempts == int(stage in {"close", "tail"})


async def test_deny_peer_counts_refusals_and_joins_without_any_upstream_operation():
    listener = socket.create_server(("127.0.0.1", 0))
    listener.setblocking(False)
    deadline = asyncio.get_running_loop().time() + 2
    async with diagnostic.DenyPeer(listener, deadline=deadline) as peer:
        for _ in range(2):
            client = socket.socket()
            client.setblocking(False)
            await asyncio.get_running_loop().sock_connect(client, listener.getsockname())
            try:
                assert await asyncio.get_running_loop().sock_recv(client, 1) == b""
            finally:
                client.close()
        assert peer.attempts == 2
    assert peer.joined and listener.fileno() == -1


async def test_cancelled_read_never_awaits_a_blocking_close_after_cancellation():
    channel = Channel(fault="block-read")
    closes = []

    async def forbidden_close():
        closes.append(True)
        pytest.fail("cancelled protocol must use launcher's joined shutdown, not close")

    channel.close_stdin = forbidden_close
    launcher = Launcher(channel)
    task = asyncio.create_task(observe(launcher))
    await asyncio.wait_for(channel.entered.wait(), 1)
    task.cancel()
    failure = None
    try:
        await asyncio.wait_for(task, 1)
    except BaseException as error:
        failure = error
    assert isinstance(failure, asyncio.CancelledError), failure
    assert launcher.joined and closes == []


async def test_expired_read_never_awaits_a_blocking_close_after_deadline():
    launcher = Launcher(Channel(fault="block-read"))
    closes = []

    async def forbidden_close():
        closes.append(True)
        pytest.fail("expired protocol cannot begin another protocol await")

    launcher.channel.close_stdin = forbidden_close
    report, checked = await asyncio.wait_for(observe(launcher, timeout=.01), 1)
    assert report["lifecycle"] == "timeout" and not diagnostic.successful(report)
    assert launcher.joined and checked == [False, False, True]
    assert closes == []
    assert_report(report)


@pytest.mark.parametrize("damage", ["stdout", "supervisor", "payload", "timeout", "bound"])
async def test_process_damage_and_cumulative_output_bound_prevent_success(damage):
    launcher = Launcher()
    if damage == "stdout":
        launcher.limits = replace(launcher.limits, stdout_bytes=1)
    elif damage == "supervisor":
        launcher.result = replace(launcher.result, returncode=125)
    elif damage == "payload":
        launcher.result = replace(launcher.result, payload_returncode=None)
    elif damage == "timeout":
        launcher.result = replace(launcher.result, timed_out=True)
    else:
        launcher.result = replace(launcher.result, bound_exceeded="stdout")
    report, _ = await observe(launcher)
    assert not diagnostic.successful(report), report
    assert launcher.joined
    assert report["protocol_reason"] == ("output-bound" if damage == "stdout" else "none")
    assert_report(report)


@pytest.mark.parametrize("value", ["private non-bytes", b"x" * 8193])
async def test_read_contract_failure_reports_only_a_static_reason(value):
    channel = Channel()

    async def read(maximum=8192):
        return value

    channel.read = read
    report, _ = await observe(Launcher(channel))
    assert report["protocol"] == "invalid" and report["protocol_reason"] == "read-contract"
    assert not diagnostic.successful(report)
    assert_report(report)


@pytest.mark.parametrize("variant", ["base", "hosted", "failure"])
async def test_shared_schema_walks_every_published_field(variant):
    report, _ = await observe(Launcher())
    if variant == "hosted":
        identity = str(digest("diagnostic-schema-test", 1, "opaque"))
        report.update({"proxy_accepted_connections": 0, "proxy_bound_exceeded": False,
                       "proxy_joined": True, "launch_revision": identity,
                       "vendor_digest": identity, "runtime_digest": identity,
                       "member_sha256": "0" * 64, "archive_sha256": "0" * 64,
                       "member_size": 257068216, "version": "2.1.296"})
    elif variant == "failure":
        report = {"schema_version": 1, "scope": diagnostic.SCOPE, "lifecycle": "failed",
                  "protocol_reason": "incomplete", "production_available": False,
                  "subscription_qualified": False, "claude_qualified": False}
    assert_report(report, variant=variant)
    for key in report:
        damaged = {**report, key: "private unbounded sentinel" * 1024}
        failure = None
        try:
            assert_report(damaged, variant=variant)
        except Exception as error:
            failure = error
        assert isinstance(failure, AssertionError), key


async def test_exact_record_ceiling_binds_and_duplicate_json_facts_refuse():
    raw = response("id")
    padded = raw[:-1] + b" " * (RECORD_BYTES - len(raw)) + b"\n"
    assert diagnostic.classify(padded, "id") == ("correlated-noauth", "none")
    assert diagnostic.classify(padded[:-1] + b" \n", "id") == ("invalid", "record-bound")
    duplicate = raw.replace(b'"tokenSource":"none"',
                            b'"tokenSource":"private","tokenSource":"none"')
    assert diagnostic.classify(duplicate, "id") == ("invalid", "json")


@pytest.mark.parametrize("damage", ["outer", "type", "envelope", "subtype", "body", "account",
                                    "account-value", "account-key", "crlf", "system", "result",
                                    "assistant", "unknown-type", "unhashable-type",
                                    "unhashable-subtype", "request-type", "request-mismatch",
                                    "pending-permissions", "pending-dialogs", "envelope-extra",
                                    "version", "state", "json", "non-object", "record-type",
                                    "framing", "record-bound", "noauth", "other-mode"])
def test_classifier_rejects_invalid_shapes_without_disclosing_fields(damage):
    value = json.loads(response("id"))
    if damage == "outer":
        value["private"] = "not allowed"
    elif damage == "type":
        value["type"] = "control_request"
    elif damage == "envelope":
        value["response"] = []
    elif damage == "subtype":
        value["response"]["subtype"] = "error"
    elif damage == "body":
        value["response"]["response"] = []
    elif damage == "account":
        value["response"]["response"]["account"] = []
    elif damage == "account-value":
        value["response"]["response"]["account"]["tokenSource"] = 0
    elif damage == "account-key":
        value["response"]["response"]["account"]["private"] = "not allowed"
    elif damage in {"system", "result", "assistant"}:
        value["type"] = damage
    elif damage == "unknown-type":
        value["type"] = "private unrecognized type" * 100
    elif damage == "unhashable-type":
        value["type"] = {"private": []}
    elif damage == "unhashable-subtype":
        value["response"]["subtype"] = {"private": []}
    elif damage == "request-type":
        value["response"]["request_id"] = []
    elif damage == "request-mismatch":
        value["response"]["request_id"] = "private other id"
    elif damage in {"pending-permissions", "pending-dialogs"}:
        field = ("pending_permission_requests" if damage == "pending-permissions"
                 else "pending_user_dialog_requests")
        value["response"][field] = [{"private": "prompt"}]
    elif damage == "envelope-extra":
        value["response"]["private"] = "not allowed"
    elif damage == "version":
        value["response"]["response"]["claude_code_version"] = "private version"
    elif damage == "state":
        value["response"]["response"]["session_state"] = []
    elif damage == "non-object":
        value = []
    elif damage == "other-mode":
        value["response"]["response"]["account"]["tokenSource"] = "private token source"
    raw = json.dumps(value).encode() + (b"\r\n" if damage == "crlf" else b"\n")
    if damage == "json":
        raw = b"private malformed\n"
    elif damage == "record-type":
        raw = "private not bytes"
    elif damage == "framing":
        raw = raw[:-1]
    elif damage == "record-bound":
        raw += b" " * RECORD_BYTES
    reasons = {
        "outer": "outer-shape", "type": "unexpected-control-request",
        "envelope": "envelope-shape", "subtype": "response-not-success", "body": "body-shape",
        "account": "account-shape", "account-value": "account-fields",
        "account-key": "account-fields", "crlf": "framing", "system": "system-subtype-missing",
        "result": "unexpected-result", "assistant": "unexpected-assistant",
        "unknown-type": "unexpected-other", "unhashable-type": "unexpected-other",
        "unhashable-subtype": "response-not-success", "request-type": "request-mismatch",
        "request-mismatch": "request-mismatch", "pending-permissions": "pending-permissions",
        "pending-dialogs": "pending-dialogs", "envelope-extra": "envelope-shape",
        "version": "version-mismatch", "state": "state-not-idle", "json": "json",
        "non-object": "outer-shape", "record-type": "record-type", "framing": "framing",
        "record-bound": "record-bound", "noauth": "none", "other-mode": "other-mode",
    }
    failure, observed = None, None
    try:
        observed = diagnostic.classify(raw, "id")
    except Exception as error:
        failure = error
    assert failure is None
    protocol = ("correlated-noauth" if damage == "noauth" else "other-mode"
                if damage == "other-mode" else "invalid")
    assert observed == (protocol, reasons[damage])
    assert observed[1] in REASONS and len(observed[1]) <= REASON_BYTES
    assert "private" not in json.dumps(observed)


async def test_callback_is_single_use_and_deadline_checked_before_any_write():
    channel = Channel()
    probe = diagnostic._Probe(deadline=asyncio.get_running_loop().time() + 2,
                              input_limit=8192, output_limit=RECORD_BYTES)
    await probe(channel)
    failure = None
    try:
        await probe(channel)
    except BaseException as error:
        failure = error
    assert isinstance(failure, diagnostic._Refused) and len(channel.writes) == 1
    assert probe.reason == "single-use"
    expired = diagnostic._Probe(deadline=asyncio.get_running_loop().time() - 1,
                                input_limit=8192, output_limit=RECORD_BYTES)
    failure = None
    try:
        await expired(channel)
    except BaseException as error:
        failure = error
    assert isinstance(failure, TimeoutError) and len(channel.writes) == 1


def test_main_rejects_arguments_without_launching_or_publishing_private_error(monkeypatch, capsys):
    async def forbidden():
        pytest.fail("argument refusal must precede hosted launch")

    monkeypatch.setattr(sys, "argv", ["observe", "private-unexpected"])
    monkeypatch.setattr(diagnostic, "hosted_observation", forbidden)
    assert diagnostic.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "schema_version": 1, "scope": diagnostic.SCOPE, "lifecycle": "failed",
        "protocol_reason": "incomplete",
        "production_available": False, "subscription_qualified": False, "claude_qualified": False,
    }
    assert_report(report, variant="failure")


async def test_hosted_helper_is_not_bound_to_pytest_argv_and_publishes_only_pinned_fields(
    monkeypatch, tmp_path,
):
    from scripts.ci import build_m8_claude_startup_fixture as builder

    pins = {
        "schema_version": 1, "scope": "credential_free_native_startup_fixture",
        "version": builder.VERSION, "member_sha256": builder.MEMBER_SHA256,
        "member_size": builder.MEMBER_SIZE, "archive_sha256": builder.ARCHIVE_SHA256,
        "vendor_digest": str(digest("diagnostic-test", 1, "vendor")),
        "runtime_digest": str(digest("diagnostic-test", 1, "pinned-runtime")),
        "production_available": False, "subscription_qualified": False, "claude_qualified": False,
    }
    (tmp_path / "pinned-startup.json").write_text(json.dumps(pins))
    (tmp_path / "fixture.json").write_text(json.dumps({
        "runtime_digest": str(digest("diagnostic-test", 1, "fake-runtime")),
        "policy_sha256": "1" * 64,
    }))
    monkeypatch.setattr(diagnostic, "ROOT", tmp_path)
    monkeypatch.setattr(diagnostic.sys, "platform", "linux")
    monkeypatch.setattr(diagnostic.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(sys, "argv", ["pytest", "private-not-an-observer-option"])
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")

    def launcher(**arguments):
        assert arguments["runtime_root"] == tmp_path / "pinned-runtime"
        assert arguments["expected_runtime"] == Digest(pins["runtime_digest"])
        value = Launcher()
        value.revision = digest("diagnostic-test", 1, "recipe")
        return value

    @asynccontextmanager
    async def store(_deadline):
        peer = SimpleNamespace(attempts=0, bound_exceeded=False, joined=False)
        try:
            yield ClaudeNativeStoreMount(
                42, 43, lambda: BindingCheck(digest("diagnostic-test", 1, "binding")),
            ), peer
        finally:
            peer.joined = True

    monkeypatch.setattr(diagnostic, "LinuxLauncher", launcher)
    monkeypatch.setattr(diagnostic, "fake_store", store)
    report = await diagnostic.hosted_observation()
    assert diagnostic.successful(report)
    extras = {"proxy_accepted_connections", "proxy_bound_exceeded", "proxy_joined",
              "launch_revision", "vendor_digest", "member_sha256", "archive_sha256",
              "member_size", "version", "runtime_digest"}
    assert_report(report, variant="hosted")
    assert {key: report[key] for key in extras} == {
        "proxy_accepted_connections": 0, "proxy_bound_exceeded": False, "proxy_joined": True,
        "launch_revision": str(digest("diagnostic-test", 1, "recipe")),
        "vendor_digest": pins["vendor_digest"], "member_sha256": builder.MEMBER_SHA256,
        "runtime_digest": pins["runtime_digest"],
        "archive_sha256": builder.ARCHIVE_SHA256, "member_size": builder.MEMBER_SIZE,
        "version": builder.VERSION,
    }


async def test_fatal_exchange_is_preserved_when_terminal_check_fails():
    class Fatal(BaseException):
        pass

    primary = Fatal("private fatal")
    launcher = Launcher(error=primary)
    checked = []

    def check():
        checked.append(launcher.joined)
        if launcher.joined:
            raise OSError("private terminal")
        return BindingCheck(digest("diagnostic-test", 1, "binding"))

    failure = None
    try:
        await diagnostic.observe_startup(launcher, ClaudeNativeStoreMount(42, 43, check))
    except BaseException as error:
        failure = error
    assert failure is primary and checked == [False, False, True]


async def test_deny_peer_bound_counts_the_refused_ninth_attempt_and_stops():
    listener = socket.create_server(("127.0.0.1", 0))
    listener.setblocking(False)
    async with diagnostic.DenyPeer(
        listener, deadline=asyncio.get_running_loop().time() + 2,
    ) as peer:
        for _ in range(diagnostic.PROXY_ATTEMPTS + 1):
            client = socket.socket()
            client.setblocking(False)
            await asyncio.get_running_loop().sock_connect(client, listener.getsockname())
            try:
                assert await asyncio.get_running_loop().sock_recv(client, 1) == b""
            finally:
                client.close()
    assert peer.joined and peer.attempts == 9 and peer.bound_exceeded


async def test_deny_peer_join_handles_no_started_task_and_preserves_task_failure(monkeypatch):
    for broken in (False, True):
        listener = socket.create_server(("127.0.0.1", 0))
        listener.setblocking(False)
        peer = diagnostic.DenyPeer(listener, deadline=asyncio.get_running_loop().time() + 2)

        async def fail():
            raise OSError("private peer failure")

        if broken:
            monkeypatch.setattr(peer, "serve", fail)
        error = None
        try:
            async with peer:
                if broken:
                    await asyncio.sleep(0)
        except BaseException as observed:
            error = observed
        assert isinstance(error, OSError) if broken else error is None
        assert peer.joined is (not broken) and listener.fileno() == -1


@pytest.mark.parametrize("cancelled", [False, True])
async def test_deny_peer_cleanup_failure_never_masks_primary_control_flow(monkeypatch, cancelled):
    class Fatal(BaseException):
        pass

    primary = (asyncio.CancelledError("private cancellation") if cancelled
               else Fatal("private fatal"))
    listener = socket.create_server(("127.0.0.1", 0))
    listener.setblocking(False)
    peer = diagnostic.DenyPeer(listener, deadline=asyncio.get_running_loop().time() + 2)

    async def fail():
        raise OSError("private peer failure")

    monkeypatch.setattr(peer, "serve", fail)
    failure = None
    try:
        async with peer:
            await asyncio.sleep(0)
            raise primary
    except BaseException as error:
        failure = error
    assert failure is primary and not peer.joined and listener.fileno() == -1


@pytest.mark.parametrize("model", ["fixture-startup", "fixture-startup-subscribed",
                                  "fixture-startup-ui", "fixture-startup-ui-overflow"])
async def test_compiled_fake_uses_the_same_diagnostic_callback_and_requires_eof(wire_peer, model):
    launcher = Launcher()
    launcher.claude = replace(launcher.claude, model=model)

    async def exchange(command, **arguments):
        child = None
        try:
            arguments["native_store"].before_spawn()
            child = await asyncio.create_subprocess_exec(
                str(wire_peer), *command[1:], stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            launcher.spawned = True

            class Pipes:
                async def write(self, raw):
                    child.stdin.write(raw)
                    await child.stdin.drain()

                async def read(self, maximum=8192):
                    return await child.stdout.read(maximum)

                async def close_stdin(self):
                    child.stdin.close()
                    await child.stdin.wait_closed()

            await arguments["conversation"](Pipes())
            code = await child.wait()
            assert await child.stderr.read(1024) == b""
            return ProcessResult(code, b"", b"", .1, payload_returncode=code)
        finally:
            if child is not None:
                if child.returncode is None:
                    child.kill()
                await child.wait()
            launcher.joined = True

    launcher.exchange = exchange
    report, checked = await observe(launcher, timeout=5)
    assert diagnostic.successful(report) is (model in {"fixture-startup", "fixture-startup-ui"})
    assert report["accepted_ui_records"] == (8 if "-ui" in model else 0)
    if model == "fixture-startup-ui-overflow":
        assert report["protocol"] == "invalid" and report["protocol_reason"] == "ui-bound"
    assert report["lifecycle"] == "clean" and report["eof"] is True
    assert checked == [False, False, True]
    assert_report(report)


def physical_launcher(model):
    if not os.environ.get("M8_CLAUDE_STARTUP_REQUIRED"):
        pytest.skip("native startup observation requires the disposable hosted fixture")
    assert sys.platform == "linux" and os.getuid() != 0
    assert os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    root = diagnostic.ROOT
    assert (root / "fixture.json").is_file(), "required fake fixture is absent"
    pins = json.loads((root / "fixture.json").read_text())
    return LinuxLauncher(
        runtime_root=root / "runtime", expected_runtime=Digest(pins["runtime_digest"]),
        bubblewrap=root / "bwrap", policy=diagnostic.POLICY,
        expected_policy_sha256=pins["policy_sha256"],
        claude=ClaudeNativeVendor(root / "fake-vendor", model, "low",
                                  Digest(pins["vendor_digest"])),
    )


@pytest.mark.parametrize("model", ["fixture-startup", "fixture-startup-subscribed",
                                  "fixture-startup-ui", "fixture-startup-ui-overflow"])
async def test_physical_fake_startup_control_precedes_pinned_observation(model):
    launcher = physical_launcher(model)
    deadline = asyncio.get_running_loop().time() + 20
    async with diagnostic.fake_store(deadline) as (mount, peer):
        report = await diagnostic.observe_startup(
            launcher, mount, timeout_s=deadline - asyncio.get_running_loop().time(),
        )
    assert diagnostic.successful(report) is (model in {"fixture-startup", "fixture-startup-ui"})
    assert report["protocol"] == (
        "invalid" if model == "fixture-startup-ui-overflow"
        else "other-mode" if model == "fixture-startup-subscribed" else "correlated-noauth"
    )
    assert report["accepted_ui_records"] == (8 if "-ui" in model else 0)
    if model == "fixture-startup-ui-overflow":
        assert report["protocol_reason"] == "ui-bound"
    assert report["lifecycle"] == "clean" and report["eof"] is report["stdin_closed"] is True
    assert peer.joined and peer.attempts == 0 and not peer.bound_exceeded
    assert_report(report)
    write_evidence(f"n6-claude-startup-{model}.json", report)


async def test_pinned_credential_free_startup_has_only_a_noauth_observation():
    physical_launcher("fixture-startup")  # Required fixture/platform failures are never skips.
    report = await diagnostic.hosted_observation()
    write_evidence("n6-claude-pinned-startup.json", report)
    assert_report(report, variant="hosted")
    assert diagnostic.successful(report), report
    assert report["proxy_joined"] is True and report["proxy_bound_exceeded"] is False
    assert (type(report["proxy_accepted_connections"]) is int
            and 0 <= report["proxy_accepted_connections"] <= 8)
