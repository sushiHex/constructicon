"""Private durable command executor and typed command law (M6.2).

MCP is one adapter. Every mutation follows the same law:
Authorize -> Claim -> Plan -> Apply once -> Record -> replay after loss.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal, TypeVar, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from constructicon.api.cursor import CursorCodec
from constructicon.api.detail import DetailAddress, DetailResolver
from constructicon.api.run_host import LaunchDisposition, RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.admission import AdmissionRejected
from constructicon.core.component import ComponentDef, PromotionRecord
from constructicon.core.control import (
    ADMIN_SCOPE,
    APPROVE_SCOPE,
    OPERATE_SCOPE,
    PROMOTE_SCOPE,
    ApprovalCommandResult,
    AuthenticatedActor,
    CancellationResult,
    CommandClaim,
    CommandMeta,
    CommandRecord,
    ControlCode,
    ControlRejected,
    ControlStore,
    PromotionCommandResult,
    RegistrationCommandResult,
    ResolutionLock,
    ResolutionPin,
    RunOrigin,
    RunSubmission,
    approval_id_for_command,
    run_id_for_command,
    validate_idempotency_key,
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
from constructicon.core.identity import Digest, JsonValue, canonical_json, digest, json_value
from constructicon.core.journal import Journal
from constructicon.core.manifest import ExecutionManifest, parse_manifest_json
from constructicon.core.registry import (
    RegistryStore,
    StoredVersion,
)
from constructicon.core.run import RunStatus
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
_RESUME_LAUNCH_STATUSES = frozenset(
    {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.FAILED, RunStatus.PARKED}
)

T = TypeVar("T", bound=BaseModel)


class _PlanModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class _SourceLock(_PlanModel):
    run_id: RunId
    manifest_hash: Digest
    input_hash: Digest
    source_graph_hash: Digest
    resolution_lock: ResolutionLock | None = None


class _RunCreationPlan(_PlanModel):
    kind: Literal["run_creation"] = "run_creation"
    run_id: RunId
    manifest: ExecutionManifest
    inputs: dict[str, JsonValue]
    origin: RunOrigin
    source_lock: _SourceLock | None = None


class _CancelPlan(_PlanModel):
    kind: Literal["cancel"] = "cancel"
    run_id: RunId
    observed_status: RunStatus
    outcome: Literal["cancel_requested", "already_terminal"]
    response_status: RunStatus


class _ResumePlan(_PlanModel):
    kind: Literal["resume"] = "resume"
    policy: Literal["resume-v1"] = "resume-v1"
    run_id: RunId
    baseline_event_seq: int = Field(ge=0)
    submitted_status: RunStatus


class _ApprovalPlan(_PlanModel):
    kind: Literal["approval"] = "approval"
    approval: ApprovalRecord


class _RegistrationPlan(_PlanModel):
    kind: Literal["registration"] = "registration"
    definition: ComponentDef
    content_hash: Digest
    candidate_timestamp: AwareDatetime
    row_origin: Literal["existing", "canonical_new"]


class _InitialPromotionPlan(_PlanModel):
    kind: Literal["initial_promotion"] = "initial_promotion"
    component: str
    baseline: None = None
    target: Digest
    draft: AttestationDraft
    attestation_id: str


class _PromotionPlan(_PlanModel):
    kind: Literal["promotion"] = "promotion"
    component: str
    baseline: Digest | None
    target: Digest
    attestation_id: str


class _RollbackPlan(_PlanModel):
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


_CommandPlan = Annotated[
    _RunCreationPlan
    | _CancelPlan
    | _ResumePlan
    | _ApprovalPlan
    | _RegistrationPlan
    | _InitialPromotionPlan
    | _PromotionPlan
    | _RollbackPlan
    | _AdmissionRejectPlan
    | _ControlRejectPlan,
    Field(discriminator="kind"),
]


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
        return plan

    def load(self) -> _CommandPlan:
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
        store: ControlStore,
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
                _RunCreationPlan(
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
        if not isinstance(plan, _RunCreationPlan):
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
        terminal = record.status in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.PARKED,
        }
        if session.record.plan is None:
            session.plan(
                _CancelPlan(
                    run_id=run_id,
                    observed_status=record.status,
                    outcome=("already_terminal" if terminal else "cancel_requested"),
                    response_status=record.status,
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
        record = self._journal.run_record(run_id)
        if record is None:
            return self._terminal_control_fault(
                claim,
                ControlCode.RUN_UNKNOWN,
                f"unknown run {run_id!r}",
                "use a RunId returned by a Constructicon run mutation",
            )
        if session.record.plan is None:
            session.plan(
                _ResumePlan(
                    run_id=run_id,
                    baseline_event_seq=self._journal.max_event_seq(run_id),
                    submitted_status=record.status,
                )
            )
        plan = session.load()
        if isinstance(plan, _ControlRejectPlan):
            return self._terminal_rejection(claim, plan.response)
        if not isinstance(plan, _ResumePlan) or plan.run_id != run_id:
            raise JournalDamaged("runs_resume command carries the wrong plan")
        if self._resume_attempt_started(
            run_id,
            baseline_event_seq=plan.baseline_event_seq,
            command_id=claim.command_id,
        ):
            self._fault_probe("runs_resume.after_domain_mutation")
            response = RunSubmission(
                run_id=run_id,
                run_status=plan.submitted_status,
                command=CommandMeta(command_id=claim.command_id, replayed=False),
                origin=record.origin,
            )
            self._complete_command(claim, response)
            return response
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
        disposition = self._launch_resume(
            run_id,
            expected_event_seq=plan.baseline_event_seq,
            command_id=claim.command_id,
        )
        if disposition == "superseded":
            return self._terminal_control_fault(
                claim,
                ControlCode.RUN_NOT_RESUMABLE,
                f"resume intent for {run_id!r} was superseded at its attempt fence",
                "submit a new resume command after refreshing run status",
                {"reason": "attempt_superseded"},
            )
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
    ) -> ApprovalCommandResult | ControlRejected:
        begun = self._begin_command(
            actor,
            required_scope=APPROVE_SCOPE,
            operation="runs_approve",
            idempotency_key=idempotency_key,
            request={
                "run_id": str(run_id),
                "subject": subject.model_dump(mode="json"),
                "decision": decision,
                "reason": reason,
            },
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
            session.plan(_ApprovalPlan(approval=approval))
        plan = session.load()
        if isinstance(plan, _ControlRejectPlan):
            return self._terminal_rejection(claim, plan.response)
        if not isinstance(plan, _ApprovalPlan):
            raise JournalDamaged("runs_approve command carries the wrong plan")
        approval = plan.approval
        self._store.store_approval(claim, approval)
        self._fault_probe("runs_approve.after_domain_mutation")
        response = ApprovalCommandResult(
            approval_id=approval.approval_id,
            decision=approval.decision,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
            detail=self._details.required_reference(
                actor, DetailAddress.approval(approval.approval_id)
            ),
        )
        self._complete_command(claim, response)
        return response

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
                return self._terminal_control_fault(
                    claim,
                    ControlCode.REGISTRY_STABLE_MOVED,
                    "stable already names the target but not through this attestation",
                    "choose a fresh idempotency key after inspecting promotion history",
                )
            if current != plan.baseline:
                return self._terminal_control_fault(
                    claim,
                    ControlCode.REGISTRY_STABLE_MOVED,
                    f"stable moved from planned baseline {plan.baseline} to {current}",
                    "re-evaluate the candidate against the current stable version",
                )
            try:
                record = self._system._promote_version(
                    component=plan.component,
                    version=plan.target,
                    attestation_id=plan.attestation_id,
                    actor=actor.actor_id,
                )
            except (AdmissionError, ContractViolation) as exc:
                prior = self._registry.store.promotion_for_attestation(plan.attestation_id)
                if prior is None:
                    return self._terminal_control_fault(
                        claim,
                        ControlCode.REGISTRY_STABLE_MOVED,
                        str(exc),
                        "inspect the attestation and current stable version",
                    )
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
                _RunCreationPlan(
                    run_id=run_id,
                    manifest=manifest,
                    inputs=source_inputs,
                    origin=origin,
                    source_lock=_SourceLock(
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
        if not isinstance(plan, _RunCreationPlan):
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
        required_scope: str,
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
        request_hash = digest("control-request", 1, normalized)
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
            session.plan(planned)
        else:
            existing = self._load_stored_plan(claim, record.plan)
            if (
                isinstance(existing, (_AdmissionRejectPlan, _ControlRejectPlan))
                and existing.response != response
            ):
                raise JournalDamaged(f"command {claim.command_id!r} rejection contradicts its plan")
        session.reject(cast(ControlRejected | AdmissionRejected, response))
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
        except ValidationError as exc:
            raise JournalDamaged(
                f"command {claim.command_id!r} has an invalid typed plan: {exc}"
            ) from exc
        rendered = parsed.model_dump(mode="json")
        if canonical_json(raw) != canonical_json(rendered):
            raise JournalDamaged(f"command {claim.command_id!r} typed plan is not lossless")
        expected: dict[str, tuple[type[_PlanModel], ...]] = {
            "runs_start": (_RunCreationPlan, _AdmissionRejectPlan, _ControlRejectPlan),
            "runs_cancel": (_CancelPlan, _ControlRejectPlan),
            "runs_resume": (_ResumePlan, _ControlRejectPlan),
            "runs_reproduce": (_RunCreationPlan, _ControlRejectPlan),
            "runs_counterfactual": (_RunCreationPlan, _ControlRejectPlan),
            "runs_approve": (_ApprovalPlan, _ControlRejectPlan),
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
    ) -> _CommandPlan:
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
                return _RunCreationPlan(
                    run_id=RunId(self._string(raw, "run_id")),
                    manifest=ExecutionManifest.model_validate(self._object(raw, "manifest")),
                    inputs=legacy_inputs,
                    origin=RunOrigin.model_validate(self._object(raw, "origin")),
                )
            if operation == "runs_resume":
                run_id = RunId(self._string(raw, "run_id"))
                run = self._journal.run_record(run_id)
                if run is None:
                    raise JournalDamaged("legacy resume run disappeared")
                resume_baseline = self._optional_nonnegative_int(raw, "baseline_event_seq")
                if resume_baseline is None:
                    resume_baseline = self._journal.max_event_seq(run_id)
                return _ResumePlan(
                    run_id=run_id,
                    baseline_event_seq=resume_baseline,
                    submitted_status=run.status,
                )
            if operation == "runs_approve":
                return _ApprovalPlan(
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
        plan: _CommandPlan,
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

        if isinstance(plan, _RunCreationPlan):
            if plan.run_id != run_id_for_command(claim.command_id):
                raise JournalDamaged("run creation plan has a non-derived RunId")
            try:
                parsed_manifest = parse_manifest_json(
                    canonical_json(plan.manifest.model_dump(mode="json"))
                )
            except (TypeError, ValueError, ValidationError) as exc:
                raise JournalDamaged(f"run creation plan has an invalid manifest: {exc}") from exc
            if parsed_manifest != plan.manifest:
                raise JournalDamaged("run creation plan manifest parsing is lossy")
            if digest("inputs", 1, plan.inputs) != plan.manifest.input_hash:
                raise JournalDamaged("run creation inputs contradict the manifest input hash")
            origin = plan.origin
            if origin.actor_id != record.actor.actor_id or origin.command_id != claim.command_id:
                raise JournalDamaged("run origin contradicts its command actor or identity")
            if claim.operation == "runs_start":
                proposal = request.get("proposal")
                inputs = request.get("inputs")
                try:
                    graph = (
                        Graph.model_validate_json(proposal)
                        if isinstance(proposal, str)
                        else Graph.model_validate(proposal)
                    )
                except (TypeError, ValueError, ValidationError) as exc:
                    raise JournalDamaged(
                        f"stored start request is not a valid graph: {exc}"
                    ) from exc
                if (
                    plan.source_lock is not None
                    or graph != plan.manifest.source_graph
                    or inputs != plan.inputs
                    or origin
                    != RunOrigin(
                        kind="start",
                        actor_id=record.actor.actor_id,
                        command_id=claim.command_id,
                    )
                ):
                    raise JournalDamaged("start plan contradicts its canonical request")
                return
            if claim.operation not in {"runs_reproduce", "runs_counterfactual"}:
                raise JournalDamaged("run creation plan belongs to another operation")
            source_value = request.get("source_run_id")
            if not isinstance(source_value, str):
                raise JournalDamaged("clone request has no exact source RunId")
            source_run_id = RunId(source_value)
            raw_overrides = request.get("overrides")
            if not isinstance(raw_overrides, dict) or not all(
                isinstance(name, str) and isinstance(value, str)
                for name, value in raw_overrides.items()
            ):
                raise JournalDamaged("clone request has invalid overrides")
            overrides = {name: Digest(value) for name, value in raw_overrides.items()}
            expected_origin = RunOrigin(
                kind=(
                    "counterfactual" if claim.operation == "runs_counterfactual" else "reproduce"
                ),
                actor_id=record.actor.actor_id,
                command_id=claim.command_id,
                source_run_id=source_run_id,
                overrides=(overrides if claim.operation == "runs_counterfactual" else {}),
                effects=("simulated" if claim.operation == "runs_counterfactual" else "live"),
                capabilities=("discard" if claim.operation == "runs_counterfactual" else "normal"),
            )
            if origin != expected_origin:
                raise JournalDamaged("clone origin contradicts its canonical request")
            source_record = self._journal.run_record(source_run_id)
            if source_record is None:
                raise JournalDamaged("clone source run disappeared")
            source_manifest = self._system.manifest_for_run(source_run_id)
            source_inputs = self._system.inputs_for_run(source_run_id)
            if (
                plan.inputs != source_inputs
                or plan.manifest.source_graph != source_manifest.source_graph
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
                    or plan.manifest != source_manifest
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

        if isinstance(plan, (_CancelPlan, _ResumePlan)):
            if request.get("run_id") != str(plan.run_id):
                raise JournalDamaged("run command plan targets another RunId")
            return

        if isinstance(plan, _ApprovalPlan):
            approval = plan.approval
            if (
                request.get("run_id") != str(approval.run_id)
                or request.get("subject") != approval.subject.model_dump(mode="json")
                or request.get("decision") != approval.decision
                or request.get("reason") != approval.reason
                or approval.actor != record.actor
                or approval.approval_id
                != approval_id_for_command(claim.command_id, request.get("subject"))
            ):
                raise JournalDamaged("approval plan contradicts its canonical request")
            return

        if isinstance(plan, _RegistrationPlan):
            try:
                requested = ComponentDef.model_validate(request.get("definition"))
            except ValidationError as exc:
                raise JournalDamaged("registration request has an invalid definition") from exc
            if requested != plan.definition:
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
                    or existing.definition != plan.definition
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
                or plan.draft != expected.draft
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
            if plan.draft != expected.draft or plan.attestation_id != expected.attestation_id:
                raise JournalDamaged("rollback policy identity is invalid")
            return

        raise JournalDamaged("unknown command plan family")

    def _validate_terminal_response(
        self,
        record: CommandRecord,
        response: BaseModel,
    ) -> None:
        if record.plan is None:
            raise JournalDamaged("terminal command has no immutable plan")
        claim = CommandClaim(
            command_id=record.command_id,
            actor_id=record.actor.actor_id,
            operation=record.operation,
            owner_id=record.owner_id or "replay:terminal",
            epoch=max(1, record.owner_epoch),
            expires_at=record.updated_at,
        )
        plan = self._load_stored_plan(claim, record.plan)
        self._validate_command_plan(claim, plan)
        if isinstance(response, (AdmissionRejected, ControlRejected)):
            self._validate_terminal_rejection(record, plan, response)
            return

        command = getattr(response, "command", None)
        if (
            not isinstance(command, CommandMeta)
            or command.command_id != record.command_id
            or command.replayed
        ):
            raise JournalDamaged("successful response has invalid command metadata")

        if isinstance(response, RunSubmission):
            if isinstance(plan, _RunCreationPlan):
                if (
                    response.run_id != plan.run_id
                    or response.run_status is not RunStatus.PENDING
                    or response.origin != plan.origin
                ):
                    raise JournalDamaged("run submission contradicts its creation plan")
            elif isinstance(plan, _ResumePlan):
                run = self._journal.run_record(plan.run_id)
                if (
                    run is None
                    or response.run_id != plan.run_id
                    or response.run_status != plan.submitted_status
                    or response.origin != run.origin
                ):
                    raise JournalDamaged("resume response contradicts its attempt plan")
            else:
                raise JournalDamaged("run submission has the wrong plan family")
            if self._journal.run_record(response.run_id) is None:
                raise JournalDamaged("submitted run has no durable row")
            return
        if isinstance(response, CancellationResult):
            if (
                not isinstance(plan, _CancelPlan)
                or response.run_id != plan.run_id
                or response.status != plan.outcome
                or response.run_status != plan.response_status
            ):
                raise JournalDamaged("cancellation response contradicts its plan")
            return
        if isinstance(response, ApprovalCommandResult):
            if not isinstance(plan, _ApprovalPlan):
                raise JournalDamaged("approval response has the wrong plan")
            expected_detail = self._details.required_reference(
                record.actor,
                DetailAddress.approval(plan.approval.approval_id),
            )
            if (
                response.approval_id != plan.approval.approval_id
                or response.decision != plan.approval.decision
                or self._store.approval(response.approval_id) != plan.approval
                or response.detail != expected_detail
            ):
                raise JournalDamaged("approval response contradicts its plan or fact")
            return
        if isinstance(response, RegistrationCommandResult):
            if not isinstance(plan, _RegistrationPlan):
                raise JournalDamaged("registration response has the wrong plan")
            stored = self._registry.snapshot().get(
                plan.definition.name,
                plan.content_hash,
            )
            if (
                stored is None
                or stored.definition != plan.definition
                or response.component != plan.definition.name
                or response.version != plan.content_hash
                or response.detail
                != self._details.required_reference(
                    record.actor,
                    DetailAddress.component(plan.definition.name, plan.content_hash),
                )
            ):
                raise JournalDamaged("registration response contradicts its exact row")
            return
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
            return
        raise JournalDamaged("terminal response uses an unknown schema family")

    @staticmethod
    def _validate_terminal_rejection(
        record: CommandRecord,
        plan: _CommandPlan,
        response: AdmissionRejected | ControlRejected,
    ) -> None:
        """Bind a refusal to the only plan families that can lawfully emit it."""

        if isinstance(plan, _AdmissionRejectPlan):
            if record.operation != "runs_start" or response != plan.response:
                raise JournalDamaged("admission rejection contradicts its claimed command")
            return
        if isinstance(plan, _ControlRejectPlan):
            if response != plan.response:
                raise JournalDamaged("control rejection contradicts its claimed command")
            return
        if not isinstance(response, ControlRejected) or len(response.faults) != 1:
            raise JournalDamaged("domain plan carries an invalid terminal rejection")

        code = response.faults[0].code
        if record.operation == "runs_resume" and isinstance(plan, _ResumePlan):
            lawful = {
                ControlCode.RUN_LIVE_OWNER,
                ControlCode.RUN_TERMINAL,
                ControlCode.RUN_NOT_RESUMABLE,
            }
        elif (
            record.operation,
            type(plan),
        ) in {
            ("registry_promote_initial", _InitialPromotionPlan),
            ("registry_promote", _PromotionPlan),
            ("registry_rollback", _RollbackPlan),
        }:
            lawful = {ControlCode.REGISTRY_STABLE_MOVED}
        else:
            lawful = set()
        if code not in lawful:
            raise JournalDamaged(
                f"{record.operation!r} rejection is not lawful for its durable domain plan"
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
            allowed_statuses=_RESUME_LAUNCH_STATUSES,
            resume_command_id=command_id,
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
        if record.operation != "runs_resume" or record.state != "committed":
            raise JournalDamaged("committed resume scan returned a non-resume command")
        if record.response is None or record.plan is None:
            raise JournalDamaged("committed resume command lacks plan or response")
        request = record.request
        if not isinstance(request, dict) or not isinstance(request.get("run_id"), str):
            raise JournalDamaged("resume command request has no exact RunId")
        run_id = RunId(request["run_id"])

        raw_plan = record.plan
        if not isinstance(raw_plan, dict):
            raise JournalDamaged("resume command plan is not an object")
        if "schema_version" in raw_plan:
            try:
                stored = _StoredPlan.model_validate_json(canonical_json(raw_plan))
            except ValidationError as exc:
                raise JournalDamaged("committed resume plan is invalid") from exc
            if canonical_json(raw_plan) != canonical_json(stored.model_dump(mode="json")):
                raise JournalDamaged("committed resume plan is not lossless")
            if not isinstance(stored.plan, _ResumePlan):
                raise JournalDamaged("committed resume command carries another plan kind")
            plan = stored.plan
            baseline = plan.baseline_event_seq
            if plan.run_id != run_id:
                raise JournalDamaged("resume request and plan RunIds disagree")
        else:
            legacy_baseline = self._optional_nonnegative_int(
                raw_plan,
                "baseline_event_seq",
            )
            if legacy_baseline is None:
                return None
            baseline = legacy_baseline
            if RunId(self._string(raw_plan, "run_id")) != run_id:
                raise JournalDamaged("legacy resume request and plan RunIds disagree")

        decoded = self._decode_response(
            record.response,
            (RunSubmission,),
            record.actor,
        )
        if not isinstance(decoded, RunSubmission):
            raise JournalDamaged("committed resume response has the wrong family")
        if (
            decoded.run_id != run_id
            or decoded.command.command_id != record.command_id
            or decoded.command.replayed
        ):
            raise JournalDamaged("resume response contradicts its command or RunId")

        current_seq = self._journal.max_event_seq(run_id)
        if self._resume_attempt_started(
            run_id,
            baseline_event_seq=baseline,
            command_id=record.command_id,
            current_event_seq=current_seq,
        ):
            return None
        run = self._journal.run_record(run_id)
        if run is None:
            raise JournalDamaged("committed resume target disappeared")
        if current_seq != baseline or run.status not in _RESUME_LAUNCH_STATUSES:
            return None
        return (run_id, baseline, record.command_id)

    def _resume_attempt_started(
        self,
        run_id: RunId,
        *,
        baseline_event_seq: int,
        command_id: str,
        current_event_seq: int | None = None,
    ) -> bool:
        current = (
            self._journal.max_event_seq(run_id)
            if current_event_seq is None
            else current_event_seq
        )
        if current < baseline_event_seq:
            raise JournalDamaged("resume event sequence precedes its stored baseline")
        after = baseline_event_seq
        while after < current:
            events = self._journal.events(run_id, after_seq=after, limit=100)
            if not events:
                break
            for event in events:
                after = event.seq
                if (
                    event.kind in {"RunStarted", "RunResumed", "RunReclaimed"}
                    and event.payload is not None
                    and event.payload.get("resume_command_id") == command_id
                ):
                    return True
            if len(events) < 100:
                break
        return False

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
            return self._fault(
                ControlCode.REGISTRY_STABLE_MOVED,
                f"stable moved from planned {plan.baseline} to {current}",
                "inspect registry state and submit a new command key",
            )
        try:
            receipt = self._system._promote_version(
                component=plan.component,
                version=plan.target,
                attestation_id=plan.attestation_id,
                actor=actor_id,
            )
        except (AdmissionError, ContractViolation) as exc:
            prior = self._registry.store.promotion_for_attestation(plan.attestation_id)
            if prior is None:
                return self._fault(
                    ControlCode.REGISTRY_STABLE_MOVED,
                    str(exc),
                    "inspect registry state and submit a new command key",
                )
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
            or attestation.checks != draft.checks
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

    def _authorize(self, actor: AuthenticatedActor, required_scope: str) -> ControlRejected | None:
        if actor.allows(required_scope):
            return None
        return self._fault(
            ControlCode.AUTH_REQUIRED_SCOPE,
            f"actor {actor.actor_id!r} lacks required scope {required_scope!r}",
            f"authenticate with {required_scope} or constructicon:admin",
            {"required_scope": required_scope},
        )

    def _decode_response(
        self,
        value: JsonValue,
        models: tuple[type[BaseModel], ...],
        actor: AuthenticatedActor,
    ) -> BaseModel:
        failures: list[str] = []
        for model in models:
            try:
                return model.model_validate(value)
            except ValidationError as exc:
                failures.append(f"{model.__name__}: {exc.error_count()}")
        for model in models:
            upgraded = self._normalize_legacy_response(value, model, actor)
            if upgraded is None:
                continue
            try:
                return model.model_validate(upgraded)
            except ValidationError as exc:
                failures.append(f"{model.__name__} normalized: {exc.error_count()}")
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
