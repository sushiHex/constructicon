"""The operator-bound Codex adapter (ADR 0021, READ and mediated WRITE).

One task, one acquisition, one contained conversation: no persistent agent
service, no second controller and no scheduler. The interesting logic lives in
:mod:`constructicon.substrate.executors.codex_protocol`, which has no I/O; this
module is the thin binding between that protocol and
``LinuxLauncher.exchange``.

The conversation is strictly sequential per direction::

    initialize            (WRITE opts into the exact dynamic-tool field)
    initialized           (notification)
    account/read          -> account_faults(...)      pre-turn gate
    <turn>                   collect records and mediate exact WRITE callbacks
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
neither result nor error is refused, nothing already read when a request is
built may answer it — framed or still being framed — and no id is answered
twice.

Ids are allocated monotonically, which is only how they are generated and not a
property correlation relies on. Predictability turned out to be a liability
rather than a feature: a child that emits ``{"id": <next>, ...}`` before the
request exists satisfies an id check, which is why arrival order is checked too.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import os
import tomllib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import (
    ExecutorError,
    ExecutorFailure,
    ExecutorOutcome,
    TaskSpec,
)
from constructicon.core.grants import EffectiveGrants, Posture
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
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors import codex_protocol
from constructicon.substrate.executors.codex_protocol import (
    ACCOUNT_NOTICE_FAULT,
    ANSWERED_NOTHING_FAULT,
    CONTAINED_PYTHON_CATALOG,
    CONTAINED_PYTHON_TOOL,
    DAMAGE_NESTING,
    DUPLICATE_REPLY_FAULT,
    EMPTY_TURN,
    GATE_INCOMPLETE_FAULT,
    INCONCLUSIVE_DRAIN_FAULT,
    MAX_TOOL_CALLS,
    RECORD_BYTES,
    UNSOLICITED_REPLY_FAULT,
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
    parse_tool_call,
    thread_start_request,
    tool_call_response,
    turn_request,
    unavailable_outcome,
)
from constructicon.substrate.executors.egress import (
    MAX_SOCKET_PATH_BYTES,
    SOCKET_NAME,
    EgressPolicy,
    EgressRelay,
    identity_digests,
)
from constructicon.substrate.executors.linux import (
    Conversation,
    LinuxLauncher,
    NativeStoreMount,
    ProcessExchangeError,
    ProcessLimits,
    ProcessResult,
    sealed_data_fd,
)
from constructicon.substrate.executors.operator_store import (
    BindingCheck,
    BindingStore,
    HeldStoreLock,
)
from constructicon.substrate.git.acquisition import (
    AcquisitionClosure,
    AcquisitionPaths,
    acquisition_guard,
    dispose_acquisition,
)
from constructicon.substrate.git.capture import (
    ContainedWriteWorkspace,
    ContainedWriteWorkspaceProvider,
)

CLIENT_NAME = "constructicon"
CLIENT_VERSION = "0"
NATIVE_CWD = "/tmp"
"""The native zone has no workspace; the launcher already chdirs here."""

APP_SERVER_ARGUMENTS = ("app-server", "--strict-config", "--stdio")
WORKER_ARGUMENTS = ("/usr/bin/python3", "-I", "-c", "import sys; exec(sys.stdin.read())")

WITHHELD_METHODS = 16
"""How many withheld method names to retain for reporting."""

CALLBACK_PENDING_RECORDS = 64
CALLBACK_PENDING_BYTES = RECORD_BYTES
"""What one active callback may observe and defer before it must refuse."""

INGRESS_NOT_ESTABLISHED = "private fixed-actor ingress is not established by assembly"
STORE_NOT_ESTABLISHED = "the operator store binding has no physical qualification"
OVERAGE_NOT_ENFORCED = (
    "an overages-forbidden profile has no proved refusal at its included limit"
)
"""ADR 0021 read mechanically: nothing here can supply that refusal, so no reason
tuple, flag or label can clear this one. It reads the sealed overage literal only."""
UNQUALIFIED_PREREQUISITES: tuple[str, ...] = (
    INGRESS_NOT_ESTABLISHED,
    STORE_NOT_ESTABLISHED,
    "the native vendor-session egress boundary has not been qualified",
)
"""The default published unavailability. Assembly narrows this only once the
physical prerequisites actually hold; nothing at runtime can clear it."""


class _LocalClose(asyncio.CancelledError):
    """Owned physical work stopped by this handle's permanent close latch."""


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
        input_limit: int, preamble: int = 0, catalog: Sequence[str] = (),
        worker: Callable[[str], Awaitable[str]] | None = None,
        deadline: float | None = None,
    ) -> None:
        selection = grants.model_selection
        if selection.kind != "explicit" or not (selection.model or "").strip():
            # ``turn_request`` refuses this too, but there it raises mid-turn and
            # out of the byte scope. A caller precondition belongs at
            # construction, before any byte moves: one fewer way for an
            # exception to escape the conversation.
            raise ContractViolation("a native operator conversation requires a sealed model")
        resolved_catalog = tuple(catalog)
        if resolved_catalog not in ((), CONTAINED_PYTHON_CATALOG):
            raise ContractViolation("a codex conversation has an unknown callback catalog")
        if tuple(sorted(set(grants.allowed_tools))) != resolved_catalog:
            raise ContractViolation("the callback catalog differs from the sealed tool grant")
        if bool(resolved_catalog) != (worker is not None):
            raise ContractViolation("a callback catalog and worker must be supplied together")
        if bool(resolved_catalog) != (deadline is not None):
            raise ContractViolation("a callback conversation requires its shared deadline")
        if deadline is not None and (
            type(deadline) not in (int, float) or not math.isfinite(deadline)
        ):
            raise ContractViolation("a callback conversation requires a finite deadline")
        self._task = task
        self._grants = grants
        self._expected = expected
        # The budget is cumulative over the whole byte scope and may already
        # have been spent against by whoever opened it, so a caller states what
        # this conversation may spend rather than assuming the launcher's whole
        # allowance is still available.
        self._input_limit = input_limit
        self._preamble = preamble
        self._catalog = resolved_catalog
        self._worker = worker
        self._deadline = deadline
        self._stream = RecordStream()
        self._queue: list[bytes] = []
        self._identifier = 0
        self._transcript: list[bytes] = []
        self._collecting = False
        self._spent = 0
        self._allocated: set[int] = set()
        self._correlated: set[int] = set()
        self._deferred: bytes | None = None
        self._deferred_request: bytes | None = None
        self._pre_send_record = False
        self._excluded = 0
        self._server_requests: set[tuple[str, int | str]] = set()
        self._tool_calls: set[str] = set()
        self._callbacks_started = 0
        self._callbacks_completed = 0
        # Classified and bounded: what the session emitted before the turn
        # existed is a fact about the pinned interface worth reporting, and
        # the native lane records it.
        self.withheld_methods: list[str] = []
        self._entered = False
        self.faults: tuple[str, ...] = ()
        self.gate_completed = False
        self.observation: TurnObservation = EMPTY_TURN
        self.preamble_records: list[bytes] = []
        self.thread_id: str | None = None
        self.turn_id: str | None = None

    async def __call__(self, io: ProcessIO) -> None:
        if self._entered:
            # ``gate_completed`` is a latch and the transcript, budget and ids all
            # carry over, so a second scope would publish the first run's output
            # with no incomplete-gate fault. ``materialize`` already guards entry
            # this way, and this callable is advertised to a second consumer, so
            # the asymmetry is the argument for the guard.
            # Before the raise: this precedes the ``try``, so the ``finally``
            # does not run and the first run's faults, latch and observation
            # survive. A caller that swallowed the raise would otherwise publish
            # run one's output against run two's result.
            self._refuse("a codex conversation drives one byte scope only")
            raise ContractViolation("a codex conversation drives one byte scope only")
        self._entered = True
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
                transport_damage=self._stream.damage, excluded=self._excluded,
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
        self._allocated.add(self._identifier)
        return self._identifier

    def _owned(self, identifier: Any) -> bool:
        """Whether this conversation allocated that id.

        Ownership, not record shape, is what separates an attack on the gate from
        unsolicited noise. Shape was an inference: one extra ``method`` key moved
        a pre-send forgery from refusal to demotion, because the shape test ran
        first. An id we allocated is the id a forger can predict, and that is the
        positive fact worth keying on.
        """

        return _hashable(identifier) and identifier in self._allocated

    def _judge_identified(
        self, line: bytes, record: Mapping[str, Any], *, context: str,
        awaiting: int | None = None,
    ) -> bool:
        """The one rule for an id-bearing record, applied at every site.

        Four sites can meet one — the pre-send drain, the reply loop, the turn
        collector and the drain to EOF — and each used to decide for itself, which
        is why ``_once`` was untrue in three places. They all route through here.

        Two facts are used, each for a stated reason, and the order matters.
        **Ownership** decides whether the record attacks our correlation: an id we
        allocated is ours, so a second answer to it is a duplicate and an answer
        arriving where none is awaited is an ordering violation. Both are aimed at
        the gate, so both refuse and discard the turn's result.

        Only then does the **method key** matter, and only to separate two kinds of
        unowned record: one *without* a method is a reply answering a request that
        does not exist — a protocol violation, refused, because letting it pass as
        noise made the loop wait for a reply that never comes and publish a
        deadline when the real cause was a violation. One *with* a method is a
        native request this slice authorizes nowhere: damage, so the result is
        demoted rather than discarded — trust in the output degraded, the gate's
        authority did not.

        This is not the shape heuristic it replaced. There the method key decided
        the severity of a record whose id we *owned*, which was wrong because
        ownership is what made it an attack. Here ownership is settled first and
        the method key only distinguishes "you answered nothing" from "you asked
        for a callback". A simplification that collapses the two will re-break it.
        """

        identifier = record["id"]
        if not self._owned(identifier):
            if "method" not in record:
                self._refuse(ANSWERED_NOTHING_FAULT)
                return False
            # The fold counts it from the transcript. At the drain to EOF the
            # observation is already folded, so this is a no-op there, which is
            # harmless: an unsolicited request at EOF changes no verdict.
            self._transcript.append(line)
            return True
        if not self._once(identifier):
            return False
        if awaiting is not None and identifier == awaiting:
            return True  # the reply we are waiting for; the caller checks it
        self._refuse(f"{UNSOLICITED_REPLY_FAULT}: {context}")
        return False

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
        # Read before the turn was named, so it cannot be the turn's evidence —
        # but it must not vanish either. Counting it here is what keeps the
        # ordering boundary from becoming the adapter's one silent exclusion.
        if record.get("method") == "turn/completed":
            # Held, not judged. Refusing this rested on an assumption about the
            # pin that nothing here verifies: if the app-server emits a turn's
            # notifications before the ``turn/start`` response, every live turn
            # would refuse, and no test in this repository would show it — the
            # native lanes both refuse at the pre-turn gate. The probe's own wire
            # skips notifications while awaiting a response
            # (``tests/native_codex_probe.py``), so whoever wrote it expected the
            # interleaving. The containment lane then observed it directly: the
            # pinned app-server emits notifications before any turn exists, which
            # is recorded in ``withheld_methods``. A server that does that is not
            # one to bet on about reply-versus-notification ordering, so the
            # deferral rests on an observation rather than on caution.
            #
            # Deferring removes the assumption instead of betting on it, and still
            # fixes the hang, because the record is no longer discarded and then
            # waited for. One record of buffer is enough:
            # a second unattributable completion is a protocol violation.
            if self._deferred is not None:
                self._refuse("two turn completions arrived before either was named")
                return False
            self._deferred = line
            return True
        self._excluded += 1
        if len(self.withheld_methods) < WITHHELD_METHODS:
            self.withheld_methods.append(named_method(record.get("method")))
        return True

    def _drain_before(self, method: str) -> bool:
        """Nothing already buffered can be a reply to a request not yet sent.

        Request ids are monotonic and therefore predictable, and ``_collect``
        returns the moment it sees the terminal record, so a child can leave
        bytes queued and a forged ``{"id": <next>, ...}`` among them would
        satisfy correlation before the live reply was ever read. Correlation
        alone only checks which request a reply *claims* to answer; this is the
        missing half — a reply must arrive **after** its request.

        Ordering is enforced over two things: the records already framed, and
        **the record still being framed**. The second is not an afterthought —
        draining only the framed queue left the rule one read window wide, and a
        record straddling an 8192-byte boundary had its id read before the request
        bearing it was written. Any ordinary turn trailing a few hundred bytes
        past the terminal record reaches that state, so the gap needed no
        oversized record at all.

        Unframed bytes cannot be refused wholesale: a legitimate turn may trail
        bytes after its terminal record. But those bytes predate this send by
        construction, so the *first* record completed from them is pre-send and is
        marked as such. One ``feed`` can complete several records, so the marker
        applies to that first one only and then clears.

        **What this does not reach.** A client that forges a reply and then
        suppresses its own genuine one. The duplicate-id rule below catches a
        confused client that answers the real request, and refuses when it cannot
        complete that check; deliberate suppression escapes, and no rule reaches it
        because the vendor authors the reply's *content*, not merely its timing —
        a client willing to forge could instead answer the real request with a
        lie. The gate trusts the session's report of its own mode.
        """

        while self._queue:
            line = self._queue.pop(0)
            record = self._classify(line, method=method)
            if record is None:
                return False
            if "id" in record:
                if "method" in record and self._catalog:
                    self._refuse("a native request arrived outside the active turn")
                    return False
                if not self._judge_identified(
                    line, record, context=f"the {method!r} request",
                ):
                    return False
                continue
            if not self._absorb(line, record):
                return False
        self._pre_send_record = bool(self._stream.pending)
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
            pre_send, self._pre_send_record = self._pre_send_record, False
            record = self._classify(line, method=method)
            if record is None:
                return None
            if "id" not in record:
                if not self._absorb(line, record):
                    return None
                continue
            if "method" in record:
                if pre_send:
                    self._refuse(
                        f"a native request arrived before the {method!r} request"
                    )
                    return None
                if (
                    bool(self._catalog)
                    and method == "turn/start"
                    and record.get("method") == "item/tool/call"
                ):
                    if not self._defer_tool_request(line, record):
                        return None
                    continue
                self._refuse("this conversation authorizes no native request here")
                return None
            if pre_send:
                # Its bytes were read before this request was written, so it
                # cannot be the reply to it however well its id matches.
                self._refuse(
                    f"a reply arrived before the {method!r} request it claims to answer"
                )
                return None
            if not self._judge_identified(
                line, record, context=f"the {method!r} request", awaiting=identifier,
            ):
                return None
            if type(record["id"]) is not int:
                # Reachable although ownership already passed: ``1.0 in {1}`` is
                # true, so a float can be "owned" and equal to an awaited int. The
                # wire form still has to be the one the protocol specifies.
                self._refuse(f"a reply to {method!r} carries a non-integer id")
                return None
            if ("result" in record) == ("error" in record):
                self._refuse(f"the {method!r} reply carries neither a result nor an error")
                return None
            self._correlated.add(record["id"])
            return record

    def _defer_tool_request(self, line: bytes, record: Mapping[str, Any]) -> bool:
        """Hold at most one validated request until ``turn/start`` names its turn."""

        if self._deferred is not None:
            self._refuse("a callback request arrived after the deferred turn completion")
            return False
        if self._deferred_request is not None:
            self._refuse("two callback requests arrived before the turn was named")
            return False
        if self.thread_id is None:
            self._refuse("a callback request arrived before the thread was named")
            return False
        try:
            parse_tool_call(record, thread_id=self.thread_id, turn_id=None)
        except ContractViolation as exc:
            self._refuse(bounded_detail(str(exc)))
            return False
        self._deferred_request = line
        return True

    @staticmethod
    def _server_key(request_id: int | str) -> tuple[str, int | str]:
        """Keep inbound request ids separate from client RPC reply ids."""

        return type(request_id).__name__, request_id

    async def _dispatch_tool(
        self, io: ProcessIO, record: Mapping[str, Any],
    ) -> bool:
        """Run and answer one admitted callback, recording completion positively."""

        if (
            self.thread_id is None
            or self.turn_id is None
            or self._worker is None
            or self._deadline is None
            or self._catalog != CONTAINED_PYTHON_CATALOG
        ):
            self._refuse("the callback authority is not open for this turn")
            return False
        try:
            call = parse_tool_call(
                record, thread_id=self.thread_id, turn_id=self.turn_id,
            )
        except ContractViolation as exc:
            self._refuse(bounded_detail(str(exc)))
            return False
        request_key = self._server_key(call.request_id)
        if request_key in self._server_requests:
            self._refuse("the native client repeated a callback request id")
            return False
        self._server_requests.add(request_key)
        if call.call_id in self._tool_calls:
            self._refuse("the native client repeated a callback call id")
            return False
        if len(self._tool_calls) >= MAX_TOOL_CALLS:
            self._refuse("the native client exceeded the callback call ceiling")
            return False
        # Spend before the first effect await. A lost response can never make
        # this call eligible to run again.
        self._tool_calls.add(call.call_id)
        self._callbacks_started += 1
        try:
            completed = await self._await_callback(io, call.program)
            if completed is None:
                return False
            output, held = completed
            response = tool_call_response(call, output)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._refuse(f"the contained callback failed ({type(exc).__name__})")
            return False
        if not await self._send(io, response):
            return False
        # These calls arrived before this response. They can become eligible
        # only now; prepending preserves their wire order ahead of records that
        # were still unread when the response completed.
        self._queue = held + self._queue
        # Worker return and the complete response write are both positive facts.
        self._callbacks_completed += 1
        return True

    async def _await_callback(
        self, io: ProcessIO, program: str,
    ) -> tuple[str, list[bytes]] | None:
        """Race one effect with native death while preserving sequential calls."""

        assert self._worker is not None and self._deadline is not None
        async def invoke_worker() -> str:
            assert self._worker is not None
            return await self._worker(program)

        worker: asyncio.Task[str] = asyncio.create_task(invoke_worker())
        reads: list[asyncio.Task[bytes | None]] = []
        current = asyncio.create_task(self._read(io))
        reads.append(current)
        held: list[bytes] = []
        held_bytes = 0
        held_requests: set[tuple[str, int | str]] = set()
        held_calls: set[str] = set()
        records = 0
        cancelled_here: set[asyncio.Task[object]] = set()

        async def join_owned() -> None:
            tasks = (worker, *reads)
            results = await asyncio.gather(*tasks, return_exceptions=True)
            errors: list[BaseException] = []
            for task, result in zip(tasks, results, strict=True):
                if not isinstance(result, BaseException):
                    continue
                if isinstance(result, asyncio.CancelledError) and task in cancelled_here:
                    continue
                if isinstance(result, BaseExceptionGroup) and task in cancelled_here:
                    _, remainder = result.split(asyncio.CancelledError)
                    if remainder is not None:
                        errors.append(remainder)
                    continue
                errors.append(result)
            if len(errors) == 1:
                raise errors[0]
            if errors:
                raise BaseExceptionGroup("callback cleanup failed", errors)

        primary: BaseException | None = None
        try:
            try:
                async with asyncio.timeout_at(self._deadline):
                    while True:
                        done, _ = await asyncio.wait(
                            (worker, current), return_when=asyncio.FIRST_COMPLETED,
                        )
                        # A simultaneously observable native fact precedes the
                        # worker result: without a live peer no response can be
                        # credited, however close the two completions were.
                        if current in done:
                            line = current.result()
                            if line is None:
                                self._refuse(
                                    "the native client ended while a callback was active"
                                )
                                return None
                            records += 1
                            if records > CALLBACK_PENDING_RECORDS:
                                self._refuse(
                                    "the native client flooded an active callback"
                                )
                                return None
                            try:
                                pending = parse_record(line)
                            except RecordDamaged:
                                self._refuse(
                                    "a damaged native record arrived while a callback was active"
                                )
                                return None
                            if not isinstance(pending, dict) or (
                                "id" not in pending and "method" not in pending
                            ):
                                self._refuse(
                                    "a malformed native record arrived while a callback was active"
                                )
                                return None
                            if "method" in pending and not isinstance(
                                pending["method"], str,
                            ):
                                self._refuse(
                                    "a malformed native method arrived while a callback was active"
                                )
                                return None
                            if "id" in pending:
                                if "method" not in pending:
                                    self._judge_identified(
                                        line, pending, context="an active callback",
                                    )
                                    return None
                                try:
                                    deferred = parse_tool_call(
                                        pending,
                                        thread_id=self.thread_id or "",
                                        turn_id=self.turn_id,
                                    )
                                except ContractViolation as exc:
                                    self._refuse(bounded_detail(str(exc)))
                                    return None
                                request_key = self._server_key(deferred.request_id)
                                if (
                                    request_key in self._server_requests
                                    or request_key in held_requests
                                ):
                                    self._refuse(
                                        "the native client repeated a pending callback request id"
                                    )
                                    return None
                                if (
                                    deferred.call_id in self._tool_calls
                                    or deferred.call_id in held_calls
                                ):
                                    self._refuse(
                                        "the native client repeated a pending callback call id"
                                    )
                                    return None
                                if len(self._tool_calls) + len(held) >= MAX_TOOL_CALLS:
                                    self._refuse(
                                        "the native client exceeded the callback call ceiling"
                                    )
                                    return None
                                if held_bytes + len(line) > CALLBACK_PENDING_BYTES:
                                    self._refuse(
                                        "pending callback requests exceeded their byte ceiling"
                                    )
                                    return None
                                held_requests.add(request_key)
                                held_calls.add(deferred.call_id)
                                held.append(line)
                                held_bytes += len(line)
                            elif pending.get("method") == "turn/completed":
                                self._transcript.append(line)
                                self._refuse(
                                    "the turn completed while a callback was active"
                                )
                                return None
                            elif not self._absorb(line, pending):
                                return None
                            if worker in done:
                                return worker.result(), held
                            current = asyncio.create_task(self._read(io))
                            reads.append(current)
                            continue
                        return worker.result(), held
            except TimeoutError:
                self._refuse("the shared deadline expired while a callback was active")
                return None
        except BaseException as exc:
            primary = exc
            raise
        finally:
            for task in (worker, *reads):
                if not task.done():
                    cancelled_here.add(task)
                    task.cancel()
            try:
                await finish_owned(asyncio.create_task(join_owned()))
            except BaseException as cleanup:
                if primary is not None:
                    raise BaseExceptionGroup(
                        "callback failed during cleanup", [primary, cleanup],
                    ) from None
                raise

    async def _claim_deferred_request(self, io: ProcessIO) -> bool:
        """Validate and dispatch the no-effect request held before turn identity."""

        line, self._deferred_request = self._deferred_request, None
        if line is None:
            return True
        try:
            record = parse_record(line)
        except RecordDamaged:
            self._refuse("the deferred callback request became damaged")
            return False
        if not isinstance(record, dict):
            self._refuse("the deferred callback request is not an object")
            return False
        return await self._dispatch_tool(io, record)

    def _once(self, identifier: Any) -> bool:
        """No second record may bear an id already correlated.

        The stronger of the two ordering rules: a confused client still answers
        the real request, so its genuine reply arrives as a duplicate of the
        forged id. It is applied at the reply site and in the drain to EOF, and a
        fault raised in either reaches the handle, because ``__call__``'s
        ``finally`` completes before ``exchange`` returns.

        What is tested, rather than a claim about the class: a duplicate arriving
        immediately, behind unterminated bytes, and behind an oversized record;
        and an id that is not an integer at either site. A drain that cannot be
        completed refuses in its own right, so a shape not listed here fails
        closed rather than passing silently — but that is a property of the
        inconclusive rule, not a proof that no other shape exists.
        """

        # Hashability is guaranteed by ``_owned``, which is the only caller and
        # tests it first. Membership rather than type is deliberate: ``1.0 in {1}``
        # and ``True in {1}`` are both true, so a duplicate spelled ``1.0`` or
        # ``true`` against a correlated ``1`` is caught, and an ``int``-only guard
        # would have narrowed the rule while fixing the TypeError.
        if identifier in self._correlated:
            self._refuse(DUPLICATE_REPLY_FAULT)
            return False
        return True

    def _audit(self, line: bytes) -> bool:
        """Apply the duplicate-id rule to one drained record.

        Returns whether the record left the check inconclusive: bytes we could not
        decode mean we cannot say whether a duplicate was among them.
        """

        try:
            record = parse_record(line)
        except RecordDamaged:
            return True
        if not isinstance(record, dict) or "id" not in record:
            return False
        if "method" in record and self._catalog:
            self._refuse("a native request arrived during the terminal drain")
            return False
        self._judge_identified(line, record, context="the drain to EOF")
        return False

    async def _finish(self, io: ProcessIO) -> None:
        """Close stdin and drain to EOF, applying the duplicate-id rule.

        Why two ``suppress`` blocks are sufficient depends on an ordering in
        another module: ``linux.py``'s ``stop()`` calls
        ``channel.invalidate(stopping=True)`` *before* ``protocol.cancel()``, so
        ``require_active`` raises ``_OwnedStop`` — a ``ContractViolation`` — at the
        top of ``read``, before any await, and ``close_stdin`` has no await at all.
        A cancellation therefore cannot land on one of these awaits and skip the
        drain. Reordering ``stop()`` would break this silently.
        """

        with suppress(ContractViolation, OSError):
            await io.close_stdin()
        # Framing its own way rather than through ``_read``, which stops at the
        # first damage — inheriting that stop let four unterminated bytes end the
        # drain before the duplicate arrived, and the turn published as a success.
        # Records already framed sit in the queue, so they are audited first.
        before = self._stream.damage
        damaged: list[bool] = []
        inconclusive = True  # until the drain reaches EOF, it has not completed
        try:
            with suppress(ContractViolation, OSError):
                while True:
                    if self._queue:
                        lines, self._queue, ended = self._queue, [], False
                    else:
                        chunk = await io.read(self._stream.next_read())
                        lines, ended = self._stream.feed(chunk), not chunk
                    for line in lines:
                        if self._audit(line):
                            damaged.append(True)
                    if self._stream.damage is not None and self._stream.damage != before:
                        damaged.append(True)
                    if ended:
                        inconclusive = bool(damaged)
                        break
        finally:
            # In a ``finally`` and defaulting to true, so the rule holds on every
            # way out of the drain and not only the clean ones — an exception
            # leaving here used to route around it entirely.
            #
            # The fault, not the observation, is the channel that reaches the
            # outcome: ``__call__`` folds the observation *before* awaiting this,
            # so damage first seen here reaches no field, while faults are read by
            # the handle after ``exchange`` returns. Do not route this through
            # ``transport_damage``; it would be silently dropped.
            if inconclusive:
                self._refuse(INCONCLUSIVE_DRAIN_FAULT)

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

        These records are **not** classified and not account-checked: production
        passes no preamble, and the Linux lane's two come from a trusted fixture
        that asserts the transcript stays empty. An untrusted scope opener would
        need them classified like any other record.
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
            experimental_api=bool(self._catalog),
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
            dynamic_tools=(CONTAINED_PYTHON_TOOL,) if self._catalog else (),
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
        if self._deferred_request is not None and self._deferred is not None:
            self._refuse("the turn completed before its deferred callback was answered")
            return
        if not await self._claim_deferred_request(io):
            return
        if not self._claim_deferred():
            await self._collect(io)

        if (
            self._deferred_request is not None
            or self._callbacks_started != self._callbacks_completed
        ):
            self._refuse("the callback completion check did not complete")
            return

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

    def _claim_deferred(self) -> bool:
        """Evaluate a completion held from before the turn was named.

        Now that the reply has named the turn the record is attributable, so it is
        judged rather than waited for: this turn's terminal record if it names
        this turn, and damage through the ordinary fold if it names another.
        Returns whether the turn is already complete.
        """

        line, self._deferred = self._deferred, None
        if line is None:
            return False
        assert self.thread_id is not None and self.turn_id is not None
        self._transcript.append(line)
        return is_terminal_record(line, thread_id=self.thread_id, turn_id=self.turn_id)

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
            if isinstance(record, dict) and "id" in record:
                if "method" in record and self._catalog:
                    if not await self._dispatch_tool(io, record):
                        return
                elif not self._judge_identified(line, record, context="this turn"):
                    return
            elif isinstance(record, dict) and "method" in record:
                if not self._absorb(line, record):
                    return
            else:
                # Neither a reply nor a notification: the fold counts it.
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


def _resource_reference(acquisition_id: str, binding_digest: Digest) -> str:
    """The complete durable recovery reference, with no private store locator."""

    return canonical_json({
        "schema_version": 1,
        "acquisition_id": acquisition_id,
        "operator_binding_digest": binding_digest,
    })


def _read_resource_reference(raw: str) -> tuple[str, Digest]:
    try:
        value = parse_json_value(raw)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContractViolation("a codex recovery reference is malformed") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "acquisition_id", "operator_binding_digest"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or not isinstance(value["acquisition_id"], str)
        or not isinstance(value["operator_binding_digest"], str)
        or canonical_json(value) != raw
    ):
        raise ContractViolation("a codex recovery reference is not strict canonical metadata")
    try:
        binding_digest = Digest(value["operator_binding_digest"])
    except ValueError as exc:
        raise ContractViolation("a codex recovery reference has an invalid binding digest") from exc
    return value["acquisition_id"], binding_digest


class CodexOperatorHandle:
    """One acquisition and the two physical guards held for its whole life."""

    def __init__(
        self, provider: CodexOperatorProvider, context: LeaseContext, paths: AcquisitionPaths,
    ) -> None:
        self.provider = provider
        self.context = context
        self.paths = paths
        self.entered = False
        self.ready = False
        self.closed = False
        self.executed = False
        self.active: asyncio.Task[ProcessResult] | None = None
        self.worker_active: asyncio.Task[ProcessResult] | None = None
        self._materialization: asyncio.Task[None] | None = None
        self._cleanup: asyncio.Task[None] | None = None
        self._close_disposition: Disposition | None = None
        self._guard_owner: AbstractAsyncContextManager[int] | None = None
        self._guard_fd: int | None = None
        self._store_lock: HeldStoreLock | None = None
        self.initial_check: BindingCheck | None = None
        self.launch_check: BindingCheck | None = None
        self.terminal_check: BindingCheck | None = None

    @property
    def profile(self) -> NativeOperatorExecutorProfileV3:
        return self.provider.profile

    def validate_grants(self, grants: EffectiveGrants) -> tuple[str, ...]:
        return self.profile.grant_faults(grants)

    async def materialize(self) -> None:
        """Acquire then retain the acquisition guard and binding-store lock."""
        if self.closed or self.entered:
            raise ContractViolation("a closed or entered codex acquisition cannot materialize")
        self.entered = True
        self._materialization = asyncio.create_task(self._materialize_owned())
        await self._materialization

    def _check_control(self) -> None:
        if self.closed:
            raise _LocalClose("codex acquisition closed during physical work")
        control = self.context.check_control
        if control is None:
            raise ContractViolation("codex acquisition lost its invocation control check")
        control()
        if self.closed:
            raise _LocalClose("codex acquisition closed during physical work")

    def _checked_binding(self, value: object, phase: str) -> BindingCheck:
        expected = self.provider.identity.store.operator_binding_digest
        if not isinstance(value, BindingCheck) or value.binding_digest != expected:
            raise ContractViolation(
                f"the {phase} operator binding check was not an affirmative sealed observation"
            )
        return value

    async def _require_open(self) -> None:
        closure = self.provider.closure
        if closure is None:
            raise ContractViolation("codex store materialization requires acquisition closure")
        self._check_control()
        await finish_owned(asyncio.create_task(asyncio.to_thread(
            closure.require_open, self.paths,
        )))
        self._check_control()

    def _require_open_sync(self) -> None:
        """Read the durable fence inside a no-await transfer boundary."""

        closure = self.provider.closure
        if closure is None:
            raise ContractViolation("codex store materialization requires acquisition closure")
        self._check_control()
        closure.require_open(self.paths)
        self._check_control()

    async def _materialize_owned(self) -> None:
        store = self.provider.binding_store
        if store is None:
            raise ContractViolation("codex store materialization requires a physical binding")
        guard_owner = acquisition_guard(self.paths)
        held: HeldStoreLock | None = None
        guard_entered = False
        failure: BaseException | None = None
        try:
            guard_fd = await guard_owner.__aenter__()
            guard_entered = True
            await self._require_open()
            candidate = store.open_candidate()
            held = await store.acquire_lock(
                candidate,
                check_control=self._check_control,
                check_closure=self._require_open,
            )
            # Nothing before this fresh check can mint readiness. In particular,
            # acquire_lock's successful return is only custody, not acceptance.
            await self._require_open()
            check = self._checked_binding(store.check_held(held), "initial")
            # Recovery can commit closure after the awaited read's worker
            # observed absence but before this task resumes. Re-read it after
            # the binding observation, with no await before readiness transfer.
            self._require_open_sync()
            self._guard_owner = guard_owner
            self._guard_fd = guard_fd
            self._store_lock = held
            self.initial_check = check
            self.ready = True
            guard_entered = False
            held = None
        except BaseException as exc:
            failure = exc
        errors = [failure] if failure is not None else []
        errors.extend(await self._release_custody(
            store=store,
            held=held,
            owner=guard_owner if guard_entered else None,
        ))
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("codex materialization and cleanup failed", errors)

    async def _release_custody(
        self,
        *,
        store: BindingStore | None,
        held: HeldStoreLock | None,
        owner: AbstractAsyncContextManager[int] | None,
    ) -> list[BaseException]:
        """Release both independent owners, preserving every cleanup failure."""

        errors: list[BaseException] = []
        if held is not None:
            if store is None:
                errors.append(ContractViolation("retained codex store lost its owner"))
            else:
                try:
                    store.close_held(held)
                except BaseException as exc:
                    errors.append(exc)
        if owner is not None:
            try:
                await owner.__aexit__(None, None, None)
            except BaseException as exc:
                errors.append(exc)
        return errors

    async def execute(
        self, task: TaskSpec, *, workspace: WorkspaceView | None, grants: EffectiveGrants,
    ) -> ExecutorOutcome:
        if self.closed or not self.ready:
            raise ContractViolation("codex acquisition is not open and materialized")
        if self.executed:
            raise ContractViolation("a codex acquisition executes one task only")
        self.executed = True
        if canonical_json(grants) != canonical_json(self.context.binding.effective_grants):
            raise ContractViolation("codex executor call differs from its sealed grants")
        faults = self.validate_grants(grants)
        write_workspace: ContainedWriteWorkspace | None = None
        if self.profile.posture is Posture.WRITE:
            if not isinstance(workspace, ContainedWriteWorkspace):
                faults += ("the WRITE operator requires its contained workspace",)
            else:
                try:
                    write_workspace = self._validated_workspace(workspace, grants)
                except (OSError, ContractViolation) as exc:
                    faults += (f"the WRITE workspace is unavailable: {bounded_detail(str(exc))}",)
        elif workspace is not None:
            faults += ("the READ native zone takes no workspace",)
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
        return await self._converse(task, grants, write_workspace)

    def _validated_workspace(
        self, workspace: ContainedWriteWorkspace, grants: EffectiveGrants,
    ) -> ContainedWriteWorkspace:
        """Compose the provider's ownership proof with the three missing facts."""

        provider = workspace.provider
        if not isinstance(provider, ContainedWriteWorkspaceProvider):
            raise ContractViolation("the WRITE workspace has another provider kind")
        owned = provider.owned_view(workspace, self.context)
        if not isinstance(owned, ContainedWriteWorkspace):
            raise ContractViolation("the WRITE workspace provider returned another view kind")
        actual = owned.context
        if actual.run_lease.owner_id != self.context.run_lease.owner_id:
            raise ContractViolation("the WRITE workspace belongs to another lease owner")
        if actual.binding.revision != provider.revision:
            raise ContractViolation("the WRITE workspace binding revision drifted")
        if (
            canonical_json(actual.binding.effective_grants) != canonical_json(grants)
            or canonical_json(self.context.binding.effective_grants) != canonical_json(grants)
        ):
            raise ContractViolation("the WRITE workspace carries different sealed grants")
        control = actual.check_control
        if control is None:
            raise ContractViolation("the WRITE workspace lost invocation control")
        self._check_control()
        control()
        return owned

    async def _converse(
        self, task: TaskSpec, grants: EffectiveGrants,
        workspace: ContainedWriteWorkspace | None,
    ) -> ExecutorOutcome:
        provider = self.provider
        store = provider.binding_store
        held = self._store_lock
        guard = self._guard_fd
        if store is None or held is None or guard is None or self.initial_check is None:
            raise ContractViolation("codex acquisition has no retained binding custody")
        # The deadline covers the launcher's own prerequisite probe, which
        # re-hashes bubblewrap, the policy and the whole runtime root before the
        # child starts. It does not begin at the first byte.
        self._check_control()
        await self._require_open()
        if provider.launcher.revision != provider.identity.isolation_revision:
            raise ContractViolation("the pinned launch recipe drifted from its identity")
        deadline = asyncio.get_running_loop().time() + grants.timeout_s
        worker = None
        if workspace is not None:
            async def run_worker(program: str) -> str:
                return await self._run_worker(
                    program, workspace=workspace, grants=grants, deadline=deadline,
                )

            worker = run_worker
        conversation = CodexConversation(
            task=task, grants=grants, expected=provider.expected_account,
            input_limit=provider.launcher.limits.input_bytes,
            catalog=provider.catalog, worker=worker,
            deadline=deadline if worker is not None else None,
        )

        def before_spawn() -> BindingCheck:
            # LinuxLauncher invokes this after its probe and immediately before
            # spawning. It is synchronous so no close/withdrawal can interleave
            # on this event loop after the positive check.
            self._check_control()
            check = self._checked_binding(store.check_held(held), "pre-launch")
            self._require_open_sync()
            self.launch_check = check
            return check

        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return _unavailable("the native operator deadline expired before launch", grants)
        # The two host objects the zone receives, each bound by the descriptor
        # checked here: the credential relative to the held store, the
        # configuration as the sealed bytes this provider's identity digests.
        mount_fds: list[int] = []
        try:
            try:
                mount_fds.append(store.open_credential(held))
                mount_fds.append(sealed_data_fd(provider.configuration.encode("utf-8")))
            except (OSError, ContractViolation) as exc:
                return _unavailable(str(exc), grants)
            native_store = NativeStoreMount(
                lock_fd=held.lock_fd,
                configuration_fd=mount_fds[1],
                credential_fd=mount_fds[0],
                before_spawn=before_spawn,
            )
            self.active = asyncio.create_task(self._exchange(
                (provider.binary, *APP_SERVER_ARGUMENTS),
                posture=grants.posture, guard_fds=(guard, held.lock_fd),
                conversation=conversation, timeout_s=remaining, native_store=native_store,
                deadline=deadline,
            ))
            try:
                result = await self.active
            except ProcessExchangeError as exc:
                # Something escaped the callback; the evidence survives.
                result = exc.result
            except (OSError, ContractViolation) as exc:
                return _unavailable(str(exc), grants)
            except BaseExceptionGroup as group:
                if group.subgroup(asyncio.CancelledError) is not None:
                    raise
                return _unavailable(repr(group), grants)
            finally:
                self.active = None
        finally:
            # Released only after the exchange task has ended: awaiting a task
            # returns, even on this caller's cancellation, only once it is done,
            # so no spawn can still receive either number.
            for fd in mount_fds:
                with suppress(OSError):
                    os.close(fd)
        requested = grants.model_selection.model
        try:
            self._check_control()
            terminal = self._checked_binding(store.check_held(held), "terminal")
            self._require_open_sync()
            if self.launch_check is None:
                raise ContractViolation("the pre-launch binding check did not complete")
            self.terminal_check = terminal
        except (OSError, ContractViolation) as exc:
            return unavailable_outcome(
                (f"operator binding terminal check failed: {bounded_detail(str(exc))}",),
                conversation.observation,
                result,
                requested_model=requested,
            )
        if conversation.faults:
            return unavailable_outcome(
                conversation.faults, conversation.observation, result, requested_model=requested,
            )
        return decode_turn(conversation.observation, result, requested_model=requested)

    async def _exchange(
        self, command: tuple[str, ...], *, posture: Posture, guard_fds: tuple[int, ...],
        conversation: Conversation, timeout_s: float, native_store: NativeStoreMount,
        deadline: float,
    ) -> ProcessResult:
        """The owned native exchange, inside its acquisition's egress relay.

        This body is the task ``_cleanup_owned`` cancels and joins, so the
        relay's teardown finishes before either guard is released.
        """

        launcher = self.provider.launcher
        policy = self.provider.egress
        if policy is None:
            return await launcher.exchange(
                command, workspace=None, posture=posture, guard_fds=guard_fds,
                conversation=conversation, timeout_s=timeout_s, native_store=native_store,
            )
        # A close latched after this task was created allocates nothing.
        self._check_control()
        async with EgressRelay(policy, self.paths.payload, deadline, self._check_control) as egress:
            return await launcher.exchange(
                command, workspace=None, posture=posture, guard_fds=guard_fds,
                conversation=conversation, timeout_s=timeout_s,
                native_store=replace(native_store, egress=egress),
            )

    async def _run_worker(
        self, program: str, *, workspace: ContainedWriteWorkspace,
        grants: EffectiveGrants, deadline: float,
    ) -> str:
        """Execute one program in the workspace-only zone and join its owner."""

        if self.worker_active is not None:
            raise ContractViolation("contained callbacks must be sequential")
        validated = self._validated_workspace(workspace, grants)
        async with validated.use() as guard:
            self._validated_workspace(validated, grants)
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise ContractViolation("the shared operator deadline expired")
            task = asyncio.create_task(self.provider.launcher.run(
                WORKER_ARGUMENTS,
                workspace=Path(validated.path), posture=Posture.WRITE,
                guard_fds=(guard,), stdin=program.encode("utf-8"), input_kind="task",
                timeout_s=remaining,
            ))
            self.worker_active = task
            result: ProcessResult | None = None
            primary: BaseException | None = None
            try:
                # Shield distinguishes cancellation of this callback owner from
                # the worker's own terminal result, so cleanup failure cannot
                # overwrite the cancellation fact.
                result = await asyncio.shield(task)
            except BaseException as exc:
                primary = exc

            cleanup: BaseException | None = None
            if isinstance(primary, asyncio.CancelledError) and not task.done():
                task.cancel()
                try:
                    await finish_owned(task)
                except BaseException as exc:
                    if isinstance(exc, asyncio.CancelledError):
                        pass
                    elif isinstance(exc, BaseExceptionGroup):
                        _, cleanup = exc.split(asyncio.CancelledError)
                    else:
                        cleanup = exc
            try:
                if primary is not None and cleanup is not None:
                    raise BaseExceptionGroup(
                        "contained callback cancelled during failed cleanup",
                        [primary, cleanup],
                    )
                if primary is not None:
                    raise primary
                if cleanup is not None:
                    raise cleanup
            finally:
                # No await may follow clearing this latch: the task is either
                # terminal already or was explicitly cancelled and joined.
                if not task.done():
                    raise ContractViolation("contained callback worker lost ownership")
                self.worker_active = None
            assert result is not None
            self._validated_workspace(validated, grants)
            if (
                result.returncode != 0
                or result.payload_returncode != 0
                or result.timed_out
                or result.bound_exceeded is not None
            ):
                raise ContractViolation("the contained callback worker did not complete")
            try:
                return result.stdout.decode("utf-8")
            except UnicodeError as exc:
                raise ContractViolation("the contained callback returned invalid UTF-8") from exc

    async def cleanup(self, disposition: Disposition) -> None:
        if self._close_disposition is None:
            self._close_disposition = disposition
        elif self._close_disposition != disposition:
            raise ContractViolation("repeated codex close changed its disposition")
        self.closed = True
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._cleanup_owned())
        await finish_owned(self._cleanup)

    async def _cleanup_owned(self) -> None:
        errors: list[BaseException] = []
        closure = self.provider.closure
        if self.entered:
            if closure is None:
                errors.append(ContractViolation(
                    "entered codex acquisition has no permanent closure fence"
                ))
            else:
                try:
                    await finish_owned(asyncio.create_task(asyncio.to_thread(
                        closure.commit, self.paths,
                    )))
                except BaseException as exc:
                    errors.append(exc)

        # These tasks own all work that can still acquire or pass the retained
        # descriptions. Join them before closing either parent copy.
        pending = tuple(dict.fromkeys(
            task for task in (self._materialization, self.active, self.worker_active)
            if task is not None
        ))
        cancelled_here: set[asyncio.Task[object]] = set()
        for task in pending:
            if not task.done():
                cancelled_here.add(task)
                task.cancel()
        if pending:
            results = await asyncio.gather(*pending, return_exceptions=True)
            for task, result in zip(pending, results, strict=True):
                if not isinstance(result, BaseException):
                    continue
                if isinstance(result, asyncio.CancelledError) and (
                    task in cancelled_here or self.closed
                ):
                    continue
                if isinstance(result, BaseExceptionGroup) and task in cancelled_here:
                    _, remainder = result.split(asyncio.CancelledError)
                    if remainder is not None:
                        errors.append(remainder)
                    continue
                errors.append(result)

        self.ready = False
        held, self._store_lock = self._store_lock, None
        owner, self._guard_owner = self._guard_owner, None
        self._guard_fd = None
        errors.extend(await self._release_custody(
            store=self.provider.binding_store,
            held=held,
            owner=owner,
        ))
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("codex acquisition cleanup failed", errors)


def _hashable(value: Any) -> bool:
    """Whether a wire value can be a set member at all.

    ``parse_record`` admits any JSON value as an ``id``, and an object or a list
    raises ``unhashable type`` from a membership test — which escaped the byte
    scope, was converted by the launcher into a ``ProcessExchangeError`` carrying
    a clean result, and published the turn as a success.
    """

    try:
        hash(value)
    except TypeError:
        return False
    return True


def _unavailable(detail: str, grants: EffectiveGrants) -> ExecutorFailure:
    return ExecutorFailure(
        requested_model=grants.model_selection.model,
        error=ExecutorError(kind="unavailable", detail=bounded_detail(detail)),
    )


class CodexOperatorProvider:
    """A leased schema-3 provider whose published facts describe this adapter.

    Availability is an assembly fact read without runtime I/O. A configured
    binding still starts unavailable unless assembly explicitly clears every
    independent prerequisite; an absent binding, and an overages-forbidden
    profile, can never be cleared by an empty caller-supplied reason tuple. An
    absent egress policy is not forced
    the same way: it allocates no relay and mounts no leaf, so the native zone
    keeps only ``lo``, a stronger denial rather than a widening.
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
        binding_store: BindingStore | None = None,
        closure: AcquisitionClosure | None = None,
        egress: EgressPolicy | None = None,
    ) -> None:
        if not binary.startswith("/") or "\0" in binary:
            raise ContractViolation("the native client requires a fixed absolute executable")
        if not acquisition_root.is_absolute():
            raise ContractViolation("the acquisition root must be absolute")
        if ".." in acquisition_root.parts:
            raise ContractViolation("the acquisition root must be canonical")
        resolved_catalog = tuple(catalog)
        policy = profile.grant_policy
        if profile.posture is Posture.READ:
            coherent = (
                resolved_catalog == ()
                and policy.tool_sets == ((),)
                and not policy.workspace_required
            )
        else:
            coherent = (
                resolved_catalog == CONTAINED_PYTHON_CATALOG
                and policy.tool_sets == (CONTAINED_PYTHON_CATALOG,)
                and policy.workspace_required
            )
        if not coherent:
            raise ContractViolation(
                "the native operator profile and mediated callback catalog disagree"
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
        if egress is not None:
            # Checked where the policy is supplied. Conformance is never minted.
            for field, value in identity_digests(egress).items():
                if getattr(identity.egress, field) != value:
                    raise ContractViolation(
                        f"the published egress {field} differs from the sealed relay policy"
                    )
        if (binding_store is None) != (closure is None):
            raise ContractViolation(
                "a physical operator binding and acquisition closure must be injected together"
            )
        if binding_store is not None and binding_store.sealed != identity.store:
            raise ContractViolation(
                "the physical operator binding differs from the published store identity"
            )
        acquisition_locator = acquisition_root
        if binding_store is not None:
            if ".." in binding_store.root.parts:
                raise ContractViolation("the operator binding root must be canonical")
            acquisition_locator = acquisition_root.resolve(strict=False)
            binding_locator = binding_store.root.resolve(strict=False)
            if acquisition_root != acquisition_locator:
                raise ContractViolation(
                    "the acquisition root must be a canonical path without symlink ancestry"
                )
            if (
                acquisition_locator == binding_locator
                or acquisition_locator.is_relative_to(binding_locator)
                or binding_locator.is_relative_to(acquisition_locator)
            ):
                raise ContractViolation(
                    "the acquisition and operator binding roots must be disjoint"
                )
        if egress is not None:
            # The real layout, not a hard-coded suffix: every acquisition id has
            # this length, so one probe covers every socket this root can bind.
            longest = AcquisitionPaths(acquisition_locator, "acq-" + "0" * 32).payload
            if len(os.fsencode(longest / SOCKET_NAME)) > MAX_SOCKET_PATH_BYTES:
                raise ContractViolation(
                    "the acquisition root is too long for the native egress socket"
                )
        # Retained as the exact bytes the published configuration digest names
        # (the drift check above); the zone receives these and nothing else.
        self.configuration = configuration
        self.configured_model = configured_model(configuration)
        if self.configured_model not in profile.grant_policy.model_ids:
            raise ContractViolation(
                "the sealed configuration names a model outside the profile's inventory"
            )
        self.launcher = launcher
        self.profile = profile
        self.catalog = resolved_catalog
        self.binary = binary
        self.expected_account = expected_account
        self._identity = identity
        # Retain the same canonical locator whose disjointness was checked.
        # Trusted host custody protects its ancestors; this is not an inode pin.
        self._acquisition_root = acquisition_locator
        reasons = tuple(unavailable_reasons)
        if binding_store is None and STORE_NOT_ESTABLISHED not in reasons:
            reasons += (STORE_NOT_ESTABLISHED,)
        if profile.subscription_overage == "forbidden" and OVERAGE_NOT_ENFORCED not in reasons:
            reasons += (OVERAGE_NOT_ENFORCED,)
        self._unavailable = reasons
        self.binding_store = binding_store
        self.closure = closure
        self.egress = egress
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
        if self.binding_store is None or self.closure is None:
            raise ContractViolation("an available operator provider requires a physical binding")
        if context.check_control is None:
            raise ContractViolation("an operator acquisition requires invocation control")
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        acquisition = acquisition_id_for(logical, context.run_lease.epoch)
        handle = CodexOperatorHandle(
            self, context, AcquisitionPaths(self._acquisition_root, acquisition),
        )
        self.handles.append(handle)
        return AcquiredCapability(
            resource=handle, lease_id=logical, acquisition_id=acquisition,
            resource_ref=_resource_reference(
                acquisition, self.identity.store.operator_binding_digest,
            ),
            materialize=handle.materialize,
        )

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition,
    ) -> LeaseClosure:
        handle = acquisition.resource
        expected_logical = lease_id_for(
            handle.context.run_lease.run_id,
            handle.context.path,
            handle.context.binding.binding,
        ) if isinstance(handle, CodexOperatorHandle) else ""
        expected_acquisition = acquisition_id_for(
            expected_logical, handle.context.run_lease.epoch,
        ) if isinstance(handle, CodexOperatorHandle) else ""
        expected_ref = _resource_reference(
            expected_acquisition, self.identity.store.operator_binding_digest,
        ) if isinstance(handle, CodexOperatorHandle) else ""
        if (
            not isinstance(handle, CodexOperatorHandle)
            or handle.provider is not self
            or handle not in self.handles
            or acquisition.lease_id != expected_logical
            or acquisition.acquisition_id != expected_acquisition
            or acquisition.resource_ref != expected_ref
        ):
            raise ContractViolation("codex close requires its own handle")
        await handle.cleanup(disposition)
        return LeaseClosure(disposition="released" if disposition == "release" else "discarded")

    async def reconcile(
        self, context: LeaseContext, stale: tuple[StaleAcquisition, ...],
    ) -> LeaseReconciliation:
        if self.binding_store is None or self.closure is None:
            raise ContractViolation("codex recovery requires its configured physical binding")
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        pending: list[tuple[str, str, Disposition]] = []
        for item in stale:
            row = item.lease
            expected = acquisition_id_for(logical, row.acquisition_epoch)
            if (
                row.lease_id != logical or row.run_id != context.run_lease.run_id
                or row.path != context.path or row.binding_id != context.binding.binding
                or row.acquisition_epoch >= context.run_lease.epoch
                or row.resource_ref is None
            ):
                raise ContractViolation("a codex recovery row is not this stale invocation")
            acquired, binding_digest = _read_resource_reference(row.resource_ref)
            if (
                acquired != expected
                or binding_digest != self.identity.store.operator_binding_digest
            ):
                raise ContractViolation(
                    "a codex recovery reference contradicts its durable row"
                )
            pending.append((expected, row.resource_ref, item.disposition))
        # Validate the complete batch before committing any irreversible fence.
        for acquired, _, disposition in pending:
            await dispose_acquisition(
                self.closure,
                AcquisitionPaths(self._acquisition_root, acquired),
                disposition=disposition,
            )
        return LeaseReconciliation(reaped=tuple(reference for _, reference, _ in pending))


ADAPTER_REVISION = digest("codex-operator-adapter", 1, {
    member.__name__: inspect.getsource(member)
    for member in (CodexConversation, CodexOperatorHandle, CodexOperatorProvider)
})
"""Derived from this adapter's actual bodies, not a manual version."""
