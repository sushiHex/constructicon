"""Fake-first settings diagnostic; no credentials, vendor or model invocation."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from scripts.ci import observe_m8_claude_settings as diagnostic

from constructicon.core.identity import digest
from constructicon.substrate.executors.claude_native import (
    POLICY_MOUNT,
    ClaudeNativeStoreMount,
    ClaudeNativeVendor,
)
from constructicon.substrate.executors.claude_protocol import RECORD_BYTES
from constructicon.substrate.executors.operator_store import BindingCheck
from tests.substrate.test_claude_native_startup import Launcher, response, ui_record
from tests.substrate.test_native_codex_mediation import write_evidence


def settings(identifier, body=None):
    return json.dumps({"type": "control_response", "response": {
        "subtype": "success", "request_id": identifier, "response": body or {},
    }}, separators=(",", ":")).encode() + b"\n"


class Channel:
    def __init__(self, *, body=None, transform=lambda kind, raw: raw, fragment=8192):
        self.body, self.transform, self.fragment = body, transform, fragment
        self.output = bytearray()
        self.ready = asyncio.Event()
        self.writes = []
        self.closed = False
        self.readers = self.maximum_readers = 0
        self.close_attempts = 0
        self.operations = []
        self.seam = self.noop

    async def noop(self, stage):
        pass

    async def write(self, raw):
        value = json.loads(raw)
        kind = value["request"]["subtype"]
        assert value == {"type": "control_request", "request_id": value["request_id"],
                         "request": {"subtype": kind}}
        assert kind == ("initialize" if not self.writes else "get_settings")
        self.writes.append(raw)
        frame = (response(value["request_id"]) if kind == "initialize" else
                 settings(value["request_id"], self.body))
        self.output.extend(self.transform(kind, frame))
        self.ready.set()
        stage = f"write-{len(self.writes)}"
        self.operations.append(stage)
        await self.seam(stage)

    async def read(self, maximum=8192):
        self.readers += 1
        self.maximum_readers = max(self.maximum_readers, self.readers)
        try:
            while not self.output and not self.closed:
                self.ready.clear()
                await self.ready.wait()
            stage = "eof" if not self.output else f"read-{len(self.writes)}"
            self.operations.append(stage)
            await self.seam(stage)
            size = min(maximum, self.fragment, len(self.output))
            value = bytes(self.output[:size])
            del self.output[:size]
            return value
        finally:
            self.readers -= 1

    async def close_stdin(self):
        self.close_attempts += 1
        self.operations.append("close")
        await self.seam("close")
        self.closed = True
        self.ready.set()


async def observe(channel, *, timeout=1, limits=None):
    launcher = Launcher(channel)
    if limits is not None:
        launcher.limits = limits
    checked = []

    def check():
        from constructicon.substrate.executors.operator_store import BindingCheck
        checked.append(launcher.joined)
        return BindingCheck(digest("settings-test", 1, "binding"))

    report = await diagnostic.observe_settings(
        launcher, ClaudeNativeStoreMount(42, 43, check), timeout_s=timeout,
    )
    assert launcher.joined and checked == [False, False, True]
    assert channel.readers == 0 and channel.maximum_readers == 1
    assert_report(report)
    return report


def assert_report(report, *, hosted=False):
    enums = {
        "schema_version": {1}, "scope": {diagnostic.SCOPE},
        "lifecycle": {"clean", "process-refused", "timeout", "failed"},
        "initialize_kind": {"incomplete", "correlated-noauth", "invalid", "other-mode"},
        "refusal_code": {None, *(item.value for item in diagnostic.Refusal)},
        "request_writes": {0, 1, 2}, "accepted_ui_records": set(range(9)),
        "binding_checks": {0, 1, 2, 3},
    }
    bools = {"exchange_completed", "initialize_observed", "settings_observed", "stdin_closed",
             "eof", "reader_joined", "production_available", "subscription_qualified",
             "claude_qualified"}
    if hosted:
        enums["proxy_accepted_connections"] = set(range(10))
        bools |= {"proxy_bound_exceeded", "proxy_joined"}
    assert set(report) == set(enums) | bools | {"policy_presence"}
    for key, allowed in enums.items():
        assert report[key] in allowed
    for key in bools:
        assert type(report[key]) is bool
    for key in ("production_available", "subscription_qualified", "claude_qualified"):
        assert report[key] is False
    projection = report["policy_presence"]
    if projection is not None:
        assert set(projection) == {
            "effective", "errors_shape", "sources_shape", "source_entry_invalid",
            "source_unknown", "source_duplicate", "sources",
        }
        assert projection["errors_shape"] in {"absent", "empty", "nonempty", "wrong-type"}
        assert projection["sources_shape"] in {"absent", "list", "wrong-type"}
        for key in ("source_entry_invalid", "source_unknown", "source_duplicate"):
            assert type(projection[key]) is bool
        assert set(projection["sources"]) == set(diagnostic.SOURCES)
        for value in [projection["effective"], *projection["sources"].values()]:
            assert set(value) == {"shape", "refresh", "mcp"}
            assert value["shape"] in {"absent", "object", "wrong-type", "duplicate"}
            assert value["refresh"] in {"absent", "true", "false", "wrong-type"}
            assert value["mcp"] in {"absent", "empty", "deny-all", "wrong-type", "other"}
    assert "private" not in json.dumps(report)


@pytest.mark.parametrize("fragment", [1, 8192])
@pytest.mark.parametrize("policy,refresh,mcp", [
    ({}, "absent", "absent"),
    ({"forceRemoteSettingsRefresh": True, "deniedMcpServers": [{"serverUrl": "*"}]},
     "true", "deny-all"),
    ({"forceRemoteSettingsRefresh": False, "deniedMcpServers": []}, "false", "empty"),
    ({"forceRemoteSettingsRefresh": 1, "deniedMcpServers": None}, "wrong-type", "wrong-type"),
    ({"forceRemoteSettingsRefresh": "private", "deniedMcpServers": ["private"]},
     "wrong-type", "other"),
])
async def test_two_exact_controls_complete_even_when_policy_absent(fragment, policy, refresh, mcp):
    body = {"effective": {**policy, "private": "private"}, "sources": [
        {"source": "policySettings", "settings": policy},
        {"source": "private-name", "settings": {"private": "private"}},
    ], "applied": {"private": "private"}, "private": "private"}
    channel = Channel(body=body, fragment=fragment)
    report = await observe(channel)
    assert diagnostic.successful(report), report
    assert report["initialize_observed"] and report["settings_observed"]
    assert channel.close_attempts == 1 and channel.closed
    identifiers = [json.loads(raw)["request_id"] for raw in channel.writes]
    assert len(set(identifiers)) == 2
    presence = report["policy_presence"]
    expected = {"shape": "object", "refresh": refresh, "mcp": mcp}
    assert presence["effective"] == presence["sources"]["policySettings"] == expected
    assert presence["source_unknown"] is True


@pytest.mark.parametrize("body", [
    {}, {"effective": None, "sources": None},
    {"sources": [None, {"source": "private"}, {"source": [], "settings": None}]},
    {"sources": [{"source": "policySettings", "settings": {}},
                 {"source": "policySettings", "settings": {"private": "private"}}]},
])
async def test_source_shape_and_presence_are_observations(body):
    report = await observe(Channel(body=body))
    assert diagnostic.successful(report)
    assert report["policy_presence"] == diagnostic.settings_presence(body)


@pytest.mark.parametrize("body,state", [
    ({}, "absent"),
    ({"errors": []}, "empty"),
    ({"errors": [{"file": "private-path", "message": "private-message",
                  "private-field": "private-value"}]}, "nonempty"),
    ({"errors": {"private-field": "private-value"}}, "wrong-type"),
])
async def test_errors_have_only_a_finite_shape_observation(body, state):
    report = await observe(Channel(body=body))
    assert diagnostic.successful(report)
    assert report["policy_presence"]["errors_shape"] == state
    assert "private" not in json.dumps(report)


@pytest.mark.parametrize("fragment", [1, 8192])
@pytest.mark.parametrize("case", ["preinitialize", "prebuffered", "partial", "duplicate",
                                  "callback", "mismatch", "subscription", "pending"])
async def test_unsolicited_and_invalid_frames_never_authorize_next_control(
    case, fragment, monkeypatch,
):
    identifiers = iter(["a" * 32, "b" * 32])
    monkeypatch.setattr(diagnostic.secrets, "token_hex", lambda size: next(identifiers))

    def transform(kind, raw):
        if kind == "initialize":
            if case == "prebuffered":
                return raw + settings("b" * 32)
            if case == "partial":
                return raw + b'{"type":'
            if case == "subscription":
                return response("a" * 32, mode="subscription")
            if case == "pending":
                return raw.replace(b'"pending_permission_requests":[]',
                                   b'"pending_permission_requests":[{}]')
        else:
            if case == "duplicate":
                return raw + raw
            if case == "callback":
                return b'{"type":"control_request","private":"private"}\n' + raw
            if case == "mismatch":
                return settings("a" * 32)
        return raw

    channel = Channel(transform=transform, fragment=fragment)
    if case == "preinitialize":
        channel.output.extend(response("a" * 32))
    report = await observe(channel)
    assert not diagnostic.successful(report), report
    assert report["request_writes"] == (0 if case == "preinitialize" else
                                        1 if case in {"prebuffered", "partial", "subscription",
                                                      "pending"} else 2)


@pytest.mark.parametrize("stage", ["write-1", "read-1", "write-2", "read-2", "close", "eof"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_cancellation_and_one_deadline_join_reader_without_later_operations(stage, cancel):
    entered = asyncio.Event()
    channel = Channel()

    async def seam(current):
        if current == stage:
            entered.set()
            await asyncio.Future()

    channel.seam = seam
    launcher = Launcher(channel)
    from constructicon.substrate.executors.operator_store import BindingCheck
    mount = ClaudeNativeStoreMount(42, 43,
                                  lambda: BindingCheck(digest("settings-test", 1, "binding")))
    task = asyncio.create_task(diagnostic.observe_settings(launcher, mount,
                                                          timeout_s=1 if cancel else .03))
    await asyncio.wait_for(entered.wait(), 1)
    operations = list(channel.operations)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        report = await task
        assert report["lifecycle"] == "timeout" and not diagnostic.successful(report)
        assert_report(report)
    assert launcher.joined and channel.readers == 0 and channel.operations == operations


async def test_cumulative_input_output_record_and_ui_budgets_bind():
    launcher = Launcher()
    init_size = len(json.dumps({"type": "control_request", "request_id": "a" * 32,
                                "request": {"subtype": "initialize"}}, separators=(",", ":"))) + 1
    # Each individual request fits; the second exceeds only the cumulative cap.
    report = await observe(Channel(), limits=replace(launcher.limits, input_bytes=init_size + 10))
    assert report["request_writes"] == 1 and report["refusal_code"] == "input-limit"
    for case in ("output", "record", "ui"):
        def transform(kind, raw, case=case):
            if case == "output":
                return ui_record(uuid="private" + "x" * (RECORD_BYTES // 2 + 8192)) + raw
            if case == "record":
                return ui_record(uuid="private" + "x" * RECORD_BYTES) + raw
            return ui_record() * (4 if kind == "initialize" else 5) + raw

        report = await observe(Channel(transform=transform))
        assert not diagnostic.successful(report)
        assert report["refusal_code"] == {"output": "output-limit", "record": "record-limit",
                                           "ui": "ui-record"}[case]


async def test_shared_absolute_deadline_does_not_restart_after_initialize():
    channel = Channel()

    async def seam(stage):
        if stage == "read-1":
            await asyncio.sleep(.04)
        if stage == "read-2":
            await asyncio.sleep(.04)

    channel.seam = seam
    report = await observe(channel, timeout=.06)
    assert report["initialize_observed"] and not report["settings_observed"]
    assert report["lifecycle"] == "timeout"


@pytest.mark.parametrize("fragment", [1, 8192])
async def test_fragmented_ui_between_responses_consumes_shared_budget(fragment):
    channel = Channel(transform=lambda kind, raw: raw + ui_record() * 4, fragment=fragment)
    report = await observe(channel)
    assert diagnostic.successful(report) and report["accepted_ui_records"] == 8


@pytest.mark.parametrize("transition", [False, True])
async def test_full_read_ui_never_hides_prebuffered_correlated_reply(transition, monkeypatch):
    ids = iter(["a" * 32, "b" * 32])
    monkeypatch.setattr(diagnostic.secrets, "token_hex", lambda size: next(ids))
    ui = ui_record(uuid="x" * (8192 - len(ui_record(uuid="x")) + 1))
    assert len(ui) == 8192
    channel = Channel(transform=lambda kind, raw: (
        raw + ui + settings("b" * 32) if transition and kind == "initialize"
        else b"" if not transition and kind == "initialize" else raw
    ))
    if not transition:
        channel.output.extend(ui + response("a" * 32))
    report = await observe(channel)
    assert not diagnostic.successful(report)
    assert report["request_writes"] == int(transition)
    assert report["accepted_ui_records"] == 1


async def test_incomplete_transition_ui_at_eof_cannot_allow_settings_write():
    channel = Channel(transform=lambda kind, raw: raw + ui_record()[:-1])

    async def seam(stage):
        if stage == "write-1":
            channel.closed = True

    channel.seam = seam
    report = await observe(channel)
    assert report["initialize_observed"] and not report["settings_observed"]
    assert report["request_writes"] == 1 and not diagnostic.successful(report)


@pytest.mark.parametrize("settings_file_control", [False, True])
async def test_pinned_credential_free_settings_diagnostic_has_closed_output(settings_file_control):
    if not os.environ.get("M8_CLAUDE_SETTINGS_REQUIRED"):
        pytest.skip("settings diagnostic requires the disposable hosted fixture")
    report = await diagnostic.hosted_observation(settings_file_control=settings_file_control)
    # Persist the finite result before asserting so a refusal is evidence too.
    assert_report(report, hosted=True)
    artifact = ("n6-claude-pinned-settings-file-control.json" if settings_file_control else
                "n6-claude-pinned-settings.json")
    write_evidence(artifact, report)
    assert diagnostic.successful(report), report
    assert report["proxy_joined"] is True and report["proxy_bound_exceeded"] is False
    if settings_file_control:
        assert diagnostic.settings_file_control_successful(report), report
    else:
        assert diagnostic.managed_policy_observed(report), report


@pytest.mark.parametrize("settings_file_control", [None, False, True])
async def test_hosted_control_selects_only_fixed_command_and_keeps_closed_report(
    settings_file_control, monkeypatch, tmp_path,
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
    (tmp_path / "fixture.json").write_text(json.dumps({"policy_sha256": "1" * 64}))
    monkeypatch.setattr(diagnostic.startup, "ROOT", tmp_path)
    monkeypatch.setattr(diagnostic.sys, "platform", "linux")
    monkeypatch.setattr(diagnostic.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    policy = {"forceRemoteSettingsRefresh": True, "deniedMcpServers": [{"serverUrl": "*"}]}
    channel = Channel(body={"sources": [{"source": "flagSettings", "settings": policy}]})
    launches = []

    def launcher(**arguments):
        native = arguments["claude"]
        ordinary = ClaudeNativeVendor(native.tree, native.model, native.effort,
                                      native.expected_tree)
        assert native.command == ordinary.command + (
            ("--settings", POLICY_MOUNT) if settings_file_control else ())
        assert type(native) is (diagnostic._SettingsFileControlVendor if settings_file_control else
                                ClaudeNativeVendor)
        value = Launcher(channel)
        value.claude = native
        launches.append(value)
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
    monkeypatch.setattr(diagnostic.startup, "fake_store", store)
    report = await (diagnostic.hosted_observation() if settings_file_control is None else
                    diagnostic.hosted_observation(settings_file_control=settings_file_control))
    assert len(launches) == 1 and launches[0].joined
    assert_report(report, hosted=True)
    assert diagnostic.successful(report) and diagnostic.settings_file_control_successful(report)
    assert report["proxy_joined"] is True and report["proxy_bound_exceeded"] is False


@pytest.mark.parametrize("selection", [None, 0, 1, "private-path", object()])
async def test_hosted_control_never_accepts_a_caller_path_or_nonbool_selection(selection):
    with pytest.raises(diagnostic._Refused):
        await diagnostic.hosted_observation(settings_file_control=selection)


@pytest.mark.parametrize("errors_present", [False, True])
async def test_file_control_accepts_absent_or_empty_errors_without_managed_policy(errors_present):
    body = {"sources": [{"source": "flagSettings", "settings": {
        "forceRemoteSettingsRefresh": True, "deniedMcpServers": [{"serverUrl": "*"}],
    }}]}
    if errors_present:
        body["errors"] = []
    report = await observe(Channel(body=body))
    assert diagnostic.settings_file_control_successful(report)
    assert report["policy_presence"]["sources"]["policySettings"]["shape"] == "absent"


@pytest.mark.parametrize("case", ["absent", "refresh", "mcp", "duplicate", "invalid", "unknown",
                                  "errors", "error-shape", "exchange"])
async def test_file_control_requires_affirmative_unambiguous_flag_policy(case):
    policy = {"forceRemoteSettingsRefresh": True, "deniedMcpServers": [{"serverUrl": "*"}]}
    body = {"sources": [{"source": "flagSettings", "settings": policy}]}
    if case == "absent":
        body["sources"] = []
    elif case == "refresh":
        policy["forceRemoteSettingsRefresh"] = False
    elif case == "mcp":
        policy["deniedMcpServers"] = []
    elif case == "duplicate":
        body["sources"] *= 2
    elif case == "invalid":
        body["sources"].append({"private": "private"})
    elif case == "unknown":
        body["sources"].append({"source": "private", "settings": policy})
    elif case == "errors":
        body["errors"] = [{"private": "private"}]
    elif case == "error-shape":
        body["errors"] = {"private": "private"}
    channel = Channel(body=body)
    if case == "exchange":
        channel.transform = lambda kind, raw: settings("wrong") if kind == "get_settings" else raw
    report = await observe(channel)
    assert not diagnostic.settings_file_control_successful(report)
    if case != "exchange":
        assert diagnostic.successful(report)  # Ordinary observation remains unchanged.


@pytest.mark.parametrize("case", ["match", "flag-only", "effective-absent", "source-absent",
                                  "effective-drift", "source-drift", "errors"])
async def test_managed_projection_requires_effective_and_managed_source(case):
    policy = {"forceRemoteSettingsRefresh": True, "deniedMcpServers": [{"serverUrl": "*"}]}
    body = {"effective": dict(policy), "sources": [
        {"source": "policySettings", "settings": dict(policy)},
    ]}
    if case == "flag-only":
        body["sources"][0]["source"] = "flagSettings"
    elif case == "effective-absent":
        del body["effective"]
    elif case == "source-absent":
        body["sources"] = []
    elif case == "effective-drift":
        body["effective"]["forceRemoteSettingsRefresh"] = False
    elif case == "source-drift":
        body["sources"][0]["settings"]["forceRemoteSettingsRefresh"] = False
    elif case == "errors":
        body["errors"] = [{"private": "not published"}]
    report = await observe(Channel(body=body))
    assert diagnostic.successful(report)
    assert diagnostic.managed_policy_observed(report) is (case == "match")
