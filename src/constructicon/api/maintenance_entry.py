"""Trusted one-attempt maintenance entry; ordinary Graph and control-plane lifecycle.

Only ``run`` starts recovery. ``inspect`` reports previously stored evidence and
does no assembly, current-world verification, provider probing or journal work.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from constructicon.api._maintenance_identity import (
    maintenance_application_revision as maintenance_application_revision,
)
from constructicon.api._maintenance_source import (
    git,
    inspect_source,
    prepare_source,
    read_bounded,
    write_once,
)
from constructicon.api.control import ControlPlane
from constructicon.api.plan_manifest_application import (
    GRAPH_NAME,
    MaintenanceResources,
    derive_maintenance_result,
    maintenance_checks,
    maintenance_definitions,
    maintenance_graph,
    maintenance_system,
    require_maintenance_resources,
)
from constructicon.api.system import Constructicon
from constructicon.core.address import GitSha, ScopePath
from constructicon.core.control import (
    ADMIN_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    PromotionCommandResult,
    RegistrationCommandResult,
    RunSubmission,
)
from constructicon.core.envelope import utc_now
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorProvider
from constructicon.core.grants import Posture
from constructicon.core.identity import Digest, canonical_json, digest, parse_json_value
from constructicon.core.maintenance import (
    TARGET_PATH,
    MaintenanceAttemptAuthorization,
    MaintenanceCapabilityPin,
    PlanManifestRequest,
    PlanManifestResult,
)
from constructicon.core.manifest import parse_manifest_json, source_graph_hash_for
from constructicon.core.run import RunStatus
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.runtime.validator import admit
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors import codex_lane
from constructicon.substrate.executors.codex import CodexOperatorProvider
from constructicon.substrate.executors.codex_host import (
    WRITE_GRANTS,
    HostSession,
    maintenance_operator_provider,
    write_operator_provider,
)
from constructicon.substrate.executors.maintenance import read_maintenance_authorization
from constructicon.substrate.executors.qualification import MAX_AUTHORIZATION_BYTES
from constructicon.substrate.gates.contained import ContainedGateRunner
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
from constructicon.substrate.journal.sqlite import SqliteJournal

EXECUTOR = "codex-operator"
WORKSPACE = "maintenance-workspace"
GATE = "maintenance-gate"
WRITER_SCOPE = ScopePath(segments=(GRAPH_NAME, "writer"))
MAX_RESULT_BYTES = 65536


@dataclass(frozen=True)
class MaintenanceAssembly:
    resources: MaintenanceResources
    executor: CodexOperatorProvider
    descriptor: CapabilityDescriptor


async def assemble_maintenance(
    *, host: HostSession, root: Path, journal: SqliteJournal,
    authorization: MaintenanceAttemptAuthorization | None = None,
) -> MaintenanceAssembly:
    pin = await inspect_source(root)  # Before authority constructor writes its hook.
    authority = GitAuthority(root / "authority.git", root / "authority-workspaces")
    launcher = codex_lane._launcher(host.launch_root)
    workspace = ContainedWriteWorkspaceProvider(authority, root=root / "workspace-acquisitions",
        target_ref=pin.target_ref, provider_id=WORKSPACE, posture=Posture.WRITE, launcher=launcher)
    source = await git(root / "authority.git", "show", f"{pin.base_commit}:{TARGET_PATH}")
    inventory = await git(root / "authority.git", "ls-tree", "-r", "-z", pin.base_commit)
    before = workspace.revision
    gate = await ContainedGateRunner.create(journal=journal, authority=authority,
        root=root / "gate-acquisitions", target_ref=pin.target_ref, provider_id=GATE,
        launcher=launcher, checks=maintenance_checks(source, hashlib.sha256(source).hexdigest(),
            inventory, authority.environment.object_format))
    request = PlanManifestRequest(repository=authority.repository_id, target_ref=pin.target_ref,
        base_commit=pin.base_commit, target_sha256=hashlib.sha256(source).hexdigest(),
        check_set_hash=gate.check_set_hash)
    resources = MaintenanceResources(journal, authority, workspace, gate, request, source)
    executor = (write_operator_provider(host, workspace) if authorization is None
                else maintenance_operator_provider(host, workspace, authorization))
    descriptor = CapabilityDescriptor(capability_id=EXECUTOR, kind="executor", leased=True,
        revision=executor.identity.revision, executor_profile=executor.profile)
    # Assembly probes awaited; affirm custody, immutable code and base again.
    await inspect_source(root)
    await require_maintenance_resources(resources)
    if workspace.revision != before:
        raise ContractViolation("maintenance workspace changed during assembly")
    return MaintenanceAssembly(resources, executor, descriptor)


async def require_maintenance_attempt(
    resources: MaintenanceResources, executor: ExecutorProvider,
    descriptor: CapabilityDescriptor, authorization: MaintenanceAttemptAuthorization,
) -> None:
    """Before RunHost startup: exact world, journal, retained inputs and descriptors."""
    authorization = MaintenanceAttemptAuthorization.model_validate_json(
        authorization.model_dump_json(),
    )
    await require_maintenance_resources(resources)
    graph = maintenance_graph(executor_id=authorization.capability_id,
        workspace_id=resources.workspace.provider_id, gate_id=resources.gate.provider_id,
        writer_grants=authorization.grants)
    journal = resources.journal
    journal_path = Path(authorization.journal)
    attempt_path = Path(authorization.attempt_record)
    if not (
        authorization.request == resources.request
        and authorization.application_revision == maintenance_application_revision()
        and authorization.scope == WRITER_SCOPE and authorization.binding == "executor"
        and authorization.source_graph_hash == source_graph_hash_for(graph)
        and authorization.workspace == MaintenanceCapabilityPin(
            capability_id=resources.workspace.provider_id, revision=resources.workspace.revision)
        and authorization.gate == MaintenanceCapabilityPin(
            capability_id=resources.gate.provider_id, revision=resources.gate.revision)
        and journal_path.is_absolute() and journal_path.resolve() == journal_path
        and journal_path == Path(journal._db_path).resolve()
        and attempt_path.is_absolute() and attempt_path.resolve() == attempt_path
        and attempt_path.parent == journal_path.parent and attempt_path != journal_path
        and authorization.revision == str(executor.identity.revision)
        and descriptor.capability_id == authorization.capability_id
        and descriptor.kind == "executor" and descriptor.leased
        and descriptor.executor_incoherence(executor) is None
        and canonical_json(getattr(executor, "maintenance", None)) == canonical_json(authorization)
    ):
        raise ContractViolation("maintenance authorization differs from actual assembled resources")
    if isinstance(executor, CodexOperatorProvider) and (
        authorization.operator_binding_digest != executor.identity.store.operator_binding_digest
        or executor.launcher is not resources.workspace.launcher
    ):
        raise ContractViolation("maintenance operator binding differs")
    definitions = maintenance_definitions()
    expected_versions = {bundle.definition.name: str(bundle.definition.content_hash())
                         for bundle in definitions}
    snapshot = journal.snapshot()
    for name, versions in snapshot.versions.items():
        if name not in expected_versions or set(versions) != {expected_versions[name]}:
            raise ContractViolation("maintenance journal retains another component")
    for record in journal.run_records(limit=2):
        if record.run_id != authorization.run_id:
            raise ContractViolation("maintenance journal holds another run")
        retained_hash = journal.run_manifest_hash(record.run_id)
        raw = None if retained_hash is None else journal.load_manifest_json(retained_hash)
        inputs = {"request": resources.request.model_dump(mode="json")}
        if raw is None or (
            canonical_json(journal.run_inputs(record.run_id)) != canonical_json(inputs)
        ):
            raise ContractViolation("maintenance retained inputs differ or are unavailable")
        catalog = {
            authorization.capability_id: descriptor,
            resources.workspace.provider_id: CapabilityDescriptor(
                capability_id=resources.workspace.provider_id, kind="workspace.contained",
                revision=resources.workspace.revision, leased=True, requires_posture=Posture.WRITE),
            resources.gate.provider_id: CapabilityDescriptor(
                capability_id=resources.gate.provider_id, kind="gates.contained",
                revision=resources.gate.revision, leased=True),
        }
        expected = admit(graph, snapshot=snapshot, catalog=catalog,
            root_grants=authorization.grants,
            capabilities={authorization.capability_id: executor,
                          resources.workspace.provider_id: resources.workspace,
                          resources.gate.provider_id: resources.gate}, inputs=inputs)
        if canonical_json(parse_manifest_json(raw)) != canonical_json(expected):
            raise ContractViolation("maintenance retained manifest differs from exact assembly")


class _StoredResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    meaning: Literal["historical-application-acceptance"] = "historical-application-acceptance"
    authorization_digest: Digest
    result: PlanManifestResult


def inspect_result(path: Path) -> dict[str, object]:
    """Historical file observation only; no claim of current validity or authenticity."""
    raw = read_bounded(path, MAX_RESULT_BYTES).decode("utf-8", errors="strict")
    stored = _StoredResult.model_validate(parse_json_value(raw))
    result = stored.result
    if re.fullmatch(r"run-[0-9a-f]{32}", result.run_id) is None or (
        re.fullmatch(r"[0-9a-f]{40}([0-9a-f]{24})?", result.candidate.commit) is None
    ):
        raise ContractViolation("maintenance historical evidence has malformed public identifiers")
    return {"schema_version": 1, "meaning": stored.meaning, "run_id": str(result.run_id),
            "input_sha256": result.input_sha256, "render_sha256": result.render_sha256,
            "candidate_commit": str(result.candidate.commit)}


async def run_maintenance(
    *, resources: MaintenanceResources, executor: ExecutorProvider,
    executor_descriptor: CapabilityDescriptor, authorization: MaintenanceAttemptAuthorization,
    timeout_s: float = 1200,
) -> PlanManifestResult | None:
    await require_maintenance_attempt(resources, executor, executor_descriptor, authorization)
    system: Constructicon = await maintenance_system(resources,
        executor_id=authorization.capability_id, executor=executor,
        executor_descriptor=executor_descriptor, writer_grants=authorization.grants)
    # Admission/system construction is not permission to recover a changed journal.
    await require_maintenance_attempt(resources, executor, executor_descriptor, authorization)
    actor = AuthenticatedActor(actor_id=authorization.actor_id, auth_method="static",
                               scopes=frozenset({READ_SCOPE, ADMIN_SCOPE}))
    control = ControlPlane(system=system, store=resources.journal)
    try:
        await control.startup()
        for bundle in maintenance_definitions():
            version = str(bundle.definition.content_hash())
            registered = await control.registry_register(actor, definition=bundle,
                idempotency_key="maintenance-register-" + version)
            if not isinstance(registered, RegistrationCommandResult):
                raise ContractViolation("maintenance fixed registration failed")
            promoted = await control.registry_promote_initial(actor,
                component=registered.component, version=registered.version,
                idempotency_key="maintenance-promote-" + version)
            if not isinstance(promoted, PromotionCommandResult):
                raise ContractViolation("maintenance fixed promotion failed")
        submitted = await control.runs_start(actor, proposal=maintenance_graph(
            executor_id=authorization.capability_id, workspace_id=resources.workspace.provider_id,
            gate_id=resources.gate.provider_id, writer_grants=authorization.grants),
            inputs={"request": resources.request.model_dump(mode="json")},
            idempotency_key=authorization.idempotency_key)
        if not isinstance(submitted, RunSubmission) or submitted.run_id != authorization.run_id:
            raise ContractViolation("maintenance exact run was not admitted")
        async with asyncio.timeout(timeout_s):
            while True:
                state = resources.journal.run_state(authorization.run_id)
                if state is None:
                    raise ContractViolation("maintenance admitted run has no durable state")
                if state.status not in {RunStatus.PENDING, RunStatus.RUNNING}:
                    break
                await asyncio.sleep(0.05)
    finally:
        await finish_owned(asyncio.create_task(control.shutdown()))
    if state.status is not RunStatus.SUCCEEDED:
        return None
    result = await derive_maintenance_result(system, resources, authorization.run_id)
    stored = _StoredResult(authorization_digest=digest("maintenance-authorization", 1,
        authorization.model_dump(mode="json")), result=result)
    raw = stored.model_dump_json().encode()
    if len(raw) > MAX_RESULT_BYTES:
        raise ContractViolation("maintenance accepted evidence exceeds publication bound")
    path = Path(authorization.journal).parent / "maintenance-result.json"
    if path.exists():
        if read_bounded(path, MAX_RESULT_BYTES) != raw:
            raise ContractViolation("maintenance previously stored evidence differs")
    else:
        write_once(path, raw)
    return result


def _host(args: argparse.Namespace) -> HostSession:
    return HostSession(session=args.session, store_key=args.store_key, sealed=args.sealed,
                       qualification=args.qualification, state=args.state,
                       launch_root=args.launch_root)


def _authorization_preview(authorization: MaintenanceAttemptAuthorization) -> dict[str, object]:
    preview: dict[str, object] = authorization.model_dump(mode="json")
    raw = json.dumps(preview, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) + 1 > MAX_AUTHORIZATION_BYTES:
        raise ContractViolation("maintenance proposed authorization exceeds its reader bound")
    return preview


async def _command(args: argparse.Namespace) -> object:
    if args.command == "prepare":
        return (await prepare_source(args.root, args.bundle, bundle_sha256=args.bundle_sha256,
            base_commit=GitSha(args.base), target_ref=args.target_ref)).model_dump(mode="json")
    if args.command == "inspect":
        return inspect_result(args.result)
    await inspect_source(args.root)
    journal_path = args.root / "maintenance.sqlite"
    authorization = (read_maintenance_authorization(args.authorization)
                     if args.command == "run" else None)
    if authorization is not None and Path(authorization.journal) != journal_path:
        raise ContractViolation("maintenance authorization names another dedicated journal")
    journal = SqliteJournal(journal_path)
    assembly = await assemble_maintenance(host=_host(args), root=args.root, journal=journal,
                                          authorization=authorization)
    if args.command == "preflight":
        authorization = MaintenanceAttemptAuthorization(authorization_id=args.authorization_id,
            actor_id=args.actor, idempotency_key=args.key, scope=WRITER_SCOPE, binding="executor",
            source_graph_hash=source_graph_hash_for(maintenance_graph(executor_id=EXECUTOR,
                workspace_id=WORKSPACE, gate_id=GATE, writer_grants=WRITE_GRANTS)),
            capability_id=EXECUTOR, revision=str(assembly.executor.identity.revision),
            operator_binding_digest=assembly.executor.identity.store.operator_binding_digest,
            journal=str(journal_path), max_epoch=1, not_after=utc_now() + timedelta(hours=1),
            grants=WRITE_GRANTS, attempt_record=str(args.root / "maintenance-attempt.json"),
            request=assembly.resources.request,
            application_revision=maintenance_application_revision(),
            workspace=MaintenanceCapabilityPin(capability_id=WORKSPACE,
                revision=assembly.resources.workspace.revision),
            gate=MaintenanceCapabilityPin(capability_id=GATE,
                                          revision=assembly.resources.gate.revision))
        return _authorization_preview(authorization)
    if authorization is None:
        raise ContractViolation("maintenance run requires installed authority")
    result = await run_maintenance(resources=assembly.resources, executor=assembly.executor,
        executor_descriptor=assembly.descriptor, authorization=authorization)
    return {"accepted": result is not None, "run_id": str(authorization.run_id)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--root", type=Path, required=True)
    prepare.add_argument("--bundle", type=Path, required=True)
    prepare.add_argument("--bundle-sha256", required=True)
    prepare.add_argument("--base", required=True)
    prepare.add_argument("--target-ref", default="refs/heads/maintenance")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--result", type=Path, required=True)
    for command in ("preflight", "run"):
        child = commands.add_parser(command)
        for name in ("root", "session", "sealed", "qualification", "state", "launch-root"):
            child.add_argument("--" + name, type=Path, required=True)
        child.add_argument("--store-key", required=True)
        if command == "run":
            child.add_argument("--authorization", type=Path, required=True)
        else:
            for name in ("authorization-id", "actor", "key"):
                child.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(_command(args))
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    except Exception:
        # No private path, subprocess text, credentials or uncertain retry advice.
        print('{"accepted":false,"error":"maintenance command refused or incomplete"}')
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
