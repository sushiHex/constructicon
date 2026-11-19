"""The batch entry composes durable ordinary reviews without executing source."""

from __future__ import annotations

import asyncio
import copy
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from examples import change_review_batch as batch
from examples.change_review import (
    CHANNEL_ID,
    OPERATOR,
    SOURCE_BYTES,
    assemble,
    checked,
    git,
    register,
    wait_for,
)

from constructicon.core.address import RunId
from constructicon.core.control import DetailChunk, DetailRef, command_id_for
from constructicon.core.graph import Graph
from constructicon.core.identity import canonical_json, digest
from constructicon.core.run import RunStatus
from constructicon.sdk.std import ADVISOR_COMPONENT

ROOT = Path(__file__).parents[2]


def entry(
    state: Path, *arguments: str, crash_at: str | None = None, wait_seconds: float | None = None,
) -> subprocess.CompletedProcess:
    command = [sys.executable, "-m", "examples.change_review_batch"]
    if crash_at is not None or wait_seconds is not None:
        # Replace only the existing fault probe or the app's observation deadline.
        code = """
import os
import examples.change_review as single
import examples.change_review_batch as batch
if os.environ['BATCH_REVIEW_WAIT_SECONDS']:
    batch.WAIT_SECONDS = float(os.environ['BATCH_REVIEW_WAIT_SECONDS'])
if os.environ['BATCH_REVIEW_CRASH_AT']:
    original = single.ControlPlane
    def injected(**kwargs):
        def probe(name):
            if name == os.environ['BATCH_REVIEW_CRASH_AT']:
                os._exit(19)
        return original(**kwargs, command_ttl_s=0.01, fault_probe=probe)
    single.ControlPlane = injected
raise SystemExit(batch.main())
"""
        command = [sys.executable, "-c", code]
    return subprocess.run(
        [*command, "--state", str(state), *arguments],
        cwd=ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8",
             "BATCH_REVIEW_CRASH_AT": crash_at or "",
             "BATCH_REVIEW_WAIT_SECONDS": "" if wait_seconds is None else str(wait_seconds)},
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
        timeout=90, check=False,
    )


def output(process: subprocess.CompletedProcess, *, returncode: int = 0) -> dict:
    assert process.returncode == returncode, (process.returncode, process.stdout, process.stderr)
    response = json.loads(process.stdout)
    assert len(process.stdout.encode("utf-8")) <= batch.MAX_RESPONSE_BYTES
    assert response["schema_version"] == 1
    assert response["run_id"] == response["result"]["run_id"]
    return response


def source_commits(
    root: Path, before: dict[str, bytes], after: dict[str, bytes],
) -> tuple[Path, str, str]:
    repository = root / "source"
    repository.mkdir()
    git(repository, "init", "--quiet")
    commits = []
    for files in (before, after):
        for name, raw in files.items():
            path = repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        git(repository, "add", "--", *files)
        git(repository, "-c", "user.name=Example", "-c", "user.email=example@example.invalid",
            "commit", "--quiet", "--allow-empty", "-m", "fixture")
        commits.append(git(repository, "rev-parse", "HEAD").decode("ascii").strip())
    return repository, commits[0], commits[1]


def submit_arguments(
    repository: Path, before: str, after: str, paths: tuple[str, ...], *, key: str = "batch-1",
) -> tuple[str, ...]:
    return ("submit", "--repository", str(repository), "--before-commit", before,
            "--after-commit", after, *(arg for path in paths for arg in ("--path", path)),
            "--key", key)


def by_path(response: dict) -> dict[str, dict]:
    return {file["path"]: file for file in response["files"]}


def assert_public_result(state: Path, response: dict) -> None:
    _, control = assemble(state / "review.db")
    retained = checked(control.runs_result(OPERATOR, RunId(response["run_id"])))
    # Metering belongs to the root run and is retained exactly once, unchanged.
    assert response["result"] == retained.model_dump(mode="json")
    assert response["result"]["result_schema_version"] == 3
    assert "metering" not in response
    for file in response["files"]:
        assert file["usage"] == {
            "coverage": "unknown", "reason": "run metering is not attributed per file",
        }


def test_fresh_cli_batch_keeps_each_review_separate_and_replays_the_whole_run(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "source-was-executed"
    attack = (f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
              "def new_alpha(): return 2\n").encode()
    repository, before, after = source_commits(
        tmp_path,
        {"alpha.py": b"def old_alpha(): return 1\n", "nested/beta.py": b"def beta(): pass\n"},
        {"alpha.py": attack, "nested/beta.py": b"def broken(:\n"},
    )
    state = tmp_path / "state"
    submitted = output(entry(state, *submit_arguments(
        repository, before, after, ("nested/beta.py", "alpha.py"),
    )))
    assert submitted["result"]["status"] == "parked"
    assert submitted["mapping_status"] == "complete" and submitted["partial"] is False
    assert [file["path"] for file in submitted["files"]] == ["alpha.py", "nested/beta.py"]
    files = by_path(submitted)
    alpha, beta = files["alpha.py"], files["nested/beta.py"]
    assert alpha["file_id"] != beta["file_id"]
    assert alpha["request"]["message_id"] != beta["request"]["message_id"]
    assert all(file["status"] == "parked" for file in files.values())
    assert alpha["analysis"]["symbols"] == {
        "added": ["new_alpha"], "removed": ["old_alpha"], "changed": [],
    }
    assert beta["analysis"]["comparison_available"] is False
    assert beta["analysis"]["syntax_errors"] == {"after": "line 1: SyntaxError"}
    assert beta["analysis"]["symbols"] == beta["analysis"]["counts"] == {}
    assert all(file["analysis"]["tests_executed"] is False for file in files.values())
    assert not marker.exists()
    assert_public_result(state, submitted)

    replay = output(entry(state, *submit_arguments(
        repository / ".." / "source", before, after, ("alpha.py", "nested/beta.py"),
    )))
    assert replay["run_id"] == submitted["run_id"]
    assert replay["submission"]["command"]["replayed"] is True
    assert replay["result"] == submitted["result"]
    system, control = assemble(state / "review.db")
    assert checked(control.runs_list(OPERATOR)).page.count == 1
    manifest = system.manifest_for_run(RunId(submitted["run_id"]))
    assert len(manifest.source_graph.nodes) == 2
    assert all(isinstance(node.body, Graph) for node in manifest.source_graph.nodes)
    assert {item.component for item in manifest.resolved_components} == {
        "example/prepare-python-review", ADVISOR_COMPONENT,
    }
    assert len(manifest.resolved_components) == 4
    assert system.describe().components == ()
    inputs = system.inputs_for_run(RunId(submitted["run_id"]))
    assert len(inputs) == 2 and "Path(" not in json.dumps(inputs)
    assert {change["after_ref"]["commit"] for change in inputs.values()} == {after}
    assert {change["after_ref"]["repository"] for change in inputs.values()} == {
        str(repository.resolve()),
    }
    for file in files.values():
        request = system._journal.channel_message(
            channel_id=CHANNEL_ID, message_id=file["request"]["message_id"],
        )
        assert request is not None
        assert request.envelope.run_id == submitted["run_id"]
        assert request.envelope.path.scope.segments == (
            batch.ROOT_NAME, file["file_id"], "review",
        )
        assert request.envelope.payload["analysis"] == inputs[f"change_{file['file_id']}"]
        assert request.recipient_actor_id == OPERATOR.actor_id

    conflict = entry(state, *submit_arguments(repository, before, before, ("alpha.py",)))
    assert conflict.returncode == 1
    assert "control.idempotency.conflict" in conflict.stderr
    run_id = submitted["run_id"]
    missing = entry(state, "reply", "--run-id", run_id, "--file-id", "file_" + "0" * 64,
                    "--advice", "Do not route this.", "--key", "bad-membership")
    assert missing.returncode == 1
    assert "batch_file" in json.loads(missing.stderr)["error"]
    observed = output(entry(state, "status", "--run-id", run_id))
    assert observed["result"] == submitted["result"]
    assert [file["reply"] for file in observed["files"]] == [None, None]

    reply_args = ("reply", "--run-id", run_id, "--file-id", alpha["file_id"],
                  "--advice", "Alpha needs a regression test.", "--key", "alpha-advice")
    answered = output(entry(state, *reply_args))
    answer_files = by_path(answered)
    assert answered["result"]["status"] == "parked"
    assert answer_files["alpha.py"]["status"] == "succeeded"
    assert answer_files["alpha.py"]["advice"]["advice"] == "Alpha needs a regression test."
    assert answer_files["alpha.py"]["advice"]["actor_id"] == OPERATOR.actor_id
    assert answered["reply"]["request_id"] == alpha["request"]["message_id"]
    assert answer_files["nested/beta.py"]["status"] == "parked"
    assert answer_files["nested/beta.py"]["advice"] is None
    assert answer_files["nested/beta.py"]["request"]["message_id"] == beta["request"]["message_id"]
    assert answer_files["nested/beta.py"]["request"]["acknowledged"] is False
    replay_reply = output(entry(state, *reply_args))
    assert replay_reply["reply"]["command"]["replayed"] is True
    assert replay_reply["result"] == answered["result"]
    changed_reply = entry(state, *("Different advice." if arg == "Alpha needs a regression test."
                                  else arg for arg in reply_args))
    assert changed_reply.returncode == 1
    assert "control.idempotency.conflict" in changed_reply.stderr
    crosswire = entry(state, *(beta["file_id"] if arg == alpha["file_id"] else arg
                              for arg in reply_args))
    assert crosswire.returncode == 1 and "control.idempotency.conflict" in crosswire.stderr

    finished = output(entry(state, "reply", "--run-id", run_id, "--file-id", beta["file_id"],
                            "--advice", "Fix beta syntax first.", "--key", "beta-advice"))
    assert finished["result"]["status"] == "succeeded"
    assert all(file["status"] == "succeeded" for file in finished["files"])
    assert by_path(finished)["nested/beta.py"]["advice"]["advice"] == "Fix beta syntax first."
    assert by_path(finished)["nested/beta.py"]["analysis"] == beta["analysis"]
    assert_public_result(state, finished)
    assert output(entry(state, "status", "--run-id", run_id))["result"] == finished["result"]
    assert not marker.exists()
    assert checked(control.runs_list(OPERATOR)).page.count == 1


@pytest.mark.parametrize(
    "seam", ["after_plan", "after_domain_mutation", "after_command_completion"],
)
def test_reply_process_death_has_durable_evidence_and_status_never_recovers(
    tmp_path: Path, seam: str,
) -> None:
    repository, before, after = source_commits(
        tmp_path, {"a.py": b"", "b.py": b""},
        {"a.py": b"def a(): pass\n", "b.py": b"def b(): pass\n"},
    )
    state = tmp_path / "state"
    submitted = output(entry(state, *submit_arguments(repository, before, after, ("a.py", "b.py"))))
    run_id = submitted["run_id"]
    first = by_path(submitted)["a.py"]
    arguments = ("reply", "--run-id", run_id, "--file-id", first["file_id"],
                 "--advice", "Retain this exact reply.", "--key", "crashed-reply")
    died = entry(state, *arguments, crash_at=f"channels_reply.{seam}")
    assert died.returncode == 19, (died.returncode, died.stdout, died.stderr)
    system, control = assemble(state / "review.db")
    journal = system._journal
    command_id = command_id_for(OPERATOR.actor_id, "channels_reply", "crashed-reply")
    command = journal.command(command_id)
    assert command is not None and command.plan is not None
    assert command.state == ("committed" if seam == "after_command_completion" else "prepared")
    assert checked(control.commands_status(OPERATOR, command_id)).state == command.state
    stored_reply = journal.channel_reply_for(
        channel_id=CHANNEL_ID, request_id=first["request"]["message_id"],
    )
    if seam == "after_plan":
        assert stored_reply is None
        assert command.plan["plan"]["kind"] == "channel_reply"
    else:
        assert stored_reply is not None
        assert stored_reply.envelope.payload["advice"] == "Retain this exact reply."
        writer = journal.channel_message_writer(message_id=stored_reply.message_id)
        assert writer is not None and writer.command_id == command_id
    assert checked(control.runs_status(OPERATOR, RunId(run_id))).status is RunStatus.PARKED
    events_before = journal.events(RunId(run_id))
    observed = output(entry(state, "status", "--run-id", run_id))
    assert observed["result"]["status"] == "parked"
    assert by_path(observed)["a.py"]["status"] == (
        "parked" if seam == "after_plan" else "reply_recorded"
    )
    assert by_path(observed)["b.py"]["status"] == "parked"
    assert journal.events(RunId(run_id)) == events_before
    assert journal.command(command_id) == command

    resumed = output(entry(state, *arguments))
    assert by_path(resumed)["a.py"]["status"] == "succeeded"
    assert by_path(resumed)["b.py"]["status"] == "parked"
    assert resumed["reply"]["command"]["command_id"] == command_id
    assert resumed["reply"]["command"]["replayed"] is (seam == "after_command_completion")
    assert by_path(resumed)["a.py"]["advice"]["advice"] == "Retain this exact reply."
    if stored_reply is not None:
        assert resumed["reply"]["message_id"] == str(stored_reply.message_id)
    finished = output(entry(
        state, "reply", "--run-id", run_id, "--file-id", by_path(resumed)["b.py"]["file_id"],
        "--advice", "Second file only.", "--key", "second-reply",
    ))
    assert finished["result"]["status"] == "succeeded"
    assert_public_result(state, finished)
    assert checked(control.runs_list(OPERATOR)).page.count == 1
    events = journal.events(RunId(run_id))
    resolutions = system.manifest_for_run(RunId(run_id)).resolved_components
    inspect_paths = {item.scope for item in resolutions
                     if item.component == "example/prepare-python-review"}
    assert len(inspect_paths) == 2
    assert all(sum(event.kind == "NodeCompleted" and event.path is not None
                   and event.path.scope == path for event in events) == 1
               for path in inspect_paths)
    assert sum(event.kind == "RunSucceeded" for event in events) == 1
    assert len({row.message_id for row in [
        journal.channel_reply_for(channel_id=CHANNEL_ID, request_id=file["request"]["message_id"])
        for file in submitted["files"]
    ] if row is not None}) == 2


@pytest.mark.parametrize("bad", [b"x" * (SOURCE_BYTES + 1), b"\xff"], ids=["oversize", "utf8"])
def test_final_file_preflight_failure_creates_no_state(tmp_path: Path, bad: bytes) -> None:
    repository, before, after = source_commits(
        tmp_path, {"a.py": b"", "z.py": b""},
        {"a.py": b"def valid(): pass\n", "z.py": bad},
    )
    state = tmp_path / "state"
    refused = entry(state, *submit_arguments(repository, before, after, ("a.py", "z.py")))
    assert refused.returncode == 1
    assert json.loads(refused.stderr)["error"]
    assert not state.exists()


def test_file_count_bound_binds_and_file_identity_ignores_commits_and_batch_index(
    tmp_path: Path,
) -> None:
    assert batch.MAX_FILES == 16
    names = tuple(f"file_{index:02}.py" for index in range(batch.MAX_FILES + 1))
    repository, before, after = source_commits(
        tmp_path, dict.fromkeys(names, b""), dict.fromkeys(names, b"def added(): pass\n"),
    )
    allowed = batch.prepare_batch(repository, before, after, names[:batch.MAX_FILES])
    assert len(allowed) == batch.MAX_FILES
    one = batch.prepare_batch(repository / ".." / "source", before, before, (names[1],))
    assert set(one) <= set(allowed)
    assert next(iter(one.values())).after_ref.commit == before
    state = tmp_path / "state"
    refused = entry(state, *submit_arguments(repository, before, after, names))
    assert refused.returncode == 1
    assert "batch_file" in json.loads(refused.stderr)["error"]
    assert not state.exists()
    duplicate = entry(state, *submit_arguments(repository, before, after, (names[0], names[0])))
    assert duplicate.returncode == 1
    assert "batch_path_duplicate" in json.loads(duplicate.stderr)["error"]
    assert not state.exists()


def test_missing_and_occupied_state_paths_refuse_without_creating_authority(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    status = entry(missing, "status", "--run-id", "run-missing")
    assert status.returncode == 1 and "store_missing" in json.loads(status.stderr)["error"]
    assert not missing.exists()
    repository, before, after = source_commits(
        tmp_path, {"a.py": b"", "b.py": b""}, {"a.py": b"pass\n", "b.py": b"pass\n"},
    )
    occupied = tmp_path / "occupied"
    occupied.write_bytes(b"operator-owned")
    refused = entry(occupied, *submit_arguments(repository, before, after, ("a.py", "b.py")))
    assert refused.returncode == 1 and json.loads(refused.stderr)["error"]
    assert occupied.read_bytes() == b"operator-owned"


def test_cancelled_root_does_not_report_unfinished_file_as_waiting_for_advice(
    tmp_path: Path,
) -> None:
    repository, before, after = source_commits(
        tmp_path, {"a.py": b"", "b.py": b""},
        {"a.py": b"def a(): pass\n", "b.py": b"def b(): pass\n"},
    )
    state = tmp_path / "state"
    files = batch.prepare_batch(repository, before, after, ("a.py", "b.py"))
    state.mkdir()

    async def cancel() -> RunId:
        _, control = assemble(state / "review.db")
        try:
            versions = await register(control)
            submitted = checked(await control.runs_start(
                OPERATOR, proposal=batch.batch_graph(versions, files),
                inputs={f"change_{identity}": change.model_dump(mode="json")
                        for identity, change in files.items()},
                idempotency_key="cancel-before-first-attempt",
            ))
            # Cancel before the first park. The existing control contract treats
            # an already parked attempt as terminal for cancellation purposes.
            requested = checked(await control.runs_cancel(
                OPERATOR, run_id=submitted.run_id, idempotency_key="cancel-batch",
            ))
            assert requested.status == "cancel_requested"
            await wait_for(control, submitted.run_id, allow_parked=False)
            return submitted.run_id
        finally:
            await control.shutdown()

    run_id = asyncio.run(cancel())
    cancelled = output(entry(state, "status", "--run-id", run_id), returncode=1)
    assert cancelled["result"]["status"] == "cancelled"
    assert len(cancelled["files"]) == 2
    assert all(file["status"] in {"cancelled", "not_completed"} for file in cancelled["files"])
    assert all(file["advice"] is None for file in cancelled["files"])
    assert_public_result(state, cancelled)


def test_response_limit_binds_without_changing_the_retained_result() -> None:
    assert batch.MAX_RESPONSE_BYTES == 262_144
    retained = {
        "result_schema_version": 3, "run_id": "run-projection", "status": "parked",
        "outputs": {"a": "retained output"},
        "metering": {"coverage": "partial", "attempt_count": 7, "estimate": None},
    }
    response = {
        "schema_version": 1, "run_id": "run-projection", "partial": False,
        "limitations": [], "result": retained,
        "files": [{"analysis": "\N{SNOWMAN}" * (batch.MAX_RESPONSE_BYTES // 3),
                   "advice": "Advice that may be omitted."}],
    }
    retained_before = copy.deepcopy(retained)
    assert len(canonical_json(response).encode()) > batch.MAX_RESPONSE_BYTES
    bounded = batch.bounded_response(response)
    assert bounded["partial"] is True and bounded["limitations"]
    assert len(canonical_json(bounded).encode()) <= batch.MAX_RESPONSE_BYTES
    assert bounded["files"][0]["analysis"] is None
    assert "analysis" in bounded["files"][0]["omitted"]
    assert bounded["result"] == retained_before

    # Root V3 is an existing contract. A response cannot silently rewrite its
    # published outputs just to fit the app's independent projection limit.
    retained["outputs"] = {"wide": "x" * batch.MAX_RESPONSE_BYTES}
    wide_before = copy.deepcopy(retained)
    with pytest.raises(ValueError, match="batch_response_unbounded"):
        batch.bounded_response(response)
    assert retained == wide_before


def test_detail_limit_binds_at_the_public_chunk_reader() -> None:
    assert batch.MAX_DETAIL_BYTES == 4_194_304
    text = '{"data":"' + "x" * (batch.MAX_DETAIL_BYTES + 1) + '"}'
    reference = DetailRef(uri="detail:test", digest=digest("detail-test", 1, text))

    class Reader:
        calls = 0

        def details_read(self, actor, ref, *, cursor, max_bytes):
            assert actor == OPERATOR and ref == reference
            self.calls += 1
            offset = 0 if cursor is None else int(cursor)
            end = min(offset + max_bytes, len(text))
            return DetailChunk(
                uri=ref.uri, media_type=ref.media_type, digest=ref.digest,
                text=text[offset:end], offset=offset, total_bytes=len(text),
                next_cursor=str(end) if end < len(text) else None,
            )

    reader = Reader()
    with pytest.raises(ValueError, match="batch_detail_bytes_exceeded"):
        batch.read_detail(reader, reference)
    assert reader.calls == 1


def test_exact_response_byte_limit_survives_a_windows_text_stdout_wrapper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    response = {"result": {"status": "parked"}, "padding": ""}
    response["padding"] = "x" * (
        batch.MAX_RESPONSE_BYTES - 1 - len(canonical_json(response).encode("utf-8"))
    )
    expected = (canonical_json(response) + "\n").encode("utf-8")
    assert len(expected) == batch.MAX_RESPONSE_BYTES

    async def execute(args):
        assert args.command == "status" and args.run_id == "run-byte-boundary"
        return response

    raw = io.BytesIO()
    translated = io.TextIOWrapper(raw, encoding="utf-8", newline="\r\n")
    with monkeypatch.context() as patch:
        patch.setattr(batch, "execute", execute)
        patch.setattr(batch.sys, "stdout", translated)
        returned = batch.main([
            "--state", str(tmp_path / "state"), "status", "--run-id", "run-byte-boundary",
        ])
        translated.flush()
        actual = raw.getvalue()
    assert returned == 0
    assert actual == expected
    assert not (tmp_path / "state").exists()


def test_status_recovers_mapping_before_start_command_completion_without_starting_the_run(
    tmp_path: Path,
) -> None:
    repository, before, after = source_commits(
        tmp_path, {"a.py": b"", "b.py": b""},
        {"a.py": b"def a(): pass\n", "b.py": b"def b(): pass\n"},
    )
    state = tmp_path / "state"
    arguments = submit_arguments(repository, before, after, ("b.py", "a.py"), key="start-crash")
    died = entry(state, *arguments, crash_at="runs_start.after_domain_mutation")
    assert died.returncode == 19, (died.returncode, died.stdout, died.stderr)
    system, control = assemble(state / "review.db")
    command_id = command_id_for(OPERATOR.actor_id, "runs_start", "start-crash")
    command = system._journal.command(command_id)
    assert command is not None and command.state == "prepared" and command.plan is not None
    plan = command.plan["plan"]
    assert plan["kind"] == "run_creation"
    run_id = RunId(plan["run_id"])
    head = system._journal.run_head(run_id)
    assert head is not None
    assert head.record.status is RunStatus.PENDING
    assert head.record.origin.command_id == command_id
    assert head.record.owner_id is None
    events_before = system._journal.events(run_id)
    assert events_before == []
    inputs = system.inputs_for_run(run_id)
    assert len(inputs) == 2

    observed = output(entry(state, "status", "--run-id", run_id))
    assert observed["mapping_status"] == "complete"
    assert observed["partial"] is False
    assert observed["result"]["status"] == "pending"
    assert {file["path"] for file in observed["files"]} == {"a.py", "b.py"}
    assert all(file["status"] == "pending" for file in observed["files"])
    assert all(file["analysis_provenance"] == "sealed_preflight" for file in observed["files"])
    assert all(file["request"] is None and file["reply"] is None and file["advice"] is None
               for file in observed["files"])
    assert system._journal.command(command_id) == command
    assert system._journal.events(run_id) == events_before
    assert_public_result(state, observed)

    resumed = output(entry(state, *arguments))
    assert resumed["run_id"] == run_id
    assert resumed["submission"]["command"]["command_id"] == command_id
    assert resumed["result"]["status"] == "parked"
    assert len({file["request"]["message_id"] for file in resumed["files"]}) == 2
    assert all(file["status"] == "parked" for file in resumed["files"])
    assert system._journal.command(command_id).state == "committed"
    assert checked(control.runs_list(OPERATOR)).page.count == 1
    assert sum(event.kind == "RunStarted" for event in system._journal.events(run_id)) == 1
    assert_public_result(state, resumed)


def test_wait_deadline_preserves_the_durable_run_and_original_key_for_recovery(
    tmp_path: Path,
) -> None:
    repository, before, after = source_commits(
        tmp_path, {"a.py": b""}, {"a.py": b"def added(): pass\n"},
    )
    state = tmp_path / "state"
    arguments = submit_arguments(repository, before, after, ("a.py",), key="wait-deadline")
    # The real CLI and worker remain intact. Only the local observer's deadline
    # changes; expiry must preserve durable identity rather than invent failure.
    timed = output(entry(state, *arguments, wait_seconds=0), returncode=2)
    run_id = RunId(timed["run_id"])
    assert timed["wait_status"] == "timed_out" and timed["partial"] is True
    assert any("batch_wait_timeout" in limitation for limitation in timed["limitations"])
    assert timed["submission"]["run_id"] == run_id
    assert timed["result"]["status"] in {"pending", "running", "parked"}
    assert timed["files"][0]["analysis"]["symbols"]["added"] == ["added"]
    system, control = assemble(state / "review.db")
    command_id = command_id_for(OPERATOR.actor_id, "runs_start", "wait-deadline")
    command = system._journal.command(command_id)
    assert command is not None and command.state == "committed"
    assert command.idempotency_key == "wait-deadline"
    assert command.plan["plan"]["run_id"] == run_id
    assert timed["submission"]["command"]["command_id"] == command_id
    assert system._journal.cancel_requested(run_id) is False
    events_before = system._journal.events(run_id)

    observed = output(entry(state, "status", "--run-id", run_id))
    assert "wait_status" not in observed
    assert observed["run_id"] == run_id
    assert system._journal.command(command_id) == command
    assert system._journal.events(run_id) == events_before
    assert system._journal.cancel_requested(run_id) is False
    assert_public_result(state, observed)

    recovered = output(entry(state, *arguments))
    assert recovered["run_id"] == run_id
    assert recovered["submission"]["command"]["command_id"] == command_id
    assert recovered["submission"]["command"]["replayed"] is True
    assert recovered["wait_status"] == "settled"
    assert recovered["result"]["status"] == "parked"
    assert recovered["files"][0]["request"] is not None
    finished = output(entry(
        state, "reply", "--run-id", run_id, "--file-id", recovered["files"][0]["file_id"],
        "--advice", "Recovered advice.", "--key", "after-wait-deadline",
    ))
    assert finished["wait_status"] == "settled"
    assert finished["result"]["status"] == "succeeded"
    assert finished["files"][0]["advice"]["advice"] == "Recovered advice."
    assert checked(control.runs_list(OPERATOR)).page.count == 1
    assert_public_result(state, finished)
