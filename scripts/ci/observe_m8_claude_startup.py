"""One hosted, credential-free startup observation; never subscription admission.

The callback is shared by portable fakes, the physical fake controls and the
pinned CLI. No user message, SDK registration, login or upstream dial exists.
Only finite facts leave this diagnostic; vendor frames and errors stay private.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import secrets
import socket
import stat
import sys
import tempfile
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager, suppress
from dataclasses import replace
from pathlib import Path
from types import TracebackType

from constructicon.core.grants import Posture
from constructicon.core.identity import Digest, digest, parse_json_value
from constructicon.core.process import ProcessIO
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.claude_initialize import _clean
from constructicon.substrate.executors.claude_native import (
    ClaudeNativeStoreMount,
    ClaudeNativeVendor,
)
from constructicon.substrate.executors.claude_protocol import (
    CLAUDE_CODE_VERSION,
    RECORD_BYTES,
    initialize_request,
)
from constructicon.substrate.executors.egress import EgressSocket
from constructicon.substrate.executors.linux import (
    LinuxLauncher,
    ProcessExchangeError,
    ProcessResult,
)
from constructicon.substrate.executors.operator_store import BindingCheck

ROOT = Path("/var/lib/constructicon-m8-claude")
POLICY = Path("/etc/apparmor.d/constructicon-m8-claude")
MODEL = "claude-sonnet-4-6"
EFFORT = "low"
OUTPUT_BYTES = RECORD_BYTES + 8192
PROXY_ATTEMPTS = 8
SCOPE = "credential_free_native_startup_observation"


class _Refused(Exception):
    pass


def classify(record: bytes, identifier: str) -> str:
    """Classify one private correlated frame; mismatch alone is not no-auth."""
    if (type(record) is not bytes or len(record) > RECORD_BYTES
            or not record.endswith(b"\n") or b"\n" in record[:-1] or b"\r" in record):
        return "invalid"
    try:
        value = parse_json_value(record[:-1].decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        return "invalid"
    if (type(value) is not dict or set(value) != {"type", "response"}
            or value["type"] != "control_response" or type(value["response"]) is not dict):
        return "invalid"
    envelope = value["response"]
    if (set(envelope) != {"subtype", "request_id", "response",
                          "pending_permission_requests", "pending_user_dialog_requests"}
            or envelope["subtype"] != "success"
            or type(envelope["request_id"]) is not str
            or envelope["request_id"] != identifier
            or envelope["pending_permission_requests"] != []
            or envelope["pending_user_dialog_requests"] != []):
        return "invalid"
    body = envelope["response"]
    if (type(body) is not dict or body.get("claude_code_version") != CLAUDE_CODE_VERSION
            or body.get("session_state") != "idle" or type(body.get("account")) is not dict):
        return "invalid"
    account = body["account"]
    if (not set(account) <= {"apiProvider", "tokenSource", "apiKeySource", "subscriptionType",
                            "email", "organization"}
            or any(type(item) is not str for item in account.values())):
        return "invalid"
    if account == {"apiProvider": "firstParty", "tokenSource": "none"}:
        return "correlated-noauth"
    return "other-mode"


class _Probe:
    def __init__(self, *, deadline: float, input_limit: int, output_limit: int) -> None:
        self.deadline, self.input_limit = deadline, input_limit
        self.output_limit = min(output_limit, OUTPUT_BYTES)
        self.protocol = "incomplete"
        self.writes = 0
        self.close_attempted = self.closed = self.eof = False
        self.output_bytes = 0
        self.used = False

    def check(self) -> None:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError()
        if asyncio.get_running_loop().time() >= self.deadline:
            raise TimeoutError()

    async def read(self, io: ProcessIO, maximum: int = 8192) -> bytes:
        self.check()
        value = await io.read(maximum)
        self.check()
        if type(value) is not bytes or len(value) > maximum:
            self.protocol = "invalid"
            raise _Refused()
        self.output_bytes += len(value)
        if self.output_bytes > self.output_limit:
            self.protocol = "invalid"
            raise _Refused()
        if not value:
            self.eof = True
        return value

    async def close(self, io: ProcessIO) -> None:
        if self.close_attempted:
            return
        self.check()
        self.close_attempted = True
        await io.close_stdin()
        self.check()
        self.closed = True

    async def __call__(self, io: ProcessIO) -> None:
        if self.used:
            self.protocol = "invalid"
            raise _Refused()
        self.used = True
        self.check()
        identifier = secrets.token_hex(16)
        request = initialize_request(identifier)
        if len(request) > self.input_limit:
            raise _Refused()
        self.writes = 1  # Delivery is spent before its first await.
        await io.write(request)
        self.check()
        buffered = bytearray()
        while True:
            chunk = await self.read(io, min(8192, RECORD_BYTES - len(buffered)))
            if not chunk:
                break
            buffered.extend(chunk)
            newline = buffered.find(b"\n")
            if newline >= 0:
                self.protocol = classify(bytes(buffered[:newline + 1]), identifier)
                if newline + 1 != len(buffered):
                    self.protocol = "invalid"
                break
            if len(buffered) == RECORD_BYTES:
                self.protocol = "invalid"
                break
        # Protocol I/O failure/cancellation is joined by LinuxLauncher. Never
        # await a second protocol operation after its deadline/cancellation fired.
        await self.close(io)
        while not self.eof:
            if await self.read(io):
                self.protocol = "invalid"


async def observe_startup(
    launcher: LinuxLauncher, native_store: ClaudeNativeStoreMount, *, timeout_s: float = 20,
) -> dict[str, object]:
    """Observe one owned native exchange, never a reusable public passed latch."""
    if (type(timeout_s) not in (int, float) or not math.isfinite(timeout_s)
            or not 0 < timeout_s <= 60):
        raise ValueError("invalid diagnostic deadline")
    deadline = asyncio.get_running_loop().time() + timeout_s
    probe = _Probe(deadline=deadline, input_limit=launcher.limits.input_bytes,
                   output_limit=launcher.limits.stdout_bytes)
    checks = 0
    lifecycle = "failed"
    result: ProcessResult | None = None
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
            checked = native_store.before_spawn()
            if type(checked) is not BindingCheck or checked != initial:
                raise _Refused()
            return checked

        launch_store = replace(native_store, before_spawn=check_binding)
        try:
            async with asyncio.timeout_at(deadline):
                result = await launcher.exchange(
                    launcher.claude.command, workspace=None, posture=Posture.READ,
                    guard_fds=(native_store.lock_fd,), conversation=probe,
                    timeout_s=deadline - asyncio.get_running_loop().time(),
                    native_store=launch_store,
                )
        except BaseException:
            with suppress(BaseException):
                check_binding()
            raise
        check_binding()
        lifecycle = "clean" if _clean(result) else "process-refused"
        if result.timed_out:
            lifecycle = "timeout"
    except TimeoutError:
        lifecycle = "timeout"
    except ProcessExchangeError as error:
        result = error.result
        lifecycle = "failed"
    except Exception:
        lifecycle = "failed"
    observed = result if type(result) is ProcessResult else None
    return {
        "schema_version": 1, "scope": SCOPE, "protocol": probe.protocol,
        "lifecycle": lifecycle, "request_writes": probe.writes,
        "stdin_closed": probe.closed, "eof": probe.eof, "binding_checks": checks,
        "supervisor_returncode": (
            observed.returncode if observed is not None and type(observed.returncode) is int
            and -255 <= observed.returncode <= 255 else None
        ),
        "payload_returncode": (
            observed.payload_returncode if observed is not None
            and type(observed.payload_returncode) is int
            and 0 <= observed.payload_returncode <= 255 else None
        ),
        "process_timed_out": observed.timed_out if observed is not None
        and type(observed.timed_out) is bool else None,
        "process_bound_exceeded": observed.bound_exceeded is not None if observed else None,
        "production_available": False, "subscription_qualified": False, "claude_qualified": False,
    }


def successful(report: dict[str, object]) -> bool:
    """Diagnostic completion only, never a production/subscription admission API."""
    return (report["protocol"] == "correlated-noauth" and report["lifecycle"] == "clean"
            and report["request_writes"] == 1 and report["stdin_closed"] is True
            and report["eof"] is True and report["binding_checks"] == 3)


class DenyPeer:
    """One bounded accepting socket; every accepted connection closes unread."""

    def __init__(self, listener: socket.socket, *, deadline: float) -> None:
        self.listener, self.deadline = listener, deadline
        self.attempts = 0
        self.bound_exceeded = self.joined = False
        self.task: asyncio.Task[None] | None = None

    async def serve(self) -> None:
        try:
            async with asyncio.timeout_at(self.deadline):
                while True:
                    connection, _ = await asyncio.get_running_loop().sock_accept(self.listener)
                    connection.close()
                    self.attempts += 1
                    if self.attempts > PROXY_ATTEMPTS:
                        self.bound_exceeded = True
                        return
        except (TimeoutError, asyncio.CancelledError):
            return
        finally:
            self.listener.close()

    async def __aenter__(self) -> DenyPeer:
        self.task = asyncio.create_task(self.serve())
        return self

    async def __aexit__(
        self, kind: type[BaseException] | None, error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        task = self.task
        assert task is not None
        task.cancel()

        async def join() -> None:
            results = await asyncio.gather(task, return_exceptions=True)
            if isinstance(results[0], BaseException) and not isinstance(
                results[0], asyncio.CancelledError,
            ):
                raise results[0]

        try:
            await finish_owned(asyncio.create_task(join()))
        except BaseException:
            if error is None:
                raise
        else:
            self.joined = True
        finally:
            self.listener.close()


@asynccontextmanager
async def fake_store(deadline: float) -> AsyncIterator[tuple[ClaudeNativeStoreMount, DenyPeer]]:
    """Disposable empty fake credential and retained lock; no real store is read."""
    import fcntl

    with tempfile.TemporaryDirectory(prefix="m8-startup-") as directory, ExitStack() as owned:
        root = Path(directory)
        lock_fd = os.open(root / "lock", os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        owned.callback(os.close, lock_fd)
        credential_fd = os.open(root / "credential", os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        owned.callback(os.close, credential_fd)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        owned.callback(listener.close)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            path = root / "deny.sock"
            listener.bind(str(path))
            listener.listen(PROXY_ATTEMPTS)
            listener.setblocking(False)
            info = path.stat()
            leaf = EgressSocket(path, (info.st_dev, info.st_ino))
            opened = os.fstat(credential_fd)
            expected = opened.st_dev, opened.st_ino, opened.st_uid, opened.st_nlink

            def check() -> BindingCheck:
                named, held = os.lstat(root / "credential"), os.fstat(credential_fd)
                for current in (named, held):
                    if (not stat.S_ISREG(current.st_mode) or current.st_mode & 0o777 != 0o600
                            or (current.st_dev, current.st_ino, current.st_uid,
                                current.st_nlink) != expected):
                        raise _Refused()
                return BindingCheck(digest("startup-empty-fake-binding", 1, list(expected)))

            async with DenyPeer(listener, deadline=deadline) as peer:
                yield ClaudeNativeStoreMount(lock_fd, credential_fd, check, leaf), peer
        finally:
            listener.close()


async def hosted_observation() -> dict[str, object]:
    if (sys.platform != "linux" or os.getuid() == 0
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"):
        raise _Refused()
    # Direct script invocation need not have the checkout root on sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.ci.build_m8_claude_startup_fixture import (
        ARCHIVE_SHA256,
        MEMBER_SHA256,
        MEMBER_SIZE,
        VERSION,
    )

    pins = json.loads((ROOT / "pinned-startup.json").read_text())
    fixture = json.loads((ROOT / "fixture.json").read_text())
    if (pins.get("schema_version") != 1
            or pins.get("scope") != "credential_free_native_startup_fixture"
            or pins.get("version") != VERSION or pins.get("archive_sha256") != ARCHIVE_SHA256
            or pins.get("member_sha256") != MEMBER_SHA256
            or pins.get("member_size") != MEMBER_SIZE
            or any(pins.get(key) is not False for key in (
                "production_available", "subscription_qualified", "claude_qualified"))):
        raise _Refused()
    vendor_digest = Digest(pins["vendor_digest"])
    pinned_runtime_digest = Digest(pins["runtime_digest"])
    launcher = LinuxLauncher(
        runtime_root=ROOT / "pinned-runtime", expected_runtime=pinned_runtime_digest,
        bubblewrap=ROOT / "bwrap", policy=POLICY,
        expected_policy_sha256=fixture["policy_sha256"],
        claude=ClaudeNativeVendor(ROOT / "pinned-vendor", MODEL, EFFORT,
                                  vendor_digest),
    )
    deadline = asyncio.get_running_loop().time() + 20
    async with fake_store(deadline) as (mount, peer):
        report = await observe_startup(launcher, mount,
                                       timeout_s=deadline - asyncio.get_running_loop().time())
    # Accepted/refused connections are observed; a zero count does not claim
    # that no connect attempt was queued when the listener was withdrawn.
    report.update({"proxy_accepted_connections": peer.attempts,
                   "proxy_bound_exceeded": peer.bound_exceeded,
                   "proxy_joined": peer.joined, "launch_revision": str(launcher.revision),
                   "vendor_digest": str(vendor_digest), "member_sha256": MEMBER_SHA256,
                   "runtime_digest": str(pinned_runtime_digest),
                   "archive_sha256": ARCHIVE_SHA256, "member_size": MEMBER_SIZE,
                   "version": VERSION})
    return report


def main() -> int:
    try:
        if len(sys.argv) != 1:
            raise _Refused()
        report = asyncio.run(hosted_observation())
    except (Exception, asyncio.CancelledError):
        print(json.dumps({"schema_version": 1, "scope": SCOPE, "lifecycle": "failed",
                          "production_available": False, "subscription_qualified": False,
                          "claude_qualified": False}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if successful(report) and report["proxy_joined"] is True and not (
        report["proxy_bound_exceeded"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
