"""Guest-side one-shot claim and completion proof for the fixed M9 READ.

Run only as the trusted operator in the fresh, private, staged phase directory.
A lost SSH response is not a completion receipt. The observer either wins a
fence before native intent, or reads a receipt written after native return.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
BOOT = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
SHA = re.compile(r"[0-9a-f]{64}")
SERVICE_STATE = "/home/m8-service/m9-s1"
SESSION = "/home/m8-service/m9-codex-g12"
CONTROLLER = "/opt/constructicon-m8-controller"
AUTH_PARENT = "/var/lib/constructicon-m8-launch/qualification"
CLOSURE_SOURCE = b""  # Replaced in the checked phase, alongside the fixed pins.

SERVICE = (
    "/usr/bin/sudo",
    "-n",
    "-u",
    "m8-service",
    "/usr/bin/env",
    "-i",
    "PATH=/usr/bin:/bin",
    "HOME=/home/m8-service",
    "LANG=C.UTF-8",
    "/usr/bin/python3",
    "-I",
    "-S",
    "-B",
    "-c",
)

# Checked on the guest as the service, then the already installed entry reads
# the root-owned authorization again. The protected parent and a single
# authorized operator rule out concurrent replacement by the service.
_SERVICE_CODE = """
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api.m9_trial import main
from constructicon.substrate.executors.qualification import _read_authorization_bytes

authorization, expected, cutoff = sys.argv[1:4]
raw = _read_authorization_bytes(Path(authorization))
if hashlib.sha256(raw).hexdigest() != expected:
    raise SystemExit("M9_READ_AUTHORIZATION_BYTES_CHANGED")
if time.time() >= int(cutoff):
    raise SystemExit("M9_READ_ADMISSION_EXPIRED")
raise SystemExit(main(sys.argv[4:]))
"""

# Root writes use the same stock install/rm boundary as the operator
# procedure. The installed controller checks protected ancestry and reads
# exact root-owned bytes under the service account; it does not issue READ.
_AUTH_CODE = """
import hashlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.core.qualification import QualificationAuthorization
from constructicon.substrate.executors.operator_store import _open_trusted_directory
from constructicon.substrate.executors.qualification import _read_authorization_bytes

action, name, expected = sys.argv[1:]
path = Path(name)
parent = _open_trusted_directory(path.parent)
try:
    try:
        os.stat(path.name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        present = False
    else:
        present = True
finally:
    os.close(parent)
if action == "fresh":
    candidate = sys.stdin.buffer.read(8193)
    selected = QualificationAuthorization.model_validate_json(candidate)
    if (
        present or selected.not_after <= datetime.now(UTC)
        or hashlib.sha256(candidate).hexdigest() != expected
    ):
        raise SystemExit("M9_READ_AUTHORIZATION_PLACEMENT_REFUSED")
elif not present and action == "inspect":
    print("absent")
elif present and action in ("readback", "inspect"):
    raw = _read_authorization_bytes(path)
    QualificationAuthorization.model_validate_json(raw)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise SystemExit("M9_READ_AUTHORIZATION_BYTES_CHANGED")
    if action == "readback":
        sys.stdout.buffer.write(raw)
    else:
        print("present")
else:
    raise SystemExit("M9_READ_AUTHORIZATION_STATE_UNPROVED")
"""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def read_argv(candidate_sha: str, authorization: str, admit_until: int) -> list[str]:
    """Use the installed selector's fixed trial, provider, and grants."""
    _require(SHA.fullmatch(candidate_sha) is not None, "M9_READ_BAD_CANDIDATE_HASH")
    _require(type(admit_until) is int and 0 < admit_until < 2**53, "M9_READ_BAD_ADMISSION_CUTOFF")
    prefix = AUTH_PARENT + "/"
    leaf = authorization.removeprefix(prefix)
    _require(
        authorization.startswith(prefix)
        and re.fullmatch(r"[a-z0-9-]{1,80}\.json", leaf) is not None,
        "M9_READ_BAD_AUTHORIZATION_LEAF",
    )
    return [
        *SERVICE,
        _SERVICE_CODE,
        authorization,
        candidate_sha,
        str(admit_until),
        "propose",
        "--trial",
        "m9-live-1",
        "--store",
        SERVICE_STATE + "/trial",
        "--session",
        SESSION,
        "--store-key",
        "n4-codex-pro",
        "--sealed",
        SESSION + "/g12.sealed.json",
        "--qualification",
        SESSION + "/s6a-qualification.json",
        "--state",
        SERVICE_STATE,
        "--authorization",
        authorization,
    ]


def _encoded(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _retain(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    # Both the bytes and the exclusive directory entry precede native intent.
    _sync_directory(path.parent)


def _sync_directory(path: Path) -> None:
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _matches(path: Path, raw: bytes) -> bool:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return False
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        matched = (
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.geteuid()
            and info.st_nlink == 1
            and not info.st_mode & 0o077
            and stream.read(len(raw) + 1) == raw
        )
        if matched:
            os.fsync(stream.fileno())
            _sync_directory(path.parent)
        return matched


def _decision(boot: str, claim: str, state: str) -> bytes:
    return _encoded({"boot": boot, "claim": claim, "state": state})


def _check(work: Path, boot: str, claim: str) -> None:
    _require(
        BOOT.fullmatch(boot) is not None and SHA.fullmatch(claim) is not None,
        "M9_READ_BAD_BOOT_OR_CLAIM",
    )
    _require(BOOT_ID.read_bytes() == (boot + "\n").encode("ascii"), "M9_READ_WRONG_BOOT")
    info = work.lstat()
    _require(
        work == work.resolve(strict=True)
        and stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid() != 0
        and stat.S_IMODE(info.st_mode) == 0o700,
        "M9_READ_UNSAFE_GUEST_WORKSPACE",
    )


def _logs(work: Path) -> tuple[bytes, bytes]:
    values = []
    for leaf in ("read.stdout", "read.stderr"):
        fd = os.open(work / leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            _require(
                stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077 and info.st_size <= 4096,
                "M9_READ_UNSAFE_ORIGINAL_LOG",
            )
            raw = stream.read(4097)
            after = os.fstat(stream.fileno())
            _require(len(raw) == info.st_size and info.st_ctime_ns == after.st_ctime_ns
                     and info.st_mtime_ns == after.st_mtime_ns, "M9_READ_ORIGINAL_LOG_CHANGED")
            values.append(raw)
    return values[0], values[1]


def _terminal_record(boot: str, claim: str, out: bytes, err: bytes) -> bytes:
    return _encoded({"boot": boot, "claim": claim, "returncode": 0,
                     "stdout_sha256": hashlib.sha256(out).hexdigest(),
                     "stderr_sha256": hashlib.sha256(err).hexdigest()})


def original(work: Path, boot: str, claim: str) -> tuple[bytes, bytes]:
    """Original streams only, under a matching protected terminal receipt."""
    _check(work, boot, claim)
    _require(_matches(work / "native-decision", _decision(boot, claim, "dispatch")),
             "M9_READ_NATIVE_INTENT_UNPROVED")
    out, err = _logs(work)
    _require(_matches(work / "native-terminal", _terminal_record(boot, claim, out, err)),
             "M9_READ_ORIGINAL_LOG_UNPROVED")
    return out, err


def projection(work: Path, boot: str, claim: str, pins: list[str]) -> bytes:
    original(work, boot, claim)
    _require(bool(CLOSURE_SOURCE) and pins[1] == "m9-live-1", "M9_READ_CLOSURE_BAD_PINS")
    attempt, *bindings = pins
    result = subprocess.run(
        [*SERVICE[:-1], "-", SERVICE_STATE + "/trial", attempt, *bindings],
        input=CLOSURE_SOURCE, capture_output=True, check=False,
    )
    _require(
        result.returncode == 0 and not result.stderr and 0 < len(result.stdout) <= 4096,
        "M9_READ_CLOSURE_UNPROVED",
    )
    return result.stdout


def dispatch(
    work: Path,
    boot: str,
    claim: str,
    candidate_sha: str,
    authorization: str,
    admit_until: int,
) -> str:
    """No replay, including if the guest previously lost the child result."""
    _check(work, boot, claim)
    argv = read_argv(candidate_sha, authorization, admit_until)
    _require(time.time() < admit_until, "M9_READ_ADMISSION_EXPIRED")
    _require(
        _matches(work / "placement-terminal", _decision(boot, claim, "placed")),
        "M9_READ_REQUIRES_CHECKED_PLACEMENT",
    )
    decision = work / "native-decision"
    _retain(decision, _decision(boot, claim, "dispatch"))
    with (work / "read.stdout").open("xb") as stdout, (work / "read.stderr").open("xb") as stderr:
        _require(time.time() < admit_until, "M9_READ_ADMISSION_EXPIRED")
        result = subprocess.run(
            argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, check=False
        )
        stdout.flush()
        stderr.flush()
        os.fsync(stdout.fileno())
        os.fsync(stderr.fileno())
    # The installed successful propose path awaits owned control.shutdown in
    # m9_trial.execute_selection before returning. A nonzero or lost child
    # result is deliberately not terminal proof, even if SSH completed.
    if result.returncode != 0:
        return "unknown"
    out, err = _logs(work)
    _retain(work / "native-terminal", _terminal_record(boot, claim, out, err))
    return "joined"


def prove(work: Path, boot: str, claim: str) -> str:
    """Fence a delayed dispatch or independently observe positive native return."""
    _check(work, boot, claim)
    decision = work / "native-decision"
    fence = _decision(boot, claim, "fenced")
    try:
        _retain(decision, fence)
    except FileExistsError:
        # A previous proof can be read again, but can never start a turn.
        # A partial claim or a delayed child remains unknown.
        if _matches(decision, fence):
            return "fenced"
        try:
            original(work, boot, claim)
        except (OSError, ValueError):
            return "unknown"
        return "joined"
    return "fenced"


def _authority(action: str, authorization: str, expected: str, candidate=None) -> bytes:
    read_argv(expected, authorization, 1)  # same fixed leaf and digest validation as dispatch
    argv = [*SERVICE, _AUTH_CODE, action, authorization, expected]
    if candidate is None:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, check=False)
    else:
        result = subprocess.run(argv, input=candidate, capture_output=True, check=False)
    _require(
        result.returncode == 0 and not result.stderr and len(result.stdout) <= 8192,
        "M9_READ_AUTHORIZATION_PROOF_UNAVAILABLE",
    )
    return result.stdout


def place(
    work: Path,
    boot: str,
    claim: str,
    expected: str,
    authorization: str,
    admit_until: int,
    candidate: bytes,
) -> str:
    _check(work, boot, claim)
    read_argv(expected, authorization, admit_until)
    _require(
        0 < len(candidate) <= 8192 and hashlib.sha256(candidate).hexdigest() == expected,
        "M9_READ_BAD_CANDIDATE_BYTES",
    )
    _require(time.time() < admit_until, "M9_READ_ADMISSION_EXPIRED")
    _retain(work / "placement-decision", _decision(boot, claim, "place"))
    _require(
        not _authority("fresh", authorization, expected, candidate),
        "M9_READ_AUTHORIZATION_FRESHNESS_UNPROVED",
    )
    file = work / "candidate"
    _retain(file, candidate)
    _require(time.time() < admit_until, "M9_READ_ADMISSION_EXPIRED")
    install = subprocess.run(
        [
            "/usr/bin/sudo",
            "-n",
            "/usr/bin/install",
            "-o",
            "root",
            "-g",
            "m8-service",
            "-m",
            "0640",
            "--",
            str(file),
            authorization,
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    _require(
        install.returncode == 0 and not install.stdout and not install.stderr,
        "M9_READ_AUTHORIZATION_INSTALL_UNPROVED",
    )
    _retain(work / "placement-terminal", _decision(boot, claim, "placed"))
    return "placed"


def discard(work: Path, boot: str, claim: str, expected: str, authorization: str) -> str:
    """Fence a delayed placement before touching the leaf, or prove it joined."""
    _check(work, boot, claim)
    read_argv(expected, authorization, 1)
    fence = _decision(boot, claim, "fenced")
    decision = work / "placement-decision"
    placed = False
    try:
        _retain(decision, fence)
    except FileExistsError:
        placed = _matches(decision, _decision(boot, claim, "place")) and _matches(
            work / "placement-terminal", _decision(boot, claim, "placed")
        )
        _require(placed or _matches(decision, fence), "M9_READ_AUTHORIZATION_PLACEMENT_UNRESOLVED")
    _require(prove(work, boot, claim) in ("joined", "fenced"), "M9_READ_NATIVE_STATE_UNRESOLVED")
    state = _authority("inspect", authorization, expected)
    if state == b"present\n":
        _require(placed, "M9_READ_AUTHORIZATION_LEAF_NOT_OWNED")
        removed = subprocess.run(
            ["/usr/bin/sudo", "-n", "/usr/bin/rm", "--", authorization],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )
        _require(
            removed.returncode == 0 and not removed.stdout and not removed.stderr,
            "M9_READ_AUTHORIZATION_REMOVAL_UNPROVED",
        )
        state = _authority("inspect", authorization, expected)
    _require(state == b"absent\n", "M9_READ_AUTHORIZATION_NOT_ABSENT")
    return "discarded"


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument(
        "action",
        choices=("dispatch", "prove", "original", "projection", "place", "readback", "discard"),
    )
    parser.add_argument("--boot", required=True)
    parser.add_argument("--claim", required=True)
    parser.add_argument("--closure-pins", nargs=9)
    parser.add_argument("--candidate-sha")
    parser.add_argument("--authorization")
    parser.add_argument("--admit-until", type=int)
    parser.add_argument("--candidate-hex")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        _require((args.closure_pins is not None) == (args.action == "projection"),
                 "M9_READ_CLOSURE_BAD_PINS")
        if args.action in ("prove", "original", "projection"):
            _require(
                args.candidate_sha is None
                and args.authorization is None
                and args.admit_until is None
                and args.candidate_hex is None,
                "M9_READ_BAD_PROOF_ARGUMENTS",
            )
            if args.action == "projection":
                sys.stdout.buffer.write(projection(Path.cwd(), args.boot, args.claim,
                                                   args.closure_pins))
                return 0
            if args.action == "original":
                out, err = original(Path.cwd(), args.boot, args.claim)
                sys.stdout.buffer.write(_encoded({"boot": args.boot, "claim": args.claim,
                                                  "returncode": 0,
                                                  "stdout": base64.b64encode(out).decode("ascii"),
                                                  "stderr": base64.b64encode(err).decode("ascii")}))
                return 0
            state = prove(Path.cwd(), args.boot, args.claim)
        else:
            _require(
                args.candidate_sha is not None and args.authorization is not None,
                "M9_READ_MISSING_AUTHORIZATION_BINDING",
            )
            if args.action == "place":
                _require(
                    args.admit_until is not None
                    and args.candidate_hex is not None
                    and re.fullmatch(r"(?:[0-9a-f]{2}){1,8192}", args.candidate_hex) is not None,
                    "M9_READ_MISSING_PLACEMENT_BINDING",
                )
                state = place(
                    Path.cwd(),
                    args.boot,
                    args.claim,
                    args.candidate_sha,
                    args.authorization,
                    args.admit_until,
                    bytes.fromhex(args.candidate_hex),
                )
            else:
                _require(args.candidate_hex is None, "M9_READ_UNEXPECTED_CANDIDATE")
                if args.action == "dispatch":
                    _require(args.admit_until is not None, "M9_READ_MISSING_DISPATCH_BINDING")
                    state = dispatch(
                        Path.cwd(),
                        args.boot,
                        args.claim,
                        args.candidate_sha,
                        args.authorization,
                        args.admit_until,
                    )
                elif args.action == "discard":
                    state = discard(
                        Path.cwd(), args.boot, args.claim, args.candidate_sha, args.authorization
                    )
                else:
                    _check(Path.cwd(), args.boot, args.claim)
                    raw = _authority("readback", args.authorization, args.candidate_sha)
                    sys.stdout.buffer.write(raw)
                    return 0
    except FileExistsError:
        state = "unknown"
    except (OSError, ValueError):
        state = "unknown"
    record = {"state": state}
    if state != "unknown":
        record.update(boot=args.boot, claim=args.claim)
    print(_encoded(record).decode("ascii"), end="")
    return 0 if state != "unknown" else 1


if __name__ == "__main__":
    raise SystemExit(main())
