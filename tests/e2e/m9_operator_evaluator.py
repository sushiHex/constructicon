"""Fixed evaluator assembly for the repo-local, credential-free operator trial."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.component import ComponentLineage
from constructicon.core.control import (
    ADMIN_SCOPE,
    APPROVE_SCOPE,
    OPERATE_SCOPE,
    PROMOTE_SCOPE,
    AuthenticatedActor,
    RegistrationCommandResult,
    RunSubmission,
    command_id_for,
)
from constructicon.core.effect import ComponentProofSubject
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.run import RunStatus
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import atomic
from tests.e2e.m9_evidence import (
    CASE_POLICY,
    CURATOR,
    DIAGNOSTIC_PATH,
    PROJECTION,
    PROPOSER_PATH,
    RETAINED,
    TrialIdentity,
    curator_graph,
    fixed_exam,
    projection_ref,
    proposer_definition,
    proposer_graph,
    read_fixed_projection,
    retain_projection,
    suggest,
)
from tests.e2e.m9_fixture import (
    PROVIDER,
    REVISION,
    TARGET,
    baseline,
    bind_candidate,
    candidate,
    diagnostic_definition,
    report_definition,
    report_graph,
    scripted_replies,
)
from tests.e2e.m9_issuer import Issuer, Pair, fixture_digest, load_manifest


def _actor(role: str, scope: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=f"static:m9-trial-{role}", auth_method="static", scopes=frozenset({scope})
    )


OPERATOR = _actor("operator", OPERATE_SCOPE)
OWNER = _actor("owner", APPROVE_SCOPE)
REGISTRAR = _actor("registrar", ADMIN_SCOPE)
PROMOTER = _actor("promoter", PROMOTE_SCOPE)


@dataclass(frozen=True)
class Evaluator:
    journal: SqliteJournal
    executor: FakeExecutor
    system: Constructicon

    @classmethod
    def assemble(cls, journal: SqliteJournal, *, initialize: bool = False) -> Evaluator:
        executor = FakeExecutor(scripted_replies())
        system = Constructicon(
            journal=journal,
            capabilities={PROVIDER: executor},
            catalog={
                PROVIDER: CapabilityDescriptor(
                    capability_id=PROVIDER,
                    kind="executor",
                    revision=REVISION,
                    executor_profile=executor.profile,
                )
            },
        )
        curator, _ = atomic(CURATOR, (PROJECTION,), (RETAINED,), retain_projection)
        for definition, implementation in (
            (diagnostic_definition(baseline), baseline),
            (report_definition(), None),
            (curator, retain_projection),
            (proposer_definition(), suggest),
        ):
            version = definition.content_hash()
            snapshot = journal.snapshot()
            current = snapshot.stable_version(definition.name)
            if current is None and initialize:
                system._promote_initial(
                    component=definition.name,
                    version=system._register(definition, implementation),
                )
            elif current != version or snapshot.get(definition.name, version) is None:
                raise ValueError(f"Trial baseline changed: {definition.name}")
        return cls(journal, executor, system)

    async def succeeded(self, result: object, *, resuming: bool = False) -> RunId:
        if not isinstance(result, RunSubmission):
            raise ValueError(f"Trial run was not admitted: {result}")
        async with asyncio.timeout(10):
            while True:
                record = self.journal.run_record(result.run_id)
                if record is None:
                    raise ValueError("Admitted trial run has no durable record")
                if record.status == RunStatus.SUCCEEDED:
                    return result.run_id
                if record.status not in (RunStatus.PENDING, RunStatus.RUNNING) and not (
                    resuming and record.status == RunStatus.PARKED
                ):
                    raise ValueError(f"Trial run did not succeed: {record.status}")
                await asyncio.sleep(0.01)

    def checkpoint_digest(self, run: RunId) -> Digest:
        checkpoint = self.journal.checkpoint(run, DIAGNOSTIC_PATH)
        if checkpoint is None:
            raise ValueError("Trial pair is missing the diagnostic checkpoint")
        return digest("m9-checkpoint", 1, checkpoint.model_dump(mode="json"))

    async def prepare(self, trial: TrialIdentity, *, retained: bool) -> Issuer:
        old = diagnostic_definition(baseline).content_hash()
        impact = report_definition().content_hash()
        fixture = fixture_digest(self.executor)
        graph = report_graph()
        control = ControlPlane(system=self.system, store=self.journal)

        async def command(
            actor: AuthenticatedActor,
            operation: str,
            stage: str,
            execute: Callable[[], Awaitable[object]],
        ) -> object:
            if not retained:
                return await execute()
            row = self.journal.command(command_id_for(actor.actor_id, operation, trial.key(stage)))
            if row is None or row.state != "committed":
                raise ValueError(f"Trial stage has no committed result: {stage}")
            if operation == "registry_register":
                return RegistrationCommandResult.model_validate_json(canonical_json(row.response))
            return RunSubmission.model_validate(row.response)

        if not retained:
            await control.startup()
        try:

            async def start(stage, graph, inputs):
                return await self.succeeded(
                    await command(
                        OPERATOR,
                        "runs_start",
                        stage,
                        lambda: control.runs_start(
                            OPERATOR,
                            proposal=graph,
                            inputs=inputs,
                            idempotency_key=trial.key(stage),
                        ),
                    )
                )

            sources = tuple(
                [
                    await start(
                        f"source-{case.evidence_id}", graph, {"case": case.model_dump(mode="json")}
                    )
                    for case, _, _ in CASE_POLICY
                ]
            )
            policy = dict(source_runs=sources, fixture=fixture, baseline=old, impact=impact)
            raw = fixed_exam(self.journal, **policy).canonical()
            projection = projection_ref(raw)
            seal = await start("seal", curator_graph(), {"projection": raw})
            exam = read_fixed_projection(self.journal, seal, projection, **policy)
            proposal = await start(
                "propose",
                proposer_graph(),
                {"training": canonical_json(exam.training_projection())},
            )
            output = self.journal.checkpoint(proposal, PROPOSER_PATH)
            if output is None:
                raise ValueError("Trial proposal has no durable result")
            reviewed = bind_candidate(
                output.outputs["choice"].payload,
                diagnostic_definition(candidate),
            )
            definition = reviewed.model_copy(
                update={
                    "metadata": reviewed.metadata.model_copy(
                        update={
                            "lineage": ComponentLineage(
                                parent_version=old,
                                created_by_run=proposal,
                                experience_set=projection,
                                proposer_manifest_hash=load_manifest(
                                    self.journal, proposal
                                ).manifest_hash,
                            )
                        }
                    )
                }
            )
            registered = await command(
                REGISTRAR,
                "registry_register",
                "register",
                lambda: control.registry_register(
                    REGISTRAR,
                    definition=DefinitionBundle(definition, candidate),
                    idempotency_key=trial.key("register"),
                ),
            )
            if not isinstance(registered, RegistrationCommandResult):
                raise ValueError(f"Trial candidate registration refused: {registered}")
            new = registered.version
            pairs = []
            for row in exam.cases:
                if row.split != "held":
                    continue

                async def counterfactual(stage, overrides, source=row.source_run):
                    return await self.succeeded(
                        await command(
                            OPERATOR,
                            "runs_counterfactual",
                            stage,
                            lambda: control.runs_counterfactual(
                                OPERATOR,
                                source_run_id=source,
                                overrides=overrides,
                                idempotency_key=trial.key(stage),
                            ),
                        )
                    )

                old_run = await counterfactual(f"baseline-{row.case.evidence_id}", {})
                new_run = await counterfactual(f"candidate-{row.case.evidence_id}", {TARGET: new})
                pairs.append(
                    Pair(
                        row.source_run,
                        old_run,
                        new_run,
                        self.checkpoint_digest(old_run),
                        self.checkpoint_digest(new_run),
                    )
                )
            issuer = Issuer(
                journal=self.journal,
                approvals=self.journal,
                registry=self.journal,
                owner=OWNER.actor_id,
                subject=ComponentProofSubject(component=TARGET, version=new, baseline_version=old),
                seal=seal,
                proposal=proposal,
                projection=projection,
                pairs=tuple(pairs),
                executor=self.executor,
                fixture=fixture,
                reverse_dependencies=self.system.rdeps,
                operator_mailbox=True,
                current_manifest=lambda inputs: self.system.validate(graph, inputs),
            )
            issuer.verify()
            return issuer
        finally:
            await control.shutdown()
