"""The N4 operator lanes: device login and the no-model startup, under custody.

An offline operator helper beside the store's publication, maintenance and
activation helpers (M8-N4-state-review.md, section 5). It composes existing
parts only: the store's custody, the sealed configuration, the egress relay,
the launcher and :class:`CodexConversation` stopped at its first readback. It is
not a provider and adds no availability: nothing here can clear
``vendor_conformance_qualified``.

Two lanes, each one native launch in the real zone behind the relay:

* ``login`` runs the unmodified client's ``login --device-auth``, and only
  inside maintenance: a login rewrites the credential, which ADR 0021 allows
  only after a durable withdrawal. Its stdout carries the one-time code and
  goes to the operator's terminal only; nothing of it is kept.
* ``startup`` runs the four authorized methods (``initialize``,
  ``initialized``, ``account/read``, ``account/rateLimits/read``) under either
  maintenance (qualification) or the active selection.

Maintenance is root's (host-runtime decision 1). Root's store helper withdraws
and starts a maintenance lane as the service holding only the inherited lock
(``operator_store.run_under_maintenance``). The lane proves that custody before
anything else (``operator_store.inherit_maintenance``) and never runs as root.

A lane passes only on affirmative facts, each recorded; a missing one is a
fault that names it. Evidence is a closed record: its path is reserved before
any launch, and it appears under its final name only once it is complete and
synced. A missing file is a failed run. It never holds stdout, stderr text, an
email, an account id, a token, credential bytes or a hostname outside the
sealed policy.
"""

from __future__ import annotations

import argparse
import asyncio
import errno
import hashlib
import json
import os
import secrets
import stat
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Literal

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.core.process import ProcessIO
from constructicon.substrate.executors.codex import (
    ADAPTER_REVISION,
    PROTOCOL_REVISION,
    CodexConversation,
    configuration_digest,
    configured_model,
    configured_provider,
)
from constructicon.substrate.executors.codex_protocol import (
    SPEND_FIELDS,
    USAGE_FIELDS,
    ExpectedAccount,
    bounded_detail,
    named_method,
    parse_record,
)
from constructicon.substrate.executors.egress import (
    EgressDestination,
    EgressPolicy,
    EgressRelay,
    identity_digests,
)
from constructicon.substrate.executors.linux import (
    CATALOG_MOUNT,
    VENDOR_MOUNT,
    LinuxLauncher,
    NativeStoreMount,
    NativeVendor,
    ProcessExchangeError,
    ProcessResult,
    sealed_data_fd,
)
from constructicon.substrate.executors.operator_store import (
    BindingCheck,
    BindingStore,
    StoreMaintenance,
    credential_facts,
    inherit_maintenance,
)

LANE_SCHEMA = 2
LOGIN_ARGUMENTS = ("login", "--device-auth")
STARTUP_ARGUMENTS = ("app-server", "--strict-config", "--stdio")
STARTUP_METHODS = ("initialize", "initialized", "account/read", "account/rateLimits/read")
"""The owner's authorization for the startup lane, in order: nothing else is sent."""
QUALIFICATION_PLANS = ("pro", "prolite")
"""What the owner-attended S4 qualification may observe and seal (M8-N4-state-review.md,
orchestrator decision 1); the operator cannot narrow or widen this with a flag."""
RUNTIME_BINARY = VENDOR_MOUNT + "/bin/codex"
RUNTIME_CATALOG = CATALOG_MOUNT
"""In-zone paths of the bound vendor tree's client and the bound model catalog."""
LOGIN_DEADLINE_S = 960.0
"""The pinned device flow polls for up to 15 minutes
(``login/src/device_code_auth.rs:108``); 60 s more covers the launcher's probe,
the relay and the client's own start."""
STARTUP_DEADLINE_S = 120.0
REFRESH_DESTINATION = "auth.openai.com:443"
"""Where a proactive refresh goes (``login/src/auth/manager.rs:197``)."""
DENIAL_FAULT = "the relay denied a connection in a lane expected to be clean"
EVIDENCE_DOMAIN = "codex-authenticated-startup-evidence"
LANE_GRANTS = EffectiveGrants(
    posture=Posture.READ,
    model_selection=ModelSelection(kind="explicit", model="unused-by-startup"),
    effort="low", allowed_tools=(), env_allowlist=(), network="allow", timeout_s=600,
)
"""The conversation requires sealed grants; the startup phase sends none of them."""
LOGIN_FIELDS = frozenset({
    "schema_version", "lane", "custody", "adapter_revision", "protocol_revision",
    "launch_revision", "runtime_digest", "executable", "configuration_digest", "egress",
    "relay", "credential", "process", "vendor_identity", "vendor_conformance_qualified",
    "faults",
})
"""The closed login record; the state review's schema block lists the same keys."""
STARTUP_FIELDS = LOGIN_FIELDS | {
    "methods_sent", "withheld_methods", "gate", "readback", "observation", "refresh", "hold_s",
}
"""The closed startup record, likewise."""


@dataclass(frozen=True)
class Custody:
    """What one launch needs from the store: a lock, a credential, a check."""

    kind: Literal["maintenance", "active"]
    lock_fd: int
    open_credential: Callable[[], int]
    check: Callable[[], BindingCheck]
    detail: Mapping[str, Any]
    facts: Callable[[int], tuple[int, int, int]] = credential_facts
    create_credential: Callable[[], None] | None = None


def maintenance_custody(maintenance: StoreMaintenance) -> Custody:
    return Custody(
        "maintenance", maintenance.lock_fd, maintenance.open_credential, maintenance.check,
        {"generation_floor": maintenance.generation_floor},
        create_credential=maintenance.create_credential,
    )


@asynccontextmanager
async def active_custody(store: BindingStore) -> AsyncIterator[Custody]:
    """The provider's own custody path over the active selection (runbook S8)."""

    async def open_closure() -> None:
        return None

    held = await store.acquire_lock(store.open_candidate(), lambda: None, open_closure)
    try:
        yield Custody(
            "active", held.lock_fd, lambda: store.open_credential(held),
            lambda: store.check_held(held),
            {"binding_digest": str(store.check_held(held).binding_digest)},
        )
    finally:
        store.close_held(held)


@dataclass(frozen=True)
class Executable:
    """The in-zone client that receives the credential, by path and content."""

    path: str
    sha256: str


def vendor_executable(launcher: LinuxLauncher) -> Executable:
    """The bound vendor tree's client, hashed from the launch set it is bound from."""

    if launcher.vendor is None:
        raise ContractViolation("an N4 lane runs only the bound vendor client")
    with (launcher.vendor.tree / "bin" / "codex").open("rb") as stream:
        return Executable(RUNTIME_BINARY, hashlib.file_digest(stream, "sha256").hexdigest())


class RecordingIO:
    """Pass-through ``ProcessIO`` that records the method of each written record."""

    def __init__(self, io: ProcessIO) -> None:
        self._io = io
        self.methods: list[str] = []

    async def read(self, maximum: int = 8192) -> bytes:
        return await self._io.read(maximum)

    async def write(self, data: bytes) -> None:
        await self._io.write(data)
        with suppress(ValueError, TypeError, RecursionError):
            record = parse_record(data.rstrip(b"\n"))
            if isinstance(record, dict) and "method" in record:
                self.methods.append(named_method(record["method"]))

    async def close_stdin(self) -> None:
        await self._io.close_stdin()


@dataclass
class Launched:
    result: ProcessResult
    exchange_failed: bool
    destinations: dict[str, int]
    denied: dict[str, int]
    relay_closed: bool
    credential: dict[str, bool]


async def launch(
    custody: Custody, launcher: LinuxLauncher, policy: EgressPolicy,
    command: tuple[str, ...], conversation: Callable[[ProcessIO], Any], *,
    configuration: str, lane_dir: Path, deadline_s: float,
) -> Launched:
    """One native launch in the real zone, behind the relay, under custody.

    After the exchange it measures, rather than assumes, what the verdict needs:
    the credential's own metadata through the descriptor that was bound, and a
    terminal custody check (CC-2, RL-4).
    """

    lane_dir.mkdir(mode=0o700)  # fresh, or refuse: FileExistsError
    deadline = asyncio.get_running_loop().time() + deadline_s
    mount_fds: list[int] = []
    try:
        mount_fds.append(custody.open_credential())
        mount_fds.append(sealed_data_fd(configuration.encode("utf-8")))
        before = os.fstat(mount_fds[0]).st_mtime_ns
        relay = EgressRelay(policy, lane_dir / "relay", deadline, lambda: None)
        exchange_failed = False
        async with relay as leaf:
            mount = NativeStoreMount(
                lock_fd=custody.lock_fd, configuration_fd=mount_fds[1],
                credential_fd=mount_fds[0], before_spawn=custody.check, egress=leaf,
            )
            try:
                result = await launcher.exchange(
                    command, workspace=None, posture=Posture.READ,
                    guard_fds=(custody.lock_fd,), conversation=conversation,
                    timeout_s=deadline_s, native_store=mount,
                )
            except ProcessExchangeError as exc:
                result, exchange_failed = exc.result, True
        mode, links, _ = custody.facts(mount_fds[0])
        try:
            custody.check()
            checked = True
        except (OSError, ContractViolation):
            checked = False
        return Launched(
            result=result, exchange_failed=exchange_failed,
            destinations=dict(relay.destinations),
            denied={key: value for key, value in relay.observed.items()
                    if key.startswith("denied:")},
            relay_closed=relay.closed is True,
            credential={
                "present": links == 1,
                "regular_0600": stat.S_ISREG(mode) and stat.S_IMODE(mode) == 0o600,
                "mtime_changed": os.fstat(mount_fds[0]).st_mtime_ns != before,
                "checked": checked,
            },
        )
    finally:
        for fd in mount_fds:
            with suppress(OSError):
                os.close(fd)
        with suppress(OSError):
            lane_dir.rmdir()


def _process(launched: Launched) -> dict[str, Any]:
    result = launched.result
    return {
        "returncode": result.returncode, "payload_returncode": result.payload_returncode,
        "timed_out": result.timed_out, "bound_exceeded": result.bound_exceeded is not None,
        "exchange_failed": launched.exchange_failed,
        "elapsed_s": round(result.elapsed_s, 3), "stderr_bytes": len(result.stderr),
    }


def launch_faults(launched: Launched) -> list[str]:
    """The facts every lane must show affirmatively; each absent one is named."""

    result = launched.result
    checks = (
        (not launched.exchange_failed, "the exchange raised after the launch"),
        (not result.timed_out, "the launch timed out"),
        (result.bound_exceeded is None, "a launch bound was exceeded"),
        (result.returncode == 0 and result.payload_returncode == 0,
         "the native client did not exit cleanly"),
        (launched.relay_closed, "the relay did not close cleanly"),
        (launched.credential["checked"], "the terminal custody check failed"),
        (launched.credential["present"] and launched.credential["regular_0600"],
         "the credential is not one regular 0600 file after the run"),
    )
    return [fault for holds, fault in checks if not holds]


def _base(lane: str, custody: Custody, launcher: LinuxLauncher, policy: EgressPolicy,
          executable: Executable, configuration: str, launched: Launched) -> dict[str, Any]:
    return {
        "schema_version": LANE_SCHEMA, "lane": lane,
        "custody": {"kind": custody.kind, **dict(custody.detail)},
        "adapter_revision": str(ADAPTER_REVISION),
        "protocol_revision": str(PROTOCOL_REVISION),
        "launch_revision": str(launcher.revision),
        "runtime_digest": str(launcher.expected_runtime),
        "executable": {"path": executable.path, "sha256": executable.sha256},
        "configuration_digest": str(configuration_digest(configuration)),
        "egress": {key: str(value) for key, value in identity_digests(policy).items()},
        "relay": {"destinations": launched.destinations, "denied": launched.denied,
                  "closed": launched.relay_closed},
        "credential": dict(launched.credential),
        "process": _process(launched),
        "vendor_identity": "unverified",
        "vendor_conformance_qualified": False,
    }


async def run_login(
    custody: Custody, launcher: LinuxLauncher, policy: EgressPolicy, *,
    executable: Executable, configuration: str, lane_dir: Path, deadline_s: float,
    out: BinaryIO, first_login: bool = False,
) -> dict[str, Any]:
    """The unmodified client's device login; its output reaches ``out`` only.

    Maintenance only (CC-1): a login rewrites the credential in place, and ADR
    0021 allows that only after a durable withdrawal. ``first_login`` creates
    the empty credential file the bind needs, create-exclusive, under the same
    custody (runbook S2).
    """

    if custody.kind != "maintenance":
        raise ContractViolation("a device login runs only inside maintenance")
    if first_login:
        if custody.create_credential is None:
            raise ContractViolation("this custody cannot create a first credential")
        custody.create_credential()

    async def relay_to_operator(io: ProcessIO) -> None:
        while chunk := await io.read(8192):
            out.write(chunk)
            out.flush()
        await io.close_stdin()

    launched = await launch(
        custody, launcher, policy, (executable.path, *LOGIN_ARGUMENTS), relay_to_operator,
        configuration=configuration, lane_dir=lane_dir, deadline_s=deadline_s,
    )
    faults = [DENIAL_FAULT] if launched.denied else []
    faults += launch_faults(launched)
    if not launched.credential["mtime_changed"]:
        faults.append("the device login wrote no credential")
    return {**_base("login", custody, launcher, policy, executable, configuration, launched),
            "faults": faults}


async def run_startup(
    custody: Custody, launcher: LinuxLauncher, policy: EgressPolicy, *,
    executable: Executable, configuration: str, expected: ExpectedAccount, lane_dir: Path,
    deadline_s: float, expect_denial: bool = False, hold_s: float = 0.0,
) -> dict[str, Any]:
    """The four authorized methods, then stdin closes; never a thread.

    A pass is affirmative (SPEND-1, RL-1): the gate completed, exactly the four
    methods were sent in order, a readback was judged, the session emitted no
    damage, and every launch fact holds. ``hold_s`` pauses after the gate and
    before stdin closes, while the zone is live (RL-3), within the deadline.
    """

    if not 0 <= hold_s < deadline_s:
        raise ContractViolation("the startup hold must lie inside the deadline")
    pause: Callable[[], Awaitable[None]] | None = None
    if hold_s:
        async def hold() -> None:
            await asyncio.sleep(hold_s)

        pause = hold
    conversation = CodexConversation(
        task=TaskSpec(instruction="unused by the startup phase"),
        grants=LANE_GRANTS.model_copy(update={"model_selection": ModelSelection(
            kind="explicit", model=configured_model(configuration),
        )}),
        expected=expected, input_limit=launcher.limits.input_bytes, startup_only=True,
        provider=configured_provider(configuration), pause=pause,
    )
    recorded: list[RecordingIO] = []

    async def converse(io: ProcessIO) -> None:
        recording = RecordingIO(io)
        recorded.append(recording)
        await conversation(recording)

    launched = await launch(
        custody, launcher, policy, (executable.path, *STARTUP_ARGUMENTS), converse,
        configuration=configuration, lane_dir=lane_dir, deadline_s=deadline_s,
    )
    methods = recorded[0].methods if recorded else []
    observation = conversation.observation
    faults = [bounded_detail(fault) for fault in conversation.faults]
    checks = (
        (conversation.gate_completed, "the startup gate did not complete"),
        (methods == [named_method(method) for method in STARTUP_METHODS],
         "the startup did not send exactly the four authorized methods"),
        (conversation.before_spend is not None, "no spend readback was judged"),
        (not observation.malformed_records and observation.first_error is None,
         "the session emitted damaged or unattributed records"),
    )
    faults += [fault for holds, fault in checks if not holds]
    faults += launch_faults(launched)
    if bool(launched.denied) != expect_denial:
        faults.append(
            DENIAL_FAULT if launched.denied else "the declared control denial did not occur"
        )
    reading = conversation.before_spend
    refreshed = (
        launched.destinations.get("accepted:" + REFRESH_DESTINATION, 0) > 0
        and launched.credential["mtime_changed"] and not faults
    )
    return {
        **_base("startup", custody, launcher, policy, executable, configuration, launched),
        "methods_sent": methods,
        "withheld_methods": list(conversation.withheld_methods),
        "gate": {"completed": conversation.gate_completed, "plan": conversation.observed_plan},
        "readback": None if reading is None else {
            name: getattr(reading, name) for name in (*SPEND_FIELDS, *USAGE_FIELDS)
        },
        "observation": {
            "malformed_records": observation.malformed_records,
            "first_error": observation.first_error is not None,
        },
        "refresh": "measured" if refreshed else "unmeasured",
        "hold_s": hold_s,
        "faults": faults,
    }


# --- evidence ------------------------------------------------------------------

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _fsync_directory(path: Path) -> None:
    flag = getattr(os, "O_DIRECTORY", None)
    if flag is None:
        return  # Windows cannot open a directory; the lane itself runs on Linux
    fd = os.open(path, os.O_RDONLY | flag)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class EvidenceFile:
    """A lane's evidence path, reserved before any launch and published once.

    Reserving creates a create-exclusive temporary beside the final name, so a
    duplicate, unwritable or missing-parent path refuses before any vendor
    traffic (RL-2). Publishing writes the whole record, syncs it, and only then
    links it to the final name, which never replaces an existing file; any
    failure removes both, so a failed run leaves no file there (RL-6).
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        if os.path.lexists(path):
            raise FileExistsError(errno.EEXIST, "the evidence path already exists", str(path))
        self.temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.pending")
        self._fd = os.open(
            self.temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW, 0o600,
        )
        self._linked = False

    def publish(self, evidence: Mapping[str, Any]) -> Digest:
        """Write, sync, link: returns the evidence digest, the conformance revision.

        Activation does not itself verify that digest (M8-N4-state-review.md,
        orchestrator decision 5).
        """

        try:
            if "completed" in evidence:
                raise ContractViolation("evidence marks itself completed only as its last act")
            complete = {**evidence, "completed": True}
            raw = (json.dumps(complete, ensure_ascii=True, allow_nan=False) + "\n").encode()
            view = memoryview(raw)
            while view:
                written = os.write(self._fd, view)
                if written <= 0:
                    raise ContractViolation("the lane evidence was not written")
                view = view[written:]
            os.fsync(self._fd)
            os.close(self._fd)
            self._fd = -1
            os.link(self.temporary, self.path)
            self._linked = True
            os.unlink(self.temporary)
            _fsync_directory(self.path.parent)
        except BaseException:
            self.abandon()
            raise
        return digest(EVIDENCE_DOMAIN, 1, json.loads(canonical_json(complete)))

    def abandon(self) -> None:
        if self._fd >= 0:
            with suppress(OSError):
                os.close(self._fd)
            self._fd = -1
        with suppress(FileNotFoundError):
            os.unlink(self.temporary)
        if self._linked:
            with suppress(FileNotFoundError):
                os.unlink(self.path)
            self._linked = False


def write_evidence(path: Path, evidence: Mapping[str, Any]) -> Digest:
    """Reserve and publish at once, for a caller that ran nothing in between."""

    return EvidenceFile(path).publish(evidence)


# --- the operator's command line ---------------------------------------------


def _launcher(root: Path) -> LinuxLauncher:
    """The installed runtime and launch set, from its reviewed manifest."""

    manifest = json.loads((root / "runtime.json").read_text(encoding="utf-8"))
    return LinuxLauncher(
        runtime_root=root / "runtime", expected_runtime=Digest(manifest["runtime_digest"]),
        bubblewrap=root / "bwrap", policy=Path(manifest["policy"]),
        expected_policy_sha256=manifest["policy_sha256"],
        vendor=NativeVendor(root / "native-codex", root / "codex-models.json"),
    )


def _policy(path: Path) -> EgressPolicy:
    value = json.loads(path.read_text(encoding="utf-8"))
    return EgressPolicy(
        destinations=tuple(
            EgressDestination(host, port, address)
            for host, port, address in value["destinations"]
        ),
        connections=value["connections"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex_lane", allow_abbrev=False)
    parser.add_argument("lane", choices=("login", "startup"))
    parser.add_argument("--custody", choices=("maintenance", "active"), default="maintenance")
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--sealed", type=Path, help="the active selection's store identity")
    parser.add_argument("--lock-fd", type=int, help="the root helper's inherited lock")
    parser.add_argument("--floor", type=int, help="the root helper's withdrawal floor")
    parser.add_argument("--launch-root", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--lane-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--first-login", action="store_true")
    parser.add_argument("--expected")
    parser.add_argument("--expect-denial", action="store_true")
    parser.add_argument("--hold", type=float, default=0.0)
    parser.add_argument("--deadline", type=float)
    options = parser.parse_args(argv)
    login = options.lane == "login"
    deadline = options.deadline if options.deadline is not None else (
        LOGIN_DEADLINE_S if login else STARTUP_DEADLINE_S
    )
    if login and options.custody != "maintenance":
        parser.error("a device login runs only inside maintenance")
    if options.first_login and not login:
        parser.error("--first-login belongs to the login lane")
    if not 0 <= options.hold < deadline or (options.hold and login):
        parser.error("--hold is a startup pause inside the deadline")
    if options.custody == "active" and options.sealed is None:
        parser.error("--custody active requires --sealed")
    if options.custody == "maintenance" and (options.lock_fd is None or options.floor is None):
        parser.error("a maintenance lane runs only under `operator_store maintain`")
    if not login and options.custody == "maintenance" and options.expected is not None:
        parser.error("maintenance-custody qualification binds {pro, prolite} itself; "
                      "--expected is refused")
    if not login and options.custody == "active" and options.expected is None:
        parser.error("--custody active requires --expected")
    reservation = EvidenceFile(options.evidence)
    try:
        launcher = _launcher(options.launch_root)
        executable = vendor_executable(launcher)
        policy = _policy(options.policy)
        configuration = options.configuration.read_text(encoding="utf-8")

        async def lane(custody: Custody) -> dict[str, Any]:
            if login:
                return await run_login(
                    custody, launcher, policy, executable=executable,
                    configuration=configuration, lane_dir=options.lane_dir,
                    deadline_s=deadline, out=sys.stdout.buffer,
                    first_login=options.first_login,
                )
            expected = (
                ExpectedAccount(
                    plan_type=QUALIFICATION_PLANS[0], alternatives=QUALIFICATION_PLANS[1:],
                )
                if options.custody == "maintenance"
                else ExpectedAccount(plan_type=options.expected)
            )
            return await run_startup(
                custody, launcher, policy, executable=executable,
                configuration=configuration, expected=expected,
                lane_dir=options.lane_dir, deadline_s=deadline,
                expect_denial=options.expect_denial, hold_s=options.hold,
            )

        async def under_custody() -> dict[str, Any]:
            if options.custody == "maintenance":
                with inherit_maintenance(
                    options.store_root, options.key, options.lock_fd,
                    generation_floor=options.floor, parent=os.getppid(),
                ) as withdrawn:
                    return await lane(maintenance_custody(withdrawn))
            sealed = NativeOperatorStoreIdentityV1.model_validate_json(
                options.sealed.read_text(encoding="utf-8"),
            )
            store = BindingStore(options.store_root, options.key, sealed)
            async with active_custody(store) as held:
                return await lane(held)

        evidence = asyncio.run(under_custody())
    except BaseException:
        reservation.abandon()
        raise
    revision = reservation.publish(evidence)
    print(json.dumps({"evidence_digest": str(revision), "faults": evidence["faults"]}),
          file=sys.stderr)
    return 1 if evidence["faults"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
