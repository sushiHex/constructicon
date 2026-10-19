"""Credential-free real-Git proof for exact candidate retrieval and reconstruction."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from scripts import m8_candidate_transfer as transfer

from constructicon.api import _maintenance_source as source
from constructicon.core.errors import ContractViolation
from constructicon.substrate.gates import maintenance as gate
from tests.substrate.test_maintenance_vectors import permitting_vectors

ROOT = Path(__file__).resolve().parents[1]
MESSAGE = b"constructicon plan-manifest regression vectors\n"
IDENTITY = b"constructicon <authority@constructicon.invalid> 1767225600 +0000"


def inventory(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def verified_receipt(artifact, pins):
    return {"schema_version": 1, "meaning": "exact-candidate-reconstructed-and-exam-passed",
            "historical_projection_matched": True, "tree_reconstructed": True,
            "reexam_passed": True, "candidate_commit": pins.candidate, "base_commit": pins.base,
            "input_sha256": pins.input_sha256, "render_sha256": pins.render_sha256,
            "artifact_sha256": hashlib.sha256(artifact).hexdigest()}


def read_status(destination):
    status = json.loads((destination / "status.json").read_bytes())
    assert set(status) == {"schema_version", "complete", "launch_requested", "returncode",
                           "stdout_eof", "stderr_eof", "stdout_bytes", "stderr_bytes",
                           "overflow", "timed_out", "capture_io_failed"}
    assert type(status["schema_version"]) is int and status["schema_version"] == 1
    assert status["returncode"] is None or type(status["returncode"]) is int
    for name in ("complete", "launch_requested", "stdout_eof", "stderr_eof", "overflow",
                 "timed_out", "capture_io_failed"):
        assert type(status[name]) is bool
    for name, bound in (("stdout_bytes", transfer.MAX_ARTIFACT + 1), ("stderr_bytes", 1025)):
        assert type(status[name]) is int and 0 <= status[name] <= bound
    return status


async def make_commit(repo, base, vector, *, path=transfer.VECTOR_PATH, mode="100644",
                      extra=False, parents=None, message=MESSAGE,
                      identity=IDENTITY):
    git = transfer.git_process()
    await git.run("read-tree", base, cwd=repo)
    blob = (await git.run("hash-object", "-w", "--stdin", cwd=repo,
                          stdin=vector)).strip().decode()
    await git.run("update-index", "--add", "--cacheinfo", mode, blob, path, cwd=repo)
    if extra:
        await git.run("update-index", "--add", "--cacheinfo", "100644", blob,
                      "unexpected.txt", cwd=repo)
    tree = (await git.run("write-tree", cwd=repo)).strip()
    parents = [base] if parents is None else parents
    raw = (b"tree " + tree + b"\n"
           + b"".join(b"parent " + value.encode() + b"\n" for value in parents)
           + b"author " + identity + b"\ncommitter " + identity + b"\n\n" + message)
    candidate = (await git.run("hash-object", "-t", "commit", "-w", "--stdin", cwd=repo,
                               stdin=raw)).strip().decode()
    return candidate, raw


def stored_result(pins):
    return {"schema_version": 1, "meaning": "historical-application-acceptance",
        "authorization_digest": "sha256:" + "a" * 64, "result": {
            "run_id": pins.run_id,
            "candidate": {"repository": "private-locator", "commit": pins.candidate,
                          "diff_against": pins.base},
            "evaluation": {"subject": None, "checks": [], "attestation_id": None},
            "input_sha256": pins.input_sha256, "render_sha256": pins.render_sha256}}


@pytest.fixture
async def world(tmp_path, monkeypatch):
    # Only the platform-bound service custody predicate is substituted. Source
    # pin/config/metadata inspection and every Git operation remain production.
    def custody(path):
        assert path.is_absolute() and path.resolve() == path and path.is_dir()
        assert path.is_relative_to(tmp_path)

    monkeypatch.setattr(source, "private_root", custody)
    root = tmp_path / "source"
    root.mkdir()
    for name in ("authority.git", "authority-workspaces", "workspace-acquisitions",
                 "gate-acquisitions"):
        (root / name).mkdir()
    repo = root / "authority.git"
    git = transfer.git_process()
    await git.run("init", "--quiet", "--bare", "--template=", ".", cwd=repo)
    (repo / "hooks").mkdir()
    (repo / "config").write_bytes(source.CONFIG)
    stream = (b"commit refs/heads/maintenance\n"
              b"committer test <test@example.invalid> 1767225600 +0000\ndata 1\nx\n")
    for name in source.SOURCE_FILES:
        blob = await git.run("show", "HEAD:" + name, cwd=ROOT)
        stream += f"M 100644 inline {name}\ndata {len(blob)}\n".encode() + blob + b"\n"
    stream += b"\ndone\n"
    await git.run("fast-import", "--quiet", cwd=repo, stdin=stream)
    base = (await git.run("rev-parse", "refs/heads/maintenance", cwd=repo)).strip().decode()
    (root / "source-pin.json").write_bytes(source.SourcePin(
        bundle_sha256="a" * 64, base_commit=base, target_ref="refs/heads/maintenance",
        config_sha256=hashlib.sha256(source.CONFIG).hexdigest(),
        sources=source.SOURCE_HASHES).model_dump_json().encode())
    vector = permitting_vectors()
    target = await git.run("show", f"{base}:{transfer.TARGET_PATH}", cwd=repo)
    report = gate.run_vectors(vector, target, source.SOURCE_HASHES[transfer.TARGET_PATH])
    assert report.passed
    candidate, raw = await make_commit(repo, base, vector)
    pins = transfer.Pins(candidate, base, "run-" + "a" * 32,
                         report.input_sha256, report.render_sha256)
    (root / "maintenance-result.json").write_bytes(transfer.canonical(stored_result(pins)))
    await source.inspect_source(root)
    return root, repo, pins, raw, vector


async def test_real_export_and_independent_reconstruction_leave_source_unchanged(world, tmp_path):
    root, repo, pins, raw, vector = world
    before = inventory(root)
    artifact = await transfer.export_candidate(root, pins)
    assert transfer.parse_artifact(artifact, pins) == (raw, vector)
    assert len(artifact) <= transfer.MAX_ARTIFACT
    assert b"private-locator" not in artifact
    quarantine = tmp_path / "receiver"
    result = await transfer.verify_candidate(artifact, repo, quarantine, pins)
    assert result == verified_receipt(artifact, pins)
    assert json.loads((quarantine / "VERIFIED.json").read_bytes()) == result
    assert await transfer.git_process().run("for-each-ref", cwd=quarantine) == b""
    assert await transfer.git_process().run("cat-file", "commit", pins.candidate,
                                          cwd=quarantine) == raw
    assert inventory(root) == before
    with pytest.raises(transfer.TransferRefused, match="occupied"):
        await transfer.verify_candidate(artifact, repo, quarantine, pins)
    assert inventory(root) == before


@pytest.mark.parametrize("change", ["candidate", "base", "input", "historical"])
async def test_export_refuses_independent_pins_and_historical_mismatch(world, change):
    root, _repo, pins, _raw, _vector = world
    if change == "historical":
        record = stored_result(pins)
        record["result"]["render_sha256"] = "b" * 64
        (root / "maintenance-result.json").write_bytes(transfer.canonical(record))
    else:
        field = {"candidate": "candidate", "base": "base", "input": "input_sha256"}[change]
        pins = replace(pins, **{field: "b" * (40 if change != "input" else 64)})
    before = inventory(root)
    with pytest.raises((transfer.TransferRefused, ContractViolation)):
        await transfer.export_candidate(root, pins)
    assert inventory(root) == before


@pytest.mark.parametrize("change", ["extra", "path", "mode", "parents"])
async def test_export_rejects_whole_defect_class(world, change):
    root, repo, pins, _raw, vector = world
    kwargs = {"extra": {"extra": True}, "path": {"path": "tests/vectors/other.json"},
              "mode": {"mode": "100755"}, "parents": {"parents": [pins.base, pins.base]}}
    candidate, _ = await make_commit(repo, pins.base, vector, **kwargs[change])
    pins = replace(pins, candidate=candidate)
    (root / "maintenance-result.json").write_bytes(transfer.canonical(stored_result(pins)))
    before = inventory(root)
    with pytest.raises(transfer.TransferRefused):
        await transfer.export_candidate(root, pins)
    assert inventory(root) == before


async def test_other_bounded_commit_metadata_is_preserved_privately(world, tmp_path):
    root, repo, pins, _raw, vector = world
    candidate, raw = await make_commit(
        repo, pins.base, vector, message=b"another precommitted message\n",
        identity=b"other author <other@example.invalid> 1767225601 +0000")
    pins = replace(pins, candidate=candidate)
    (root / "maintenance-result.json").write_bytes(transfer.canonical(stored_result(pins)))
    artifact = await transfer.export_candidate(root, pins)
    assert transfer.parse_artifact(artifact, pins)[0] == raw
    result = await transfer.verify_candidate(artifact, repo, tmp_path / "other-metadata", pins)
    assert result == verified_receipt(artifact, pins)


@pytest.mark.parametrize("change", ["extra-header", "control", "message-bound", "commit-bound"])
async def test_commit_metadata_grammar_is_bounded_even_for_matching_oid(world, change):
    _root, _repo, pins, raw, _vector = world
    if change == "extra-header":
        raw = raw.replace(b"\n\n", b"\nencoding UTF-8\n\n", 1)
    elif change == "control":
        raw += b"\x00"
    elif change == "message-bound":
        raw = raw.partition(b"\n\n")[0] + b"\n\n" + b"x" * 2049
    else:
        raw += b"x" * transfer.MAX_COMMIT
    pins = replace(pins, candidate=transfer.object_oid("commit", raw))
    with pytest.raises(transfer.TransferRefused):
        transfer.commit_tree(raw, pins)


@pytest.mark.parametrize("change", ["candidate", "base", "path", "mode", "historical", "blob",
                                    "commit", "extra", "duplicate", "partial", "oversize",
                                    "hex", "schema-bool", "noncanonical"])
async def test_closed_artifact_refuses_before_receiving_mutation(world, tmp_path, change):
    _root, repo, pins, raw, vector = world
    artifact = transfer.artifact_bytes(raw, vector, pins)
    value = json.loads(artifact)
    if change == "partial":
        artifact = artifact[:-2]
    elif change == "oversize":
        artifact = b" " * (transfer.MAX_ARTIFACT + 1)
    elif change == "duplicate":
        artifact = artifact.replace(b'"mode":"100644"', b'"mode":"100644","mode":"100644"')
    elif change == "noncanonical":
        artifact += b"\n"
    else:
        if change in {"candidate", "base"}:
            value[change + "_commit"] = "b" * 40
        elif change in {"path", "mode"}:
            value[change] = "unexpected"
        elif change == "historical":
            value["historical"]["render_sha256"] = "b" * 64
        elif change == "blob":
            value["vector_hex"] = b"{}".hex()
        elif change == "commit":
            value["commit_hex"] = (raw + b"x").hex()
        elif change == "extra":
            value["extra"] = "private-text"
        elif change == "hex":
            value["vector_hex"] = "AA"
        elif change == "schema-bool":
            value["schema_version"] = True
        artifact = transfer.canonical(value)
    quarantine = tmp_path / "refused"
    with pytest.raises(transfer.TransferRefused):
        await transfer.verify_candidate(artifact, repo, quarantine, pins)
    assert not quarantine.exists()


async def test_receiver_independently_rejects_extra_tree_even_with_valid_objects(world, tmp_path):
    _root, repo, pins, _raw, vector = world
    candidate, raw = await make_commit(repo, pins.base, vector, extra=True)
    pins = replace(pins, candidate=candidate)
    artifact = transfer.artifact_bytes(raw, vector, pins)
    quarantine = tmp_path / "refused-tree"
    with pytest.raises(transfer.TransferRefused, match="reconstructed-tree"):
        await transfer.verify_candidate(artifact, repo, quarantine, pins)
    assert not (quarantine / "VERIFIED.json").exists()


async def test_receiver_refuses_wrong_render_and_nonpassing_exam(world, tmp_path, monkeypatch):
    _root, repo, pins, raw, vector = world
    wrong_render = replace(pins, render_sha256="b" * 64)
    with pytest.raises(transfer.TransferRefused, match="trusted-exam"):
        await transfer.verify_candidate(transfer.artifact_bytes(raw, vector, wrong_render), repo,
                                        tmp_path / "wrong-render", wrong_render)
    original = gate.run_vectors

    def failed(*args):
        return replace(original(*args), passed=False)

    monkeypatch.setattr(gate, "run_vectors", failed)
    quarantine = tmp_path / "failed-exam"
    with pytest.raises(transfer.TransferRefused, match="trusted-exam"):
        await transfer.verify_candidate(transfer.artifact_bytes(raw, vector, pins), repo,
                                        quarantine, pins)
    assert not (quarantine / "VERIFIED.json").exists()


@pytest.mark.parametrize("field", ["target_sha256", "gate_sha256"])
async def test_receiver_requires_independently_pinned_trusted_sources(world, tmp_path, field):
    _root, repo, pins, raw, vector = world
    pins = replace(pins, **{field: "b" * 64})
    quarantine = tmp_path / field
    with pytest.raises(transfer.TransferRefused, match="trusted-source-pins"):
        await transfer.verify_candidate(transfer.artifact_bytes(raw, vector, pins), repo,
                                        quarantine, pins)
    assert not (quarantine / "VERIFIED.json").exists()


async def test_export_rechecks_source_after_git_awaits(world, monkeypatch):
    root, _repo, pins, _raw, _vector = world
    original = transfer.GitProcess.run

    async def change(self, *args, **kwargs):
        result = await original(self, *args, **kwargs)
        if args[:2] == ("cat-file", "blob"):
            path = root / "source-pin.json"
            value = json.loads(path.read_bytes())
            value["bundle_sha256"] = "b" * 64
            path.write_bytes(transfer.canonical(value))
        return result

    monkeypatch.setattr(transfer.GitProcess, "run", change)
    with pytest.raises(transfer.TransferRefused, match="source-changed"):
        await transfer.export_candidate(root, pins)


async def test_vector_crlf_whitespace_roundtrips_as_exact_data(world, tmp_path):
    root, repo, pins, _raw, vector = world
    vector += b"\r\n"
    candidate, raw = await make_commit(repo, pins.base, vector)
    pins = replace(pins, candidate=candidate, input_sha256=hashlib.sha256(vector).hexdigest())
    (root / "maintenance-result.json").write_bytes(transfer.canonical(stored_result(pins)))
    artifact = await transfer.export_candidate(root, pins)
    assert transfer.parse_artifact(artifact, pins) == (raw, vector)
    quarantine = tmp_path / "crlf"
    result = await transfer.verify_candidate(artifact, repo, quarantine, pins)
    assert result == verified_receipt(artifact, pins)
    recovered = await transfer.git_process().run("cat-file", "blob",
                                                f"{candidate}:{transfer.VECTOR_PATH}",
                                                cwd=quarantine)
    assert recovered == vector and recovered.endswith(b"\r\n")


async def test_publication_failure_retains_only_incomplete_marker(world, tmp_path, monkeypatch):
    _root, repo, pins, raw, vector = world
    quarantine = tmp_path / "partial-publication"

    def crash(path, _raw):
        path.write_bytes(b"{")
        raise OSError("synthetic publication failure")

    monkeypatch.setattr(transfer, "write_once", crash)
    with pytest.raises(OSError):
        await transfer.verify_candidate(transfer.artifact_bytes(raw, vector, pins), repo,
                                        quarantine, pins)
    with pytest.raises(json.JSONDecodeError):
        json.loads((quarantine / "VERIFIED.json").read_bytes())
    with pytest.raises(transfer.TransferRefused, match="occupied"):
        await transfer.verify_candidate(transfer.artifact_bytes(raw, vector, pins), repo,
                                        quarantine, pins)


async def test_cancelled_git_step_does_not_publish_success(world, tmp_path, monkeypatch):
    _root, repo, pins, raw, vector = world
    quarantine = tmp_path / "cancelled"
    original = transfer.GitProcess.run

    async def cancel(self, *args, **kwargs):
        if args[:1] == ("write-tree",):
            raise asyncio.CancelledError
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(transfer.GitProcess, "run", cancel)
    with pytest.raises(asyncio.CancelledError):
        await transfer.verify_candidate(transfer.artifact_bytes(raw, vector, pins), repo,
                                        quarantine, pins)
    assert not (quarantine / "VERIFIED.json").exists()


def test_cli_has_only_fixed_q13_pins_and_redacts_bad_arguments(capsys):
    assert transfer.main(["export", "--root", "private-locator", "--candidate", "secret"]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "candidate-transfer-refused\n"


@pytest.fixture
def capture_artifact():
    vector = b'{"version":1,"cases":[]}'
    base = "a" * 40
    raw = (b"tree " + b"b" * 40 + b"\nparent " + base.encode()
           + b"\nauthor " + IDENTITY + b"\ncommitter " + IDENTITY
           + b"\n\n" + MESSAGE)
    pins = transfer.Pins(transfer.object_oid("commit", raw), base, "run-" + "c" * 32,
                         hashlib.sha256(vector).hexdigest(), "d" * 64)
    return transfer.artifact_bytes(raw, vector, pins), pins


async def test_bounded_capture_accepts_positive_exit_eof_and_closed_artifact(
    capture_artifact, tmp_path,
):
    artifact, pins = capture_artifact
    destination = tmp_path / "capture"
    argv = (sys.executable, "-I", "-c", "import sys; sys.stdout.buffer.write("
            + repr(artifact) + "); assert not sys.stdin.buffer.read()")
    result = await transfer.capture_transfer(argv, destination, pins)
    status = read_status(destination)
    assert status["complete"] is True and status["returncode"] == 0
    assert status["stdout_eof"] is status["stderr_eof"] is True
    assert (destination / "artifact.json").read_bytes() == artifact
    assert result == {"schema_version": 1, "meaning": "bounded-transfer-received",
                      "historical_projection_matched": True, "artifact_bytes": len(artifact),
                      "artifact_sha256": hashlib.sha256(artifact).hexdigest()}
    assert status["stdout_bytes"] == len(artifact) and status["stderr_bytes"] == 0
    with pytest.raises(transfer.TransferRefused, match="capture-destination"):
        await transfer.capture_transfer(argv, destination, pins)


@pytest.mark.parametrize("kind", ["stdout-overflow", "stderr-overflow", "stderr", "nonzero",
                                  "partial", "timeout"])
async def test_capture_refusal_preserves_bounded_partial_evidence(
    capture_artifact, tmp_path, kind,
):
    artifact, pins = capture_artifact
    source = "import sys,time; "
    if kind == "stdout-overflow":
        source += f"sys.stdout.buffer.write(b'x'*{transfer.MAX_ARTIFACT + 4096})"
    elif kind == "stderr-overflow":
        source += "sys.stderr.buffer.write(b'x'*4096)"
    elif kind == "stderr":
        source += "sys.stdout.buffer.write(" + repr(artifact) + "); sys.stderr.write('private')"
    elif kind == "nonzero":
        source += "sys.stdout.buffer.write(" + repr(artifact) + "); sys.exit(4)"
    elif kind == "partial":
        source += "sys.stdout.buffer.write(b'{')"
    else:
        source += "sys.stdout.buffer.write(b'{'); sys.stdout.flush(); time.sleep(30)"
    destination = tmp_path / kind
    argv = (sys.executable, "-I", "-c", source)
    with pytest.raises(transfer.TransferRefused):
        await transfer.capture_transfer(argv, destination, pins,
                                        timeout_s=0.3 if kind == "timeout" else 10)
    status = read_status(destination)
    assert status["complete"] is False and status["launch_requested"] is True
    assert type(status["returncode"]) is int
    assert status["stdout_bytes"] <= transfer.MAX_ARTIFACT + 1
    assert status["stderr_bytes"] <= 1025
    assert not (destination / "artifact.json").exists()
    if kind == "timeout":
        assert status["timed_out"] is True
    if kind.endswith("overflow"):
        assert status["overflow"] is True


async def test_capture_cancellation_joins_child_and_never_completes(capture_artifact, tmp_path):
    _artifact, pins = capture_artifact
    destination = tmp_path / "cancel-capture"
    argv = (sys.executable, "-I", "-c",
            "import sys,time; sys.stdout.write('{'); sys.stdout.flush(); time.sleep(30)")
    task = asyncio.create_task(transfer.capture_transfer(argv, destination, pins))
    async with asyncio.timeout(10):
        while not (destination / "stdout.private").exists():
            await asyncio.sleep(0.01)
        while (destination / "stdout.private").stat().st_size == 0:
            await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    status = read_status(destination)
    assert status["complete"] is False and type(status["returncode"]) is int
    assert not (destination / "artifact.json").exists()


async def test_capture_artifact_write_failure_cannot_publish_complete(
    capture_artifact, tmp_path, monkeypatch,
):
    artifact, pins = capture_artifact
    destination = tmp_path / "partial-artifact"
    original = transfer.write_once

    def fail(path, raw):
        if path.name == "artifact.json":
            path.write_bytes(b"{")
            raise OSError("synthetic artifact write failure")
        return original(path, raw)

    monkeypatch.setattr(transfer, "write_once", fail)
    code = "import sys;sys.stdout.buffer.write(" + repr(artifact) + ")"
    with pytest.raises(OSError):
        await transfer.capture_transfer(
            (sys.executable, "-I", "-c", code), destination, pins)
    status = read_status(destination)
    assert status["complete"] is False
    with pytest.raises(transfer.TransferRefused):
        transfer.parse_artifact((destination / "artifact.json").read_bytes(), pins)


async def test_pending_spawn_cancellation_joins_a_child_with_full_pipes(
    capture_artifact, tmp_path, monkeypatch,
):
    _artifact, pins = capture_artifact
    destination = tmp_path / "cancel-full-pipe"
    original = asyncio.create_subprocess_exec
    paused = asyncio.Event()
    release = asyncio.Event()
    child = None

    async def delayed(*args, **kwargs):
        nonlocal child
        child = await original(*args, **kwargs)
        # This binds the transport's actual pause condition, unlike sleeping and
        # hoping that the one-byte cancellation fixture filled a pipe.
        async with asyncio.timeout(10):
            while not child.stdout._paused:
                await asyncio.sleep(0.01)
        paused.set()
        await release.wait()
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
    argv = (sys.executable, "-I", "-c",
            "import sys,time;sys.stdout.buffer.write(b'x'*1048576);"
            "sys.stdout.flush();time.sleep(30)")
    task = asyncio.create_task(transfer.capture_transfer(argv, destination, pins))
    await asyncio.wait_for(paused.wait(), 10)
    task.cancel()
    release.set()
    done, _pending = await asyncio.wait({task}, timeout=5)
    joined = task in done
    if not joined:
        # Ensure a failing regression can still tear down its actual subprocess.
        await child.stdout.read()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert joined, "pending-spawn cleanup must drain a full pipe before waiting"
    with pytest.raises(asyncio.CancelledError):
        await task
    status = read_status(destination)
    assert status["complete"] is False and type(status["returncode"]) is int
    assert status["stdout_bytes"] <= transfer.MAX_ARTIFACT + 1
    assert not (destination / "artifact.json").exists()


async def test_capture_sink_failure_still_drains_and_joins_without_publication(
    capture_artifact, tmp_path, monkeypatch,
):
    artifact, pins = capture_artifact
    original = Path.open

    class FailingSink:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def write(self, _raw):
            raise OSError("synthetic capture sink failure")

        def flush(self):
            self.handle.flush()

        def fileno(self):
            return self.handle.fileno()

    def opened(path, *args, **kwargs):
        handle = original(path, *args, **kwargs)
        return FailingSink(handle) if path.name == "stdout.private" else handle

    monkeypatch.setattr(Path, "open", opened)
    destination = tmp_path / "sink-failure"
    code = ("import sys,time;sys.stdout.buffer.write(" + repr(artifact)
            + ");sys.stdout.flush();time.sleep(30)")
    with pytest.raises(transfer.TransferRefused, match="capture-incomplete"):
        await transfer.capture_transfer((sys.executable, "-I", "-c", code),
                                        destination, pins, timeout_s=3)
    status = read_status(destination)
    assert status["complete"] is False and status["capture_io_failed"] is True
    assert type(status["returncode"]) is int and status["stdout_eof"] is True
    assert status["timed_out"] is False and not (destination / "artifact.json").exists()


@pytest.mark.parametrize("kind", ["commit", "vector"])
async def test_host_output_bound_binds_before_materialization(world, kind):
    root, repo, pins, _raw, vector = world
    if kind == "commit":
        kwargs = {"message": b"x" * (transfer.MAX_COMMIT + 1)}
    else:
        vector = b"x" * (transfer.MAX_VECTOR + 1)
        pins = replace(pins, input_sha256=hashlib.sha256(vector).hexdigest())
        kwargs = {}
    candidate, _raw = await make_commit(repo, pins.base, vector, **kwargs)
    pins = replace(pins, candidate=candidate)
    (root / "maintenance-result.json").write_bytes(transfer.canonical(stored_result(pins)))
    with pytest.raises(ContractViolation, match="output exceeds"):
        await transfer.export_candidate(root, pins)
