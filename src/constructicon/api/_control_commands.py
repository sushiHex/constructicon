"""Private durable command executor and typed command law (M6.2).

MCP is one adapter. Every mutation follows the same law:
Authorize -> Claim -> Plan -> Apply once -> Record -> replay after loss.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal, TypeVar, cast

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    ValidationError,
    model_serializer,
)

from constructicon.api.cursor import CursorCodec
from constructicon.api.detail import (
    DetailAddress,
    DetailResolver,
    channel_scope_refusal,
    governed_delivery,
)
from constructicon.api.run_host import LaunchDisposition, RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.admission import AdmissionRejected
from constructicon.core.channel import (
    ACK_CONSUMES,
    APPROVE_CONSUMES,
    REPLY_CONSUMES,
    ChannelAckConflict,
    ChannelInteraction,
    ChannelMessage,
    ChannelMessageWriter,
    ChannelReplyConflict,
    reply_message_id,
)
from constructicon.core.component import ComponentDef, PromotionRecord
from constructicon.core.control import (
    ADMIN_SCOPE,
    APPROVE_SCOPE,
    INTERACTION_SCOPES,
    OPERATE_SCOPE,
    PROMOTE_SCOPE,
    RESUMABLE_RUN_STATUSES,
    ApprovalCommandResult,
    AuthenticatedActor,
    CancellationResult,
    ChannelAckResult,
    ChannelReplyResult,
    CommandClaim,
    CommandMeta,
    CommandRecord,
    ControlCode,
    ControlPlaneStore,
    ControlRejected,
    LegacyResumeCommandPlan,
    PromotionCommandResult,
    RegistrationCommandResult,
    ResolutionLock,
    ResolutionPin,
    ResumeCommandPlan,
    RunCreationPlan,
    RunOrigin,
    RunSubmission,
    SourceRunLock,
    approval_id_for_command,
    channel_authority_holder,
    command_request_hash,
    resume_attempt_kind,
    resume_plan_requires_historical_evidence,
    run_id_for_command,
    scope_refusal,
    validate_idempotency_key,
    validated_new_run_creation_plan,
    validated_resume_command_plan,
    validated_resume_status_at_fence,
    validated_run_creation_command,
)
from constructicon.core.effect import (
    ApprovalRecord,
    AttestationDraft,
    ComponentProofSubject,
    ProofSubject,
)
from constructicon.core.envelope import utc_now
from constructicon.core.errors import AdmissionError, ContractViolation, JournalDamaged
from constructicon.core.graph import Graph
from constructicon.core.human import (
    APPROVAL_REPLY_CONTRACT,
    APPROVAL_REQUEST_CONTRACT,
    ApprovalPlan,
    ApprovalRequestPayload,
    ChannelAckPlan,
    ChannelApprovalPlan,
    ChannelReplyPlan,
    approval_decision_payload,
    canonical_exchange_fault,
    sealed_reply_payload,
    validated_approval_reply,
    validated_channel_ack_plan,
    validated_channel_approval_exchange,
    validated_channel_approval_plan,
    validated_channel_command_reply,
    validated_channel_reply_plan,
)
from constructicon.core.identity import Digest, JsonValue, canonical_json, digest, json_value
from constructicon.core.journal import Journal
from constructicon.core.manifest import ExecutionManifest
from constructicon.core.registry import (
    RegistryStore,
    StoredVersion,
)
from constructicon.core.run import (
    TERMINAL_EVENT_STATUSES,
    TERMINAL_STATUS_EVENTS,
    AttemptCause,
    RunStatus,
)
from constructicon.runtime.registry import (
    ComponentRegistry,
    PlannedRegistration,
    RegistryError,
)
from constructicon.sdk.types import DefinitionBundle

COMMAND_TTL_S = 30.0

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
_NEW_RUN_LAUNCH_STATUSES = frozenset({RunStatus.PENDING, RunStatus.RUNNING})

T = TypeVar("T", bound=BaseModel)


def _same_json_fact(left: object, right: object) -> bool:
    """Compare durable facts by their wire bytes, never Python scalar equality."""

    try:
        return canonical_json(left) == canonical_json(right)
    except (TypeError, ValueError) as exc:
        raise JournalDamaged("durable JSON fact is not canonical") from exc


class _PlanModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class _ExactRejectionPlan(_PlanModel):
    """A domain plan whose post-plan refusal has independent canonical bytes.

    ``None`` denotes a plan written before that law existed.  Omitting the
    nullable marker from those model bytes keeps their historical durable
    identity readable without pretending they carry the stronger proof.
    """

    terminal_rejection_policy: Literal["exact-v1"] | None = None

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, Any]:
        data = handler(self)
        if not isinstance(data, dict):
            raise TypeError("command plan serializer expected an object")
        if self.terminal_rejection_policy is None:
            data.pop("terminal_rejection_policy", None)
        return data


class _CancelPlan(_PlanModel):
    kind: Literal["cancel"] = "cancel"
    run_id: RunId
    observed_status: RunStatus
    outcome: Literal["cancel_requested", "already_terminal"]
    response_status: RunStatus
    observed_event_seq: int | None = Field(default=None, ge=1)

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, Any]:
        data = handler(self)
        if not isinstance(data, dict):
            raise TypeError("cancel plan serializer expected an object")
        if self.observed_event_seq is None:
            data.pop("observed_event_seq", None)
        return data


class _RegistrationPlan(_PlanModel):
    kind: Literal["registration"] = "registration"
    definition: ComponentDef
    content_hash: Digest
    candidate_timestamp: AwareDatetime
    row_origin: Literal["existing", "canonical_new"]


class _InitialPromotionPlan(_ExactRejectionPlan):
    kind: Literal["initial_promotion"] = "initial_promotion"
    component: str
    baseline: None = None
    target: Digest
    draft: AttestationDraft
    attestation_id: str


class _PromotionPlan(_ExactRejectionPlan):
    kind: Literal["promotion"] = "promotion"
    component: str
    baseline: Digest | None
    target: Digest
    attestation_id: str


class _RollbackPlan(_ExactRejectionPlan):
    kind: Literal["rollback"] = "rollback"
    component: str
    baseline: Digest
    target: Digest
    draft: AttestationDraft
    attestation_id: str


class _AdmissionRejectPlan(_PlanModel):
    kind: Literal["admission_reject"] = "admission_reject"
    command_id: str
    operation: Literal["runs_start"] = "runs_start"
    request_hash: Digest
    response: AdmissionRejected


class _ControlRejectPlan(_PlanModel):
    kind: Literal["control_reject"] = "control_reject"
    command_id: str
    operation: str
    request_hash: Digest
    response: ControlRejected


_RegistryPromotionPlan = _InitialPromotionPlan | _PromotionPlan | _RollbackPlan


def _canonical_domain_rejection(
    plan: ResumeCommandPlan | _RegistryPromotionPlan,
) -> ControlRejected:
    """Rebuild the one post-plan refusal from immutable planned facts."""

    if isinstance(plan, ResumeCommandPlan):
        return ControlRejected.one_fault(
            ControlCode.RUN_NOT_RESUMABLE,
            f"resume intent for {plan.run_id!r} lost its exact attempt fence",
            "submit a new resume command after refreshing run status",
            {
                "reason": "attempt_superseded",
                "baseline_event_seq": plan.baseline_event_seq,
            },
        )
    baseline = str(plan.baseline) if plan.baseline is not None else None
    return ControlRejected.one_fault(
        ControlCode.REGISTRY_STABLE_MOVED,
        f"stable changed before the planned edge for {plan.component!r} could commit",
        "inspect the current stable version and submit a fresh command key",
        {
            "component": plan.component,
            "planned_from": baseline,
            "planned_to": str(plan.target),
        },
    )


def _unfenced_resume_rejection(plan: LegacyResumeCommandPlan) -> ControlRejected:
    """Rebuild the exact terminal refusal owed by one unfenced legacy plan."""

    return ControlRejected.one_fault(
        ControlCode.RUN_NOT_RESUMABLE,
        f"legacy resume intent for {plan.run_id!r} has no exact attempt fence",
        "submit a new resume command with a new idempotency key",
        {"reason": "attempt_fence_missing"},
    )


_CommandPlan = Annotated[
    RunCreationPlan
    | _CancelPlan
    | ResumeCommandPlan
    | ApprovalPlan
    | ChannelApprovalPlan
    | _RegistrationPlan
    | _InitialPromotionPlan
    | _PromotionPlan
    | _RollbackPlan
    | ChannelReplyPlan
    | ChannelAckPlan
    | _AdmissionRejectPlan
    | _ControlRejectPlan,
    Field(discriminator="kind"),
]
_LoadedCommandPlan = _CommandPlan | LegacyResumeCommandPlan
_ResumeIntentDisposition = Literal["credited", "launchable", "superseded"]


class _StoredPlan(_PlanModel):
    schema_version: Literal[1] = 1
    plan: _CommandPlan


class _CommandSession:
    """One owned command fence and its single typed plan/terminal path."""

    def __init__(self, control: _CommandExecutor, claim: CommandClaim) -> None:
        self._control = control
        self.claim = claim

    @property
    def record(self) -> CommandRecord:
        return self._control._command_record(self.claim)

    def plan(self, value: _CommandPlan) -> _CommandPlan:
        record = self.record
        if record.plan is None:
            self._control._validate_command_plan(self.claim, value)
            envelope = _StoredPlan(plan=value).model_dump(mode="json")
            self._control._store.store_command_plan(self.claim, envelope)
            self._control._fault_probe(f"{self.claim.operation}.after_plan")
            return value
        plan = self._control._load_stored_plan(self.claim, record.plan)
        self._control._validate_command_plan(self.claim, plan)
        if isinstance(plan, LegacyResumeCommandPlan):
            raise JournalDamaged(
                f"current plan for command {self.claim.command_id!r} reconciled as legacy"
            )
        return plan

    def load(self) -> _LoadedCommandPlan:
        raw = self.record.plan
        if raw is None:
            raise JournalDamaged(f"command {self.claim.command_id!r} has no stored plan")
        plan = self._control._load_stored_plan(self.claim, raw)
        self._control._validate_command_plan(self.claim, plan)
        return plan

    def complete(self, response: BaseModel) -> None:
        self._control._store.complete_command(
            self.claim,
            response.model_dump(mode="json"),
        )
        self._control._fault_probe(f"{self.claim.operation}.after_command_completion")

    def reject(self, response: ControlRejected | AdmissionRejected) -> None:
        self._control._store.reject_command(
            self.claim,
            response.model_dump(mode="json"),
        )
        self._control._fault_probe(f"{self.claim.operation}.after_command_completion")


class _CommandExecutor:
    def __init__(
        self,
        *,
        system: Constructicon,
        store: ControlPlaneStore,
        journal: Journal | None = None,
        registry: ComponentRegistry | None = None,
        run_host: RunHost | None = None,
        owner_id: str | None = None,
        command_ttl_s: float = COMMAND_TTL_S,
        cursor_codec: CursorCodec | None = None,
        detail_resolver: DetailResolver | None = None,
        fault_probe: Callable[[str], None] | None = None,
    ) -> None:
        if command_ttl_s <= 0:
            raise ValueError("command_ttl_s must be positive")
        self._system = system
        self._store = store
        self._journal = journal or cast(Journal, store)
        self._registry = registry or ComponentRegistry(store=cast(RegistryStore, store))
        self._owner_id = owner_id or f"control:{system.owner_id}"
        self._command_ttl_s = command_ttl_s
        self._cursors = cursor_codec or CursorCodec()
        self._run_host = run_host or RunHost(system, journal=self._journal)
        self._run_host._configure_committed_resumes(
            store,
            self._resume_intent_from_record,
        )
        self._details = detail_resolver or DetailResolver(
            system=system,
            store=store,
            cursors=self._cursors,
            journal=self._journal,
            registry=self._registry,
        )
        self._fault_probe = fault_probe or (lambda name: None)

    # -- mutations ---------------------------------------------------------

    async def runs_start(
        self,
        actor: AuthenticatedActor,
        *,
        proposal: Graph | Mapping[str, Any] | str,
        inputs: Mapping[str, Any],
        idempotency_key: str,
    ) -> RunSubmission | AdmissionRejected | ControlRejected:
        request = {
            "proposal": (
                proposal.model_dump(mode="json") if isinstance(proposal, Graph) else proposal
            ),
            "inputs": dict(inputs),
        }
        begun = self._begin_command(
            actor,
            required_scope=OPERATE_SCOPE,
            operation="runs_start",
            idempotency_key=idempotency_key,
            request=request,
            response_types=(RunSubmission, AdmissionRejected, ControlRejected),
        )
        if not isinstance(begun, CommandClaim):
            if isinstance(begun, RunSubmission):
                self._launch_new_run(begun.run_id)
            return cast(RunSubmission | AdmissionRejected | ControlRejected, begun)
        claim = begun
        session = _CommandSession(self, claim)
        if session.record.plan is None:
            admitted = self._system.admit_graph(proposal, inputs)
            if isinstance(admitted, AdmissionRejected):
                return self._terminal_rejection(claim, admitted)
            run_id = run_id_for_command(claim.command_id)
            origin = RunOrigin(
                kind="start",
                actor_id=actor.actor_id,
                command_id=claim.command_id,
            )
            normalized_inputs = json_value(dict(inputs))
            if not isinstance(normalized_inputs, dict):
                raise JournalDamaged("admitted run inputs are not an object")
            session.plan(
                RunCreationPlan(
                    run_id=run_id,
                    manifest=admitted.manifest,
                    inputs=normalized_inputs,
                    origin=origin,
                )
            )
        plan = session.load()
        if isinstance(plan, _AdmissionRejectPlan):
            return self._terminal_rejection(claim, plan.response)
        if isinstance(plan, _ControlRejectPlan):
            return self._terminal_rejection(claim, plan.response)
        if not isinstance(plan, RunCreationPlan):
            raise JournalDamaged("runs_start command carries the wrong plan")
        run_id = plan.run_id
        manifest = plan.manifest
        run_inputs = plan.inputs
        origin = plan.origin
        self._system._prepare_run(manifest, run_id=run_id, inputs=run_inputs, origin=origin)
        self._fault_probe("runs_start.after_domain_mutation")
        response = self._submission(claim, run_id, origin)
        self._complete_command(claim, response)
        self._launch_new_run(run_id)
        return response

    async def runs_cancel(
        self,
        actor: AuthenticatedActor,
        *,
        run_id: RunId,
        idempotency_key: str,
    ) -> CancellationResult | ControlRejected:
        begun = self._begin_command(
            actor,
            required_scope=OPERATE_SCOPE,
            operation="runs_cancel",
            idempotency_key=idempotency_key,
            request={"run_id": str(run_id)},
            response_types=(CancellationResult, ControlRejected),
        )
        if not isinstance(begun, CommandClaim):
            return cast(CancellationResult | ControlRejected, begun)
        claim = begun
        session = _CommandSession(self, claim)
        record = self._journal.run_record(run_id)
        if record is None:
            return self._terminal_control_fault(
                claim,
                ControlCode.RUN_UNKNOWN,
                f"unknown run {run_id!r}",
                "use a RunId returned by a Constructicon run mutation",
            )
        if session.record.plan is None:
            terminal_event = self._journal.latest_terminal_event(run_id)
            if terminal_event is not None:
                observed_status = TERMINAL_EVENT_STATUSES.get(terminal_event.kind)
                if observed_status is None:
                    raise JournalDamaged("terminal run event has an unknown status family")
                terminal = True
                response_status = observed_status
                observed_event_seq = terminal_event.seq
            else:
                observed = self._journal.run_record(run_id)
                if observed is None:
                    raise JournalDamaged(f"run {run_id!r} disappeared while planning cancellation")
                terminal = False
                response_status = observed.status
                observed_status = observed.status
                observed_event_seq = None
            session.plan(
                _CancelPlan(
                    run_id=run_id,
                    observed_status=observed_status,
                    outcome=("already_terminal" if terminal else "cancel_requested"),
                    response_status=response_status,
                    observed_event_seq=observed_event_seq,
                )
            )
        plan = session.load()
        if isinstance(plan, _ControlRejectPlan):
            return self._terminal_rejection(claim, plan.response)
        if not isinstance(plan, _CancelPlan) or plan.run_id != run_id:
            raise JournalDamaged("runs_cancel command carries the wrong plan")
        if plan.outcome == "cancel_requested":
            self._system._request_cancel(run_id)
        self._fault_probe("runs_cancel.after_domain_mutation")
        response = CancellationResult(
            status=plan.outcome,
            run_id=run_id,
            run_status=plan.response_status,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
        )
        self._complete_command(claim, response)
        return response

    async def runs_resume(
        self,
        actor: AuthenticatedActor,
        *,
        run_id: RunId,
        idempotency_key: str,
    ) -> RunSubmission | ControlRejected:
        begun = self._begin_command(
            actor,
            required_scope=OPERATE_SCOPE,
            operation="runs_resume",
            idempotency_key=idempotency_key,
            request={"run_id": str(run_id)},
            response_types=(RunSubmission, ControlRejected),
        )
        if not isinstance(begun, CommandClaim):
            if isinstance(begun, RunSubmission):
                self._launch_replayed_resume(begun)
            return cast(RunSubmission | ControlRejected, begun)
        claim = begun
        session = _CommandSession(self, claim)
        head = self._journal.run_head(run_id)
        if head is None:
            return self._terminal_control_fault(
                claim,
                ControlCode.RUN_UNKNOWN,
                f"unknown run {run_id!r}",
                "use a RunId returned by a Constructicon run mutation",
            )
        record = head.record
        if session.record.plan is None:
            # These are complete observations before a resume intent exists.
            # Keeping them on an exact rejection plan means replay never asks
            # mutable run state to explain an already-recorded refusal.
            if record.status is RunStatus.RUNNING and record.liveness == "live":
                return self._terminal_control_fault(
                    claim,
                    ControlCode.RUN_LIVE_OWNER,
                    f"run {run_id!r} already has a live owner",
                    "poll runs_status or retry after ownership is lost",
                )
            if record.status in {RunStatus.SUCCEEDED, RunStatus.CANCELLED}:
                return self._terminal_control_fault(
                    claim,
                    ControlCode.RUN_TERMINAL,
                    f"run {run_id!r} is terminal at {record.status.value}",
                    "start a reproduction for a new RunId instead",
                )
            session.plan(
                ResumeCommandPlan(
                    terminal_rejection_policy="exact-v1",
                    run_id=run_id,
                    baseline_event_seq=head.event_seq,
                    submitted_status=record.status,
                )
            )
        plan = session.load()
        if isinstance(plan, _ControlRejectPlan):
            return self._terminal_rejection(claim, plan.response)
        if isinstance(plan, LegacyResumeCommandPlan):
            return self._terminal_rejection(claim, _unfenced_resume_rejection(plan))
        if not isinstance(plan, ResumeCommandPlan) or plan.run_id != run_id:
            raise JournalDamaged("runs_resume command carries the wrong plan")
        durable = self._classify_resume_intent(
            run_id,
            baseline_event_seq=plan.baseline_event_seq,
            submitted_status=plan.submitted_status,
            command_id=claim.command_id,
        )
        if durable == "credited":
            self._fault_probe("runs_resume.after_domain_mutation")
            response = RunSubmission(
                run_id=run_id,
                run_status=plan.submitted_status,
                command=CommandMeta(command_id=claim.command_id, replayed=False),
                origin=record.origin,
            )
            self._complete_command(claim, response)
            return response
        if durable == "superseded":
            return self._terminal_rejection(claim, _canonical_domain_rejection(plan))
        disposition = self._launch_resume(
            run_id,
            expected_event_seq=plan.baseline_event_seq,
            command_id=claim.command_id,
        )
        if disposition == "superseded":
            return self._terminal_rejection(claim, _canonical_domain_rejection(plan))
        self._fault_probe("runs_resume.after_domain_mutation")
        response = RunSubmission(
            run_id=run_id,
            run_status=plan.submitted_status,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
            origin=record.origin,
        )
        self._complete_command(claim, response)
        return response

    async def runs_reproduce(
        self,
        actor: AuthenticatedActor,
        *,
        source_run_id: RunId,
        idempotency_key: str,
    ) -> RunSubmission | ControlRejected:
        return await self._clone_run(
            actor,
            source_run_id=source_run_id,
            operation="runs_reproduce",
            idempotency_key=idempotency_key,
            overrides=None,
        )

    async def runs_counterfactual(
        self,
        actor: AuthenticatedActor,
        *,
        source_run_id: RunId,
        overrides: Mapping[str, Digest],
        idempotency_key: str,
    ) -> RunSubmission | ControlRejected:
        return await self._clone_run(
            actor,
            source_run_id=source_run_id,
            operation="runs_counterfactual",
            idempotency_key=idempotency_key,
            overrides=dict(overrides),
        )

    async def runs_approve(
        self,
        actor: AuthenticatedActor,
        *,
        run_id: RunId,
        subject: ProofSubject,
        decision: str,
        reason: str | None,
        idempotency_key: str,
        request_message_id: Digest | None = None,
    ) -> ApprovalCommandResult | ControlRejected:
        bound: ChannelMessage | None = None
        if request_message_id is not None:
            prepared = self._bound_approval_request(
                actor,
                request_message_id,
                run_id=run_id,
                subject=subject,
            )
            if isinstance(prepared, ControlRejected):
                return prepared
            bound = prepared
        # The key is absent, not null, when no request is bound: a standalone M6
        # decision must hash to exactly the request it always hashed to, or
        # every command already recorded under that key becomes unreplayable.
        request: dict[str, JsonValue] = {
            "run_id": str(run_id),
            "subject": subject.model_dump(mode="json"),
            "decision": decision,
            "reason": reason,
        }
        if request_message_id is not None:
            request["request_message_id"] = str(request_message_id)
        begun = self._begin_command(
            actor,
            required_scope=APPROVE_SCOPE,
            operation="runs_approve",
            idempotency_key=idempotency_key,
            request=request,
            response_types=(ApprovalCommandResult, ControlRejected),
        )
        if not isinstance(begun, CommandClaim):
            return cast(ApprovalCommandResult | ControlRejected, begun)
        claim = begun
        session = _CommandSession(self, claim)
        if decision not in {"approved", "rejected"}:
            return self._terminal_control_fault(
                claim,
                ControlCode.APPROVAL_INVALID_SUBJECT,
                f"unknown approval decision {decision!r}",
                "use 'approved' or 'rejected'",
            )
        if self._journal.run_record(run_id) is None:
            return self._terminal_control_fault(
                claim,
                ControlCode.RUN_UNKNOWN,
                f"unknown run {run_id!r}",
                "bind the decision to an existing run",
            )
        if session.record.plan is None:
            approval_id = approval_id_for_command(claim.command_id, subject.model_dump(mode="json"))
            approval = ApprovalRecord(
                approval_id=approval_id,
                subject=subject,
                decision=cast(Literal["approved", "rejected"], decision),
                reason=reason,
                actor=actor,
                run_id=run_id,
                created_at=utc_now(),
            )
            if bound is None:
                session.plan(ApprovalPlan(approval=approval))
            else:
                session.plan(self._channel_approval_plan(approval, bound))
        plan = session.load()
        if isinstance(plan, _ControlRejectPlan):
            return self._terminal_rejection(claim, plan.response)
        if isinstance(plan, ChannelApprovalPlan):
            approval = plan.approval
            applied = self._apply_channel_approval(claim, plan)
            if isinstance(applied, ControlRejected):
                return applied
            reply: Digest | None = applied.message_id
        elif isinstance(plan, ApprovalPlan):
            approval = plan.approval
            self._store.store_approval(claim, approval)
            self._fault_probe("runs_approve.after_domain_mutation")
            reply = None
        else:
            raise JournalDamaged("runs_approve command carries the wrong plan")
        response = ApprovalCommandResult(
            approval_id=approval.approval_id,
            decision=approval.decision,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
            detail=self._details.required_reference(
                actor, DetailAddress.approval(approval.approval_id)
            ),
            reply=reply,
        )
        self._complete_command(claim, response)
        return response

    def _sealed_request(
        self,
        request_id: Digest,
        actor: AuthenticatedActor,
    ) -> ChannelMessage:
        """Re-read a plan's request; a plan may never be its own evidence."""

        stored = self._journal.channel_delivery(message_id=request_id, actor_id=actor.actor_id)
        sealed = stored.message if stored is not None else None
        if (
            sealed is None
            or sealed.kind != "request"
            or not channel_authority_holder(sealed, actor)
        ):
            raise JournalDamaged(
                f"channel plan names no request {request_id} this actor may act on"
            )
        return sealed

    def _bound_approval_request(
        self,
        actor: AuthenticatedActor,
        request_message_id: Digest,
        *,
        run_id: RunId,
        subject: ProofSubject,
    ) -> ChannelMessage | ControlRejected:
        """The approval request this decision answers, or a refusal.

        Everything checked here is a property of the request rather than an
        outcome of the decision, so all of it refuses before the claim: no
        command record is written and the idempotency key stays reusable.
        """

        request = self._actionable_request(actor, request_message_id, consumes=APPROVE_CONSUMES)
        if isinstance(request, ControlRejected):
            return request
        # The decision names a run and the request belongs to one. If those
        # differ, the record would claim one run while the reply it writes is
        # delivered to — and wakes — another: a governance fact about nothing.
        if request.envelope.run_id != run_id:
            return self._fault(
                ControlCode.APPROVAL_RUN_MISMATCH,
                f"channel request {request_message_id} belongs to run "
                f"{request.envelope.run_id!r}, not {run_id!r}",
                "decide the request under the run that is waiting on it",
                {"run_id": str(request.envelope.run_id)},
            )
        # An `ApprovalRecord` is a governance fact. Nominal typing is what keeps
        # it from being written into an arbitrary approval-interaction exchange
        # that merely happens to look like a human-approval one.
        if (
            request.contract != APPROVAL_REQUEST_CONTRACT
            or request.reply_contract != APPROVAL_REPLY_CONTRACT
        ):
            return self._fault(
                ControlCode.APPROVAL_INVALID_SUBJECT,
                f"channel request {request_message_id} is not a human-approval exchange",
                "bind the decision to a request typed by the canonical approval contracts",
            )
        try:
            payload = ApprovalRequestPayload.model_validate(request.envelope.payload)
        except ValidationError:
            return self._fault(
                ControlCode.APPROVAL_INVALID_SUBJECT,
                f"channel request {request_message_id} carries no approval subject",
                "bind the decision to a request whose payload names its subject",
            )
        # Canonical bytes, never model equality. `1 == True` and `1 == 1.0` are
        # Python facts rather than JSON ones, so comparing models would accept a
        # decision about a subject this request never pinned.
        if canonical_json(json_value(payload.subject)) != canonical_json(
            json_value(subject.model_dump(mode="json"))
        ):
            return self._fault(
                ControlCode.APPROVAL_INVALID_SUBJECT,
                f"channel request {request_message_id} pins a different subject",
                "decide exactly the subject the bound request names",
                {"request_message_id": str(request_message_id)},
            )
        return request

    def _channel_approval_plan(
        self,
        approval: ApprovalRecord,
        request: ChannelMessage,
    ) -> ChannelApprovalPlan:
        """Bind the decision to the request, reading every field off the seal."""

        if request.reply_port is None:
            raise JournalDamaged(f"channel request {request.message_id} pins no reply port")
        run_id = request.envelope.run_id
        return ChannelApprovalPlan(
            approval=approval,
            channel_id=request.channel_id,
            request_id=request.message_id,
            reply_id=reply_message_id(
                request_id=request.message_id,
                reply_port=request.reply_port,
            ),
            reply_port=request.reply_port,
            payload=approval_decision_payload(approval),
            ack_actor_id=approval.actor.actor_id,
            run_id=run_id,
            parked_event_seq=self._journal.max_event_seq(run_id),
        )

    def _apply_channel_approval(
        self,
        claim: CommandClaim,
        plan: ChannelApprovalPlan,
    ) -> ChannelMessage | ControlRejected:
        """Approval, reply, and acknowledgement in one commit, then one wake.

        Approved and rejected are ordinary data here: nothing branches on which
        the decision was, so both record and wake identically.
        """

        try:
            reply = self._store.store_approval_exchange(
                claim,
                plan.approval,
                channel_id=plan.channel_id,
                request_id=plan.request_id,
                payload=plan.payload,
            )
        except ChannelReplyConflict:
            request = self._sealed_request(plan.request_id, plan.approval.actor)
            self._require_foreign_approval(
                request=request,
                command_id=claim.command_id,
            )
            return self._terminal_rejection(
                claim,
                self._already_replied_fault(plan.request_id, approval=True),
            )
        self._fault_probe("runs_approve.after_domain_mutation")
        self._run_host.launch(
            plan.run_id,
            expected_event_seq=plan.parked_event_seq,
            allowed_statuses=frozenset({RunStatus.PARKED}),
            cause=AttemptCause(kind="channel_reply", id=str(reply.message_id)),
        )
        return reply

    def _require_whole_exchange(
        self,
        request: ChannelMessage,
        reply: ChannelMessage,
    ) -> CommandRecord:
        """A foreign decision's triple is whole, or the store is torn.

        Approval and reply commit together and ensure the actor's immutable
        acknowledgement. Any two facts without the third are therefore not a
        race this command lost — they are a state that should be impossible.

        Existence is not togetherness. The reply names the command that wrote it,
        and that command must be the one that wrote the approval — otherwise a
        standalone decision could be spliced into an unrelated exchange and read
        as a complete foreign transaction. Provenance first, then the three
        facts must agree about subject, run, and who decided.

        The acknowledgement cannot supply that provenance: an actor may
        legitimately have acknowledged the request under an earlier
        `channels_ack`, and the reply then only implies that delivery fact
        rather than owning it.
        """

        carried = validated_approval_reply(request, reply)
        writer = self._journal.channel_message_writer(message_id=reply.message_id)
        if writer is None or not writer.is_current:
            # An approval exchange is a schema-7 fact. A reply from before that
            # era names no command of its own, so it cannot be one — and the
            # acknowledgement scalar it would otherwise offer is not a command
            # reference to resolve in its place.
            raise JournalDamaged(
                f"approval reply {reply.message_id} names no current-era writer command"
            )
        writer_record = self._store.command(writer.command_id)
        if writer_record is None:
            raise JournalDamaged(
                f"approval reply {reply.message_id} exists without its writer's command"
            )
        if writer_record.state == "rejected" or writer_record.plan is None:
            raise JournalDamaged(
                f"approval reply {reply.message_id} was not written by a live or "
                "successful approval plan"
            )
        validated_channel_approval_exchange(writer_record, carried, request, reply)
        return writer_record

    @staticmethod
    def _already_replied_fault(
        request_id: Digest,
        *,
        approval: bool,
    ) -> ControlRejected:
        noun = "approval request" if approval else "channel request"
        fact = "decision" if approval else "reply"
        repair = (
            "read the recorded decision with channels_message"
            if approval
            else "read the stored reply with channels_message"
        )
        return ControlRejected.one_fault(
            ControlCode.CHANNEL_ALREADY_REPLIED,
            f"{noun} {request_id} already carries its one {fact}",
            repair,
        )

    @staticmethod
    def _already_acknowledged_fault(message_id: Digest) -> ControlRejected:
        return ControlRejected.one_fault(
            ControlCode.IDEMPOTENCY_CONFLICT,
            f"message {message_id} is already acknowledged for this actor",
            "read the delivery state with channels_message",
        )

    def _require_foreign_reply(
        self,
        *,
        request: ChannelMessage,
        command_id: str,
    ) -> str:
        """Prove a foreign reply under its current or historical provenance.

        A schema-7 reply's exact read already requires its typed writer command
        and plan. A migrated schema-6 reply has a NULL writer column and only
        the acknowledgement's opaque command id; exact relationship, bytes,
        and ack ownership are the strongest historical proof that exists.
        """

        reply = self._journal.channel_reply_for(
            channel_id=request.channel_id,
            request_id=request.message_id,
        )
        writer = (
            self._journal.channel_message_writer(message_id=reply.message_id)
            if reply is not None
            else None
        )
        if reply is None or writer is None or writer.command_id == command_id:
            raise JournalDamaged(
                f"rejected command {command_id!r} has no foreign reply for {request.message_id}"
            )
        if reply.sender_actor_id is None:
            raise JournalDamaged(f"channel reply {reply.message_id} names no sender")
        if not writer.is_current:
            # The schema-6 fallback, taken because the reply records that era —
            # not because a command lookup happened to miss. Its identity is the
            # acknowledgement's opaque scalar, which may well collide with a real
            # command of some other operation; demanding a reply plan of it would
            # turn this lawful refusal into permanent damage.
            return writer.command_id
        writer_record = self._store.command(writer.command_id)
        if writer_record is None:
            raise JournalDamaged(
                f"channel reply {reply.message_id} names a writer command that is gone"
            )
        if writer_record.state == "rejected" or writer_record.plan is None:
            raise JournalDamaged(
                f"channel reply {reply.message_id} was not written by a live or "
                "successful reply plan"
            )
        writer_claim = self._claim_for_record(writer_record)
        writer_plan = self._load_stored_plan(writer_claim, writer_record.plan)
        self._validate_command_plan(writer_claim, writer_plan)
        if not isinstance(writer_plan, ChannelReplyPlan):
            raise JournalDamaged(
                f"channel reply {reply.message_id} was not written by a channel reply plan"
            )
        validated_channel_command_reply(writer_record, request, reply)
        return writer_record.command_id

    def _require_foreign_approval(
        self,
        *,
        request: ChannelMessage,
        command_id: str,
    ) -> CommandRecord:
        """Prove the foreign approval exchange that made one decision lose."""

        reply = self._journal.channel_reply_for(
            channel_id=request.channel_id,
            request_id=request.message_id,
        )
        if reply is None:
            raise JournalDamaged(f"rejected approval command {command_id!r} has no winning reply")
        writer = self._require_whole_exchange(request, reply)
        if writer.command_id == command_id:
            raise JournalDamaged("rejected approval command owns the reply it claims it lost")
        return writer

    def _require_foreign_ack(
        self,
        *,
        plan: ChannelAckPlan,
        command_id: str,
    ) -> str:
        """Prove the command whose delivery fact made one acknowledgement lose.

        An acknowledgement has three legitimate authors.  ``channels_ack`` may
        claim it directly; ``channels_reply`` and request-bound ``runs_approve``
        may imply it while writing their reply.  The row alone cannot say which
        law produced it, so its owning command must carry the corresponding
        exact plan, and reply-shaped owners must still prove their reply-shaped
        domain fact.
        """

        ack = self._journal.channel_ack(
            message_id=plan.message_id,
            actor_id=plan.actor_id,
        )
        if (
            ack is None
            or ack.ack.message_id != plan.message_id
            or ack.ack.actor_id != plan.actor_id
            or ack.command_id == command_id
        ):
            raise JournalDamaged(f"rejected command {command_id!r} has no foreign acknowledgement")
        writer = self._store.command(ack.command_id)
        if writer is None:
            # SQLite exposes this case only for the positive schema-6 shape:
            # provenance v0 below the migration cutoff and no command row.
            # Historical acknowledgement was a standalone delivery fact and
            # need not have an accompanying reply. A current row whose command
            # disappeared is refused by the durable decoder before it reaches
            # this compatibility branch.
            return ack.command_id
        if writer.state == "rejected" or writer.plan is None:
            raise JournalDamaged(
                f"acknowledgement for {plan.message_id} was not written by a live or "
                "successful command plan"
            )
        writer_claim = self._claim_for_record(writer)
        writer_plan = self._load_stored_plan(writer_claim, writer.plan)
        self._validate_command_plan(writer_claim, writer_plan)

        if isinstance(writer_plan, ChannelAckPlan):
            exact = (
                writer_plan.message_id == plan.message_id and writer_plan.actor_id == plan.actor_id
            )
        elif isinstance(writer_plan, ChannelReplyPlan):
            request = self._sealed_request(writer_plan.request_id, writer.actor)
            reply_writer = self._require_foreign_reply(
                request=request,
                command_id=command_id,
            )
            exact = (
                reply_writer == ack.command_id
                and writer_plan.request_id == plan.message_id
                and writer_plan.actor_id == plan.actor_id
            )
        elif isinstance(writer_plan, ChannelApprovalPlan):
            request = self._sealed_request(writer_plan.request_id, writer.actor)
            approval_writer = self._require_foreign_approval(
                request=request,
                command_id=command_id,
            )
            exact = (
                approval_writer.command_id == ack.command_id
                and writer_plan.request_id == plan.message_id
                and writer_plan.ack_actor_id == plan.actor_id
            )
        else:
            exact = False
        if not exact:
            raise JournalDamaged(
                f"acknowledgement for {plan.message_id} contradicts its writer's durable plan"
            )
        return writer.command_id

    async def channels_reply(
        self,
        actor: AuthenticatedActor,
        *,
        message_id: Digest,
        payload: JsonValue,
        idempotency_key: str,
    ) -> ChannelReplyResult | ControlRejected:
        """Answer one advice request, and only an advice request.

        Approval is consumed exclusively by request-bound `runs_approve`, so
        holding approve must not quietly make this a generic reply path. The
        dispatch rule is stated at the call — `REPLY_CONSUMES` — rather than
        emerging from whichever scopes the actor happens to carry.
        """

        request = self._actionable_request(actor, message_id, consumes=REPLY_CONSUMES)
        if isinstance(request, ControlRejected):
            return request
        reply_contract = request.reply_contract
        if reply_contract is None:
            raise JournalDamaged(
                f"channel request {request.message_id} carries no sealed reply contract"
            )
        incoherence = canonical_exchange_fault(
            request.contract,
            reply_contract,
            request.interaction,
        )
        if incoherence is not None:
            return self._fault(
                ControlCode.REQUEST_INVALID,
                f"channel request {request.message_id} carries an incoherent exchange: "
                f"{incoherence}",
                "answer a request admitted with a coherent contract pair and interaction",
                {"interaction": request.interaction},
            )
        begun = self._begin_command(
            actor,
            # `_actionable_request` has already derived and enforced the exact
            # scope this request seals. The claim's door stays the coarse one,
            # so it states a fact rather than repeating a check that cannot fail.
            required_scope=frozenset(INTERACTION_SCOPES.values()),
            operation="channels_reply",
            idempotency_key=idempotency_key,
            request={"message_id": str(message_id), "payload": payload},
            response_types=(ChannelReplyResult, ControlRejected),
        )
        if not isinstance(begun, CommandClaim):
            return cast(ChannelReplyResult | ControlRejected, begun)
        claim = begun
        session = _CommandSession(self, claim)
        if session.record.plan is None:
            session.plan(self._channel_reply_plan(actor, request, payload))
        plan = session.load()
        if isinstance(plan, _ControlRejectPlan):
            return self._terminal_rejection(claim, plan.response)
        if not isinstance(plan, ChannelReplyPlan):
            raise JournalDamaged("channels_reply command carries the wrong plan")
        try:
            reply = self._journal.channel_reply(
                channel_id=plan.channel_id,
                request_id=plan.request_id,
                actor_id=plan.actor_id,
                payload=plan.payload,
                command_id=claim.command_id,
            )
        except ChannelReplyConflict:
            request = self._sealed_request(plan.request_id, actor)
            self._require_foreign_reply(
                request=request,
                command_id=claim.command_id,
            )
            return self._terminal_rejection(
                claim,
                self._already_replied_fault(plan.request_id, approval=False),
            )
        self._fault_probe("channels_reply.after_domain_mutation")
        # The reply is the durable wake; this only spares the human the scan
        # interval. It is pinned to the fence the plan recorded, so a replay
        # cannot revive an attempt the run has already moved past, and the
        # answered-wait scan remains the authority when this process dies.
        self._run_host.launch(
            plan.run_id,
            expected_event_seq=plan.parked_event_seq,
            allowed_statuses=frozenset({RunStatus.PARKED}),
            cause=AttemptCause(kind="channel_reply", id=str(reply.message_id)),
        )
        response = ChannelReplyResult(
            request_id=plan.request_id,
            message_id=reply.message_id,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
            detail=self._details.required_reference(
                actor,
                DetailAddress.channel_message(reply.message_id),
            ),
        )
        self._complete_command(claim, response)
        return response

    async def channels_ack(
        self,
        actor: AuthenticatedActor,
        *,
        message_id: Digest,
        idempotency_key: str,
    ) -> ChannelAckResult | ControlRejected:
        """Record that one actor took delivery of one request.

        Both interactions are delivered, so both are ackable, each under its own
        scope. Replies are not: no inbox ever surfaces one, so acknowledging a
        reply would record a delivery that never happened. `_actionable_request`
        refuses a reply id for both mutations, deliberately and in one place.
        """

        request = self._actionable_request(actor, message_id, consumes=ACK_CONSUMES)
        if isinstance(request, ControlRejected):
            return request
        begun = self._begin_command(
            actor,
            required_scope=frozenset(INTERACTION_SCOPES.values()),
            operation="channels_ack",
            idempotency_key=idempotency_key,
            request={"message_id": str(message_id)},
            response_types=(ChannelAckResult, ControlRejected),
        )
        if not isinstance(begun, CommandClaim):
            return cast(ChannelAckResult | ControlRejected, begun)
        claim = begun
        session = _CommandSession(self, claim)
        if session.record.plan is None:
            session.plan(
                ChannelAckPlan(
                    channel_id=request.channel_id,
                    message_id=request.message_id,
                    interaction=request.interaction,
                    actor_id=actor.actor_id,
                )
            )
        plan = session.load()
        if isinstance(plan, _ControlRejectPlan):
            return self._terminal_rejection(claim, plan.response)
        if not isinstance(plan, ChannelAckPlan):
            raise JournalDamaged("channels_ack command carries the wrong plan")
        try:
            ack = self._journal.channel_acknowledge(
                channel_id=plan.channel_id,
                message_id=plan.message_id,
                actor_id=plan.actor_id,
                command_id=claim.command_id,
            )
        except ChannelAckConflict:
            # Another command already owns this actor's delivery fact. One fact,
            # one owning command, so this is a duplicate rather than damage.
            self._require_foreign_ack(
                plan=plan,
                command_id=claim.command_id,
            )
            return self._terminal_rejection(
                claim,
                self._already_acknowledged_fault(message_id),
            )
        self._fault_probe("channels_ack.after_domain_mutation")
        response = ChannelAckResult(
            message_id=ack.message_id,
            actor_id=ack.actor_id,
            acked_at=ack.acked_at,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
        )
        self._complete_command(claim, response)
        return response

    def _actionable_request(
        self,
        actor: AuthenticatedActor,
        message_id: Digest,
        *,
        consumes: frozenset[ChannelInteraction],
    ) -> ChannelMessage | ControlRejected:
        """The request this operation may act on, refused in dispatch order.

        Kind, then interaction, then authority — and all three before the
        command is claimed, because none of them is a domain outcome. An
        idempotency key is not burned by asking the wrong operation, and a
        durable command record is not written for a message this operation was
        never going to consume.
        """

        resolved = governed_delivery(self._journal, actor, message_id)
        if isinstance(resolved, ControlRejected):
            return resolved
        delivery, governing = resolved
        message = delivery.message
        if message.kind != "request":
            return self._fault(
                ControlCode.CHANNEL_REQUEST_REQUIRED,
                f"channel message {message_id} is a reply; this operation acts on a request",
                "address the request instead, as channels_inbox lists it",
            )
        if governing.interaction not in consumes:
            # Interaction before authority: telling an approver to acquire a
            # scope would be wrong guidance when even holding it, this is not
            # the operation that consumes an approval.
            return self._fault(
                ControlCode.CHANNEL_WRONG_INTERACTION,
                f"this operation consumes {sorted(consumes)}, "
                f"not a sealed {governing.interaction!r} request",
                (
                    "answer an approval request with runs_approve bound to it"
                    if governing.interaction == "approval"
                    else "answer an advice request with channels_reply"
                ),
                {"interaction": governing.interaction},
            )
        return channel_scope_refusal(governing, actor) or governing

    def _channel_reply_plan(
        self,
        actor: AuthenticatedActor,
        request: ChannelMessage,
        answer: JsonValue,
    ) -> ChannelReplyPlan:
        """Read every field off the sealed request; the caller wrote the answer."""

        if request.reply_port is None:
            raise JournalDamaged(f"channel request {request.message_id} pins no reply port")
        run_id = request.envelope.run_id
        reply_id = reply_message_id(
            request_id=request.message_id,
            reply_port=request.reply_port,
        )
        return ChannelReplyPlan(
            channel_id=request.channel_id,
            request_id=request.message_id,
            interaction=request.interaction,
            actor_id=actor.actor_id,
            reply_id=reply_id,
            reply_port=request.reply_port,
            payload=sealed_reply_payload(
                request,
                answer=answer,
                actor_id=actor.actor_id,
                reply_id=reply_id,
            ),
            run_id=run_id,
            parked_event_seq=self._journal.max_event_seq(run_id),
        )

    async def registry_register(
        self,
        actor: AuthenticatedActor,
        *,
        definition: ComponentDef | DefinitionBundle,
        idempotency_key: str,
    ) -> RegistrationCommandResult | ControlRejected:
        if isinstance(definition, DefinitionBundle):
            canonical = definition.definition
            implementation = definition.implementation
        else:
            canonical = definition
            implementation = None
        begun = self._begin_command(
            actor,
            required_scope=ADMIN_SCOPE,
            operation="registry_register",
            idempotency_key=idempotency_key,
            request={"definition": canonical.model_dump(mode="json")},
            response_types=(RegistrationCommandResult, ControlRejected),
        )
        if not isinstance(begun, CommandClaim):
            return cast(RegistrationCommandResult | ControlRejected, begun)
        claim = begun
        session = _CommandSession(self, claim)
        if session.record.plan is None:
            try:
                planned = self._registry.plan_registration(
                    canonical,
                    impl=implementation,
                    registered_at=session.record.created_at,
                )
            except (AdmissionError, ContractViolation, RegistryError, ValueError) as exc:
                return self._terminal_control_fault(
                    claim,
                    ControlCode.REQUEST_INVALID,
                    str(exc),
                    "submit a canonical restart-importable component definition",
                )
            session.plan(
                _RegistrationPlan(
                    definition=planned.stored.definition,
                    content_hash=planned.stored.content_hash,
                    candidate_timestamp=planned.stored.registered_at,
                    row_origin=planned.row_origin,
                )
            )
        plan = session.load()
        if isinstance(plan, _ControlRejectPlan):
            return self._terminal_rejection(claim, plan.response)
        if not isinstance(plan, _RegistrationPlan):
            raise JournalDamaged("registry_register command carries the wrong plan")
        stored = self._registry.apply_registration(
            PlannedRegistration(
                stored=StoredVersion(
                    definition=plan.definition,
                    content_hash=plan.content_hash,
                    registered_at=plan.candidate_timestamp,
                ),
                row_origin=plan.row_origin,
            )
        )
        self._fault_probe("registry_register.after_domain_mutation")
        response = RegistrationCommandResult(
            component=stored.definition.name,
            version=stored.content_hash,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
            detail=self._details.required_reference(
                actor,
                DetailAddress.component(stored.definition.name, stored.content_hash),
            ),
        )
        self._complete_command(claim, response)
        return response

    async def registry_promote_initial(
        self,
        actor: AuthenticatedActor,
        *,
        component: str,
        version: Digest,
        idempotency_key: str,
    ) -> PromotionCommandResult | ControlRejected:
        begun = self._begin_command(
            actor,
            required_scope=ADMIN_SCOPE,
            operation="registry_promote_initial",
            idempotency_key=idempotency_key,
            request={"component": component, "version": str(version)},
            response_types=(PromotionCommandResult, ControlRejected),
        )
        if not isinstance(begun, CommandClaim):
            return cast(PromotionCommandResult | ControlRejected, begun)
        claim = begun
        session = _CommandSession(self, claim)
        if session.record.plan is None:
            try:
                planned = self._registry.plan_initial_promotion(
                    component=component,
                    version=version,
                )
            except (AdmissionError, ContractViolation, RegistryError, ValueError) as exc:
                return self._terminal_control_fault(
                    claim,
                    ControlCode.REGISTRY_VERSION_UNKNOWN,
                    str(exc),
                    "register the exact target version before initial promotion",
                )
            prior = self._registry.store.promotion_for_attestation(planned.attestation_id)
            stable = self._registry.stable_version(component)
            if prior is None and stable is not None:
                return self._terminal_control_fault(
                    claim,
                    ControlCode.REGISTRY_STABLE_MOVED,
                    f"component {component!r} is already stable at {stable}",
                    "use evaluated promotion for an established stable pointer",
                )
            session.plan(
                _InitialPromotionPlan(
                    terminal_rejection_policy="exact-v1",
                    component=component,
                    target=version,
                    draft=planned.draft,
                    attestation_id=planned.attestation_id,
                )
            )
        plan = session.load()
        if isinstance(plan, _ControlRejectPlan):
            return self._terminal_rejection(claim, plan.response)
        if not isinstance(plan, _InitialPromotionPlan):
            raise JournalDamaged("registry_promote_initial command carries the wrong plan")
        record = self._apply_policy_promotion(
            plan=plan,
            actor_id=actor.actor_id,
            internal_fault="registry_promote_initial.after_attestation",
        )
        if isinstance(record, ControlRejected):
            return self._terminal_rejection(claim, record)
        self._fault_probe("registry_promote_initial.after_domain_mutation")
        response = PromotionCommandResult(
            status="promoted",
            component=record.component,
            from_version=record.from_version,
            to_version=record.to_version,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
            detail=self._details.required_reference(
                actor,
                DetailAddress.component(record.component, record.to_version),
            ),
        )
        self._complete_command(claim, response)
        return response

    async def registry_promote(
        self,
        actor: AuthenticatedActor,
        *,
        component: str,
        version: Digest,
        attestation_id: str,
        idempotency_key: str,
    ) -> PromotionCommandResult | ControlRejected:
        begun = self._begin_command(
            actor,
            required_scope=PROMOTE_SCOPE,
            operation="registry_promote",
            idempotency_key=idempotency_key,
            request={
                "component": component,
                "version": str(version),
                "attestation_id": attestation_id,
            },
            response_types=(PromotionCommandResult, ControlRejected),
        )
        if not isinstance(begun, CommandClaim):
            return cast(PromotionCommandResult | ControlRejected, begun)
        claim = begun
        session = _CommandSession(self, claim)
        if session.record.plan is None:
            planned = self._plan_promotion(component, version, attestation_id)
            if isinstance(planned, ControlRejected):
                return self._terminal_rejection(claim, planned)
            session.plan(
                _PromotionPlan(
                    terminal_rejection_policy="exact-v1",
                    component=component,
                    baseline=self._optional_digest(planned.get("baseline")),
                    target=version,
                    attestation_id=attestation_id,
                )
            )
        plan = session.load()
        if isinstance(plan, _ControlRejectPlan):
            return self._terminal_rejection(claim, plan.response)
        if not isinstance(plan, _PromotionPlan):
            raise JournalDamaged("registry_promote command carries the wrong plan")
        prior = self._registry.store.promotion_for_attestation(plan.attestation_id)
        if prior is not None:
            self._validate_evaluated_promotion_receipt(prior, plan=plan)
            record = prior
        else:
            current = self._registry.stable_version(plan.component)
            if current == plan.target:
                return self._terminal_rejection(claim, _canonical_domain_rejection(plan))
            if current != plan.baseline:
                return self._terminal_rejection(claim, _canonical_domain_rejection(plan))
            try:
                record = self._system._promote_version(
                    component=plan.component,
                    version=plan.target,
                    attestation_id=plan.attestation_id,
                    actor=actor.actor_id,
                )
            except (AdmissionError, ContractViolation):
                prior = self._registry.store.promotion_for_attestation(plan.attestation_id)
                if prior is None:
                    return self._terminal_rejection(claim, _canonical_domain_rejection(plan))
                record = prior
            self._validate_evaluated_promotion_receipt(record, plan=plan)
        self._fault_probe("registry_promote.after_domain_mutation")
        response = PromotionCommandResult(
            status="promoted",
            component=plan.component,
            from_version=record.from_version,
            to_version=record.to_version,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
            detail=self._details.required_reference(
                actor, DetailAddress.component(plan.component, record.to_version)
            ),
        )
        self._complete_command(claim, response)
        return response

    async def registry_rollback(
        self,
        actor: AuthenticatedActor,
        *,
        component: str,
        expected_stable: Digest,
        idempotency_key: str,
    ) -> PromotionCommandResult | ControlRejected:
        begun = self._begin_command(
            actor,
            required_scope=PROMOTE_SCOPE,
            operation="registry_rollback",
            idempotency_key=idempotency_key,
            request={"component": component, "expected_stable": str(expected_stable)},
            response_types=(PromotionCommandResult, ControlRejected),
        )
        if not isinstance(begun, CommandClaim):
            return cast(PromotionCommandResult | ControlRejected, begun)
        claim = begun
        session = _CommandSession(self, claim)
        if session.record.plan is None:
            try:
                planned = self._registry.plan_rollback(
                    component=component,
                    expected_stable=expected_stable,
                )
            except (AdmissionError, ContractViolation) as exc:
                return self._terminal_control_fault(
                    claim,
                    ControlCode.REGISTRY_STABLE_MOVED,
                    str(exc),
                    "inspect registry state and retry with a new key",
                )
            session.plan(
                _RollbackPlan(
                    terminal_rejection_policy="exact-v1",
                    component=component,
                    baseline=expected_stable,
                    target=planned.target,
                    draft=planned.draft,
                    attestation_id=planned.attestation_id,
                )
            )
        plan = session.load()
        if isinstance(plan, _ControlRejectPlan):
            return self._terminal_rejection(claim, plan.response)
        if not isinstance(plan, _RollbackPlan):
            raise JournalDamaged("registry_rollback command carries the wrong plan")
        applied = self._apply_policy_promotion(plan=plan, actor_id=actor.actor_id)
        if isinstance(applied, ControlRejected):
            return self._terminal_rejection(claim, applied)
        self._fault_probe("registry_rollback.after_domain_mutation")
        response = PromotionCommandResult(
            status="rolled_back",
            component=plan.component,
            from_version=applied.from_version,
            to_version=applied.to_version,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
            detail=self._details.required_reference(
                actor, DetailAddress.component(plan.component, applied.to_version)
            ),
        )
        self._complete_command(claim, response)
        return response

    # -- clone/counterfactual ---------------------------------------------

    async def _clone_run(
        self,
        actor: AuthenticatedActor,
        *,
        source_run_id: RunId,
        operation: str,
        idempotency_key: str,
        overrides: dict[str, Digest] | None,
    ) -> RunSubmission | ControlRejected:
        begun = self._begin_command(
            actor,
            required_scope=OPERATE_SCOPE,
            operation=operation,
            idempotency_key=idempotency_key,
            request={
                "source_run_id": str(source_run_id),
                "overrides": {
                    name: str(version) for name, version in sorted((overrides or {}).items())
                },
            },
            response_types=(RunSubmission, ControlRejected),
        )
        if not isinstance(begun, CommandClaim):
            if isinstance(begun, RunSubmission):
                self._launch_new_run(begun.run_id)
            return cast(RunSubmission | ControlRejected, begun)
        claim = begun
        session = _CommandSession(self, claim)
        if session.record.plan is None:
            source_record = self._journal.run_record(source_run_id)
            if source_record is None:
                return self._terminal_control_fault(
                    claim,
                    ControlCode.RUN_UNKNOWN,
                    f"unknown source run {source_run_id!r}",
                    "choose an existing source run",
                )
            source_manifest = self._system.manifest_for_run(source_run_id)
            source_inputs = self._system.inputs_for_run(source_run_id)
            manifest = source_manifest
            mode: Literal["live", "simulated"] = "live"
            capability_mode: Literal["normal", "discard"] = "normal"
            normalized_overrides: dict[str, Digest] = {}
            if operation == "runs_counterfactual":
                normalized_overrides = dict(overrides or {})
                source_components = {
                    resolution.component for resolution in source_manifest.resolved_components
                }
                unknown_names = sorted(set(normalized_overrides) - source_components)
                if unknown_names:
                    return self._terminal_control_fault(
                        claim,
                        ControlCode.COUNTERFACTUAL_OVERRIDE_INVALID,
                        f"overrides name components absent from the source world: {unknown_names}",
                        "override only exact component names recorded in the source manifest",
                    )
                snapshot = self._registry.snapshot()
                for name, version in normalized_overrides.items():
                    if snapshot.get(name, version) is None:
                        return self._terminal_control_fault(
                            claim,
                            ControlCode.REGISTRY_VERSION_UNKNOWN,
                            f"override {name!r}@{version} is not retained",
                            "choose an exact version returned by registry_versions",
                        )
                lock = ResolutionLock(
                    source_manifest_hash=source_manifest.manifest_hash,
                    pins=tuple(
                        ResolutionPin(
                            scope=resolution.scope,
                            component=resolution.component,
                            version=normalized_overrides.get(
                                resolution.component, resolution.resolved_version
                            ),
                        )
                        for resolution in source_manifest.resolved_components
                    ),
                )
                try:
                    manifest = self._system.validate(
                        source_manifest.source_graph,
                        source_inputs,
                        resolution_lock=lock,
                    )
                except AdmissionError as exc:
                    return self._terminal_control_fault(
                        claim,
                        ControlCode.COUNTERFACTUAL_LOCK_MISMATCH,
                        str(exc),
                        "use a contract-compatible exact override; topology changes wait for M9",
                    )
                mode = "simulated"
                capability_mode = "discard"
            run_id = run_id_for_command(claim.command_id)
            origin = RunOrigin(
                kind="counterfactual" if operation == "runs_counterfactual" else "reproduce",
                actor_id=actor.actor_id,
                command_id=claim.command_id,
                source_run_id=source_run_id,
                overrides=normalized_overrides,
                effects=mode,
                capabilities=capability_mode,
            )
            source_graph_hash = digest(
                "graph-proposal",
                1,
                source_manifest.source_graph.model_dump(mode="json"),
            )
            session.plan(
                RunCreationPlan(
                    run_id=run_id,
                    manifest=manifest,
                    inputs=source_inputs,
                    origin=origin,
                    source_lock=SourceRunLock(
                        run_id=source_run_id,
                        manifest_hash=source_manifest.manifest_hash,
                        input_hash=source_manifest.input_hash,
                        source_graph_hash=source_graph_hash,
                        resolution_lock=(lock if operation == "runs_counterfactual" else None),
                    ),
                )
            )
        plan = session.load()
        if isinstance(plan, _ControlRejectPlan):
            return self._terminal_rejection(claim, plan.response)
        if not isinstance(plan, RunCreationPlan):
            raise JournalDamaged(f"{operation} command carries the wrong plan")
        run_id = plan.run_id
        manifest = plan.manifest
        run_inputs = plan.inputs
        origin = plan.origin
        self._system._prepare_run(manifest, run_id=run_id, inputs=run_inputs, origin=origin)
        self._fault_probe(f"{operation}.after_domain_mutation")
        response = self._submission(claim, run_id, origin)
        self._complete_command(claim, response)
        self._launch_new_run(run_id)
        return response

    # -- command law ------------------------------------------------------

    def _complete_command(self, claim: CommandClaim, response: BaseModel) -> None:
        _CommandSession(self, claim).complete(response)

    def _begin_command(
        self,
        actor: AuthenticatedActor,
        *,
        required_scope: str | frozenset[str],
        operation: str,
        idempotency_key: str,
        request: Any,
        response_types: tuple[type[BaseModel], ...],
    ) -> CommandClaim | BaseModel:
        denied = self._authorize(actor, required_scope)
        if denied:
            return denied
        try:
            key = validate_idempotency_key(idempotency_key)
            normalized = json_value(request)
        except (TypeError, ValueError) as exc:
            return self._fault(
                ControlCode.REQUEST_INVALID,
                str(exc),
                "submit canonical JSON and a non-empty bounded idempotency key",
            )
        request_hash = command_request_hash(normalized)
        result = self._store.claim_command(
            actor=actor,
            operation=operation,
            idempotency_key=key,
            request_hash=request_hash,
            request=normalized,
            owner_id=self._owner_id,
            ttl_s=self._command_ttl_s,
        )
        if result.status == "conflict":
            return self._fault(
                ControlCode.IDEMPOTENCY_CONFLICT,
                "this actor, operation, and idempotency key already name another request",
                "reuse the original arguments or choose a new idempotency key",
                {"command_id": result.record.command_id if result.record else None},
            )
        if result.status == "in_progress":
            return self._fault(
                ControlCode.COMMAND_IN_PROGRESS,
                "the identical command is still owned by a live control worker",
                "poll commands_status and retry after its short claim expires",
                {"command_id": result.record.command_id if result.record else None},
            )
        if result.status == "replayed":
            if result.record is None or result.record.response is None:
                raise JournalDamaged("terminal command has no stored response")
            decoded = self._decode_response(result.record.response, response_types, actor)
            self._validate_terminal_response(result.record, decoded)
            return self._mark_replayed(decoded)
        if result.claim is None:
            raise JournalDamaged("claimed command returned no fence")
        return result.claim

    def _terminal_rejection(self, claim: CommandClaim, response: T) -> T:
        session = _CommandSession(self, claim)
        record = session.record
        plan: _LoadedCommandPlan
        if record.plan is None:
            if isinstance(response, AdmissionRejected):
                planned: _CommandPlan = _AdmissionRejectPlan(
                    command_id=claim.command_id,
                    request_hash=record.request_hash,
                    response=response,
                )
            elif isinstance(response, ControlRejected):
                planned = _ControlRejectPlan(
                    command_id=claim.command_id,
                    operation=claim.operation,
                    request_hash=record.request_hash,
                    response=response,
                )
            else:
                raise JournalDamaged("unknown terminal rejection schema family")
            plan = session.plan(planned)
        else:
            plan = self._load_stored_plan(claim, record.plan)
            self._validate_command_plan(claim, plan)
            if (
                isinstance(plan, (_AdmissionRejectPlan, _ControlRejectPlan))
                and not _same_json_fact(plan.response, response)
            ):
                raise JournalDamaged(f"command {claim.command_id!r} rejection contradicts its plan")
        rejection = cast(ControlRejected | AdmissionRejected, response)
        self._validate_terminal_rejection(record, plan, rejection)
        session.reject(rejection)
        return response

    def _terminal_control_fault(
        self,
        claim: CommandClaim,
        code: ControlCode,
        message: str,
        repair: str,
        details: dict[str, JsonValue] | None = None,
    ) -> ControlRejected:
        return self._terminal_rejection(claim, self._fault(code, message, repair, details))

    def _command_record(self, claim: CommandClaim) -> CommandRecord:
        record = self._store.command(claim.command_id)
        if record is None:
            raise JournalDamaged(f"claimed command {claim.command_id!r} disappeared")
        return record

    @staticmethod
    def _parse_stored_plan(claim: CommandClaim, raw: JsonValue) -> _CommandPlan:
        if not isinstance(raw, dict) or "schema_version" not in raw:
            raise JournalDamaged(
                f"command {claim.command_id!r} carries a legacy plan where a typed "
                "schema-1 plan is required"
            )
        try:
            parsed = _StoredPlan.model_validate_json(canonical_json(raw))
        except (TypeError, ValueError, ValidationError) as exc:
            raise JournalDamaged(
                f"command {claim.command_id!r} has an invalid typed plan: {exc}"
            ) from exc
        rendered = parsed.model_dump(mode="json")
        if canonical_json(raw) != canonical_json(rendered):
            raise JournalDamaged(f"command {claim.command_id!r} typed plan is not lossless")
        expected: dict[str, tuple[type[BaseModel], ...]] = {
            "runs_start": (RunCreationPlan, _AdmissionRejectPlan, _ControlRejectPlan),
            "runs_cancel": (_CancelPlan, _ControlRejectPlan),
            "runs_resume": (ResumeCommandPlan, _ControlRejectPlan),
            "runs_reproduce": (RunCreationPlan, _ControlRejectPlan),
            "runs_counterfactual": (RunCreationPlan, _ControlRejectPlan),
            "runs_approve": (ApprovalPlan, ChannelApprovalPlan, _ControlRejectPlan),
            "channels_reply": (ChannelReplyPlan, _ControlRejectPlan),
            "channels_ack": (ChannelAckPlan, _ControlRejectPlan),
            "registry_register": (_RegistrationPlan, _ControlRejectPlan),
            "registry_promote_initial": (_InitialPromotionPlan, _ControlRejectPlan),
            "registry_promote": (_PromotionPlan, _ControlRejectPlan),
            "registry_rollback": (_RollbackPlan, _ControlRejectPlan),
        }
        allowed = expected.get(claim.operation)
        if allowed is None or not isinstance(parsed.plan, allowed):
            raise JournalDamaged(
                f"command {claim.command_id!r} operation {claim.operation!r} "
                f"does not match plan kind {parsed.plan.kind!r}"
            )
        return parsed.plan

    def _load_stored_plan(
        self,
        claim: CommandClaim,
        raw: JsonValue,
    ) -> _LoadedCommandPlan:
        if isinstance(raw, dict) and "schema_version" in raw:
            return self._parse_stored_plan(claim, raw)
        if not isinstance(raw, dict):
            raise JournalDamaged(f"command {claim.command_id!r} has no object plan")
        record = self._command_record(claim)
        operation = claim.operation
        try:
            if "rejection" in raw:
                rejected = self._object(raw, "rejection")
                if operation == "runs_start":
                    try:
                        admission = AdmissionRejected.model_validate(rejected)
                    except ValidationError:
                        admission = None
                    if admission is not None:
                        return _AdmissionRejectPlan(
                            command_id=claim.command_id,
                            request_hash=record.request_hash,
                            response=admission,
                        )
                response = cast(
                    ControlRejected,
                    self._decode_response(
                        rejected,
                        (ControlRejected,),
                        record.actor,
                    ),
                )
                return _ControlRejectPlan(
                    command_id=claim.command_id,
                    operation=operation,
                    request_hash=record.request_hash,
                    response=response,
                )
            if operation in {
                "runs_start",
                "runs_reproduce",
                "runs_counterfactual",
            }:
                legacy_inputs = json_value(self._object(raw, "inputs"))
                if not isinstance(legacy_inputs, dict):
                    raise JournalDamaged("legacy run inputs are not an object")
                return RunCreationPlan(
                    run_id=RunId(self._string(raw, "run_id")),
                    manifest=ExecutionManifest.model_validate(self._object(raw, "manifest")),
                    inputs=legacy_inputs,
                    origin=RunOrigin.model_validate(self._object(raw, "origin")),
                )
            if operation == "runs_resume":
                run_id = RunId(self._string(raw, "run_id"))
                legacy_plan = validated_resume_command_plan(record)
                if (
                    isinstance(legacy_plan, LegacyResumeCommandPlan)
                    and legacy_plan.baseline_event_seq is None
                ):
                    return legacy_plan
                run = self._journal.run_record(run_id)
                if run is None:
                    raise JournalDamaged("legacy resume run disappeared")
                resume_baseline = self._optional_nonnegative_int(raw, "baseline_event_seq")
                if resume_baseline is None:
                    raise JournalDamaged("unfenced legacy resume plan changed during decoding")
                return ResumeCommandPlan(
                    run_id=run_id,
                    baseline_event_seq=resume_baseline,
                    submitted_status=self._resume_status_for_plan_fence(legacy_plan),
                )
            if operation == "runs_approve":
                return ApprovalPlan(
                    approval=ApprovalRecord.model_validate(self._object(raw, "approval"))
                )
            if operation == "registry_promote":
                return _PromotionPlan(
                    component=self._string(raw, "component"),
                    baseline=self._optional_digest(raw.get("baseline")),
                    target=Digest(self._string(raw, "version")),
                    attestation_id=self._string(raw, "attestation_id"),
                )
            if operation == "registry_rollback":
                component = self._string(raw, "component")
                rollback_baseline = Digest(self._string(raw, "expected_stable"))
                target = Digest(self._string(raw, "target"))
                planned = self._registry.plan_rollback_edge(
                    component=component,
                    baseline=rollback_baseline,
                    target=target,
                )
                return _RollbackPlan(
                    component=component,
                    baseline=rollback_baseline,
                    target=target,
                    draft=planned.draft,
                    attestation_id=planned.attestation_id,
                )
        except (TypeError, ValueError, ValidationError) as exc:
            raise JournalDamaged(
                f"command {claim.command_id!r} has invalid legacy plan data: {exc}"
            ) from exc
        raise JournalDamaged(
            f"command {claim.command_id!r} has unsupported legacy plan for {operation!r}"
        )

    def _validate_command_plan(
        self,
        claim: CommandClaim,
        plan: _LoadedCommandPlan,
    ) -> None:
        """Bind a parsed plan to its immutable command request and domain identity."""

        record = self._command_record(claim)
        request = record.request
        if not isinstance(request, dict):
            raise JournalDamaged("command request is not an object")
        if isinstance(plan, (_AdmissionRejectPlan, _ControlRejectPlan)):
            if (
                plan.command_id != claim.command_id
                or plan.request_hash != record.request_hash
                or (isinstance(plan, _ControlRejectPlan) and plan.operation != claim.operation)
            ):
                raise JournalDamaged("rejection plan contradicts its command identity")
            return

        if isinstance(plan, RunCreationPlan):
            validated = (
                validated_run_creation_command(record)
                if record.plan is not None
                else validated_new_run_creation_plan(record, plan)
            )
            if validated != plan:
                raise JournalDamaged("run creation plan contradicts its command")
            origin = plan.origin
            if claim.operation == "runs_start":
                return
            source_run_id = origin.source_run_id
            assert source_run_id is not None
            overrides = origin.overrides
            source_record = self._journal.run_record(source_run_id)
            if source_record is None:
                raise JournalDamaged("clone source run disappeared")
            source_manifest = self._system.manifest_for_run(source_run_id)
            source_inputs = self._system.inputs_for_run(source_run_id)
            if (
                not _same_json_fact(plan.inputs, source_inputs)
                or not _same_json_fact(
                    plan.manifest.source_graph,
                    source_manifest.source_graph,
                )
            ):
                raise JournalDamaged("clone plan contradicts its immutable source world")
            legacy = isinstance(record.plan, dict) and "schema_version" not in record.plan
            if plan.source_lock is None:
                if not legacy:
                    raise JournalDamaged("current clone plan has no source lock")
                return
            source_lock = plan.source_lock
            expected_graph_hash = digest(
                "graph-proposal",
                1,
                source_manifest.source_graph.model_dump(mode="json"),
            )
            if (
                source_lock.run_id != source_run_id
                or source_lock.manifest_hash != source_record.manifest_hash
                or source_lock.input_hash != source_record.input_hash
                or source_lock.source_graph_hash != expected_graph_hash
            ):
                raise JournalDamaged("clone source lock contradicts its durable source")
            if claim.operation == "runs_reproduce":
                if (
                    overrides
                    or source_lock.resolution_lock is not None
                    or not _same_json_fact(plan.manifest, source_manifest)
                ):
                    raise JournalDamaged("reproduce plan changed its source world")
                return
            expected_lock = ResolutionLock(
                source_manifest_hash=source_manifest.manifest_hash,
                pins=tuple(
                    ResolutionPin(
                        scope=resolution.scope,
                        component=resolution.component,
                        version=overrides.get(
                            resolution.component,
                            resolution.resolved_version,
                        ),
                    )
                    for resolution in source_manifest.resolved_components
                ),
            )
            if source_lock.resolution_lock != expected_lock:
                raise JournalDamaged("counterfactual resolution lock contradicts its request")
            return

        if isinstance(plan, _CancelPlan):
            if request.get("run_id") != str(plan.run_id):
                raise JournalDamaged("run command plan targets another RunId")
            if plan.observed_status != plan.response_status:
                raise JournalDamaged("cancellation plan carries contradictory observed statuses")
            if plan.outcome == "cancel_requested":
                if plan.observed_event_seq is not None:
                    raise JournalDamaged("cancel-request plan carries a terminal event marker")
                return
            if plan.observed_event_seq is not None:
                event = self._journal.event(plan.run_id, plan.observed_event_seq)
                expected_kind = TERMINAL_STATUS_EVENTS.get(plan.observed_status)
                if event is None or event.kind != expected_kind:
                    raise JournalDamaged(
                        "cancellation plan contradicts its exact terminal observation"
                    )
                return
            if plan.observed_status in {RunStatus.SUCCEEDED, RunStatus.CANCELLED}:
                # Immutable, so the run itself still proves the observation.
                current = self._journal.run_record(plan.run_id)
                if current is None or current.status != plan.observed_status:
                    raise JournalDamaged(
                        "legacy cancellation contradicts its immutable terminal status"
                    )
                return
            # A resumable status may have moved on since, so the run cannot
            # re-prove what was observed. The migration's terminal witness can:
            # it bound this plan and the exact response the command gave at
            # the one moment the observation could be honestly recorded.
            witness = self._store.historical_domain_plan_evidence(claim.command_id)
            if witness is not None and witness.phase_at_migration == "terminal":
                return
            raise JournalDamaged(
                "legacy cancellation of a resumable status has no exact observation"
            )

        if isinstance(plan, LegacyResumeCommandPlan):
            if (
                claim.operation != "runs_resume"
                or plan.baseline_event_seq is not None
                or validated_resume_command_plan(record) != plan
            ):
                raise JournalDamaged("legacy unfenced resume plan contradicts its command")
            return

        if isinstance(plan, ResumeCommandPlan):
            if request.get("run_id") != str(plan.run_id):
                raise JournalDamaged("run command plan targets another RunId")
            self._resume_status_for_plan_fence(plan)
            return

        if isinstance(plan, ApprovalPlan):
            approval = plan.approval
            if (
                "request_message_id" in request
                or request.get("run_id") != str(approval.run_id)
                or not _same_json_fact(
                    request.get("subject"),
                    approval.subject,
                )
                or request.get("decision") != approval.decision
                or request.get("reason") != approval.reason
                or approval.actor != record.actor
                or approval.approval_id
                != approval_id_for_command(claim.command_id, request.get("subject"))
            ):
                raise JournalDamaged("approval plan contradicts its canonical request")
            return

        if isinstance(plan, ChannelApprovalPlan):
            approval = plan.approval
            if (
                request.get("run_id") != str(approval.run_id)
                or not _same_json_fact(
                    request.get("subject"),
                    approval.subject,
                )
                or request.get("decision") != approval.decision
                or request.get("reason") != approval.reason
                or request.get("request_message_id") != str(plan.request_id)
                or approval.actor != record.actor
                or plan.ack_actor_id != record.actor.actor_id
                or approval.approval_id
                != approval_id_for_command(claim.command_id, request.get("subject"))
            ):
                raise JournalDamaged("channel approval plan contradicts its canonical request")
            sealed = self._sealed_request(plan.request_id, record.actor)
            validated_channel_approval_plan(plan, approval, sealed)
            return

        if isinstance(plan, ChannelReplyPlan):
            sealed = self._sealed_request(plan.request_id, record.actor)
            validated_channel_reply_plan(record, plan, sealed)
            return

        if isinstance(plan, ChannelAckPlan):
            sealed = self._sealed_request(plan.message_id, record.actor)
            validated_channel_ack_plan(record, plan, sealed)
            return

        if isinstance(plan, _RegistrationPlan):
            try:
                requested = ComponentDef.model_validate(request.get("definition"))
            except ValidationError as exc:
                raise JournalDamaged("registration request has an invalid definition") from exc
            if not _same_json_fact(requested, plan.definition):
                raise JournalDamaged("registration plan contradicts its canonical request")
            existing = self._registry.snapshot().get(
                plan.definition.name,
                plan.content_hash,
            )
            if plan.row_origin == "existing":
                # A reused identity binds to the durable row that already carries
                # it, never to a re-derivation. A retained version keeps the
                # identity it was written under, so recomputing here would make
                # every row registered under an older hash law unreplayable.
                if (
                    existing is None
                    or not _same_json_fact(existing.definition, plan.definition)
                    or existing.registered_at != plan.candidate_timestamp
                ):
                    raise JournalDamaged("registration plan contradicts its existing row")
                return
            # A new row, by contrast, may only claim a definition-derived identity.
            if plan.content_hash != plan.definition.content_hash():
                raise JournalDamaged("new registration identity is not definition-derived")
            if plan.candidate_timestamp != record.created_at:
                raise JournalDamaged("new registration timestamp is not command-derived")
            return

        if isinstance(plan, _InitialPromotionPlan):
            if request.get("component") != plan.component or request.get("version") != str(
                plan.target
            ):
                raise JournalDamaged("initial-promotion plan contradicts its request")
            try:
                expected = self._registry.plan_initial_promotion(
                    component=plan.component,
                    version=plan.target,
                )
            except (AdmissionError, RegistryError) as exc:
                raise JournalDamaged("initial-promotion target is not retained") from exc
            if (
                plan.baseline is not None
                or not _same_json_fact(plan.draft, expected.draft)
                or plan.attestation_id != expected.attestation_id
            ):
                raise JournalDamaged("initial-promotion policy identity is invalid")
            return

        if isinstance(plan, _PromotionPlan):
            if (
                request.get("component") != plan.component
                or request.get("version") != str(plan.target)
                or request.get("attestation_id") != plan.attestation_id
            ):
                raise JournalDamaged("promotion plan contradicts its canonical request")
            attestation = self._journal.load_attestation(plan.attestation_id)
            subject = attestation.subject if attestation is not None else None
            if (
                attestation is None
                or attestation.action != "promote"
                or not isinstance(subject, ComponentProofSubject)
                or subject.component != plan.component
                or subject.version != plan.target
                or subject.baseline_version != plan.baseline
                or not attestation.ok
            ):
                raise JournalDamaged("promotion plan has no exact authority fact")
            return

        if isinstance(plan, _RollbackPlan):
            if request.get("component") != plan.component or request.get("expected_stable") != str(
                plan.baseline
            ):
                raise JournalDamaged("rollback plan contradicts its canonical request")
            try:
                expected = self._registry.plan_rollback_edge(
                    component=plan.component,
                    baseline=plan.baseline,
                    target=plan.target,
                )
            except RegistryError as exc:
                raise JournalDamaged("rollback target is not retained") from exc
            if (
                not _same_json_fact(plan.draft, expected.draft)
                or plan.attestation_id != expected.attestation_id
            ):
                raise JournalDamaged("rollback policy identity is invalid")
            return

        raise JournalDamaged("unknown command plan family")

    @staticmethod
    def _claim_for_record(record: CommandRecord) -> CommandClaim:
        """A read-only claim identity for validating one durable command record."""

        return CommandClaim(
            command_id=record.command_id,
            actor_id=record.actor.actor_id,
            operation=record.operation,
            owner_id=record.owner_id or "replay:terminal",
            epoch=max(1, record.owner_epoch),
            expires_at=record.updated_at,
        )

    def _validate_created_run_fact(self, plan: RunCreationPlan) -> None:
        """Bind one creation plan to the exact run world it committed."""

        record = self._journal.run_record(plan.run_id)
        inputs = self._journal.run_inputs(plan.run_id)
        try:
            manifest = self._system.manifest_for_run(plan.run_id)
        except ContractViolation as exc:
            raise JournalDamaged(
                f"created run {plan.run_id!r} has no exact manifest"
            ) from exc
        if (
            record is None
            or inputs is None
            or record.manifest_hash != plan.manifest.manifest_hash
            or record.input_hash != plan.manifest.input_hash
            or not _same_json_fact(manifest, plan.manifest)
            or not _same_json_fact(inputs, plan.inputs)
            or not _same_json_fact(record.origin, plan.origin)
        ):
            raise JournalDamaged(
                f"created run {plan.run_id!r} contradicts its command plan"
            )

    def _validate_terminal_response(
        self,
        record: CommandRecord,
        response: BaseModel,
        *,
        loaded_plan: _LoadedCommandPlan | None = None,
    ) -> _ResumeIntentDisposition | None:
        response_is_rejection = isinstance(
            response,
            (AdmissionRejected, ControlRejected),
        )
        if (record.state == "rejected") != response_is_rejection:
            raise JournalDamaged(
                "terminal command lifecycle contradicts its response family"
            )
        if record.plan is None:
            raise JournalDamaged("terminal command has no immutable plan")
        claim = self._claim_for_record(record)
        plan = (
            self._load_stored_plan(claim, record.plan)
            if loaded_plan is None
            else loaded_plan
        )
        self._validate_command_plan(claim, plan)
        if response_is_rejection:
            assert isinstance(response, (AdmissionRejected, ControlRejected))
            self._validate_terminal_rejection(record, plan, response)
            return None

        command = getattr(response, "command", None)
        if (
            not isinstance(command, CommandMeta)
            or command.command_id != record.command_id
            or command.replayed
        ):
            raise JournalDamaged("successful response has invalid command metadata")

        if isinstance(response, RunSubmission):
            if isinstance(plan, RunCreationPlan):
                self._validate_created_run_fact(plan)
                if (
                    response.run_id != plan.run_id
                    or response.run_status is not RunStatus.PENDING
                    or response.origin != plan.origin
                ):
                    raise JournalDamaged("run submission contradicts its creation plan")
            elif isinstance(plan, (ResumeCommandPlan, LegacyResumeCommandPlan)):
                run = self._journal.run_record(plan.run_id)
                expected_status = (
                    plan.submitted_status if isinstance(plan, ResumeCommandPlan) else None
                )
                if (
                    run is None
                    or response.run_id != plan.run_id
                    or (expected_status is not None and response.run_status != expected_status)
                    or response.origin != run.origin
                ):
                    raise JournalDamaged("resume response contradicts its attempt plan")
                if isinstance(plan, ResumeCommandPlan):
                    return self._classify_resume_intent(
                        plan.run_id,
                        baseline_event_seq=plan.baseline_event_seq,
                        submitted_status=plan.submitted_status,
                        command_id=record.command_id,
                    )
            else:
                raise JournalDamaged("run submission has the wrong plan family")
            if self._journal.run_record(response.run_id) is None:
                raise JournalDamaged("submitted run has no durable row")
            return None

        if isinstance(response, CancellationResult):
            run = self._journal.run_record(plan.run_id) if isinstance(plan, _CancelPlan) else None
            if (
                not isinstance(plan, _CancelPlan)
                or response.run_id != plan.run_id
                or response.status != plan.outcome
                or response.run_status != plan.response_status
                or run is None
                or (plan.outcome == "cancel_requested" and not run.cancel_requested)
            ):
                raise JournalDamaged(
                    "cancellation response contradicts its plan or durable request"
                )
            return None
        if isinstance(response, ApprovalCommandResult):
            if not isinstance(plan, (ApprovalPlan, ChannelApprovalPlan)):
                raise JournalDamaged("approval response has the wrong plan")
            expected_detail = self._details.required_reference(
                record.actor,
                DetailAddress.approval(plan.approval.approval_id),
            )
            if (
                response.approval_id != plan.approval.approval_id
                or response.decision != plan.approval.decision
                or self._store.approval(response.approval_id) != plan.approval
                or self._store.approval_for_command(record.command_id) != plan.approval
                or response.detail != expected_detail
            ):
                raise JournalDamaged("approval response contradicts its plan or fact")
            if isinstance(plan, ApprovalPlan):
                if response.reply is not None:
                    raise JournalDamaged("standalone approval response names a reply")
                return None
            # Bound: validate the same transaction-shaped proof used when a
            # foreign command discovers this answer. Content agreement alone is
            # insufficient: both the approval and reply must name this command.
            answered = self._journal.channel_reply_for(
                channel_id=plan.channel_id,
                request_id=plan.request_id,
            )
            sealed = self._sealed_request(plan.request_id, record.actor)
            writer = (
                self._require_whole_exchange(sealed, answered) if answered is not None else None
            )
            if (
                answered is None
                or writer is None
                or writer.command_id != record.command_id
                or answered.message_id != plan.reply_id
                or answered.sender_actor_id != plan.ack_actor_id
                or canonical_json(json_value(answered.envelope.payload))
                != canonical_json(json_value(plan.payload))
                or response.reply != plan.reply_id
            ):
                raise JournalDamaged("bound approval response contradicts its plan or facts")
            return None
        if isinstance(response, ChannelReplyResult):
            if not isinstance(plan, ChannelReplyPlan):
                raise JournalDamaged("channel reply response has the wrong plan")
            request = self._journal.channel_delivery(
                message_id=plan.request_id,
                actor_id=plan.actor_id,
            )
            reply = self._journal.channel_reply_for(
                channel_id=plan.channel_id,
                request_id=plan.request_id,
            )
            # `channel_reply_for` rebuilds the reply from its request rather
            # than trusting a `reply_to` pointer, so existence is already a
            # validated relationship. What remains is that the stored reply is
            # THIS command's: its derived id, its sender, its planned payload,
            # and the request ack that shares its transaction.
            if (
                request is None
                or reply is None
                or not request.acknowledged
                or self._journal.channel_message_writer(message_id=plan.reply_id)
                != ChannelMessageWriter(command_id=record.command_id, era="current")
                or reply.message_id != plan.reply_id
                or reply.sender_actor_id != plan.actor_id
                or canonical_json(json_value(reply.envelope.payload))
                != canonical_json(json_value(plan.payload))
                or response.request_id != plan.request_id
                or response.message_id != plan.reply_id
                or response.detail
                != self._details.required_reference(
                    record.actor,
                    DetailAddress.channel_message(plan.reply_id),
                )
            ):
                raise JournalDamaged("channel reply response contradicts its plan or fact")
            return None
        if isinstance(response, ChannelAckResult):
            if not isinstance(plan, ChannelAckPlan):
                raise JournalDamaged("channel ack response has the wrong plan")
            ack_record = self._journal.channel_ack(
                message_id=plan.message_id,
                actor_id=plan.actor_id,
            )
            if (
                ack_record is None
                or ack_record.command_id != record.command_id
                or ack_record.ack.message_id != plan.message_id
                or ack_record.ack.actor_id != plan.actor_id
                or response.message_id != ack_record.ack.message_id
                or response.actor_id != ack_record.ack.actor_id
                or response.acked_at != ack_record.ack.acked_at
            ):
                raise JournalDamaged("channel ack response contradicts its plan or fact")
            return None
        if isinstance(response, RegistrationCommandResult):
            if not isinstance(plan, _RegistrationPlan):
                raise JournalDamaged("registration response has the wrong plan")
            stored = self._registry.snapshot().get(
                plan.definition.name,
                plan.content_hash,
            )
            if (
                stored is None
                or not _same_json_fact(stored.definition, plan.definition)
                or stored.registered_at != plan.candidate_timestamp
                or response.component != plan.definition.name
                or response.version != plan.content_hash
                or response.detail
                != self._details.required_reference(
                    record.actor,
                    DetailAddress.component(plan.definition.name, plan.content_hash),
                )
            ):
                raise JournalDamaged("registration response contradicts its exact row")
            return None
        if isinstance(response, PromotionCommandResult):
            if isinstance(plan, (_InitialPromotionPlan, _PromotionPlan, _RollbackPlan)):
                component = plan.component
                baseline = plan.baseline
                target = plan.target
                attestation_id = plan.attestation_id
            else:
                raise JournalDamaged("promotion response has the wrong plan")
            receipt = self._registry.store.promotion_for_attestation(attestation_id)
            if (
                receipt is None
                or response.status
                != ("rolled_back" if isinstance(plan, _RollbackPlan) else "promoted")
                or response.component != component
                or response.from_version != baseline
                or response.to_version != target
                or receipt.component != component
                or receipt.from_version != baseline
                or receipt.to_version != target
                or receipt.attestation_id != attestation_id
                or response.detail
                != self._details.required_reference(
                    record.actor,
                    DetailAddress.component(component, target),
                )
            ):
                raise JournalDamaged("promotion response contradicts its exact receipt")
            if isinstance(plan, _PromotionPlan):
                self._validate_evaluated_promotion_receipt(receipt, plan=plan)
            else:
                self._validate_promotion_receipt(
                    receipt,
                    component=component,
                    baseline=baseline,
                    target=target,
                    attestation_id=attestation_id,
                    draft=plan.draft,
                )
            return None
        raise JournalDamaged("terminal response uses an unknown schema family")

    def _validate_terminal_rejection(
        self,
        record: CommandRecord,
        plan: _LoadedCommandPlan,
        response: AdmissionRejected | ControlRejected,
    ) -> None:
        """Bind a refusal to the only plan families that can lawfully emit it."""

        if isinstance(plan, _AdmissionRejectPlan):
            if record.operation != "runs_start" or not _same_json_fact(
                response,
                plan.response,
            ):
                raise JournalDamaged("admission rejection contradicts its claimed command")
            return
        if isinstance(plan, _ControlRejectPlan):
            if not _same_json_fact(response, plan.response):
                raise JournalDamaged("control rejection contradicts its claimed command")
            return
        if record.operation == "runs_resume" and isinstance(
            plan,
            (ResumeCommandPlan, LegacyResumeCommandPlan),
        ):
            if not isinstance(response, ControlRejected):
                raise JournalDamaged("resume domain plan carries another response family")
            historical = resume_plan_requires_historical_evidence(record)
            if historical:
                evidence = self._store.historical_resume_plan_evidence(record.command_id)
                if evidence is None:
                    raise JournalDamaged("historical resume plan has no era evidence")
                if evidence.phase_at_migration == "terminal":
                    # The migration witness binds the complete structurally
                    # decoded response, including its fault tuple.
                    return
            expected_resume = (
                _unfenced_resume_rejection(plan)
                if isinstance(plan, LegacyResumeCommandPlan)
                else _canonical_domain_rejection(plan)
            )
            if len(response.faults) != 1 or not _same_json_fact(
                response,
                expected_resume,
            ):
                raise JournalDamaged(
                    "resume rejection contradicts its exact planned refusal"
                )
            return
        if not isinstance(response, ControlRejected) or len(response.faults) != 1:
            raise JournalDamaged("domain plan carries an invalid terminal rejection")

        code = response.faults[0].code
        expected: ControlRejected | None = None
        if isinstance(
            plan,
            (_InitialPromotionPlan, _PromotionPlan, _RollbackPlan),
        ) and (
            record.operation,
            type(plan),
        ) in {
            ("registry_promote_initial", _InitialPromotionPlan),
            ("registry_promote", _PromotionPlan),
            ("registry_rollback", _RollbackPlan),
        }:
            if plan.terminal_rejection_policy != "exact-v1":
                # Written before its refusal had canonical bytes, so nothing
                # can re-derive them today. What can still be trusted is the
                # migration's witness: a terminal witness bound the exact
                # retained response at the one moment such a plan could be
                # honestly observed, and a legacy shape with no witness is not
                # history but a downgrade — which stays damage.
                witness = self._store.historical_domain_plan_evidence(record.command_id)
                if witness is None:
                    raise JournalDamaged(
                        f"{record.operation!r} legacy domain-plan rejection has no exact proof"
                    )
                if witness.phase_at_migration == "terminal":
                    # The witness excuses the wording, which no law today can
                    # re-derive. It does not excuse the code: every writer that
                    # ever refused after a promotion plan refused for this one
                    # reason, and that much is checkable without any bytes.
                    if code is not ControlCode.REGISTRY_STABLE_MOVED:
                        raise JournalDamaged(
                            f"{record.operation!r} witnessed rejection carries an unlawful code"
                        )
                    return
                # Witnessed while still prepared: whoever finished it did so
                # under the current law, so its refusal must be the exact one.
            expected = _canonical_domain_rejection(plan)
            if not _same_json_fact(response, expected):
                raise JournalDamaged(
                    f"{record.operation!r} rejection contradicts its exact planned edge"
                )
            return
        elif record.operation == "channels_reply" and isinstance(plan, ChannelReplyPlan):
            request = self._sealed_request(plan.request_id, record.actor)
            self._require_foreign_reply(
                request=request,
                command_id=record.command_id,
            )
            lawful = {ControlCode.CHANNEL_ALREADY_REPLIED}
            expected = self._already_replied_fault(plan.request_id, approval=False)
        elif record.operation == "runs_approve" and isinstance(plan, ChannelApprovalPlan):
            request = self._sealed_request(plan.request_id, record.actor)
            self._require_foreign_approval(
                request=request,
                command_id=record.command_id,
            )
            lawful = {ControlCode.CHANNEL_ALREADY_REPLIED}
            expected = self._already_replied_fault(plan.request_id, approval=True)
        elif record.operation == "channels_ack" and isinstance(plan, ChannelAckPlan):
            self._require_foreign_ack(
                plan=plan,
                command_id=record.command_id,
            )
            lawful = {ControlCode.IDEMPOTENCY_CONFLICT}
            expected = self._already_acknowledged_fault(plan.message_id)
        else:
            lawful = set()
        if code not in lawful:
            raise JournalDamaged(
                f"{record.operation!r} rejection is not lawful for its durable domain plan"
            )
        if expected is not None and not _same_json_fact(response, expected):
            raise JournalDamaged(
                f"{record.operation!r} rejection contradicts its canonical response"
            )

    # -- helpers ----------------------------------------------------------

    def _launch_new_run(self, run_id: RunId) -> None:
        """Host a new/replayed submission only while it remains recoverable work.

        A replay after a completed FAILED/PARKED attempt returns the stored
        response without silently turning the original command into a resume.
        The event fence also prevents queued intent from starting after another
        owner has advanced the run.
        """

        record = self._journal.run_record(run_id)
        if record is None:
            raise JournalDamaged(f"submitted run {run_id!r} disappeared")
        if record.status not in _NEW_RUN_LAUNCH_STATUSES:
            return
        self._run_host.launch(
            run_id,
            expected_event_seq=self._journal.max_event_seq(run_id),
            allowed_statuses=_NEW_RUN_LAUNCH_STATUSES,
        )

    def _launch_resume(
        self,
        run_id: RunId,
        *,
        expected_event_seq: int,
        command_id: str,
    ) -> LaunchDisposition:
        return self._run_host.launch(
            run_id,
            expected_event_seq=expected_event_seq,
            allowed_statuses=RESUMABLE_RUN_STATUSES,
            cause=AttemptCause(kind="resume_command", id=command_id),
        )

    def _launch_replayed_resume(self, submission: RunSubmission) -> None:
        record = self._store.command(submission.command.command_id)
        if record is None:
            raise JournalDamaged(f"replayed command {submission.command.command_id!r} disappeared")
        intent = self._resume_intent_from_record(record)
        if intent is None:
            return
        run_id, baseline, command_id = intent
        self._launch_resume(
            run_id,
            expected_event_seq=baseline,
            command_id=command_id,
        )

    def _resume_intent_from_record(
        self,
        record: CommandRecord,
    ) -> tuple[RunId, int, str] | None:
        if record.operation != "runs_resume" or record.state not in {"committed", "rejected"}:
            raise JournalDamaged("terminal resume scan returned a nonterminal command")
        if record.response is None or record.plan is None:
            raise JournalDamaged("terminal resume command lacks plan or response")
        decoded = self._decode_response(
            record.response,
            (RunSubmission, ControlRejected),
            record.actor,
        )
        claim = self._claim_for_record(record)
        plan = self._load_stored_plan(claim, record.plan)
        disposition = self._validate_terminal_response(
            record,
            decoded,
            loaded_plan=plan,
        )
        if record.state == "rejected":
            return None
        if not isinstance(decoded, RunSubmission):
            raise JournalDamaged("committed resume response has the wrong family")
        if isinstance(plan, LegacyResumeCommandPlan):
            return None
        if not isinstance(plan, ResumeCommandPlan):
            raise JournalDamaged("committed resume command carries another plan kind")
        if disposition is None:
            raise JournalDamaged("committed resume response has no durable disposition")
        if disposition != "launchable":
            return None
        return (plan.run_id, plan.baseline_event_seq, record.command_id)

    def _classify_resume_intent(
        self,
        run_id: RunId,
        *,
        baseline_event_seq: int,
        submitted_status: RunStatus,
        command_id: str,
    ) -> _ResumeIntentDisposition:
        """Classify one successful intent without crediting a competing attempt."""

        current_seq = self._journal.max_event_seq(run_id)
        if self._resume_attempt_started(
            run_id,
            baseline_event_seq=baseline_event_seq,
            submitted_status=submitted_status,
            command_id=command_id,
            current_event_seq=current_seq,
        ):
            return "credited"
        run = self._journal.run_record(run_id)
        if run is None:
            raise JournalDamaged(f"committed resume run {run_id!r} disappeared")
        if current_seq > baseline_event_seq:
            # Another command or ordinary recovery lawfully won the fence.
            return "superseded"
        if run.status not in RESUMABLE_RUN_STATUSES:
            return "superseded"
        return "launchable"

    def _resume_attempt_started(
        self,
        run_id: RunId,
        *,
        baseline_event_seq: int,
        submitted_status: RunStatus,
        command_id: str,
        current_event_seq: int | None = None,
    ) -> bool:
        current = (
            self._journal.max_event_seq(run_id) if current_event_seq is None else current_event_seq
        )
        if current < baseline_event_seq:
            raise JournalDamaged("resume event sequence precedes its stored baseline")
        if current == baseline_event_seq:
            return False
        events = self._journal.events(
            run_id,
            after_seq=baseline_event_seq,
            limit=1,
        )
        if not events or events[0].seq != baseline_event_seq + 1:
            raise JournalDamaged("resume attempt history is not contiguous with its baseline")
        try:
            expected_kind = resume_attempt_kind(submitted_status)
        except ValueError as exc:
            raise JournalDamaged("resume plan has a non-resumable submitted status") from exc
        event = events[0]
        try:
            cause = AttemptCause.from_payload(event.payload)
        except ValueError as exc:
            raise JournalDamaged("resume attempt event has contradictory cause facts") from exc
        return event.kind == expected_kind and cause == AttemptCause(
            kind="resume_command",
            id=command_id,
        )

    def _resume_status_for_plan_fence(
        self,
        plan: ResumeCommandPlan | LegacyResumeCommandPlan,
    ) -> RunStatus:
        """Project the one L0 status law through retained event history."""

        baseline_event_seq = plan.baseline_event_seq
        if baseline_event_seq is None:
            raise JournalDamaged("resume plan has no exact event fence")
        baseline = (
            self._journal.event(plan.run_id, baseline_event_seq)
            if baseline_event_seq > 0
            else None
        )
        try:
            return validated_resume_status_at_fence(
                plan,
                baseline_event_kind=(baseline.kind if baseline is not None else None),
            )
        except ValueError as exc:
            raise JournalDamaged("resume plan contradicts its exact fenced status") from exc

    def _submission(
        self,
        claim: CommandClaim,
        run_id: RunId,
        origin: RunOrigin | None,
    ) -> RunSubmission:
        record = self._journal.run_record(run_id)
        if record is None:
            raise JournalDamaged(f"planned run {run_id!r} was not durably created")
        return RunSubmission(
            run_id=run_id,
            run_status=RunStatus.PENDING,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
            origin=origin,
        )

    def _plan_promotion(
        self,
        component: str,
        version: Digest,
        attestation_id: str,
    ) -> dict[str, JsonValue] | ControlRejected:
        snapshot = self._registry.snapshot()
        if snapshot.get(component, version) is None:
            return self._fault(
                ControlCode.REGISTRY_VERSION_UNKNOWN,
                f"component {component!r} has no retained version {version}",
                "choose a version returned by registry_versions",
            )
        attestation = self._journal.load_attestation(attestation_id)
        if attestation is None:
            return self._fault(
                ControlCode.REQUEST_INVALID,
                f"attestation {attestation_id!r} is not journal-minted",
                "use an attestation id returned by deterministic evaluation",
            )
        subject = attestation.subject
        if (
            attestation.action != "promote"
            or not isinstance(subject, ComponentProofSubject)
            or subject.component != component
            or subject.version != version
            or not attestation.ok
        ):
            return self._fault(
                ControlCode.REQUEST_INVALID,
                "attestation does not authorize this exact passing promotion",
                "submit the exact component/version bound by a passing promotion attestation",
            )
        current = snapshot.stable_version(component)
        if subject.baseline_version != current:
            return self._fault(
                ControlCode.REGISTRY_STABLE_MOVED,
                f"attestation baseline {subject.baseline_version} differs from stable {current}",
                "re-evaluate against the current stable version",
            )
        return {
            "component": component,
            "version": str(version),
            "attestation_id": attestation_id,
            "baseline": str(current) if current else None,
        }

    def _apply_policy_promotion(
        self,
        *,
        plan: _InitialPromotionPlan | _RollbackPlan,
        actor_id: str,
        internal_fault: str | None = None,
    ) -> PromotionRecord | ControlRejected:
        prior = self._registry.store.promotion_for_attestation(plan.attestation_id)
        if prior is not None:
            self._validate_promotion_receipt(
                prior,
                component=plan.component,
                baseline=plan.baseline,
                target=plan.target,
                attestation_id=plan.attestation_id,
                draft=plan.draft,
            )
            return prior

        attestation = self._journal.mint_policy_attestation(plan.draft)
        if attestation.attestation_id != plan.attestation_id:
            raise JournalDamaged("policy attestation identity differs from its plan")
        if internal_fault is not None:
            self._fault_probe(internal_fault)

        prior = self._registry.store.promotion_for_attestation(plan.attestation_id)
        if prior is not None:
            self._validate_promotion_receipt(
                prior,
                component=plan.component,
                baseline=plan.baseline,
                target=plan.target,
                attestation_id=plan.attestation_id,
                draft=plan.draft,
            )
            return prior
        current = self._registry.stable_version(plan.component)
        if current != plan.baseline:
            prior = self._registry.store.promotion_for_attestation(plan.attestation_id)
            if prior is not None:
                self._validate_promotion_receipt(
                    prior,
                    component=plan.component,
                    baseline=plan.baseline,
                    target=plan.target,
                    attestation_id=plan.attestation_id,
                    draft=plan.draft,
                )
                return prior
            return _canonical_domain_rejection(plan)
        try:
            receipt = self._system._promote_version(
                component=plan.component,
                version=plan.target,
                attestation_id=plan.attestation_id,
                actor=actor_id,
            )
        except (AdmissionError, ContractViolation):
            prior = self._registry.store.promotion_for_attestation(plan.attestation_id)
            if prior is None:
                return _canonical_domain_rejection(plan)
            receipt = prior
        self._validate_promotion_receipt(
            receipt,
            component=plan.component,
            baseline=plan.baseline,
            target=plan.target,
            attestation_id=plan.attestation_id,
            draft=plan.draft,
        )
        return receipt

    def _validate_promotion_receipt(
        self,
        receipt: PromotionRecord,
        *,
        component: str,
        baseline: Digest | None,
        target: Digest,
        attestation_id: str,
        draft: AttestationDraft,
    ) -> None:
        if (
            receipt.component != component
            or receipt.channel != "stable"
            or receipt.from_version != baseline
            or receipt.to_version != target
            or receipt.attestation_id != attestation_id
            or receipt.source_run is not None
        ):
            raise JournalDamaged(
                f"promotion receipt {attestation_id!r} contradicts its planned edge"
            )
        attestation = self._journal.load_attestation(attestation_id)
        if attestation is None:
            raise JournalDamaged(f"promotion receipt {attestation_id!r} has no authority fact")
        if (
            attestation.action != draft.action
            or attestation.subject != draft.subject
            or not _same_json_fact(attestation.checks, draft.checks)
            or attestation.check_set_hash != draft.check_set_hash
            or attestation.evidence != draft.evidence
            or attestation.manifest_hash != draft.manifest_hash
            or attestation.workspace_id != draft.workspace_id
            or attestation.created_by_run is not None
        ):
            raise JournalDamaged(f"promotion attestation {attestation_id!r} contradicts its plan")

    def _validate_evaluated_promotion_receipt(
        self,
        receipt: PromotionRecord,
        *,
        plan: _PromotionPlan,
    ) -> None:
        attestation = self._journal.load_attestation(plan.attestation_id)
        if attestation is None:
            raise JournalDamaged(f"promotion receipt {plan.attestation_id!r} has no authority fact")
        subject = attestation.subject
        if (
            receipt.component != plan.component
            or receipt.channel != "stable"
            or receipt.from_version != plan.baseline
            or receipt.to_version != plan.target
            or receipt.attestation_id != plan.attestation_id
            or receipt.source_run != attestation.created_by_run
            or attestation.action != "promote"
            or not isinstance(subject, ComponentProofSubject)
            or subject.component != plan.component
            or subject.version != plan.target
            or subject.baseline_version != plan.baseline
            or not attestation.ok
        ):
            raise JournalDamaged(
                f"promotion receipt {plan.attestation_id!r} contradicts its planned edge"
            )

    @staticmethod
    def _object(mapping: Mapping[str, Any], key: str) -> dict[str, Any]:
        value = mapping.get(key)
        if not isinstance(value, dict):
            raise JournalDamaged(f"command plan field {key!r} is not an object")
        return value

    @staticmethod
    def _string(mapping: Mapping[str, Any], key: str) -> str:
        value = mapping.get(key)
        if not isinstance(value, str):
            raise JournalDamaged(f"command plan field {key!r} is not a string")
        return value

    @staticmethod
    def _optional_nonnegative_int(mapping: Mapping[str, Any], key: str) -> int | None:
        if key not in mapping:
            return None
        value = mapping[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise JournalDamaged(f"command plan field {key!r} is not a non-negative integer")
        return value

    @staticmethod
    def _optional_digest(value: Any) -> Digest | None:
        return Digest(value) if isinstance(value, str) else None

    def _authorize(
        self,
        actor: AuthenticatedActor,
        required_scope: str | frozenset[str],
    ) -> ControlRejected | None:
        return scope_refusal(actor, required_scope)

    def _decode_response(
        self,
        value: JsonValue,
        models: tuple[type[BaseModel], ...],
        actor: AuthenticatedActor,
    ) -> BaseModel:
        failures: list[str] = []
        for model in models:
            try:
                decoded = model.model_validate(value)
            except ValidationError as exc:
                failures.append(f"{model.__name__}: {exc.error_count()}")
                continue
            if not _same_json_fact(value, decoded.model_dump(mode="json")):
                failures.append(f"{model.__name__}: current response parsing is not lossless")
                continue
            return decoded
        for model in models:
            upgraded = self._normalize_legacy_response(value, model, actor)
            if upgraded is None:
                continue
            try:
                decoded = model.model_validate(upgraded)
            except ValidationError as exc:
                failures.append(f"{model.__name__} normalized: {exc.error_count()}")
                continue
            if not _same_json_fact(upgraded, decoded.model_dump(mode="json")):
                failures.append(
                    f"{model.__name__} normalized: response parsing is not lossless"
                )
                continue
            return decoded
        raise JournalDamaged(
            f"stored command response matches none of the operation models: {failures}"
        )

    def _normalize_legacy_response(
        self,
        value: JsonValue,
        model: type[BaseModel],
        actor: AuthenticatedActor,
    ) -> dict[str, JsonValue] | None:
        """Upgrade durable v1/v2 responses without rewriting their ledger row."""

        if not isinstance(value, dict) or value.get("schema_version") not in {1, 2}:
            return None
        supported = {
            RunSubmission,
            CancellationResult,
            ApprovalCommandResult,
            PromotionCommandResult,
            ControlRejected,
        }
        if model not in supported:
            return None
        upgraded = dict(value)
        upgraded["schema_version"] = 3
        if model is RunSubmission:
            # v1 exposed a mutable URI-only status_ref. Status lives at
            # runs_status in v2, so replay intentionally drops that field.
            upgraded.pop("status_ref", None)
        elif model is ApprovalCommandResult:
            approval_id = upgraded.get("approval_id")
            if not isinstance(approval_id, str):
                return None
            upgraded["detail"] = self._details.required_reference(
                actor, DetailAddress.approval(approval_id)
            ).model_dump(mode="json")
        elif model is PromotionCommandResult:
            component = upgraded.get("component")
            to_version = upgraded.get("to_version")
            if not isinstance(component, str) or not isinstance(to_version, str):
                return None
            try:
                version = Digest(to_version)
            except ValidationError:
                return None
            upgraded["detail"] = self._details.required_reference(
                actor, DetailAddress.component(component, version)
            ).model_dump(mode="json")
        return upgraded

    @staticmethod
    def _mark_replayed(value: BaseModel) -> BaseModel:
        command = getattr(value, "command", None)
        if isinstance(command, CommandMeta):
            return value.model_copy(
                update={"command": command.model_copy(update={"replayed": True})}
            )
        return value

    @staticmethod
    def _fault(
        code: ControlCode,
        message: str,
        repair: str,
        details: dict[str, JsonValue] | None = None,
    ) -> ControlRejected:
        return ControlRejected.one_fault(code, message, repair, details)
