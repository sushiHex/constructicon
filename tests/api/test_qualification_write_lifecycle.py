"""N5's permitting lifecycle and cold reconstruction, with explicit doubles.

The native peer is a real scripted byte channel. SQLite, the walker, attempt
record, acquisition closures, Git objects, checkpoint and gate attestation are
real. Worker execution and capture are deterministic contract doubles here;
the companion Linux lane exercises their actual containment implementation.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.api import _qualification_write_assembly as assembly_module
from constructicon.api import qualification
from constructicon.api._qualification_write_assembly import WriteAssembly
from constructicon.api._qualification_write_graph import (
    WRITER_SCOPE,
    write_definitions,
    write_graph,
    write_inputs,
)
from constructicon.api._qualification_write_report import write_report_definition
from constructicon.api.control import ControlPlane
from constructicon.core.control import RunSubmission
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import canonical_json, digest
from constructicon.core.manifest import manifest_hash_for, parse_manifest_json
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.run import RunStatus
from constructicon.substrate.executors import codex, codex_lane
from constructicon.substrate.executors.codex import CodexOperatorProvider, launch_identity
from constructicon.substrate.executors.codex_host import WRITE_GRANTS, WRITE_PROFILE
from constructicon.substrate.executors.codex_protocol import CONTAINED_PYTHON_CATALOG
from constructicon.substrate.executors.linux import LinuxLauncher, ProcessResult
from constructicon.substrate.gates import contained as gates_module
from constructicon.substrate.git import acquisition, contained
from constructicon.substrate.git.process import GitProcess
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.native_operator_world import native_egress
from tests.substrate.test_codex_adapter import (
    BINARY,
    EXPECTED,
    FINISHED,
    ScriptedLauncher,
    bare_launcher,
)
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_write import write_native

PROGRAM = "from pathlib import Path; Path('n5-write.txt').write_bytes(b'ready\\n')"


@dataclass(frozen=True, kw_only=True)
class PortableWriteLauncher(ScriptedLauncher):
    """No host program execution: only the fixed worker/check contracts are faked."""

    worker_calls: list = field(default_factory=list)
    contents: bytes = b"ready\n"

    async def run(self, command, **kwargs):
        for descriptor in kwargs["guard_fds"]:
            os.fstat(descriptor)
        if command == codex.WORKER_ARGUMENTS:
            self.worker_calls.append((command, kwargs))
            (kwargs["workspace"] / "n5-write.txt").write_bytes(self.contents)
            return FINISHED
        if kwargs["workspace"] is None:
            return ProcessResult(0, b"Python scripted\n", b"", 0, payload_returncode=0)
        snapshot = kwargs["workspace"]
        passed = sorted(p.name for p in snapshot.iterdir()) == ["n5-write.txt"] and (
            snapshot / "n5-write.txt"
        ).read_bytes() == b"ready\n"
        return ProcessResult(0 if passed else 1, b"", b"", 0,
                             payload_returncode=0 if passed else 1)


def portable_launcher(*, contents=b"ready\n"):
    initial = bare_launcher(native=write_native(program=PROGRAM))
    return PortableWriteLauncher(
        **{item.name: getattr(initial, item.name) for item in fields(LinuxLauncher)},
        native=initial.native, result=FINISHED, contents=contents,
    )


def executor_for(launcher, binding, root, authorization=None):
    """Use production profile/configuration and retain every unavailable reason."""
    store, closure = binding
    configuration = codex_lane.production_configuration()
    identity = launch_identity(
        launcher=launcher, profile=WRITE_PROFILE, egress=native_egress(), store=store.sealed,
        executable_digest=digest("scripted-n5-binary", 1, BINARY),
        configuration=configuration, catalog=CONTAINED_PYTHON_CATALOG,
        authenticated_startup_conformance_revision=digest("scripted-n5-startup", 1, "fixture"),
        subscription_mode_conformance_revision=digest("scripted-n5-mode", 1, "fixture"),
    )
    return CodexOperatorProvider(
        launcher=launcher, profile=WRITE_PROFILE, identity=identity, expected_account=EXPECTED,
        binary=BINARY, configuration=configuration, catalog=CONTAINED_PYTHON_CATALOG,
        acquisition_root=root, binding_store=store, closure=closure,
        qualification=authorization,
    )


async def sealed_assembly(tmp_path, launcher, binding, authorization=None):
    root = tmp_path / "fixture"
    if not root.exists():
        assembly_module.prepare_fixture(root)
    journal = SqliteJournal(tmp_path / "qualification.sqlite")
    resources = await assembly_module.assemble_contained_write(root, journal, launcher)
    pins = assembly_module.contained_pins(resources, write_report_definition())
    provisional = executor_for(launcher, binding, tmp_path / "executor")
    if authorization is None:
        authorization = QualificationAuthorization(
            authorization_id="scripted-n5-write", stage="qualification-write",
            actor_id="operator:qualification", idempotency_key="scripted-write",
            scope=WRITER_SCOPE, binding="executor", capability_id="codex-operator",
            source_graph_hash=qualification.source_graph_hash_for(
                write_graph("codex-operator", pins),
            ), revision=provisional.identity.revision,
            operator_binding_digest=provisional.identity.store.operator_binding_digest,
            journal=str(tmp_path / "qualification.sqlite"), max_epoch=1,
            not_after=datetime.now(UTC) + timedelta(hours=1), grants=WRITE_GRANTS,
            attempt_record=str(tmp_path / "write.attempt"), write=pins,
        )
    executor = executor_for(launcher, binding, tmp_path / "executor", authorization)
    return WriteAssembly(executor, resources, pins), authorization


@pytest.fixture
def portable_write_boundary(monkeypatch):
    # The production Linux syscall/fence and worker/capture boundaries are
    # explicitly substituted. No safety or report guard is removed.
    monkeypatch.setattr(assembly_module, "_private_owner", lambda info: None)
    monkeypatch.setattr(assembly_module, "_ancestor_owner", lambda info: None)

    @asynccontextmanager
    async def guard(paths):
        paths.guard.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(paths.guard, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            yield descriptor
        finally:
            os.close(descriptor)

    for module in (codex, acquisition, contained, gates_module):
        monkeypatch.setattr(module, "acquisition_guard", guard)

    async def populate(self, view, guard):
        await asyncio.sleep(0)

    async def capture(self, view, message):
        self._check(view)
        async with view.use():
            authority = self.authority
            blob = authority._run(
                "hash-object", "-w", "--stdin",
                input_text=(Path(view.path) / "n5-write.txt").read_text(),
            ).stdout.strip()
            tree = authority._run(
                "mktree", input_text=f"100644 blob {blob}\tn5-write.txt\n",
            ).stdout.strip()
            candidate = authority._run("commit-tree", tree, "-p", view.base,
                                       input_text=message).stdout.strip()
        self._check(view)
        self.closure.publish(view.paths, self._candidate_ref(view), candidate)
        view._phase.head = candidate
        return candidate

    monkeypatch.setattr(assembly_module.ContainedWriteWorkspaceProvider, "populate", populate)
    monkeypatch.setattr(assembly_module.ContainedWriteWorkspaceProvider, "capture", capture)
    if os.name != "posix":
        # The fixture owns only literal test-created paths; this is not proof
        # that Windows supplies Linux's fd-based, symlink-safe disposal.
        monkeypatch.setattr(shutil.rmtree, "avoids_symlink_attacks", True)
        original_run = GitProcess.run

        async def immutable_git(self, *args, **kwargs):
            # Windows cannot inherit a POSIX guard. Only immutable authority
            # reads reach this seam; actual Git inventory/archive still run.
            kwargs["guard"] = None
            return await original_run(self, *args, **kwargs)

        monkeypatch.setattr(GitProcess, "run", immutable_git)


async def until(predicate):
    async with asyncio.timeout(30):
        while not predicate():
            await asyncio.sleep(0.01)


def assert_closed(assembly, run_id):
    rows = assembly.resources.journal.capability_leases(run_id)
    assert rows and {row.binding_id for row in rows} == {"executor", "workspace", "gate"}
    assert all(row.state == "closed" for row in rows)
    assert not list(assembly.resources.workspace.root.glob("payloads/*"))
    assert not list(assembly.resources.gate.root.glob("payloads/*"))
    assert all(handle.closed for handle in assembly.executor.handles)


def callback_calls(launcher):
    return [call for call in launcher.worker_calls if call[0] == codex.WORKER_ARGUMENTS]


@pytest.mark.parametrize("contents,passed", [(b"ready\n", True), (b"wrong\n", False)])
async def test_qualified_write_actual_entry_joins_and_reports_exact_candidate(
    tmp_path, portable_binding, portable_write_boundary, contents, passed,
):
    launcher = portable_launcher(contents=contents)
    assembly, auth = await sealed_assembly(tmp_path, launcher, portable_binding[1:])
    async with asyncio.timeout(30):
        report = await qualification.qualify_write(assembly=assembly, authorization=auth)
    journal = assembly.resources.journal
    assert journal.run_state(auth.run_id).status is (
        RunStatus.SUCCEEDED if passed else RunStatus.FAILED
    ), journal.events(auth.run_id)
    assert (report.verdict == "passed") is passed, report.model_dump_json()
    assert len(launcher.commands) == len(launcher.worker_calls) == 1
    assert len(launcher.native.callback_responses) == 1
    assert json.loads(Path(auth.attempt_record).read_text())["dispatch"] == "completed"
    assert_closed(assembly, auth.run_id)
    assert assembly.resources.authority.resolve_ref(assembly.resources.fixture.target_ref) == (
        assembly.resources.fixture.base_commit
    )
    assert assembly.executor.unavailable_reasons  # Qualification is not promotion.


@pytest.mark.parametrize("checkpointed", [False, True])
async def test_write_cold_reconstruction_never_redispatches_spent_writer(
    tmp_path, portable_binding, portable_write_boundary, monkeypatch, checkpointed,
):
    await reconstruct_write(tmp_path, portable_binding[1:], monkeypatch, checkpointed,
                            portable_launcher)


async def reconstruct_write(tmp_path, binding, monkeypatch, checkpointed, launcher_factory):
    """Exercise the same durable seam with either the portable or real launcher."""
    first_launcher = launcher_factory()
    first_assembly, auth = await sealed_assembly(tmp_path, first_launcher, binding)
    resources = first_assembly.resources
    reached = asyncio.Event()
    if checkpointed:
        original_verify = resources.gate._verify

        async def pause_gate(handle, candidate):
            reached.set()
            await asyncio.Event().wait()
            return await original_verify(handle, candidate)

        monkeypatch.setattr(resources.gate, "_verify", pause_gate)
    else:
        original_capture = resources.workspace.capture

        async def pause_capture(view, message):
            reached.set()
            await asyncio.Event().wait()
            return await original_capture(view, message)

        monkeypatch.setattr(resources.workspace, "capture", pause_capture)

    system = qualification._contained_system(resources, first_assembly.executor)
    control = ControlPlane(system=system, store=resources.journal)
    actor = qualification.AuthenticatedActor(actor_id=auth.actor_id, auth_method="static",
        scopes=frozenset({qualification.READ_SCOPE, qualification.ADMIN_SCOPE}))
    await control.startup()
    try:
        await qualification._bootstrap_definitions(control, actor, write_definitions())
        submitted = await control.runs_start(
            actor, proposal=write_graph(auth.capability_id, auth.write),
            inputs=write_inputs(auth), idempotency_key=auth.idempotency_key,
        )
        assert isinstance(submitted, RunSubmission) and submitted.run_id == auth.run_id
        await until(reached.is_set)
        writer = next(row for row in resources.journal.capability_leases(auth.run_id)
                      if row.binding_id == "workspace")
        assert (resources.journal.checkpoint(auth.run_id, writer.path) is not None) is checkpointed
        assert len(callback_calls(first_launcher)) == 1
    finally:
        await control.shutdown()
    assert resources.journal.run_state(auth.run_id).status is RunStatus.RUNNING
    assert not resources.journal.cancel_requested(auth.run_id)
    spent = Path(auth.attempt_record).read_bytes()

    # Fresh journal/provider/host objects: no process-local latch proves recovery.
    second_launcher = launcher_factory()
    second_assembly, _ = await sealed_assembly(
        tmp_path, second_launcher, binding, authorization=auth,
    )
    async with asyncio.timeout(30):
        report = await qualification.qualify_write(assembly=second_assembly, authorization=auth)
    journal = second_assembly.resources.journal
    assert journal.run_state(auth.run_id).status is (
        RunStatus.SUCCEEDED if checkpointed else RunStatus.FAILED
    ), journal.events(auth.run_id)
    assert (report.verdict == "passed") is checkpointed, report.model_dump_json()
    assert second_launcher.commands == callback_calls(second_launcher) == []
    assert second_launcher.native.callback_responses == []
    assert Path(auth.attempt_record).read_bytes() == spent
    if checkpointed:
        checker = next(row for row in journal.capability_leases(auth.run_id)
                       if row.binding_id == "gate" and row.acquisition_epoch > 1)
        assert journal.checkpoint(auth.run_id, checker.path) is not None
        assert_closed(second_assembly, auth.run_id)
    else:
        assert journal.checkpoint(auth.run_id, writer.path) is None
        assert not second_assembly.executor.handles


async def test_credential_free_smoke_uses_the_same_contained_capture_and_checker(
    tmp_path, portable_write_boundary, monkeypatch,
):
    root = tmp_path / "fixture"
    assembly_module.prepare_fixture(root)
    launcher = portable_launcher()
    monkeypatch.setattr(codex_lane, "_launcher", lambda _: launcher)
    async with asyncio.timeout(30):
        report = await qualification.smoke_write(SimpleNamespace(
            fixture=root, launch_root=Path("/unused-scripted-launch"),
        ))
    assert report.verdict == "passed", report.model_dump_json()
    assert report.obligation_count == 2 and report.check_count == 1
    assert not launcher.commands and not launcher.native.received
    assert len(callback_calls(launcher)) == 1
    assert not list(root.glob("*.attempt"))
    assert not list((root / "workspace-acquisitions").glob("payloads/*"))
    assert not list((root / "gate-acquisitions").glob("payloads/*"))


@pytest.mark.parametrize("changed", ["inputs", "manifest"])
async def test_retained_write_identity_is_refused_before_recovery_startup(
    tmp_path, portable_binding, portable_write_boundary, monkeypatch, changed,
):
    assembly, auth = await sealed_assembly(tmp_path, portable_launcher(), portable_binding[1:])
    initial = await qualification.qualify_write(assembly=assembly, authorization=auth)
    assert initial.verdict == "passed", initial.model_dump_json()
    journal = assembly.resources.journal
    if changed == "inputs":
        wrong = write_inputs(auth)
        wrong["request"]["authorization_id"] = "another-authority"
        monkeypatch.setattr(journal, "run_inputs", lambda _: wrong)
    else:
        retained = parse_manifest_json(
            journal.load_manifest_json(journal.run_manifest_hash(auth.run_id)),
        )
        bindings = tuple(
            binding.model_copy(update={"revision": "sha256:" + "0" * 64})
            if binding.binding == "workspace" else binding
            for binding in retained.capability_bindings
        )
        wrong = retained.model_copy(update={"capability_bindings": bindings})
        wrong = wrong.model_copy(update={"manifest_hash": manifest_hash_for(wrong)})
        # A valid differently admitted manifest, not a malformed JSON parser error.
        raw = canonical_json(wrong)
        assert parse_manifest_json(raw) == wrong
        monkeypatch.setattr(journal, "load_manifest_json", lambda _: raw)

    async def forbidden(**kwargs):
        pytest.fail("a changed retained WRITE identity reached host startup")

    monkeypatch.setattr(qualification, "_drive", forbidden)
    with pytest.raises(ContractViolation, match="retained WRITE"):
        await qualification.qualify_write(assembly=assembly, authorization=auth)


async def test_write_attempt_survives_a_whole_journal_reset(
    tmp_path, portable_binding, portable_write_boundary,
):
    first, auth = await sealed_assembly(tmp_path, portable_launcher(), portable_binding[1:])
    initial = await qualification.qualify_write(assembly=first, authorization=auth)
    assert initial.verdict == "passed", initial.model_dump_json()
    spent = Path(auth.attempt_record).read_bytes()
    # Retire only this test's dedicated database. The exclusive artifact and
    # actual captured Git candidate remain; neither grants another acquisition.
    Path(auth.journal).rename(tmp_path / "retired.sqlite")
    launcher = portable_launcher()
    second, _ = await sealed_assembly(tmp_path, launcher, portable_binding[1:], authorization=auth)
    assert second.resources.journal.run_state(auth.run_id) is None
    async with asyncio.timeout(30):
        report = await qualification.qualify_write(assembly=second, authorization=auth)
    assert report.verdict != "passed"
    assert second.resources.journal.run_state(auth.run_id).status is RunStatus.FAILED
    assert launcher.commands == callback_calls(launcher) == []
    assert not launcher.native.callback_responses and not second.executor.handles
    assert Path(auth.attempt_record).read_bytes() == spent
