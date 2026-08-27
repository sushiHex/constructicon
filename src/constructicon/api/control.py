"""Transport-neutral durable control plane (M6).

MCP is one adapter. Every mutation follows the same law:
Authorize -> Claim -> Plan -> Apply once -> Record -> replay after loss.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, TypeVar
from urllib.parse import quote

from pydantic import BaseModel, TypeAdapter, ValidationError

from constructicon.api.cursor import CursorCodec, CursorFault
from constructicon.api.detail import DetailResolver
from constructicon.api.run_host import RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.admission import AdmissionRejected
from constructicon.core.control import (
    ADMIN_SCOPE,
    APPROVE_SCOPE,
    OPERATE_SCOPE,
    PROMOTE_SCOPE,
    READ_SCOPE,
    ApprovalCommandResult,
    AuthenticatedActor,
    CancellationResult,
    CommandClaim,
    CommandMeta,
    CommandRecord,
    CommandView,
    ComponentComparison,
    ControlCode,
    ControlFault,
    ControlRejected,
    ControlStore,
    DetailChunk,
    DetailRef,
    EventPage,
    EventSummary,
    NamePage,
    PageInfo,
    PromotionCommandResult,
    ResolutionLock,
    ResolutionPin,
    RunOrigin,
    RunPage,
    RunResultPreview,
    RunSubmission,
    RunSummary,
    VersionPage,
    VersionSummary,
    approval_id_for_command,
    run_id_for_command,
    validate_idempotency_key,
)
from constructicon.core.effect import ApprovalRecord, ComponentProofSubject, ProofSubject
from constructicon.core.envelope import utc_now
from constructicon.core.errors import AdmissionError, ContractViolation, JournalDamaged
from constructicon.core.graph import Graph
from constructicon.core.identity import Digest, JsonValue, canonical_json, digest, json_value
from constructicon.core.manifest import ExecutionManifest, parse_manifest_json
from constructicon.core.run import RunStatus

COMMAND_TTL_S = 30.0
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

T = TypeVar("T", bound=BaseModel)


class ControlPlane:
    def __init__(
        self,
        *,
        system: Constructicon,
        store: ControlStore,
        run_host: RunHost | None = None,
        owner_id: str | None = None,
        command_ttl_s: float = COMMAND_TTL_S,
        cursor_codec: CursorCodec | None = None,
    ) -> None:
        if command_ttl_s <= 0:
            raise ValueError("command_ttl_s must be positive")
        self.system = system
        self.store = store
        self.owner_id = owner_id or f"control:{system.owner_id}"
        self.command_ttl_s = command_ttl_s
        self.cursors = cursor_codec or CursorCodec()
        self.run_host = run_host or RunHost(system)
        self.details = DetailResolver(system=system, store=store, cursors=self.cursors)
        self.fault_probe: Callable[[str], None] = lambda name: None

    # -- read surface -----------------------------------------------------

    def whoami(self, actor: AuthenticatedActor) -> AuthenticatedActor:
        return actor

    def system_describe(
        self,
        actor: AuthenticatedActor,
        *,
        component_names: Sequence[str] | None = None,
        limit: int = 100,
    ) -> BaseModel | ControlRejected:
        denied = self._authorize(actor, READ_SCOPE)
        if denied:
            return denied
        return self.system.describe(component_names=component_names, limit=limit)

    def graphs_validate(
        self,
        actor: AuthenticatedActor,
        proposal: Graph | Mapping[str, Any] | str,
        inputs: Mapping[str, Any],
    ) -> BaseModel | ControlRejected:
        denied = self._authorize(actor, READ_SCOPE)
        if denied:
            return denied
        return self.system.admit_graph(proposal, inputs)

    def runs_status(
        self, actor: AuthenticatedActor, run_id: RunId
    ) -> RunSummary | ControlRejected:
        denied = self._authorize(actor, READ_SCOPE)
        if denied:
            return denied
        record = self.system.journal.run_record(run_id)
        if record is None:
            return self._fault(
                ControlCode.RUN_UNKNOWN,
                f"unknown run {run_id!r}",
                "use a RunId returned by runs_start, runs_reproduce, or runs_counterfactual",
            )
        return self._run_summary(record)

    def runs_list(
        self,
        actor: AuthenticatedActor,
        *,
        statuses: tuple[RunStatus, ...] | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> RunPage | ControlRejected:
        denied = self._authorize(actor, READ_SCOPE)
        if denied:
            return denied
        invalid = self._limit_fault(limit)
        if invalid:
            return invalid
        query: JsonValue = {
            "statuses": [status.value for status in statuses] if statuses else None
        }
        after: tuple[str, str] | None = None
        if cursor is None:
            upper = self.system.journal.latest_run_key(statuses=statuses)
        else:
            decoded = self._decode_cursor(
                actor, cursor, kind="runs", query=query
            )
            if isinstance(decoded, ControlRejected):
                return decoded
            upper = self._pair(decoded.upper_bound)
            after = self._pair(decoded.last_key)
        if upper is None:
            return RunPage(
                items=(),
                page=PageInfo(
                    next_cursor=None,
                    snapshot_digest=digest("run-page", 1, {"query": query, "upper": None}),
                    count=0,
                ),
            )
        records = self.system.journal.run_records(
            statuses=statuses,
            after=after,
            through=upper,
            limit=limit + 1,
        )
        has_more = len(records) > limit
        visible = records[:limit]
        next_cursor = None
        if has_more and visible:
            last = visible[-1]
            next_cursor = self.cursors.encode(
                actor_id=actor.actor_id,
                kind="runs",
                query=query,
                upper_bound=list(upper),
                last_key=[last.created_at.isoformat(), str(last.run_id)],
            )
        return RunPage(
            items=tuple(self._run_summary(record) for record in visible),
            page=PageInfo(
                next_cursor=next_cursor,
                snapshot_digest=digest(
                    "run-page", 1, {"query": query, "upper": list(upper)}
                ),
                count=len(visible),
            ),
        )

    def runs_events(
        self,
        actor: AuthenticatedActor,
        run_id: RunId,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> EventPage | ControlRejected:
        denied = self._authorize(actor, READ_SCOPE)
        if denied:
            return denied
        invalid = self._limit_fault(limit)
        if invalid:
            return invalid
        if self.system.journal.run_record(run_id) is None:
            return self._fault(
                ControlCode.RUN_UNKNOWN,
                f"unknown run {run_id!r}",
                "use a RunId returned by a Constructicon run mutation",
            )
        query: JsonValue = {"run_id": str(run_id)}
        if cursor is None:
            through = self.system.journal.max_event_seq(run_id)
            after_seq = 0
        else:
            decoded = self._decode_cursor(
                actor, cursor, kind="run-events", query=query
            )
            if isinstance(decoded, ControlRejected):
                return decoded
            if not isinstance(decoded.upper_bound, int) or not isinstance(
                decoded.last_key, int
            ):
                return self._cursor_shape_fault()
            through = decoded.upper_bound
            after_seq = decoded.last_key
        events = [
            event
            for event in self.system.journal.events(
                run_id, after_seq=after_seq, limit=limit + 1
            )
            if event.seq <= through
        ]
        has_more = len(events) > limit
        visible = events[:limit]
        next_cursor = None
        if has_more and visible:
            next_cursor = self.cursors.encode(
                actor_id=actor.actor_id,
                kind="run-events",
                query=query,
                upper_bound=through,
                last_key=visible[-1].seq,
            )
        items = tuple(
            EventSummary(
                run_id=event.run_id,
                seq=event.seq,
                kind=event.kind,
                path=event.path.render() if event.path else None,
                created_at=event.created_at,
                payload=(json_value(event.payload) if event.payload is not None else None),  # type: ignore[arg-type]
                detail=self._event_ref(run_id, event.seq),
            )
            for event in visible
        )
        return EventPage(
            run_id=run_id,
            items=items,
            through_seq=through,
            page=PageInfo(
                next_cursor=next_cursor,
                snapshot_digest=digest(
                    "event-page", 1, {"run_id": str(run_id), "through": through}
                ),
                count=len(items),
            ),
        )

    def runs_result(
        self, actor: AuthenticatedActor, run_id: RunId
    ) -> RunResultPreview | ControlRejected:
        denied = self._authorize(actor, READ_SCOPE)
        if denied:
            return denied
        record = self.system.journal.run_record(run_id)
        if record is None:
            return self._fault(
                ControlCode.RUN_UNKNOWN,
                f"unknown run {run_id!r}",
                "use a RunId returned by a Constructicon run mutation",
            )
        outputs: dict[str, JsonValue] = {}
        if record.status is RunStatus.SUCCEEDED:
            materialized = json_value(self.system.materialize_run(run_id))
            if isinstance(materialized, dict):
                outputs = self._bounded_mapping(materialized)
        failures: dict[str, str] = {}
        for event in self.system.journal.events(run_id, after_seq=0, limit=1_000):
            if event.kind == "NodeFailed" and event.path and event.payload:
                failures[event.path.render()] = str(event.payload.get("error", "failed"))
        return RunResultPreview(
            run_id=run_id,
            status=record.status,
            outputs=outputs,
            failures=dict(list(sorted(failures.items()))[:20]),
            detail=self._result_ref(run_id),
        )

    def commands_status(
        self, actor: AuthenticatedActor, command_id: str
    ) -> CommandView | ControlRejected:
        denied = self._authorize(actor, READ_SCOPE)
        if denied:
            return denied
        record = self.store.command(command_id)
        if record is None:
            return self._fault(
                ControlCode.COMMAND_UNKNOWN,
                f"unknown command {command_id!r}",
                "use a command_id returned by a mutating control operation",
            )
        if record.actor.actor_id != actor.actor_id and not actor.allows(ADMIN_SCOPE):
            return self._fault(
                ControlCode.AUTH_REQUIRED_SCOPE,
                "command records are visible only to their actor or an administrator",
                "authenticate as the command actor or request constructicon:admin",
            )
        return CommandView(record=record, detail=self._command_ref(command_id))

    def registry_versions(
        self,
        actor: AuthenticatedActor,
        component: str,
        *,
        candidates_only: bool = False,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> VersionPage | ControlRejected:
        denied = self._authorize(actor, READ_SCOPE)
        if denied:
            return denied
        invalid = self._limit_fault(limit)
        if invalid:
            return invalid
        snapshot = self.system.registry.snapshot()
        if component not in snapshot.versions:
            return self._fault(
                ControlCode.REGISTRY_VERSION_UNKNOWN,
                f"unknown component {component!r}",
                "choose a component returned by system_describe",
            )
        all_versions = list(snapshot.order.get(component, ()))
        if candidates_only:
            stable = snapshot.stable.get(component)
            all_versions = [version for version in all_versions if version != stable]
        query: JsonValue = {
            "component": component,
            "candidates_only": candidates_only,
        }
        if cursor is None:
            upper = len(all_versions)
            offset = 0
        else:
            decoded = self._decode_cursor(
                actor, cursor, kind="registry-versions", query=query
            )
            if isinstance(decoded, ControlRejected):
                return decoded
            if not isinstance(decoded.upper_bound, int) or not isinstance(
                decoded.last_key, int
            ):
                return self._cursor_shape_fault()
            upper, offset = decoded.upper_bound, decoded.last_key
        bounded = all_versions[:upper]
        visible_hashes = bounded[offset : offset + limit]
        next_offset = offset + len(visible_hashes)
        next_cursor = None
        if next_offset < len(bounded):
            next_cursor = self.cursors.encode(
                actor_id=actor.actor_id,
                kind="registry-versions",
                query=query,
                upper_bound=upper,
                last_key=next_offset,
            )
        items: list[VersionSummary] = []
        stable = snapshot.stable.get(component)
        for version_text in visible_hashes:
            stored = snapshot.versions[component][version_text]
            version = Digest(version_text)
            items.append(
                VersionSummary(
                    component=component,
                    version=version,
                    stable=version_text == stable,
                    registered_at=stored.registered_at,
                    detail=self._component_ref(component, version),
                )
            )
        return VersionPage(
            component=component,
            items=tuple(items),
            page=PageInfo(
                next_cursor=next_cursor,
                snapshot_digest=digest(
                    "version-page", 1, {"query": query, "upper": bounded}
                ),
                count=len(items),
            ),
        )

    def registry_candidates(
        self,
        actor: AuthenticatedActor,
        component: str,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> VersionPage | ControlRejected:
        return self.registry_versions(
            actor,
            component,
            candidates_only=True,
            cursor=cursor,
            limit=limit,
        )

    def registry_rdeps(
        self,
        actor: AuthenticatedActor,
        component: str,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> NamePage | ControlRejected:
        denied = self._authorize(actor, READ_SCOPE)
        if denied:
            return denied
        invalid = self._limit_fault(limit)
        if invalid:
            return invalid
        names = self.system.rdeps(component)
        query: JsonValue = {"component": component}
        if cursor is None:
            upper = len(names)
            offset = 0
        else:
            decoded = self._decode_cursor(actor, cursor, kind="registry-rdeps", query=query)
            if isinstance(decoded, ControlRejected):
                return decoded
            if not isinstance(decoded.upper_bound, int) or not isinstance(
                decoded.last_key, int
            ):
                return self._cursor_shape_fault()
            upper, offset = decoded.upper_bound, decoded.last_key
        bounded = names[:upper]
        visible = bounded[offset : offset + limit]
        next_offset = offset + len(visible)
        next_cursor = None
        if next_offset < len(bounded):
            next_cursor = self.cursors.encode(
                actor_id=actor.actor_id,
                kind="registry-rdeps",
                query=query,
                upper_bound=upper,
                last_key=next_offset,
            )
        return NamePage(
            kind="reverse_dependencies",
            items=tuple(visible),
            page=PageInfo(
                next_cursor=next_cursor,
                snapshot_digest=digest("rdeps-page", 1, {"items": bounded}),
                count=len(visible),
            ),
        )

    def registry_compare(
        self,
        actor: AuthenticatedActor,
        component: str,
        left: Digest,
        right: Digest,
    ) -> ComponentComparison | ControlRejected:
        denied = self._authorize(actor, READ_SCOPE)
        if denied:
            return denied
        snapshot = self.system.registry.snapshot()
        left_stored = snapshot.get(component, left)
        right_stored = snapshot.get(component, right)
        if left_stored is None or right_stored is None:
            return self._fault(
                ControlCode.REGISTRY_VERSION_UNKNOWN,
                f"comparison requires two retained versions of {component!r}",
                "choose exact versions returned by registry_versions",
            )
        a = left_stored.definition
        b = right_stored.definition
        changes: dict[str, JsonValue] = {}
        pairs = {
            "role": (a.role, b.role),
            "body_kind": (
                "composite" if isinstance(a.body, Graph) else "atomic",
                "composite" if isinstance(b.body, Graph) else "atomic",
            ),
            "inputs": (
                [port.model_dump(mode="json") for port in a.inputs],
                [port.model_dump(mode="json") for port in b.inputs],
            ),
            "outputs": (
                [port.model_dump(mode="json") for port in a.outputs],
                [port.model_dump(mode="json") for port in b.outputs],
            ),
            "capability_requirements": (
                [item.model_dump(mode="json") for item in (a.capability_requirements or ())],
                [item.model_dump(mode="json") for item in (b.capability_requirements or ())],
            ),
            "learning": (
                a.metadata.learning.model_dump(mode="json") if a.metadata.learning else None,
                b.metadata.learning.model_dump(mode="json") if b.metadata.learning else None,
            ),
            "implementation_digest": (
                None if isinstance(a.body, Graph) else str(a.body.source_digest),
                None if isinstance(b.body, Graph) else str(b.body.source_digest),
            ),
        }
        for name, (before, after) in pairs.items():
            if before != after:
                changes[name] = {"before": json_value(before), "after": json_value(after)}
        return ComponentComparison(
            component=component,
            left=left,
            right=right,
            changes=changes,
            reverse_dependencies=tuple(self.system.rdeps(component)),
        )

    def details_read(
        self,
        actor: AuthenticatedActor,
        uri: str,
        *,
        cursor: str | None = None,
        max_bytes: int = 16_000,
    ) -> DetailChunk | ControlRejected:
        denied = self._authorize(actor, READ_SCOPE)
        if denied:
            return denied
        return self.details.read(actor, uri, cursor=cursor, max_bytes=max_bytes)

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
                self.run_host.launch(begun.run_id)
            return begun
        claim = begun
        record = self._command_record(claim)
        if record.plan is None:
            admitted = self.system.admit_graph(proposal, inputs)
            if isinstance(admitted, AdmissionRejected):
                return self._terminal_rejection(claim, admitted)
            run_id = run_id_for_command(claim.command_id)
            origin = RunOrigin(
                kind="start",
                actor_id=actor.actor_id,
                command_id=claim.command_id,
            )
            plan: JsonValue = {
                "run_id": str(run_id),
                "manifest": admitted.manifest.model_dump(mode="json"),
                "inputs": json_value(dict(inputs)),
                "origin": origin.model_dump(mode="json"),
            }
            self.store.store_command_plan(claim, plan)
            self.fault_probe("runs_start.after_plan")
        plan = self._command_plan(claim)
        run_id = RunId(self._string(plan, "run_id"))
        manifest = ExecutionManifest.model_validate(self._object(plan, "manifest"))
        run_inputs = self._object(plan, "inputs")
        origin = RunOrigin.model_validate(self._object(plan, "origin"))
        self.system.prepare(manifest, run_id=run_id, inputs=run_inputs, origin=origin)
        self.fault_probe("runs_start.after_domain_mutation")
        response = self._submission(claim, run_id, origin)
        self.store.complete_command(claim, response.model_dump(mode="json"))
        self.run_host.launch(run_id)
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
            return begun
        claim = begun
        record = self.system.journal.run_record(run_id)
        if record is None:
            return self._terminal_control_fault(
                claim,
                ControlCode.RUN_UNKNOWN,
                f"unknown run {run_id!r}",
                "use a RunId returned by a Constructicon run mutation",
            )
        self._ensure_plan(claim, {"run_id": str(run_id)})
        terminal = record.status in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.PARKED,
        }
        if not terminal:
            self.system.cancel(run_id)
        self.fault_probe("runs_cancel.after_domain_mutation")
        latest = self.system.journal.run_record(run_id) or record
        response = CancellationResult(
            status="already_terminal" if terminal else "cancel_requested",
            run_id=run_id,
            run_status=latest.status,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
        )
        self.store.complete_command(claim, response.model_dump(mode="json"))
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
                self.run_host.launch(run_id)
            return begun
        claim = begun
        record = self.system.journal.run_record(run_id)
        if record is None:
            return self._terminal_control_fault(
                claim,
                ControlCode.RUN_UNKNOWN,
                f"unknown run {run_id!r}",
                "use a RunId returned by a Constructicon run mutation",
            )
        self._ensure_plan(claim, {"run_id": str(run_id)})
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
        response = self._submission(claim, run_id, record.origin)
        self.store.complete_command(claim, response.model_dump(mode="json"))
        self.run_host.launch(run_id)
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
            return begun
        claim = begun
        if decision not in {"approved", "rejected"}:
            return self._terminal_control_fault(
                claim,
                ControlCode.APPROVAL_INVALID_SUBJECT,
                f"unknown approval decision {decision!r}",
                "use 'approved' or 'rejected'",
            )
        if self.system.journal.run_record(run_id) is None:
            return self._terminal_control_fault(
                claim,
                ControlCode.RUN_UNKNOWN,
                f"unknown run {run_id!r}",
                "bind the decision to an existing run",
            )
        if self._command_record(claim).plan is None:
            approval_id = approval_id_for_command(
                claim.command_id, subject.model_dump(mode="json")
            )
            approval = ApprovalRecord(
                approval_id=approval_id,
                subject=subject,
                decision=decision,  # type: ignore[arg-type]
                reason=reason,
                actor=actor,
                run_id=run_id,
                created_at=utc_now(),
            )
            self.store.store_command_plan(
                claim,
                {"approval": approval.model_dump(mode="json")},
            )
            self.fault_probe("runs_approve.after_plan")
        approval = ApprovalRecord.model_validate(
            self._object(self._command_plan(claim), "approval")
        )
        self.store.store_approval(claim, approval)
        self.fault_probe("runs_approve.after_domain_mutation")
        response = ApprovalCommandResult(
            approval_id=approval.approval_id,
            decision=approval.decision,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
            detail=self._approval_ref(approval.approval_id),
        )
        self.store.complete_command(claim, response.model_dump(mode="json"))
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
            return begun
        claim = begun
        if self._command_record(claim).plan is None:
            planned = self._plan_promotion(component, version, attestation_id)
            if isinstance(planned, ControlRejected):
                return self._terminal_rejection(claim, planned)
            self.store.store_command_plan(claim, planned)
            self.fault_probe("registry_promote.after_plan")
        plan = self._command_plan(claim)
        baseline = self._optional_digest(plan.get("baseline"))
        current = self.system.registry.stable_version(component)
        if current == version:
            prior = self.system.registry.store.promotion_for_attestation(attestation_id)
            if prior is None:
                return self._terminal_control_fault(
                    claim,
                    ControlCode.REGISTRY_STABLE_MOVED,
                    "stable already names the target but not through this attestation",
                    "choose a fresh idempotency key after inspecting promotion history",
                )
            record = prior
        elif current != baseline:
            return self._terminal_control_fault(
                claim,
                ControlCode.REGISTRY_STABLE_MOVED,
                f"stable moved from planned baseline {baseline} to {current}",
                "re-evaluate the candidate against the current stable version",
            )
        else:
            try:
                record = self.system.promote(
                    component=component,
                    version=version,
                    attestation_id=attestation_id,
                    actor=actor.actor_id,
                )
            except (AdmissionError, ContractViolation) as exc:
                return self._terminal_control_fault(
                    claim,
                    ControlCode.REGISTRY_STABLE_MOVED,
                    str(exc),
                    "inspect the attestation and current stable version",
                )
        self.fault_probe("registry_promote.after_domain_mutation")
        response = PromotionCommandResult(
            status="promoted",
            component=component,
            from_version=record.from_version,
            to_version=record.to_version,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
            detail=self._component_ref(component, record.to_version),
        )
        self.store.complete_command(claim, response.model_dump(mode="json"))
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
            return begun
        claim = begun
        if self._command_record(claim).plan is None:
            snapshot = self.system.registry.snapshot()
            current = snapshot.stable_version(component)
            if current != expected_stable:
                return self._terminal_control_fault(
                    claim,
                    ControlCode.REGISTRY_STABLE_MOVED,
                    f"rollback expected {expected_stable}, found {current}",
                    "refresh registry state and submit a new command",
                )
            target: Digest | None = None
            for before, after in reversed(snapshot.history.get(component, ())):
                if after == str(expected_stable) and before is not None:
                    target = Digest(before)
                    break
            if target is None:
                return self._terminal_control_fault(
                    claim,
                    ControlCode.REGISTRY_VERSION_UNKNOWN,
                    f"component {component!r} has no prior stable target",
                    "rollback only after at least one evaluated promotion",
                )
            self.store.store_command_plan(
                claim,
                {
                    "component": component,
                    "expected_stable": str(expected_stable),
                    "target": str(target),
                },
            )
            self.fault_probe("registry_rollback.after_plan")
        plan = self._command_plan(claim)
        target = Digest(self._string(plan, "target"))
        current = self.system.registry.stable_version(component)
        if current == target:
            from_version = expected_stable
            to_version = target
        elif current != expected_stable:
            return self._terminal_control_fault(
                claim,
                ControlCode.REGISTRY_STABLE_MOVED,
                f"stable moved from planned {expected_stable} to {current}",
                "inspect registry state and submit a new rollback command",
            )
        else:
            try:
                record = self.system.rollback(
                    component=component,
                    actor=actor.actor_id,
                    expected_stable=expected_stable,
                )
            except (AdmissionError, ContractViolation) as exc:
                return self._terminal_control_fault(
                    claim,
                    ControlCode.REGISTRY_STABLE_MOVED,
                    str(exc),
                    "inspect registry state and retry with a new key",
                )
            from_version, to_version = record.from_version, record.to_version
        self.fault_probe("registry_rollback.after_domain_mutation")
        response = PromotionCommandResult(
            status="rolled_back",
            component=component,
            from_version=from_version,
            to_version=to_version,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
            detail=self._component_ref(component, to_version),
        )
        self.store.complete_command(claim, response.model_dump(mode="json"))
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
                self.run_host.launch(begun.run_id)
            return begun
        claim = begun
        if self._command_record(claim).plan is None:
            source_record = self.system.journal.run_record(source_run_id)
            if source_record is None:
                return self._terminal_control_fault(
                    claim,
                    ControlCode.RUN_UNKNOWN,
                    f"unknown source run {source_run_id!r}",
                    "choose an existing source run",
                )
            source_manifest = self.system.manifest_for_run(source_run_id)
            source_inputs = self.system.inputs_for_run(source_run_id)
            manifest = source_manifest
            mode = "live"
            capability_mode = "normal"
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
                snapshot = self.system.registry.snapshot()
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
                    manifest = self.system.validate(
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
                effects=mode,  # type: ignore[arg-type]
                capabilities=capability_mode,  # type: ignore[arg-type]
            )
            self.store.store_command_plan(
                claim,
                {
                    "run_id": str(run_id),
                    "manifest": manifest.model_dump(mode="json"),
                    "inputs": source_inputs,
                    "origin": origin.model_dump(mode="json"),
                },
            )
            self.fault_probe(f"{operation}.after_plan")
        plan = self._command_plan(claim)
        run_id = RunId(self._string(plan, "run_id"))
        manifest = ExecutionManifest.model_validate(self._object(plan, "manifest"))
        run_inputs = self._object(plan, "inputs")
        origin = RunOrigin.model_validate(self._object(plan, "origin"))
        self.system.prepare(manifest, run_id=run_id, inputs=run_inputs, origin=origin)
        self.fault_probe(f"{operation}.after_domain_mutation")
        response = self._submission(claim, run_id, origin)
        self.store.complete_command(claim, response.model_dump(mode="json"))
        self.run_host.launch(run_id)
        return response

    # -- command law ------------------------------------------------------

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
        result = self.store.claim_command(
            actor=actor,
            operation=operation,
            idempotency_key=key,
            request_hash=request_hash,
            request=normalized,
            owner_id=self.owner_id,
            ttl_s=self.command_ttl_s,
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
            decoded = self._decode_response(result.record.response, response_types)
            return self._mark_replayed(decoded)
        if result.claim is None:
            raise JournalDamaged("claimed command returned no fence")
        return result.claim

    def _ensure_plan(self, claim: CommandClaim, plan: JsonValue) -> JsonValue:
        record = self._command_record(claim)
        if record.plan is None:
            self.store.store_command_plan(claim, plan)
            self.fault_probe(f"{claim.operation}.after_plan")
            return plan
        return record.plan

    def _terminal_rejection(self, claim: CommandClaim, response: T) -> T:
        self._ensure_plan(claim, {"rejection": response.model_dump(mode="json")})
        self.store.reject_command(claim, response.model_dump(mode="json"))
        return response

    def _terminal_control_fault(
        self,
        claim: CommandClaim,
        code: ControlCode,
        message: str,
        repair: str,
        details: dict[str, JsonValue] | None = None,
    ) -> ControlRejected:
        return self._terminal_rejection(
            claim, self._fault(code, message, repair, details)
        )

    def _command_record(self, claim: CommandClaim) -> CommandRecord:
        record = self.store.command(claim.command_id)
        if record is None:
            raise JournalDamaged(f"claimed command {claim.command_id!r} disappeared")
        return record

    def _command_plan(self, claim: CommandClaim) -> dict[str, Any]:
        record = self._command_record(claim)
        if not isinstance(record.plan, dict):
            raise JournalDamaged(f"command {claim.command_id!r} has no object plan")
        return record.plan

    # -- helpers ----------------------------------------------------------

    def _submission(
        self,
        claim: CommandClaim,
        run_id: RunId,
        origin: RunOrigin | None,
    ) -> RunSubmission:
        record = self.system.journal.run_record(run_id)
        if record is None:
            raise JournalDamaged(f"planned run {run_id!r} was not durably created")
        return RunSubmission(
            run_id=run_id,
            run_status=record.status,
            command=CommandMeta(command_id=claim.command_id, replayed=False),
            origin=origin,
            status_ref=DetailRef(uri=f"constructicon://runs/{quote(str(run_id), safe='')}/result"),
        )

    def _plan_promotion(
        self,
        component: str,
        version: Digest,
        attestation_id: str,
    ) -> dict[str, JsonValue] | ControlRejected:
        snapshot = self.system.registry.snapshot()
        if snapshot.get(component, version) is None:
            return self._fault(
                ControlCode.REGISTRY_VERSION_UNKNOWN,
                f"component {component!r} has no retained version {version}",
                "choose a version returned by registry_versions",
            )
        attestation = self.system.journal.load_attestation(attestation_id)
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

    def _run_summary(self, record: Any) -> RunSummary:
        run_id = record.run_id
        return RunSummary(
            run_id=run_id,
            status=record.status,
            liveness=record.liveness,
            created_at=record.created_at,
            manifest_hash=record.manifest_hash,
            input_hash=record.input_hash,
            origin=record.origin,
            manifest_ref=self._manifest_ref(run_id),
            result_ref=self._result_ref(run_id),
        )

    @staticmethod
    def _bounded_mapping(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {}
        for key in sorted(value)[:20]:
            item = value[key]
            rendered = canonical_json(item)
            result[key] = item if len(rendered) <= 2_000 else {"truncated": True}
        return result

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
    def _optional_digest(value: Any) -> Digest | None:
        return Digest(value) if isinstance(value, str) else None

    @staticmethod
    def _pair(value: JsonValue | None) -> tuple[str, str] | None:
        if (
            isinstance(value, list)
            and len(value) == 2
            and all(isinstance(item, str) for item in value)
        ):
            return (value[0], value[1])
        return None

    def _authorize(
        self, actor: AuthenticatedActor, required_scope: str
    ) -> ControlRejected | None:
        if actor.allows(required_scope):
            return None
        return self._fault(
            ControlCode.AUTH_REQUIRED_SCOPE,
            f"actor {actor.actor_id!r} lacks required scope {required_scope!r}",
            f"authenticate with {required_scope} or constructicon:admin",
            {"required_scope": required_scope},
        )

    def _limit_fault(self, limit: int) -> ControlRejected | None:
        if 1 <= limit <= MAX_PAGE_SIZE:
            return None
        return self._fault(
            ControlCode.REQUEST_INVALID,
            f"page limit must be in 1..{MAX_PAGE_SIZE}; received {limit}",
            f"choose a limit in 1..{MAX_PAGE_SIZE}",
        )

    def _decode_cursor(
        self,
        actor: AuthenticatedActor,
        cursor: str,
        *,
        kind: str,
        query: JsonValue,
    ) -> Any | ControlRejected:
        try:
            return self.cursors.decode(
                cursor, actor_id=actor.actor_id, kind=kind, query=query
            )
        except CursorFault as exc:
            return self._fault(exc.code, exc.message, exc.repair)

    def _cursor_shape_fault(self) -> ControlRejected:
        return self._fault(
            ControlCode.CURSOR_INVALID,
            "cursor continuation shape is invalid",
            "restart the query without a cursor",
        )

    @staticmethod
    def _decode_response(
        value: JsonValue,
        models: tuple[type[BaseModel], ...],
    ) -> BaseModel:
        failures: list[str] = []
        for model in models:
            try:
                return model.model_validate(value)
            except ValidationError as exc:
                failures.append(f"{model.__name__}: {exc.error_count()}")
        raise JournalDamaged(
            f"stored command response matches none of the operation models: {failures}"
        )

    @staticmethod
    def _mark_replayed(value: BaseModel) -> BaseModel:
        command = getattr(value, "command", None)
        if isinstance(command, CommandMeta):
            return value.model_copy(
                update={
                    "command": command.model_copy(update={"replayed": True})
                }
            )
        return value

    @staticmethod
    def _fault(
        code: ControlCode,
        message: str,
        repair: str,
        details: dict[str, JsonValue] | None = None,
    ) -> ControlRejected:
        return ControlRejected(
            faults=(
                ControlFault(
                    code=code,
                    message=message,
                    repair=repair,
                    details=details or {},
                ),
            )
        )

    @staticmethod
    def _manifest_ref(run_id: RunId) -> DetailRef:
        return DetailRef(uri=f"constructicon://runs/{quote(str(run_id), safe='')}/manifest")

    @staticmethod
    def _result_ref(run_id: RunId) -> DetailRef:
        return DetailRef(uri=f"constructicon://runs/{quote(str(run_id), safe='')}/result")

    @staticmethod
    def _event_ref(run_id: RunId, seq: int) -> DetailRef:
        return DetailRef(
            uri=f"constructicon://runs/{quote(str(run_id), safe='')}/events/{seq}"
        )

    @staticmethod
    def _command_ref(command_id: str) -> DetailRef:
        return DetailRef(uri=f"constructicon://commands/{quote(command_id, safe='')}")

    @staticmethod
    def _approval_ref(approval_id: str) -> DetailRef:
        return DetailRef(uri=f"constructicon://approvals/{quote(approval_id, safe='')}")

    @staticmethod
    def _component_ref(component: str, version: Digest) -> DetailRef:
        return DetailRef(
            uri=(
                f"constructicon://components/{quote(component, safe='')}/"
                f"{quote(str(version), safe='')}"
            )
        )
