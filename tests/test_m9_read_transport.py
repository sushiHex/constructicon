"""Execute the emitted guest packet in a new shell with a fake native child."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from hashlib import sha256
from pathlib import Path

import pytest
from scripts.ops.m9_read_transport import StagedRead

from tests.test_m9_read_window import Fake

BOOT = "01234567-89ab-cdef-0123-456789abcdef"
CLAIM = "1" * 64
CANDIDATE = "2" * 64
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
    def __init__(self, root, *, child_status=0, lose_reply=False, claim=CLAIM, candidate=CANDIDATE):
        self.root = root
        self.root.mkdir()
        self.child_status = child_status
        self.lose_reply = lose_reply
        self.events = []
        self.claim = claim
        self.candidate = candidate

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
    expected = read_argv(${CANDIDATE!r}, ${AUTH!r}, ${ADMISSION!r})
    if argv != expected or kw["stdin"] != subprocess.DEVNULL:
        raise ValueError("fixture native argv mismatch")
    with Path("fake-call").open("xb") as f:
        f.write(b"invoked")
    kw["stdout"].write(b'{"replayed":false}\\n')
    return subprocess.CompletedProcess(argv, ${self.child_status!r})

subprocess.run = fake_native
"""
        values = {
            "BOOT": BOOT,
            "CLAIM": self.claim,
            "CANDIDATE": self.candidate,
            "AUTH": AUTH,
            "ADMISSION": ADMISSION,
            "self.child_status": self.child_status,
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


def staged(tmp_path, *, admit_until=ADMISSION, **guest_options):
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
    return read, guest, captures, cutoff


def test_lost_ssh_response_can_read_original_terminal_receipt(tmp_path):
    read, guest, captures, cutoff = staged(tmp_path, lose_reply=True)
    read.dispatch(captures, cutoff, run=guest)
    assert json.loads((captures / "read-dispatch.status.json").read_bytes())["timed_out"] is True
    proof = read.prove(captures, cutoff, run=guest)
    assert proof is not None and proof.disposition == "terminal" and proof.challenge_sha256 == CLAIM
    assert guest.events == ["dispatch", "prove"]
    assert (guest.root / "fake-call").read_bytes() == b"invoked"
    with pytest.raises(ValueError, match="M9_READ_ALREADY_ISSUED_OR_FENCED"):
        read.dispatch(captures, cutoff, run=guest)


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
    read.dispatch(captures, cutoff, run=guest)
    assert read.prove(captures, cutoff, run=guest) is None
    assert (guest.root / "fake-call").is_file()
    assert not (guest.root / "native-terminal").exists()


def test_guest_admission_expiry_is_checked_before_claim(tmp_path):
    read, guest, captures, cutoff = staged(tmp_path, admit_until=1)
    read.dispatch(captures, cutoff, run=guest)
    assert not (guest.root / "native-decision").exists()
    assert not (guest.root / "fake-call").exists()
    proof = read.prove(captures, cutoff, run=guest)
    assert proof is not None and proof.disposition == "fenced"


def test_supervisor_closes_window_with_real_generated_transport_after_lost_response(tmp_path):
    class Composed(Fake):
        def place(self, qualification, cutoff):
            super().place(qualification, cutoff)
            candidate = sha256(qualification.candidate).hexdigest()
            self.guest = Guest(
                tmp_path / "guest", lose_reply=True, claim=self.challenge_sha, candidate=candidate
            )
            self.captures = tmp_path / "captures"
            self.captures.mkdir()
            package = tmp_path / "package"
            self.read = StagedRead(
                package,
                "operator@192.0.2.1",
                "constructicon-test",
                BOOT,
                self.challenge_sha,
                candidate,
                AUTH,
                ADMISSION,
            )
            self.guest.prepare((package / "phase.sh").read_bytes())
            self.transport_cutoff = time.monotonic() + 120
            self.read.stage(self.captures, self.transport_cutoff, run=self.guest)

        def dispatch(self, qualification, cutoff):
            super().dispatch(qualification, cutoff)
            self.read.dispatch(self.captures, self.transport_cutoff, run=self.guest)

        def prove_remote(self, qualification, challenge_sha256, cutoff):
            self.event("prove-remote", cutoff)
            return self.read.prove(self.captures, self.transport_cutoff, run=self.guest)

    fake = Composed(tmp_path)
    result = fake.run()
    assert (
        result.dispatch == "terminal" and result.cleanup == "clean" and not result.custody_retained
    )
    assert fake.native_calls == 1 and fake.guest.events == ["dispatch", "prove"]
    assert fake.names[-5:] == ["prove-remote", "close", "withdraw", "park", "check-park"]
