"""A fixed, autonomous WRITE/capture/check Graph; never installs its candidate.

The components consume L0 contracts. Concrete containment and Git evidence are
checked here at the L4 injection boundary, outside the ordinary walker.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.component import CapabilityRequirement, ComponentDef, PythonRef
from constructicon.core.envelope import GitRef
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import Executor, ExecutorProvider, ExecutorSuccess, TaskSpec
from constructicon.core.gates import MergeEvaluation, MergeGate
from constructicon.core.grants import EffectiveGrants, GrantRequest, Posture
from constructicon.core.graph import Connection, Graph, GraphNode, Ref
from constructicon.core.identity import canonical_json, digest
from constructicon.core.maintenance import (
    TARGET_PATH,
    VECTOR_PATH,
    PlanManifestRequest,
    PlanManifestResult,
)
from constructicon.core.ports import Port
from constructicon.core.run import RunStatus
from constructicon.core.workspace import AsyncWriteWorkspace
from constructicon.runtime.context import NodeContext, NodeImpl
from constructicon.runtime.registry import CapabilityDescriptor, source_digest_for
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.linux import ProcessLimits
from constructicon.substrate.gates.contained import ContainedGateRunner
from constructicon.substrate.gates.runner import CheckSpec
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
from constructicon.substrate.git.process import GitProcess
from constructicon.substrate.journal.sqlite import SqliteJournal

GRAPH_NAME = "constructicon-plan-manifest-maintenance"
WRITE_INSTRUCTION = (
    "Create only tests/vectors/plan_manifest.json as a regular nonexecutable UTF-8 file. "
    "It must be a JSON object with exactly version:1 and cases (1 to 64 items). "
    "Each case has exactly kind:'plan_path' and path (at most 256 ASCII characters), "
    "or kind:'entries' and blob_hex (canonical lowercase hexadecimal for at most "
    "1024 bytes of ASCII text or invalid UTF-8). The entire file is at most 32768 "
    "bytes. Propose regression cases for plan_path and entries in "
    "scripts/regen_plan_manifest.py. Do not add expected answers, executable code, "
    "or change any other file. The trusted harness supplies all expected answers."
)


def _port(name: str, model: type[BaseModel]) -> Port:
    schema = model.model_json_schema()
    return Port(name=name, type_id=f"constructicon.maintenance/{model.__name__}",
                schema_hash=str(digest("json-schema", 1, schema)), json_schema=schema)


REQUEST = _port("request", PlanManifestRequest)
CANDIDATE = _port("candidate", GitRef)
EVALUATION = _port("evaluation", MergeEvaluation)


async def maintenance_writer(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    request = PlanManifestRequest.model_validate(inputs["request"])
    workspace = ctx.capability("workspace")
    if not isinstance(workspace, AsyncWriteWorkspace):
        raise ContractViolation("maintenance requires an asynchronous WRITE workspace")
    initial = workspace.git_ref()
    if initial.repository != request.repository or initial.commit != request.base_commit:
        raise ContractViolation("maintenance workspace differs from the pinned base")
    executor = cast(Executor, ctx.capability("executor"))
    outcome = await executor.execute(
        TaskSpec(instruction=WRITE_INSTRUCTION), workspace=workspace, grants=ctx.grants,
    )
    if not isinstance(outcome, ExecutorSuccess):
        raise ContractViolation("maintenance writer did not positively succeed")
    captured = await workspace.commit_all("constructicon plan-manifest regression vectors")
    candidate = workspace.git_ref()
    if (
        candidate.commit != captured or candidate.commit == request.base_commit
        or candidate.repository != request.repository or candidate.paths
        or candidate.diff_against != request.base_commit
    ):
        raise ContractViolation("maintenance capture differs from the requested candidate")
    return {"candidate": candidate.model_dump(mode="json")}


async def maintenance_checker(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    request = PlanManifestRequest.model_validate(inputs["request"])
    candidate = GitRef.model_validate(inputs["candidate"])
    gate = ctx.capability("gate")
    if not isinstance(gate, MergeGate) or (
        candidate.repository != request.repository or candidate.diff_against != request.base_commit
        or candidate.paths or candidate.commit == request.base_commit
        or gate.target_ref != request.target_ref
    ):
        raise ContractViolation("maintenance checker received another candidate or gate")
    evaluation = await gate.verify(candidate.commit)
    subject = evaluation.subject
    if not evaluation.ok or subject is None or (
        subject.repository != request.repository or subject.target_ref != request.target_ref
        or subject.candidate != candidate.commit or subject.expected_base != request.base_commit
    ):
        raise ContractViolation("maintenance candidate failed its exact gate")
    return {"evaluation": evaluation.model_dump(mode="json")}


def maintenance_definitions() -> tuple[DefinitionBundle, DefinitionBundle]:
    revision = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    bundles = []
    for name, body, inputs, outputs, requirements in (
        ("constructicon.maintenance/plan-manifest-writer", maintenance_writer, (REQUEST,),
         (CANDIDATE,), (CapabilityRequirement(alias="workspace", kind="workspace.contained"),
                        CapabilityRequirement(alias="executor", kind="executor"))),
        ("constructicon.maintenance/plan-manifest-checker", maintenance_checker,
         (REQUEST, CANDIDATE), (EVALUATION,),
         (CapabilityRequirement(alias="gate", kind="gates.contained"),)),
    ):
        body.__constructicon_adapter_revision__ = revision  # type: ignore[attr-defined]
        definition = ComponentDef(
            name=name, role="node", inputs=inputs, outputs=outputs,
            capability_requirements=requirements,
            body=PythonRef(package="constructicon", module=__name__, qualname=body.__name__,
                contract_hash=digest("component-contract", 1, {
                    "inputs": [port.model_dump(mode="json") for port in inputs],
                    "outputs": [port.model_dump(mode="json") for port in outputs],
                }), source_digest=source_digest_for(body)),
        )
        bundles.append(DefinitionBundle(definition, cast(NodeImpl, body)))
    return bundles[0], bundles[1]


def maintenance_graph(
    *, executor_id: str, workspace_id: str, gate_id: str, writer_grants: EffectiveGrants,
) -> Graph:
    if writer_grants.posture is not Posture.WRITE:
        raise ContractViolation("maintenance writer requires explicit WRITE grants")
    writer, checker = maintenance_definitions()
    grants = GrantRequest(
        posture=Posture.WRITE, model=writer_grants.model_selection.model,
        effort=writer_grants.effort, allowed_tools=writer_grants.allowed_tools,
        env_allowlist=writer_grants.env_allowlist, network=writer_grants.network,
        timeout_s=writer_grants.timeout_s,
    )
    return Graph(
        name=GRAPH_NAME, inputs=(REQUEST,), outputs=(CANDIDATE, EVALUATION),
        nodes=(
            GraphNode(id="writer", body=Ref(component=writer.definition.name,
                version=str(writer.definition.content_hash()),
                bind={"executor": executor_id, "workspace": workspace_id}, grants=grants)),
            GraphNode(id="checker", body=Ref(component=checker.definition.name,
                version=str(checker.definition.content_hash()), bind={"gate": gate_id},
                grants=GrantRequest(posture=Posture.READ, allowed_tools=(), env_allowlist=(),
                                    network="none", timeout_s=120))),
        ), connections=(Connection(src="writer", dst="checker",
            map={"candidate": "writer.candidate", "request": "$input.request"}),),
    )


@dataclass(frozen=True)
class MaintenanceResources:
    journal: SqliteJournal
    authority: GitAuthority
    workspace: ContainedWriteWorkspaceProvider
    gate: ContainedGateRunner
    request: PlanManifestRequest
    target_source: bytes


async def _git(authority: GitAuthority, *args: str) -> bytes:
    return await GitProcess(authority.git_executable, ProcessLimits()).run(
        *args, cwd=Path(authority.repository_id),
    )


def maintenance_checks(
    target_source: bytes, target_sha256: str, baseline_inventory: bytes, object_format: str,
) -> tuple[CheckSpec, ...]:
    """The fixed exam embeds trusted code and pins every unchanged base blob."""
    from constructicon.substrate.gates import maintenance

    if hashlib.sha256(target_source).hexdigest() != target_sha256:
        raise ContractViolation("maintenance check target digest differs")
    if object_format not in {"sha1", "sha256"}:
        raise ContractViolation("maintenance check object format is unsupported")
    inventory: dict[str, tuple[str, str]] = {}
    for record in baseline_inventory.split(b"\0"):
        if not record:
            continue
        metadata, raw_name = record.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise ContractViolation("maintenance base has an unsupported tree entry")
        name = raw_name.decode("utf-8", errors="strict")
        if name == VECTOR_PATH or name in inventory:
            raise ContractViolation("maintenance vector exists or base inventory repeats a path")
        inventory[name] = mode, oid
    inventory_hash = hashlib.sha256(json.dumps(
        sorted((name, mode, oid) for name, (mode, oid) in inventory.items()),
        ensure_ascii=True, separators=(",", ":"),
    ).encode("ascii")).hexdigest()
    source = Path(maintenance.__file__).read_text(encoding="utf-8")
    # The gate's already verified immutable tree is the input. This comparison
    # forbids *all* other changed paths and modes before any passing attestation.
    program = (
        "import dataclasses,hashlib,json,linecache,os,pathlib,stat,sys,types\n"
        f"expected_hash={inventory_hash!r}\n"
        f"allowed={VECTOR_PATH!r}\nobject_format={object_format!r}\n"
        "observed=[]\n"
        "for p in pathlib.Path('.').rglob('*'):\n"
        " name=p.as_posix()\n"
        " if p.is_symlink():\n"
        "  mode='120000';raw=os.fsencode(os.readlink(p))\n"
        " elif p.is_file():\n"
        "  if name==allowed: assert p.stat().st_size<=32768\n"
        "  mode='100755' if p.stat().st_mode & 0o111 else '100644';raw=p.read_bytes()\n"
        " else:\n"
        "  continue\n"
        " if name==allowed:\n"
        "  assert mode=='100644' and len(raw)<=32768\n"
        "  continue\n"
        " oid=hashlib.new(object_format,f'blob {len(raw)}\\0'.encode()+raw).hexdigest()\n"
        " observed.append((name,mode,oid))\n"
        "actual_hash=hashlib.sha256(json.dumps(sorted(observed),ensure_ascii=True,"
        "separators=(',',':')).encode('ascii')).hexdigest()\n"
        "assert actual_hash==expected_hash\n"
        "p=pathlib.Path(allowed)\n"
        "assert stat.S_ISREG(p.lstat().st_mode) and not (p.lstat().st_mode & 0o111)\n"
        "m=types.ModuleType('trusted_plan_manifest_vectors')\n"
        "sys.modules[m.__name__]=m\n"
        "filename='<trusted-plan-manifest-vectors>'\n"
        "m.__file__=filename\n"
        f"source={source!r}\n"
        "linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)\n"
        "exec(compile(source,filename,'exec'),m.__dict__)\n"
        f"report=m.run_vectors(p.read_bytes(),{target_source!r},{target_sha256!r})\n"
        "assert report.passed\n"
        "summary=json.dumps(dataclasses.asdict(report),sort_keys=True,separators=(',',':'))\n"
        "assert len(summary.encode('ascii'))<=4096\n"
        "print(summary)\n"
    )
    if len(program.encode("utf-8")) > 120_000:
        raise ContractViolation("maintenance trusted check exceeds the fixed argument bound")
    return (CheckSpec(name="plan-manifest-trusted-vectors",
                      argv=("/usr/bin/python3", "-I", "-c", program), timeout_s=120),)


async def require_maintenance_resources(resources: MaintenanceResources) -> None:
    """Refuse relabeled resources, target drift, and a candidate-defined check."""
    PlanManifestRequest.model_validate(resources.request.model_dump(mode="json"))
    request, authority, workspace, gate = (
        resources.request, resources.authority, resources.workspace, resources.gate,
    )
    if not (
        isinstance(resources.journal, SqliteJournal) and isinstance(authority, GitAuthority)
        and isinstance(workspace, ContainedWriteWorkspaceProvider)
        and isinstance(gate, ContainedGateRunner)
        and gate.is_assembled_from(resources.journal)
        and workspace.authority is authority and gate.authority is authority
        and workspace.launcher is gate.launcher and workspace.posture is Posture.WRITE
        and workspace.target_ref == gate.target_ref == request.target_ref
        and authority.repository_id == request.repository
        and workspace.provider_id != gate.provider_id
        and workspace.root != gate.root
    ):
        raise ContractViolation("maintenance resources differ from the concrete trusted assembly")
    if hashlib.sha256(resources.target_source).hexdigest() != request.target_sha256:
        raise ContractViolation("maintenance trusted target digest differs")
    actual_base = (await _git(authority, "rev-parse", "--verify", request.target_ref)).strip()
    source = await _git(authority, "show", f"{request.base_commit}:{TARGET_PATH}")
    existing = await _git(authority, "ls-tree", request.base_commit, "--", VECTOR_PATH)
    inventory = await _git(authority, "ls-tree", "-r", "-z", request.base_commit)
    expected_checks = maintenance_checks(resources.target_source, request.target_sha256, inventory,
                                         authority.environment.object_format)
    revision = await finish_owned(asyncio.create_task(asyncio.to_thread(
        lambda: gate.check_set_hash,
    )))
    if actual_base.decode("ascii") != request.base_commit or source != resources.target_source:
        raise ContractViolation("maintenance base or target source drifted")
    if existing or revision != request.check_set_hash or gate.checks != expected_checks:
        raise ContractViolation("maintenance vector already exists or gate recipe drifted")


async def maintenance_system(
    resources: MaintenanceResources, *, executor_id: str, executor: object,
    executor_descriptor: CapabilityDescriptor, writer_grants: EffectiveGrants,
) -> Constructicon:
    """Inject existing resources; never creates or enables a production executor."""
    await require_maintenance_resources(resources)
    if executor_id in {resources.workspace.provider_id, resources.gate.provider_id}:
        raise ContractViolation("maintenance capability identities must be distinct")
    if not isinstance(executor, ExecutorProvider) or (
        executor_descriptor.capability_id != executor_id
        or executor_descriptor.kind != "executor" or not executor_descriptor.leased
        or executor_descriptor.executor_incoherence(executor) is not None
        or executor.unavailable_reasons
        or writer_grants.posture is not Posture.WRITE
    ):
        raise ContractViolation("maintenance requires an available, exact leased executor binding")
    return Constructicon(
        journal=resources.journal, root_grants=writer_grants,
        capabilities={executor_id: executor, resources.workspace.provider_id: resources.workspace,
                      resources.gate.provider_id: resources.gate},
        catalog={
            executor_id: executor_descriptor,
            resources.workspace.provider_id: CapabilityDescriptor(
                capability_id=resources.workspace.provider_id, kind="workspace.contained",
                revision=resources.workspace.revision, leased=True, requires_posture=Posture.WRITE,
            ),
            resources.gate.provider_id: CapabilityDescriptor(
                capability_id=resources.gate.provider_id, kind="gates.contained",
                revision=resources.gate.revision, leased=True,
            ),
        },
    )


async def derive_maintenance_result(
    system: Constructicon, resources: MaintenanceResources, run_id: RunId,
) -> PlanManifestResult:
    """Affirm the exact candidate/tree, journal proof, and sole new data file."""
    from constructicon.substrate.gates.maintenance import parse_vectors, render_unittest

    await require_maintenance_resources(resources)
    journal, request, authority = resources.journal, resources.request, resources.authority
    if system._journal is not journal or (
        system._capabilities.get(resources.workspace.provider_id) is not resources.workspace
        or system._capabilities.get(resources.gate.provider_id) is not resources.gate
    ):
        raise ContractViolation("maintenance result requires the exact assembled system world")
    state = journal.run_state(run_id)
    if state is None or state.status is not RunStatus.SUCCEEDED:
        raise ContractViolation("maintenance run did not succeed")
    manifest = system.manifest_for_run(run_id)
    bindings = {
        (binding.scope.render(), binding.binding): binding
        for binding in manifest.capability_bindings
        if binding.binding in {"executor", "workspace", "gate"}
    }
    writer_key, workspace_key, gate_key = (
        (GRAPH_NAME + "/writer", "executor"),
        (GRAPH_NAME + "/writer", "workspace"),
        (GRAPH_NAME + "/checker", "gate"),
    )
    if set(bindings) != {writer_key, workspace_key, gate_key}:
        raise ContractViolation("maintenance manifest has another capability boundary")
    expected_graph = maintenance_graph(
        executor_id=bindings[writer_key].capability_id,
        workspace_id=resources.workspace.provider_id, gate_id=resources.gate.provider_id,
        writer_grants=bindings[writer_key].effective_grants,
    )
    if (
        canonical_json(manifest.source_graph) != canonical_json(expected_graph)
        or bindings[workspace_key].revision != resources.workspace.revision
        or bindings[gate_key].revision != resources.gate.revision
    ):
        raise ContractViolation("maintenance manifest differs from the fixed admitted Graph")
    if canonical_json(system.inputs_for_run(run_id)) != canonical_json(
        {"request": request.model_dump(mode="json")}
    ):
        raise ContractViolation("maintenance run recorded another request")
    outputs = system.materialize_run(run_id)
    candidate = GitRef.model_validate(outputs["candidate"])
    evaluation = MergeEvaluation.model_validate(outputs["evaluation"])
    subject = evaluation.subject
    attestation = journal.load_attestation(evaluation.attestation_id or "")
    if not evaluation.ok or subject is None or attestation is None or not attestation.ok or (
        attestation.action != "merge" or attestation.created_by_run != run_id
        or attestation.manifest_hash != manifest.manifest_hash
        or attestation.check_set_hash != request.check_set_hash
        or canonical_json(attestation.subject) != canonical_json(subject)
        or canonical_json(attestation.checks) != canonical_json(evaluation.checks)
        or tuple(check.name for check in attestation.checks)
        != tuple(spec.name for spec in resources.gate.checks)
        or candidate.repository != request.repository or candidate.paths
        or candidate.diff_against != request.base_commit
        or subject.repository != request.repository or subject.target_ref != request.target_ref
        or subject.candidate != candidate.commit or subject.expected_base != request.base_commit
    ):
        raise ContractViolation("maintenance attestation does not affirm this run and candidate")
    tree = (await _git(authority, "rev-parse", f"{candidate.commit}^{{tree}}")).strip().decode()
    merged_tree = (await _git(authority, "rev-parse", f"{subject.merge_commit}^{{tree}}"))
    parents = (await _git(authority, "rev-list", "--parents", "-n", "1", subject.merge_commit))
    delta = await _git(authority, "diff-tree", "--no-commit-id", "--raw", "-r", "-z",
                       "--no-renames", request.base_commit, candidate.commit)
    fields = delta.split(b"\0")
    metadata = fields[0].split() if fields else []
    if (
        subject.tested_tree != tree or merged_tree.strip().decode() != tree
        or parents.split()[1:] != [request.base_commit.encode(), candidate.commit.encode()]
        or len(fields) != 3 or fields[1] != VECTOR_PATH.encode() or fields[2]
        or len(metadata) != 5 or metadata[0] != b":000000" or metadata[1] != b"100644"
        or metadata[4] != b"A"
    ):
        raise ContractViolation("maintenance candidate changed more than its one new data file")
    blob = await _git(authority, "show", f"{candidate.commit}:{VECTOR_PATH}")
    rendered = render_unittest(parse_vectors(blob), resources.target_source,
                               trusted_target_sha256=request.target_sha256)
    await require_maintenance_resources(resources)
    return PlanManifestResult(
        run_id=run_id, candidate=candidate, evaluation=evaluation,
        input_sha256=hashlib.sha256(blob).hexdigest(),
        render_sha256=hashlib.sha256(rendered).hexdigest(),
    )
