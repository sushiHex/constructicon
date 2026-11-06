"""Guest-side one-shot claim and completion proof for the fixed M9 READ.

Run only as the trusted operator in the fresh, private, staged phase directory.
A lost SSH response is not a completion receipt. The observer either wins a
fence before native intent, or reads a receipt written after native return.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import time
from pathlib import Path

BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
BOOT = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
SHA = re.compile(r"[0-9a-f]{64}")
SERVICE_STATE = "/home/m8-service/m9-s1"
SESSION = "/home/m8-service/m9-codex-g12"
CONTROLLER = "/opt/constructicon-m8-controller"
AUTH_PARENT = "/var/lib/constructicon-m8-launch/qualification"

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
    _retain(work / "native-terminal", _decision(boot, claim, "joined"))
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
        if _matches(decision, _decision(boot, claim, "dispatch")) and _matches(
            work / "native-terminal", _decision(boot, claim, "joined")
        ):
            return "joined"
        return "unknown"
    return "fenced"


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("action", choices=("dispatch", "prove"))
    parser.add_argument("--boot", required=True)
    parser.add_argument("--claim", required=True)
    parser.add_argument("--candidate-sha")
    parser.add_argument("--authorization")
    parser.add_argument("--admit-until", type=int)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.action == "dispatch":
            _require(
                args.candidate_sha is not None
                and args.authorization is not None
                and args.admit_until is not None,
                "M9_READ_MISSING_DISPATCH_BINDING",
            )
            state = dispatch(
                Path.cwd(),
                args.boot,
                args.claim,
                args.candidate_sha,
                args.authorization,
                args.admit_until,
            )
        else:
            _require(
                args.candidate_sha is None
                and args.authorization is None
                and args.admit_until is None,
                "M9_READ_BAD_PROOF_ARGUMENTS",
            )
            state = prove(Path.cwd(), args.boot, args.claim)
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
