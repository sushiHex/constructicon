"""Guest-side one-shot claim and completion proof for one reviewed READ consumer.

Run only as the trusted operator in the fresh, private, staged phase directory.
A lost SSH response is not a completion receipt. The observer either wins a
fence before native intent, or reads a receipt written after native return.

Exactly two consumers exist, each a frozen descriptor below: the M9 selector
and the change-review advice route. Only a descriptor's closed id is ever
chosen; its entry, argv, derived paths, closure rule and bounds are this
source's, never a caller's.
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
from dataclasses import dataclass
from pathlib import Path

BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
BOOT = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
SHA = re.compile(r"[0-9a-f]{64}")
SERVICE_STATE = "/home/m8-service/m9-s1"
SESSION = "/home/m8-service/m9-codex-g12"
CONTROLLER = "/opt/constructicon-m8-controller"
AUTH_PARENT = "/var/lib/constructicon-m8-launch/qualification"
CLOSURE_SOURCE = b""  # Replaced in the checked phase, alongside the fixed pins.

# The advice route's own bounds, restated because this program runs alone on
# the guest; the host transport refuses to stage if either differs from
# change_review_advice.INSTRUCTION_MAX_BYTES / MODEL_ADVICE_MAX_BYTES.
SUMMARY_LIMIT = 8192
REPLY_LIMIT = 16384
# The entry prints json.dumps(ensure_ascii=True): one reply byte (a control
# byte) becomes the six bytes of "\u0001". The frame bounds everything beside
# the escaped reply: the run identity, the advice fields and the result
# preview, whose outputs are each cut to 2,000 canonical bytes.
ESCAPE = 6
FRAME = 16384
COMPLETION_LIMIT = 4096


def _b64(size: int) -> int:
    return 4 * ((size + 2) // 3)


@dataclass(frozen=True)
class Consumer:
    """One reviewed READ consumer. Slots in ``{}`` are derived from its site."""

    id: str
    prefix: str  # every refusal names its consumer
    procedure: str  # the owner challenge's literal
    entry: str  # the constructicon.api module whose main is the READ entry
    site: tuple[str, str, str] | None  # fixed (root, label, state), or selected
    run: tuple[str, ...]  # the entry's argv after the permit-bytes prologue
    journal: str
    attempt: str | None  # None: the candidate selects it (M9's existing rule)
    phases: tuple[str, ...]  # the qualification phases after the shared twelve
    closure: tuple[str, ...]  # the closure program's leading argv
    closure_arity: int  # the projection pins: the attempt, then its bindings
    closure_id: int  # the pin holding the authorization id
    closure_fixed: tuple[tuple[int, str], ...]
    replay: tuple[str, ...] | None  # the projection reruns the entry, unpermitted
    log_limit: int  # each original stream
    original_limit: int  # the original record, as the operator reads it
    projection_limit: int  # the projection record, as the operator reads it


M9 = Consumer(
    id="m9",
    prefix="M9_READ",
    procedure="m9-codex-read",
    entry="m9_trial",
    site=(SESSION, "g12", SERVICE_STATE),
    run=(
        "propose", "--trial", "m9-live-1", "--store", "{state}/trial", "--session", "{root}",
        "--store-key", "n4-codex-pro", "--sealed", "{sealed}",
        "--qualification", "{qualification}", "--state", "{state}",
        "--authorization", "{authorization}",
    ),
    journal="{state}/trial/journal.sqlite",
    attempt=None,
    phases=("trial-seed", "trial-pins", "trial-mint"),
    closure=("{state}/trial",),
    closure_arity=9,
    closure_id=2,
    closure_fixed=((1, "m9-live-1"),),
    replay=None,
    log_limit=4096,
    original_limit=16384,
    projection_limit=4096,
)
_ADVICE_LOG = ESCAPE * REPLY_LIMIT + FRAME
ADVICE = Consumer(
    id="change-review-advice",
    prefix="CHANGE_REVIEW_READ",
    procedure="change-review-advice-codex-read",
    entry="change_review_advice",
    site=None,
    run=(
        "--summary", "-", "--stage", "run", "--session", "{root}",
        "--store-key", "n4-codex-pro", "--sealed", "{sealed}",
        "--qualification", "{qualification}", "--state", "{state}",
        "--journal", "{journal}", "--authorization", "{authorization}",
    ),
    journal="{state}/{id}.sqlite",
    attempt="{state}/{id}.attempt",
    phases=("consumer-pins", "consumer-mint"),
    closure=("change-review-advice", "{journal}"),
    closure_arity=6,
    closure_id=1,
    closure_fixed=((0, "{attempt}"),),
    replay=("--summary", "-", "--stage", "run", "--journal", "{journal}"),
    log_limit=_ADVICE_LOG,
    original_limit=2 * _b64(_ADVICE_LOG) + 512,
    projection_limit=_b64(_ADVICE_LOG) + _b64(COMPLETION_LIMIT) + 512,
)
CONSUMERS = {consumer.id: consumer for consumer in (M9, ADVICE)}
_SERVICE_LEAF = re.compile(r"/home/m8-service/[a-z0-9][a-z0-9-]{0,62}")
_LABEL = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
_SCOPED_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


@dataclass(frozen=True)
class Site:
    """Where one consumer's READ lives on the guest; M9's is fixed.

    A selected site is fresh service ground: never M9's session or state,
    which are historical and must not be assumed absent or reused.
    """

    consumer: Consumer
    root: str
    label: str
    state: str

    def __post_init__(self) -> None:
        fixed = self.consumer.site
        _require(
            CONSUMERS.get(self.consumer.id) is self.consumer
            and type(self.root) is type(self.label) is type(self.state) is str
            and (
                (self.root, self.label, self.state) == fixed
                if fixed is not None
                else (
                    _SERVICE_LEAF.fullmatch(self.root) is not None
                    and _SERVICE_LEAF.fullmatch(self.state) is not None
                    and _LABEL.fullmatch(self.label) is not None
                    and len({self.root, self.state, SESSION, SERVICE_STATE}) == 4
                )
            ),
            self.consumer.prefix + "_BAD_SITE",
        )


M9_SITE = Site(M9, SESSION, "g12", SERVICE_STATE)


def paths(site: Site, identifier: str | None) -> dict[str, str]:
    """The consumer's derived paths; only the validated site and id vary."""
    consumer = site.consumer
    slots = {
        "root": site.root,
        "sealed": f"{site.root}/{site.label}.sealed.json",
        "qualification": site.root + "/s6a-qualification.json",
        "state": site.state,
    }
    if consumer.attempt is not None:
        # Guest names are scoped by the authorization id.
        _require(
            type(identifier) is str and _SCOPED_ID.fullmatch(identifier) is not None,
            consumer.prefix + "_BAD_AUTHORIZATION_ID",
        )
        slots.update(id=str(identifier), authorization=f"{AUTH_PARENT}/{identifier}.json")
        slots["attempt"] = consumer.attempt.format_map(slots)
    slots["journal"] = consumer.journal.format_map(slots)
    return slots


def _fill(template: tuple[str, ...], slots: dict[str, str]) -> list[str]:
    return [item.format_map(slots) for item in template]


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
from constructicon.api.ENTRY import main
from constructicon.substrate.executors.qualification import _read_authorization_bytes

authorization, expected, cutoff = sys.argv[1:4]
raw = _read_authorization_bytes(Path(authorization))
if hashlib.sha256(raw).hexdigest() != expected:
    raise SystemExit("PREFIX_AUTHORIZATION_BYTES_CHANGED")
if time.time() >= int(cutoff):
    raise SystemExit("PREFIX_ADMISSION_EXPIRED")
raise SystemExit(main(sys.argv[4:]))
"""

# The same installed entry with no permit: a completed run replays before any
# permit read (change_review_advice.run), and without one it can only refuse.
_REPLAY_CODE = """
import sys

sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api.ENTRY import main

raise SystemExit(main(sys.argv[1:]))
"""


def _code(source: str, consumer: Consumer) -> str:
    return source.replace("ENTRY", consumer.entry).replace("PREFIX", consumer.prefix)


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
        raise SystemExit("READ_AUTHORIZATION_PLACEMENT_REFUSED")
elif not present and action == "inspect":
    print("absent")
elif present and action in ("readback", "inspect"):
    raw = _read_authorization_bytes(path)
    QualificationAuthorization.model_validate_json(raw)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise SystemExit("READ_AUTHORIZATION_BYTES_CHANGED")
    if action == "readback":
        sys.stdout.buffer.write(raw)
    else:
        print("present")
else:
    raise SystemExit("READ_AUTHORIZATION_STATE_UNPROVED")
"""


def read_argv(
    candidate_sha: str, authorization: str, admit_until: int, site: Site = M9_SITE,
) -> list[str]:
    """Use the installed entry's fixed argv, provider, and grants for this site."""
    code = site.consumer.prefix + "_"
    _require(SHA.fullmatch(candidate_sha) is not None, code + "BAD_CANDIDATE_HASH")
    _require(type(admit_until) is int and 0 < admit_until < 2**53, code + "BAD_ADMISSION_CUTOFF")
    prefix = AUTH_PARENT + "/"
    leaf = authorization.removeprefix(prefix)
    _require(
        authorization.startswith(prefix)
        and re.fullmatch(r"[a-z0-9-]{1,80}\.json", leaf) is not None,
        code + "BAD_AUTHORIZATION_LEAF",
    )
    # A scoped site derives its paths from the leaf, so the leaf is the id.
    slots = {**paths(site, leaf.removesuffix(".json")), "authorization": authorization}
    return [
        *SERVICE,
        _code(_SERVICE_CODE, site.consumer),
        authorization,
        candidate_sha,
        str(admit_until),
        *_fill(site.consumer.run, slots),
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
        "READ_BAD_BOOT_OR_CLAIM",
    )
    _require(BOOT_ID.read_bytes() == (boot + "\n").encode("ascii"), "READ_WRONG_BOOT")
    info = work.lstat()
    _require(
        work == work.resolve(strict=True)
        and stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid() != 0
        and stat.S_IMODE(info.st_mode) == 0o700,
        "READ_UNSAFE_GUEST_WORKSPACE",
    )


def _logs(site: Site, work: Path) -> tuple[bytes, bytes]:
    code, limit = site.consumer.prefix + "_", site.consumer.log_limit
    values = []
    for leaf in ("read.stdout", "read.stderr"):
        fd = os.open(work / leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            _require(
                stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077 and info.st_size <= limit,
                code + "UNSAFE_ORIGINAL_LOG",
            )
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            _require(len(raw) == info.st_size and info.st_ctime_ns == after.st_ctime_ns
                     and info.st_mtime_ns == after.st_mtime_ns, code + "ORIGINAL_LOG_CHANGED")
            values.append(raw)
    return values[0], values[1]


def _terminal_record(boot: str, claim: str, out: bytes, err: bytes) -> bytes:
    return _encoded({"boot": boot, "claim": claim, "returncode": 0,
                     "stdout_sha256": hashlib.sha256(out).hexdigest(),
                     "stderr_sha256": hashlib.sha256(err).hexdigest()})


def original(site: Site, work: Path, boot: str, claim: str) -> tuple[bytes, bytes]:
    """Original streams only, under a matching protected terminal receipt."""
    code = site.consumer.prefix + "_"
    _check(work, boot, claim)
    _require(_matches(work / "native-decision", _decision(boot, claim, "dispatch")),
             code + "NATIVE_INTENT_UNPROVED")
    out, err = _logs(site, work)
    _require(_matches(work / "native-terminal", _terminal_record(boot, claim, out, err)),
             code + "ORIGINAL_LOG_UNPROVED")
    return out, err


def _service(argv: list[str], data: bytes, limit: int, code: str) -> bytes:
    result = subprocess.run(argv, input=data, capture_output=True, check=False)
    _require(result.returncode == 0 and not result.stderr and 0 < len(result.stdout) <= limit,
             code)
    return result.stdout


def projection(site: Site, work: Path, boot: str, claim: str, pins: list[str],
               summary: bytes | None) -> bytes:
    consumer = site.consumer
    code = consumer.prefix + "_"
    original(site, work, boot, claim)
    _require(bool(CLOSURE_SOURCE) and len(pins) == consumer.closure_arity
             and (summary is None) == (consumer.replay is None), code + "CLOSURE_BAD_PINS")
    slots = paths(site, pins[consumer.closure_id])
    _require(all(pins[i] == value.format_map(slots) for i, value in consumer.closure_fixed),
             code + "CLOSURE_BAD_PINS")
    replayed = None
    if consumer.replay is not None and summary is not None:
        # The route's own replay of the completed run, read without a permit.
        replayed = _service([*SERVICE, _code(_REPLAY_CODE, consumer),
                             *_fill(consumer.replay, slots)],
                            summary, consumer.log_limit, code + "REPLAY_UNPROVED")
    completion = _service([*SERVICE[:-1], "-", *_fill(consumer.closure, slots), *pins],
                          CLOSURE_SOURCE, COMPLETION_LIMIT, code + "CLOSURE_UNPROVED")
    if replayed is None:
        return completion
    return _encoded({"completion": base64.b64encode(completion).decode("ascii"),
                     "replay": base64.b64encode(replayed).decode("ascii")})


def dispatch(
    site: Site,
    work: Path,
    boot: str,
    claim: str,
    candidate_sha: str,
    authorization: str,
    admit_until: int,
    summary: bytes | None,
) -> str:
    """No replay, including if the guest previously lost the child result."""
    code = site.consumer.prefix + "_"
    _check(work, boot, claim)
    argv = read_argv(candidate_sha, authorization, admit_until, site)
    _require((summary is None) == (site.consumer.replay is None), code + "BAD_SUMMARY")
    _require(time.time() < admit_until, code + "ADMISSION_EXPIRED")
    _require(
        _matches(work / "placement-terminal", _decision(boot, claim, "placed")),
        code + "REQUIRES_CHECKED_PLACEMENT",
    )
    decision = work / "native-decision"
    _retain(decision, _decision(boot, claim, "dispatch"))
    # The summary is data: bounded explicit stdin, never argv or source.
    stdin = {"stdin": subprocess.DEVNULL} if summary is None else {"input": summary}
    with (work / "read.stdout").open("xb") as stdout, (work / "read.stderr").open("xb") as stderr:
        _require(time.time() < admit_until, code + "ADMISSION_EXPIRED")
        result = subprocess.run(argv, **stdin, stdout=stdout, stderr=stderr, check=False)
        stdout.flush()
        stderr.flush()
        os.fsync(stdout.fileno())
        os.fsync(stderr.fileno())
    # The installed successful entry awaits its owned control.shutdown
    # (m9_trial.execute_selection, change_review_advice.advise) before
    # returning. A nonzero or lost child result is deliberately not terminal
    # proof, even if SSH completed.
    if result.returncode != 0:
        return "unknown"
    out, err = _logs(site, work)
    _retain(work / "native-terminal", _terminal_record(boot, claim, out, err))
    return "joined"


def prove(site: Site, work: Path, boot: str, claim: str) -> str:
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
            original(site, work, boot, claim)
        except (OSError, ValueError):
            return "unknown"
        return "joined"
    return "fenced"


def _authority(site: Site, action: str, authorization: str, expected: str,
               candidate=None) -> bytes:
    read_argv(expected, authorization, 1, site)  # same fixed leaf and digest validation as dispatch
    argv = [*SERVICE, _AUTH_CODE, action, authorization, expected]
    if candidate is None:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, check=False)
    else:
        result = subprocess.run(argv, input=candidate, capture_output=True, check=False)
    _require(
        result.returncode == 0 and not result.stderr and len(result.stdout) <= 8192,
        site.consumer.prefix + "_AUTHORIZATION_PROOF_UNAVAILABLE",
    )
    return result.stdout


def place(
    site: Site,
    work: Path,
    boot: str,
    claim: str,
    expected: str,
    authorization: str,
    admit_until: int,
    candidate: bytes,
) -> str:
    code = site.consumer.prefix + "_"
    _check(work, boot, claim)
    read_argv(expected, authorization, admit_until, site)
    _require(
        0 < len(candidate) <= 8192 and hashlib.sha256(candidate).hexdigest() == expected,
        code + "BAD_CANDIDATE_BYTES",
    )
    _require(time.time() < admit_until, code + "ADMISSION_EXPIRED")
    _retain(work / "placement-decision", _decision(boot, claim, "place"))
    _require(
        not _authority(site, "fresh", authorization, expected, candidate),
        code + "AUTHORIZATION_FRESHNESS_UNPROVED",
    )
    file = work / "candidate"
    _retain(file, candidate)
    _require(time.time() < admit_until, code + "ADMISSION_EXPIRED")
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
        code + "AUTHORIZATION_INSTALL_UNPROVED",
    )
    _retain(work / "placement-terminal", _decision(boot, claim, "placed"))
    return "placed"


def discard(site: Site, work: Path, boot: str, claim: str, expected: str,
            authorization: str) -> str:
    """Fence a delayed placement before touching the leaf, or prove it joined."""
    code = site.consumer.prefix + "_"
    _check(work, boot, claim)
    read_argv(expected, authorization, 1, site)
    fence = _decision(boot, claim, "fenced")
    decision = work / "placement-decision"
    placed = False
    try:
        _retain(decision, fence)
    except FileExistsError:
        placed = _matches(decision, _decision(boot, claim, "place")) and _matches(
            work / "placement-terminal", _decision(boot, claim, "placed")
        )
        _require(placed or _matches(decision, fence), code + "AUTHORIZATION_PLACEMENT_UNRESOLVED")
    _require(prove(site, work, boot, claim) in ("joined", "fenced"),
             code + "NATIVE_STATE_UNRESOLVED")
    state = _authority(site, "inspect", authorization, expected)
    if state == b"present\n":
        _require(placed, code + "AUTHORIZATION_LEAF_NOT_OWNED")
        removed = subprocess.run(
            ["/usr/bin/sudo", "-n", "/usr/bin/rm", "--", authorization],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )
        _require(
            removed.returncode == 0 and not removed.stdout and not removed.stderr,
            code + "AUTHORIZATION_REMOVAL_UNPROVED",
        )
        state = _authority(site, "inspect", authorization, expected)
    _require(state == b"absent\n", code + "AUTHORIZATION_NOT_ABSENT")
    return "discarded"


def _site(args: argparse.Namespace) -> Site:
    consumer = CONSUMERS[args.consumer]
    located = (args.root, args.label, args.state)
    if consumer.site is not None:
        _require(located == (None, None, None), consumer.prefix + "_BAD_SITE")
        return Site(consumer, *consumer.site)
    _require(None not in located, consumer.prefix + "_BAD_SITE")
    return Site(consumer, *located)


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument(
        "action",
        choices=("dispatch", "prove", "original", "projection", "place", "readback", "discard"),
    )
    parser.add_argument("--boot", required=True)
    parser.add_argument("--claim", required=True)
    parser.add_argument("--consumer", choices=tuple(CONSUMERS), required=True)
    for name in ("root", "label", "state"):
        parser.add_argument("--" + name)
    parser.add_argument("--closure-pins", nargs="+")
    parser.add_argument("--summary-hex")
    parser.add_argument("--candidate-sha")
    parser.add_argument("--authorization")
    parser.add_argument("--admit-until", type=int)
    parser.add_argument("--candidate-hex")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        site = _site(args)
        code = site.consumer.prefix + "_"
        summary = None
        if args.summary_hex is not None:
            _require(
                site.consumer.replay is not None
                and args.action in ("dispatch", "projection")
                and re.fullmatch(rf"(?:[0-9a-f]{{2}}){{1,{SUMMARY_LIMIT}}}", args.summary_hex)
                is not None,
                code + "BAD_SUMMARY",
            )
            summary = bytes.fromhex(args.summary_hex)
        _require((args.closure_pins is not None) == (args.action == "projection"),
                 code + "CLOSURE_BAD_PINS")
        if args.action in ("prove", "original", "projection"):
            _require(
                args.candidate_sha is None
                and args.authorization is None
                and args.admit_until is None
                and args.candidate_hex is None,
                code + "BAD_PROOF_ARGUMENTS",
            )
            if args.action == "projection":
                sys.stdout.buffer.write(projection(site, Path.cwd(), args.boot, args.claim,
                                                   args.closure_pins, summary))
                return 0
            if args.action == "original":
                out, err = original(site, Path.cwd(), args.boot, args.claim)
                sys.stdout.buffer.write(_encoded({"boot": args.boot, "claim": args.claim,
                                                  "returncode": 0,
                                                  "stdout": base64.b64encode(out).decode("ascii"),
                                                  "stderr": base64.b64encode(err).decode("ascii")}))
                return 0
            state = prove(site, Path.cwd(), args.boot, args.claim)
        else:
            _require(
                args.candidate_sha is not None and args.authorization is not None,
                code + "MISSING_AUTHORIZATION_BINDING",
            )
            if args.action == "place":
                _require(
                    args.admit_until is not None
                    and args.candidate_hex is not None
                    and re.fullmatch(r"(?:[0-9a-f]{2}){1,8192}", args.candidate_hex) is not None,
                    code + "MISSING_PLACEMENT_BINDING",
                )
                state = place(
                    site,
                    Path.cwd(),
                    args.boot,
                    args.claim,
                    args.candidate_sha,
                    args.authorization,
                    args.admit_until,
                    bytes.fromhex(args.candidate_hex),
                )
            else:
                _require(args.candidate_hex is None, code + "UNEXPECTED_CANDIDATE")
                if args.action == "dispatch":
                    _require(args.admit_until is not None, code + "MISSING_DISPATCH_BINDING")
                    state = dispatch(
                        site,
                        Path.cwd(),
                        args.boot,
                        args.claim,
                        args.candidate_sha,
                        args.authorization,
                        args.admit_until,
                        summary,
                    )
                elif args.action == "discard":
                    state = discard(
                        site, Path.cwd(), args.boot, args.claim, args.candidate_sha,
                        args.authorization,
                    )
                else:
                    _check(Path.cwd(), args.boot, args.claim)
                    raw = _authority(site, "readback", args.authorization, args.candidate_sha)
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
