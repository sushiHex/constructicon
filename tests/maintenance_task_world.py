"""A feasibility witness, never a model answer or an additional acceptance rule.

The full committed checkout tree supplies fixture data; its captured tree OID
is imported without history or network into a deterministic parentless base.
The scripted native peer replaces the vendor, while the real adapter mediates
its callback through the supplied portable or physically contained launcher.
"""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import tempfile
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

from constructicon.api import maintenance_entry as entry
from constructicon.api._maintenance_source import SOURCE_FILES, SOURCE_HASHES
from constructicon.api.plan_manifest_application import maintenance_graph
from constructicon.core.address import ExecutionPath
from constructicon.core.envelope import utc_now
from constructicon.core.identity import digest
from constructicon.core.maintenance import MaintenanceAttemptAuthorization, MaintenanceCapabilityPin
from constructicon.core.manifest import source_graph_hash_for
from constructicon.core.run import RunStatus
from constructicon.substrate.executors.codex import CodexOperatorProvider, launch_identity
from constructicon.substrate.executors.codex_host import WRITE_GRANTS as GRANTS
from constructicon.substrate.executors.codex_host import WRITE_PROFILE
from constructicon.substrate.executors.codex_protocol import CONTAINED_PYTHON_CATALOG
from constructicon.substrate.executors.linux import ProcessLimits
from constructicon.substrate.gates.contained import ContainedGateRunner
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
from constructicon.substrate.git.process import GitProcess
from tests.native_operator_world import native_egress
from tests.substrate.test_codex_adapter import (
    BINARY,
    EXPECTED,
    FINISHED,
    ScriptedLauncher,
    bare_launcher,
    descriptor_of,
)
from tests.substrate.test_codex_write import write_native


def task_vectors() -> bytes:
    """Independent input family: separated duplicates across ASCII line boundaries."""
    cases = [{"kind": "plan_path", "path": value} for value in (
        "handoffs/new.md", " a.md", "..md", ".md", "/absolute.md", "a/./b.md",
        "a/../b.md", "a\\b.md", "C:a.md", "a\n.md", "a\r.md", "report.txt",
    )]

    def records(blob: bytes) -> None:
        cases.append({"kind": "entries", "blob_hex": blob.hex()})

    first = b"a" * 64 + b"  handoffs/repeated.md"
    middle = b"b" * 64 + b"  other.md"
    repeated = b"c" * 64 + b"  handoffs/repeated.md"
    for boundary in (b"\n", b"\r", b"\r\n", b"\v", b"\f", b"\x1c", b"\x1d", b"\x1e"):
        records(boundary.join((first, middle)))
        records(boundary.join((first, middle, repeated)))
    records(b"A" * 64 + b"  upper.md\n")
    for marker in (b"<<<<<<<", b"|||||||", b"=======", b">>>>>>>"):
        records(marker + b" fixture\n" + first)
    records(b"\xff")
    return json.dumps({"version": 1, "cases": cases}, separators=(",", ":")).encode()


async def committed_tree_base(authority) -> str:
    repository = Path(__file__).resolve().parents[1]
    git = GitProcess(authority.git_executable, ProcessLimits())
    checkout = ("-c", f"safe.directory={repository.resolve().as_posix()}")
    # Resolve once: all later reads use this immutable tree, ignoring index and
    # working-copy edits. Shallow CI has the tree and blobs, but not old commits.
    tree = (await git.run(*checkout, "rev-parse", "HEAD^{tree}", cwd=repository)).strip()
    inventory = await git.run(*checkout, "ls-tree", "-r", "-z", tree.decode(), cwd=repository)
    assert inventory
    for name in SOURCE_FILES:
        source = await git.run(*checkout, "show", tree.decode() + ":" + name, cwd=repository)
        assert hashlib.sha256(source).hexdigest() == SOURCE_HASHES[name]
    return await import_fixture_tree(authority, repository, tree)


async def import_fixture_tree(authority, repository, tree: bytes) -> str:
    """Keep every committed blob/mode except the application's one output path."""
    git = GitProcess(authority.git_executable, ProcessLimits())
    # CI's checked-out source belongs to runner while the physical lane runs as
    # m8-service. Trust this exact read-only fixture source for this child only.
    checkout = ("-c", f"safe.directory={repository.resolve().as_posix()}")
    inventory = await git.run(*checkout, "ls-tree", "-r", "-z", tree.decode(), cwd=repository)
    expected = b"\0".join(record for record in inventory.split(b"\0")
        if not record.endswith(b"\ttests/vectors/plan_manifest.json"))
    pack = await git.run(*checkout, "pack-objects", "--stdout", "--revs", cwd=repository,
                         stdin=tree + b"\n")
    await git.run("index-pack", "--stdin", cwd=authority.repository_id, stdin=pack)
    # This index belongs only to the fresh scratch authority. A future retained
    # contribution cannot invalidate this reusable feasibility witness.
    await git.run("read-tree", tree.decode(), cwd=authority.repository_id)
    oid_width = 40 if authority.environment.object_format == "sha1" else 64
    await git.run("update-index", "--index-info", cwd=authority.repository_id,
        stdin=f"0 {'0' * oid_width}\ttests/vectors/plan_manifest.json\n".encode())
    fixture_tree = (await git.run("write-tree", cwd=authority.repository_id)).strip().decode()
    base = (await git.run("commit-tree", fixture_tree, cwd=authority.repository_id,
                         stdin=b"full committed-tree maintenance fixture\n")).strip().decode()
    await git.run("update-ref", "refs/heads/main", base, cwd=authority.repository_id)
    assert authority.tree_of(base) == fixture_tree
    assert authority.parents_of(base) == ()
    assert await git.run("ls-tree", "-r", "-z", base, cwd=authority.repository_id) == expected
    assert not await git.run("ls-tree", base, "--", "tests/vectors/plan_manifest.json",
                             cwd=authority.repository_id)
    if expected == inventory:
        assert fixture_tree == tree.decode()
    return base


@dataclass(frozen=True, kw_only=True)
class ScriptedWorkerLauncher(ScriptedLauncher):
    process_launcher: object

    async def run(self, command, **kwargs):
        return await self.process_launcher.run(command, **kwargs)


async def exercise_task_entry(
    resources, process_launcher, binding, tmp_path, monkeypatch, *, change,
):
    blob = task_vectors()
    program = (
        "from pathlib import Path\n"
        "p=Path('tests/vectors/plan_manifest.json')\n"
        "assert not p.exists()\n"
        + ("p.parent.mkdir(parents=True,exist_ok=True)\n" + f"p.write_bytes({blob!r})\n"
           if change else "")
        + "print('task callback completed')\n"
    )
    assert len(blob) <= 32768 and len(program.encode()) <= process_launcher.limits.input_bytes
    prototype = bare_launcher()
    scripted = ScriptedWorkerLauncher(
        **{name: getattr(prototype, name) for name in (
            "runtime_root", "expected_runtime", "bubblewrap", "policy", "expected_policy_sha256",
        )}, native=write_native(program=program), result=FINISHED,
        process_launcher=process_launcher,
    )
    # The real entry requires one exact launcher object for the executor and
    # workspace; the gate shares it too. Rebuild identified companion pins.
    workspace = ContainedWriteWorkspaceProvider(resources.authority,
        root=resources.workspace.root, target_ref=resources.workspace.target_ref,
        provider_id=resources.workspace.provider_id, posture=GRANTS.posture, launcher=scripted)
    gate = await ContainedGateRunner.create(journal=resources.journal,
        authority=resources.authority, root=resources.gate.root,
        target_ref=resources.gate.target_ref, provider_id=resources.gate.provider_id,
        launcher=scripted, checks=resources.gate.checks)
    resources = replace(resources, workspace=workspace, gate=gate,
        request=resources.request.model_copy(update={"check_set_hash": gate.check_set_hash}))
    configuration = (f'model = "{GRANTS.model_selection.model}"\n'
                     f'model_reasoning_effort = "{GRANTS.effort}"\n')
    identity = launch_identity(launcher=scripted, profile=WRITE_PROFILE,
        egress=native_egress(), store=binding[1].sealed,
        executable_digest=digest("test-task-binary", 1, BINARY), configuration=configuration,
        catalog=CONTAINED_PYTHON_CATALOG,
        authenticated_startup_conformance_revision=digest("test-task-startup", 1, "fixture"),
        subscription_mode_conformance_revision=digest("test-task-mode", 1, "fixture"))
    executor = CodexOperatorProvider(launcher=scripted, profile=WRITE_PROFILE, identity=identity,
        expected_account=EXPECTED, binary=BINARY, configuration=configuration,
        catalog=CONTAINED_PYTHON_CATALOG, acquisition_root=tmp_path / "executor",
        binding_store=binding[1], closure=binding[2])
    graph = maintenance_graph(executor_id="executor", workspace_id=resources.workspace.provider_id,
        gate_id=resources.gate.provider_id, writer_grants=GRANTS)
    authorization = MaintenanceAttemptAuthorization(
        authorization_id="full-tree-task-witness", actor_id="operator:test",
        idempotency_key="one-task", scope=entry.WRITER_SCOPE, binding="executor",
        source_graph_hash=source_graph_hash_for(graph), capability_id="executor",
        revision=executor.identity.revision,
        operator_binding_digest=executor.identity.store.operator_binding_digest,
        journal=str(Path(resources.journal._db_path).resolve()), max_epoch=1,
        not_after=utc_now() + timedelta(hours=1), grants=GRANTS,
        attempt_record=str(tmp_path / "task.attempt"), request=resources.request,
        application_revision=entry.maintenance_application_revision(),
        workspace=MaintenanceCapabilityPin(capability_id=resources.workspace.provider_id,
                                          revision=resources.workspace.revision),
        gate=MaintenanceCapabilityPin(capability_id=resources.gate.provider_id,
                                     revision=resources.gate.revision),
    )
    executor.maintenance = authorization
    from constructicon.substrate.executors import codex
    from tests.substrate.test_codex_write import portable_guard

    if os.name != "posix":
        monkeypatch.setattr(codex, "acquisition_guard", portable_guard)
    capture = []
    original_capture = resources.workspace.capture

    async def observe_capture(workspace, message):
        candidate = await original_capture(workspace, message)
        capture.append(candidate)
        return candidate

    monkeypatch.setattr(resources.workspace, "capture", observe_capture)
    result = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=descriptor_of(executor, "executor"), authorization=authorization)
    journal, run_id = resources.journal, authorization.run_id
    state = journal.run_state(run_id)
    assert state.status is (RunStatus.SUCCEEDED if change else RunStatus.FAILED), \
        journal.events(run_id, limit=100)
    assert state.owner_id is None and not journal.cancel_requested(run_id)
    assert scripted.native.methods.count("turn/start") == 1
    assert configuration.encode() in binding[0].configurations
    assert executor.identity.profile == WRITE_PROFILE and authorization.grants == GRANTS
    assert len(scripted.native.callback_responses) == 1
    assert scripted.native.callback_responses[0]["result"]["success"] is True
    assert scripted.native.callback_responses[0]["result"]["contentItems"] == [
        {"type": "inputText", "text": "task callback completed" + os.linesep},
    ]
    workers = [(command, kwargs) for command, kwargs in process_launcher.calls
               if kwargs.get("input_kind") == "task"]
    assert len(workers) == 1 and workers[0][1]["stdin"] == program.encode()
    record = json.loads(Path(authorization.attempt_record).read_bytes())
    assert record["phase"] == "outcome" and record["dispatch"] == "completed"
    assert record["facts"]["status"] == "success"
    assert record["callbacks"]["admitted_started"] == 1
    assert record["callbacks"]["admitted_completed"] == 1
    assert len(record["callbacks"]["worker_results"]) == 1
    assert record["callbacks"]["worker_results"] == ["success"]
    assert len(capture) == 1
    rows = journal.capability_leases(run_id)
    assert len(rows) == (3 if change else 2) and all(row.state == "closed" for row in rows)
    assert resources.authority.resolve_ref(resources.request.target_ref) \
        == resources.request.base_commit
    assert not list(resources.workspace.root.glob("payloads/*"))
    assert not list(resources.gate.root.glob("payloads/*"))
    published = Path(authorization.journal).parent / "maintenance-result.json"
    if not change:
        assert result is None and not published.exists()
        assert capture == [resources.request.base_commit]
        assert journal.checkpoint(run_id, ExecutionPath(scope=authorization.scope)) is None
        events = journal.events(run_id, limit=100)
        failures = [event for event in events if event.kind == "NodeFailed"]
        assert len(failures) == 1 and failures[0].payload == {
            "error_type": "ContractViolation",
            "error": "maintenance captured candidate equals the pinned base",
        }
        assert not any(event.kind == "NodeStarted" and event.path is not None
            and event.path.scope.segments[-1] == "checker" for event in events)
        return
    assert result is not None and published.exists()
    assert capture == [result.candidate.commit]
    assert resources.authority.parents_of(result.candidate.commit) \
        == (resources.request.base_commit,)
    attestation = journal.load_attestation(result.evaluation.attestation_id)
    assert attestation.ok and attestation.created_by_run == run_id
    assert attestation.subject == result.evaluation.subject
    report = json.loads(result.evaluation.checks[0].detail)
    assert report["baseline"] == {"tests_run": 34, "failures": 0, "errors": 0, "skips": 0}
    assert len(report["mutants"]) == 8
    assert all(item["distinguished"] and item["counts"]["failures"] > 0
               and item["counts"]["errors"] == item["counts"]["skips"] == 0
               for item in report["mutants"])
    assert result.input_sha256 == hashlib.sha256(blob).hexdigest()
    snapshot = resources.authority.read_snapshot(result.candidate.commit)
    try:
        snapshot_root = Path(snapshot.path)
        assert (snapshot_root / "tests/vectors/plan_manifest.json").read_bytes() == blob
        consumer_path = snapshot_root / "tests/test_plan_manifest_contribution.py"
        assert hashlib.sha256(consumer_path.read_bytes()).hexdigest() \
            == SOURCE_HASHES["tests/test_plan_manifest_contribution.py"]
        consumer_module = runpy.run_path(str(consumer_path))
        with monkeypatch.context() as consumer_environment:
            # The portable guarded remover deliberately accepts only this
            # test's root. Keep the consumer's genuine temporary scratch there.
            consumer_environment.setattr(tempfile, "tempdir", str(tmp_path))
            consumer = consumer_module["contribution_result"](snapshot_root)
        assert consumer is not None and consumer.passed
        assert consumer.input_sha256 == result.input_sha256
        assert consumer.render_sha256 == result.render_sha256
    finally:
        resources.authority.discard_snapshot(snapshot)
    assert entry.inspect_result(published)["meaning"] == "historical-application-acceptance"
