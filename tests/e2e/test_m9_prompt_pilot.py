"""Run the frozen diagnostic through real admission and counterfactual execution."""

from __future__ import annotations

from constructicon.api.control import ControlPlane
from constructicon.core.address import ExecutionPath, ScopePath
from constructicon.core.component import PythonRef
from constructicon.core.control import (
    ADMIN_SCOPE,
    OPERATE_SCOPE,
    AuthenticatedActor,
    RegistrationCommandResult,
    RunSubmission,
)
from constructicon.core.executor import TaskSpec
from constructicon.core.manifest import ExecutionManifest
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import await_attempt_terminal, build_system
from tests.e2e.m9_fixture import (
    DEPENDENT,
    PROVIDER,
    REVISION,
    TARGET,
    Case,
    Diagnosis,
    baseline,
    candidate,
    diagnostic_definition,
    instruction,
    report_definition,
    report_graph,
    scripted_replies,
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


async def test_diagnostic_prompt_counterfactual(journal: SqliteJournal) -> None:
    executor = FakeExecutor(scripted_replies())
    world = build_system(journal, executor, FakeAnnounceEffect(), owner_id="m9-fixture")
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
    graph = report_graph()

    control = ControlPlane(system=world, store=journal)
    try:
        cases = (
            (Case(evidence_id="held-1", observation="Disk quota exceeded"), "storage"),
            (Case(evidence_id="held-2", observation="TCP connection refused"), "network"),
        )
        retained = []
        for case, label in cases:
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
            retained.append((case, label, source, manifest))

        registered = await control.registry_register(
            REGISTRAR, definition=DefinitionBundle(new_def, candidate), idempotency_key="candidate"
        )
        assert isinstance(registered, RegistrationCommandResult)
        new = registered.version
        assert new == new_def.content_hash() and new != old
        failures = 0
        for case, label, source, manifest in retained:
            expected = Diagnosis(classification=label, evidence_id=case.evidence_id)
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
                    source_run_id=source.run_id,
                    overrides=overrides,
                    idempotency_key=f"{case.evidence_id}-{version}",
                )
                assert isinstance(paired, RunSubmission)
                assert (
                    await await_attempt_terminal(journal, paired.run_id, baseline_event_seq=0)
                ).kind == "RunSucceeded"
                assert executor.calls[before:] == [TaskSpec(instruction=instruction(prompt, case))]
                origin = journal.run_origin(paired.run_id)
                assert origin is not None and origin.kind == "counterfactual"
                assert origin.source_run_id == source.run_id and origin.overrides == overrides
                assert (origin.effects, origin.capabilities) == ("simulated", "discard")
                actual = _manifest(journal, paired)
                assert actual.input_hash == manifest.input_hash
                assert actual.source_graph_hash == manifest.source_graph_hash
                assert actual.capability_bindings == manifest.capability_bindings
                expected_resolutions = tuple(
                    r
                    if r.component != TARGET
                    else r.model_copy(
                        update={
                            "resolved_version": version,
                            "implementation_digest": (
                                old_def.body.source_digest
                                if version == old
                                else new_def.body.source_digest
                            ),
                        }
                    )
                    for r in manifest.resolved_components
                )
                assert actual.resolved_components == expected_resolutions
                checkpoint = journal.checkpoint(paired.run_id, PATH)
                assert checkpoint is not None and checkpoint.resolved_version == version
                output = Diagnosis.model_validate(checkpoint.outputs["diagnosis"].payload)
                if version == old:
                    failures += output != expected
                else:
                    assert output == expected
        assert failures == 1
        admitted = world.validate(graph, {"case": cases[0][0].model_dump(mode="json")})
        assert any(
            r.component == TARGET and r.resolved_version == old
            for r in admitted.resolved_components
        )
    finally:
        await control.shutdown()
