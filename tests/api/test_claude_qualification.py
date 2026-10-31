"""Real admitted graph and leases, with only platform/process primitives doubled."""

import hashlib
import json
import os
import shutil
import sqlite3
import stat
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.ops import read_attempt_evidence as reader

from constructicon.api import _claude_read_fixture as fixture
from constructicon.api import claude_qualification as entry
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorError, ExecutorFailure
from constructicon.core.manifest import source_graph_hash_for
from constructicon.core.native_operator import NativeOperatorLaunchIdentityV3
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.run import RunStatus
from constructicon.substrate.executors import claude_provider as native
from constructicon.substrate.executors.claude_read_worker import READ_WORKER_LIMITS
from constructicon.substrate.executors.linux import LinuxLauncher, LinuxLaunchProfile, ProcessResult
from constructicon.substrate.git import contained
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.substrate.test_claude_lane import configuration
from tests.substrate.test_claude_provider import assembled as assembled
from tests.substrate.test_claude_provider import provider as provider
from tests.substrate.test_claude_read import Peer


class FixedPeer(Peer):
    answer = "ready"

    def emit(self, value):
        if value.get("type") == "result":
            value["result"] = self.answer
        if value.get("type") == "assistant":
            for content in value["message"]["content"]:
                if content.get("type") == "tool_use":
                    content["input"] = {"path": "ready.txt"}
        if value.get("type") == "control_request":
            message = value["request"].get("message", {})
            if message.get("method") == "tools/call":
                message["params"]["arguments"] = {"path": "ready.txt"}
        super().emit(value)

    async def write(self, raw):
        value = json.loads(raw)
        if (value.get("type") == "control_response"
                and value["response"]["request_id"] == "outer-tools/call"):
            response = value["response"]["response"]["mcp_response"]
            assert response["result"] == {
                "content": [{"type": "text", "text": "ready\n"}], "isError": False,
            }
            # Reuse the protocol peer's one-response sequencing assertion.
            response["result"]["content"][0]["text"] = "file text"
            raw = json.dumps(value).encode() + b"\n"
        await super().write(raw)


@pytest.fixture
async def qualified(assembled, tmp_path, monkeypatch):
    a = assembled
    monkeypatch.setattr(fixture, "_service_owner", lambda info: None)
    monkeypatch.setattr(fixture, "_ancestor_owner", lambda info: None)

    async def dispose(closure, paths, **kwargs):
        # Substitute only the Linux namespace/flock disposal primitive. The
        # real Git fence is retained and the temporary payload is removed.
        assert paths.root.is_relative_to(tmp_path)
        closure.commit(paths, **kwargs)
        if paths.payload.exists():
            shutil.rmtree(paths.payload)
        return True

    monkeypatch.setattr(contained, "dispose_acquisition", dispose)
    monkeypatch.setattr(native, "dispose_acquisition", dispose)
    root = tmp_path / "fixed-fixture"
    fixture.prepare_fixture(root)
    workspace = fixture.workspace_provider(root, a.kwargs["worker_launcher"])
    kwargs = {
        **a.kwargs, "workspace_provider": workspace, "closure": workspace.closure,
        "workspace_capability_id": entry.WORKSPACE_CAPABILITY,
        "workspace_revision": fixture.REVISION, "expected_base": fixture.BASE,
        "qualification": None,
    }
    identity = NativeOperatorLaunchIdentityV3(**{
        **a.executor.identity.model_dump(),
        **native.identity_fields(
            kwargs["launcher"], kwargs["worker_launcher"], workspace_provider=workspace,
            workspace_capability_id=entry.WORKSPACE_CAPABILITY,
            workspace_revision=fixture.REVISION, mode=kwargs["mode"],
            expected_base=fixture.BASE,
        ),
    })
    kwargs["identity"] = identity
    plain = native.ClaudeOperatorProvider(**kwargs)
    grants = entry.fixed_grants(plain)
    authorization = QualificationAuthorization(
        authorization_id="fixed-read", stage="qualification-read", actor_id="static:test",
        idempotency_key="fixed-read", scope=entry.SCOPE, binding=entry.EXECUTOR,
        source_graph_hash=source_graph_hash_for(entry.graph(grants)),
        capability_id=entry.CAPABILITY,
        revision=identity.revision, operator_binding_digest=identity.store.operator_binding_digest,
        journal=str(tmp_path / "claude.sqlite"), attempt_record=str(tmp_path / "read-attempt.json"),
        max_epoch=1, not_after=datetime.now(UTC) + timedelta(hours=1), grants=grants,
    )
    a.state.peer = FixedPeer()

    async def read(self, command, **options):
        assert self is kwargs["worker_launcher"]
        assert command[-1] == fixture.FILE
        assert a.state.guards == 2 and a.state.locks == 1
        content = (options["workspace"] / command[-1]).read_bytes()
        assert content == fixture.CONTENT
        a.state.workers.append(command)
        return ProcessResult(0, content, b"", .01, payload_returncode=0)

    monkeypatch.setattr(LinuxLauncher, "run", read)
    a.kwargs = {**kwargs, "qualification": authorization}
    a.executor = native.ClaudeOperatorProvider(**a.kwargs)
    return a


async def test_fixed_graph_admits_reads_and_replays_without_another_attempt(qualified):
    a = qualified
    authorization = a.executor.qualification
    assert entry.require_coherent(a.executor) is authorization
    assert await entry.qualify(a.executor) is RunStatus.SUCCEEDED
    assert a.executor.unavailable_reasons
    assert len(a.state.workers) == len(a.state.exchanges) == 1
    assert a.state.guards == a.state.locks == 0
    record = json.loads(Path(authorization.attempt_record).read_text())
    assert record["dispatch"] == "completed"
    assert record["facts"]["callback_started"] == record["facts"]["callback_completed"] == 1
    journal = SqliteJournal(authorization.journal)
    rows = journal.capability_leases(authorization.run_id)
    assert len(rows) == 2
    assert {row.binding_id for row in rows} == {entry.EXECUTOR, entry.WORKSPACE}
    assert all(row.state == "closed" for row in rows)
    assert await entry.qualify(a.executor) is RunStatus.SUCCEEDED
    assert len(a.state.exchanges) == 1


async def test_wrong_authorization_refuses_before_opening_journal(qualified):
    a = qualified
    authorization = a.executor.qualification
    for field, value in (
        ("binding", "other"), ("capability_id", "other"),
        ("journal", "relative.sqlite"), ("attempt_record", "relative.json"),
        ("revision", "another"), ("scope", entry.ScopePath(segments=("other",))),
        ("source_graph_hash", entry.digest("different", 1, {})),
        ("grants", authorization.grants.model_copy(update={"timeout_s": 121})),
    ):
        a.executor.qualification = authorization.model_copy(update={field: value})
        with pytest.raises(ContractViolation, match="exact Claude READ"):
            await entry.qualify(a.executor)
    assert not Path(authorization.journal).exists()
    assert not a.state.exchanges


async def test_zero_callback_is_not_a_read_proof(qualified):
    a = qualified
    a.state.peer.callback = False
    assert await entry.qualify(a.executor) is RunStatus.FAILED
    assert a.state.workers == []
    record = json.loads(Path(a.executor.qualification.attempt_record).read_text())
    assert record["dispatch"] != "completed"


@pytest.mark.parametrize("gate", [
    "system-init-model", "mcp-arguments", "barrier-control-request",
    "barrier-result", "barrier-user", "barrier-unknown", "post-result",
    "initialize", "settings", "hooks", "startup-snapshot-session", "settings-post", "hooks-post",
])
async def test_closed_refusal_survives_real_graph_journal_and_metadata(
    qualified, tmp_path, monkeypatch, gate,
):
    a = qualified
    authorization = a.executor.qualification.model_copy(
        update={"journal": str(tmp_path / "read.sqlite")},
    )
    a.kwargs = {**a.kwargs, "qualification": authorization}
    a.executor = native.ClaudeOperatorProvider(**a.kwargs)
    original = Peer.emit

    def emit(self, value):
        if value.get("type") == "control_response":
            body = value["response"].get("response", {})
            if gate == "initialize" and "account" in body:
                body["account"].update(tokenSource="none", apiKeySource="PRIVATE-SOURCE-CANARY")
            if ((gate == "settings" or (gate == "settings-post" and self.post))
                    and "applied" in body):
                body["applied"]["model"] = "PRIVATE-MODEL-CANARY"
            if (gate == "hooks" or (gate == "hooks-post" and self.post)) and "hooks" in body:
                body["hooks"] = ["PRIVATE-HOOK-CANARY"]
        if (gate == "startup-snapshot-session" and value.get("type") == "system"
                and value.get("subtype") == "background_tasks_changed"):
            value["session_id"] = "PRIVATE-SESSION-CANARY"
        if (gate == "system-init-model" and value.get("type") == "system"
                and value.get("subtype") == "init"):
            value["model"] = "PRIVATE-MODEL-CANARY"
        # FixedPeer has chosen ready.txt before delegating to this base emitter.
        if gate == "mcp-arguments" and value.get("type") == "control_request":
            message = value["request"].get("message", {})
            if message.get("method") == "tools/call":
                message["params"]["arguments"]["path"] = "../PRIVATE-PATH-CANARY"
        original(self, value)
        if gate == "post-result" and value.get("type") == "result":
            original(self, {"type": "system", "subtype": "PRIVATE-SUBTYPE-CANARY"})
        if (gate.startswith("barrier-") and value.get("type") == "control_response"
                and "account" in value["response"].get("response", {})):
            frame_type = gate.removeprefix("barrier-")
            if frame_type == "control-request":
                frame_type = "control_request"
            if frame_type == "unknown":
                frame_type = "PRIVATE-UNKNOWN-CANARY"
            original(self, {"type": frame_type, "payload": "PRIVATE-BARRIER-CANARY"})

    monkeypatch.setattr(Peer, "emit", emit)
    assert await entry.qualify(a.executor) is RunStatus.FAILED
    completed = gate in {"post-result", "settings-post", "hooks-post"}
    assert len(a.state.workers) == int(completed)
    before_user = (gate.startswith(("barrier-", "startup-"))
                   or gate in {"initialize", "settings", "hooks"})
    assert len(a.state.peer.users) == (0 if before_user else 1)
    assert a.state.guards == a.state.locks == 0 and a.state.native_joined
    # Read the actual graph's attempt and SQLite, replacing only UID/mode primitives.
    uid = 123
    ancestors = {(p.stat().st_dev, p.stat().st_ino) for p in tmp_path.parents}
    root_id = tmp_path.stat().st_dev, tmp_path.stat().st_ino

    def permissions(info):
        identity = info.st_dev, info.st_ino
        if identity in ancestors:
            return 0, stat.S_IMODE(info.st_mode) & ~0o22
        if identity == root_id:
            return uid, 0o700
        return uid, 0o600 if os.name == "nt" else stat.S_IMODE(info.st_mode)

    monkeypatch.setattr(reader, "_permissions", permissions)
    monkeypatch.setattr(reader, "_service_uid", lambda: uid)
    monkeypatch.setattr(reader, "_effective_uid", lambda: uid)
    projected = reader.collect(
        tmp_path, authorization.authorization_id, str(authorization.run_id), 1,
    )
    assert projected["attempt"]["state"] == projected["journal"]["state"] == "valid"
    assert (projected["attempt"]["callback_started"]
            == projected["attempt"]["callback_completed"] == int(completed))
    failures = [event for event in projected["journal"]["events"] if event["kind"] == "NodeFailed"]
    assert len(failures) == 1
    failure = failures[0]
    assert {key: failure[key] for key in ("kind", "error_type", "reason")} == {
        "kind": "NodeFailed", "error_type": "ContractViolation",
        "reason": ("claude_read_initialize" if gate == "initialize"
                   else "claude_read_system_other" if gate == "post-result"
                   else "claude_read_" + gate.removesuffix("-post").replace("-", "_")),
    }
    if gate == "initialize":
        assert failure["initialize_observation"] == {
            "verdict": "mode-mismatch", "reason": "credential-source-present",
            "token_source": "none", "api_key_source": "unknown",
        }
    elif gate.startswith("startup-"):
        assert set(failure) == {"kind", "error_type", "reason"}
    else:
        context = failure["refusal_context"]
        assert set(context) == {"family", "phase", "predicate", "terminal_result_accepted"}
        assert context["terminal_result_accepted"] is completed
    if gate in {"settings", "hooks", "settings-post", "hooks-post"}:
        assert context == {"family": "other-record",
                           "phase": "post-result" if completed else "startup",
                           "predicate": "guard", "terminal_result_accepted": completed}
    if gate == "system-init-model":
        assert context == {"family": "system-init", "phase": "body-before-callback",
                           "predicate": "guard", "terminal_result_accepted": False}
    if gate == "post-result":
        assert context == {"family": "system-unknown-subtype", "phase": "post-result",
                           "predicate": "unsupported-family", "terminal_result_accepted": True}
    if before_user:
        assert projected["attempt"]["dispatch"] == "not dispatched"
        assert projected["attempt"]["initial_binding_checked"] is True
        assert projected["attempt"]["terminal_binding_checked"] is True
        assert projected["attempt"]["relay_closed"] is True
    from scripts.ops import read_metadata_session as metadata
    assert metadata.observation_checked(json.dumps(projected).encode()) == projected
    published = json.dumps(projected)
    assert "PRIVATE" not in published and str(tmp_path) not in published
    assert (authorization.authorization_id not in published
            and str(authorization.run_id) not in published)


@pytest.mark.parametrize("kind,detail", [
    ("exit", "PRIVATE-ACCOUNT-CANARY"),
    ("exit", "Claude READ refused [known_refusal=PRIVATE-CANARY]"),
    ("exit", "Claude READ refused [known_refusal=api-retry; family=system-api-retry; "
             "phase=drain; predicate=phase; terminal_result_accepted=false; private=PRIVATE]"),
    ("exit", "Claude READ refused [known_refusal=api-retry; family=PRIVATE-CANARY; "
             "phase=drain; predicate=phase; terminal_result_accepted=false]"),
    ("timeout", "Claude READ refused [known_refusal=system-init-model]"),
    ("exit", "Claude READ refused [initialize observed: verdict=PRIVATE-CANARY; "
             "reason=credential-source-present; token_source=none; api_key_source=unknown]"),
    ("exit", "Claude READ refused [initialize observed: verdict=mode-mismatch; "
             "reason=PRIVATE-CANARY; token_source=none; api_key_source=unknown]"),
    ("exit", "Claude READ refused [initialize observed: verdict=mode-mismatch; "
             "reason=credential-source-present; token_source=PRIVATE-CANARY; "
             "api_key_source=unknown]"),
    ("exit", "Claude READ refused [initialize observed: verdict=mode-mismatch; "
             "reason=credential-source-present; token_source=none; api_key_source=PRIVATE-CANARY]"),
])
async def test_graph_never_journals_unrecognized_or_nonexit_detail(
    qualified, monkeypatch, kind, detail,
):
    async def failed(self, task, worker):
        return ExecutorFailure(error=ExecutorError(kind=kind, detail=detail))

    monkeypatch.setattr(native.ClaudeOperatorHandle, "_run", failed)
    assert await entry.qualify(qualified.executor) is RunStatus.FAILED
    authorization = qualified.executor.qualification
    with sqlite3.connect(authorization.journal) as db:
        (raw,) = db.execute("SELECT payload FROM events WHERE kind='NodeFailed'").fetchone()
    assert json.loads(raw)["error"] == "Claude qualification did not complete its fixed READ"
    assert "PRIVATE" not in raw and detail not in raw
    assert qualified.state.guards == qualified.state.locks == 0


async def test_a_completed_callback_still_requires_the_fixed_answer(qualified):
    a = qualified
    a.state.peer.answer = "a different answer"
    assert await entry.qualify(a.executor) is RunStatus.FAILED
    assert len(a.state.workers) == 1


def test_assemble_threads_exact_config_pin_and_separate_worker_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = configuration(tmp_path)
    config_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    options = SimpleNamespace(
        fixture=tmp_path / "fixture", launch_config=path, launch_config_sha256=config_sha,
        store_root=tmp_path / "store", store_key="reviewed-key",
        sealed=tmp_path / "sealed.json", qualification=tmp_path / "qualification.json",
        acquisition_root=tmp_path / "acquisitions",
    )
    calls: list[tuple[object, ...]] = []

    def workspace(root: Path, worker: LinuxLauncher) -> SimpleNamespace:
        calls.append(("workspace", root, worker))
        return SimpleNamespace(launcher=replace(worker, limits=fixture.MATERIALIZATION_LIMITS))

    def host_provider(host: object, **kwargs: object) -> object:
        calls.append(("host", host, kwargs))
        return "assembled"

    monkeypatch.setattr(entry.fixture, "workspace_provider", workspace)
    monkeypatch.setattr(entry, "operator_provider", host_provider)
    assert entry.assemble(options) == "assembled"
    _, root, worker = calls[0]
    _, host, kwargs = calls[1]
    assert root == options.fixture and isinstance(worker, LinuxLauncher)
    assert worker.limits == READ_WORKER_LIMITS
    assert worker.claude is None and worker.vendor is None
    assert worker.effective_profile is LinuxLaunchProfile.CLAUDE_BOOTSTRAP
    assert worker.expected_runtime == entry.read_configuration(
        path, expected_sha256=config_sha,
    ).runtime_digest
    assert host == entry.ClaudeHostSession(
        configuration=path, configuration_sha256=config_sha,
        store_root=options.store_root, store_key=options.store_key,
        sealed=options.sealed, qualification=options.qualification,
        acquisition_root=options.acquisition_root,
    )
    assert kwargs["worker_launcher"] is worker
    assert kwargs["workspace"].launcher.limits == fixture.MATERIALIZATION_LIMITS
    assert kwargs["workspace"].launcher.effective_profile is LinuxLaunchProfile.CLAUDE_BOOTSTRAP
    assert kwargs["workspace_capability_id"] == entry.WORKSPACE_CAPABILITY
    assert kwargs["workspace_revision"] == fixture.REVISION
    assert kwargs["expected_base"] == fixture.BASE
    calls.clear()
    options.launch_config_sha256 = "0" * 64
    with pytest.raises(ValueError, match="reviewed bytes"):
        entry.assemble(options)
    assert calls == []


def test_mint_pins_fixed_graph_grants_and_one_epoch_without_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = entry.digest("test-binding", 1, "fixed")
    provider = SimpleNamespace(
        launcher=SimpleNamespace(claude=SimpleNamespace(model="model", effort="high")),
        identity=SimpleNamespace(revision="test-revision", store=SimpleNamespace(
            operator_binding_digest=binding,
        )),
    )
    calls: list[object] = []
    monkeypatch.setattr(entry, "assemble", lambda options: calls.append(options) or provider)
    options = SimpleNamespace(
        authorization_id="fixed-read", actor="static:test", key="fixed-read",
        journal=tmp_path / "journal.sqlite", attempt_record=tmp_path / "attempt.json",
        hours=1.0,
    )
    authorization = entry.mint(options)
    assert calls == [options]
    assert authorization.stage == "qualification-read" and authorization.max_epoch == 1
    assert authorization.scope == entry.SCOPE and authorization.binding == entry.EXECUTOR
    assert authorization.capability_id == entry.CAPABILITY
    assert authorization.revision == provider.identity.revision
    assert authorization.operator_binding_digest == binding
    assert authorization.grants == entry.fixed_grants(provider)
    assert authorization.source_graph_hash == source_graph_hash_for(
        entry.graph(authorization.grants),
    )
    assert authorization.attempt_record == str(options.attempt_record)


def test_cli_only_run_dispatches_and_passes_exact_parsed_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[object, ...]] = []
    fixture_path = tmp_path / "fixture"
    monkeypatch.setattr(entry.fixture, "prepare_fixture", lambda path: (
        calls.append(("prepare", path)) or fixture.REVISION
    ))
    def mint(options: object) -> SimpleNamespace:
        calls.append(("mint", options))
        return SimpleNamespace(model_dump_json=lambda: '{"minted":true}')

    monkeypatch.setattr(entry, "mint", mint)
    token = object()
    monkeypatch.setattr(entry, "read_authorization", lambda path: (
        calls.append(("read-authorization", path)) or token
    ))
    monkeypatch.setattr(entry, "assemble", lambda options, authorization: (
        calls.append(("assemble", options, authorization)) or "provider"
    ))

    async def qualify(provider: object) -> RunStatus:
        calls.append(("qualify", provider))
        return RunStatus.SUCCEEDED

    monkeypatch.setattr(entry, "qualify", qualify)
    assert entry.main(["prepare", "--fixture", str(fixture_path)]) == 0
    assert calls == [("prepare", fixture_path)]
    assert json.loads(capsys.readouterr().out)["fixture_revision"] == fixture.REVISION
    common = [
        "--fixture", str(fixture_path), "--launch-config", str(tmp_path / "config.json"),
        "--launch-config-sha256", "a" * 64, "--store-root", str(tmp_path / "store"),
        "--store-key", "reviewed-key", "--sealed", str(tmp_path / "sealed.json"),
        "--qualification", str(tmp_path / "qualification.json"),
        "--acquisition-root", str(tmp_path / "acquisitions"),
    ]
    calls.clear()
    assert entry.main(["mint", *common, "--authorization-id", "one", "--actor", "static:test",
                       "--key", "one", "--journal", str(tmp_path / "journal.sqlite"),
                       "--attempt-record", str(tmp_path / "attempt.json")]) == 0
    assert len(calls) == 1 and calls[0][0] == "mint"
    assert calls[0][1].launch_config_sha256 == "a" * 64
    assert calls[0][1].store_key == "reviewed-key"
    assert json.loads(capsys.readouterr().out) == {"minted": True}
    calls.clear()
    authorization_path = tmp_path / "authorization.json"
    assert entry.main(["run", *common, "--authorization", str(authorization_path)]) == 0
    assert calls[0] == ("read-authorization", authorization_path)
    assert calls[1][0] == "assemble" and calls[1][2] is token
    assert calls[1][1].launch_config == tmp_path / "config.json"
    assert calls[1][1].store_root == tmp_path / "store"
    assert calls[2] == ("qualify", "provider")
    assert json.loads(capsys.readouterr().out) == {"status": RunStatus.SUCCEEDED.value}
