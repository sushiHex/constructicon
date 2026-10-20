"""The maintenance application runs its real Graph with genuine L0 doubles."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from constructicon.api.control import ControlPlane
from constructicon.api.plan_manifest_application import (
    WRITE_INSTRUCTION,
    MaintenanceResources,
    derive_maintenance_result,
    maintenance_checks,
    maintenance_definitions,
    maintenance_graph,
    maintenance_system,
    maintenance_writer,
    require_maintenance_resources,
)
from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, GitSha, RunId, ScopePath
from constructicon.core.control import RegistrationCommandResult, RunSubmission
from constructicon.core.effect import AttestationDraft, CheckResult, MergeSubject
from constructicon.core.envelope import GitRef
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import (
    ExecutorGrantPolicy,
    ExecutorPartial,
    ExecutorProfile,
    ExecutorSuccess,
    TransportDamage,
)
from constructicon.core.gates import MergeEvaluation
from constructicon.core.grants import IsolationProfile, Posture
from constructicon.core.graph import Graph
from constructicon.core.identity import digest
from constructicon.core.maintenance import PlanManifestRequest
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.linux import ProcessLimits, ProcessResult
from constructicon.substrate.gates.contained import ContainedGateRunner
from constructicon.substrate.git import acquisition, contained
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
from constructicon.substrate.git.process import GitProcess
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import LOCAL_ADMIN, RUN_ACTOR
from tests.captureworld import ControlledAsyncWorkspace, ControlledWorkspaceProvider
from tests.conftest import LEASE_TTL_S, FakeClock
from tests.executorworld import FakeExecutorProvider, launch_identity
from tests.gateworld import ControlledGate, ControlledGateProvider
from tests.gitworld import WRITE_GRANTS, seed_authority
from tests.runtime.test_async_workspace import until

BASE, CANDIDATE, TREE, MERGE = (GitSha(char * 40) for char in "abcd")
CHECK_SET = digest("maintenance-fake-check-set", 1, "fixed")
REQUEST = PlanManifestRequest(
    repository="fake-authority", target_ref="refs/heads/main", base_commit=BASE,
    target_sha256="f" * 64, check_set_hash=CHECK_SET,
)
INPUTS = {"request": REQUEST.model_dump(mode="json")}


class Writer:
    """A WRITE-capable task fake; no physical-isolation claim for live code."""

    profile = ExecutorProfile(
        name="maintenance-writing-double", structured_output=False,
        postures=frozenset({Posture.WRITE}),
        isolation=IsolationProfile(filesystem="workspace_only", process_tree_owned=True,
                                   environment_allowlisted=True, network_enforced=True),
        grant_policy=ExecutorGrantPolicy(tool_sets=((),), network_modes=("none",),
            network_access="none", environment_names=(), workspace_required=True),
    )

    def __init__(self, *, partial=False):
        self.calls = []
        self.partial = partial

    def validate_grants(self, grants):
        return self.profile.grant_faults(grants)

    async def execute(self, task, *, workspace, grants):
        assert not self.validate_grants(grants)
        assert task.instruction == WRITE_INSTRUCTION and task.context == ()
        assert task.response_schema is None and workspace.ready
        self.calls.append(task)
        if self.partial:
            return ExecutorPartial(damage=TransportDamage(
                malformed_records=1, first_error="damaged", evidence_excerpt=None,
            ))
        return ExecutorSuccess(raw_reply="vector data proposed")


class WorkspaceProvider(ControlledWorkspaceProvider):
    revision = "maintenance-workspace-double-v1"

    async def acquire(self, context):
        acquired = await super().acquire(context)
        acquired.resource.reference = GitRef(
            repository=REQUEST.repository, commit=BASE, diff_against=BASE,
        )
        acquired.resource.commit_allowed.set()
        return acquired


@pytest.mark.parametrize(("changes", "captured", "message"), [
    ({}, CANDIDATE, None),
    ({"commit": TREE}, CANDIDATE, "maintenance captured candidate differs from capture return"),
    ({"commit": BASE}, BASE, "maintenance captured candidate equals the pinned base"),
    ({"repository": "private-repository"}, CANDIDATE,
     "maintenance captured candidate has another repository"),
    ({"paths": ("private-path",)}, CANDIDATE,
     "maintenance captured candidate has path restrictions"),
    ({"diff_against": TREE}, CANDIDATE,
     "maintenance captured candidate has another comparison base"),
    ({"commit": BASE, "repository": "private-repository", "paths": ("private-path",),
      "diff_against": TREE}, CANDIDATE,
     "maintenance captured candidate differs from capture return"),
    ({"commit": BASE, "repository": "private-repository", "paths": ("private-path",),
      "diff_against": TREE}, BASE,
     "maintenance captured candidate equals the pinned base"),
    ({"repository": "private-repository", "paths": ("private-path",), "diff_against": TREE},
     CANDIDATE, "maintenance captured candidate has another repository"),
    ({"paths": ("private-path",), "diff_against": TREE}, CANDIDATE,
     "maintenance captured candidate has path restrictions"),
], ids=["accepted", "commit", "base", "repository", "paths", "comparison-base",
        "commit-first", "base-first", "repository-first", "paths-first"])
async def test_writer_capture_guards_keep_acceptance_and_first_failure(
    monkeypatch, changes, captured, message,
):
    workspace = ControlledAsyncWorkspace(SimpleNamespace(check_control=lambda: None))
    workspace.reference = GitRef(repository=REQUEST.repository, commit=BASE, diff_against=BASE)
    workspace.ready = True
    workspace.commit_allowed.set()
    original = workspace.commit_all
    capture_calls = []

    async def capture(text):
        capture_calls.append(text)
        await original(text)
        workspace.reference = workspace.reference.model_copy(update=changes)
        return captured

    monkeypatch.setattr(workspace, "commit_all", capture)
    executor = Writer()
    ctx = NodeContext(run_id=RunId("run-" + "1" * 32),
        path=ExecutionPath(scope=ScopePath(segments=("capture-guard", "writer"))),
        capabilities={"workspace": workspace, "executor": executor},
        grants=WRITE_GRANTS, effect=lambda *args, **kwargs: pytest.fail("unexpected effect"))
    if message is None:
        result = await maintenance_writer(ctx, INPUTS)
        assert result == {"candidate": GitRef(repository=REQUEST.repository, commit=CANDIDATE,
                                             diff_against=BASE).model_dump(mode="json")}
    else:
        with pytest.raises(ContractViolation) as refusal:
            await maintenance_writer(ctx, INPUTS)
        assert str(refusal.value) == message
        assert "private-" not in str(refusal.value)
    assert len(executor.calls) == 1
    assert capture_calls == ["constructicon plan-manifest regression vectors"]


class Gate(ControlledGate):
    async def verify(self, candidate):
        self.context.check_control()
        self.started.set()
        while not self.allowed.is_set():
            await asyncio.sleep(0.001)
            self.context.check_control()
        self.context.check_control()
        subject = MergeSubject(repository=REQUEST.repository, target_ref=REQUEST.target_ref,
            candidate=candidate, expected_base=BASE, merge_commit=MERGE, tested_tree=TREE)
        if self.provider.fault in {"candidate", "expected_base", "repository", "target_ref"}:
            value = "foreign" if self.provider.fault == "repository" else (
                "refs/heads/foreign" if self.provider.fault == "target_ref" else "e" * 40
            )
            subject = subject.model_copy(update={self.provider.fault: value})
        checks = (CheckResult(name="trusted-vectors", status=(
            "failed" if self.provider.fault == "failed" else "passed"
        ), detail="fake: observed finite check", elapsed_s=0),)
        if self.provider.fault == "empty":
            checks = ()
        attestation = self.provider.journal.mint_attestation(self.context.run_lease,
            AttestationDraft(action="merge", subject=subject, checks=checks,
                check_set_hash=CHECK_SET, manifest_hash=self.context.manifest_hash))
        return MergeEvaluation(subject=subject, checks=checks, attestation_id=(
            None if self.provider.fault == "missing" else attestation.attestation_id
        ))


class GateProvider(ControlledGateProvider):
    def __init__(self, journal, *, fault=None, blocked=False):
        super().__init__()
        self.journal, self.fault, self.blocked = journal, fault, blocked
        self.relinquished = []

    async def acquire(self, context):
        acquired = await super().acquire(context)
        gate = Gate(context)
        gate.provider = self
        if not self.blocked:
            gate.allowed.set()
        self.handles[-1] = gate
        return replace(acquired, resource=gate)

    async def relinquish(self, acquisition):
        acquisition.resource.closed = True
        self.relinquished.append(acquisition.acquisition_id)


def world(journal, *, partial=False, fault=None, blocked=False, providers=None):
    if providers is None:
        executor = FakeExecutorProvider()
        executor.executor = Writer(partial=partial)
        executor._identity = launch_identity(executor.executor.profile)
        workspace = WorkspaceProvider()
        gate = GateProvider(journal, fault=fault, blocked=blocked)
        providers = executor, workspace, gate
    executor, workspace, gate = providers
    system = Constructicon(journal=journal, root_grants=WRITE_GRANTS,
        capabilities={"executor": executor, "workspace": workspace, "gate": gate},
        catalog={"executor": executor.descriptor("executor"),
            "workspace": CapabilityDescriptor(capability_id="workspace", kind="workspace.contained",
                revision=workspace.revision, leased=True, requires_posture=Posture.WRITE),
            "gate": CapabilityDescriptor(capability_id="gate", kind="gates.contained",
                revision=gate.revision, leased=True)},
    )
    return system, ControlPlane(system=system, store=journal), providers


async def register(control):
    for bundle in maintenance_definitions():
        registered = await control.registry_register(LOCAL_ADMIN,
            definition=bundle.definition, idempotency_key="register-" + bundle.definition.name)
        assert isinstance(registered, RegistrationCommandResult), registered
        await control.registry_promote_initial(LOCAL_ADMIN, component=bundle.definition.name,
            version=registered.version, idempotency_key="promote-" + bundle.definition.name)
    return maintenance_graph(executor_id="executor", workspace_id="workspace",
                             gate_id="gate", writer_grants=WRITE_GRANTS)


def test_request_is_closed_and_graph_is_the_same_strict_graph():
    with pytest.raises(ValidationError):
        PlanManifestRequest.model_validate({**INPUTS["request"], "instruction": "another exam"})
    graph = maintenance_graph(executor_id="executor", workspace_id="workspace",
                             gate_id="gate", writer_grants=WRITE_GRANTS)
    assert Graph.model_validate_json(graph.model_dump_json()) == graph
    assert len(graph.nodes) == 2 and graph.connections[0].map["request"] == "$input.request"
    assert {port.name for port in graph.outputs} == {"candidate", "evaluation"}


@pytest.mark.parametrize("fault", [None, "candidate", "expected_base", "repository",
                                  "target_ref", "missing", "empty", "failed", "partial"])
async def test_actual_control_plane_runs_fixed_writer_and_accepts_only_exact_gate(tmp_path, fault):
    journal = SqliteJournal(tmp_path / "application.sqlite")
    system, control, (executor, workspace, gate) = world(
        journal, partial=fault == "partial", fault=fault,
    )
    await control.startup()
    try:
        graph = await register(control)
        assert system.describe_component(maintenance_definitions()[0].definition.name)
        assert len(system.describe().capabilities) == 3
        submission = await control.runs_start(RUN_ACTOR, proposal=graph, inputs=INPUTS,
                                             idempotency_key="start")
        assert isinstance(submission, RunSubmission), submission
        terminal = RunStatus.SUCCEEDED if fault is None else RunStatus.FAILED
        await until(lambda: journal.run_state(submission.run_id).status is terminal)
        assert len(executor.executor.calls) == 1
        assert all(handle.closed for handle in workspace.handles + gate.handles)
        if fault is None:
            materialized = system.materialize_run(submission.run_id)
            evaluation = MergeEvaluation.model_validate(materialized["evaluation"])
            assert evaluation.ok
            proof = journal.load_attestation(evaluation.attestation_id)
            assert proof.ok and proof.created_by_run == submission.run_id
            assert proof.subject.candidate == CANDIDATE
            assert workspace.dispositions == gate.dispositions == ["release"]
            events = journal.events(submission.run_id, limit=100)
            assert journal.max_event_seq(submission.run_id) <= 100
            assert events[-1].kind == "RunSucceeded"
            assert not any(event.kind.startswith("Effect") for event in events)
        elif fault == "partial":
            assert not gate.handles and workspace.dispositions == ["discard"]
            assert not workspace.handles[0].commit_started.is_set()
        else:
            assert workspace.dispositions == ["release"] and gate.dispositions == ["discard"]
            assert journal.checkpoint(submission.run_id, gate.handles[0].context.path) is None
    finally:
        await control.shutdown()


async def test_owned_gate_loser_relinquishes_and_successor_reconciles_before_acceptance(tmp_path):
    clock = FakeClock()
    journal = SqliteJournal(tmp_path / "ownership.sqlite", now_fn=clock.now)
    system, control, providers = world(journal, blocked=True)
    executor, _workspace, gate = providers
    system._walker._heartbeat_interval_s = 0.001
    await control.startup()
    try:
        graph = await register(control)
        submission = await control.runs_start(RUN_ACTOR, proposal=graph, inputs=INPUTS,
                                             idempotency_key="start")
        assert isinstance(submission, RunSubmission), submission
        await until(lambda: gate.handles and gate.handles[0].started.is_set())
        path = gate.handles[0].context.path
        clock.advance(LEASE_TTL_S + 1)
        successor = journal.claim_run(submission.run_id, owner_id="maintenance-successor",
                                      ttl_s=LEASE_TTL_S)
        await until(lambda: bool(gate.relinquished))
        assert gate.handles[0].closed and not gate.dispositions
        assert journal.checkpoint(submission.run_id, path) is None
        active = [row for row in journal.capability_leases(submission.run_id)
                  if row.path == path and row.state == "active"]
        assert len(active) == 1
        await control.shutdown()
        journal.release_run(successor)
        gate.blocked = False
        recovered_system, recovered, _ = world(journal, providers=providers)
        await recovered.startup()
        try:
            await until(lambda: journal.run_state(submission.run_id).status is RunStatus.SUCCEEDED)
            recovered_output = recovered_system.materialize_run(submission.run_id)
            assert recovered_output["evaluation"]["attestation_id"]
            assert gate.dispositions == ["discard", "release"]
            assert len(executor.executor.calls) == 1
            assert not any(row.state == "active"
                           for row in journal.capability_leases(submission.run_id))
        finally:
            await recovered.shutdown()
    finally:
        await control.shutdown()


@pytest.mark.parametrize("change", [None, "source", "added", "removed", "weak-vectors"])
def test_exact_trusted_gate_program_accepts_only_one_new_data_file(tmp_path, change):
    from tests.substrate.test_maintenance_vectors import permitting_vectors

    source = (Path(__file__).resolve().parents[2] / "scripts/regen_plan_manifest.py").read_bytes()
    source_path = tmp_path / "scripts/regen_plan_manifest.py"
    source_path.parent.mkdir()
    source_path.write_bytes(source)
    baseline_oid = hashlib.sha1(f"blob {len(source)}\0".encode() + source).hexdigest()
    inventory = f"100644 blob {baseline_oid}\tscripts/regen_plan_manifest.py\0".encode()
    checks = maintenance_checks(source, hashlib.sha256(source).hexdigest(), inventory, "sha1")
    vector_path = tmp_path / "tests/vectors/plan_manifest.json"
    vector_path.parent.mkdir(parents=True)
    vector_path.write_bytes(permitting_vectors())
    if change == "source":
        source_path.write_bytes(source + b"\n# unauthorized change\n")
    elif change == "added":
        (tmp_path / "extra.py").write_bytes(b"raise RuntimeError('must never run')")
    elif change == "removed":
        source_path.unlink()
    elif change == "weak-vectors":
        vector_path.write_bytes(b'{"version":1,"cases":[{"kind":"plan_path","path":"a.md"}]}')
    result = subprocess.run((sys.executable, *checks[0].argv[1:]), cwd=tmp_path,
        stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=False)
    if change is None:
        assert result.returncode == 0, result.stderr.decode()
        report = json.loads(result.stdout)
        assert report["passed"] is True
        assert report["input_sha256"] == hashlib.sha256(vector_path.read_bytes()).hexdigest()
        assert len(report["render_sha256"]) == 64
        assert report["baseline"] == {"tests_run": 24, "failures": 0, "errors": 0, "skips": 0}
        assert len(report["mutants"]) == 8
        for mutant in report["mutants"]:
            assert mutant["distinguished"] and mutant["counts"]["failures"] > 0
            assert mutant["counts"]["errors"] == mutant["counts"]["skips"] == 0
    else:
        assert result.returncode != 0 and not result.stdout


@pytest.mark.parametrize("finish", ["cancel", "restart"])
async def test_pending_gate_cleanup_cancel_or_restart_uses_existing_walker(tmp_path, finish):
    journal = SqliteJournal(tmp_path / "pending.sqlite")
    _system, control, providers = world(journal, blocked=True)
    executor, workspace, gate = providers
    await control.startup()
    try:
        graph = await register(control)
        submission = await control.runs_start(RUN_ACTOR, proposal=graph, inputs=INPUTS,
                                             idempotency_key="start")
        assert isinstance(submission, RunSubmission), submission
        await until(lambda: gate.handles and gate.handles[0].started.is_set())
        path = gate.handles[0].context.path
        assert journal.checkpoint(submission.run_id, path) is None
        if finish == "cancel":
            await control.runs_cancel(RUN_ACTOR, run_id=submission.run_id,
                                      idempotency_key="cancel")
            await until(lambda: journal.run_state(submission.run_id).status is RunStatus.CANCELLED)
            assert journal.checkpoint(submission.run_id, path) is None
        else:
            await control.shutdown()
            assert journal.run_state(submission.run_id).status is RunStatus.RUNNING
            gate.blocked = False
            recovered_system, recovered, _ = world(journal, providers=providers)
            await recovered.startup()
            try:
                await until(
                    lambda: journal.run_state(submission.run_id).status is RunStatus.SUCCEEDED,
                )
                assert recovered_system.materialize_run(submission.run_id)["candidate"]["commit"] \
                    == CANDIDATE
                assert len(executor.executor.calls) == 1
                assert gate.dispositions == ["discard", "release"]
            finally:
                await recovered.shutdown()
        assert all(handle.closed for handle in workspace.handles + gate.handles)
        assert workspace.dispositions == ["release"]
        assert gate.dispositions[0] == "discard"
    finally:
        await control.shutdown()


class PortableProcessLauncher:
    """Execute the actual fixed worker/check programs, without Linux isolation.

    The substituted platform primitives are executable locators, guard-fd
    inheritance and the Linux launch boundary. Git, packs, capture publication,
    snapshot verification, admission, journal and attestation laws remain real.
    """

    revision = digest("maintenance-portable-process-double", 1, "closed-stdin")
    limits = ProcessLimits()

    def __init__(self, root, git):
        self.root, self.git = root, git
        root.mkdir()
        self.calls = []

    async def run(self, command, **kwargs):
        from constructicon.substrate.gates.contained import _CHECK

        assert kwargs["guard_fds"]
        for descriptor in kwargs["guard_fds"]:
            os.fstat(descriptor)
        self.calls.append((command, kwargs))
        environment = {name: value for name, value in os.environ.items()
                       if not name.upper().startswith("GIT_")}
        # The Linux boundary exposes no host Git configuration. Inheriting a
        # Windows autocrlf setting changes full-tree checkout bytes before the
        # capture program (correctly) disables globals for staging.
        environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
            GIT_ATTR_NOSYSTEM="1", GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="core.attributesFile", GIT_CONFIG_VALUE_0=os.devnull)
        combined = command[1:4] == ("-I", "-c", _CHECK)
        if combined:
            # Windows os.execv does not preserve this Linux trampoline's
            # argv/exit contract. Substitute the exec primitive, observing the
            # real check child's exit, with the trampoline's exact environment.
            command = command[4:]
            environment.update(PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(self.root),
                               RUFF_CACHE_DIR=str(self.root / "ruff"))
        replacements = {"/usr/bin/python3": Path(sys.executable).as_posix(),
                        "/usr/bin/git": Path(self.git).as_posix(),
                        "/dev/null": os.devnull, "/tmp": self.root.as_posix()}
        translated = []
        for argument in command:
            for before, after in replacements.items():
                argument = argument.replace(before, after)
            translated.append(argument)
        started = time.monotonic()
        result = await finish_owned(asyncio.create_task(asyncio.to_thread(
            subprocess.run, translated,
            cwd=kwargs.get("workspace"), input=kwargs.get("stdin", b""),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT if combined else subprocess.PIPE,
            env=environment, timeout=kwargs["timeout_s"], check=False)))
        assert len(result.stdout) <= self.limits.stdout_bytes
        errors = result.stderr or b""
        assert len(errors) <= self.limits.stderr_bytes
        return ProcessResult(result.returncode, result.stdout, errors,
                             time.monotonic() - started, payload_returncode=result.returncode)


async def test_portable_process_cancellation_joins_the_child(tmp_path, monkeypatch):
    launcher = PortableProcessLauncher(tmp_path / "scratch", sys.executable)
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release, finished = threading.Event(), threading.Event()

    def child(command, **kwargs):
        assert kwargs["timeout"] == 30 and kwargs["input"] == b""
        loop.call_soon_threadsafe(started.set)
        release.wait()
        finished.set()
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", child)
    with (tmp_path / "guard").open("w+b") as guard:
        caller = asyncio.create_task(launcher.run(("/usr/bin/python3", "--version"),
            guard_fds=(guard.fileno(),), timeout_s=30))
        try:
            await started.wait()
            caller.cancel("joined child cancellation")
            await asyncio.sleep(0)
            assert not caller.done() and not finished.is_set()
        finally:
            release.set()
            await asyncio.wait((caller,))
        with pytest.raises(asyncio.CancelledError, match="joined child cancellation"):
            await caller
        assert finished.is_set()


class PortableVectorWriter(Writer):
    intermediate_commits = False

    async def execute(self, task, *, workspace, grants):
        from tests.substrate.test_maintenance_vectors import permitting_vectors

        assert task.instruction == WRITE_INSTRUCTION and not self.validate_grants(grants)
        self.calls.append(task)
        history = (
            "import os,subprocess\n"
            "os.environ.update(GIT_AUTHOR_NAME='test',GIT_AUTHOR_EMAIL='test@example.invalid',"
            "GIT_COMMITTER_NAME='test',GIT_COMMITTER_EMAIL='test@example.invalid')\n"
            "extra=Path('forbidden.py')\n"
            "extra.write_bytes(b'# outside the approved data surface\\n')\n"
            "subprocess.run(['/usr/bin/git','add','--all'],check=True)\n"
            "subprocess.run(['/usr/bin/git','commit','-qm','worker intermediate'],check=True)\n"
            "extra.unlink()\n"
            "subprocess.run(['/usr/bin/git','add','--all'],check=True)\n"
            "subprocess.run(['/usr/bin/git','commit','-qm','worker removes extra'],check=True)\n"
        ) if self.intermediate_commits else ""
        program = (
            "from pathlib import Path\n"
            + history
            +
            "p=Path('tests/vectors/plan_manifest.json')\n"
            "p.parent.mkdir(parents=True,exist_ok=True)\n"
            f"p.write_bytes({permitting_vectors()!r})\n"
        )
        async with workspace.use() as guard:
            result = await workspace.provider.launcher.run(
                ("/usr/bin/python3", "-I", "-c", program),
                workspace=Path(workspace.path), posture=Posture.WRITE,
                guard_fds=(guard,), timeout_s=30,
            )
        assert result.returncode == 0, result.stderr.decode()
        return ExecutorSuccess()


@pytest.fixture
async def concrete_application(tmp_path, monkeypatch, request, portable_acquisition_namespace):
    from constructicon.substrate.gates import contained as gate_module

    if getattr(request, "param", None) == "committed-tree":
        # Seed the callback's fake store before this fixture substitutes its
        # narrowly scoped guarded-removal primitive below.
        request.getfixturevalue("portable_binding")
    source = (Path(__file__).resolve().parents[2] / "scripts/regen_plan_manifest.py").read_bytes()
    repo = seed_authority(tmp_path, {"seed.txt": "trusted fixture seed\n"})
    authority = GitAuthority(repo.resolve(), tmp_path / "authority-workspaces")
    blob = authority._run("hash-object", "-w", "--stdin", input_text=source.decode()).stdout.strip()
    scripts = authority._run("mktree",
        input_text=f"100644 blob {blob}\tregen_plan_manifest.py\n").stdout.strip()
    tree = authority._run("mktree", input_text=f"040000 tree {scripts}\tscripts\n").stdout.strip()
    base = authority._run(
        "commit-tree", tree, input_text="trusted maintenance base\n",
    ).stdout.strip()
    authority._run("update-ref", "refs/heads/main", base)
    if getattr(request, "param", None) == "committed-tree":
        from tests.maintenance_task_world import committed_tree_base

        base = await committed_tree_base(authority)
        attributes = tmp_path / "ambient.attributes"
        attributes.write_text("* text eol=crlf\n", encoding="ascii")
        for name, value in {
            "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "core.autocrlf",
            "GIT_CONFIG_VALUE_0": "true", "GIT_CONFIG_KEY_1": "core.attributesFile",
            "GIT_CONFIG_VALUE_1": str(attributes),
        }.items():
            monkeypatch.setenv(name, value)
    journal = SqliteJournal(tmp_path / "application.sqlite")
    launch = PortableProcessLauncher(tmp_path / "scratch", authority.git_executable)
    locks = {}

    @asynccontextmanager
    async def portable_guard(paths):
        lock = locks.setdefault(str(paths.guard), asyncio.Lock())
        async with lock:
            paths.guard.parent.mkdir(parents=True, exist_ok=True)
            with paths.guard.open("a+b") as stream:
                yield stream.fileno()

    for module in (acquisition, contained, gate_module):
        monkeypatch.setattr(module, "acquisition_guard", portable_guard)
    original_rmtree = acquisition.shutil.rmtree

    def portable_rmtree(root, **kwargs):
        # The genuine Windows primitive has no fd-based unlink. Substitute
        # only that primitive over these owned, positively link-free fixtures.
        if "dir_fd" in kwargs:
            return original_rmtree(root, **kwargs)  # Linux keeps its physical primitive.
        root = Path(root)
        assert root.resolve().is_relative_to(tmp_path.resolve()) and not root.is_symlink()
        for path in root.rglob("*"):
            assert not path.is_symlink()
            path.chmod(0o700 if path.is_dir() else 0o600)
        root.chmod(0o700)
        return original_rmtree(root, **kwargs)

    portable_rmtree.avoids_symlink_attacks = True
    monkeypatch.setattr(acquisition.shutil, "rmtree", portable_rmtree)
    original_run = GitProcess.run

    async def portable_git(self, *args, guard=None, **kwargs):
        if guard is not None:
            os.fstat(guard)
        return await original_run(self, *args, **kwargs)

    monkeypatch.setattr(GitProcess, "run", portable_git)
    base = authority.resolve_ref("refs/heads/main")
    # Pin the actual immutable authority blob, exactly as assembly must do.
    source = await GitProcess(authority.git_executable, ProcessLimits()).run(
        "show", f"{base}:scripts/regen_plan_manifest.py", cwd=repo,
    )
    inventory = await GitProcess(authority.git_executable, ProcessLimits()).run(
        "ls-tree", "-r", "-z", base, cwd=repo,
    )
    workspace = ContainedWriteWorkspaceProvider(authority, root=tmp_path / "writer-acquisitions",
        target_ref="refs/heads/main", provider_id="workspace", posture=Posture.WRITE,
        launcher=launch)
    gate = await ContainedGateRunner.create(journal=journal, authority=authority,
        root=tmp_path / "gate-acquisitions", target_ref="refs/heads/main", provider_id="gate",
        launcher=launch, checks=maintenance_checks(
            source, hashlib.sha256(source).hexdigest(), inventory,
            authority.environment.object_format,
        ))
    request = PlanManifestRequest(repository=authority.repository_id, target_ref=gate.target_ref,
        base_commit=base, target_sha256=hashlib.sha256(source).hexdigest(),
        check_set_hash=gate.check_set_hash)
    resources = MaintenanceResources(journal, authority, workspace, gate, request, source)
    executor = FakeExecutorProvider()
    executor.executor = PortableVectorWriter()
    executor._identity = launch_identity(executor.executor.profile)
    system = await maintenance_system(resources, executor_id="executor", executor=executor,
        executor_descriptor=executor.descriptor("executor"), writer_grants=WRITE_GRANTS)
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    try:
        yield resources, executor, system, control, launch
    finally:
        await control.shutdown()


@pytest.fixture
async def completed_concrete_attempt(concrete_application, monkeypatch):
    _resources, _executor, system, _control, _launch = concrete_application
    completed = asyncio.get_running_loop().create_future()
    original = system._run_prepared

    async def observe(*args, **kwargs):
        worker = asyncio.current_task()
        assert worker is not None
        try:
            result = await original(*args, **kwargs)
        except BaseException as error:
            completed.set_result((worker, error))
            raise
        completed.set_result((worker, result))
        return result

    monkeypatch.setattr(system, "_run_prepared", observe)

    async def join(run_id):
        worker, result = await asyncio.shield(completed)
        await asyncio.shield(worker)
        if isinstance(result, BaseException):
            raise result
        assert result.run_id == run_id
        return result

    return join


async def test_concrete_assembly_real_git_and_journal_affirm_exact_accepted_result(
    concrete_application, completed_concrete_attempt,
):
    resources, executor, system, control, launch = concrete_application
    await require_maintenance_resources(resources)
    graph = await register(control)
    submission = await control.runs_start(RUN_ACTOR, proposal=graph,
        inputs={"request": resources.request.model_dump(mode="json")}, idempotency_key="concrete")
    assert isinstance(submission, RunSubmission), submission
    result = await completed_concrete_attempt(submission.run_id)
    assert result.status is RunStatus.SUCCEEDED, result
    assert resources.journal.run_state(submission.run_id).status is RunStatus.SUCCEEDED, \
        resources.journal.events(submission.run_id, limit=100)
    result = await derive_maintenance_result(system, resources, submission.run_id)
    assert result.candidate.commit != resources.request.base_commit
    assert result.evaluation.ok
    assert len(executor.executor.calls) == 1
    assert resources.authority.resolve_ref(resources.request.target_ref) \
        == resources.request.base_commit
    subject = result.evaluation.subject
    assert resources.authority.tree_of(result.candidate.commit) == subject.tested_tree
    assert resources.authority.tree_of(subject.merge_commit) == subject.tested_tree
    assert resources.authority.parents_of(subject.merge_commit) == (
        resources.request.base_commit, result.candidate.commit,
    )
    details = json.loads(result.evaluation.checks[0].detail)
    assert details["input_sha256"] == result.input_sha256
    assert details["render_sha256"] == result.render_sha256
    assert details["baseline"]["tests_run"] == 24
    assert len(details["mutants"]) == 8
    assert all(item["distinguished"] for item in details["mutants"])
    rows = resources.journal.capability_leases(submission.run_id)
    assert rows and all(row.state == "closed" for row in rows)
    assert any(kwargs["workspace"] is not None for _, kwargs in launch.calls)
    assert not list(resources.workspace.root.glob("payloads/*"))
    assert not list(resources.gate.root.glob("payloads/*"))
    changed = resources.request.model_copy(update={"target_sha256": "0" * 64})
    with pytest.raises(ContractViolation):
        await derive_maintenance_result(
            system, replace(resources, request=changed), submission.run_id,
        )
    with pytest.raises(ContractViolation, match="exact assembled system world"):
        foreign = Constructicon(journal=resources.journal)
        await derive_maintenance_result(foreign, resources, submission.run_id)


async def test_concrete_successful_noop_is_refused_after_real_capture(
    concrete_application, completed_concrete_attempt, monkeypatch,
):
    resources, executor, _system, control, _launch = concrete_application
    executor.executor = Writer()
    captured = []
    original = resources.workspace.capture

    async def observe_capture(workspace, message):
        oid = await original(workspace, message)
        captured.append((oid, workspace.git_ref()))
        return oid

    monkeypatch.setattr(resources.workspace, "capture", observe_capture)
    graph = await register(control)
    submitted = await control.runs_start(RUN_ACTOR, proposal=graph,
        inputs={"request": resources.request.model_dump(mode="json")}, idempotency_key="noop")
    assert isinstance(submitted, RunSubmission), submitted
    result = await completed_concrete_attempt(submitted.run_id)
    assert result.status is RunStatus.FAILED
    assert resources.journal.run_state(submitted.run_id).status is RunStatus.FAILED
    assert captured == [(resources.request.base_commit, GitRef(
        repository=resources.request.repository, commit=resources.request.base_commit,
        diff_against=resources.request.base_commit))]
    events = resources.journal.events(submitted.run_id, limit=100)
    failures = [event for event in events if event.kind == "NodeFailed"]
    assert len(failures) == 1
    assert failures[0].payload == {
        "error_type": "ContractViolation",
        "error": "maintenance captured candidate equals the pinned base",
    }
    writer_path = failures[0].path
    assert writer_path is not None and writer_path.scope.segments[-1] == "writer"
    assert resources.journal.checkpoint(submitted.run_id, writer_path) is None
    assert not any(event.kind == "NodeStarted" and event.path is not None
                   and event.path.scope.segments[-1] == "checker" for event in events)
    assert len(executor.executor.calls) == 1
    rows = resources.journal.capability_leases(submitted.run_id)
    assert rows and all(row.state == "closed" for row in rows)
    assert resources.authority.resolve_ref(resources.request.target_ref) \
        == resources.request.base_commit


@pytest.mark.parametrize("change", ["journal", "authority", "checks", "descriptor"])
async def test_concrete_assembly_refuses_mismatched_resources(concrete_application, change):
    resources, executor, _system, _control, _launch = concrete_application
    descriptor = executor.descriptor("executor")
    if change == "journal":
        resources = replace(resources,
                            journal=SqliteJournal(resources.gate.root.parent / "foreign.sqlite"))
    elif change == "authority":
        resources = replace(resources, authority=GitAuthority(
            Path(resources.authority.repository_id), resources.gate.root / "foreign-workspaces",
        ))
    elif change == "checks":
        resources.gate.checks = ()
    else:
        descriptor = replace(descriptor, revision="foreign")
    with pytest.raises(ContractViolation):
        await maintenance_system(resources, executor_id="executor", executor=executor,
                                 executor_descriptor=descriptor, writer_grants=WRITE_GRANTS)


async def test_application_refuses_history_despite_passing_generic_tree_gate(
    concrete_application, completed_concrete_attempt,
):
    resources, executor, system, control, _launch = concrete_application
    executor.executor.intermediate_commits = True
    graph = await register(control)
    submission = await control.runs_start(RUN_ACTOR, proposal=graph,
        inputs={"request": resources.request.model_dump(mode="json")}, idempotency_key="history")
    assert isinstance(submission, RunSubmission), submission
    result = await completed_concrete_attempt(submission.run_id)
    assert result.status is RunStatus.SUCCEEDED, result
    assert resources.journal.run_state(submission.run_id).status is RunStatus.SUCCEEDED
    materialized = system.materialize_run(submission.run_id)
    candidate = GitRef.model_validate(materialized["candidate"])
    evaluation = MergeEvaluation.model_validate(materialized["evaluation"])
    proof = resources.journal.load_attestation(evaluation.attestation_id)
    assert evaluation.ok and proof.ok
    assert proof.subject.candidate == candidate.commit
    parents = resources.authority.parents_of(candidate.commit)
    assert len(parents) == 1 and parents != (resources.request.base_commit,)
    intermediate = resources.authority.parents_of(parents[0])[0]
    assert resources.authority._run("show", f"{intermediate}:forbidden.py").stdout \
        == "# outside the approved data surface\n"
    assert resources.authority._run("cat-file", "-e", f"{candidate.commit}:forbidden.py",
                                   check=False).returncode != 0
    rejected = False
    try:
        await derive_maintenance_result(system, resources, submission.run_id)
    except ContractViolation as error:
        assert "sole parent" in str(error)
        rejected = True
    assert rejected, "passing the generic tree gate must not accept intermediate worker code"
