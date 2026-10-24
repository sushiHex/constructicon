"""Separate credential-free policy-presence diagnostic; never qualification.

The original single-initialize observer remains unchanged. This sibling owns
one initialize and one get_settings under one deadline, reader and byte budget.
Only fixed policy-presence facts leave the process; settings and stderr do not.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import secrets
import sys
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import Digest
from constructicon.core.process import ProcessIO
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.claude_initialize import _clean
from constructicon.substrate.executors.claude_maintenance_mode import (
    ClaudeMaintenanceConversation,
    ClaudeMaintenancePhase,
)
from constructicon.substrate.executors.claude_maintenance_mode import (
    ClaudeMaintenanceRefusalCode as Refusal,
)
from constructicon.substrate.executors.claude_native import (
    POLICY_MOUNT,
    ClaudeNativeStoreMount,
    ClaudeNativeVendor,
)
from constructicon.substrate.executors.claude_protocol import ClaudePlan, initialize_request
from constructicon.substrate.executors.claude_startup import (
    ClaudeStartupVerdict,
    _body,
    settings_request,
)
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.executors.operator_store import BindingCheck

# The script entry point has src on sys.path, but need not have the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.ci import observe_m8_claude_startup as startup

SCOPE = "credential_free_native_settings_diagnostic"
SOURCES = ("userSettings", "projectSettings", "localSettings", "flagSettings", "policySettings")


class _SettingsFileControlVendor(ClaudeNativeVendor):
    """CI-only read of the same immutable policy through the explicit file flag."""

    @property
    def command(self) -> tuple[str, ...]:
        # Pinned 2.1.296: yNs B@220409963 reads and pins the file for flagSettings.
        return (*super().command, "--settings", POLICY_MOUNT)


def policy_presence(value: object, *, present: bool = True) -> dict[str, str]:
    """Closed projection; no unknown key, value, size or native digest escapes."""
    shape = "absent" if not present else "object" if type(value) is dict else "wrong-type"
    refresh = mcp = "absent"
    if type(value) is dict and present:
        if "forceRemoteSettingsRefresh" in value:
            field = value["forceRemoteSettingsRefresh"]
            refresh = "true" if field is True else "false" if field is False else "wrong-type"
        if "deniedMcpServers" in value:
            denied = value["deniedMcpServers"]
            mcp = ("wrong-type" if type(denied) is not list else "empty" if not denied
                   else "deny-all" if denied == [{"serverUrl": "*"}] else "other")
    return {"shape": shape, "refresh": refresh, "mcp": mcp}


def settings_presence(body: dict[str, object]) -> dict[str, object]:
    sources = body.get("sources")
    errors = body.get("errors")
    projected: dict[str, object] = {
        "effective": policy_presence(body.get("effective"), present="effective" in body),
        "errors_shape": ("absent" if "errors" not in body else
                         "wrong-type" if type(errors) is not list else
                         "nonempty" if errors else "empty"),
        "sources_shape": ("absent" if "sources" not in body else
                          "list" if type(sources) is list else "wrong-type"),
        "source_entry_invalid": False, "source_unknown": False, "source_duplicate": False,
        "sources": {name: policy_presence(None, present=False) for name in SOURCES},
    }
    seen: set[str] = set()
    if type(sources) is list:
        for source in sources:
            if type(source) is not dict or set(source) != {"source", "settings"}:
                projected["source_entry_invalid"] = True
                continue
            name = source["source"]
            if type(name) is not str or name not in SOURCES:
                projected["source_unknown"] = True
                continue
            if name in seen:
                projected["source_duplicate"] = True
                # Do not choose a winner from conflicting duplicate sources.
                projected["sources"][name] = {"shape": "duplicate", "refresh": "absent",
                                               "mcp": "absent"}
                continue
            seen.add(name)
            projected["sources"][name] = policy_presence(source["settings"])
    return projected


class _Refused(Exception):
    pass


class SettingsConversation(ClaudeMaintenanceConversation):
    """Reuse the owned byte reader, never the authenticated admission predicate."""

    def __init__(self, *, deadline: float, input_limit: int, output_limit: int) -> None:
        # The base owns framing only here; no plan classifier is invoked.
        super().__init__(phase=ClaudeMaintenancePhase.OBSERVE, selected_plan=ClaudePlan.PRO,
                         deadline=deadline, input_limit=input_limit,
                         output_limit=min(output_limit, startup.OUTPUT_BYTES))
        self.initialize_observed = self.settings_observed = self.reader_joined = False
        self.initialize_kind = "incomplete"
        self.presence: dict[str, object] | None = None

    async def _control(self, kind: str) -> None:
        while True:
            previous_bytes = self.output_bytes
            # Give the single pending reader a turn, including after consuming
            # a UI frame, before reserving the next control delivery.
            await asyncio.sleep(0)
            self._audit()
            self._consume_ui_records()
            if self.eof:
                self._latch(Refusal.EOF)
                raise _Refused()
            if self._buffer:
                # A partial UI is neither malformed nor evidence of quiescence.
                # Finish it under the same deadline; only exact UI may pass.
                await self._next_ui()
                continue
            if self.output_bytes == previous_bytes:
                break
        if self.request_writes >= 2:
            self._latch(Refusal.WRITE_LIMIT)
            raise _Refused()
        identifier = secrets.token_hex(16)
        if identifier in self._ids:
            self._latch(Refusal.REQUEST_ID_REUSE)
            raise _Refused()
        raw = (initialize_request(identifier) if kind == "initialize" else
               settings_request(identifier))
        if self.input_bytes + len(raw) > self.input_limit:
            self._latch(Refusal.INPUT_LIMIT)
            raise _Refused()
        self._ids.add(identifier)
        self.request_writes += 1  # Delivery is spent before its first await.
        self.input_bytes += len(raw)
        assert self._io is not None
        await self._io.write(raw)
        self._audit()
        while True:
            record = await self._next()
            if self._ui(record):
                continue
            if kind == "initialize":
                self.initialize_kind, _ = startup.classify(record, identifier)
                if self.initialize_kind != "correlated-noauth":
                    self._latch(Refusal.RESPONSE_VERDICT)
                    raise _Refused()
                self.initialize_observed = True
            else:
                body = _body(record, identifier)
                if isinstance(body, ClaudeStartupVerdict):
                    self._latch(Refusal.RESPONSE_VERDICT)
                    raise _Refused()
                self.presence = settings_presence(body)
                self.settings_observed = True
            return

    async def __call__(self, io: ProcessIO) -> None:
        if self._state != "new":
            self._latch(Refusal.STATE)
            self._state = "refused"
            owner = self._owner
            if owner is not None and owner is not asyncio.current_task() and not owner.done():
                owner.cancel()
            raise ContractViolation("settings diagnostic is single-use")
        self._state, self._io = "running", io
        self._owner = asyncio.current_task()
        self._start_read()
        try:
            for kind in ("initialize", "get_settings"):
                await self._control(kind)
            self._audit()
            self._consume_ui_records()
            if self.eof:
                self._latch(Refusal.EOF)
                raise _Refused()
            await io.close_stdin()
            self._check()
            self.stdin_closed = True
            await self._drain()
            self._check()
            self._state = "completed"
        except BaseException:
            self._state = "refused"
            raise
        finally:
            try:
                if self._reader is not None:
                    reader, self._reader = self._reader, None
                    if not reader.done():
                        reader.cancel()

                    async def join_reader() -> None:
                        with suppress(asyncio.CancelledError):
                            await reader

                    await finish_owned(asyncio.create_task(join_reader()))
                self.reader_joined = True
            finally:
                self._owner = None


async def observe_settings(
    launcher: LinuxLauncher, native_store: ClaudeNativeStoreMount, *, timeout_s: float = 20,
) -> dict[str, object]:
    if (type(timeout_s) not in (int, float) or not math.isfinite(timeout_s)
            or not 0 < timeout_s <= 20):
        raise ValueError("invalid diagnostic deadline")
    deadline = asyncio.get_running_loop().time() + timeout_s
    probe = SettingsConversation(deadline=deadline, input_limit=launcher.limits.input_bytes,
                                 output_limit=launcher.limits.stdout_bytes)
    checks = 0
    lifecycle = "failed"
    try:
        if type(native_store) is not ClaudeNativeStoreMount or launcher.claude is None:
            raise _Refused()
        checks += 1
        initial = native_store.before_spawn()
        if type(initial) is not BindingCheck:
            raise _Refused()

        def check_binding() -> BindingCheck:
            nonlocal checks
            if checks >= 3:
                raise _Refused()
            checks += 1
            current = native_store.before_spawn()
            if type(current) is not BindingCheck or current != initial:
                raise _Refused()
            return current

        try:
            async with asyncio.timeout_at(deadline):
                result = await launcher.exchange(
                    launcher.claude.command, workspace=None, posture=Posture.READ,
                    guard_fds=(native_store.lock_fd,), conversation=probe,
                    timeout_s=deadline - asyncio.get_running_loop().time(),
                    native_store=replace(native_store, before_spawn=check_binding),
                )
        except BaseException:
            with suppress(BaseException):
                check_binding()
            raise
        check_binding()
        lifecycle = "clean" if _clean(result) else "process-refused"
        if result.timed_out or asyncio.get_running_loop().time() >= deadline:
            lifecycle = "timeout"
    except TimeoutError:
        lifecycle = "timeout"
    except Exception:
        lifecycle = "failed"
    return {
        "schema_version": 1, "scope": SCOPE, "lifecycle": lifecycle,
        "exchange_completed": probe._state == "completed",
        "initialize_observed": probe.initialize_observed,
        "initialize_kind": probe.initialize_kind, "settings_observed": probe.settings_observed,
        "refusal_code": probe.refusal_code.value if probe.refusal_code is not None else None,
        "policy_presence": probe.presence, "request_writes": probe.request_writes,
        "accepted_ui_records": probe.ui_records, "stdin_closed": probe.stdin_closed,
        "eof": probe.eof, "reader_joined": probe.reader_joined, "binding_checks": checks,
        "production_available": False, "subscription_qualified": False, "claude_qualified": False,
    }


def successful(report: dict[str, object]) -> bool:
    """Completed observation, including absent/malformed policy, never admission."""
    return (report["lifecycle"] == "clean" and report["exchange_completed"] is True
            and report["initialize_observed"] is True and report["settings_observed"] is True
            and report["request_writes"] == 2 and report["stdin_closed"] is True
            and report["eof"] is True and report["reader_joined"] is True
            and report["binding_checks"] == 3 and report["refusal_code"] is None)


def settings_file_control_successful(report: dict[str, object]) -> bool:
    """Prove explicit-file visibility, never managed-tier or session admission."""
    if not successful(report):
        return False
    presence = report["policy_presence"]
    if not isinstance(presence, dict):
        return False
    sources = presence.get("sources")
    return (presence.get("sources_shape") == "list"
            and presence.get("source_entry_invalid") is False
            and presence.get("source_unknown") is False
            and presence.get("source_duplicate") is False
            and presence.get("errors_shape") in {"absent", "empty"}
            and isinstance(sources, dict)
            and sources.get("flagSettings") == {
                "shape": "object", "refresh": "true", "mcp": "deny-all"})


async def hosted_observation(*, settings_file_control: bool = False) -> dict[str, object]:
    if type(settings_file_control) is not bool:
        raise _Refused()
    if (sys.platform != "linux" or os.getuid() == 0
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"):
        raise _Refused()
    from scripts.ci.build_m8_claude_startup_fixture import (
        ARCHIVE_SHA256,
        MEMBER_SHA256,
        MEMBER_SIZE,
        VERSION,
    )

    pins = json.loads((startup.ROOT / "pinned-startup.json").read_text())
    fixture = json.loads((startup.ROOT / "fixture.json").read_text())
    if (pins.get("schema_version") != 1
            or pins.get("scope") != "credential_free_native_startup_fixture"
            or pins.get("version") != VERSION or pins.get("archive_sha256") != ARCHIVE_SHA256
            or pins.get("member_sha256") != MEMBER_SHA256 or pins.get("member_size") != MEMBER_SIZE
            or any(pins.get(key) is not False for key in (
                "production_available", "subscription_qualified", "claude_qualified"))):
        raise _Refused()
    vendor = _SettingsFileControlVendor if settings_file_control else ClaudeNativeVendor
    launcher = LinuxLauncher(
        runtime_root=startup.ROOT / "pinned-runtime",
        expected_runtime=Digest(pins["runtime_digest"]),
        bubblewrap=startup.ROOT / "bwrap", policy=startup.POLICY,
        expected_policy_sha256=fixture["policy_sha256"],
        claude=vendor(startup.ROOT / "pinned-vendor", startup.MODEL, startup.EFFORT,
                      Digest(pins["vendor_digest"])),
    )
    deadline = asyncio.get_running_loop().time() + 20
    async with startup.fake_store(deadline) as (mount, peer):
        report = await observe_settings(launcher, mount,
                                        timeout_s=deadline - asyncio.get_running_loop().time())
    report.update({"proxy_accepted_connections": peer.attempts,
                   "proxy_bound_exceeded": peer.bound_exceeded, "proxy_joined": peer.joined})
    return report


def main() -> int:
    try:
        if len(sys.argv) != 1:
            raise _Refused()
        report = asyncio.run(hosted_observation())
    except (Exception, asyncio.CancelledError):
        report = {"schema_version": 1, "scope": SCOPE, "lifecycle": "failed",
                  "production_available": False, "subscription_qualified": False,
                  "claude_qualified": False}
        print(json.dumps(report, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if successful(report) and report["proxy_joined"] is True and not (
        report["proxy_bound_exceeded"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
