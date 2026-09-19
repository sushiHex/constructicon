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
ADR 0021's "refuses availability/result acceptance". An ``account/`` notification
arriving between the two readings discards the turn the same way: it is the only
in-band signal for the window they bracket but cannot cover.

**The gate records its completion; nothing infers it.** An empty fault tuple
means either "the readings cleared" or "the conversation was aborted before it
could record anything", and treating those alike published a turn whose
pre-acceptance reading never ran. The conversation sets ``gate_completed`` only
after the pre-acceptance comparison, and its ``finally`` states an explicit fault
when it did not — so an escaped exception now fails closed instead of decoding
the clean result the launcher reports once the conversation's teardown has closed
stdin and drained. That invariant lives in the conversation rather than here,
because the Linux lane builds its own outcome from the same faults.

Nothing here reads, writes, parses or copies a credential, and no field of a
published identity carries an account fact. The two readings are the supported
non-secret observation; the module docstring of the protocol states exactly what
they do and do not establish.

Replies are correlated explicitly, because the pure gate cannot see it: a
mismatched id, a native request where a reply was due, or a reply carrying
neither result nor error is refused, and nothing already buffered when a request
is built may answer it.

Ids are allocated monotonically, which is only how they are generated and not a
property correlation relies on. Predictability turned out to be a liability
rather than a feature: a child that emits ``{"id": <next>, ...}`` before the
request exists satisfies an id check, which is why arrival order is checked too.
"""

from __future__ import annotations

import asyncio
import inspect
import tomllib
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
from constructicon.core.identity import Digest, canonical_json, digest
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
    ACCOUNT_NOTICE_FAULT,
    DAMAGE_NESTING,
    EMPTY_TURN,
    GATE_INCOMPLETE_FAULT,
    READ_WINDOW,
    ExpectedAccount,
    RecordDamaged,
    RecordStream,
    TurnObservation,
    account_change_faults,
    account_faults,
    account_read_request,
    bounded_detail,
    decode_turn,
    encode_record,
    initialize_request,
    initialized_notification,
    is_account_record,
    is_terminal_record,
    named_method,
    observe_turn,
    parse_record,
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


def configured_model(configuration: str) -> str:
    """The model the sealed configuration names, read from its own bytes.

    ``turn/start`` deliberately sends no model, so the model that will actually
    run comes from this configuration. Publishing ``requested_model`` from the
    grant while the configuration pins something else would be an I4 claim
    resting on an unverified coupling: the adapter would report B and the vendor
    would run A. Reading it here lets the provider refuse the disagreement.

    The shape is the pinned client's ``--strict-config`` TOML with a top-level
    ``model`` key, which is what every fixture in this repository supplies.
    """

    try:
        parsed = tomllib.loads(configuration)
    except RecursionError as exc:
        # The sibling parse, and the same class ``parse_record`` exists to close:
        # ``tomllib.loads`` exhausts the stack on deeply nested input, and
        # ``RecursionError`` is not a ``TOMLDecodeError``, so it escaped raw
        # instead of as the ContractViolation this contract promises.
        raise ContractViolation(f"the sealed configuration is {DAMAGE_NESTING}") from exc
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        raise ContractViolation(f"the sealed configuration is not valid TOML: {exc}") from exc
    model = parsed.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ContractViolation("the sealed configuration must name a top-level model")
    return model


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
        selection = grants.model_selection
        if selection.kind != "explicit" or not (selection.model or "").strip():
            # ``turn_request`` refuses this too, but there it raises mid-turn and
            # out of the byte scope. A caller precondition belongs at
            # construction, before any byte moves: one fewer way for an
            # exception to escape the conversation.
            raise ContractViolation("a native operator conversation requires a sealed model")
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
        self.gate_completed = False
        self.observation: TurnObservation = EMPTY_TURN
        self.preamble_records: list[bytes] = []
        self.thread_id: str | None = None
        self.turn_id: str | None = None

    async def __call__(self, io: ProcessIO) -> None:
        try:
            await self._converse(io)
        finally:
            if not self.gate_completed and not self.faults:
                # An aborted conversation records nothing, and an empty fault
                # tuple would then read as "the gate cleared". It is not: this
                # is the one place that turns silence into a refusal, and it is
                # here rather than in the handle because every consumer — the
                # handle and the Linux lane, which builds its own outcome from
                # these faults — must inherit it.
                #
                # Conditional on ``not self.faults`` because every early return
                # in ``_converse`` already records one, so an unconditional form
                # would only add noise to an already-explained refusal.
                self._refuse(GATE_INCOMPLETE_FAULT)
            self.observation = observe_turn(
                self._transcript, thread_id=self.thread_id, turn_id=self.turn_id,
                transport_damage=self._stream.damage,
            )
            await self._finish(io)

    # -- transport ------------------------------------------------------------

    def _refuse(self, reason: str) -> None:
        self.faults += (reason,)

    def _refuse_account(self, record: Mapping[str, Any]) -> None:
        """An account notification mid-turn is a refusal, never transcript.

        ADR 0021 refuses on an observed mode change and requires proof that
        refresh cannot silently select API or cloud authentication mid-turn.
        This is the only in-band signal for the window the two readings bracket
        but cannot cover, so it discards the turn exactly as a gate fault does.
        Only the method name reaches the public detail; nothing from ``params``.
        """

        self._refuse(ACCOUNT_NOTICE_FAULT.format(method=named_method(record.get("method"))))

    def _next_identifier(self) -> int:
        self._identifier += 1
        return self._identifier

    def _classify(self, line: bytes, *, method: str) -> Mapping[str, Any] | None:
        """One record's shape while a reply is outstanding, or ``None`` if refused."""

        try:
            record = parse_record(line)
        except RecordDamaged as exc:
            self._refuse(f"a damaged native record arrived awaiting {method!r}: {exc}")
            return None
        if not isinstance(record, dict) or ("id" not in record and "method" not in record):
            self._refuse(f"a native record awaiting {method!r} is not a protocol object")
            return None
        return record

    def _absorb(self, line: bytes, record: Mapping[str, Any]) -> bool:
        """Handle one id-less notification; ``False`` when it is a refusal.

        The single place notifications are classified. Both sites that can meet
        one — the pre-send drain and the read loop — and the turn collector route
        through here, so the account refusal and the transcription rule cannot
        drift apart between them.
        """

        if is_account_record(record):
            self._refuse_account(record)
            return False
        if self._collecting:
            self._transcript.append(line)
        return True

    def _drain_before(self, method: str) -> bool:
        """Nothing already buffered can be a reply to a request not yet sent.

        Request ids are monotonic and therefore predictable, and ``_collect``
        returns the moment it sees the terminal record, so a child can leave
        bytes queued and a forged ``{"id": <next>, ...}`` among them would
        satisfy correlation before the live reply was ever read. Correlation
        alone only checks which request a reply *claims* to answer; this is the
        missing half — a reply must arrive **after** its request.

        Every earlier request consumed its own reply, so no legitimate id-bearing
        record can be in this queue. That makes the rule exact rather than
        heuristic: it refuses the forged and the unsolicited case and nothing
        else.

        **The width of this rule, stated.** It covers bytes this adapter has
        already framed. A reply still unread in the pipe cannot be ordered
        against the request that provoked it — arrival order is only observable
        as *our* read order — so that case is not closed and is not closeable by
        any correlation rule. Randomizing the ids would not close it either, for
        the same reason the larger case is open: the vendor authors the reply's
        *content*, not merely its timing, so a client willing to forge a reply
        could instead answer the real request with a lie. The gate trusts the
        session's report of its own mode; this rule only stops a buggy or
        confused client from having an earlier record answered as a later one.
        """

        while self._queue:
            line = self._queue.pop(0)
            record = self._classify(line, method=method)
            if record is None:
                return False
            if "id" in record:
                self._refuse(
                    f"a reply arrived before the {method!r} request it claims to answer"
                )
                return False
            if not self._absorb(line, record):
                return False
        return True

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
        if not self._drain_before(method):
            return None
        if not await self._send(io, payload):
            return None
        while True:
            line = await self._read(io)
            if line is None:
                self._refuse(f"the native client ended before answering {method!r}")
                return None
            record = self._classify(line, method=method)
            if record is None:
                return None
            if "id" not in record:
                if not self._absorb(line, record):
                    return None
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

        # Nothing read before the turn existed may be attributed to it. The queue
        # can still hold records the child emitted earlier, and ``_request``
        # drains it — so collecting must not already be true when that drain
        # runs, or an earlier notification becomes this turn's evidence. Same
        # boundary as the pre-send rule, in the other direction.
        opened_turn = await self._request(io, turn_request(
            self._next_identifier(), thread_id=self.thread_id, task=self._task,
            grants=self._grants,
        ))
        if opened_turn is None:
            return
        self._collecting = True
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
        # The gate ran to its end. Nothing earlier may set this: every path that
        # does not reach here leaves a result unacceptable.
        self.gate_completed = True

    async def _collect(self, io: ProcessIO) -> None:
        assert self.thread_id is not None and self.turn_id is not None
        while True:
            line = await self._read(io)
            if line is None:
                return
            try:
                record = parse_record(line)
            except RecordDamaged:
                # Damaged bytes are the fold's business, not a refusal here.
                self._transcript.append(line)
                continue
            if isinstance(record, dict) and "id" not in record and "method" in record:
                if not self._absorb(line, record):
                    return
            else:
                # A reply or a native request inside a turn: the fold counts it.
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
        if grants.model_selection.model != self.provider.configured_model:
            # The turn sends no model, so the configuration decides what runs.
            # Publishing the grant's model while the vendor ran another would be
            # an untruthful observation, not a preference.
            faults += (
                "the sealed configuration names a different model than this grant selects",
            )
        if faults:
            return ExecutorFailure(error=ExecutorError(
                kind="unavailable", detail=bounded_detail("; ".join(faults)),
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
            # Reachable, and not a tautology over two frozen records:
            # ``LinuxLauncher.revision`` is a property that re-hashes its own
            # module and the L0 sources it binds at call time, so it is not a
            # function of the launcher's fields and can differ between the
            # provider's construction and this launch.
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
                # A launch prerequisite failed inside the launcher: bubblewrap,
                # the policy, the runtime digest or AppArmor. Not the platform
                # check — ``acquisition_guard`` raises that on entry, above this
                # try, and production never reaches either, because ``acquire``
                # refuses while any unavailable reason stands.
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
        error=ExecutorError(kind="unavailable", detail=bounded_detail(detail)),
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
        self.configured_model = configured_model(configuration)
        if self.configured_model not in profile.grant_policy.model_ids:
            raise ContractViolation(
                "the sealed configuration names a model outside the profile's inventory"
            )
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
