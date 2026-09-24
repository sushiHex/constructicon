"""The N4 operator lanes: device login and the no-model startup, under custody.

An offline operator helper beside the store's publication, maintenance and
activation helpers (M8-N4-state-review.md, section 5). It composes existing
parts only: the store's custody, the sealed configuration, the egress relay,
the launcher and :class:`CodexConversation` stopped at its first readback. It is
not a provider and adds no availability: nothing here can clear
``vendor_conformance_qualified``.

Two lanes, each one native launch in the real zone behind the relay:

* ``login`` runs the unmodified client's ``login --device-auth`` inside
  maintenance. Its stdout carries the one-time code and goes to the operator's
  terminal only; nothing of it is kept.
* ``startup`` runs the four authorized methods (``initialize``,
  ``initialized``, ``account/read``, ``account/rateLimits/read``) under either
  maintenance (qualification) or the active selection.

Evidence is a closed record written create-exclusive with ``completed`` last:
a missing or incomplete file is a failed run. It never holds stdout, stderr
text, an email, an account id, a token, credential bytes or a hostname outside
the sealed policy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator, Callable, Mapping
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
    CodexConversation,
    configuration_digest,
    configured_model,
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
    LinuxLauncher,
    NativeStoreMount,
    ProcessExchangeError,
    ProcessResult,
    sealed_data_fd,
)
from constructicon.substrate.executors.operator_store import (
    BindingCheck,
    BindingStore,
    StoreMaintenance,
    maintain_offline,
)

LANE_SCHEMA = 1
LOGIN_ARGUMENTS = ("login", "--device-auth")
STARTUP_ARGUMENTS = ("app-server", "--strict-config", "--stdio")
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


@dataclass(frozen=True)
class Custody:
    """What one launch needs from the store: a lock, a credential, a check."""

    kind: Literal["maintenance", "active"]
    lock_fd: int
    open_credential: Callable[[], int]
    check: Callable[[], BindingCheck]
    detail: Mapping[str, Any]


def maintenance_custody(maintenance: StoreMaintenance) -> Custody:
    return Custody(
        "maintenance", maintenance.lock_fd, maintenance.open_credential, maintenance.check,
        {"generation_floor": maintenance.generation_floor},
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
    destinations: dict[str, int]
    denied: dict[str, int]
    credential_changed: bool


async def launch(
    custody: Custody, launcher: LinuxLauncher, policy: EgressPolicy,
    command: tuple[str, ...], conversation: Callable[[ProcessIO], Any], *,
    configuration: str, lane_dir: Path, deadline_s: float,
) -> Launched:
    """One native launch in the real zone, behind the relay, under custody."""

    lane_dir.mkdir(mode=0o700)  # fresh, or refuse: FileExistsError
    deadline = asyncio.get_running_loop().time() + deadline_s
    mount_fds: list[int] = []
    try:
        mount_fds.append(custody.open_credential())
        mount_fds.append(sealed_data_fd(configuration.encode("utf-8")))
        before = os.fstat(mount_fds[0]).st_mtime_ns
        relay = EgressRelay(policy, lane_dir / "relay", deadline, lambda: None)
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
                result = exc.result
        return Launched(
            result=result,
            destinations=dict(relay.destinations),
            denied={key: value for key, value in relay.observed.items()
                    if key.startswith("denied:")},
            credential_changed=os.fstat(mount_fds[0]).st_mtime_ns != before,
        )
    finally:
        for fd in mount_fds:
            with suppress(OSError):
                os.close(fd)
        with suppress(OSError):
            lane_dir.rmdir()


def _process(result: ProcessResult) -> dict[str, Any]:
    return {
        "returncode": result.returncode, "payload_returncode": result.payload_returncode,
        "timed_out": result.timed_out, "elapsed_s": round(result.elapsed_s, 3),
        "stderr_bytes": len(result.stderr),
    }


def _base(lane: str, custody: Custody, launcher: LinuxLauncher, policy: EgressPolicy,
          configuration: str, launched: Launched) -> dict[str, Any]:
    return {
        "schema_version": LANE_SCHEMA, "lane": lane, "custody": custody.kind,
        **dict(custody.detail),
        "launch_revision": str(launcher.revision),
        "runtime_digest": str(launcher.expected_runtime),
        "configuration_digest": str(configuration_digest(configuration)),
        "egress": {key: str(value) for key, value in identity_digests(policy).items()},
        "relay": {"destinations": launched.destinations, "denied": launched.denied},
        "credential": {"checked": True, "mtime_changed": launched.credential_changed},
        "process": _process(launched.result),
        "vendor_identity": "unverified",
        "vendor_conformance_qualified": False,
    }


async def run_login(
    custody: Custody, launcher: LinuxLauncher, policy: EgressPolicy, *,
    binary: str, configuration: str, lane_dir: Path, deadline_s: float, out: BinaryIO,
) -> dict[str, Any]:
    """The unmodified client's device login; its output reaches ``out`` only."""

    async def relay_to_operator(io: ProcessIO) -> None:
        while chunk := await io.read(8192):
            out.write(chunk)
            out.flush()
        await io.close_stdin()

    launched = await launch(
        custody, launcher, policy, (binary, *LOGIN_ARGUMENTS), relay_to_operator,
        configuration=configuration, lane_dir=lane_dir, deadline_s=deadline_s,
    )
    faults = [DENIAL_FAULT] if launched.denied else []
    if launched.result.returncode or launched.result.payload_returncode:
        faults.append("the device login did not exit cleanly")
    return {**_base("login", custody, launcher, policy, configuration, launched),
            "faults": faults}


async def run_startup(
    custody: Custody, launcher: LinuxLauncher, policy: EgressPolicy, *,
    binary: str, configuration: str, expected: ExpectedAccount, lane_dir: Path,
    deadline_s: float, expect_denial: bool = False,
) -> dict[str, Any]:
    """The four authorized methods, then stdin closes; never a thread."""

    conversation = CodexConversation(
        task=TaskSpec(instruction="unused by the startup phase"),
        grants=LANE_GRANTS.model_copy(update={"model_selection": ModelSelection(
            kind="explicit", model=configured_model(configuration),
        )}),
        expected=expected, input_limit=launcher.limits.input_bytes, startup_only=True,
    )
    recorded: list[RecordingIO] = []

    async def converse(io: ProcessIO) -> None:
        recording = RecordingIO(io)
        recorded.append(recording)
        await conversation(recording)

    launched = await launch(
        custody, launcher, policy, (binary, *STARTUP_ARGUMENTS), converse,
        configuration=configuration, lane_dir=lane_dir, deadline_s=deadline_s,
    )
    faults = [bounded_detail(fault) for fault in conversation.faults]
    if bool(launched.denied) != expect_denial:
        faults.append(
            DENIAL_FAULT if launched.denied else "the declared control denial did not occur"
        )
    reading = conversation.before_spend
    refreshed = (
        launched.destinations.get("accepted:" + REFRESH_DESTINATION, 0) > 0
        and launched.credential_changed and conversation.gate_completed
        and not conversation.faults
    )
    return {
        **_base("startup", custody, launcher, policy, configuration, launched),
        "methods_sent": recorded[0].methods if recorded else [],
        "withheld_methods": list(conversation.withheld_methods),
        "gate": {"completed": conversation.gate_completed, "plan": conversation.observed_plan},
        "readback": None if reading is None else {
            name: getattr(reading, name) for name in (*SPEND_FIELDS, *USAGE_FIELDS)
        },
        "refresh": "measured" if refreshed else "unmeasured",
        "faults": faults,
    }


def write_evidence(path: Path, evidence: Mapping[str, Any]) -> Digest:
    """Create-exclusive, ``completed`` last, synced; returns the evidence digest.

    That digest is what the operator passes as the conformance revision, so the
    sealed identity names the evidence it rests on. Activation does not itself
    verify it (M8-N4-state-review.md, orchestrator decision 5).
    """

    if "completed" in evidence:
        raise ContractViolation("evidence marks itself completed only as its last act")
    complete = {**evidence, "completed": True}
    raw = (json.dumps(complete, ensure_ascii=True, allow_nan=False) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise ContractViolation("the lane evidence was not written")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    return digest(EVIDENCE_DOMAIN, 1, json.loads(canonical_json(complete)))


# --- the operator's command line ---------------------------------------------


def _launcher(root: Path) -> LinuxLauncher:
    """The installed runtime, from its reviewed manifest (host-runtime interface)."""

    manifest = json.loads((root / "runtime.json").read_text(encoding="utf-8"))
    return LinuxLauncher(
        runtime_root=root / "runtime", expected_runtime=Digest(manifest["runtime_digest"]),
        bubblewrap=root / "bwrap", policy=Path(manifest["policy"]),
        expected_policy_sha256=manifest["policy_sha256"],
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
    parser = argparse.ArgumentParser(prog="codex_lane")
    parser.add_argument("lane", choices=("login", "startup"))
    parser.add_argument("--custody", choices=("maintenance", "active"), default="maintenance")
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--sealed", type=Path, help="the active selection's store identity")
    parser.add_argument("--launch-root", type=Path, required=True)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--lane-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected", default="pro")
    parser.add_argument("--alternative", action="append", default=[])
    parser.add_argument("--expect-denial", action="store_true")
    parser.add_argument("--hold", type=float, default=0.0)
    parser.add_argument("--deadline", type=float, default=120.0)
    parser.add_argument("--wait", type=float, default=0.0)
    options = parser.parse_args(argv)
    if not 0 <= options.hold <= options.deadline:
        parser.error("--hold must lie within the deadline")
    launcher = _launcher(options.launch_root)
    policy = _policy(options.policy)
    configuration = options.configuration.read_text(encoding="utf-8")

    async def lane(custody: Custody) -> dict[str, Any]:
        if options.lane == "login":
            return await run_login(
                custody, launcher, policy, binary=options.binary,
                configuration=configuration, lane_dir=options.lane_dir,
                deadline_s=options.deadline, out=sys.stdout.buffer,
            )
        evidence = await run_startup(
            custody, launcher, policy, binary=options.binary, configuration=configuration,
            expected=ExpectedAccount(
                plan_type=options.expected, alternatives=tuple(options.alternative),
            ),
            lane_dir=options.lane_dir, deadline_s=options.deadline,
            expect_denial=options.expect_denial,
        )
        # Custody, and so the store lock, is held through the pause (runbook S6a).
        await asyncio.sleep(options.hold)
        return evidence

    if options.custody == "active" and options.sealed is None:
        parser.error("--custody active requires --sealed")

    async def under_custody() -> dict[str, Any]:
        if options.custody == "maintenance":
            with maintain_offline(
                options.store_root, options.key, wait_s=options.wait,
            ) as withdrawn:
                return await lane(maintenance_custody(withdrawn))
        sealed = NativeOperatorStoreIdentityV1.model_validate_json(
            options.sealed.read_text(encoding="utf-8"),
        )
        async with active_custody(BindingStore(options.store_root, options.key, sealed)) as held:
            return await lane(held)

    evidence = asyncio.run(under_custody())
    revision = write_evidence(options.evidence, evidence)
    print(json.dumps({"evidence_digest": str(revision), "faults": evidence["faults"]}),
          file=sys.stderr)
    return 1 if evidence["faults"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
