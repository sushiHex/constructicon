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
re-observed. It is required by ADR 0021, and it detects a mode change the
session **honestly reports** — the vendor-refresh case that ADR names. A switch
to an API key, to Bedrock keys or to provider headers changes the reported
account shape, and the pre-acceptance reading then refuses the result.

It is not, and cannot be, a defense against a session that *misreports* its own
mode. The mode is the vendor's assertion about itself and the vendor holds the
credentials, so a client willing to lie could run on an API key and answer
``chatgpt`` in a perfectly ordinary reply. No correlation scheme distinguishes
that from the truth, which is why the adapter does not attempt one.

The gate is also silent about *which* ChatGPT credential is in use: four pinned
credential variants collapse onto one account shape. That
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
namespace too, and the adapter refuses every such notification except the one
plan-checked rate-limit update (:func:`account_notice_faults`). The spend
readback's reply is id-bearing like the account reading's. Bytes that fail to parse
cannot be classified at all, so none of them is published: what is published is
their *count* and a reason drawn from a closed set of literals. The decoder's own
message is not published, because it names the offending key and a key name is
wire content — that was a leak, not a caveat.

**The exact scope of that guarantee, which is narrower than it sounds.** No
*account frame* reaches ``ExecutorObservation.raw_reply``: not an id-bearing
reply, not an ``account/``-namespaced notification, not unparseable bytes, and
not a record whose method is outside the attested turn-evidence set. What the
mechanism cannot promise is the *content of a legitimate turn record*. A
``turn/completed`` for this thread and turn is this turn's evidence and its
payload is the vendor's; if the vendor puts an account id inside it, it is in
``raw``, and no filter can remove it without a payload vocabulary this slice does
not hold and must not guess. Qualifying what those payloads may contain is an
N3/N4 prerequisite. The same applies to the bounded stderr excerpt below: it is
unfiltered vendor output, it is kept because it is the only transport diagnosis
available, it cannot carry an account fact in this credential-free slice, and
establishing what the pinned binary writes there is an N4 prerequisite.
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
"""Bounded stderr evidence; never the whole stream.

Unfiltered vendor output, deliberately: filtering it would be the same
unwinnable heuristic as filtering bytes we could not parse. It is kept because
it is the only transport diagnosis available. See the module docstring for the
limit this records."""


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


class RecordDamaged(ValueError):
    """One record's bytes cannot be decoded. Damage, never an escape.

    Its message is always one of :data:`DAMAGE_REASONS` and never the decoder's
    own text, which names the offending key and is therefore wire content.
    """


DAMAGE_MALFORMED = "malformed json"
DAMAGE_REPEATED_KEY = "a repeated object key"
DAMAGE_ENCODING = "an encoding failure"
DAMAGE_NESTING = "nesting too deep"
DAMAGE_REASONS = frozenset({
    DAMAGE_MALFORMED, DAMAGE_REPEATED_KEY, DAMAGE_ENCODING, DAMAGE_NESTING,
})
"""The closed set of reasons a record could not be decoded.

Classified, not truncated. The decoder reports a duplicated key by naming it, and
a key name is wire-controlled, so its message is exactly as publishable as an
account field — and truncating still publishes the first characters, which an
email fits inside. A reader needs the fact and the count of a decode failure;
the offending bytes are what the value classifier exists to keep out of public
fields, and this was the one channel that bypassed it.
"""


def _damage_reason(exc: ValueError) -> str:
    """Choose a literal. The decoder's message is read here and never leaves.

    The duplicate-key case has no distinct exception type to match on, so this
    reads our own message — ``core/identity.py``'s wording, not the vendor's — to
    pick a literal. Nothing derived from it is returned. If that wording is ever
    reworded, the classification degrades to ``malformed json`` and a test
    notices; no wire content escapes either way.
    """

    return DAMAGE_REPEATED_KEY if "repeats key" in str(exc) else DAMAGE_MALFORMED


def parse_record(line: bytes) -> Any:
    """Decode one record's bytes, or raise :class:`RecordDamaged`.

    The bounded set of decoder failures is named here, once, because it has four
    call sites and they must not drift. ``RecursionError`` is in it and is the
    reason this helper exists: a record of a few thousand nested arrays sits far
    inside the record ceiling, yet the decoder exhausts the stack on it, and
    ``RecursionError`` is neither a ``ValueError`` nor a ``UnicodeError``. Left
    uncaught it escaped the whole conversation, whose ``finally`` had already
    closed stdin and drained to EOF — so the child exited cleanly, the launcher
    reported a complete result, and a turn was published although the
    pre-acceptance gate never ran.

    Shape checks stay with the callers, which want different things from a
    record; only the decode is shared.
    """

    try:
        return parse_json_value(line.decode("utf-8"))
    except RecursionError as exc:
        raise RecordDamaged(DAMAGE_NESTING) from exc
    except UnicodeError as exc:
        # Before ``ValueError``: ``UnicodeError`` is one of its subclasses.
        raise RecordDamaged(DAMAGE_ENCODING) from exc
    except ValueError as exc:
        raise RecordDamaged(_damage_reason(exc)) from exc


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


def initialize_request(
    request_id: int, *, client: str, version: str, experimental_api: bool = False,
) -> dict[str, Any]:
    """Initialize one session, opting in only for the sealed WRITE callback.

    The default deliberately preserves the READ request bytes. At the retained
    pin the boolean admits experimental request fields on this client
    connection; it is not itself an authentication or routing operation. The
    adapter's closed request constructors remain the authority boundary.
    """

    if type(experimental_api) is not bool:
        raise ContractViolation("the experimental capability selector must be boolean")

    return _sealed({
        "id": request_id,
        "method": "initialize",
        "params": {
            "clientInfo": {"name": client, "version": version},
            "capabilities": {"experimentalApi": True} if experimental_api else {},
        },
    })


def initialized_notification() -> dict[str, Any]:
    return {"method": "initialized"}


def account_read_request(request_id: int) -> dict[str, Any]:
    """Observe the authentication mode; never cause a refresh."""

    return _sealed({
        "id": request_id, "method": "account/read", "params": {"refreshToken": False},
    })


def rate_limits_read_request(request_id: int) -> dict[str, Any]:
    """The spend readback: the pinned request has no params at all.

    ``common.rs:1234-1238`` declares ``params`` as an omitted unit, and the
    wire test at ``:3014-3030`` serializes exactly ``{"id", "method"}``. It is
    also the first request that exercises the credential: the handler calls
    ``AuthManager::auth()``, which may refresh (M8-N4-state-review.md, Inputs 5-6).
    """

    return _sealed({"id": request_id, "method": RATE_LIMITS_READ})


CONTAINED_PYTHON = "contained_python"
CONTAINED_PYTHON_CATALOG = (CONTAINED_PYTHON,)
CONTAINED_PYTHON_TOOL: dict[str, Any] = {
    "type": "function",
    "name": CONTAINED_PYTHON,
    "description": "Run Python in the invocation's isolated contained worker.",
    "inputSchema": {
        "type": "object",
        "properties": {"program": {"type": "string"}},
        "required": ["program"],
        "additionalProperties": False,
    },
}
"""The one callback declaration this protocol can register."""

MAX_TOOL_CALLS = 8
TOOL_IDENTIFIER_BYTES = 1024
TOOL_PROGRAM_BYTES = 128 * 1024
TOOL_OUTPUT_BYTES = 32 * 1024
"""Code-bound per-turn mediation limits, included in ``PROTOCOL_REVISION``."""


def thread_start_request(
    request_id: int, *, cwd: str,
    dynamic_tools: tuple[Mapping[str, Any], ...] = (),
) -> dict[str, Any]:
    """One ephemeral thread, with no model, no provider and no approval policy.

    ``approvalPolicy`` is marked experimental-nested at the pin. Even WRITE,
    which opts in for ``dynamicTools``, omits it: the fixed configuration is
    responsible for disabling native tools and every server request except the
    exact dynamic callback is refused. A turn that asks for approval is never
    answered here.

    The native zone has no workspace, so the vendor sandbox value is defense in
    depth over physical containment the launcher already owns, never the worker
    boundary. The admitted callback executes in a distinct contained process.
    """

    if dynamic_tools and tuple(dynamic_tools) != (CONTAINED_PYTHON_TOOL,):
        raise ContractViolation("the native session can register only contained_python")
    params: dict[str, Any] = {
        "cwd": cwd,
        "sandbox": "read-only",
        "ephemeral": True,
    }
    if dynamic_tools:
        # Construct fresh nested objects so a caller cannot retain and mutate a
        # request after this constructor has admitted it.
        params["dynamicTools"] = [{
            "type": "function",
            "name": CONTAINED_PYTHON,
            "description": CONTAINED_PYTHON_TOOL["description"],
            "inputSchema": {
                "type": "object",
                "properties": {"program": {"type": "string"}},
                "required": ["program"],
                "additionalProperties": False,
            },
        }]
    return _sealed({
        "id": request_id,
        "method": "thread/start",
        "params": params,
    })


@dataclass(frozen=True)
class ToolCall:
    """One strictly decoded server request in its own identifier domain."""

    request_id: int | str
    thread_id: str
    turn_id: str
    call_id: str
    program: str


def _bounded_wire_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value.encode("utf-8")) <= TOOL_IDENTIFIER_BYTES
    )


def parse_tool_call(
    record: Mapping[str, Any], *, thread_id: str, turn_id: str | None,
) -> ToolCall:
    """Decode the sole server request without exposing an extensible router.

    ``turn_id=None`` is the bounded pre-identity check: all other fields are
    validated, but no effect is authorized until the turn-start reply supplies
    the identity and the same record is checked again.
    """

    if set(record) != {"id", "method", "params"}:
        raise ContractViolation("the callback request has an unknown top-level field")
    request_id = record["id"]
    if not (
        type(request_id) is int
        or (type(request_id) is str and _bounded_wire_name(request_id))
    ):
        raise ContractViolation("the callback request has an invalid request id")
    if record["method"] != "item/tool/call":
        raise ContractViolation("the native client requested an unauthorized operation")
    params = record["params"]
    required = {"threadId", "turnId", "callId", "tool", "arguments"}
    allowed = required | {"namespace"}
    if (
        not isinstance(params, dict)
        or not required <= set(params)
        or set(params) - allowed
        or params.get("namespace") is not None
    ):
        raise ContractViolation("the callback request has an invalid parameter shape")
    if params["threadId"] != thread_id:
        raise ContractViolation("the callback request belongs to another thread")
    if turn_id is not None and params["turnId"] != turn_id:
        raise ContractViolation("the callback request belongs to another turn")
    if not _bounded_wire_name(params["turnId"]):
        raise ContractViolation("the callback request has an invalid turn id")
    if params["tool"] != CONTAINED_PYTHON:
        raise ContractViolation("the callback request names an unauthorized tool")
    call_id = params["callId"]
    if not _bounded_wire_name(call_id):
        raise ContractViolation("the callback request has an invalid call id")
    arguments = params["arguments"]
    if not isinstance(arguments, dict) or set(arguments) != {"program"}:
        raise ContractViolation("the callback request has invalid tool arguments")
    program = arguments["program"]
    if not isinstance(program, str) or len(program.encode("utf-8")) > TOOL_PROGRAM_BYTES:
        raise ContractViolation("the callback program exceeds its closed input bound")
    return ToolCall(
        request_id=request_id,
        thread_id=params["threadId"],
        turn_id=params["turnId"],
        call_id=call_id,
        program=program,
    )


def tool_call_response(call: ToolCall, output: str) -> dict[str, Any]:
    """Build the only response to a server request this adapter can send."""

    if not isinstance(output, str) or len(output.encode("utf-8")) > TOOL_OUTPUT_BYTES:
        raise ContractViolation("the callback output exceeds its closed output bound")
    return {
        "id": call.request_id,
        "result": {
            "contentItems": [{"type": "inputText", "text": output}],
            "success": True,
        },
    }


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

UNSOLICITED_REPLY_FAULT = "a reply arrived before the request it claims to answer"
ANSWERED_NOTHING_FAULT = "a native reply answers no request this conversation made"
DUPLICATE_REPLY_FAULT = "a second native reply bears an id already answered"

INCONCLUSIVE_DRAIN_FAULT = (
    "the duplicate-reply check could not be completed, so no result may be accepted"
)
"""An unfinished check is not a pass.

The drain to EOF is the primary defence against a client answering one request
twice, so damage that stops it short leaves us unable to prove no duplicate
arrived. This slice already refuses to count an unmeasured mutant as a kill or a
test that never ran as evidence; the same rule applies here.
"""

GATE_INCOMPLETE_FAULT = (
    "the subscription-mode gate did not complete, so no result may be accepted"
)
"""An empty fault tuple is not evidence that the gate cleared.

Empty has a second meaning: the conversation was aborted before it could record
anything. The adapter used to infer "cleared" from "empty", which published a
turn although the pre-acceptance reading never ran. The conversation now records
its completion affirmatively and states this fault when it did not, so the
negative inference is gone.
"""

ACCOUNT_NAMESPACE = "account/"
PROVIDER_NAMESPACE = "modelProvider/"
RATE_LIMITS_UPDATED = "account/rateLimits/updated"
RATE_LIMITS_READ = "account/rateLimits/read"
"""The account and provider-authentication notification surface, enumerated.

The pinned generated ``ServerNotification.json`` holds exactly three
``account/`` notifications (lines 7596-7610, 7616-7630, 8318-8332):
``account/updated`` (the auth mode and ``planType``) and ``account/login/completed``
both refuse; ``account/rateLimits/updated`` is emitted on every token-count
event of a turn (``bespoke_event_handling.rs:1676-1701``) and is admitted only
by :func:`account_notice_faults`'s plan rule. Every other member of either
namespace still refuses, so an unknown future method fails closed. The
``modelProvider/`` pair (``common.rs:1920-1921``) names a provider and a
recovery message: it is a provider-authentication event, refused rather than
silently withheld (M8-N4-state-review.md, section 3).
"""

TURN_EVIDENCE_PREFIXES = ("turn/",)
TURN_EVIDENCE_METHODS = frozenset({"error", "warning", "configWarning"})
"""What a turn transcript may carry: one earned prefix and three exact names.

``error``, ``warning`` and ``configWarning`` are **names** — a closed
enumeration, and each was observed from the pinned binary directly
(``tests/substrate/test_native_startup.py`` asserts an ``error`` carrying
``threadId`` and ``turnId`` during a turn, and the bubblewrap ``warning``
verbatim).

``turn/`` is the one **prefix**, and it is earned rather than assumed: its
terminal member ``turn/completed`` is attested from the real binary
(``tests/substrate/test_provider_placement.py``, ``test_native_startup.py``), and
this module's turn projection — terminal detection, served model, usage — is
defined in terms of that namespace's semantics. A prefix still admits
members never observed, so this is the one place that residual is accepted, and
it is frame admission inside a namespace that is the invocation's own by
construction.

**``item/`` was considered and excluded**, deliberately, not by oversight. The
only ``item/`` member this repository has ever seen is ``item/tool/call``
(``tests/native_codex_probe.py``), and that is an **id-bearing request**, which
this adapter refuses as damage by design. So the namespace has never been
observed emitting a notification at all, and admitting it would be an assumption
about an unobserved surface — the exact thing this allowlist exists to remove.
``item/started`` and ``item/completed``, used in this repository's own tests, are
invented names. Add ``item/`` back at N4 once a real stream has been observed and
its methods can be named: a one-line change backed by evidence.
``hook/started`` and ``hook/completed`` are attested but are session-start
activity rather than turn evidence, so they stay out too.

The cost is real and points the right way: an unattested notification is excluded
from ``raw`` rather than published, and is not counted as malformed because it is
not damage. But exclusion must never be *silent* — a near-empty transcript with
no indication anything was withheld is an evidence blackout at exactly the moment
N4 needs evidence, which is structurally the same defect as a gate that passes
without running. So the fold counts every record it excludes as
unclassified and says so in the transcript's own marker. Blank lines are the one
thing skipped without a count: they carry no evidence and there is nothing about
them to report.
"""


def is_turn_evidence(record: Mapping[str, Any]) -> bool:
    """Whether one parsed notification is this turn's attested evidence."""

    method = record.get("method")
    if not isinstance(method, str):
        return False
    return method in TURN_EVIDENCE_METHODS or method.startswith(TURN_EVIDENCE_PREFIXES)


NAMEABLE_VALUE = 32
"""How much of a wire value may appear in a public fault detail."""

NAMEABLE_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
"""ASCII alphanumerics, spelled out because ``str.isalnum`` is Unicode-aware.

The docstring below claimed ``[A-Za-z0-9_-]`` while the code admitted
``日本語``, Arabic-Indic digits and ``pro²``. Not exploitable — ``@`` and ``.``
stay out and the length bound holds — but a guarantee written stronger than its
mechanism is the recurring defect in this slice, so the alphabet is now literally
the one the docstring names."""

NAMEABLE_METHOD = 64
"""The same rule for a method name, which needs ``/`` and a little more room."""


def _nameable(value: Any, *, limit: int, extra: str) -> str | None:
    if isinstance(value, str) and 0 < len(value) <= limit and all(
        character in NAMEABLE_ALPHABET or character in extra for character in value
    ):
        return repr(value)
    return None


def named_method(value: Any) -> str:
    """Report a wire method name, bounded, or its type.

    Methods carry ``/`` by construction, so they cannot use the value charset;
    that would classify every real method as unnameable and strip the account
    refusal of the only specificity it has. The bound and the lexical check are
    the same idea, with the namespace separator admitted.
    """

    return _nameable(value, limit=NAMEABLE_METHOD, extra="_-/") or named_value(value)


def named_value(value: Any) -> str:
    """Report a wire value only when it is short and lexically safe.

    ``ExecutorError.detail`` is public and wire values are vendor-controlled, so
    a value reaches it only when it is a ``str`` of at most
    :data:`NAMEABLE_VALUE` characters drawn from ``[A-Za-z0-9_-]``. Anything else
    is reported as its JSON type: an object under ``account.type`` would
    otherwise carry an email into a public field, and a 200 KB plan name would
    make a 200 KB detail.

    This is why two assertions in the protocol tests that look contradictory are
    both right. A plan literal like ``'free'`` **is** named, because that is the
    diagnostic telling an operator why availability was refused; arbitrary wire
    content never is. The rule is the value's shape, not the field it came from,
    so do not "fix" either test by loosening this.
    """

    nameable = _nameable(value, limit=NAMEABLE_VALUE, extra="_-")
    if nameable is not None:
        return nameable
    if value is None:
        return "absent"
    if isinstance(value, bool):
        return repr(value)
    return f"a {type(value).__name__} value"

ACCOUNT_NOTICE_FAULT = "the session reported {method}"
"""Neutral by construction, and it names no turn: the startup phase has none.
ADR 0021 refuses on "an observed mode change" and
requires qualification that refresh "cannot silently select API/cloud
authentication mid-turn"; a mode-change notification lands in exactly the window
the two readings bracket but cannot cover. A refused record need not be a mode
change, so the text claims none — the method name supplies the specificity.
Nothing from ``params`` may appear here: ``ExecutorError.detail`` is public.
"""


@dataclass(frozen=True, kw_only=True)
class ExpectedAccount:
    """The account shape established when the binding generation was provisioned.

    An assembly fact. Never caller input, never derived from a task or a grant.
    The plan is required: the pinned plan type is an untagged union with a known
    ``free`` member, so an accept-any default would admit a free ChatGPT plan as
    a vendor-managed subscription and a later lapse to free would go unnoticed.

    ``alternatives`` exists for qualification alone. The pinned ``PlanType``
    has both ``pro`` and ``prolite`` and nothing proves which one a subscription
    reports, so the first authenticated reading may accept a declared set; the
    literal it observes becomes the sole ``plan_type`` of every later run
    (M8-N4-state-review.md, orchestrator decision 1). Production assembly
    passes none.
    """

    plan_type: str
    account_type: Literal["chatgpt"] = "chatgpt"
    alternatives: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.plan_type.strip():
            raise ValueError("an expected account requires the plan recorded at provisioning")
        if type(self.alternatives) is not tuple or not all(
            type(item) is str and item.strip() for item in self.alternatives
        ):
            raise ValueError("expected plan alternatives are non-empty literals")

    def accepts(self, plan: Any) -> bool:
        return type(plan) is str and (plan == self.plan_type or plan in self.alternatives)


def account_notice_faults(record: Mapping[str, Any], expected: ExpectedAccount) -> tuple[str, ...]:
    """Why one id-less record ends the phase, or ``()`` when it may pass.

    Only ``account/rateLimits/updated`` passes, and only with exactly the pinned
    ``{rateLimits}`` params whose ``planType`` is absent, null or accepted: the
    snapshot is documented as sparse ("Nullable account metadata ... does not
    clear a previously observed value", ``v2/account.rs:553-557``), while a
    present different plan is a plan change inside the window the readings
    bracket. Its spend facts are judged too, because the pinned client builds
    it from the model call's own response headers (``rate_limits.rs:218``):
    it is the one in-band spend record inside that window. A present credits
    object must meet the readback's zero rule, and ``spendControlReached``
    must not be true. Absent or null values stay admissible, as the sparse
    update requires.
    """

    method = record.get("method")
    if not isinstance(method, str):
        return ()
    refused = (ACCOUNT_NOTICE_FAULT.format(method=named_method(method)),)
    if method == RATE_LIMITS_UPDATED:
        params = record.get("params")
        snapshot = params.get("rateLimits") if isinstance(params, Mapping) else None
        if (
            isinstance(params, Mapping) and set(params) == {"rateLimits"}
            and isinstance(snapshot, Mapping)
            and (snapshot.get(PLAN_TYPE_KEY) is None or expected.accepts(snapshot[PLAN_TYPE_KEY]))
            and _no_spend(snapshot)
        ):
            return ()
        return refused
    if method.startswith((ACCOUNT_NAMESPACE, PROVIDER_NAMESPACE)):
        return refused
    return ()


def account_request_faults(record: Mapping[str, Any]) -> tuple[str, ...]:
    """An id-bearing record in either refused namespace refuses; nothing admits one.

    The allowlist's one admitted method is a notification. The pinned
    ``account/chatgptAuthTokens/refresh`` is a server *request* with an id, and
    an ``account/updated`` may arrive with ``"id": null``; both are account
    events, so neither may pass as ordinary damage.
    """

    method = record.get("method")
    if isinstance(method, str) and method.startswith((ACCOUNT_NAMESPACE, PROVIDER_NAMESPACE)):
        return (ACCOUNT_NOTICE_FAULT.format(method=named_method(method)),)
    return ()


def _no_spend(snapshot: Mapping[str, Any]) -> bool:
    """A sparse snapshot's spend facts: absent or null, or proven zero."""

    credits = snapshot.get("credits")
    if credits is not None and not (
        isinstance(credits, Mapping)
        and credits.get("hasCredits") is False and credits.get("unlimited") is False
        and _balance_zero(credits.get("balance")) is not False
    ):
        return False
    return snapshot.get("spendControlReached") is not True


SETTINGS_UPDATED = "thread/settings/updated"


def settings_notice_faults(
    record: Mapping[str, Any], *, model: str, provider: str,
) -> tuple[str, ...]:
    """A settings update must name the sealed model and provider, or it refuses.

    The pinned ``thread/settings/updated`` (experimental, ``common.rs:1865``)
    carries ``threadSettings.model`` and ``.modelProvider`` (``v2/thread.rs``).
    It is outside both refused namespaces, yet a different provider in it is a
    provider change inside the window the readings bracket, exactly the event
    the ``modelProvider/`` refusal exists for. So it is judged, not withheld: a
    missing, non-string or different value refuses. Only the method is named.
    """

    if record.get("method") != SETTINGS_UPDATED:
        return ()
    params = record.get("params")
    values = params.get("threadSettings") if isinstance(params, Mapping) else None
    if (
        isinstance(values, Mapping)
        and values.get("model") == model and type(values.get("model")) is str
        and values.get("modelProvider") == provider
        and type(values.get("modelProvider")) is str
    ):
        return ()
    return (ACCOUNT_NOTICE_FAULT.format(method=named_method(SETTINGS_UPDATED)),)


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
            f"account type {named_value(known.get(ACCOUNT_TYPE_KEY))} is not the "
            f"expected {expected.account_type!r}"
        )
    if result.get(PROVIDER_FLAG_KEY) is not True:
        faults.append(PROVIDER_OVERRIDE_FAULT)
    if known is not None and plan is None:
        # Unreachable against the pinned binary, whose wire type requires a plan
        # and surfaces absence as an error the first fault catches. Kept
        # fail-closed for a scripted or future reply that omits it.
        faults.append(NO_PLAN_FAULT)
    if plan is not None and not expected.accepts(plan):
        faults.append(
            f"account plan {named_value(plan)} is not the expected "
            f"{expected.plan_type!r}"
        )
    return tuple(faults)


def account_plan(reply: Any) -> str | None:
    """The plan literal of a reading, only when it is a string.

    Called after :func:`account_faults` cleared, so the value is one the
    binding's expected account accepts: an operator-declared literal.
    """

    plan = _reading(reply)[1]
    return plan if isinstance(plan, str) else None


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
        f"{name} changed from {named_value(old)} to {named_value(new)} across the turn"
        for name, old, new in zip(names, _reading(before), _reading(after), strict=True)
        if old != new
    )


# --- the spend readback ------------------------------------------------------

CODEX_LIMIT_ID = "codex"
BALANCE_CHARS = 32
SPEND_UNREADABLE_FAULT = (
    "the rate-limit readback is an error or carries no Codex bucket, so spend is unknown"
)
CREDITS_FAULT = "the rate-limit readback does not show zero purchased credits"
SPEND_FIELDS = (
    "has_credits", "unlimited", "balance_zero", "spend_control_reached", "rate_limit_reached",
)
USAGE_FIELDS = ("primary_used_percent", "secondary_used_percent")


@dataclass(frozen=True)
class SpendReading:
    """One Codex bucket's spend state: flags and bounded numbers only.

    ``plan`` is the wire value, compared and never published. Nothing else of
    the reply is read: ``accountId``, ``rateLimitUpsell``, reset credits, other
    buckets, ``limitName`` and ``individualLimit`` never leave the reply.
    """

    plan: Any
    has_credits: bool | None
    unlimited: bool | None
    balance_zero: bool | None
    spend_control_reached: bool | None
    rate_limit_reached: bool | None
    primary_used_percent: int | None
    secondary_used_percent: int | None


def _flag(value: Any) -> bool | None:
    return value if type(value) is bool else None


def _percent(window: Any) -> int | None:
    value = window.get("usedPercent") if isinstance(window, Mapping) else None
    return value if type(value) is int and _number(value) else None


def _balance_zero(balance: Any) -> bool | None:
    """``True`` only for a short decimal string equal to zero; absent is ``None``."""

    if balance is None:
        return None
    if not isinstance(balance, str) or len(balance) > BALANCE_CHARS:
        return False
    whole, dot, fraction = balance.removeprefix("-").partition(".")
    digits = whole + fraction
    if not (whole and digits.isascii() and digits.isdigit()) or (dot and not fraction):
        return False
    return set(digits) == {"0"}


def spend_reading(reply: Any) -> SpendReading | None:
    """The bucket whose own ``limitId`` is ``codex``, or ``None``: never a fallback.

    The pinned headline ``rateLimits`` is the ``codex`` snapshot only when one
    exists, and otherwise the first bucket returned; ``rateLimitsByLimitId``
    also keys an id-less snapshot as ``codex``
    (``account_processor.rs:1164-1181``). So only a map entry naming itself
    ``codex`` identifies the Codex bucket affirmatively.
    """

    result = _result_object(reply)
    buckets = result.get("rateLimitsByLimitId") if result is not None else None
    bucket = buckets.get(CODEX_LIMIT_ID) if isinstance(buckets, Mapping) else None
    if not isinstance(bucket, Mapping) or bucket.get("limitId") != CODEX_LIMIT_ID:
        return None
    credits = bucket.get("credits")
    credit = credits if isinstance(credits, Mapping) else {}
    reached = bucket.get("rateLimitReachedType", ...)
    return SpendReading(
        plan=bucket.get(PLAN_TYPE_KEY),
        has_credits=_flag(credit.get("hasCredits")),
        unlimited=_flag(credit.get("unlimited")),
        balance_zero=_balance_zero(credit.get("balance")),
        spend_control_reached=_flag(bucket.get("spendControlReached")),
        rate_limit_reached=None if reached is ... else reached is not None,
        primary_used_percent=_percent(bucket.get("primary")),
        secondary_used_percent=_percent(bucket.get("secondary")),
    )


def spend_faults(reading: SpendReading | None, expected: ExpectedAccount) -> tuple[str, ...]:
    """The owner's N5 bound, as code: no purchased credits, the expected plan.

    Absent credits are unknown, never zero, and refuse. A different owner bound
    is a new ``PROTOCOL_REVISION``, never a parameter (M8-N4-state-review.md,
    section 2).
    """

    if reading is None:
        return (SPEND_UNREADABLE_FAULT,)
    faults: list[str] = []
    if reading.plan is not None and not expected.accepts(reading.plan):
        faults.append(
            f"readback plan {named_value(reading.plan)} is not the expected "
            f"{expected.plan_type!r}"
        )
    if not (
        reading.has_credits is False and reading.unlimited is False
        and reading.balance_zero is not False
    ):
        faults.append(CREDITS_FAULT)
    return tuple(faults)


def spend_change_faults(before: SpendReading | None, after: SpendReading | None) -> tuple[str, ...]:
    """Overage state must equal its pre-turn baseline; usage is expected to move."""

    if before is None or after is None:
        return ()  # the per-reading fault already refused
    return tuple(
        f"readback {name.replace('_', ' ')} changed across the turn"
        for name in SPEND_FIELDS
        if getattr(before, name) != getattr(after, name)
    )


def rate_limit_of(before: SpendReading | None, after: SpendReading | None) -> RateLimitInfo | None:
    """The published readbacks: a fixed vocabulary of flags and bounded numbers.

    ``is_using_overage`` stays ``None``: the pin emits no such fact (I4).
    """

    detail = {
        f"{phase}.{name}": value
        for phase, reading in (("before", before), ("after", after)) if reading is not None
        for name in (*SPEND_FIELDS, *USAGE_FIELDS)
        if (value := getattr(reading, name)) is not None
    }
    return RateLimitInfo(is_using_overage=None, detail=detail) if detail else None


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
    record: Mapping[str, Any], *, thread_id: str | None, turn_id: str | None,
) -> Mapping[str, Any] | None:
    if thread_id is None or turn_id is None:
        # Defensive rather than live: from the adapter the transcript is provably
        # empty when the turn has no id, because both append sites require either
        # ``_collecting`` or ``_collect`` itself. This matters for a direct
        # ``observe_turn`` caller, which the protocol tests are, and that is where
        # its coverage lives.
        # An invocation that was never identified can have no terminal record.
        # Comparing against "" instead let a child assert a terminal turn for a
        # turn it had not named, which then published produced_output=True on a
        # refusal — a truthfulness field (I4). Unreachable is better than guarded.
        return None
    if record.get("method") != "turn/completed":
        return None
    params = record.get("params")
    if not isinstance(params, Mapping) or params.get("threadId") != thread_id:
        return None
    turn = params.get("turn")
    if not isinstance(turn, Mapping) or turn.get("id") != turn_id:
        return None
    return turn


def is_terminal_record(line: bytes, *, thread_id: str | None, turn_id: str | None) -> bool:
    """Whether this record terminates *this* invocation's turn.

    A cheap stop condition for the reader. ``observe_turn`` remains the
    authoritative fold; a record this rejects is still judged there.
    """

    try:
        record = parse_record(line)
    except RecordDamaged:
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
        name: item for name, item in fields.items()
        if type(item) is int and len(repr(item)) <= NUMBER_CHARS
    }
    return Usage(**numbers) if numbers else None


NUMBER_CHARS = 32
"""How long a wire number's own text may be.

``json.loads`` accepts integers up to 4,300 digits, and a bounded key count left
that magnitude unbounded: sixteen admitted keys once serialized to 68,918
characters. A number is only a fact if it is a number-sized fact."""

DETAIL_CHARS = 4096
"""``ExecutorError.detail`` joins itemized faults, so several may accumulate."""

FIRST_ERROR_CHARS = 512
"""``TransportDamage.first_error``. It had neither a bound nor a classifier."""


def _number(value: Any) -> bool:
    """A wire number small enough to publish, magnitude included."""

    return (
        (type(value) is bool or type(value) is int or type(value) is float)
        and len(repr(value)) <= NUMBER_CHARS
    )

TRANSCRIPT_CHARS = 64 * 1024
"""What ``raw_reply`` may carry. The launcher's 32 MiB stdout bound is the only
other ceiling and it arrives after the transcript is already in the outcome, so a
chatty session would otherwise put megabytes into a field that flows wherever
outcomes flow (I9: bounded surfaces)."""


def _bounded_transcript(kept: Sequence[str], unclassified: int) -> str:
    """Join the kept records, bounded, saying in-band what is missing and why.

    Two things withhold evidence here and both must be visible. Our own byte
    bound, and the evidence allowlist, which excludes records it cannot attest.
    Neither is transport damage: neither may become ``first_error`` or demote a
    clean success to partial. The markers carry that instead, so a reader holding
    a near-empty transcript knows a count of what was withheld and can go attest
    it rather than wondering whether the turn was silent.
    """

    transcript: list[str] = []
    size = 0
    dropped = 0
    for index, item in enumerate(kept):
        if size + len(item) > TRANSCRIPT_CHARS:
            dropped = len(kept) - index
            break
        transcript.append(item)
        size += len(item) + 1
    if dropped:
        transcript.append(
            f"[transcript bounded at {TRANSCRIPT_CHARS} characters; "
            f"{dropped} further records not shown]"
        )
    if unclassified:
        transcript.append(f"[{unclassified} records withheld from this turn]")
    return "\n".join(transcript)


def observe_turn(
    records: Sequence[bytes], *, thread_id: str | None, turn_id: str | None,
    transport_damage: str | None = None, excluded: int = 0,
) -> TurnObservation:
    """Fold one turn's records into a truthful observation.

    Damage is sticky: a later terminal record never promotes an earlier
    malformed one, and a second terminal record is contradictory rather than
    last-wins. Every field a record did not emit stays ``None`` (I4).

    A record carrying an ``id`` is a reply or a native request. This slice
    authorizes no callback, so such a record is damage and is dropped *before*
    ``raw`` exists — that is what keeps an ``account/read`` reply, and the email
    it carries, out of the public outcome.

    Everything else is admitted by an **allowlist**, not by failing a denylist,
    and that is this function's one rule: only attested turn evidence is kept.
    The reason the account namespace is refused at all is that the notification
    surface is unenumerated — and that same unenumerated-ness means an unknown
    method is an open assumption, so ``raw`` carries records this module
    classified as evidence rather than records it merely failed to reject. An
    id-less ``account/`` notification is excluded because it is not attested
    evidence, which needs no separate clause here: a redundant one would have no
    observable effect and so could not be falsified, which is exactly what
    invites a later reader to widen the allowlist and reopen the hole. The
    adapter refuses on such a record separately, and there the denylist acts
    alone and is falsifiable.

    Unparseable bytes contribute their count and their parse error and nothing
    else: a heuristic over content we could not classify is not a rule that can
    be true.
    """

    output: Any = None
    served_model: str | None = None
    usage: Usage | None = None
    terminal = False
    malformed = 0
    # Records the *caller* excluded before the turn was named. They are
    # counted here so one marker reports every withheld record, whichever
    # side of the boundary withheld it.
    unclassified = excluded
    first_error = transport_damage
    kept: list[str] = []
    for line in records:
        if not line.strip():
            continue
        try:
            record = parse_record(line)
        except RecordDamaged as exc:
            # Bytes we could not parse we cannot classify, so none of them is
            # published. The count and the damage report them truthfully (I4).
            malformed += 1
            first_error = first_error or f"a damaged native record: {exc}"
            continue
        if not isinstance(record, dict) or "id" in record or "method" not in record:
            malformed += 1
            first_error = first_error or "a turn transcript carries native notifications only"
            continue
        if not is_turn_evidence(record):
            # Not damage, so it is not counted as malformed and sets no error —
            # but never silent either: the transcript states this count.
            unclassified += 1
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
                first_error = first_error or (
                    f"the turn reported status {named_value(turn.get('status'))}"
                )
            output = turn.get("output")
            model = turn.get("model")
            served_model = model if isinstance(model, str) else None
            usage = _usage(turn.get("usage"))
    return TurnObservation(
        output=output, served_model=served_model, usage=usage,
        # The pinned Turn carries no rate limits (thread_data.rs:366); the
        # conversation adds its readbacks, the only spend source (N4 section 2).
        rate_limit=None,
        terminal=terminal, malformed_records=malformed, first_error=first_error,
        raw=_bounded_transcript(kept, unclassified),
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


def _bounded(text: str, limit: int) -> str:
    """Every public text surface is bounded by a named constant.

    Four fields of a published outcome carry text, and this slice has now found a
    leak or an unbounded field in three of them on three separate review passes —
    each time by looking at one site rather than at the set. The set is finite and
    enumerable, so the bound is applied by name here and asserted by enumeration
    in the tests, which fails when a *new* surface appears instead of after
    someone finds it.
    """

    return text if len(text) <= limit else text[:limit] + "[truncated]"


def bounded_detail(detail: str) -> str:
    """The public ``ExecutorError.detail`` bound, for the adapter's own faults."""

    return _bounded(detail, DETAIL_CHARS)


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
            malformed_records=observation.malformed_records,
            first_error=_bounded(damage, FIRST_ERROR_CHARS),
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
            detail=_bounded("; ".join(faults), DETAIL_CHARS),
            produced_output=observation.terminal,
        ),
    )
