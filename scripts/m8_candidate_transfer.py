"""One reviewed q13 transfer: immutable commit/data bytes, never candidate execution.

The public CLI has only the independently recorded q13 pins. Explicit Pins on
the Python functions exist for credential-free real-Git rehearsals. This file
also runs through ``python -c`` with the retained controller on sys.path.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from constructicon.api._maintenance_source import (
    SOURCE_HASHES,
    inspect_source,
    read_bounded,
    write_once,
)
from constructicon.api.maintenance_entry import inspect_result
from constructicon.core.maintenance import TARGET_PATH, VECTOR_PATH
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.linux import ProcessLimits
from constructicon.substrate.gates import maintenance as vector_gate
from constructicon.substrate.git.process import GitProcess

MAX_COMMIT = 4096
MAX_VECTOR = 32768
MAX_ARTIFACT = 80 * 1024
MAX_LOCAL_BASE_PACK = 64 * 1024 * 1024
GATE_PATH = "src/constructicon/substrate/gates/maintenance.py"


class TransferRefused(ValueError):
    """A fixed reason that carries no private source bytes or locators."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise TransferRefused(reason)


@dataclass(frozen=True)
class Pins:
    candidate: str
    base: str
    run_id: str
    input_sha256: str
    render_sha256: str
    target_sha256: str = SOURCE_HASHES[TARGET_PATH]
    gate_sha256: str = SOURCE_HASHES[GATE_PATH]

    def __post_init__(self) -> None:
        for value in (self.candidate, self.base):
            require(re.fullmatch(r"[0-9a-f]{40}", value) is not None, "commit-pin")
        require(re.fullmatch(r"run-[0-9a-f]{32}", self.run_id) is not None, "run-pin")
        for value in (self.input_sha256, self.render_sha256,
                      self.target_sha256, self.gate_sha256):
            require(re.fullmatch(r"[0-9a-f]{64}", value) is not None, "digest-pin")

    def historical(self) -> dict[str, object]:
        return {"schema_version": 1, "meaning": "historical-application-acceptance",
                "run_id": self.run_id, "candidate_commit": self.candidate,
                "input_sha256": self.input_sha256, "render_sha256": self.render_sha256}


Q13 = Pins(
    candidate="058d85fed094256f09b909789a8e07b72092337f",
    base="5793ef98ef5597c9ee9811a0d1f031554eb7f514",
    run_id="run-4c5df557e3d2f6a0f44030084115f865",
    input_sha256="ef04c5d45233e6a7cd7b54e9cc29d1e67a9511f1a030f6a57df8278a9759d67e",
    render_sha256="ec1a425474b6cd7c286c65556bfa9e5bd3278c525436d1efa867acd249fc3d02",
)


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def object_oid(kind: str, raw: bytes) -> str:
    return hashlib.sha1(kind.encode("ascii") + b" " + str(len(raw)).encode()
                        + b"\0" + raw).hexdigest()


def commit_tree(raw: bytes, pins: Pins) -> str:
    require(0 < len(raw) <= MAX_COMMIT, "commit-bound")
    require(object_oid("commit", raw) == pins.candidate, "candidate-identity")
    header, separator, message = raw.partition(b"\n\n")
    rows = header.split(b"\n")
    require(separator == b"\n\n" and 0 < len(message) <= 2048 and len(rows) == 4,
            "commit-metadata")
    require(re.fullmatch(rb"tree [0-9a-f]{40}", rows[0]) is not None
            and rows[1] == b"parent " + pins.base.encode()
            and re.fullmatch(rb"author [\x20-\x7e]{1,512}", rows[2]) is not None
            and re.fullmatch(rb"committer [\x20-\x7e]{1,512}", rows[3]) is not None,
            "commit-metadata")
    try:
        message_text = message.decode("utf-8")
    except UnicodeError as error:
        raise TransferRefused("commit-message") from error
    require(all(char == "\n" or char.isprintable() for char in message_text), "commit-message")
    return rows[0][5:].decode("ascii")


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, "duplicate-key")
        result[key] = value
    return result


def artifact_bytes(raw_commit: bytes, vector: bytes, pins: Pins) -> bytes:
    commit_tree(raw_commit, pins)
    require(len(vector) <= MAX_VECTOR
            and hashlib.sha256(vector).hexdigest() == pins.input_sha256, "vector-identity")
    raw = canonical({"schema_version": 1, "base_commit": pins.base,
                     "candidate_commit": pins.candidate, "path": VECTOR_PATH,
                     "mode": "100644", "commit_hex": raw_commit.hex(),
                     "vector_hex": vector.hex(), "historical": pins.historical()})
    require(len(raw) <= MAX_ARTIFACT, "artifact-bound")
    return raw


def parse_artifact(raw: bytes, pins: Pins) -> tuple[bytes, bytes]:
    require(type(raw) is bytes and 0 < len(raw) <= MAX_ARTIFACT, "artifact-bound")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise TransferRefused("artifact-json") from error
    keys = {"schema_version", "base_commit", "candidate_commit", "path", "mode",
            "commit_hex", "vector_hex", "historical"}
    require(type(value) is dict and set(value) == keys, "artifact-shape")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["base_commit"] == pins.base
            and value["candidate_commit"] == pins.candidate
            and value["path"] == VECTOR_PATH and value["mode"] == "100644",
            "artifact-pins")
    require(type(value["historical"]) is dict
            and canonical(value["historical"]) == canonical(pins.historical()),
            "historical-pins")
    decoded = []
    for name, bound in (("commit_hex", MAX_COMMIT), ("vector_hex", MAX_VECTOR)):
        encoded = value[name]
        require(type(encoded) is str and len(encoded) <= 2 * bound
                and len(encoded) % 2 == 0
                and re.fullmatch(r"[0-9a-f]*", encoded) is not None, "hex-shape")
        decoded.append(bytes.fromhex(encoded))
    commit, vector = decoded
    require(raw == artifact_bytes(commit, vector, pins), "artifact-canonical")
    return commit, vector


def git_process(artifact_bytes: int = MAX_ARTIFACT) -> GitProcess:
    executable = shutil.which("git")
    require(executable is not None, "git-unavailable")
    return GitProcess(str(Path(executable).resolve()), ProcessLimits(
        artifact_bytes=artifact_bytes, stderr_bytes=4096))


async def export_candidate(root: Path, pins: Pins) -> bytes:
    """Observe authority only; emit no bytes until all source checks finish."""
    source = await inspect_source(root)
    require(source.base_commit == pins.base, "source-base")
    git = git_process()
    repo = root / "authority.git"
    commit = await git_process(MAX_COMMIT).run("cat-file", "commit", pins.candidate, cwd=repo)
    commit_tree(commit, pins)
    parents = await git.run("rev-list", "--parents", "-n", "1", pins.candidate, cwd=repo)
    require(parents.split() == [pins.candidate.encode(), pins.base.encode()], "sole-parent")
    delta = await git.run("diff-tree", "--no-commit-id", "--raw", "--no-abbrev", "-r",
                          "-z", "--no-renames", pins.base, pins.candidate, cwd=repo)
    fields = delta.split(b"\0")
    metadata = fields[0].split() if fields else []
    require(len(fields) == 3 and fields[1] == VECTOR_PATH.encode() and fields[2] == b""
            and len(metadata) == 5 and metadata[0] == b":000000"
            and metadata[1] == b"100644" and metadata[2] == b"0" * 40
            and re.fullmatch(rb"[0-9a-f]{40}", metadata[3]) is not None
            and metadata[4] == b"A", "one-added-vector")
    vector = await git_process(MAX_VECTOR).run("cat-file", "blob", metadata[3].decode("ascii"),
                                               cwd=repo)
    require(inspect_result(root / "maintenance-result.json") == pins.historical(),
            "historical-pins")
    result = artifact_bytes(commit, vector, pins)
    require(await inspect_source(root) == source, "source-changed")
    return result


async def verify_candidate(raw: bytes, trusted_base: Path, quarantine: Path,
                           pins: Pins) -> dict[str, object]:
    """Reconstruct in a new local repository; create no branch or main objects."""
    commit, vector = parse_artifact(raw, pins)
    require(trusted_base.is_absolute() and trusted_base.resolve() == trusted_base
            and trusted_base.is_dir(), "trusted-base-path")
    require(quarantine.is_absolute() and quarantine.parent.resolve() == quarantine.parent,
            "quarantine-path")
    # A symlink (including a dangling one) and any occupied destination refuse.
    require(not os.path.lexists(quarantine), "quarantine-occupied")
    quarantine.mkdir(mode=0o700)
    git = git_process()
    base = await git.run("cat-file", "commit", pins.base, cwd=trusted_base)
    require(object_oid("commit", base) == pins.base, "local-base-identity")
    first = base.partition(b"\n")[0]
    require(re.fullmatch(rb"tree [0-9a-f]{40}", first) is not None, "local-base-tree")
    base_tree = first[5:].decode("ascii")
    target = await git.run("cat-file", "blob", f"{pins.base}:{TARGET_PATH}", cwd=trusted_base)
    gate = await git.run("cat-file", "blob", f"{pins.base}:{GATE_PATH}", cwd=trusted_base)
    require(hashlib.sha256(target).hexdigest() == pins.target_sha256
            and hashlib.sha256(gate).hexdigest() == pins.gate_sha256, "trusted-source-pins")
    # CPython normalizes source newlines when importing. Permit the checkout's
    # CRLF spelling only when its normalized bytes equal the pinned base source.
    imported = read_bounded(Path(vector_gate.__file__), 65536).replace(b"\r\n", b"\n")
    require(imported == gate, "imported-gate-pin")
    require(await git.run("ls-tree", pins.base, "--", VECTOR_PATH,
                          cwd=trusted_base) == b"", "base-vector-present")
    pack_git = git_process(MAX_LOCAL_BASE_PACK)
    local_pack = await pack_git.run("pack-objects", "--stdout", "--revs", cwd=trusted_base,
                                    stdin=(base_tree + "\n").encode())
    await git.run("init", "--quiet", "--bare", "--template=", "--object-format=sha1", ".",
                  cwd=quarantine, creation_mask=0o077)
    await pack_git.run("index-pack", "--stdin", "--strict", "--threads=1",
                       f"--max-input-size={MAX_LOCAL_BASE_PACK}", cwd=quarantine, stdin=local_pack)
    inserted_base = await git.run("hash-object", "-t", "commit", "-w", "--stdin",
                                  cwd=quarantine, stdin=base)
    require(inserted_base == (pins.base + "\n").encode(), "local-base-import")
    blob = await git.run("hash-object", "-t", "blob", "-w", "--stdin",
                         cwd=quarantine, stdin=vector)
    require(blob == (object_oid("blob", vector) + "\n").encode(), "vector-import")
    await git.run("read-tree", base_tree, cwd=quarantine)
    await git.run("update-index", "--add", "--cacheinfo", "100644", blob.strip().decode(),
                  VECTOR_PATH, cwd=quarantine)
    tree = await git.run("write-tree", cwd=quarantine)
    require(tree == (commit_tree(commit, pins) + "\n").encode(), "reconstructed-tree")
    candidate = await git.run("hash-object", "-t", "commit", "-w", "--stdin",
                              cwd=quarantine, stdin=commit)
    require(candidate == (pins.candidate + "\n").encode(), "candidate-import")
    require(await git.run("for-each-ref", cwd=quarantine) == b"", "quarantine-refs")
    report = await finish_owned(asyncio.create_task(asyncio.to_thread(
        vector_gate.run_vectors, vector, target, pins.target_sha256)))
    require(report.passed and report.input_sha256 == pins.input_sha256
            and report.render_sha256 == pins.render_sha256, "trusted-exam")
    result: dict[str, object] = {"schema_version": 1,
        "meaning": "exact-candidate-reconstructed-and-exam-passed",
        "historical_projection_matched": True, "tree_reconstructed": True,
        "reexam_passed": True,
        "candidate_commit": pins.candidate, "base_commit": pins.base,
        "input_sha256": report.input_sha256, "render_sha256": report.render_sha256,
        "artifact_sha256": hashlib.sha256(raw).hexdigest()}
    write_once(quarantine / "VERIFIED.json", canonical(result))
    return result


async def capture_transfer(argv: tuple[str, ...], destination: Path, pins: Pins,
                           *, timeout_s: float = 60) -> dict[str, object]:
    """One bounded direct child; refusal preserves partial private captures.

    Killing SSH locally does not establish termination of its remote command.
    An incomplete capture grants no retry authority.
    """
    require(bool(argv) and timeout_s > 0, "capture-arguments")
    require(destination.is_absolute() and destination.parent.resolve() == destination.parent
            and not os.path.lexists(destination), "capture-destination")
    destination.mkdir(mode=0o700)
    state: dict[str, object] = {"schema_version": 1, "complete": False,
        "launch_requested": False, "returncode": None, "stdout_eof": False,
        "stderr_eof": False, "stdout_bytes": 0, "stderr_bytes": 0,
        "overflow": False, "timed_out": False, "capture_io_failed": False}
    process = None
    spawn = None
    exchange = None
    drains = []
    output = bytearray()
    errors = bytearray()

    async def drain(stream, handle, buffer, name, bound):
        while chunk := await stream.read(8192):
            room = max(0, bound + 1 - len(buffer))
            buffer.extend(chunk[:room])
            if not state["capture_io_failed"]:
                try:
                    require(handle.write(chunk[:room]) == min(room, len(chunk)), "capture-write")
                except (OSError, TransferRefused):
                    state["capture_io_failed"] = True
            state[name + "_bytes"] = len(buffer)
            if len(chunk) > room or len(buffer) > bound or state["capture_io_failed"]:
                if len(chunk) > room or len(buffer) > bound:
                    state["overflow"] = True
                if process is not None and process.returncode is None:
                    with suppress(ProcessLookupError):
                        process.kill()
        state[name + "_eof"] = True

    async def cleanup():
        nonlocal process
        if spawn is not None:
            process = process or await spawn
        if process is not None:
            # Cancellation may resume here before the shielded spawn returned
            # to its caller. Enrol readers before waiting for a full pipe.
            if not drains:
                drains.extend((
                    asyncio.create_task(drain(process.stdout, stdout, output,
                                              "stdout", MAX_ARTIFACT)),
                    asyncio.create_task(drain(process.stderr, stderr, errors, "stderr", 1024)),
                ))
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
        if drains:
            await asyncio.gather(*drains, return_exceptions=True)
        if process is not None:
            await process.wait()
            state["returncode"] = process.returncode
        if exchange is not None:
            await asyncio.gather(exchange, return_exceptions=True)

    try:
        with (destination / "stdout.private").open("x+b", buffering=0) as stdout, (
                destination / "stderr.private").open("x+b", buffering=0) as stderr:
            try:
                state["launch_requested"] = True
                spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                    *argv, stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    close_fds=True))
                async with asyncio.timeout(timeout_s):
                    process = await asyncio.shield(spawn)
                    drains = [asyncio.create_task(drain(process.stdout, stdout, output,
                                                       "stdout", MAX_ARTIFACT)),
                              asyncio.create_task(drain(process.stderr, stderr, errors,
                                                       "stderr", 1024))]
                    # Keep the readers alive across timeout/cancellation; cleanup
                    # kills and joins them before closing their capture handles.
                    exchange = asyncio.gather(process.wait(), *drains)
                    await asyncio.shield(exchange)
                state["returncode"] = process.returncode
                require(process.returncode == 0 and state["stdout_eof"] is True
                        and state["stderr_eof"] is True and not state["overflow"]
                        and not state["capture_io_failed"] and not errors, "capture-incomplete")
                parse_artifact(bytes(output), pins)
            except TimeoutError:
                state["timed_out"] = True
                raise TransferRefused("capture-timeout") from None
            finally:
                await finish_owned(asyncio.create_task(cleanup()))
                for handle in (stdout, stderr):
                    handle.flush()
                    os.fsync(handle.fileno())
        write_once(destination / "artifact.json", bytes(output))
        state["complete"] = True
    finally:
        write_once(destination / "status.json", canonical(state))
    return {"schema_version": 1, "meaning": "bounded-transfer-received",
            "historical_projection_matched": True,
            "artifact_bytes": len(output), "artifact_sha256": hashlib.sha256(output).hexdigest()}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise TransferRefused("arguments")


async def command(argv: list[str]) -> int:
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--root", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--artifact", type=Path, required=True)
    verify.add_argument("--trusted-base", type=Path, required=True)
    verify.add_argument("--quarantine", type=Path, required=True)
    capture = commands.add_parser("capture")
    capture.add_argument("--out", type=Path, required=True)
    capture.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "export":
        sys.stdout.buffer.write(await export_candidate(args.root, Q13))
        sys.stdout.buffer.flush()
    elif args.command == "verify":
        result = await verify_candidate(read_bounded(args.artifact, MAX_ARTIFACT),
                                        args.trusted_base, args.quarantine, Q13)
        sys.stdout.buffer.write(canonical(result))
        sys.stdout.buffer.flush()
    else:
        argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
        executable = shutil.which("ssh")
        require(executable is not None and bool(argv)
                and Path(argv[0]).resolve() == Path(executable).resolve(), "capture-ssh")
        result = await capture_transfer(tuple(argv), args.out, Q13)
        sys.stdout.buffer.write(canonical(result))
        sys.stdout.buffer.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(command(sys.argv[1:] if argv is None else argv))
    except Exception:
        sys.stderr.write("candidate-transfer-refused\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
