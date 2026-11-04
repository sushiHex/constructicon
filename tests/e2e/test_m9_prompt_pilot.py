"""Run the frozen diagnostic through real admission and counterfactual execution."""

from __future__ import annotations

from dataclasses import replace

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import LaunchDisposition, RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.component import CapabilityRequirement, ComponentLineage, PythonRef
from constructicon.core.control import (
    ADMIN_SCOPE,
    APPROVE_SCOPE,
    OPERATE_SCOPE,
    PROMOTE_SCOPE,
    ApprovalCommandResult,
    AuthenticatedActor,
    ControlRejected,
    PromotionCommandResult,
    RegistrationCommandResult,
    RunSubmission,
    approval_id_for_command,
    command_id_for,
)
from constructicon.core.effect import AttestationDraft, ComponentProofSubject
from constructicon.core.executor import TaskSpec
from constructicon.core.identity import canonical_json, digest
from constructicon.core.manifest import ExecutionManifest
from constructicon.core.registry import RegistryRevision, RegistrySnapshot
from constructicon.core.run import AttemptCause, RunLease, RunStatus
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import atomic, await_attempt_terminal, build_system
from tests.e2e.m9_evidence import (
    CURATOR,
    PROJECTION,
    PROPOSER_PATH,
    RETAINED,
    Exam,
    curator_graph,
    project_case,
    projection_ref,
    proposer_definition,
    proposer_graph,
    read_projection,
    retain_projection,
    suggest,
)
from tests.e2e.m9_fixture import (
    DEPENDENT,
    PROVIDER,
    REVISION,
    TARGET,
    Case,
    Diagnosis,
    baseline,
    bind_candidate,
    candidate,
    diagnostic_definition,
    instruction,
    report_definition,
    report_graph,
    scripted_replies,
)
from tests.e2e.m9_issuer import (
    APPROVAL,
    ISSUER,
    ISSUER_CAP,
    ISSUER_PATH,
    PROOF,
    Issuer,
    Pair,
    fixture_digest,
    issue,
    issuer_graph,
)

OWNER = AuthenticatedActor(
    actor_id="static:m9-owner", auth_method="static", scopes=frozenset({APPROVE_SCOPE})
)
OTHER_APPROVER = AuthenticatedActor(
    actor_id="static:m9-other", auth_method="static", scopes=frozenset({APPROVE_SCOPE})
)
PROMOTER = AuthenticatedActor(
    actor_id="static:m9-promoter", auth_method="static", scopes=frozenset({PROMOTE_SCOPE})
)

OPERATOR = AuthenticatedActor(
    actor_id="static:m9-operator", auth_method="static", scopes=frozenset({OPERATE_SCOPE})
)
REGISTRAR = AuthenticatedActor(
    actor_id="static:m9-registrar", auth_method="static", scopes=frozenset({ADMIN_SCOPE})
)
PATH = ExecutionPath(scope=ScopePath(segments=("m9-pilot", "report", "diagnose")))


def _manifest(journal: SqliteJournal, submission: RunSubmission) -> ExecutionManifest:
    manifest_hash = journal.run_manifest_hash(submission.run_id)
    assert manifest_hash is not None
    raw = journal.load_manifest_json(manifest_hash)
    assert raw is not None
    return ExecutionManifest.model_validate_json(raw)


async def test_diagnostic_prompt_counterfactual(
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = FakeExecutor(scripted_replies())
    world = build_system(journal, executor, FakeAnnounceEffect(), owner_id="m9-fixture")
    fixture = fixture_digest(executor)
    old_def = diagnostic_definition(baseline)
    new_def = diagnostic_definition(candidate)
    assert isinstance(old_def.body, PythonRef) and isinstance(new_def.body, PythonRef)
    assert str(old_def.body.source_digest) == (
        "sha256:9890709271e8c48f047d87f2442e076e0c8a4d611692a6ceb8de1acc3da523a4"
    )
    assert str(new_def.body.source_digest) == (
        "sha256:9d5047fd08fcb9d150998e9336b79fff18a693dfc04a2c2f9ddb1ce37ef882d6"
    )
    assert old_def.model_dump(exclude={"body"}) == new_def.model_dump(exclude={"body"})
    assert old_def.body.contract_hash == new_def.body.contract_hash
    old = world._register(old_def, baseline)
    world._promote_initial(component=TARGET, version=old)
    report = world._register(report_definition())
    world._promote_initial(component=DEPENDENT, version=report)
    assert world.describe(component_names=(TARGET, DEPENDENT))
    assert world.describe_component(TARGET, version=old)
    assert world.rdeps(TARGET) == [DEPENDENT]
    curator, impl = atomic(CURATOR, (PROJECTION,), (RETAINED,), retain_projection)
    world._promote_initial(component=CURATOR, version=world._register(curator, impl))
    proposer = proposer_definition()
    world._promote_initial(component=proposer.name, version=world._register(proposer, suggest))
    graph = report_graph()

    control = ControlPlane(system=world, store=journal)
    try:
        cases = (
            (Case(evidence_id="train-1", observation="DNS lookup timed out"), "network"),
            (Case(evidence_id="held-1", observation="Disk quota exceeded"), "storage"),
            (Case(evidence_id="held-2", observation="TCP connection refused"), "network"),
        )
        projected = []
        for index, (case, label) in enumerate(cases):
            inputs = {"case": case.model_dump(mode="json")}
            source = await control.runs_start(
                OPERATOR, proposal=graph, inputs=inputs, idempotency_key=case.evidence_id
            )
            assert isinstance(source, RunSubmission)
            assert (
                await await_attempt_terminal(journal, source.run_id, baseline_event_seq=0)
            ).kind == ("RunSucceeded")
            manifest = _manifest(journal, source)
            (target,) = (r for r in manifest.resolved_components if r.component == TARGET)
            assert target.scope.segments == PATH.scope.segments
            assert target.resolved_version == old
            (binding,) = (b for b in manifest.capability_bindings if b.binding == "executor")
            assert (binding.scope, binding.capability_id, binding.revision) == (
                PATH.scope,
                PROVIDER,
                REVISION,
            )
            checkpoint = journal.checkpoint(source.run_id, PATH)
            assert checkpoint is not None and checkpoint.resolved_version == old
            projected.append(
                project_case(
                    journal,
                    source.run_id,
                    Diagnosis(classification=label, evidence_id=case.evidence_id),
                    "train" if index == 0 else "held",
                )
            )

        with pytest.raises(ValueError, match="non-overlapping"):
            Exam(fixture=fixture, cases=(projected[0], projected[0], projected[2])).canonical()
        raw = Exam(fixture=fixture, cases=tuple(projected)).canonical()
        reference = projection_ref(raw)
        seal = await control.runs_start(
            OPERATOR,
            proposal=curator_graph(),
            inputs={"projection": raw},
            idempotency_key="seal-exam",
        )
        assert isinstance(seal, RunSubmission)
        assert (
            await await_attempt_terminal(journal, seal.run_id, baseline_event_seq=0)
        ).kind == "RunSucceeded"
        exam = read_projection(journal, seal.run_id, reference)
        train = exam.training_projection()
        training_bytes = canonical_json(train)
        assert "train-1" in training_bytes
        assert all(row.case.evidence_id not in training_bytes for row in exam.cases[1:])
        proposal = await control.runs_start(
            OPERATOR,
            proposal=proposer_graph(),
            inputs={"training": training_bytes},
            idempotency_key="propose-m9",
        )
        assert isinstance(proposal, RunSubmission)
        assert (
            await await_attempt_terminal(journal, proposal.run_id, baseline_event_seq=0)
        ).kind == "RunSucceeded"
        proposal_manifest = _manifest(journal, proposal)
        assert all(b.binding == "__node__" for b in proposal_manifest.capability_bindings)
        proposal_output = journal.checkpoint(proposal.run_id, PROPOSER_PATH)
        assert proposal_output is not None
        choice = proposal_output.outputs["choice"].payload
        with pytest.raises(ValueError, match="reviewed"):
            bind_candidate(choice, old_def)
        with pytest.raises(ValueError, match="reviewed"):
            bind_candidate("unreviewed-choice", new_def)
        new_def = bind_candidate(choice, new_def)
        new_def = new_def.model_copy(
            update={
                "metadata": new_def.metadata.model_copy(
                    update={
                        "lineage": ComponentLineage(
                            parent_version=old,
                            created_by_run=proposal.run_id,
                            experience_set=reference,
                            proposer_manifest_hash=proposal_manifest.manifest_hash,
                        ),
                    }
                )
            }
        )

        registered = await control.registry_register(
            REGISTRAR, definition=DefinitionBundle(new_def, candidate), idempotency_key="candidate"
        )
        assert isinstance(registered, RegistrationCommandResult)
        new = registered.version
        assert new == new_def.content_hash() and new != old
        assert fixture_digest(executor) == fixture
        failures = 0
        pairs = []
        for row in exam.cases:
            if row.split != "held":
                continue
            case, expected = row.case, row.expected
            pair = []
            for version, overrides, prompt in (
                (old, {}, "Classify the observation as network or storage."),
                (
                    new,
                    {TARGET: new},
                    "Classify the observation as network or storage. "
                    "Cite the supplied evidence ID.",
                ),
            ):
                before = len(executor.calls)
                paired = await control.runs_counterfactual(
                    OPERATOR,
                    source_run_id=row.source_run,
                    overrides=overrides,
                    idempotency_key=f"{case.evidence_id}-{version}",
                )
                assert isinstance(paired, RunSubmission)
                assert (
                    await await_attempt_terminal(journal, paired.run_id, baseline_event_seq=0)
                ).kind == "RunSucceeded"
                assert executor.calls[before:] == [TaskSpec(instruction=instruction(prompt, case))]
                checkpoint = journal.checkpoint(paired.run_id, PATH)
                assert checkpoint is not None and checkpoint.resolved_version == version
                pair.append(
                    (paired.run_id, digest("m9-checkpoint", 1, checkpoint.model_dump(mode="json")))
                )
                output = Diagnosis.model_validate(checkpoint.outputs["diagnosis"].payload)
                if version == old:
                    failures += output != expected
                else:
                    assert output == expected
            pairs.append(Pair(row.source_run, pair[0][0], pair[1][0], pair[0][1], pair[1][1]))
        assert failures == 1
        admitted = world.validate(graph, {"case": cases[0][0].model_dump(mode="json")})
        assert any(
            r.component == TARGET and r.resolved_version == old
            for r in admitted.resolved_components
        )
        issuer = Issuer(
            journal=journal,
            approvals=journal,
            registry=journal,
            owner=OWNER.actor_id,
            subject=ComponentProofSubject(component=TARGET, version=new, baseline_version=old),
            seal=seal.run_id,
            proposal=proposal.run_id,
            projection=reference,
            pairs=tuple(pairs),
            executor=executor,
            fixture=fixture,
            reverse_dependencies=world.rdeps,
            current_manifest=lambda inputs: world.validate(graph, inputs),
        )
        issuer.verify()
        with pytest.raises(ValueError, match="projection digest mismatch"):
            replace(issuer, projection=projection_ref("{}")).verify()
        with pytest.raises(ValueError, match="one pair"):
            replace(issuer, pairs=issuer.pairs[:-1]).verify()
        with pytest.raises(ValueError, match="sealed case"):
            replace(issuer, pairs=issuer.pairs[::-1]).verify()
        with pytest.raises(ValueError, match="attested baseline"):
            replace(
                issuer,
                subject=issuer.subject.model_copy(
                    update={
                        "baseline_version": digest("m9-other-baseline", 1, "another version"),
                    }
                ),
            ).verify()
        with pytest.raises(ValueError, match="configuration changed"):
            replace(issuer, executor=FakeExecutor({})).verify()
        with pytest.raises(ValueError, match="grants or provider revision"):
            replace(
                issuer,
                current_manifest=lambda inputs: world.validate(graph, inputs).model_copy(
                    update={"capability_bindings": ()}
                ),
            ).verify()
        # Close the evaluator's host before the issuance-only host starts.
        # Automatic recovery scans this journal; only the latter has the issuer.
        await control.shutdown()
        await _prove_authority(issuer, journal, monkeypatch, source.run_id)
        assert _manifest(journal, source) == manifest
        assert world.validate(graph, {"case": cases[0][0].model_dump(mode="json")}) == admitted
    finally:
        await control.shutdown()


class _PreparedRunHost(RunHost):
    """Leave the issuance run prepared while the owner records a decision."""

    def launch(
        self,
        run_id: RunId,
        *,
        expected_event_seq: int | None = None,
        allowed_statuses: frozenset[RunStatus] | None = None,
        cause: AttemptCause | None = None,
    ) -> LaunchDisposition:
        del run_id, expected_event_seq, allowed_statuses, cause
        return "queued"


async def _prove_authority(
    issuer: Issuer,
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
    other_run: RunId,
) -> None:
    # The evaluator world never had the issuance capability. This second
    # assembly serves only the reviewed issuance graph over the same facts.
    world = Constructicon(
        journal=journal,
        capabilities={ISSUER_CAP: issuer},
        catalog={
            ISSUER_CAP: CapabilityDescriptor(
                capability_id=ISSUER_CAP,
                kind=ISSUER_CAP,
                revision="1",
                leased=True,
            )
        },
        owner_id="m9-proof-worker",
    )
    definition, impl = atomic(ISSUER, (APPROVAL,), (PROOF,), issue)
    definition = definition.model_copy(
        update={
            "capability_requirements": (CapabilityRequirement(alias="issuer", kind=ISSUER_CAP),),
        }
    )
    world._promote_initial(component=ISSUER, version=world._register(definition, impl))
    prepared = _PreparedRunHost(world, journal=journal)

    class ResponseLost(Exception):
        pass

    lost = False

    def lose_promotion_response(seam: str) -> None:
        nonlocal lost
        if seam == "registry_promote.after_command_completion" and not lost:
            lost = True
            raise ResponseLost(seam)

    control = ControlPlane(
        system=world,
        store=journal,
        run_host=prepared,
        fault_probe=lose_promotion_response,
    )
    mint = journal.mint_attestation
    mints = []

    def observe(lease: RunLease, draft: AttestationDraft):
        result = mint(lease, draft)
        mints.append((lease.run_id, result.attestation_id))
        return result

    snapshot = journal.snapshot

    def corrupted_snapshot(scenario: str, revision: RegistryRevision | None) -> RegistrySnapshot:
        facts = snapshot(revision).model_copy(deep=True)
        candidate = facts.get(TARGET, issuer.subject.version)
        assert candidate is not None
        lineage = candidate.definition.metadata.lineage
        assert lineage is not None
        corrupted = (
            None
            if scenario == "missing-lineage"
            else lineage.model_copy(
                update={"proposer_manifest_hash": digest("m9-altered-manifest", 1, "changed")}
            )
        )
        definition = candidate.definition.model_copy(
            update={
                "metadata": candidate.definition.metadata.model_copy(update={"lineage": corrupted}),
            }
        )
        assert definition.content_hash() == candidate.content_hash
        facts.versions[TARGET][str(issuer.subject.version)] = candidate.model_copy(
            update={"definition": definition},
        )
        return facts

    monkeypatch.setattr(journal, "mint_attestation", observe)
    try:
        proof_ids = []
        for scenario in (
            "missing",
            "rejected",
            "wrong-owner",
            "wrong-run",
            "wrong-subject",
            "changed-config",
            "missing-lineage",
            "changed-lineage",
            "valid",
            "stale",
        ):
            approver = OTHER_APPROVER if scenario == "wrong-owner" else OWNER
            subject = (
                issuer.subject
                if scenario != "wrong-subject"
                else issuer.subject.model_copy(update={"version": issuer.subject.baseline_version})
            )
            approval_id = approval_id_for_command(
                command_id_for(approver.actor_id, "runs_approve", scenario),
                subject.model_dump(mode="json"),
            )
            run = await control.runs_start(
                OPERATOR,
                proposal=issuer_graph(),
                inputs={"approval": approval_id},
                idempotency_key=f"issue-{scenario}",
            )
            assert isinstance(run, RunSubmission)
            if scenario != "missing":
                decision = await control.runs_approve(
                    approver,
                    run_id=other_run if scenario == "wrong-run" else run.run_id,
                    subject=subject,
                    decision="rejected" if scenario == "rejected" else "approved",
                    reason=None,
                    idempotency_key=scenario,
                )
                assert isinstance(decision, ApprovalCommandResult)
                assert decision.approval_id == approval_id
            worker = RunHost(world, journal=journal)
            try:
                with monkeypatch.context() as fault:
                    if scenario == "changed-config":
                        fault.setattr(issuer.executor, "_script", {})
                    if scenario in {"missing-lineage", "changed-lineage"}:
                        fault.setattr(
                            journal,
                            "snapshot",
                            lambda revision=None, scenario=scenario: corrupted_snapshot(
                                scenario,
                                revision,
                            ),
                        )
                    assert worker.launch(run.run_id) == "queued"
                    terminal = await await_attempt_terminal(
                        journal, run.run_id, baseline_event_seq=0
                    )
            finally:
                await worker.shutdown()
            result = journal.checkpoint(run.run_id, ISSUER_PATH)
            if scenario not in {"valid", "stale"}:
                assert terminal.kind == "RunFailed"
                assert result is None and mints == []
                reason = {
                    "changed-config": "fixture or provider configuration changed",
                    "missing-lineage": "retained candidate lineage disagrees",
                    "changed-lineage": "proposer run does not match the sealed training projection",
                }.get(scenario, "affirmative exact-subject owner approval")
                errors = [
                    event.payload
                    for event in journal.events(run.run_id)
                    if event.kind == "NodeFailed" and event.path == ISSUER_PATH
                ]
                assert len(errors) == 1 and reason in str(errors[0])
                continue
            assert terminal.kind == "RunSucceeded"
            assert result is not None
            proof_id = result.outputs["proof"].payload
            assert (run.run_id, proof_id) == mints[-1]
            proof = journal.load_attestation(proof_id)
            assert proof is not None and proof.created_by_run == run.run_id
            assert proof.subject == issuer.subject and proof.ok
            proof_ids.append(proof_id)

        old, new = issuer.subject.baseline_version, issuer.subject.version
        revision = journal.snapshot().revision.promotion_seq
        with pytest.raises(ResponseLost, match="after_command_completion"):
            await control.registry_promote(
                PROMOTER,
                component=TARGET,
                version=new,
                attestation_id=proof_ids[0],
                idempotency_key="m9-promote",
            )
        assert journal.snapshot().revision.promotion_seq == revision + 1
        current = issuer.current_manifest(
            {
                "case": {
                    "evidence_id": "held-1",
                    "observation": "Disk quota exceeded",
                }
            }
        )
        assert any(
            r.component == TARGET and r.resolved_version == new for r in current.resolved_components
        )
        promote = await control.registry_promote(
            PROMOTER,
            component=TARGET,
            version=new,
            attestation_id=proof_ids[0],
            idempotency_key="m9-promote",
        )
        assert isinstance(promote, PromotionCommandResult)
        assert (promote.from_version, promote.to_version) == (old, new)
        assert promote.command.replayed
        replay = await control.registry_promote(
            PROMOTER,
            component=TARGET,
            version=new,
            attestation_id=proof_ids[0],
            idempotency_key="m9-promote",
        )
        assert isinstance(replay, PromotionCommandResult) and replay.command.replayed
        assert replay.detail == promote.detail
        assert journal.snapshot().revision.promotion_seq == revision + 1
        stale = await control.registry_promote(
            PROMOTER,
            component=TARGET,
            version=new,
            attestation_id=proof_ids[1],
            idempotency_key="m9-stale",
        )
        assert isinstance(stale, ControlRejected)
        rollback = await control.registry_rollback(
            PROMOTER, component=TARGET, expected_stable=new, idempotency_key="m9-rollback"
        )
        assert isinstance(rollback, PromotionCommandResult)
        assert (rollback.status, rollback.from_version, rollback.to_version) == (
            "rolled_back",
            new,
            old,
        )
    finally:
        await control.shutdown()
