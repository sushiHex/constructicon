"""One addressed durable member prepares actual V2 source with no native call."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from examples import change_review as source
from examples import change_review_batch as batch
from scripts.ops import change_review_batch_prepare as bridge
from scripts.ops import change_review_input as consumer
from scripts.ops import change_review_reply as collector

from constructicon.api import change_review_advice as advice
from constructicon.core.run import RunStatus
from tests.test_change_review_input import source_world as source_world


@pytest.fixture
async def durable(tmp_path):
    repository = tmp_path / "target"
    repository.mkdir()
    source.git(repository, "init", "--quiet")
    commits = []
    for version in (1, 2):
        # A module-level edit cannot be upgraded from the V1 public-symbol facts.
        (repository / "alpha.py").write_text(f"VALUE = {version}\n", encoding="utf-8")
        (repository / "beta.py").write_text(f"def beta(): return {version}\n", encoding="utf-8")
        source.git(repository, "add", "alpha.py", "beta.py")
        source.git(repository, "-c", "user.name=Example", "-c",
                   "user.email=example@example.invalid", "commit", "-qm", "fixture")
        commits.append(source.git(repository, "rev-parse", "HEAD").decode().strip())
    files = batch.prepare_batch(repository, *commits, ("alpha.py", "beta.py"))
    state = tmp_path / "state"
    state.mkdir()
    system, control = source.assemble(state / "review.db")
    versions = await source.register(control)
    submission = source.checked(await control.runs_start(
        source.OPERATOR, proposal=batch.batch_graph(versions, files),
        inputs={f"change_{key}": value.model_dump(mode="json") for key, value in files.items()},
        idempotency_key="prepare-test",
    ))
    await source.wait_for(control, submission.run_id, allow_parked=True)
    assert source.checked(control.runs_status(source.OPERATOR, submission.run_id)).status \
        is RunStatus.PARKED
    yield system, control, submission.run_id, files, repository, commits, state
    await control.shutdown()


def selected(files, path="alpha.py"):
    return next(key for key, value in files.items() if value.before_ref.paths == (path,))


async def test_separate_controller_and_target_preserve_packet_bytes_and_real_v2(
    durable, source_world, tmp_path,
):
    system, control, run_id, files, repository, commits, _state = durable
    controller_repository, controller, _before, _after = source_world
    file_id = selected(files)
    out = tmp_path / "bound"
    binding = bridge.prepare_batch_input(
        system, control, run_id=run_id, file_id=file_id, controller=controller,
        controller_repository=controller_repository, out=out,
    )
    direct = tmp_path / "direct"
    consumer.prepare(repository, controller, *commits, "alpha.py", direct,
                     controller_repository=controller_repository)
    for name in bridge.PACKET_FILES:
        raw = (out / name).read_bytes()
        assert raw == (direct / name).read_bytes()
        assert binding["packet_sha256"][name] == hashlib.sha256(raw).hexdigest()
    assert set(binding) == bridge.BINDING_FIELDS
    assert json.loads((out / "binding.json").read_bytes()) == binding
    assert len((out / "binding.json").read_bytes()) < bridge.BINDING_LIMIT
    assert b"\r" not in (out / "binding.json").read_bytes()
    assert binding["before_ref"] == files[file_id].before_ref.model_dump(mode="json")
    summary = advice.ChangeSummaryV2.model_validate_json((out / "summary.json").read_bytes())
    assert summary.module_ast_changed is True
    assert summary.symbols == {"added": [], "removed": [], "changed": []}
    assert summary.kinds.model_dump() == {"added": [], "removed": [], "changed": []}
    assert summary.changed_parts == []
    assert not (repository / "src").exists()
    with pytest.raises(ValueError, match="review_git_failed"):
        source.git(repository, "cat-file", "-t", controller)
    # Same key material with an explicit default source location is unchanged.
    old, explicit = tmp_path / "old", tmp_path / "explicit"
    consumer.prepare(*source_world, "calc.py", old)
    consumer.prepare(*source_world, "calc.py", explicit,
                     controller_repository=controller_repository)
    assert {name: (old / name).read_bytes() for name in bridge.PACKET_FILES} == {
        name: (explicit / name).read_bytes() for name in bridge.PACKET_FILES
    }


async def test_selection_survives_sibling_progress_but_refuses_answered_target(durable):
    system, control, run_id, files, _repository, _commits, _state = durable
    file_id, sibling = selected(files), selected(files, "beta.py")
    original = bridge.select_binding(system, control, run_id, file_id)
    other = bridge.select_binding(system, control, run_id, sibling)
    source.checked(await control.channels_reply(
        source.OPERATOR, message_id=other["request_id"], payload="sibling advice",
        idempotency_key="sibling-reply",
    ))
    assert bridge.select_binding(system, control, run_id, file_id) == original
    with pytest.raises(ValueError, match="batch_request_answered"):
        bridge.select_binding(system, control, run_id, sibling)
    assert bridge.select_binding(system, control, run_id, sibling,
                                 require_unanswered=False) == other
    source.checked(await control.channels_reply(
        source.OPERATOR, message_id=original["request_id"], payload="target advice",
        idempotency_key="target-reply",
    ))
    assert bridge.select_binding(system, control, run_id, file_id,
                                 require_unanswered=False) == original
    await source.wait_for(control, run_id, allow_parked=False)
    with pytest.raises(ValueError, match="batch_run_terminal"):
        bridge.select_binding(system, control, run_id, file_id)


async def test_unknown_source_mismatch_and_missing_request_refuse_before_claim(
    durable, source_world, tmp_path, monkeypatch,
):
    system, control, run_id, files, _repository, _commits, _state = durable
    controller_repository, controller, _, _ = source_world
    kwargs = dict(run_id=run_id, file_id=selected(files), controller=controller,
                  controller_repository=controller_repository)
    unknown = tmp_path / "unknown"
    with pytest.raises(ValueError, match="batch_file_unknown"):
        bridge.prepare_batch_input(system, control, **{**kwargs, "file_id": "unknown"},
                                   out=unknown)
    assert not unknown.exists()
    real = source.committed_source

    def changed(*args):
        reference, text = real(*args)
        return reference, text + "\ndef invented(): pass\n"

    monkeypatch.setattr(source, "committed_source", changed)
    mismatch = tmp_path / "mismatch"
    with pytest.raises(ValueError, match="batch_source_mismatch"):
        bridge.prepare_batch_input(system, control, **kwargs, out=mismatch)
    assert not mismatch.exists()
    monkeypatch.setattr(source, "committed_source", real)
    monkeypatch.setattr(batch, "requests_for", lambda *args: ({}, False))
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="batch_request_missing"):
        bridge.prepare_batch_input(system, control, **kwargs, out=missing)
    assert not missing.exists()


async def test_unreadable_source_and_occupied_output_are_preserved(
    durable, source_world, tmp_path, monkeypatch,
):
    system, control, run_id, files, _repository, _commits, _state = durable
    controller_repository, controller, _, _ = source_world
    kwargs = dict(run_id=run_id, file_id=selected(files), controller=controller,
                  controller_repository=controller_repository)
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    with pytest.raises(FileExistsError):
        bridge.prepare_batch_input(system, control, **kwargs, out=occupied)
    assert list(occupied.iterdir()) == []

    def unreadable(*args):
        raise ValueError("review_git_failed: fixture")

    monkeypatch.setattr(source, "committed_source", unreadable)
    out = tmp_path / "unreadable"
    with pytest.raises(ValueError, match="batch_source_unreadable"):
        bridge.prepare_batch_input(system, control, **kwargs, out=out)
    assert not out.exists()


async def test_isolated_preparation_entry_uses_durable_membership_and_reports_binding_digest(
    durable, source_world, tmp_path,
):
    _system, control, run_id, files, _repository, _commits, state = durable
    controller_repository, controller, _, _ = source_world
    # End the creating host before the offline process opens durable read state.
    await control.shutdown()
    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "cli"
    process = subprocess.run(
        [sys.executable, "-I", "-B", str(root / "scripts/ops/change_review_batch_prepare.py"),
         "--state", str(state), "--run-id", str(run_id), "--file-id", selected(files),
         "--controller", controller, "--controller-repository", str(controller_repository),
         "--out", str(out)],
        cwd=tmp_path, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        stdin=subprocess.DEVNULL, capture_output=True, timeout=45,
    )
    assert (process.returncode, process.stderr) == (0, b""), process.stdout
    assert json.loads(process.stdout) == {
        "status": "prepared", "file_id": selected(files), "execution_authorized": False,
        "binding_sha256": hashlib.sha256((out / "binding.json").read_bytes()).hexdigest(),
    }
    assert source.checked(control.runs_status(source.OPERATOR, run_id)).status is RunStatus.PARKED


async def test_actual_collector_rejects_unusable_git_path_before_direct_or_bridge_output(
    source_world, tmp_path,
):
    repository, controller, before, after = source_world
    path = "odd\nname.py"
    commits = []
    for original in (before, after):
        blob = source.git(repository, "rev-parse", f"{original}:calc.py").decode().strip()
        # Fixture-only Git object construction; no invalid Windows file is made.
        source.git(repository, "-c", "core.protectNTFS=false", "update-index", "--add",
                   "--cacheinfo", f"100644,{blob},{path}")
        tree = source.git(repository, "write-tree").decode().strip()
        commits.append(source.git(repository, "commit-tree", tree, "-m", "alias fixture")
                       .decode().strip())
    # This is a real readable Git path and valid ordinary batch input. The
    # downstream collector's exact packet contract is the narrower boundary.
    files = batch.prepare_batch(repository, *commits, (path,))
    assert next(iter(files.values())).before_ref.paths == (path,)
    direct = tmp_path / "direct-invalid-path"
    with pytest.raises(collector.ReplyRefused) as refused:
        consumer.prepare(repository, controller, *commits, path, direct)
    assert refused.value.code == collector.PACKET
    assert not direct.exists()

    system, control = source.assemble(tmp_path / "newline-review.db")
    try:
        versions = await source.register(control)
        submission = source.checked(await control.runs_start(
            source.OPERATOR, proposal=batch.batch_graph(versions, files),
            inputs={f"change_{key}": value.model_dump(mode="json")
                    for key, value in files.items()},
            idempotency_key="newline-prepare-test",
        ))
        await source.wait_for(control, submission.run_id, allow_parked=True)
        bridge_out = tmp_path / "bridge-invalid-path"
        with pytest.raises(collector.ReplyRefused) as refused:
            bridge.prepare_batch_input(
                system, control, run_id=submission.run_id, file_id=next(iter(files)),
                controller=controller, controller_repository=repository, out=bridge_out,
            )
        assert refused.value.code == collector.PACKET
        assert not bridge_out.exists()
    finally:
        await control.shutdown()
