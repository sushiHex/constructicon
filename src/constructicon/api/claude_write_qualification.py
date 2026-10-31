"""One exactly authorized Claude WRITE; capture and gate remain deterministic.

The provider stays unavailable by default. Preparation and minting compute
artifacts, never permission to dispatch. Recovery uses the ordinary RunHost.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from constructicon.api import _qualification_write_assembly as contained
from constructicon.api import _qualification_write_graph as fixed
from constructicon.api import _qualification_write_report as projection
from constructicon.api.qualification import _drive, _require_dedicated
from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath
from constructicon.core.control import ADMIN_SCOPE, READ_SCOPE, AuthenticatedActor
from constructicon.core.envelope import utc_now
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorSuccess, TaskSpec
from constructicon.core.grants import EffectiveGrants, GrantRequest, ModelSelection, Posture
from constructicon.core.graph import Connection, Graph, GraphNode, Ref
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.manifest import CapabilityLease, parse_manifest_json, source_graph_hash_for
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.qualification_write import (
    CallbackObservation,
    WriteObservation,
    WriteQualificationPins,
    WriteQualificationReport,
    WriteReportInstalledIdentities,
    WriteReportLimits,
    WriteReportTelemetry,
)
from constructicon.core.workspace import acquisition_id_for, lease_id_for
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.runtime.validator import admit
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.executors.claude_host import ClaudeHostSession, operator_provider
from constructicon.substrate.executors.claude_lane import read_configuration
from constructicon.substrate.executors.claude_native import ClaudeNativeRecipe
from constructicon.substrate.executors.claude_provider import (
    WRITE_CATALOG,
    ClaudeOperatorHandle,
    ClaudeOperatorProvider,
)
from constructicon.substrate.executors.claude_write_worker import (
    WRITE_OUTPUT_BYTES,
    WRITE_PROGRAM_BYTES,
    WRITE_WORKER_LIMITS,
)
from constructicon.substrate.executors.linux import LinuxLauncher, LinuxLaunchProfile
from constructicon.substrate.executors.qualification import read_authorization
from constructicon.substrate.journal.sqlite import SqliteJournal

CAPABILITY = "claude-operator"
Issue = projection.Issue


async def write_writer(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    executor = ctx.capability(fixed.EXECUTOR)
    if not isinstance(executor, ClaudeOperatorHandle):
        raise ContractViolation("the WRITE qualification binds the Claude operator only")
    request = fixed._request(inputs)
    workspace = await fixed._writer_workspace(ctx, request)
    outcome = await executor.execute(TaskSpec(instruction=(
        "Use contained_python to create n5-write.txt containing exactly ready "
        "followed by a newline. Change no other files."
    )), workspace=workspace, grants=ctx.grants)
    if not isinstance(outcome, ExecutorSuccess):
        raise ContractViolation(f"the WRITE turn ended {outcome.status}")
    return await fixed.capture_changed_candidate(workspace, request)


def definitions() -> tuple[DefinitionBundle, DefinitionBundle]:
    return (
        fixed._definition("constructicon.qualification/claude-write-writer",
                          write_writer, writer=True),
        fixed.write_definitions()[1],
    )


def fixed_grants(provider: ClaudeOperatorProvider) -> EffectiveGrants:
    vendor = provider.launcher.claude
    if vendor is None:
        raise ContractViolation("Claude WRITE qualification requires its native recipe")
    return EffectiveGrants(
        posture=Posture.WRITE, model_selection=ModelSelection(kind="explicit", model=vendor.model),
        effort=vendor.effort, allowed_tools=WRITE_CATALOG, env_allowlist=(),
        network="allow", timeout_s=300,
    )


def checker_grants(grants: EffectiveGrants) -> EffectiveGrants:
    return grants.model_copy(update={
        "posture": Posture.READ, "allowed_tools": (), "network": "none", "timeout_s": 30,
    })


def _request_grants(grants: EffectiveGrants) -> GrantRequest:
    return GrantRequest(
        posture=grants.posture, model=grants.model_selection.model, effort=grants.effort,
        allowed_tools=grants.allowed_tools, env_allowlist=grants.env_allowlist,
        network=grants.network, timeout_s=grants.timeout_s,
    )


def graph(grants: EffectiveGrants, pins: WriteQualificationPins) -> Graph:
    writer, checker = definitions()
    return Graph(
        name=fixed.GRAPH_NAME, inputs=(fixed.REQUEST,),
        outputs=(fixed.CANDIDATE, fixed.EVALUATION),
        nodes=(
            GraphNode(id=fixed.WRITER_ID, body=Ref(
                component=writer.definition.name, version=str(writer.definition.content_hash()),
                bind={fixed.EXECUTOR: CAPABILITY, fixed.WORKSPACE: pins.workspace.capability_id},
                grants=_request_grants(grants),
            )),
            GraphNode(id=fixed.CHECKER_ID, body=Ref(
                component=checker.definition.name, version=str(checker.definition.content_hash()),
                bind={fixed.GATE: pins.gate.capability_id},
                grants=_request_grants(checker_grants(grants)),
            )),
        ),
        connections=(Connection(src=fixed.WRITER_ID, dst=fixed.CHECKER_ID,
            map={"candidate": "writer.candidate", "request": "$input.request"}),),
    )


def report_definition() -> Digest:
    """The actual Claude projection and every shared capture helper are sealed."""
    return digest("claude-write-report-definition", 1, {
        "entry": Path(__file__).read_bytes().hex(),
        "capture": Path(fixed.__file__).read_bytes().hex(),
        "assembly": Path(contained.__file__).read_bytes().hex(),
        "projection": projection.write_report_definition(),
    })


@dataclass(frozen=True)
class ClaudeWriteAssembly:
    executor: ClaudeOperatorProvider
    resources: contained.ContainedWriteResources
    pins: WriteQualificationPins


def _catalog(assembly: ClaudeWriteAssembly) -> dict[str, CapabilityDescriptor]:
    resources, provider = assembly.resources, assembly.executor
    return {
        CAPABILITY: CapabilityDescriptor(
            capability_id=CAPABILITY, kind="executor", leased=True,
            revision=provider.identity.revision, executor_profile=provider.profile,
        ),
        contained.WORKSPACE_CAPABILITY: CapabilityDescriptor(
            capability_id=contained.WORKSPACE_CAPABILITY, kind="workspace.contained", leased=True,
            revision=resources.workspace.revision, requires_posture=Posture.WRITE,
        ),
        contained.GATE_CAPABILITY: CapabilityDescriptor(
            capability_id=contained.GATE_CAPABILITY, kind="gates.contained", leased=True,
            revision=resources.gate.revision,
        ),
    }


def _capabilities(assembly: ClaudeWriteAssembly) -> dict[str, object]:
    return {CAPABILITY: assembly.executor,
            contained.WORKSPACE_CAPABILITY: assembly.resources.workspace,
            contained.GATE_CAPABILITY: assembly.resources.gate}


def _system(assembly: ClaudeWriteAssembly) -> Constructicon:
    return Constructicon(journal=assembly.resources.journal,
                         root_grants=fixed_grants(assembly.executor),
                         capabilities=_capabilities(assembly), catalog=_catalog(assembly))


def require_coherent(
    assembly: ClaudeWriteAssembly, authorization: QualificationAuthorization,
) -> None:
    """Refuse drift before enrollment or recovery, including retained manifests."""
    try:
        QualificationAuthorization.model_validate(authorization.model_dump(mode="json"))
    except ValidationError as error:
        raise ContractViolation("Claude WRITE authorization violates its core contract") from error
    contained.require_contained_write(assembly.resources)
    provider, resources = assembly.executor, assembly.resources
    grants = fixed_grants(provider)
    pins = contained.contained_pins(resources, report_definition())
    if not (
        type(provider) is ClaudeOperatorProvider and provider.write
        and provider.recipe is ClaudeNativeRecipe.STREAM_JSON_WRITE
        and provider.launcher.claude_recipe is ClaudeNativeRecipe.STREAM_JSON_WRITE
        and provider.workspace_provider is resources.workspace
        and provider.worker_launcher == replace(resources.workspace.launcher,
                                                limits=WRITE_WORKER_LIMITS)
        and provider.workspace_capability_id == contained.WORKSPACE_CAPABILITY
        and provider.workspace_revision == str(pins.workspace.revision)
        and provider.expected_base == pins.fixture.base_commit
        and provider.profile.posture is Posture.WRITE
        and provider.identity.profile == provider.profile
        and provider.profile.grant_policy.tool_sets == (WRITE_CATALOG,)
        and provider.worker_launcher.limits == WRITE_WORKER_LIMITS
        and assembly.pins == pins and authorization.write == pins
        and authorization.stage == "qualification-write"
        and authorization.scope == fixed.WRITER_SCOPE
        and authorization.binding == fixed.EXECUTOR and authorization.capability_id == CAPABILITY
        and authorization.revision == provider.identity.revision
        and authorization.operator_binding_digest == provider.identity.store.operator_binding_digest
        and canonical_json(authorization.grants) == canonical_json(grants)
        and canonical_json(provider.qualification) == canonical_json(authorization)
        and authorization.source_graph_hash == source_graph_hash_for(graph(grants, pins))
        and Path(authorization.journal).is_absolute()
        and Path(authorization.journal).resolve() == Path(resources.journal._db_path).resolve()
        and Path(authorization.attempt_record or "").is_absolute()
    ):
        raise ContractViolation("authorization does not name this exact Claude WRITE assembly")
    retained = resources.journal.run_manifest_hash(authorization.run_id)
    if retained is not None:
        raw = resources.journal.load_manifest_json(retained)
        if raw is None or canonical_json(resources.journal.run_inputs(authorization.run_id)) != (
            canonical_json(fixed.write_inputs(authorization))
        ):
            raise ContractViolation("retained Claude WRITE inputs differ from authorization")
        expected = admit(graph(grants, pins), snapshot=resources.journal.snapshot(),
                         catalog=_catalog(assembly), capabilities=_capabilities(assembly),
                         root_grants=grants, inputs=fixed.write_inputs(authorization))
        if canonical_json(parse_manifest_json(raw)) != canonical_json(expected):
            raise ContractViolation("retained Claude WRITE manifest differs from actual assembly")


def _turn_facts(assembly: ClaudeWriteAssembly, authorization: QualificationAuthorization,
                rows: list[CapabilityLease], data: dict[str, Any], issues: set[Issue]) -> None:
    try:
        record = projection._attempt(Path(authorization.attempt_record or ""))
    except FileNotFoundError:
        issues.add(Issue.ATTEMPT_MISSING)
        return
    except Exception:
        issues.add(Issue.ATTEMPT_INVALID)
        return
    try:
        data["attempt_identity"] = digest("claude-write-attempt", 1, record)
        phase = record.get("phase")
        required = {"authorization_id", "run_id", "epoch", "acquisition_id", "phase", "at"}
        if phase not in ("acquired", "intent", "outcome") or set(record) != (
            required | {"callbacks"} | ({"dispatch", "facts"} if phase == "outcome" else set())
        ):
            raise ValueError("attempt shape")
        if datetime.fromisoformat(record["at"]).tzinfo is None:
            raise ValueError("attempt time")
        callbacks = CallbackObservation.model_validate(record["callbacks"])
        data["telemetry"] = WriteReportTelemetry(
            requested_model=fixed_grants(assembly.executor).model_selection.model,
            effort=authorization.grants.effort if authorization.grants else None,
            callbacks=callbacks, callbacks_final_snapshot=phase == "outcome",
        )
        path = ExecutionPath(scope=fixed.WRITER_SCOPE)
        logical = lease_id_for(authorization.run_id, path, fixed.EXECUTOR)
        executor_rows = [row for row in rows
                         if row.path == path and row.binding_id == fixed.EXECUTOR]
        if (type(record["epoch"]) is not int or record["epoch"] != 1
                or len(executor_rows) != 1 or executor_rows[0].acquisition_epoch != 1
                or executor_rows[0].lease_id != logical
                or record["authorization_id"] != authorization.authorization_id
                or record["run_id"] != authorization.run_id
                or record["acquisition_id"] != acquisition_id_for(logical, 1)):
            issues.add(Issue.ATTEMPT_MISMATCH)
        else:
            data.update(attempt_epoch=1, writer_lease_id=logical,
                        writer_acquisition_id=acquisition_id_for(logical, 1))
        if phase != "outcome":
            data["turn_dispatch"] = (
                "acquired-only" if phase == "acquired" else "possibly dispatched"
            )
            issues.add(Issue.ATTEMPT_NOT_COMPLETED)
            return
        facts = record["facts"]
        if not isinstance(facts, dict) or set(facts) != {
            "status", "callback_started", "callback_completed", "initial_binding_checked",
            "terminal_binding_checked", "relay_closed", "relay_denied", "relay_destinations",
        }:
            raise ValueError("attempt facts")
        data.update(turn_dispatch=record["dispatch"], turn_status=facts["status"])
        for name in ("relay_denied", "relay_destinations"):
            counts = facts[name]
            if type(counts) is not dict or any(type(count) is not int or count < 0
                    or len(repr(count)) > 32 for count in counts.values()):
                raise ValueError("relay counts")
        if (type(facts["callback_started"]) is not int
                or type(facts["callback_completed"]) is not int
                or facts["callback_started"] != callbacks.admitted_started
                or facts["callback_completed"] != callbacks.admitted_completed):
            raise ValueError("callback census")
        if (record["dispatch"] != "completed" or facts["status"] != "success"
                or facts["initial_binding_checked"] is not True
                or facts["terminal_binding_checked"] is not True
                or facts["relay_closed"] is not True or any(facts["relay_denied"].values())
                or not 1 <= callbacks.admitted_started <= 8 or not callbacks.responses_complete
                or any(result != "success" for result in callbacks.worker_results)):
            issues.add(Issue.ATTEMPT_NOT_COMPLETED)
    except Exception:
        issues.add(Issue.ATTEMPT_INVALID)


def derive_report(system: Constructicon, assembly: ClaudeWriteAssembly,
                  authorization: QualificationAuthorization,
                  observation: WriteObservation) -> WriteQualificationReport:
    grants = fixed_grants(assembly.executor)
    data, issues, rows = projection._capture_facts(
        system, assembly.resources, assembly.pins, authorization.run_id, observation,
        authorization=authorization, expected_graph=graph(grants, assembly.pins),
        writer_grants=grants, checker_grants=checker_grants(grants),
        report_definition=report_definition(),
    )
    data["authorization_identity"] = digest("qualification-authorization", 1, authorization)
    try:
        require_coherent(assembly, authorization)
        identity = assembly.executor.identity
        data["installed"] = WriteReportInstalledIdentities(
            capability_revision=Digest(identity.revision),
            **{field: getattr(identity, field)
               for field in WriteReportInstalledIdentities.model_fields
               if field != "capability_revision"},
        )
        limits = assembly.executor.launcher.limits
        data["limits"] = WriteReportLimits(
            exchange_s=grants.timeout_s, capture_s=grants.timeout_s, gate_s=30,
            check_s=max(spec.timeout_s for spec in assembly.resources.gate.checks),
            observation_s=fixed.OBSERVATION_TIMEOUT_S, callback_limit=8,
            program_bytes=WRITE_PROGRAM_BYTES, callback_output_bytes=WRITE_OUTPUT_BYTES,
            cumulative_input_bytes=limits.input_bytes, artifact_bytes=limits.artifact_bytes,
            stdout_bytes=limits.stdout_bytes, record_bytes=limits.record_bytes,
            stderr_bytes=limits.stderr_bytes,
        )
        _turn_facts(assembly, authorization, rows, data, issues)
    except ContractViolation:
        issues.add(Issue.AUTHORIZATION_MISMATCH)
    except Exception:
        issues.add(Issue.EVIDENCE_UNAVAILABLE)
    return projection._finish(WriteQualificationReport, data, issues)


async def qualify(*, assembly: ClaudeWriteAssembly,
                  authorization: QualificationAuthorization) -> WriteQualificationReport:
    require_coherent(assembly, authorization)
    journal = assembly.resources.journal
    _require_dedicated(journal, authorization)
    system = _system(assembly)
    actor = AuthenticatedActor(actor_id=authorization.actor_id, auth_method="static",
                               scopes=frozenset({READ_SCOPE, ADMIN_SCOPE}))
    observation: WriteObservation = "terminal"
    try:
        await _drive(system=system, journal=journal, actor=actor,
                     idempotency_key=authorization.idempotency_key,
                     expected_run_id=authorization.run_id,
                     graph=graph(fixed_grants(assembly.executor), assembly.pins),
                     definitions=definitions(), inputs=fixed.write_inputs(authorization),
                     timeout_s=fixed.OBSERVATION_TIMEOUT_S)
    except TimeoutError:
        observation = "timeout"
    except Exception:
        observation = "error"
    return derive_report(system, assembly, authorization, observation)


async def assemble(options: argparse.Namespace,
                   authorization: QualificationAuthorization | None = None) -> ClaudeWriteAssembly:
    configuration = read_configuration(options.launch_config,
                                       expected_sha256=options.launch_config_sha256)
    resource_launcher = LinuxLauncher(
        runtime_root=configuration.launch_root / "runtime",
        expected_runtime=configuration.runtime_digest,
        bubblewrap=configuration.launch_root / "bwrap", policy=configuration.launch_policy,
        expected_policy_sha256=configuration.launch_policy_sha256,
        launch_profile=LinuxLaunchProfile.CLAUDE_BOOTSTRAP,
    )
    worker = replace(resource_launcher, limits=WRITE_WORKER_LIMITS)
    journal = SqliteJournal(Path(authorization.journal) if authorization else options.journal)
    resources = await contained.assemble_contained_write(
        options.fixture, journal, resource_launcher,
    )
    host = ClaudeHostSession(
        configuration=options.launch_config, configuration_sha256=options.launch_config_sha256,
        store_root=options.store_root, store_key=options.store_key, sealed=options.sealed,
        qualification=options.qualification, acquisition_root=options.acquisition_root,
    )
    provider = operator_provider(host, workspace=resources.workspace,
        workspace_capability_id=contained.WORKSPACE_CAPABILITY,
        workspace_revision=str(resources.workspace.revision),
        expected_base=resources.fixture.base_commit,
        worker_launcher=worker, authorization=authorization)
    assembly = ClaudeWriteAssembly(provider, resources,
                                  contained.contained_pins(resources, report_definition()))
    if authorization is not None:
        require_coherent(assembly, authorization)
    return assembly


async def mint(options: argparse.Namespace) -> QualificationAuthorization:
    assembly = await assemble(options)
    provider = assembly.executor
    grants = fixed_grants(provider)
    return QualificationAuthorization(
        authorization_id=options.authorization_id, stage="qualification-write",
        actor_id=options.actor, idempotency_key=options.key, scope=fixed.WRITER_SCOPE,
        binding=fixed.EXECUTOR, capability_id=CAPABILITY,
        source_graph_hash=source_graph_hash_for(graph(grants, assembly.pins)),
        revision=provider.identity.revision,
        operator_binding_digest=provider.identity.store.operator_binding_digest,
        journal=str(options.journal), max_epoch=1,
        not_after=utc_now() + timedelta(hours=options.hours), grants=grants,
        attempt_record=str(options.attempt_record), write=assembly.pins,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="constructicon.api.claude_write_qualification",
                                     allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--fixture", type=Path, required=True)
    for name in ("mint", "run"):
        command = commands.add_parser(name)
        for path in ("fixture", "launch-config", "store-root", "sealed", "qualification",
                     "acquisition-root"):
            command.add_argument("--" + path, type=Path, required=True)
        command.add_argument("--launch-config-sha256", required=True)
        command.add_argument("--store-key", required=True)
        if name == "mint":
            for text in ("authorization-id", "actor", "key"):
                command.add_argument("--" + text, required=True)
            for path in ("journal", "attempt-record"):
                command.add_argument("--" + path, type=Path, required=True)
            command.add_argument("--hours", type=float, choices=(1., 2., 4.), default=1.)
        else:
            command.add_argument("--authorization", type=Path, required=True)
    options = parser.parse_args(argv)
    if options.command == "prepare":
        pin = contained.prepare_fixture(options.fixture)
        print(json.dumps({"fixture_identity": str(pin.identity)}))
        return 0
    if options.command == "mint":
        print(asyncio.run(mint(options)).model_dump_json())
        return 0

    async def run() -> WriteQualificationReport:
        authorization = read_authorization(options.authorization)
        return await qualify(assembly=await assemble(options, authorization),
                             authorization=authorization)

    report = asyncio.run(run())
    print(report.model_dump_json())
    return 0 if report.verdict == "passed" else 1


# Module-level PythonRef resolution survives reconstruction; helper edits also
# invalidate retained definitions rather than silently following old pins.
write_writer.__constructicon_adapter_revision__ = digest(  # type: ignore[attr-defined]
    "claude-write-qualification", 1,
    {"entry": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
     "capture": hashlib.sha256(Path(fixed.__file__).read_bytes()).hexdigest()},
)


if __name__ == "__main__":
    from constructicon.api import claude_write_qualification

    raise SystemExit(claude_write_qualification.main())
