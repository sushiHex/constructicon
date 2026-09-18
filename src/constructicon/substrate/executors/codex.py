"""The operator-bound Codex adapter (ADR 0021, READ posture).

One task, one acquisition, one contained conversation: no persistent agent
service, no second controller and no scheduler. The interesting logic lives in
:mod:`constructicon.substrate.executors.codex_protocol`, which has no I/O; this
module is the thin binding between that protocol and
``LinuxLauncher.exchange``.

The conversation is strictly sequential per direction::

    initialize            (never the experimental capability)
    initialized           (notification)
    account/read          -> account_faults(...)      pre-turn gate
    <turn>                   collect records until terminal
    account/read          -> account_faults(...)      pre-acceptance gate
    close stdin, drain to EOF

Either gate faulting yields an unavailable failure naming the faults, and **a
faulting pre-acceptance gate discards an otherwise successful turn**. That is
ADR 0021's "refuses availability/result acceptance".

Nothing here reads, writes, parses or copies a credential, and no field of a
published identity carries an account fact. The two readings are the supported
non-secret observation; the module docstring of the protocol states exactly what
they do and do not establish.

Replies are correlated explicitly, because the pure gate cannot see it: request
ids are monotonic within one conversation, and a mismatched id, a native request
where a reply was due, or a reply carrying neither result nor error is refused.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import (
    ExecutorError,
    ExecutorFailure,
    ExecutorOutcome,
    TaskSpec,
)
from constructicon.core.grants import EffectiveGrants
from constructicon.core.identity import Digest, canonical_json, digest, parse_json_value
from constructicon.core.native_operator import (
    NativeEgressIdentityV1,
    NativeOperatorExecutorProfileV3,
    NativeOperatorLaunchIdentityV3,
    NativeOperatorStoreIdentityV1,
)
from constructicon.core.process import ProcessIO
from constructicon.core.workspace import (
    AcquiredCapability,
    Disposition,
    LeaseClosure,
    LeaseContext,
    LeaseReconciliation,
    StaleAcquisition,
    WorkspaceView,
    acquisition_id_for,
    lease_id_for,
)
from constructicon.substrate.executors import codex_protocol
from constructicon.substrate.executors.codex_protocol import (
    EMPTY_TURN,
    READ_WINDOW,
    ExpectedAccount,
    RecordStream,
    TurnObservation,
    account_change_faults,
    account_faults,
    account_read_request,
    decode_turn,
    encode_record,
    initialize_request,
    initialized_notification,
    is_terminal_record,
    observe_turn,
    thread_start_request,
    turn_request,
    unavailable_outcome,
)
from constructicon.substrate.executors.linux import (
    LinuxLauncher,
    ProcessExchangeError,
    ProcessLimits,
    ProcessResult,
)
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard

CLIENT_NAME = "constructicon"
CLIENT_VERSION = "0"
NATIVE_CWD = "/tmp"
"""The native zone has no workspace; the launcher already chdirs here."""

APP_SERVER_ARGUMENTS = ("app-server", "--strict-config", "--stdio")

INGRESS_NOT_ESTABLISHED = "private fixed-actor ingress is not established by assembly"
UNQUALIFIED_PREREQUISITES: tuple[str, ...] = (
    INGRESS_NOT_ESTABLISHED,
    "the operator store binding has no physical qualification",
    "the native vendor-session egress boundary has not been qualified",
)
"""The default published unavailability. Assembly narrows this only once the
physical prerequisites actually hold; nothing at runtime can clear it."""

PROTOCOL_REVISION = digest("codex-operator-protocol", 1, inspect.getsource(codex_protocol))


def configuration_digest(configuration: str) -> Digest:
    return digest("codex-operator-configuration", 1, configuration)


def callback_catalog_digest(catalog: Sequence[str]) -> Digest:
    return digest("codex-operator-callback-catalog", 1, list(catalog))


def limits_digest(limits: ProcessLimits) -> Digest:
    return digest("codex-operator-limits", 1, asdict(limits))


def launch_identity(
    *,
    launcher: LinuxLauncher,
    profile: NativeOperatorExecutorProfileV3,
    egress: NativeEgressIdentityV1,
    store: NativeOperatorStoreIdentityV1,
    executable_digest: Digest,
    configuration: str,
    catalog: Sequence[str],
    authenticated_startup_conformance_revision: Digest,
    subscription_mode_conformance_revision: Digest,
) -> NativeOperatorLaunchIdentityV3:
    """The trusted factory: every fact from actual content, never a locator.

    Constructing this is not an OS, vendor-session or store availability proof.
    The two conformance revisions are supplied by whoever ran the corresponding
    qualification; this adapter never mints them.
    """

    return NativeOperatorLaunchIdentityV3(
        executable_digest=executable_digest,
        runtime_digest=launcher.expected_runtime,
        adapter_revision=ADAPTER_REVISION,
        decoder_revision=PROTOCOL_REVISION,
        isolation_revision=launcher.revision,
        configuration_digest=configuration_digest(configuration),
        limits_digest=limits_digest(launcher.limits),
        callback_protocol_revision=PROTOCOL_REVISION,
        callback_catalog_digest=callback_catalog_digest(catalog),
        profile=profile,
        egress=egress,
        store=store,
        authenticated_startup_conformance_revision=(
            authenticated_startup_conformance_revision
        ),
        subscription_mode_conformance_revision=subscription_mode_conformance_revision,
    )


class CodexConversation:
    """One sequential exchange inside one owned byte scope.

    A standalone callable over :class:`~constructicon.core.process.ProcessIO`,
    not a method of the acquisition. That is structural: in the Linux lane the
    launch belongs to the placement fixture's own ``exchange``, so a
    conversation reachable only through ``execute`` could not be exercised
    against the pinned binary at all. ``CodexOperatorHandle.execute`` is one
    caller and ``tests/substrate/test_codex_native.py`` is the other, which is
    also what gives this contract its second consumer (I6).

    It frames in the adapter, reads arbitrary chunks, never overlaps
    same-direction operations, never retries an interrupted write, joins nothing
    of its own, does not retain the handle and never renews the deadline.
    Returning from here ends the byte scope, not the process: teardown and
    reaping belong to the launcher.
    """

    def __init__(
        self, *, task: TaskSpec, grants: EffectiveGrants, expected: ExpectedAccount,
        input_limit: int, preamble: int = 0,
    ) -> None:
        self._task = task
        self._grants = grants
        self._expected = expected
        # The budget is cumulative over the whole byte scope and may already
        # have been spent against by whoever opened it, so a caller states what
        # this conversation may spend rather than assuming the launcher's whole
        # allowance is still available.
        self._input_limit = input_limit
        self._preamble = preamble
        self._stream = RecordStream()
        self._queue: list[bytes] = []
        self._identifier = 0
        self._transcript: list[bytes] = []
        self._collecting = False
        self._spent = 0
        self.faults: tuple[str, ...] = ()
        self.observation: TurnObservation = EMPTY_TURN
        self.preamble_records: list[bytes] = []
        self.thread_id: str | None = None
        self.turn_id: str | None = None

    async def __call__(self, io: ProcessIO) -> None:
        try:
            await self._converse(io)
        finally:
            self.observation = observe_turn(
                self._transcript, thread_id=self.thread_id or "", turn_id=self.turn_id or "",
                transport_damage=self._stream.damage,
            )
            await self._finish(io)

    # -- transport ------------------------------------------------------------

    def _refuse(self, reason: str) -> None:
        self.faults += (reason,)

    def _next_identifier(self) -> int:
        self._identifier += 1
        return self._identifier

    async def _read(self, io: ProcessIO) -> bytes | None:
        """One framed record, or ``None`` at EOF or once framing is damaged."""

        while True:
            if self._queue:
                return self._queue.pop(0)
            if self._stream.damage is not None:
                return None
            try:
                chunk = await io.read(self._stream.next_read())
            except (ContractViolation, OSError) as exc:
                # The owner stopped this scope, or the channel failed. Returning
                # cleanly is what the launcher's ownership contract asks for.
                self._stream.damage = self._stream.damage or f"the byte scope ended: {exc}"
                return None
            self._queue.extend(self._stream.feed(chunk))
            if not chunk and not self._queue:
                return None

    async def _send(self, io: ProcessIO, value: Mapping[str, Any]) -> bool:
        try:
            raw = encode_record(value)
        except ContractViolation as exc:
            self._refuse(f"an outbound native record cannot be framed: {exc}")
            return False
        if self._spent + len(raw) > self._input_limit:
            self._refuse("the conversation reached its cumulative input budget")
            return False
        try:
            await io.write(raw)
        except (ContractViolation, OSError) as exc:
            # An interrupted write is never re-sent or refunded.
            self._refuse(f"the native client stopped accepting input: {exc}")
            return False
        self._spent += len(raw)
        return True

    async def _request(
        self, io: ProcessIO, payload: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        """Send one request and return the reply that correlates with it."""

        identifier = payload["id"]
        method = payload["method"]
        if not await self._send(io, payload):
            return None
        while True:
            line = await self._read(io)
            if line is None:
                self._refuse(f"the native client ended before answering {method!r}")
                return None
            try:
                record = parse_json_value(line.decode("utf-8"))
            except (ValueError, UnicodeError) as exc:
                self._refuse(f"a malformed native record arrived awaiting {method!r}: {exc}")
                return None
            if not isinstance(record, dict):
                self._refuse(f"a native record awaiting {method!r} is not an object")
                return None
            if "id" not in record:
                if "method" not in record:
                    self._refuse("a native record carries neither an id nor a method")
                    return None
                if self._collecting:
                    self._transcript.append(line)
                continue
            if "method" in record:
                self._refuse("this slice authorizes no native request")
                return None
            if type(record["id"]) is not int or record["id"] != identifier:
                self._refuse(f"a reply does not correlate with the {method!r} request")
                return None
            if ("result" in record) == ("error" in record):
                self._refuse(f"the {method!r} reply carries neither a result nor an error")
                return None
            return record

    async def _finish(self, io: ProcessIO) -> None:
        with suppress(ContractViolation, OSError):
            await io.close_stdin()
        with suppress(ContractViolation, OSError):
            while await io.read(READ_WINDOW):
                pass

    # -- the conversation -----------------------------------------------------

    async def _account(self, io: ProcessIO) -> Mapping[str, Any] | None:
        """One mode reading. Its frame is consumed here and never transcribed."""

        return await self._request(io, account_read_request(self._next_identifier()))

    async def _drain_preamble(self, io: ProcessIO) -> bool:
        """Consume records the byte scope already carried before the session.

        A composed byte scope may announce itself on the same stream the native
        client then uses. Those records belong to whoever opened the scope: they
        are retained here as evidence and never transcribed, so the production
        path and a composed one share this code without branching on which is
        which. The default is none.
        """

        for _ in range(self._preamble):
            line = await self._read(io)
            if line is None:
                self._refuse("the byte scope ended inside its preamble")
                return False
            self.preamble_records.append(line)
        return True

    async def _converse(self, io: ProcessIO) -> None:
        if not await self._drain_preamble(io):
            return
        opened = await self._request(io, initialize_request(
            self._next_identifier(), client=CLIENT_NAME, version=CLIENT_VERSION,
        ))
        if opened is None:
            return
        if "error" in opened:
            self._refuse("the native client refused initialization")
            return
        if not await self._send(io, initialized_notification()):
            return

        before = await self._account(io)
        if before is None:
            return
        faults = account_faults(before, self._expected)
        if faults:
            # A refused pre-turn reading never sends a turn.
            self.faults += faults
            return

        started = await self._request(io, thread_start_request(
            self._next_identifier(), cwd=NATIVE_CWD,
        ))
        if started is None:
            return
        self.thread_id = _named(started, "thread")
        if self.thread_id is None:
            self._refuse("the native client started no identified thread")
            return

        self._collecting = True
        opened_turn = await self._request(io, turn_request(
            self._next_identifier(), thread_id=self.thread_id, task=self._task,
            grants=self._grants,
        ))
        if opened_turn is None:
            return
        self.turn_id = _named(opened_turn, "turn")
        if self.turn_id is None:
            self._refuse("the native client started no identified turn")
            return
        await self._collect(io)

        after = await self._account(io)
        if after is None:
            # A missing pre-acceptance reply is a refusal, never something to
            # wait on: the child may simply have exited after the turn.
            return
        self.faults += account_faults(after, self._expected)
        self.faults += account_change_faults(before, after)

    async def _collect(self, io: ProcessIO) -> None:
        assert self.thread_id is not None and self.turn_id is not None
        while True:
            line = await self._read(io)
            if line is None:
                return
            self._transcript.append(line)
            if is_terminal_record(line, thread_id=self.thread_id, turn_id=self.turn_id):
                return


def _named(reply: Mapping[str, Any], field: str) -> str | None:
    result = reply.get("result")
    if not isinstance(result, Mapping):
        return None
    value = result.get(field)
    if not isinstance(value, Mapping):
        return None
    identifier = value.get("id")
    return identifier if isinstance(identifier, str) and identifier else None


class CodexOperatorHandle:
    """One acquisition. It never retains a byte scope or a process handle."""

    def __init__(
        self, provider: CodexOperatorProvider, context: LeaseContext, paths: AcquisitionPaths,
    ) -> None:
        self.provider = provider
        self.context = context
        self.paths = paths
        self.entered = False
        self.ready = False
        self.closed = False
        self.active: asyncio.Task[ProcessResult] | None = None

    @property
    def profile(self) -> NativeOperatorExecutorProfileV3:
        return self.provider.profile

    def validate_grants(self, grants: EffectiveGrants) -> tuple[str, ...]:
        return self.profile.grant_faults(grants)

    async def materialize(self) -> None:
        """Entry is marked before any await; this slice owns no durable payload.

        The exclusive store lock, its qualified layout and the mount identity
        arrive with N3. There is deliberately nothing to undo here yet.
        """

        if self.closed or self.entered:
            raise ContractViolation("a closed or entered codex acquisition cannot materialize")
        self.entered = True
        self.ready = True

    async def execute(
        self, task: TaskSpec, *, workspace: WorkspaceView | None, grants: EffectiveGrants,
    ) -> ExecutorOutcome:
        if self.closed or not self.ready:
            raise ContractViolation("codex acquisition is not open and materialized")
        if canonical_json(grants) != canonical_json(self.context.binding.effective_grants):
            raise ContractViolation("codex executor call differs from its sealed grants")
        faults = self.validate_grants(grants)
        if workspace is not None:
            faults += ("the native zone takes no workspace",)
        if task.context or task.response_schema is not None:
            faults += ("this slice carries neither task context nor a response schema",)
        if faults:
            return ExecutorFailure(error=ExecutorError(
                kind="unavailable", detail="; ".join(faults),
            ))
        return await self._converse(task, grants)

    async def _converse(self, task: TaskSpec, grants: EffectiveGrants) -> ExecutorOutcome:
        provider = self.provider
        conversation = CodexConversation(
            task=task, grants=grants, expected=provider.expected_account,
            input_limit=provider.launcher.limits.input_bytes,
        )
        # The deadline covers the launcher's own prerequisite probe, which
        # re-hashes bubblewrap, the policy and the whole runtime root before the
        # child starts. It does not begin at the first byte.
        async with acquisition_guard(self.paths) as guard:
            if self.closed:
                raise ContractViolation("codex acquisition closed while awaiting its guard")
            if provider.launcher.revision != provider.identity.isolation_revision:
                raise ContractViolation("the pinned launch recipe drifted from its identity")
            self.active = asyncio.create_task(provider.launcher.exchange(
                (provider.binary, *APP_SERVER_ARGUMENTS),
                workspace=None, posture=grants.posture, guard_fds=(guard,),
                conversation=conversation, timeout_s=grants.timeout_s,
            ))
            try:
                result = await self.active
            except ProcessExchangeError as exc:
                # Something escaped the callback; the evidence survives.
                result = exc.result
            except (OSError, ContractViolation) as exc:
                # A launch prerequisite failed: bubblewrap, policy, runtime
                # digest, AppArmor or a non-Linux host.
                return _unavailable(str(exc), grants)
            except BaseExceptionGroup as group:
                # Cleanup failed alongside the conversation, so there is no
                # result at all and nothing may be decoded as a turn. A grouped
                # cancellation is still a cancellation and must not become one.
                if group.subgroup(asyncio.CancelledError) is not None:
                    raise
                return _unavailable(repr(group), grants)
            finally:
                self.active = None
        requested = grants.model_selection.model
        if conversation.faults:
            return unavailable_outcome(
                conversation.faults, conversation.observation, result, requested_model=requested,
            )
        return decode_turn(conversation.observation, result, requested_model=requested)


def _unavailable(detail: str, grants: EffectiveGrants) -> ExecutorFailure:
    return ExecutorFailure(
        requested_model=grants.model_selection.model,
        error=ExecutorError(kind="unavailable", detail=detail),
    )


class CodexOperatorProvider:
    """A leased schema-3 provider whose published facts describe this adapter.

    Availability is an assembly fact read without runtime I/O. This slice
    delivers no store, no egress and no qualified ingress, so the default
    published state is unavailable and nothing at runtime can change it.
    """

    def __init__(
        self,
        *,
        launcher: LinuxLauncher,
        profile: NativeOperatorExecutorProfileV3,
        identity: NativeOperatorLaunchIdentityV3,
        expected_account: ExpectedAccount,
        binary: str,
        configuration: str,
        catalog: Sequence[str],
        acquisition_root: Path,
        unavailable_reasons: tuple[str, ...] = UNQUALIFIED_PREREQUISITES,
    ) -> None:
        if not binary.startswith("/") or "\0" in binary:
            raise ContractViolation("the native client requires a fixed absolute executable")
        if not acquisition_root.is_absolute():
            raise ContractViolation("the acquisition root must be absolute")
        if catalog:
            raise ContractViolation(
                "this slice publishes no mediated callback catalog; the WRITE posture and "
                "its contained worker arrive with N2's second slice"
            )
        drift = {
            "adapter_revision": ADAPTER_REVISION,
            "decoder_revision": PROTOCOL_REVISION,
            "callback_protocol_revision": PROTOCOL_REVISION,
            "configuration_digest": configuration_digest(configuration),
            "callback_catalog_digest": callback_catalog_digest(catalog),
            "limits_digest": limits_digest(launcher.limits),
            "isolation_revision": launcher.revision,
            "runtime_digest": launcher.expected_runtime,
        }
        for field, expected in drift.items():
            if getattr(identity, field) != expected:
                raise ContractViolation(
                    f"the published {field} differs from this adapter's actual content"
                )
        if identity.profile != profile:
            raise ContractViolation("the published identity carries a different profile")
        self.launcher = launcher
        self.profile = profile
        self.binary = binary
        self.expected_account = expected_account
        self._identity = identity
        self._acquisition_root = acquisition_root
        self._unavailable = tuple(unavailable_reasons)
        self.handles: list[CodexOperatorHandle] = []

    @property
    def identity(self) -> NativeOperatorLaunchIdentityV3:
        return self._identity

    @property
    def unavailable_reasons(self) -> tuple[str, ...]:
        return self._unavailable

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        if self.unavailable_reasons:
            raise ContractViolation("an unavailable operator provider cannot acquire")
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        acquisition = acquisition_id_for(logical, context.run_lease.epoch)
        handle = CodexOperatorHandle(
            self, context, AcquisitionPaths(self._acquisition_root, acquisition),
        )
        self.handles.append(handle)
        return AcquiredCapability(
            resource=handle, lease_id=logical, acquisition_id=acquisition,
            resource_ref=acquisition, materialize=handle.materialize,
        )

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition,
    ) -> LeaseClosure:
        handle = acquisition.resource
        if not isinstance(handle, CodexOperatorHandle) or handle.provider is not self:
            raise ContractViolation("codex close requires its own handle")
        handle.closed = True
        if handle.active is not None:
            # The launcher owns teardown and reaping of everything it started.
            handle.active.cancel()
        return LeaseClosure(disposition="released" if disposition == "release" else "discarded")

    async def reconcile(
        self, context: LeaseContext, stale: tuple[StaleAcquisition, ...],
    ) -> LeaseReconciliation:
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        for item in stale:
            row = item.lease
            expected = acquisition_id_for(logical, row.acquisition_epoch)
            if (
                row.lease_id != logical or row.run_id != context.run_lease.run_id
                or row.acquisition_epoch >= context.run_lease.epoch
                or row.resource_ref != expected
            ):
                raise ContractViolation("a codex recovery row contradicts its own identity")
        return LeaseReconciliation(reaped=(), detail=(
            "this slice owns no durable native payload; the store binding, its exclusive "
            "lock and egress disposal arrive with N3"
        ))


ADAPTER_REVISION = digest("codex-operator-adapter", 1, {
    member.__name__: inspect.getsource(member)
    for member in (CodexConversation, CodexOperatorHandle, CodexOperatorProvider)
})
"""Derived from this adapter's actual bodies, not a manual version."""
