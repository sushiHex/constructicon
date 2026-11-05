"""A fixture-only issuer; only this leased adapter can mint the pilot proof."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.component import (
    CapabilityRequirement,
    ComponentDef,
    ComponentLineage,
    PythonRef,
)
from constructicon.core.control import ControlStore
from constructicon.core.effect import AttestationDraft, CheckResult, ComponentProofSubject
from constructicon.core.envelope import ArtifactRef
from constructicon.core.grants import Posture
from constructicon.core.graph import Connection, Graph, GraphNode, Ref
from constructicon.core.human import ApprovalDecisionPayload
from constructicon.core.identity import ActorId, Digest, canonical_json, digest
from constructicon.core.journal import Journal
from constructicon.core.manifest import (
    SELF_BINDING,
    SELF_CAPABILITY,
    ExecutionManifest,
    manifest_hash_for,
    source_graph_hash_for,
)
from constructicon.core.ports import Port
from constructicon.core.registry import RegistryStore
from constructicon.core.run import RunStatus
from constructicon.core.workspace import (
    AcquiredCapability,
    Disposition,
    LeaseClosure,
    LeaseContext,
    LeaseReconciliation,
    StaleAcquisition,
    acquisition_id_for,
    lease_id_for,
)
from constructicon.runtime.context import NodeContext
from constructicon.sdk.std import APPROVAL_CHANNEL, APPROVAL_COMPONENT, definitions
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.executors.fake import FakeExecutor
from tests.conftest import atomic
from tests.e2e import m9_evidence, m9_fixture
from tests.e2e.m9_evidence import (
    DIAGNOSTIC_PATH,
    PROPOSER,
    PROPOSER_PATH,
    Exam,
    project_case,
    proposer_definition,
    proposer_graph,
    read_projection,
)
from tests.e2e.m9_fixture import DEPENDENT, PROVIDER, REVISION, TARGET, Diagnosis

ISSUER = "test/m9-issuer"
ISSUER_CAP = "m9-issuer"
OPERATOR_ISSUER = "test/m9-operator-issuer"
OPERATOR_CHANNEL = "channel/m9-trial-approval"
OPERATOR_ISSUER_PATH = ExecutionPath(scope=ScopePath(segments=("m9-operator-issue", "issue")))
ISSUER_PATH = ExecutionPath(scope=ScopePath(segments=("m9-issue", "issue")))
APPROVAL = Port(name="approval", type_id="test/M9ApprovalId", schema_hash="m9-approval-v1")
PROOF = Port(name="proof", type_id="test/M9ProofId", schema_hash="m9-proof-v1")


@dataclass(frozen=True)
class Pair:
    source: RunId
    baseline: RunId
    candidate: RunId
    baseline_checkpoint: Digest
    candidate_checkpoint: Digest


def fixture_digest(executor: FakeExecutor) -> Digest:
    if type(executor) is not FakeExecutor:
        raise ValueError("M9 provider is not the reviewed fake executor")
    return digest(
        "m9-fixture",
        1,
        {
            "fixture": inspect.getsource(m9_fixture),
            "runner": inspect.getsource(m9_fixture.run_task),
            "renderer": inspect.getsource(m9_fixture.instruction),
            "projection": inspect.getsource(m9_evidence),
            "issuer": inspect.getsource(inspect.getmodule(fixture_digest)),
            "provider": inspect.getsource(FakeExecutor),
            "configuration": executor._script,
            "profile": executor.profile.model_dump(mode="json"),
        },
    )


def load_manifest(journal: Journal, run: RunId) -> ExecutionManifest:
    identity = journal.run_manifest_hash(run)
    raw = journal.load_manifest_json(identity) if identity is not None else None
    if raw is None:
        raise ValueError("M9 run lacks a retained manifest")
    manifest = ExecutionManifest.model_validate_json(raw)
    if manifest.manifest_hash != identity or manifest_hash_for(manifest) != identity:
        raise ValueError("M9 retained manifest digest mismatch")
    return manifest


def _checkpoint(
    journal: Journal,
    run: RunId,
    version: Digest,
    expected: Digest,
    input_hash: Digest,
) -> Diagnosis:
    checkpoint = journal.checkpoint(run, DIAGNOSTIC_PATH)
    if (
        checkpoint is None
        or checkpoint.run_id != run
        or checkpoint.path != DIAGNOSTIC_PATH
        or checkpoint.resolved_version != version
        or checkpoint.input_hash != input_hash
        or set(checkpoint.outputs) != {"diagnosis"}
        or digest("m9-checkpoint", 1, checkpoint.model_dump(mode="json")) != expected
    ):
        raise ValueError("M9 paired checkpoint is missing or changed")
    envelope = checkpoint.outputs.get("diagnosis")
    if envelope is None or envelope.run_id != run or envelope.path != DIAGNOSTIC_PATH:
        raise ValueError("M9 scored output is not from the paired checkpoint")
    return Diagnosis.model_validate(envelope.payload)


@dataclass(frozen=True)
class Issuer:
    journal: Journal
    approvals: ControlStore
    registry: RegistryStore
    owner: ActorId
    subject: ComponentProofSubject
    seal: RunId
    proposal: RunId
    projection: ArtifactRef
    pairs: tuple[Pair, ...]
    executor: FakeExecutor
    fixture: Digest
    reverse_dependencies: Callable[[str], list[str]]
    current_manifest: Callable[[dict[str, Any]], ExecutionManifest]
    operator_mailbox: bool = False

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        path, graph = (
            (OPERATOR_ISSUER_PATH, operator_issuer_graph())
            if self.operator_mailbox
            else (ISSUER_PATH, issuer_graph())
        )
        if (
            context.path != path
            or context.source_graph_hash != source_graph_hash_for(graph)
            or context.binding.capability_id != ISSUER_CAP
            or context.binding.revision != "1"
        ):
            raise ValueError("M9 issuer may only bind to its reviewed issuance graph")
        lease_id = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        return AcquiredCapability(
            resource=BoundIssuer(self, context),
            lease_id=lease_id,
            acquisition_id=acquisition_id_for(lease_id, context.run_lease.epoch),
            resource_ref=ISSUER_CAP,
        )

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition
    ) -> LeaseClosure:
        del acquisition
        return LeaseClosure(disposition="released" if disposition == "release" else "discarded")

    async def reconcile(
        self,
        context: LeaseContext,
        stale: tuple[StaleAcquisition, ...],
    ) -> LeaseReconciliation:
        del context
        return LeaseReconciliation(reaped=tuple(row.lease.acquisition_id for row in stale))

    def _verify_proposal(self, exam: Exam, old: Digest, new: Digest) -> ComponentLineage:
        snapshot = self.registry.snapshot()
        retained = snapshot.get(TARGET, new)
        if retained is None or retained.content_hash != new:
            raise ValueError("M9 retained candidate is missing")
        lineage = retained.definition.metadata.lineage
        if (
            lineage is None
            or lineage.parent_version != old
            or lineage.created_by_run != self.proposal
            or lineage.experience_set != self.projection
        ):
            raise ValueError(
                "M9 retained candidate lineage disagrees with the attested baseline or exam"
            )
        proposal = self.journal.run_record(self.proposal)
        origin = proposal.origin if proposal is not None else None
        training = {"training": canonical_json(exam.training_projection())}
        input_hash = digest("inputs", 1, training)
        if (
            proposal is None
            or proposal.status != RunStatus.SUCCEEDED
            or origin is None
            or origin.kind != "start"
            or origin.effects != "live"
            or origin.capabilities != "normal"
            or self.proposal == self.seal
            or proposal.manifest_hash != lineage.proposer_manifest_hash
            or proposal.input_hash != input_hash
            or self.journal.run_inputs(self.proposal) != training
        ):
            raise ValueError("M9 proposer run does not match the sealed training projection")
        manifest = load_manifest(self.journal, self.proposal)
        graph = proposer_graph()
        definition = proposer_definition()
        version = definition.content_hash()
        proposer = snapshot.get(PROPOSER, version)
        if (
            manifest.source_graph != graph
            or manifest.source_graph_hash != source_graph_hash_for(graph)
            or manifest.input_hash != input_hash
            or manifest.resolved_loops
            or len(manifest.resolved_components) != 1
            or len(manifest.capability_bindings) != 1
            or proposer is None
            or proposer.definition != definition
            or not isinstance(definition.body, PythonRef)
        ):
            raise ValueError("M9 proposal did not use the reviewed capability-free graph")
        (resolution,) = manifest.resolved_components
        (binding,) = manifest.capability_bindings
        if (
            resolution.component != PROPOSER
            or resolution.scope != PROPOSER_PATH.scope
            or resolution.resolved_version != version
            or resolution.implementation_digest != definition.body.source_digest
            or binding.scope != PROPOSER_PATH.scope
            or binding.binding != SELF_BINDING
            or binding.capability_id != SELF_CAPABILITY
            or binding.effective_grants.posture != Posture.READ
            or binding.effective_grants.network != "none"
            or binding.effective_grants.allowed_tools
            or binding.effective_grants.env_allowlist
        ):
            raise ValueError("M9 proposal graph resolved a different implementation or capability")
        checkpoint = self.journal.checkpoint(self.proposal, PROPOSER_PATH)
        if (
            checkpoint is None
            or checkpoint.run_id != self.proposal
            or checkpoint.path != PROPOSER_PATH
            or checkpoint.input_hash != input_hash
            or checkpoint.resolved_version != version
            or set(checkpoint.outputs) != {"choice"}
        ):
            raise ValueError("M9 proposal has no complete retained choice checkpoint")
        choice = checkpoint.outputs["choice"]
        if (
            choice.run_id != self.proposal
            or choice.path != PROPOSER_PATH
            or choice.port != "choice"
            or choice.payload != "cite-evidence"
        ):
            raise ValueError("M9 proposal did not choose the reviewed atom")
        stripped = retained.definition.model_copy(
            update={
                "metadata": retained.definition.metadata.model_copy(update={"lineage": None}),
            }
        )
        m9_fixture.bind_candidate(choice.payload, stripped)
        return lineage

    def verify(self) -> ComponentLineage:
        if fixture_digest(self.executor) != self.fixture:
            raise ValueError("M9 fixture or provider configuration changed")
        exam = read_projection(self.journal, self.seal, self.projection)
        if exam.fixture != self.fixture:
            raise ValueError("M9 fixture differs from the pre-proposal seal")
        held = tuple(row for row in exam.cases if row.split == "held")
        if len(self.pairs) != len(held):
            raise ValueError("M9 exam requires one pair per held-out source")
        if self.reverse_dependencies(TARGET) != [DEPENDENT]:
            raise ValueError("M9 impact scope is missing a dependent case")
        all_runs = {row.source_run for row in exam.cases}
        corrected = 0
        old = self.subject.baseline_version
        new = self.subject.version
        if old is None or old == new or self.subject.component != TARGET:
            raise ValueError("M9 issuer requires one candidate edge")
        lineage = self._verify_proposal(exam, old, new)
        new_def = m9_fixture.diagnostic_definition(m9_fixture.candidate)
        if not isinstance(new_def.body, PythonRef) or new_def.content_hash() != new:
            raise ValueError("M9 issuer candidate differs from the reviewed atom")
        for row, pair in zip(held, self.pairs, strict=True):
            if (
                pair.source != row.source_run
                or project_case(
                    self.journal,
                    pair.source,
                    row.expected,
                    row.split,
                )
                != row
            ):
                raise ValueError("M9 source no longer matches the sealed case")
            source = load_manifest(self.journal, pair.source)
            expected_inputs = {"case": row.case.model_dump(mode="json")}
            if source.source_graph_hash != source_graph_hash_for(m9_fixture.report_graph()):
                raise ValueError("M9 source is not the reviewed impact graph")
            current = self.current_manifest(expected_inputs)
            if self.operator_mailbox and (
                current.resolved_components != source.resolved_components
                or current.resolved_connections != source.resolved_connections
            ):
                raise ValueError("M9 current baseline or impact revision changed")
            if current.capability_bindings != source.capability_bindings:
                raise ValueError("M9 capability grants or provider revision changed")
            targets = tuple(r for r in source.resolved_components if r.component == TARGET)
            dependents = tuple(r for r in source.resolved_components if r.component == DEPENDENT)
            bindings = tuple(b for b in source.capability_bindings if b.binding == "executor")
            if (
                len(targets) != 1
                or targets[0].resolved_version != old
                or targets[0].scope != DIAGNOSTIC_PATH.scope
                or len(dependents) != 1
                or dependents[0].resolved_version != m9_fixture.report_definition().content_hash()
                or len(bindings) != 1
                or bindings[0].scope != DIAGNOSTIC_PATH.scope
                or bindings[0].capability_id != PROVIDER
                or bindings[0].revision != REVISION
            ):
                raise ValueError(
                    "M9 source does not resolve the attested baseline and impact graph"
                )
            source_checkpoint = self.journal.checkpoint(pair.source, DIAGNOSTIC_PATH)
            if source_checkpoint is None or source_checkpoint.resolved_version != old:
                raise ValueError("M9 source checkpoint is not from the attested baseline")
            for run, version, overrides, checkpoint in (
                (pair.baseline, old, {}, pair.baseline_checkpoint),
                (pair.candidate, new, {TARGET: new}, pair.candidate_checkpoint),
            ):
                if run in all_runs:
                    raise ValueError("M9 exam received reused pair evidence")
                all_runs.add(run)
                record = self.journal.run_record(run)
                origin = record.origin if record is not None else None
                if (
                    record is None
                    or record.status != RunStatus.SUCCEEDED
                    or origin is None
                    or origin.kind != "counterfactual"
                    or origin.source_run_id != pair.source
                    or origin.overrides != overrides
                    or origin.effects != "simulated"
                    or origin.capabilities != "discard"
                    or record.input_hash != row.input_hash
                    or self.journal.run_inputs(run) != self.journal.run_inputs(pair.source)
                ):
                    raise ValueError(
                        "M9 pair does not affirm the exact simulated source and override"
                    )
                actual = load_manifest(self.journal, run)
                resolved = tuple(
                    r.model_copy(
                        update={
                            "resolved_version": new,
                            "implementation_digest": new_def.body.source_digest,
                        }
                    )
                    if overrides and r.component == TARGET
                    else r
                    for r in source.resolved_components
                )
                if (
                    actual.schema_version != source.schema_version
                    or actual.source_graph != source.source_graph
                    or actual.resolved_components != resolved
                    or actual.resolved_connections != source.resolved_connections
                    or actual.source_graph_hash != source.source_graph_hash
                    or actual.capability_bindings != source.capability_bindings
                    or actual.input_hash != source.input_hash
                    or actual.resolved_loops != source.resolved_loops
                ):
                    raise ValueError("M9 paired manifest diverges from its source lock")
                output = _checkpoint(
                    self.journal,
                    run,
                    version,
                    checkpoint,
                    digest("inputs", 1, expected_inputs),
                )
                if version == new and output != row.expected:
                    raise ValueError("M9 candidate failed a held-out impact case")
                if version == old:
                    corrected += output != row.expected
        if not corrected:
            raise ValueError("M9 candidate corrected no baseline failure")
        return lineage


@dataclass(frozen=True)
class BoundIssuer:
    issuer: Issuer
    context: LeaseContext

    def issue(self, approval_id: str) -> str:
        issuer, context = self.issuer, self.context
        run = context.run_lease.run_id
        origin = issuer.journal.run_origin(run)
        approval = issuer.approvals.approval(approval_id)
        if (
            origin is None
            or origin.kind != "start"
            or origin.effects != "live"
            or origin.capabilities != "normal"
            or approval is None
            or approval.run_id != run
            or approval.actor.actor_id != issuer.owner
            or approval.subject != issuer.subject
            or approval.decision != "approved"
        ):
            raise ValueError("M9 issuance lacks affirmative exact-subject owner approval")
        lineage = issuer.verify()
        draft = AttestationDraft(
            action="promote",
            subject=issuer.subject,
            manifest_hash=context.manifest_hash,
            checks=(
                CheckResult(
                    name="m9-held-out-and-impact",
                    ok=True,
                    status="passed",
                    detail="candidate corrected a baseline failure and passed every held-out case",
                    elapsed_s=0,
                ),
            ),
            check_set_hash=digest(
                "m9-check-set",
                1,
                {
                    "fixture": issuer.fixture,
                    "lineage": lineage.model_dump(mode="json"),
                    "exam": issuer.projection.digest,
                    "approval": approval.approval_id,
                    "pairs": [
                        [
                            p.source,
                            p.baseline,
                            p.candidate,
                            p.baseline_checkpoint,
                            p.candidate_checkpoint,
                        ]
                        for p in issuer.pairs
                    ],
                },
            ),
            evidence=(issuer.projection,),
        )
        return issuer.journal.mint_attestation(context.run_lease, draft).attestation_id


async def issue(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    authority = ctx.capability("issuer")
    if not isinstance(authority, BoundIssuer) or not isinstance(inputs["approval"], str):
        raise ValueError("M9 issuance requires its exact lease and approval id")
    return {"proof": authority.issue(inputs["approval"])}


def issuer_graph() -> Graph:
    return Graph(
        name="m9-issue",
        nodes=(GraphNode(id="issue", body=Ref(component=ISSUER, bind={"issuer": ISSUER_CAP})),),
        inputs=(APPROVAL,),
        outputs=(PROOF,),
    )


class OperatorRejected(ValueError):
    """The retained owner decision refused the exact candidate."""


OPERATOR_REJECTION = "M9_OPERATOR_REJECTED"


async def issue_from_operator_decision(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    authority = ctx.capability("issuer")
    if not isinstance(authority, BoundIssuer):
        raise ValueError("M9 operator issuance requires its exact lease")
    approval = ApprovalDecisionPayload.model_validate(inputs["decision"]).approval
    retained = authority.issuer.approvals.approval(approval.approval_id)
    if retained != approval:
        raise ValueError("M9 operator issuance requires the exact retained decision")
    if approval.decision == "rejected":
        raise OperatorRejected(OPERATOR_REJECTION)
    return {"proof": authority.issue(approval.approval_id)}


def operator_approval_bundle() -> DefinitionBundle:
    return next(bundle for bundle in definitions() if bundle.name == APPROVAL_COMPONENT)


def operator_issuer_definition() -> ComponentDef:
    gate = operator_approval_bundle()
    definition, _ = atomic(
        OPERATOR_ISSUER, gate.definition.outputs, (PROOF,), issue_from_operator_decision
    )
    return definition.model_copy(update={
        "capability_requirements": (CapabilityRequirement(alias="issuer", kind=ISSUER_CAP),),
    })


def operator_issuer_graph() -> Graph:
    gate = operator_approval_bundle().definition
    issuer = operator_issuer_definition()
    return Graph(
        name="m9-operator-issue",
        nodes=(
            GraphNode(
                id="gate",
                body=Ref(
                    component=gate.name,
                    version=str(gate.content_hash()),
                    bind={APPROVAL_CHANNEL: OPERATOR_CHANNEL},
                ),
            ),
            GraphNode(
                id="issue",
                body=Ref(
                    component=issuer.name,
                    version=str(issuer.content_hash()),
                    bind={"issuer": ISSUER_CAP},
                ),
            ),
        ),
        connections=(Connection(src="gate", dst="issue"),),
        inputs=gate.inputs,
        outputs=(PROOF,),
    )
