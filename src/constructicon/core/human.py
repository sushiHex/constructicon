"""The canonical human-in-the-loop exchange contracts (M7, channel schema 1).

Defined once here in L0 so the control plane and the standard components cannot
drift apart: an approval reached through `runs_approve` and one reached through
`constructicon.std/human-approval` are the same exchange, typed by the same pair
of nominal contracts, or they are not the same exchange at all.

That matters because a request-bound approval writes an `ApprovalRecord` — a
governance fact — into a channel exchange. Nominal typing is what keeps it from
being written into an arbitrary approval-interaction conversation that merely
looks similar.

**A payload is caller-authored; authorship is not.** `Channel.ask` hands a
component the reply's payload and nothing else, deliberately: widening it would
put the whole message inside every component's reach. So anything a component is
allowed to *promise* about authority has to be written into the payload by the
executor, from authenticated and stored facts, rather than accepted from
whoever answered. Both payload laws below are built here, from those facts, and
called by the executor — never assembled by a caller.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError

from constructicon.core.address import RunId
from constructicon.core.channel import (
    ACK_CONSUMES,
    ChannelAckRecord,
    ChannelContract,
    ChannelInteraction,
    ChannelMessage,
    reply_message_id,
    validated_reply,
)
from constructicon.core.control import (
    CommandRecord,
    approval_id_for_command,
    channel_authority_holder,
    plan_records_a_refusal,
)
from constructicon.core.effect import ApprovalRecord
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import ActorId, Digest, JsonValue, canonical_json, json_value

ADVICE_REQUEST_CONTRACT = ChannelContract(
    type_id="constructicon.std/AdviceRequest",
    schema_hash="advice-request-1",
)
ADVICE_REPLY_CONTRACT = ChannelContract(
    type_id="constructicon.std/AdviceResponse",
    schema_hash="advice-response-1",
)
APPROVAL_REQUEST_CONTRACT = ChannelContract(
    type_id="constructicon.std/ApprovalRequest",
    schema_hash="approval-request-1",
)
APPROVAL_REPLY_CONTRACT = ChannelContract(
    type_id="constructicon.std/ApprovalDecision",
    schema_hash="approval-decision-1",
)


CANONICAL_EXCHANGES: tuple[tuple[ChannelContract, ChannelContract, ChannelInteraction], ...] = (
    (ADVICE_REQUEST_CONTRACT, ADVICE_REPLY_CONTRACT, "advice"),
    (APPROVAL_REQUEST_CONTRACT, APPROVAL_REPLY_CONTRACT, "approval"),
)


def canonical_exchange_fault(
    request: ChannelContract,
    reply: ChannelContract,
    interaction: ChannelInteraction,
) -> str | None:
    """Why this compiled exchange is not a coherent canonical human exchange.

    The contracts say what crosses; the endpoint says under whose authority. For
    these two exchanges those are not independent facts, and admission is the
    only place that sees both.

    An approval exchange sealed as advice is answered by `channels_reply`, which
    stamps only advice replies — so a human holding `constructicon:advise` alone
    would author the entire `ApprovalRecord`, actor and decision included, that
    the run then returns as a trusted governance fact. An advice exchange sealed
    as approval is the mirror: `channels_reply` refuses the interaction and
    `runs_approve` refuses the contracts, so the run parks with nothing able to
    answer it.

    Recognized by either half, because a pair naming one canonical contract and
    not its partner is not a canonical exchange half-dressed — it is a mismatch,
    and sealing it would be the same error one step further on.
    """

    for canonical_request, canonical_reply, required in CANONICAL_EXCHANGES:
        if request != canonical_request and reply != canonical_reply:
            continue
        if request != canonical_request or reply != canonical_reply:
            return (
                f"pairs {request.type_id!r} with {reply.type_id!r}; the canonical "
                f"{required} exchange pairs {canonical_request.type_id!r} with "
                f"{canonical_reply.type_id!r}"
            )
        if interaction != required:
            return (
                f"is the canonical {required} exchange, so its endpoint must seal "
                f"interaction={required!r}, not {interaction!r} — otherwise the "
                "authority that answers it is not the authority it describes"
            )
        return None
    if interaction == "approval":
        return (
            "seals interaction='approval', whose sole consumer is request-bound "
            "runs_approve; that operation requires the canonical approval exchange "
            f"{APPROVAL_REQUEST_CONTRACT.type_id!r} → "
            f"{APPROVAL_REPLY_CONTRACT.type_id!r}"
        )
    return None


class _HumanPayload(BaseModel):
    """A payload that crosses a channel and comes back from durable storage.

    Deliberately not ``strict``: these are validated out of stored JSON, where a
    payload arrives as plain Python objects rather than as the models that
    produced it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class ApprovalRequestPayload(_HumanPayload):
    """What a human is being asked to approve.

    ``subject`` is carried as plain JSON rather than a typed ``ProofSubject``
    because its only job here is to be compared, and comparison is a bytes law:
    ``1 == True`` and ``1 == 1.0`` are Python facts, not JSON ones, so a typed
    field invites the model equality that would accept a decision about a
    subject this request never pinned.
    """

    schema_version: Literal[1] = 1
    subject: JsonValue


class ApprovalDecisionPayload(_HumanPayload):
    """The one answer an approval request admits: the trusted record itself.

    Carrying the whole `ApprovalRecord` rather than a bare decision is what lets
    the standard component return a governance fact instead of a rumour. The
    record names its own approval id, subject, authenticated actor, run, and
    time, so a component can parse it, compare its subject against the one it
    asked about, and hand back something an auditor can follow — all without
    seeing anything but the payload.

    Approved and rejected are ordinary data inside it. Nothing branches on which
    it is; both are one decision, recorded and woken identically.
    """

    schema_version: Literal[1] = 1
    approval: ApprovalRecord


class AdviceReplyPayload(_HumanPayload):
    """One advisor's answer, carrying the authorship the executor observed.

    ``advice`` is what the human wrote. ``actor_id`` and ``message_id`` are not:
    they are stamped from the authenticated command and the derived reply
    identity. Without that, a component returning "who advised" would be
    repeating a claim the payload made about itself.

    ``message_id`` is carried rather than recomputed so the reply identity law
    stays in one place — a component that re-derived it would be a second
    implementation of it.
    """

    schema_version: Literal[1] = 1
    advice: JsonValue
    actor_id: ActorId
    message_id: Digest


class _ApprovalPlanModel(BaseModel):
    """One immutable human command schema shared by L0 provenance and L4 replay."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ChannelReplyProof(_ApprovalPlanModel):
    """The reply-shaped fact independently retained beside its evidence.

    A reply id deliberately excludes its caller-authored payload: one request
    admits one reply, whatever its answer says.  Consequently the stored
    message cannot prove its own payload.  This minimal proof is the independent
    copy both transports retain so a damaged reply never becomes successful
    advice merely because its other fields still derive from the request.
    """

    channel_id: str
    request_id: Digest
    interaction: ChannelInteraction
    actor_id: ActorId
    reply_id: Digest
    reply_port: str
    payload: JsonValue
    run_id: RunId


class ChannelReplyPlan(ChannelReplyProof):
    """A durable channels_reply plan plus its process-local wake hint."""

    kind: Literal["channel_reply"] = "channel_reply"
    parked_event_seq: int = Field(ge=0)


class StoredChannelReplyPlan(_ApprovalPlanModel):
    """The exact typed envelope persisted for one current channel reply."""

    schema_version: Literal[1] = 1
    plan: ChannelReplyPlan


class ChannelAckPlan(_ApprovalPlanModel):
    """One explicit delivery fact, sealed entirely by its request and actor."""

    kind: Literal["channel_ack"] = "channel_ack"
    channel_id: str
    message_id: Digest
    interaction: ChannelInteraction
    actor_id: ActorId


class StoredChannelAckPlan(_ApprovalPlanModel):
    """The exact typed envelope persisted for one current acknowledgement."""

    schema_version: Literal[1] = 1
    plan: ChannelAckPlan


class ApprovalPlan(_ApprovalPlanModel):
    """A standalone approval decision with no channel exchange."""

    kind: Literal["approval"] = "approval"
    approval: ApprovalRecord


class ChannelApprovalPlan(_ApprovalPlanModel):
    """One approval decision and the channel exchange it atomically authors."""

    kind: Literal["channel_approval"] = "channel_approval"
    approval: ApprovalRecord
    channel_id: str
    request_id: Digest
    reply_id: Digest
    reply_port: str
    payload: JsonValue
    ack_actor_id: ActorId
    run_id: RunId
    parked_event_seq: int = Field(ge=0)


ApprovalCommandPlan = Annotated[
    ApprovalPlan | ChannelApprovalPlan,
    Field(discriminator="kind"),
]


class StoredApprovalPlan(_ApprovalPlanModel):
    """The current typed envelope for either approval plan family."""

    schema_version: Literal[1] = 1
    plan: ApprovalCommandPlan


class _LegacyApprovalPlan(_ApprovalPlanModel):
    """The exact pre-schema-1 standalone shape retained for durable history."""

    approval: ApprovalRecord


HumanCommandPlan = ApprovalPlan | ChannelApprovalPlan | ChannelReplyPlan | ChannelAckPlan


def decoded_human_command_plan(command: CommandRecord) -> HumanCommandPlan | None:
    """Decode the exact typed plan that independently names a human domain fact.

    This deliberately stops before consulting the mutable domain tables.  It is
    therefore suitable for selectors that must find a relocated fact from the
    immutable plan first; the family-specific projector still proves the fact
    against its request and command before anyone acts on it.

    A command that refused planned no mutation, so it names no fact and this
    returns ``None`` — the same answer as an operation outside the family, and
    for the same reason.
    """

    raw = command.plan
    if command.operation not in {"runs_approve", "channels_reply", "channels_ack"}:
        return None
    if plan_records_a_refusal(raw):
        return None
    if not isinstance(raw, dict):
        raise JournalDamaged(f"human command {command.command_id!r} has no typed plan")
    try:
        if command.operation == "runs_approve":
            if "schema_version" in raw:
                stored_approval = StoredApprovalPlan.model_validate_json(canonical_json(raw))
                rendered = stored_approval.model_dump(mode="json")
                plan: HumanCommandPlan = stored_approval.plan
            else:
                legacy = _LegacyApprovalPlan.model_validate_json(canonical_json(raw))
                rendered = legacy.model_dump(mode="json")
                plan = ApprovalPlan(approval=legacy.approval)
        elif command.operation == "channels_reply":
            stored_reply = StoredChannelReplyPlan.model_validate_json(canonical_json(raw))
            rendered = stored_reply.model_dump(mode="json")
            plan = stored_reply.plan
        else:
            stored_ack = StoredChannelAckPlan.model_validate_json(canonical_json(raw))
            rendered = stored_ack.model_dump(mode="json")
            plan = stored_ack.plan
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(
            f"human command {command.command_id!r} has an invalid typed plan"
        ) from exc
    if canonical_json(raw) != canonical_json(json_value(rendered)):
        raise JournalDamaged(
            f"human command {command.command_id!r} has a non-lossless typed plan"
        )
    return plan


def channel_reply_proof(
    request: ChannelMessage,
    reply: ChannelMessage,
) -> ChannelReplyProof:
    """Derive the independent proof one exact reply must agree with."""

    validated_reply(request, reply)
    if request.reply_port is None or reply.sender_actor_id is None:
        raise JournalDamaged(
            f"channel reply {reply.message_id} names an incomplete request or sender"
        )
    return ChannelReplyProof(
        channel_id=request.channel_id,
        request_id=request.message_id,
        interaction=request.interaction,
        actor_id=reply.sender_actor_id,
        reply_id=reply.message_id,
        reply_port=request.reply_port,
        payload=json_value(reply.envelope.payload),
        run_id=request.envelope.run_id,
    )


def validated_channel_reply_proof(
    proof: ChannelReplyProof,
    request: ChannelMessage,
    reply: ChannelMessage,
) -> ChannelReplyProof:
    """Prove that stored reply evidence still matches its independent copy."""

    expected = channel_reply_proof(request, reply)
    actual = ChannelReplyProof.model_validate(
        proof.model_dump(mode="json", include=set(ChannelReplyProof.model_fields))
    )
    if canonical_json(json_value(actual.model_dump(mode="json"))) != canonical_json(
        json_value(expected.model_dump(mode="json"))
    ):
        raise JournalDamaged(
            f"channel reply {reply.message_id} contradicts its independently stored proof"
        )
    return proof


def validated_channel_reply_plan(
    command: CommandRecord,
    plan: ChannelReplyPlan,
    request: ChannelMessage,
) -> ChannelReplyPlan:
    """Bind a current reply plan to its command and the sealed request."""

    raw_request = command.request
    if (
        command.operation != "channels_reply"
        or request.interaction != "advice"
        or not channel_authority_holder(request, command.actor)
        or not isinstance(raw_request, dict)
        or set(raw_request) != {"message_id", "payload"}
        or raw_request["message_id"] != str(request.message_id)
    ):
        raise JournalDamaged(
            f"channel reply plan for {request.message_id} contradicts its command"
        )
    if request.reply_port is None:
        raise JournalDamaged(f"channel request {request.message_id} pins no reply port")
    expected_payload = sealed_reply_payload(
        request,
        answer=raw_request["payload"],
        actor_id=command.actor.actor_id,
        reply_id=reply_message_id(
            request_id=request.message_id,
            reply_port=request.reply_port,
        ),
    )
    expected = ChannelReplyProof(
        channel_id=request.channel_id,
        request_id=request.message_id,
        interaction=request.interaction,
        actor_id=command.actor.actor_id,
        reply_id=reply_message_id(
            request_id=request.message_id,
            reply_port=request.reply_port,
        ),
        reply_port=request.reply_port,
        payload=json_value(expected_payload),
        run_id=request.envelope.run_id,
    )
    actual = ChannelReplyProof.model_validate(
        plan.model_dump(mode="json", include=set(ChannelReplyProof.model_fields))
    )
    if canonical_json(json_value(actual.model_dump(mode="json"))) != canonical_json(
        json_value(expected.model_dump(mode="json"))
    ):
        raise JournalDamaged(
            f"channel reply plan for {request.message_id} contradicts its sealed request"
        )
    return plan


def validated_channel_command_reply(
    command: CommandRecord,
    request: ChannelMessage,
    reply: ChannelMessage,
) -> ChannelReplyPlan:
    """Project one current durable reply only through its command plan."""

    raw = command.plan
    if command.state == "rejected":
        raise JournalDamaged(
            f"channel reply {reply.message_id} belongs to a rejected command"
        )
    if not isinstance(raw, dict):
        raise JournalDamaged(
            f"channel reply {reply.message_id} belongs to a planless command"
        )
    try:
        stored = StoredChannelReplyPlan.model_validate_json(canonical_json(raw))
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(
            f"channel reply {reply.message_id} belongs to an invalid reply plan"
        ) from exc
    if canonical_json(raw) != canonical_json(
        json_value(stored.model_dump(mode="json"))
    ):
        raise JournalDamaged(
            f"channel reply {reply.message_id} belongs to a non-lossless reply plan"
        )
    plan = validated_channel_reply_plan(command, stored.plan, request)
    validated_channel_reply_proof(plan, request, reply)
    return plan


def validated_new_channel_command_reply(
    command: CommandRecord,
    request: ChannelMessage,
    reply: ChannelMessage,
) -> ChannelReplyPlan:
    """Prove that a first write comes from a nonterminal reply command.

    Exact retries may legitimately observe a command that completed after the
    reply committed. A missing reply cannot: terminal success is evidence that
    its domain fact already exists, never authority to manufacture it later.
    """

    if command.state != "prepared":
        raise JournalDamaged(
            f"new channel reply {reply.message_id} belongs to a terminal command"
        )
    return validated_channel_command_reply(command, request, reply)


def validated_channel_ack_plan(
    command: CommandRecord,
    plan: ChannelAckPlan,
    request: ChannelMessage,
) -> ChannelAckPlan:
    """Bind an explicit delivery plan to its command and sealed request."""

    raw_request = command.request
    expected = ChannelAckPlan(
        channel_id=request.channel_id,
        message_id=request.message_id,
        interaction=request.interaction,
        actor_id=command.actor.actor_id,
    )
    if (
        command.operation != "channels_ack"
        or request.kind != "request"
        or request.interaction not in ACK_CONSUMES
        or not channel_authority_holder(request, command.actor)
        or not isinstance(raw_request, dict)
        or set(raw_request) != {"message_id"}
        or raw_request["message_id"] != str(request.message_id)
        or canonical_json(json_value(plan.model_dump(mode="json")))
        != canonical_json(json_value(expected.model_dump(mode="json")))
    ):
        raise JournalDamaged(
            f"channel acknowledgement plan for {request.message_id} "
            "contradicts its command or sealed request"
        )
    return plan


def validated_channel_command_ack(
    command: CommandRecord,
    request: ChannelMessage,
) -> ChannelAckPlan:
    """Project a current explicit acknowledgement through its exact plan."""

    raw = command.plan
    if command.state == "rejected":
        raise JournalDamaged(
            f"channel acknowledgement for {request.message_id} belongs to a rejected command"
        )
    if not isinstance(raw, dict):
        raise JournalDamaged(
            f"channel acknowledgement for {request.message_id} belongs to a planless command"
        )
    try:
        stored = StoredChannelAckPlan.model_validate_json(canonical_json(raw))
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(
            f"channel acknowledgement for {request.message_id} belongs to an invalid plan"
        ) from exc
    if canonical_json(raw) != canonical_json(
        json_value(stored.model_dump(mode="json"))
    ):
        raise JournalDamaged(
            f"channel acknowledgement for {request.message_id} belongs to a lossy plan"
        )
    return validated_channel_ack_plan(command, stored.plan, request)


def validated_channel_ack_provenance(
    command: CommandRecord,
    acknowledgement: ChannelAckRecord,
    request: ChannelMessage,
    *,
    reply: ChannelMessage | None,
    reply_command_id: str | None,
    approval: ApprovalRecord | None,
) -> ChannelAckRecord:
    """Bind one command-backed delivery fact to the exchange that produced it.

    Acknowledgement rows are shared by three command families.  Merely finding
    a plan beside their command proves none of them: an explicit observation
    owns an exact ``ChannelAckPlan``; a reply implies its sender's observation;
    and a request-bound approval authors approval, reply, and acknowledgement
    as one exchange.  This dispatcher is the single semantic provenance law for
    all three, used equally for current facts and command-backed migrated facts.
    """

    ack = acknowledgement.ack
    if (
        acknowledgement.command_id != command.command_id
        or ack.message_id != request.message_id
        or ack.actor_id != command.actor.actor_id
    ):
        raise JournalDamaged(
            f"channel acknowledgement for {ack.message_id} contradicts its command"
        )
    if command.operation == "channels_ack":
        validated_channel_command_ack(command, request)
        return acknowledgement
    if reply is None or reply_command_id != command.command_id:
        raise JournalDamaged(
            f"channel acknowledgement for {ack.message_id} has no reply written "
            "by its command"
        )
    if acknowledgement.provenance_version == 1 and ack.acked_at != reply.envelope.created_at:
        raise JournalDamaged(
            f"channel acknowledgement for {ack.message_id} contradicts its "
            "command's atomic observation"
        )
    if command.operation == "channels_reply":
        validated_channel_command_reply(command, request, reply)
        return acknowledgement
    if command.operation == "runs_approve":
        if approval is None:
            raise JournalDamaged(
                f"approval reply {reply.message_id} exists without the approval record "
                "written in its own transaction"
            )
        validated_channel_approval_exchange(command, approval, request, reply)
        return acknowledgement
    raise JournalDamaged(
        f"channel acknowledgement for {ack.message_id} has no lawful command provenance"
    )


def approval_decision_payload(approval: ApprovalRecord) -> JsonValue:
    """The reply an approval request admits, derived from the stored record.

    Derived rather than passed, so the answer a run reads and the governance
    fact an auditor reads can never disagree about what was decided, by whom.
    """

    return cast(
        JsonValue,
        ApprovalDecisionPayload(approval=approval).model_dump(mode="json"),
    )


def validated_approval_identity(
    command_id: str,
    approval: ApprovalRecord,
) -> ApprovalRecord:
    """Prove that one approval has the identity minted by its command.

    The subject is part of the identity, so internally consistent row fields
    still are not a governance fact unless the durable command minted that
    exact approval id.
    """

    expected = approval_id_for_command(
        command_id,
        json_value(approval.subject.model_dump(mode="json")),
    )
    if approval.approval_id != expected:
        raise JournalDamaged(
            f"approval {approval.approval_id!r} was not minted by command {command_id!r}"
        )
    return approval


def validated_command_approval(
    command: CommandRecord,
    approval: ApprovalRecord,
) -> ApprovalRecord:
    """Return the governance fact only after its command and plan prove it."""

    validated_command_approval_plan(command, approval)
    return approval


def validated_command_approval_plan(
    command: CommandRecord,
    approval: ApprovalRecord,
) -> ApprovalPlan | ChannelApprovalPlan:
    """Bind one governance fact to the lawful command that authored it.

    The approval id binds the command and subject, but it does not bind the
    command's authenticated actor, operation, request, or lifecycle.  Those
    are equally part of the governance fact: a row is projectable only when a
    planned ``runs_approve`` command asked for this exact decision and either
    still owns its post-mutation crash seam or committed it.
    """

    validated_approval_identity(command.command_id, approval)
    if command.operation != "runs_approve":
        raise JournalDamaged(
            f"approval {approval.approval_id!r} belongs to a command other than runs_approve"
        )
    if command.actor != approval.actor:
        raise JournalDamaged(
            f"approval {approval.approval_id!r} actor contradicts its authenticated command"
        )
    request = command.request
    base_keys = {"run_id", "subject", "decision", "reason"}
    if not isinstance(request, dict) or set(request) not in (
        base_keys,
        base_keys | {"request_message_id"},
    ):
        raise JournalDamaged(
            f"approval {approval.approval_id!r} contradicts its canonical command request"
        )
    if (
        request["run_id"] != str(approval.run_id)
        or canonical_json(json_value(request["subject"]))
        != canonical_json(json_value(approval.subject.model_dump(mode="json")))
        or request["decision"] != approval.decision
        or request["reason"] != approval.reason
    ):
        raise JournalDamaged(
            f"approval {approval.approval_id!r} contradicts its canonical command request"
        )
    plan = _approval_plan_for(command, approval)
    if "request_message_id" not in request:
        if not isinstance(plan, ApprovalPlan):
            raise JournalDamaged(
                f"approval {approval.approval_id!r} belongs to a request-bound plan "
                "but its command is standalone"
            )
    else:
        request_id = request["request_message_id"]
        if (
            not isinstance(request_id, str)
            or not isinstance(plan, ChannelApprovalPlan)
            or request_id != str(plan.request_id)
            or plan.run_id != approval.run_id
            or plan.ack_actor_id != approval.actor.actor_id
            or plan.reply_id
            != reply_message_id(request_id=plan.request_id, reply_port=plan.reply_port)
            or canonical_json(json_value(plan.payload))
            != canonical_json(json_value(approval_decision_payload(approval)))
        ):
            raise JournalDamaged(
                f"approval {approval.approval_id!r} contradicts its request-bound plan"
            )
    if command.state == "rejected":
        raise JournalDamaged(
            f"approval {approval.approval_id!r} belongs to a rejected command"
        )
    return plan


def _approval_plan_for(
    command: CommandRecord,
    approval: ApprovalRecord,
) -> ApprovalPlan | ChannelApprovalPlan:
    """Decode the exact immutable plan that is evidence for one approval.

    Current commands use the schema-1 envelope. Historical commands may use
    only the old standalone ``{"approval": ...}`` object; that compatibility
    is intentionally narrow and can never be upgraded into a channel-bound
    decision by adding fields.
    """

    raw = command.plan
    if not isinstance(raw, dict):
        raise JournalDamaged(
            f"approval {approval.approval_id!r} belongs to a planless command"
        )
    try:
        if "schema_version" in raw:
            stored = StoredApprovalPlan.model_validate_json(canonical_json(raw))
            rendered = stored.model_dump(mode="json")
            plan: ApprovalPlan | ChannelApprovalPlan = stored.plan
        else:
            legacy = _LegacyApprovalPlan.model_validate_json(canonical_json(raw))
            rendered = legacy.model_dump(mode="json")
            plan = ApprovalPlan(approval=legacy.approval)
    except (TypeError, ValueError, ValidationError) as exc:
        raise JournalDamaged(
            f"approval {approval.approval_id!r} belongs to an invalid approval plan"
        ) from exc
    if canonical_json(raw) != canonical_json(json_value(rendered)):
        raise JournalDamaged(
            f"approval {approval.approval_id!r} belongs to a non-lossless approval plan"
        )
    if canonical_json(json_value(plan.approval.model_dump(mode="json"))) != canonical_json(
        json_value(approval.model_dump(mode="json"))
    ):
        raise JournalDamaged(
            f"approval {approval.approval_id!r} contradicts its immutable command plan"
        )
    return plan


def validated_standalone_command_approval(
    command: CommandRecord,
    approval: ApprovalRecord,
) -> ApprovalRecord:
    """Prove that the standalone approval writer owns a standalone plan."""

    plan = validated_command_approval_plan(command, approval)
    if not isinstance(plan, ApprovalPlan):
        raise JournalDamaged(
            f"approval {approval.approval_id!r} is request-bound and must be "
            "written as one channel exchange"
        )
    return approval


def validated_channel_command_approval(
    command: CommandRecord,
    approval: ApprovalRecord,
    request: ChannelMessage,
) -> ChannelApprovalPlan:
    """Decode a request-bound command plan and bind it to its sealed request."""

    plan = validated_command_approval_plan(command, approval)
    if not isinstance(plan, ChannelApprovalPlan):
        raise JournalDamaged(
            f"approval {approval.approval_id!r} has no request-bound approval plan"
        )
    return validated_channel_approval_plan(plan, approval, request)


def validated_channel_approval_plan(
    plan: ChannelApprovalPlan,
    approval: ApprovalRecord,
    request: ChannelMessage,
) -> ChannelApprovalPlan:
    """Bind one typed approval plan to the actual sealed request it claims."""

    pinned = _validated_approval_request(request)
    if (
        canonical_json(json_value(plan.approval.model_dump(mode="json")))
        != canonical_json(json_value(approval.model_dump(mode="json")))
        or plan.channel_id != request.channel_id
        or plan.request_id != request.message_id
        or plan.reply_port != request.reply_port
        or plan.reply_id
        != reply_message_id(request_id=plan.request_id, reply_port=plan.reply_port)
        or plan.run_id != request.envelope.run_id
        or plan.ack_actor_id != approval.actor.actor_id
        or canonical_json(json_value(plan.payload))
        != canonical_json(json_value(approval_decision_payload(approval)))
        or not channel_authority_holder(request, approval.actor)
        or canonical_json(json_value(pinned.subject))
        != canonical_json(json_value(approval.subject.model_dump(mode="json")))
    ):
        raise JournalDamaged(
            f"approval {approval.approval_id!r} plan contradicts its sealed request"
        )
    return plan


def validated_channel_approval_exchange(
    command: CommandRecord,
    approval: ApprovalRecord,
    request: ChannelMessage,
    reply: ChannelMessage,
) -> ChannelApprovalPlan:
    """Prove one command plan, approval, sealed request, and reply are one fact."""

    plan = validated_channel_command_approval(command, approval, request)
    carried = validated_approval_reply(request, reply)
    if (
        canonical_json(json_value(carried.model_dump(mode="json")))
        != canonical_json(json_value(approval.model_dump(mode="json")))
        or plan.reply_id != reply.message_id
        or plan.ack_actor_id != reply.sender_actor_id
        or canonical_json(json_value(plan.payload))
        != canonical_json(json_value(reply.envelope.payload))
    ):
        raise JournalDamaged(
            f"approval {approval.approval_id!r} plan contradicts its channel reply"
        )
    return plan


def _validated_approval_request(request: ChannelMessage) -> ApprovalRequestPayload:
    if (
        request.kind != "request"
        or request.interaction != "approval"
        or request.contract != APPROVAL_REQUEST_CONTRACT
        or request.reply_contract != APPROVAL_REPLY_CONTRACT
        or request.reply_port is None
    ):
        raise JournalDamaged(
            f"channel request {request.message_id} is not a canonical human-approval request"
        )
    try:
        return ApprovalRequestPayload.model_validate(request.envelope.payload)
    except ValidationError as exc:
        raise JournalDamaged(
            f"channel request {request.message_id} carries no approval subject"
        ) from exc


def validated_approval_reply(
    request: ChannelMessage,
    reply: ChannelMessage,
) -> ApprovalRecord:
    """The governance record one canonical approval exchange proves.

    A reply pointer and a payload that happens to resemble an approval are not
    that proof.  The sealed request, authenticated reply sender, carried record,
    run, and subject must describe one decision.  Persistence separately checks
    that this exact record exists in the approval ledger under the reply writer.
    """

    validated_reply(request, reply)
    pinned = _validated_approval_request(request)
    try:
        carried = ApprovalDecisionPayload.model_validate(reply.envelope.payload).approval
    except ValidationError as exc:
        raise JournalDamaged(
            f"approval reply {reply.message_id} carries no decision record"
        ) from exc
    if (
        carried.run_id != request.envelope.run_id
        or carried.actor.actor_id != reply.sender_actor_id
        or canonical_json(json_value(carried.subject.model_dump(mode="json")))
        != canonical_json(json_value(pinned.subject))
    ):
        raise JournalDamaged(
            f"approval {carried.approval_id} decides a run, actor, or subject "
            "its own exchange does not"
        )
    return carried


def claims_approval_exchange(request: ChannelMessage) -> bool:
    """Whether any sealed request field claims approval semantics."""

    return (
        request.interaction == "approval"
        or request.contract == APPROVAL_REQUEST_CONTRACT
        or request.reply_contract == APPROVAL_REPLY_CONTRACT
    )


def approval_record_for_reply(
    request: ChannelMessage,
    reply: ChannelMessage,
    *,
    current_era: bool = True,
    stored_approval: ApprovalRecord | None = None,
) -> ApprovalRecord | None:
    """Validate canonical human routing and return its approval, when any.

    ``current_era`` is false for a reply written before schema 7 began
    recording reply provenance. For a current reply the request alone settles
    it: a request that claims approval semantics must be answered by a decision,
    and anything else is damage.

    A legacy reply cannot be held to that, because the request cannot speak for
    an era it outlived. That era sealed any contract pair under any interaction
    and, for most of its life, had no approval ledger at all, so demanding a
    decision of every approval-interaction reply it left behind does not find
    damage — it invents it, and on the open path, where ADR 0016 forbids
    healing, inventing it once makes the store unopenable forever.

    What settles a legacy reply is therefore ``stored_approval``: the decision
    the ledger actually holds for its writer. That is a durable fact and a
    sealed one. The reply's own payload deliberately does not get a vote — a
    shape test is adjustable by whoever wrote the bytes and moves whenever the
    model that reads them moves, so it would classify the same history
    differently on two releases. A legacy reply with a decision behind it is
    held to the whole approval law; one without is an ordinary reply, and still
    has to be the one its request admits.
    """

    if request.kind != "request" or request.reply_contract is None:
        raise JournalDamaged(
            f"channel reply {reply.message_id} does not name a complete request exchange"
        )
    if not current_era and stored_approval is None:
        validated_reply(request, reply)
        return None
    mismatch = canonical_exchange_fault(
        request.contract,
        request.reply_contract,
        request.interaction,
    )
    if mismatch is not None:
        raise JournalDamaged(
            f"channel reply {reply.message_id} answers an incoherent exchange: {mismatch}"
        )
    if not claims_approval_exchange(request):
        validated_reply(request, reply)
        return None
    return validated_approval_reply(request, reply)


def sealed_reply_payload(
    request: ChannelMessage,
    *,
    answer: JsonValue,
    actor_id: ActorId,
    reply_id: Digest,
) -> JsonValue:
    """The payload a reply stores, as the request's sealed contract requires it.

    Only the canonical advice exchange is stamped, because only its reply
    contract promises authorship. Every other advice channel stores exactly what
    its answerer wrote: the request's sealed reply contract decides what a reply
    is, here as everywhere else, rather than the executor deciding for it.
    """

    if request.reply_contract != ADVICE_REPLY_CONTRACT:
        return answer
    return cast(
        JsonValue,
        AdviceReplyPayload(
            advice=answer,
            actor_id=actor_id,
            message_id=reply_id,
        ).model_dump(mode="json"),
    )


class AdviceRequestPayload(RootModel[JsonValue]):
    """Caller-authored JSON: the question exactly as the workflow wrote it.

    It is all the advisor sees, so it has to say what the answer must contain.
    Named here only so the shape ``describe()`` publishes is the truth: any
    JSON value.
    """


CONTRACT_SCHEMAS: Mapping[ChannelContract, type[BaseModel]] = MappingProxyType(
    {
        ADVICE_REQUEST_CONTRACT: AdviceRequestPayload,
        ADVICE_REPLY_CONTRACT: AdviceReplyPayload,
        APPROVAL_REQUEST_CONTRACT: ApprovalRequestPayload,
        APPROVAL_REPLY_CONTRACT: ApprovalDecisionPayload,
    }
)
"""Each named contract revision and the model whose shape it names, for ``describe()``.

A named revision is not the digest of a schema, so the registry will not
embed one on a port; the shape is published from here instead.
"""
