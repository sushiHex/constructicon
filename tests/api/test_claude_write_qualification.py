"""Actual capture/gate lifecycle; only platform and process primitives are doubled.

Trusted fixed Git/capture/check programs run locally against temporary data.
This portable lane is state evidence, never Linux containment evidence.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.api import _qualification_write_assembly as contained_assembly
from constructicon.api import _qualification_write_graph as fixed
from constructicon.api import claude_write_qualification as entry
from constructicon.api import qualification
from constructicon.api.control import ControlPlane
from constructicon.api.detail import DEFAULT_DETAIL_BYTES
from constructicon.core.address import ExecutionPath
from constructicon.core.control import RunSubmission
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.core.manifest import source_graph_hash_for
from constructicon.core.native_operator import NativeOperatorLaunchIdentityV3
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.qualification_write import WriteReportIssue
from constructicon.core.run import RunStatus
from constructicon.substrate.executors import claude_provider as native
from constructicon.substrate.executors.claude_host import write_profile
from constructicon.substrate.executors.claude_native import ClaudeNativeRecipe
from constructicon.substrate.executors.claude_write_worker import (
    WRITE_WORKER_COMMAND,
    WRITE_WORKER_LIMITS,
)
from constructicon.substrate.executors.linux import LinuxLauncher, ProcessResult
from constructicon.substrate.gates import contained as gate_module
from constructicon.substrate.git import acquisition, contained
from constructicon.substrate.git.authority import _PINNED_ENV, _set_write_bits
from constructicon.substrate.git.process import GitProcess
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.substrate.test_claude_provider import assembled as assembled
from tests.substrate.test_claude_provider import provider as provider
from tests.substrate.test_claude_read import Peer

PROGRAM = "from pathlib import Path; Path('n5-write.txt').write_bytes(b'ready\\n')"


class WritePeer(Peer):
    program = PROGRAM

    def emit(self, value):
        if value.get("type") == "system" and value.get("subtype") == "init":
            value["tools"] = ["mcp__constructicon_write__contained_python"]
            value["mcp_servers"] = [{"name": "constructicon_write", "status": "connected"}]
        if value.get("type") == "assistant":
            for content in value["message"]["content"]:
                if content.get("type") == "tool_use":
                    content.update(name="mcp__constructicon_write__contained_python",
                                   input={"program": self.program})
        if value.get("type") == "control_request":
            request = value["request"]
            request["server_name"] = "constructicon_write"
            message = request.get("message", {})
            if message.get("method") == "tools/call":
                message["params"] = {"name": "contained_python",
                                     "arguments": {"program": self.program}}
        super().emit(value)

    async def write(self, raw):
        value = json.loads(raw)
        if value.get("type") == "control_response":
            response = value["response"]
            message = response["response"]["mcp_response"]
            if response["request_id"] == "outer-tools/list":
                assert message["result"]["tools"] == [ClaudeNativeRecipe.STREAM_JSON_WRITE.tool]
                # Base peer's sequencing assertions are READ-specific.
                from constructicon.substrate.executors.claude_read import READ_TOOL

                message["result"]["tools"] = [READ_TOOL]
            elif response["request_id"] == "outer-tools/call":
                assert message["result"] == {
                    "content": [{"type": "text", "text": ""}], "isError": False,
                }
                message["result"]["content"][0]["text"] = "file text"
            raw = json.dumps(value).encode() + b"\n"
        await super().write(raw)


@pytest.fixture
async def qualified(assembled, tmp_path, monkeypatch, portable_acquisition_namespace):
    a = assembled
    monkeypatch.setattr(contained_assembly, "_private_owner", lambda info: None)
    monkeypatch.setattr(contained_assembly, "_ancestor_owner", lambda info: None)

    @asynccontextmanager
    async def guard(paths):
        paths.guard.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(paths.guard, os.O_CREAT | os.O_RDWR, 0o600)
        a.state.guards += 1
        try:
            yield descriptor
        finally:
            a.state.guards -= 1
            os.close(descriptor)

    for module in (native, acquisition, contained, gate_module):
        monkeypatch.setattr(module, "acquisition_guard", guard)

    if os.name == "nt":
        original_rmtree = shutil.rmtree

        def remove(path, *args, **kwargs):
            target = Path(path).resolve(strict=True)
            assert target != tmp_path and target.is_relative_to(tmp_path)
            _set_write_bits(target, writable=True)
            return original_rmtree(path, *args, **kwargs)

        remove.avoids_symlink_attacks = True
        monkeypatch.setattr(shutil, "rmtree", remove)
        original_run = GitProcess.run

        async def immutable_git(self, *args, **kwargs):
            kwargs["guard"] = None
            return await original_run(self, *args, **kwargs)

        monkeypatch.setattr(GitProcess, "run", immutable_git)

    resource_launcher = replace(a.kwargs["worker_launcher"], limits=a.kwargs["launcher"].limits)
    worker = replace(resource_launcher, limits=WRITE_WORKER_LIMITS)
    launcher = replace(a.kwargs["launcher"], claude_recipe=ClaudeNativeRecipe.STREAM_JSON_WRITE)
    a.state.peer = WritePeer()
    a.state.commands = []

    async def run(self, command, **options):
        if options.get("workspace") is None:
            return ProcessResult(0, b"Python fixture\n", b"", .01, payload_returncode=0)
        for descriptor in options["guard_fds"]:
            os.fstat(descriptor)
        a.state.commands.append(command)
        if command == WRITE_WORKER_COMMAND:
            assert options["stdin"].decode() == a.state.peer.program
            a.state.workers.append(command)
            if a.state.peer.program == PROGRAM:
                (options["workspace"] / "n5-write.txt").write_bytes(b"ready\n")
            else:
                assert a.state.peer.program == "pass"
            return ProcessResult(0, b"", b"", .01, payload_returncode=0)
        git = shutil.which("git")
        assert git
        actual = list(command)
        if actual[0] == "/usr/bin/python3":
            actual[0] = sys.executable
            actual[3] = actual[3].replace("'/usr/bin/git'", repr(git))
            actual = [sys.executable if arg == "/usr/bin/python3" else arg for arg in actual]
        else:
            assert actual[:2] == ["/usr/bin/git", "pack-objects"]
            actual[0] = git
        result = await asyncio.to_thread(
            subprocess.run, actual, cwd=options["workspace"], input=options.get("stdin", b""),
            capture_output=True, check=False, timeout=30, env={**os.environ, **_PINNED_ENV},
        )
        return ProcessResult(result.returncode, result.stdout, result.stderr, .01,
                             payload_returncode=result.returncode)

    async def exchange(self, command, **options):
        assert self is launcher and options["workspace"] is None
        a.state.exchanges.append(options)
        options["native_store"].before_spawn()
        try:
            await options["conversation"](a.state.peer)
            return ProcessResult(0, b"", b"", .01, payload_returncode=0)
        finally:
            a.state.native_joined = True

    monkeypatch.setattr(LinuxLauncher, "run", run)
    monkeypatch.setattr(LinuxLauncher, "exchange", exchange)
    root = tmp_path / "fixed-write"
    contained_assembly.prepare_fixture(root)
    journal = SqliteJournal(tmp_path / "write.sqlite")
    resources = await contained_assembly.assemble_contained_write(root, journal, resource_launcher)
    pins = contained_assembly.contained_pins(resources, entry.report_definition())
    profile = write_profile(SimpleNamespace(model="model", effort="high"))
    kwargs = {**a.kwargs, "launcher": launcher, "worker_launcher": worker,
              "profile": profile, "workspace_provider": resources.workspace,
              "closure": resources.workspace.closure,
              "workspace_capability_id": contained_assembly.WORKSPACE_CAPABILITY,
              "workspace_revision": str(resources.workspace.revision),
              "expected_base": resources.fixture.base_commit, "qualification": None}
    identity = NativeOperatorLaunchIdentityV3(**{
        **a.executor.identity.model_dump(), "profile": profile,
        **native.identity_fields(
            launcher, worker, workspace_provider=resources.workspace,
            workspace_capability_id=contained_assembly.WORKSPACE_CAPABILITY,
            workspace_revision=str(resources.workspace.revision), mode=kwargs["mode"],
            expected_base=resources.fixture.base_commit,
        ),
    })
    kwargs["identity"] = identity
    plain = native.ClaudeOperatorProvider(**kwargs)
    grants = entry.fixed_grants(plain)
    authorization = QualificationAuthorization(
        authorization_id="fixed-claude-write", stage="qualification-write", actor_id="static:test",
        idempotency_key="fixed-write", scope=fixed.WRITER_SCOPE, binding=fixed.EXECUTOR,
        capability_id=entry.CAPABILITY,
        source_graph_hash=source_graph_hash_for(entry.graph(grants, pins)),
        revision=identity.revision, operator_binding_digest=identity.store.operator_binding_digest,
        journal=str(tmp_path / "write.sqlite"), attempt_record=str(tmp_path / "write-attempt.json"),
        max_epoch=1, not_after=datetime.now(UTC) + timedelta(hours=1), grants=grants, write=pins,
    )
    a.kwargs = {**kwargs, "qualification": authorization}
    a.executor = native.ClaudeOperatorProvider(**a.kwargs)
    a.assembly = entry.ClaudeWriteAssembly(a.executor, resources, pins)
    a.authorization = authorization

    async def reconstruct():
        fresh_resources = await contained_assembly.assemble_contained_write(
            root, SqliteJournal(authorization.journal), resource_launcher,
        )
        fresh = native.ClaudeOperatorProvider(**{
            **a.kwargs, "workspace_provider": fresh_resources.workspace,
            "closure": fresh_resources.workspace.closure,
        })
        return entry.ClaudeWriteAssembly(fresh, fresh_resources, pins)

    a.reconstruct = reconstruct
    return a


async def test_actual_capture_gate_report_and_replay(qualified):
    a = qualified
    report = await entry.qualify(assembly=a.assembly, authorization=a.authorization)
    assert report.verdict == "passed", (
        [event.payload for event in a.assembly.resources.journal.events(a.authorization.run_id)
         if event.kind == "NodeFailed"],
    )
    resources = a.assembly.resources
    assert report.candidate != resources.fixture.base_commit
    assert resources.authority.tree_of(report.candidate) == report.candidate_tree
    assert resources.authority._run("ls-tree", "-r", report.candidate).stdout.split() == [
        "100644", "blob", resources.authority._run(
            "rev-parse", f"{report.candidate}:n5-write.txt",
        ).stdout.strip(), "n5-write.txt",
    ]
    assert resources.authority._run("show", f"{report.candidate}:n5-write.txt").stdout == "ready\n"
    attestation = resources.journal.load_attestation(report.attestation_id)
    assert attestation and attestation.subject.tested_tree == report.candidate_tree
    assert attestation.subject.candidate == report.candidate
    assert report.target_unchanged is True
    assert report.obligation_count == 3
    assert {row.role for row in report.obligations} == {"executor", "workspace", "gate"}
    assert all(row.state == "closed" and row.disposition == "released"
               for row in report.obligations)
    assert report.telemetry.callbacks.admitted_completed == 1
    assert report.telemetry.callbacks.worker_results == ("success",)
    assert report.telemetry.callbacks_final_snapshot is True
    assert report.telemetry.served_model is report.telemetry.input_tokens is None
    assert report.telemetry.before is report.telemetry.after is None
    assert report.limits.program_bytes == 128 * 1024
    assert report.limits.callback_output_bytes == 32 * 1024
    assert str(report.installed.capability_revision) == a.executor.identity.revision
    assert len(a.state.workers) == len(a.state.exchanges) == 1
    assert a.state.guards == a.state.locks == 0
    assert a.executor.unavailable_reasons
    assert not list(resources.workspace.root.glob("payloads/*"))
    assert not list(resources.gate.root.glob("payloads/*"))
    assert len(report.model_dump_json().encode()) <= DEFAULT_DETAIL_BYTES
    assert await entry.qualify(assembly=a.assembly, authorization=a.authorization) == report
    assert len(a.state.workers) == len(a.state.exchanges) == 1


async def test_noop_refuses_before_writer_checkpoint_or_gate(qualified):
    a = qualified
    a.state.peer.program = "pass"
    report = await entry.qualify(assembly=a.assembly, authorization=a.authorization)
    journal = a.assembly.resources.journal
    assert report.verdict != "passed"
    assert journal.run_state(a.authorization.run_id).status is RunStatus.FAILED
    assert journal.checkpoint(a.authorization.run_id,
                              ExecutionPath(scope=fixed.WRITER_SCOPE)) is None
    rows = journal.capability_leases(a.authorization.run_id)
    assert {row.binding_id for row in rows} == {fixed.EXECUTOR, fixed.WORKSPACE}
    assert all(row.state == "closed" and row.disposition == "discarded" for row in rows)
    events = journal.events(a.authorization.run_id)
    assert any(event.kind == "NodeFailed" and event.payload.get("error")
               == "the WRITE qualification captured no change" for event in events)
    assert json.loads(Path(a.authorization.attempt_record).read_text())["dispatch"] == "completed"
    spent = Path(a.authorization.attempt_record).read_bytes()
    replay = await entry.qualify(assembly=a.assembly, authorization=a.authorization)
    assert replay.verdict != "passed"
    assert Path(a.authorization.attempt_record).read_bytes() == spent
    assert len(a.state.workers) == len(a.state.exchanges) == 1
    assert a.state.guards == a.state.locks == 0


async def test_authorization_and_actual_pins_refuse_before_dispatch(qualified):
    a = qualified
    for field, value in (
        ("capability_id", "other"), ("binding", "other"),
        ("revision", "other"), ("source_graph_hash", digest("other", 1, {})),
        ("write", a.assembly.pins.model_copy(update={"report_definition": digest("other", 1, {})})),
        ("grants", a.authorization.grants.model_copy(update={"timeout_s": 301})),
    ):
        authorization = a.authorization.model_copy(update={field: value})
        a.executor.qualification = authorization
        with pytest.raises(ContractViolation):
            await entry.qualify(assembly=a.assembly, authorization=authorization)
    assert a.state.exchanges == a.state.workers == []
    assert not Path(a.authorization.attempt_record).exists()


async def test_report_refuses_zero_or_contradictory_callback_census(qualified):
    a = qualified
    original = entry.derive_report
    observed = []

    def capture(system, assembly, authorization, observation):
        observed.append(system)
        return original(system, assembly, authorization, observation)

    from unittest.mock import patch

    with patch.object(entry, "derive_report", capture):
        report = await entry.qualify(assembly=a.assembly, authorization=a.authorization)
    assert report.verdict == "passed"
    path = Path(a.authorization.attempt_record)
    record = json.loads(path.read_text())
    record["callbacks"] = {"schema_version": 1, "admitted_started": 0,
                           "admitted_completed": 0, "worker_results": []}
    path.write_text(json.dumps(record))
    invalid = original(observed[0], a.assembly, a.authorization, "terminal")
    assert invalid.verdict != "passed"
    assert WriteReportIssue.ATTEMPT_INVALID in invalid.issues
    assert len(invalid.model_dump_json().encode()) <= DEFAULT_DETAIL_BYTES


@pytest.mark.parametrize("checkpointed", [False, True])
async def test_cold_recovery_never_redispatches_spent_write(qualified, monkeypatch, checkpointed):
    a = qualified
    resources, authorization = a.assembly.resources, a.authorization
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

        async def pause_after_capture(view, message):
            candidate = await original_capture(view, message)
            assert candidate != view.base
            reached.set()
            await asyncio.Event().wait()
            return candidate

        monkeypatch.setattr(resources.workspace, "capture", pause_after_capture)

    control = ControlPlane(system=entry._system(a.assembly), store=resources.journal)
    actor = entry.AuthenticatedActor(actor_id=authorization.actor_id, auth_method="static",
                                     scopes=frozenset({entry.READ_SCOPE, entry.ADMIN_SCOPE}))
    await control.startup()
    try:
        await qualification._bootstrap_definitions(control, actor, entry.definitions())
        submitted = await control.runs_start(
            actor, proposal=entry.graph(entry.fixed_grants(a.executor), a.assembly.pins),
            inputs=fixed.write_inputs(authorization), idempotency_key=authorization.idempotency_key,
        )
        assert isinstance(submitted, RunSubmission) and submitted.run_id == authorization.run_id
        async with asyncio.timeout(90):
            await reached.wait()
        checkpoint = resources.journal.checkpoint(authorization.run_id,
                                                   ExecutionPath(scope=fixed.WRITER_SCOPE))
        assert (checkpoint is not None) is checkpointed
    finally:
        await control.shutdown()
    assert resources.journal.run_state(authorization.run_id).status is RunStatus.RUNNING
    assert resources.journal.cancel_requested(authorization.run_id) is False
    spent = Path(authorization.attempt_record).read_bytes()
    exchanges, workers = len(a.state.exchanges), len(a.state.workers)
    fresh = await a.reconstruct()
    report = await entry.qualify(assembly=fresh, authorization=authorization)
    assert fresh.resources.journal.run_state(authorization.run_id).status is (
        RunStatus.SUCCEEDED if checkpointed else RunStatus.FAILED
    )
    assert (report.verdict == "passed") is checkpointed, report.model_dump_json()
    assert len(a.state.exchanges) == exchanges == 1
    assert len(a.state.workers) == workers == 1
    assert Path(authorization.attempt_record).read_bytes() == spent
    assert not fresh.executor._handles
    if checkpointed:
        retained = fresh.resources.journal.checkpoint(
            authorization.run_id, ExecutionPath(scope=fixed.WRITER_SCOPE),
        )
        assert retained == checkpoint
        assert all(row.state == "closed" for row in report.obligations)
    assert a.state.guards == a.state.locks == 0
