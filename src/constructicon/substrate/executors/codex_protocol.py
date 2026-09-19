"""The pure Codex app-server protocol: framing, requests, the mode gate, decode.

No I/O, no process, and deliberately no launcher import: process facts arrive
through the structural :class:`ProcessFacts` protocol below, so every
interesting judgement in ADR 0021's operator-bound Codex route is provable on
any platform with zero credentials (I7). Its two consumers are
:mod:`constructicon.substrate.executors.codex`, which drives it against a real
contained process, and the protocol tests, which drive it against scripted
bytes (I6).

**What the subscription-mode gate does and does not establish.** The supported
observation is ``account/read``. It reads a process-global credential cache and
never reloads, so a turn that triggers no refresh returns a byte-identical
reply; the second reading is therefore *not* proof that anything was
re-observed. It is required by ADR 0021, and it is load-bearing against a
change that did occur — a switch to an API key, to Bedrock keys or to provider
headers changes the reported account shape, and the pre-acceptance reading then
refuses the result. The gate is also silent about *which* ChatGPT credential is
in use: four pinned credential variants collapse onto one account shape. That
distinction is not observable through the supported operation, is covered by
the published ``operator_bound_vendor_identity_unverified`` literal, and is
recorded in ``docs/plans/handoffs/M8-subscription-mode-interface-screen.md``.
The deprecated operation that would name the variant is excluded as a boundary
in either direction.

**Where ``ProcessFacts`` lives, deliberately.** Its symmetric home is beside
``ProcessIO`` in :mod:`constructicon.core.process`, and a future second native
adapter should move it there. It stays in L1 for this slice because promoting
it makes this an L0 change, which carries an invariant review it does not need,
and the protocol already has its two consumers here.

**Account facts never leave this module, and two distinct frames carry them.**
An ``account/read`` *reply* carries an email and a plan type; it is id-bearing,
and the fold below drops every id-bearing record. A server-initiated
``account/`` *notification* carries the same class of fact with no id at all:
``docs/plans/handoffs/M8-native-account-interface-preflight.md`` records, with
pinned source links, that "Login responses and account notifications expose flow
ids, auth mode, or plan type". So the fold drops the whole ``account/``
namespace too, and the adapter refuses when one arrives. Bytes that fail to
parse cannot be classified at all, so any that mention an account are dropped
from the excerpt as well — a corrupted *reply* names the account object key
rather than the method namespace, so the broader marker is the one that holds
there. Their count and damage are still reported. The guarantee is therefore
exactly this: no account frame, parseable or not, reaches
``ExecutorObservation.raw_reply``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import (
    ExecutorError,
    ExecutorFailure,
    ExecutorOutcome,
    ExecutorPartial,
    ExecutorSuccess,
    RateLimitInfo,
    TaskSpec,
    TransportDamage,
    Usage,
)
from constructicon.core.grants import EffectiveGrants
from constructicon.core.identity import parse_json_value

READ_WINDOW = 8192
"""The launcher's hard per-read ceiling; ``read`` accepts only 1 through this."""

RECORD_BYTES = 256 * 1024
"""One record's ceiling, matching the existing wires and far under the 4 MiB
record bound the launcher enforces. Breaching the launcher's bound stops the
channel; this smaller ceiling turns an unterminated record into ordinary
damage first."""

EVIDENCE_BYTES = 256
"""Bounded stderr evidence; never the whole stream."""


# --- framing -----------------------------------------------------------------


def encode_record(value: Mapping[str, Any]) -> bytes:
    """One line-delimited JSON record, refused before it can be sent oversized.

    Writes spend a cumulative budget and cannot be retried, so an outbound
    record that cannot fit is a contract violation here rather than a partial
    write the caller would be forbidden to repair.
    """

    raw = (json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False) + "\n").encode()
    if len(raw) > RECORD_BYTES:
        raise ContractViolation("an outbound protocol record exceeds the record ceiling")
    return raw


def split_records(buffer: bytearray) -> list[bytes]:
    """Consume every complete line; the incomplete tail stays in the buffer."""

    records: list[bytes] = []
    while True:
        index = buffer.find(b"\n")
        if index < 0:
            return records
        records.append(bytes(buffer[:index]))
        del buffer[: index + 1]


@dataclass
class RecordStream:
    """Line framing over arbitrary chunks. An overlong record is damage.

    A bounded record is the point: exceeding the bound must not raise out of a
    byte scope and lose the stream, and it must never leave a clamped read
    argument of zero, which is itself a launcher contract violation.
    """

    pending: bytearray = field(default_factory=bytearray)
    damage: str | None = None

    def next_read(self) -> int:
        """Clamp one read to the remaining record budget and the read window."""

        remaining = RECORD_BYTES - len(self.pending)
        if remaining < 1:
            raise ContractViolation("a clamped read argument must stay within 1..8192")
        return min(READ_WINDOW, remaining)

    def feed(self, chunk: bytes) -> list[bytes]:
        """Empty bytes are EOF: an unterminated tail is refused, never accepted."""

        if not chunk:
            if self.pending:
                self.damage = self.damage or "the native stream ended inside a record"
                self.pending.clear()
            return []
        self.pending.extend(chunk)
        records = split_records(self.pending)
        if len(self.pending) >= RECORD_BYTES:
            self.damage = self.damage or "a native protocol record exceeds its ceiling"
            self.pending.clear()
        return records


# --- requests ----------------------------------------------------------------

PROVIDER_OVERRIDE_FIELDS = frozenset({"model", "modelProvider"})
"""``thread/start`` accepts both, and neither is experimental. The mode gate
reads the *configured* provider, so a session that cleared the gate could still
run its turn somewhere else. No builder here has a parameter that can reach
either field, and :func:`_sealed` refuses one that appears anyway."""


def _sealed(request: dict[str, Any]) -> dict[str, Any]:
    params = request.get("params")
    if isinstance(params, Mapping):
        overrides = sorted(PROVIDER_OVERRIDE_FIELDS & set(params))
        if overrides:
            raise ContractViolation(
                f"a native session request may never carry {overrides!r}: the mode gate "
                "observes only the configured provider"
            )
    return request


def initialize_request(request_id: int, *, client: str, version: str) -> dict[str, Any]:
    """Initialize one session without the experimental capability.

    ``capabilities.experimentalApi`` is what enables the externally supplied
    token login ADR 0021 excludes. The investigation fixture sets it for its own
    purposes; this adapter must never copy that line.
    """

    return _sealed({
        "id": request_id,
        "method": "initialize",
        "params": {
            "clientInfo": {"name": client, "version": version},
            "capabilities": {},
        },
    })


def initialized_notification() -> dict[str, Any]:
    return {"method": "initialized"}


def account_read_request(request_id: int) -> dict[str, Any]:
    """Observe the authentication mode; never cause a refresh."""

    return _sealed({
        "id": request_id, "method": "account/read", "params": {"refreshToken": False},
    })


def thread_start_request(request_id: int, *, cwd: str) -> dict[str, Any]:
    """One ephemeral thread, with no model, no provider and no approval policy.

    ``approvalPolicy`` is marked experimental-nested at the pin, so which of its
    variants are reachable without the experimental capability depends on that
    enum's own markers. The investigation fixture can set it only because it
    opts in, which this adapter must never do, so the field is not sent at all:
    the fixed configuration already disables every native tool, so no approval
    can arise. A turn that blocks awaiting one is a refusal here and a finding
    for N3, never a prompt to answer. Verify the reachable variants before any
    later slice relies on a value.

    The native zone has no workspace and no admitted callback in this slice, so
    the vendor sandbox value is defense in depth over physical containment the
    launcher already owns, never the boundary itself. ``"read-only"`` is
    unexercised against the pinned binary and this slice cannot exercise it: the
    credential-free lane refuses at the pre-turn gate, so no ``thread/start``
    ever reaches it. The only sandbox value this repository has observed live is
    ``"danger-full-access"``, and only from a session that opted into the
    experimental capability, so it is not evidence for this adapter either.
    Verify the reachable variants, here as for the approval policy, before a
    later slice relies on one.
    """

    return _sealed({
        "id": request_id,
        "method": "thread/start",
        "params": {
            "cwd": cwd,
            "sandbox": "read-only",
            "ephemeral": True,
        },
    })


def turn_request(
    request_id: int, *, thread_id: str, task: TaskSpec, grants: EffectiveGrants,
) -> dict[str, Any]:
    """One turn. The model reaches the session through the sealed configuration.

    The grants are a precondition, not wire content: a backend default would
    mean the executing session chose its own model, which the v3 profile
    forbids. Nothing about the selection is sent, because a per-turn model or
    provider field is the second override channel the gate cannot see.
    """

    selection = grants.model_selection
    if selection.kind != "explicit" or not (selection.model or "").strip():
        raise ContractViolation("a native operator turn requires an explicit sealed model")
    return _sealed({
        "id": request_id,
        "method": "turn/start",
        "params": {
            "threadId": thread_id,
            "input": [{"type": "text", "text": task.instruction}],
        },
    })


# --- the subscription-mode gate ----------------------------------------------

ACCOUNT_TYPE_KEY = "type"
PLAN_TYPE_KEY = "planType"
PROVIDER_FLAG_KEY = "requiresOpenaiAuth"
"""The three wire keys the gate reads, and what backs each of them.

``requiresOpenaiAuth`` and the enclosing ``account`` key are confirmed against
the pinned binary by a live capture: ``test_combined_startup_origins.py`` asserts
``{"account": None, "requiresOpenaiAuth": False}`` from a real session. That
capture also establishes the wire's camelCase convention, which the handoff
records observe consistently — snake_case when quoting Rust identifiers,
camelCase when quoting the wire.

``planType`` is named by pinned source rather than guessed: the account
interface preflight states that ``account/read`` returns ChatGPT ``email`` and
``planType``, with source links. It is nonetheless the one key here with no live
capture behind it, and that gap is structural rather than an oversight — the
only credential-free lane we can run returns a *null* account, so no capture of
a populated account exists or can be obtained without a credential. A wrong key
would make fault 5 fire against a real managed account: fail closed, and first
observable at N4 where a binding exists.
"""

NO_RESULT_FAULT = "the subscription-mode reading is an error or carries no result object"
NO_ACCOUNT_FAULT = "the session reports no usable account"
PROVIDER_OVERRIDE_FAULT = (
    "the configured provider does not require OpenAI authentication, so this session "
    "can run without the subscription credential"
)
NO_PLAN_FAULT = "the account carries no plan fact"

ACCOUNT_NAMESPACE = "account/"
"""Every account-bearing method, refused as a namespace rather than a list.

The enumeration this repository holds is of *requests*: the preflight record
lists the retained binary's eleven ``account/``-prefixed methods from its
generated inventory, and the notification surface is separate and unenumerated.
Naming individual notification methods would therefore be guessing at a list we
do not have, so the namespace is the unit and the posture is fail closed.
"""

ACCOUNT_EVIDENCE_MARKER = b"account"
"""Deliberately broader than the namespace, and only for bytes that would not parse.

Classification needs a parsed record, so unparseable bytes get a substring test
instead — and the namespace is the wrong substring for them. A corrupted
``account/read`` **reply** carries the account *object* key, which has no slash:
``{"id": 3, "result": {"account": {"email": ...`` contains ``account`` but not
``account/``. Keying the excerpt guard on the namespace alone would therefore
let a truncated reply carry an operator's email into a public field.

The cost is that a malformed line mentioning "account" for any reason loses its
excerpt. Its count and its damage are still reported, so the outcome stays
truthful (I4); only the evidence text is lost, which is the right trade for this
class of bytes.
"""

ACCOUNT_NOTICE_FAULT = "the session reported {method!r} during the turn"
"""Neutral by construction. ADR 0021 refuses on "an observed mode change" and
requires qualification that refresh "cannot silently select API/cloud
authentication mid-turn"; a mode-change notification lands in exactly the window
the two readings bracket but cannot cover. Because the namespace is refused
wholesale, a record that is not ``account/updated`` need not be a mode change,
so the text claims none — the method name supplies the specificity. Nothing from
``params`` may appear here: ``ExecutorError.detail`` is public.
"""


@dataclass(frozen=True, kw_only=True)
class ExpectedAccount:
    """The account shape established when the binding generation was provisioned.

    An assembly fact. Never caller input, never derived from a task or a grant.
    The plan is required: the pinned plan type is an untagged union with a known
    ``free`` member, so an accept-any default would admit a free ChatGPT plan as
    a vendor-managed subscription and a later lapse to free would go unnoticed.
    """

    plan_type: str
    account_type: Literal["chatgpt"] = "chatgpt"

    def __post_init__(self) -> None:
        if not self.plan_type.strip():
            raise ValueError("an expected account requires the plan recorded at provisioning")


def is_account_record(record: Mapping[str, Any]) -> bool:
    """Whether one parsed record belongs to the account namespace."""

    method = record.get("method")
    return isinstance(method, str) and method.startswith(ACCOUNT_NAMESPACE)


def _result_object(reply: Any) -> Mapping[str, Any] | None:
    if not isinstance(reply, Mapping) or "error" in reply:
        return None
    result = reply.get("result")
    return result if isinstance(result, Mapping) else None


def account_faults(reply: Any, expected: ExpectedAccount) -> tuple[str, ...]:
    """Itemized reasons this reading is not a vendor-managed subscription.

    Empty means ok, in the same shape as ``grant_faults``. Absence, error and
    unknown values all refuse. The provider-authentication check is not a second
    account check: it reflects the *active provider*, and a false value means
    this session can run with no OpenAI credential at all, which is exactly the
    provider override ADR 0021 requires the adapter to exclude.

    This says nothing about which ChatGPT credential is in use; see the module
    docstring and the pinned interface screen.
    """

    result = _result_object(reply)
    if result is None:
        return (NO_RESULT_FAULT,)
    account = result.get("account")
    known = account if isinstance(account, Mapping) else None
    plan = known.get(PLAN_TYPE_KEY) if known is not None else None
    faults: list[str] = []
    if known is None:
        faults.append(NO_ACCOUNT_FAULT)
    if known is not None and known.get(ACCOUNT_TYPE_KEY) != expected.account_type:
        faults.append(
            f"account type {known.get(ACCOUNT_TYPE_KEY)!r} is not the expected "
            f"{expected.account_type!r}"
        )
    if result.get(PROVIDER_FLAG_KEY) is not True:
        faults.append(PROVIDER_OVERRIDE_FAULT)
    if known is not None and plan is None:
        # Unreachable against the pinned binary, whose wire type requires a plan
        # and surfaces absence as an error the first fault catches. Kept
        # fail-closed for a scripted or future reply that omits it.
        faults.append(NO_PLAN_FAULT)
    if plan is not None and plan != expected.plan_type:
        faults.append(f"account plan {plan!r} is not the expected {expected.plan_type!r}")
    return tuple(faults)


def _reading(reply: Any) -> tuple[Any, Any, Any]:
    result = _result_object(reply)
    if result is None:
        return (None, None, None)
    account = result.get("account")
    known = account if isinstance(account, Mapping) else None
    return (
        known.get(ACCOUNT_TYPE_KEY) if known is not None else None,
        known.get(PLAN_TYPE_KEY) if known is not None else None,
        result.get(PROVIDER_FLAG_KEY),
    )


def account_change_faults(before: Any, after: Any) -> tuple[str, ...]:
    """The pre-turn and pre-acceptance readings must agree.

    ADR 0021 refuses on "an observed mode change", and a per-reading predicate
    cannot see one. Only the three authority-bearing fields are compared; a
    difference discards the turn exactly as a fault does.
    """

    names = ("account type", "account plan", "provider authentication requirement")
    return tuple(
        f"{name} changed from {old!r} to {new!r} across the turn"
        for name, old, new in zip(names, _reading(before), _reading(after), strict=True)
        if old != new
    )


# --- observing one turn ------------------------------------------------------


@dataclass(frozen=True)
class TurnObservation:
    """What one conversation saw. Carries no process facts."""

    output: Any | None
    served_model: str | None
    usage: Usage | None
    rate_limit: RateLimitInfo | None
    terminal: bool
    malformed_records: int
    first_error: str | None
    raw: str


EMPTY_TURN = TurnObservation(
    output=None, served_model=None, usage=None, rate_limit=None, terminal=False,
    malformed_records=0, first_error=None, raw="",
)


def _turn_of(
    record: Mapping[str, Any], *, thread_id: str, turn_id: str,
) -> Mapping[str, Any] | None:
    if record.get("method") != "turn/completed":
        return None
    params = record.get("params")
    if not isinstance(params, Mapping) or params.get("threadId") != thread_id:
        return None
    turn = params.get("turn")
    if not isinstance(turn, Mapping) or turn.get("id") != turn_id:
        return None
    return turn


def is_terminal_record(line: bytes, *, thread_id: str, turn_id: str) -> bool:
    """Whether this record terminates *this* invocation's turn.

    A cheap stop condition for the reader. ``observe_turn`` remains the
    authoritative fold; a record this rejects is still judged there.
    """

    try:
        record = parse_json_value(line.decode("utf-8"))
    except (ValueError, UnicodeError):
        return False
    if not isinstance(record, dict):
        return False
    return _turn_of(record, thread_id=thread_id, turn_id=turn_id) is not None


def _usage(value: Any) -> Usage | None:
    if not isinstance(value, Mapping):
        return None  # I4: an unemitted fact stays absent, never inferred.
    fields = {
        "input_tokens": value.get("inputTokens"),
        "output_tokens": value.get("outputTokens"),
    }
    numbers = {
        name: item for name, item in fields.items() if type(item) is int
    }
    return Usage(**numbers) if numbers else None


def _rate_limit(value: Any) -> RateLimitInfo | None:
    if not isinstance(value, Mapping):
        return None
    overage = value.get("usingOverage")
    return RateLimitInfo(
        is_using_overage=overage if type(overage) is bool else None,
        detail=dict(value),
    )


def observe_turn(
    records: Sequence[bytes], *, thread_id: str, turn_id: str,
    transport_damage: str | None = None,
) -> TurnObservation:
    """Fold one turn's records into a truthful observation.

    Damage is sticky: a later terminal record never promotes an earlier
    malformed one, and a second terminal record is contradictory rather than
    last-wins. Every field a record did not emit stays ``None`` (I4).

    A record carrying an ``id`` is a reply or a native request. This slice
    authorizes no callback, so such a record is damage and is dropped *before*
    ``raw`` exists — that is what keeps an ``account/read`` reply, and the email
    it carries, out of the public outcome.

    An id-less ``account/`` notification carries the same class of fact and is
    dropped in the same place for the same reason. It is not malformed, so it is
    neither counted nor recorded as damage: it is simply not this turn's
    evidence. The adapter refuses on it separately, which is where it becomes an
    outcome.
    """

    output: Any = None
    served_model: str | None = None
    usage: Usage | None = None
    rate_limit: RateLimitInfo | None = None
    terminal = False
    malformed = 0
    first_error = transport_damage
    kept: list[str] = []
    for line in records:
        if not line.strip():
            continue
        try:
            record = parse_json_value(line.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            malformed += 1
            first_error = first_error or f"malformed native record: {exc}"
            if ACCOUNT_EVIDENCE_MARKER not in line:
                # Unparseable bytes are transport evidence worth keeping, but
                # bytes that mention an account at all cannot be classified, so
                # they are not worth the risk of carrying an account fact into a
                # public field. The count and the damage still report them
                # truthfully (I4); only the excerpt is lost.
                kept.append(line.decode("utf-8", errors="replace"))
            continue
        if not isinstance(record, dict) or "id" in record or "method" not in record:
            malformed += 1
            first_error = first_error or "a turn transcript carries native notifications only"
            continue
        if is_account_record(record):
            continue
        kept.append(line.decode("utf-8", errors="replace"))
        if record.get("method") == "turn/completed":
            turn = _turn_of(record, thread_id=thread_id, turn_id=turn_id)
            if turn is None:
                malformed += 1
                first_error = first_error or "a terminal record names another invocation"
                continue
            if terminal:
                malformed += 1
                first_error = first_error or "contradictory terminal turn records"
                continue
            terminal = True
            if turn.get("status") != "completed":
                first_error = first_error or f"the turn reported status {turn.get('status')!r}"
            output = turn.get("output")
            model = turn.get("model")
            served_model = model if isinstance(model, str) else None
            usage = _usage(turn.get("usage"))
            rate_limit = _rate_limit(turn.get("rateLimits"))
    return TurnObservation(
        output=output, served_model=served_model, usage=usage, rate_limit=rate_limit,
        terminal=terminal, malformed_records=malformed, first_error=first_error,
        raw="\n".join(kept),
    )


# --- decode ------------------------------------------------------------------


class ProcessFacts(Protocol):
    """What a finished contained process reports; ``ProcessResult`` satisfies it.

    Every member is a read-only property because the launcher's result is a
    frozen dataclass; a plain annotation would demand a settable attribute.
    """

    @property
    def returncode(self) -> int: ...

    @property
    def payload_returncode(self) -> int | None: ...

    @property
    def timed_out(self) -> bool: ...

    @property
    def bound_exceeded(self) -> str | None: ...

    @property
    def elapsed_s(self) -> float: ...

    @property
    def stderr(self) -> bytes: ...


def _evidence(process: ProcessFacts) -> str:
    return process.stderr.decode("utf-8", errors="replace")[:EVIDENCE_BYTES]


def decode_turn(
    observation: TurnObservation, process: ProcessFacts, *, requested_model: str | None,
) -> ExecutorOutcome:
    """One finished conversation plus its process facts, as one outcome.

    The order is load-bearing. A timeout salvages whatever output was seen. An
    absent or mismatched private exit report is infrastructure, not a task
    result, and is judged *before* any success or exit verdict: judging on the
    bare return code alone would decode a missing exit report as success.
    """

    fields: dict[str, Any] = {
        "output": observation.output,
        "raw_reply": observation.raw,
        "requested_model": requested_model,
        "served_model": observation.served_model,
        "usage": observation.usage,
        "rate_limit": observation.rate_limit,
        "elapsed_s": process.elapsed_s,
    }
    if process.timed_out:
        return ExecutorFailure(**fields, error=ExecutorError(
            kind="timeout", detail="the owned native conversation reached its deadline",
            timed_out_after_s=process.elapsed_s, produced_output=observation.terminal,
        ))
    incomplete = (
        process.payload_returncode is None or process.payload_returncode != process.returncode
    )
    damage = (
        process.bound_exceeded
        or ("the launcher did not report a complete native exit" if incomplete else None)
        or observation.first_error
        or (None if observation.terminal else "no terminal turn record")
    )
    if process.returncode and not (process.bound_exceeded or incomplete):
        return ExecutorFailure(**fields, error=ExecutorError(
            kind="exit", detail="the native client exited nonzero",
            exit_code=process.returncode, produced_output=observation.terminal,
        ))
    if damage:
        return ExecutorPartial(**fields, damage=TransportDamage(
            malformed_records=observation.malformed_records, first_error=damage,
            evidence_excerpt=_evidence(process),
        ))
    return ExecutorSuccess(**fields)


def unavailable_outcome(
    faults: Sequence[str], observation: TurnObservation, process: ProcessFacts, *,
    requested_model: str | None,
) -> ExecutorFailure:
    """A refused gate discards the turn's result rather than reporting it.

    ADR 0021 refuses *result acceptance*, so nothing the turn produced survives
    into the outcome. That a turn ran is itself truthful and is reported, once,
    through ``produced_output``.
    """

    return ExecutorFailure(
        requested_model=requested_model,
        elapsed_s=process.elapsed_s,
        error=ExecutorError(
            kind="unavailable",
            detail="; ".join(faults),
            produced_output=observation.terminal,
        ),
    )
