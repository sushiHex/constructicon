"""Execute the emitted guest packet in a new shell with a fake native child."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from scripts.ops import m9_read_closure, m9_read_transport
from scripts.ops.m9_read_closure import ClosurePins
from scripts.ops.m9_read_transport import StagedRead

from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_adapter import substituted_guard as substituted_guard
from tests.test_m9_read_closure import retained as retained
from tests.test_m9_read_closure import wire

BOOT = "01234567-89ab-cdef-0123-456789abcdef"
CLAIM = "1" * 64
CANDIDATE = b'{"candidate":"fixture"}\n'
ADMISSION = 2**40
AUTH = "/var/lib/constructicon-m8-launch/qualification/m9-live-1.json"


def bash():
    if os.name == "nt":
        path = Path(os.environ["PROGRAMFILES"]) / "Git/bin/bash.exe"
        if path.is_file():
            return str(path)
    executable = shutil.which("bash")
    if executable is None:
        pytest.skip("Bash is needed to execute the emitted guest phase")
    return executable


class Guest:
    def __init__(
        self,
        root,
        *,
        child_status=0,
        lose_reply=False,
        claim=CLAIM,
        candidate=CANDIDATE,
        install_status=0,
        closure_argv=None,
        original=b'{"replayed":false}\n',
        projection=b'{"projection":true}\n',
        admit_until=ADMISSION,
    ):
        self.root = root
        self.root.mkdir()
        self.child_status = child_status
        self.lose_reply = lose_reply
        self.events = []
        self.claim = claim
        self.candidate = candidate
        self.install_status = install_status
        self.closure_argv = closure_argv
        self.original = original
        self.projection = projection
        self.admit_until = admit_until

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        command = argv[-1]
        if "phase.sh" not in command or "/bin/bash" not in command:
            return subprocess.CompletedProcess(argv, 0)
        action = command.split("/bin/bash phase.sh ", 1)[1].split()[0]
        self.events.append(action)
        child = subprocess.run(
            [bash(), str(self.root / "phase.sh"), action],
            cwd=self.root,
            env=dict(os.environ, MSYS2_ARG_CONV_EXCL="*"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=10,
        )
        if action == "dispatch" and self.lose_reply:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        kwargs["stdout"].write(child.stdout)
        kwargs["stderr"].write(child.stderr)
        return subprocess.CompletedProcess(argv, child.returncode)

    def prepare(self, source: bytes):
        script = source.decode("utf-8")
        script = script.replace(
            "/usr/bin/python3 -I -S -B -",
            shlex.quote(Path(sys.executable).as_posix()) + " -I -S -B -",
            1,
        )
        # Only host-bound primitives are substituted. The real generated shell,
        # CLI dispatch, exclusive arbitration, and output receipts execute.
        injection = """
def _check(work, boot, claim):
    if boot != ${BOOT!r} or claim != ${CLAIM!r}:
        raise ValueError("fixture boot mismatch")

def fake_native(argv, **kw):
    candidate = ${CANDIDATE!r}
    expected_sha = hashlib.sha256(candidate).hexdigest()
    auth = ${AUTH!r}
    leaf = Path("fake-authority")
    if argv == read_argv(expected_sha, auth, ${ADMISSION!r}):
        if kw["stdin"] != subprocess.DEVNULL:
            raise ValueError("fixture native stdin mismatch")
        with Path("fake-call").open("xb") as f:
            f.write(b"invoked")
        kw["stdout"].write(${self.original!r})
        return subprocess.CompletedProcess(argv, ${self.child_status!r})
    if argv[:-3] == [*SERVICE, _AUTH_CODE] and argv[-2:] == [auth, expected_sha]:
        action = argv[-3]
        if action == "fresh":
            if leaf.exists() or kw["input"] != candidate:
                return subprocess.CompletedProcess(argv, 1, b"", b"bad fixture candidate")
            out = b""
        elif action == "readback":
            out = leaf.read_bytes()
        elif action == "inspect":
            out = b"present\\n" if leaf.exists() else b"absent\\n"
        else:
            raise ValueError("fixture unexpected authority operation")
        return subprocess.CompletedProcess(argv, 0, out, b"")
    if argv[:3] == ["/usr/bin/sudo", "-n", "/usr/bin/install"] and argv[-1] == auth:
        with leaf.open("xb") as f:
            f.write(Path(argv[-2]).read_bytes())
        return subprocess.CompletedProcess(argv, ${self.install_status!r}, b"", b"")
    if argv == ["/usr/bin/sudo", "-n", "/usr/bin/rm", "--", auth]:
        leaf.unlink()
        return subprocess.CompletedProcess(argv, 0, b"", b"")
    if ${self.closure_argv!r} is not None and argv == [*SERVICE[:-1], "-", *${self.closure_argv!r}]:
        if b"def accept_result(" not in kw["input"]:
            raise ValueError("fixture wrong closure source")
        return subprocess.CompletedProcess(argv, 0, ${self.projection!r}, b"")
    raise ValueError("fixture native argv mismatch")

subprocess.run = fake_native
"""
        values = {
            "BOOT": BOOT,
            "CLAIM": self.claim,
            "CANDIDATE": self.candidate,
            "AUTH": AUTH,
            "ADMISSION": self.admit_until,
            "self.child_status": self.child_status,
            "self.install_status": self.install_status,
            "self.closure_argv": self.closure_argv,
            "self.original": self.original,
            "self.projection": self.projection,
        }
        for key, value in values.items():
            injection = injection.replace("${" + key + "!r}", repr(value))
        if os.name == "nt":
            injection += """
os.O_NOFOLLOW = 0
os.O_NONBLOCK = 0
os.geteuid = lambda: Path.cwd().stat().st_uid
os.fsync = lambda fd: None
def _sync_directory(path):
    pass
"""
            script = script.replace(" and not info.st_mode & 0o077", "")
        start = 'if __name__ == "__main__":'
        assert script.count(start) == 1
        (self.root / "phase.sh").write_bytes(
            script.replace(start, injection + "\n" + start).encode()
        )


def staged(tmp_path, *, admit_until=ADMISSION, place=True, **guest_options):
    guest = Guest(tmp_path / "guest", **guest_options)
    captures = tmp_path / "captures"
    captures.mkdir()
    package = tmp_path / "package"
    read = StagedRead(
        package,
        "operator@192.0.2.1",
        "constructicon-test",
        BOOT,
        CLAIM,
        CANDIDATE,
        AUTH,
        admit_until,
    )
    guest.prepare((package / "phase.sh").read_bytes())
    cutoff = time.monotonic() + 120
    read.stage(captures, cutoff, run=guest)
    if place:
        read.place(captures, cutoff, run=guest)
        assert read.readback(captures, cutoff, run=guest) == CANDIDATE
    return read, guest, captures, cutoff


def test_lost_ssh_response_can_read_original_terminal_receipt(tmp_path):
    read, guest, captures, cutoff = staged(tmp_path, lose_reply=True)
    with pytest.raises(TimeoutError):
        read.dispatch(captures, cutoff, run=guest)
    assert json.loads((captures / "read-dispatch.status.json").read_bytes())["timed_out"] is True
    proof = read.prove(captures, cutoff, run=guest)
    assert proof is not None and proof.disposition == "terminal" and proof.challenge_sha256 == CLAIM
    assert read.original(captures, cutoff, run=guest) == (b'{"replayed":false}\n', b"")
    assert guest.events == ["place", "readback", "dispatch", "prove", "original"]
    assert (guest.root / "fake-call").read_bytes() == b"invoked"
    with pytest.raises(ValueError, match="M9_READ_ALREADY_ISSUED_OR_FENCED"):
        read.dispatch(captures, cutoff, run=guest)


def test_original_refuses_changed_guest_log_after_terminal_proof(tmp_path):
    read, guest, captures, cutoff = staged(tmp_path)
    with pytest.raises(ValueError, match="M9_READ_REQUIRES_TERMINAL_PROOF"):
        read.original(captures, cutoff, run=guest)
    read.dispatch(captures, cutoff, run=guest)
    proof = read.prove(captures, cutoff, run=guest)
    assert proof is not None and proof.disposition == "terminal"
    (guest.root / "read.stdout").write_bytes(b"changed\n")
    with pytest.raises(ValueError, match="M9_READ_ORIGINAL_UNPROVED"):
        read.original(captures, cutoff, run=guest)


def test_checked_phase_passes_projection_and_original_to_acceptance(tmp_path, monkeypatch):
    root = "/home/m8-service/m9-s1"
    attempt = root + "/fresh-attempt.json"
    pins = ClosurePins(
        "m9-live-1", "owner-read", "run-" + "2" * 32, *(["sha256:" + "3" * 64] * 5)
    )
    candidate = json.dumps({"authorization_id": "owner-read", "attempt_record": attempt}).encode()
    closure_argv = [root + "/trial", attempt, *vars(pins).values()]
    guest = Guest(tmp_path / "guest", candidate=candidate, closure_argv=closure_argv)
    package, captures = tmp_path / "package", tmp_path / "captures"
    captures.mkdir()
    read = StagedRead(package, "operator@192.0.2.1", "constructicon-test", BOOT, CLAIM,
                      candidate, AUTH, ADMISSION, pins)
    guest.prepare((package / "phase.sh").read_bytes())
    cutoff = time.monotonic() + 120
    read.stage(captures, cutoff, run=guest)
    read.place(captures, cutoff, run=guest)
    assert read.readback(captures, cutoff, run=guest) == candidate
    read.dispatch(captures, cutoff, run=guest)
    proof = read.prove(captures, cutoff, run=guest)
    assert proof is not None and proof.disposition == "terminal"

    def accept(actual, projection, stdout, stderr, rc):
        assert (actual, projection, stdout, stderr, rc) == (
            pins, b'{"projection":true}\n', b'{"replayed":false}\n', b"", 0,
        )
        return "5" * 64

    monkeypatch.setattr(m9_read_transport, "accept_result", accept)
    assert read.accept(captures, cutoff, run=guest) == "5" * 64


def test_fence_on_guest_refuses_late_dispatch(tmp_path):
    read, guest, captures, cutoff = staged(tmp_path)
    proof = read.prove(captures, cutoff, run=guest)
    assert proof is not None and proof.disposition == "fenced"
    child = subprocess.run(
        [bash(), str(guest.root / "phase.sh"), "dispatch"],
        cwd=guest.root,
        env=dict(os.environ, MSYS2_ARG_CONV_EXCL="*"),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert child.returncode == 1 and json.loads(child.stdout) == {"state": "unknown"}
    assert not (guest.root / "fake-call").exists()


def test_nonzero_child_is_not_remote_completion_proof(tmp_path):
    read, guest, captures, cutoff = staged(tmp_path, child_status=1)
    with pytest.raises(ValueError):
        read.dispatch(captures, cutoff, run=guest)
    assert read.prove(captures, cutoff, run=guest) is None
    assert (guest.root / "fake-call").is_file()
    assert not (guest.root / "native-terminal").exists()


def test_guest_admission_expiry_is_checked_before_claim(tmp_path):
    read, guest, captures, cutoff = staged(tmp_path, admit_until=1, place=False)
    child = subprocess.run(
        [bash(), str(guest.root / "phase.sh"), "dispatch"],
        cwd=guest.root,
        env=dict(os.environ, MSYS2_ARG_CONV_EXCL="*"),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert child.returncode == 1
    assert not (guest.root / "native-decision").exists()
    assert not (guest.root / "fake-call").exists()
    proof = read.prove(captures, cutoff, run=guest)
    assert proof is not None and proof.disposition == "fenced"


def test_supervisor_closes_window_with_real_generated_transport_after_lost_response(
    tmp_path, retained, monkeypatch,
):
    pins, _, attempt, journal, original = retained
    replayed = original["status"] == "baseline-no-promotion"
    original_wire = wire({**original, "replayed": replayed})
    projection = wire(
        m9_read_closure.project(pins, journal, attempt.read_bytes(), next_present=False)
    )
    root = "/home/m8-service/m9-s1"
    attempt_path = root + "/fresh-attempt.json"
    candidate_bytes = json.dumps(
        {"authorization_id": pins.authorization_id, "attempt_record": attempt_path}
    ).encode()
    closure_argv = [root + "/trial", attempt_path, *vars(pins).values()]

    from datetime import UTC, datetime, timedelta
    from hashlib import sha256
    from types import SimpleNamespace

    from scripts.ops.m9_native_read import run_native_read
    from scripts.ops.m9_owner_approval import ManualApproval
    from scripts.ops.m9_read_window import Qualification, WindowLimits

    events = []
    now = datetime.now(UTC)
    qualification = Qualification(
        "a" * 64, b"checked-packet", candidate_bytes,
        now + timedelta(minutes=10), time.monotonic() + 600,
    )
    bound = SimpleNamespace(
        qualification=qualification, target="operator@192.0.2.1", alias="constructicon-test",
        boot=BOOT, authorization=AUTH, closure=pins,
    )

    class Host:
        def qualify(self, cutoff):
            return bound

        def check_live(self, qualified, cutoff):
            assert qualified is bound
            return True

        def withdraw(self, qualified, cutoff):
            assert qualified is bound
            events.append("withdraw")
            return "c" * 64

        def park(self, cutoff):
            events.append("park")

        def check_park(self, cutoff):
            events.append("check-park")
            return "c" * 64

    exchange = tmp_path / "exchange"
    exchange.mkdir()
    approvals = []

    def approve_on_poll(_seconds):
        packets = list(exchange.iterdir())
        assert len(packets) == 1
        packet = packets[0]
        challenge = (packet / "challenge.json").read_bytes()
        assert packet.name == sha256(challenge).hexdigest()
        assert (packet / "pins.json").read_bytes() == qualification.pins
        approval = {"decision": "approve", "challenge_sha256": packet.name}
        (packet / "approval.json").write_text(json.dumps(approval), encoding="utf-8")
        approvals.append(approval)

    monkeypatch.setattr(time, "sleep", approve_on_poll)

    guest = None

    def fake_host(argv, **kwargs):
        nonlocal guest
        if "phase.sh" not in argv[-1] or "/bin/bash" not in argv[-1]:
            return subprocess.CompletedProcess(argv, 0)
        if guest is None:
            package = next(tmp_path.glob("native-*/package"))
            binding = json.loads((package / "bindings.json").read_bytes())
            guest = Guest(
                tmp_path / "guest", lose_reply=True, claim=binding["claim"],
                candidate=candidate_bytes, closure_argv=closure_argv,
                original=original_wire, projection=projection,
                admit_until=binding["admit_until"],
            )
            guest.prepare((package / "phase.sh").read_bytes())
        return guest(argv, **kwargs)

    limits = WindowLimits(window=300, qualify=10, placement=60, dispatch=30, proof=30,
                          close=60, withdraw=10, park=10)
    result = run_native_read(tmp_path, Host(), ManualApproval(exchange), limits, run=fake_host)
    assert (result.reason, result.dispatch, result.cleanup, result.custody_retained) == (
        "read-settled", "terminal", "clean", False,
    )
    if replayed:
        assert result.accepted_read_sha256 is None
    else:
        assert result.accepted_read_sha256 == m9_read_closure.accept_result(
            pins, projection, original_wire, b"", 0
        )
    assert len(approvals) == 1
    assert guest is not None
    assert guest.events == ["place", "readback", "dispatch", "prove", "original",
                            "projection", "discard"]
    assert (guest.root / "fake-call").read_bytes() == b"invoked"
    assert events == ["withdraw", "park", "check-park"]
    recorded = json.loads((result.record / "result.json").read_bytes())
    assert recorded["dispatch_transport"] == "raised"


def test_unproved_placement_blocks_discard_and_dispatch(tmp_path):
    read, guest, captures, cutoff = staged(tmp_path, place=False, install_status=1)
    with pytest.raises(ValueError, match="M9_READ_PLACE_UNPROVED"):
        read.place(captures, cutoff, run=guest)
    with pytest.raises(ValueError, match="M9_READ_REQUIRES_CHECKED_PLACEMENT"):
        read.dispatch(captures, cutoff, run=guest)
    with pytest.raises(ValueError, match="M9_READ_DISCARD_UNPROVED"):
        read.discard(captures, cutoff, run=guest)
    assert (guest.root / "fake-authority").is_file()
    assert not (guest.root / "fake-call").exists()


def test_placement_fence_does_not_remove_a_preexisting_authorization(tmp_path):
    read, guest, captures, cutoff = staged(tmp_path, place=False)
    preexisting = guest.root / "fake-authority"
    preexisting.write_bytes(CANDIDATE)
    with pytest.raises(ValueError, match="M9_READ_DISCARD_UNPROVED"):
        read.discard(captures, cutoff, run=guest)
    assert preexisting.read_bytes() == CANDIDATE
