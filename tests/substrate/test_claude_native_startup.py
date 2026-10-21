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


def assert_report(report):
    schema = {
        "schema_version": lambda value: type(value) is int and value == 1,
        "scope": lambda value: value == "credential_free_native_startup_observation",
        "protocol": lambda value: value in {"correlated-noauth", "other-mode", "invalid",
                                            "incomplete"},
        "lifecycle": lambda value: value in {"clean", "failed", "timeout", "process-refused"},
        "request_writes": lambda value: type(value) is int and 0 <= value <= 1,
        "stdin_closed": lambda value: type(value) is bool,
        "eof": lambda value: type(value) is bool,
        "binding_checks": lambda value: type(value) is int and 0 <= value <= 3,
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
    assert set(report) == set(schema)
    for key, value in report.items():
        assert schema[key](value), key


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
    expected = ("incomplete" if damage in {"missing-lf", "empty"} else "other-mode"
                if damage in {"subscription", "missing-none", "extra-account"} else "invalid")
    assert report["protocol"] == expected, report
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


async def test_input_bound_binds_before_the_only_write():
    launcher = Launcher()
    launcher.limits = replace(launcher.limits, input_bytes=1)
    report, _ = await observe(launcher)
    assert not diagnostic.successful(report) and launcher.channel.writes == []
    assert launcher.channel.close_attempts == 0


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
    assert_report(report)


async def test_exact_record_ceiling_binds_and_duplicate_json_facts_refuse():
    raw = response("id")
    padded = raw[:-1] + b" " * (RECORD_BYTES - len(raw)) + b"\n"
    assert diagnostic.classify(padded, "id") == "correlated-noauth"
    assert diagnostic.classify(padded[:-1] + b" \n", "id") == "invalid"
    duplicate = raw.replace(b'"tokenSource":"none"',
                            b'"tokenSource":"private","tokenSource":"none"')
    assert diagnostic.classify(duplicate, "id") == "invalid"


@pytest.mark.parametrize("damage", ["outer", "type", "envelope", "subtype", "body", "account",
                                    "account-value", "account-key", "crlf"])
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
    raw = json.dumps(value).encode() + (b"\r\n" if damage == "crlf" else b"\n")
    assert diagnostic.classify(raw, "id") == "invalid"


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
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1, "scope": diagnostic.SCOPE, "lifecycle": "failed",
        "production_available": False, "subscription_qualified": False, "claude_qualified": False,
    }


async def test_hosted_helper_is_not_bound_to_pytest_argv_and_publishes_only_pinned_fields(
    monkeypatch, tmp_path,
):
    from scripts.ci import build_m8_claude_startup_fixture as builder

    pins = {
        "schema_version": 1, "scope": "credential_free_native_startup_fixture",
        "version": builder.VERSION, "member_sha256": builder.MEMBER_SHA256,
        "member_size": builder.MEMBER_SIZE, "archive_sha256": builder.ARCHIVE_SHA256,
        "vendor_digest": str(digest("diagnostic-test", 1, "vendor")),
        "production_available": False, "subscription_qualified": False, "claude_qualified": False,
    }
    (tmp_path / "pinned-startup.json").write_text(json.dumps(pins))
    (tmp_path / "fixture.json").write_text(json.dumps({
        "runtime_digest": str(digest("diagnostic-test", 1, "runtime")),
        "policy_sha256": "1" * 64,
    }))
    monkeypatch.setattr(diagnostic, "ROOT", tmp_path)
    monkeypatch.setattr(diagnostic.sys, "platform", "linux")
    monkeypatch.setattr(diagnostic.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(sys, "argv", ["pytest", "private-not-an-observer-option"])
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")

    def launcher(**_arguments):
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
              "member_size", "version"}
    assert_report({key: value for key, value in report.items() if key not in extras})
    assert {key: report[key] for key in extras} == {
        "proxy_accepted_connections": 0, "proxy_bound_exceeded": False, "proxy_joined": True,
        "launch_revision": str(digest("diagnostic-test", 1, "recipe")),
        "vendor_digest": pins["vendor_digest"], "member_sha256": builder.MEMBER_SHA256,
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


@pytest.mark.parametrize("model", ["fixture-startup", "fixture-startup-subscribed"])
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
    assert diagnostic.successful(report) is (model == "fixture-startup"), report
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


@pytest.mark.parametrize("model", ["fixture-startup", "fixture-startup-subscribed"])
async def test_physical_fake_startup_control_precedes_pinned_observation(model):
    launcher = physical_launcher(model)
    deadline = asyncio.get_running_loop().time() + 20
    async with diagnostic.fake_store(deadline) as (mount, peer):
        report = await diagnostic.observe_startup(
            launcher, mount, timeout_s=deadline - asyncio.get_running_loop().time(),
        )
    assert diagnostic.successful(report) is (model == "fixture-startup"), report
    assert report["protocol"] == ("correlated-noauth" if model == "fixture-startup"
                                  else "other-mode")
    assert report["lifecycle"] == "clean" and report["eof"] is report["stdin_closed"] is True
    assert peer.joined and peer.attempts == 0 and not peer.bound_exceeded
    assert_report(report)
    write_evidence(f"n6-claude-startup-{model}.json", report)


async def test_pinned_credential_free_startup_has_only_a_noauth_observation():
    physical_launcher("fixture-startup")  # Required fixture/platform failures are never skips.
    report = await diagnostic.hosted_observation()
    write_evidence("n6-claude-pinned-startup.json", report)
    assert diagnostic.successful(report), report
    assert report["proxy_joined"] is True and report["proxy_bound_exceeded"] is False
    assert (type(report["proxy_accepted_connections"]) is int
            and 0 <= report["proxy_accepted_connections"] <= 8)
