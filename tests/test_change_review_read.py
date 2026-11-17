"""The change-review advice READ through the real supervisor chain, offline.

``QualificationBoundary`` -> ``run_native_read`` -> ``run_window`` with the
real advice pins, mint and run producers (``change_review_advice.main``), the
real generated guest shell executed by Bash, the real guest command and the
real closure program. Only the external transport and platform are fakes:
SSH/SCP/PowerShell are a closed twin, guest privilege and root custody are a
closed fake inside the guest program, the Codex peer is the adapter suite's
scripted byte peer, and Linux service paths map onto one private directory.
The guest's service child is relayed back to this process (where the scripted
peer lives) over a loopback socket, so the argv and stdin the guest actually
emits are what the entry receives.

Nothing here proves the Linux host, sudo, root custody, a real model or cost.
"""

from __future__ import annotations

import base64
import collections
import io
import json
import os
import shlex
import socket
import subprocess
import sys
import time
import types
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.ops import m9_owner_approval as owner
from scripts.ops import m9_qualification_boundary as boundary
from scripts.ops import m9_read_closure as closure
from scripts.ops import m9_read_command as command
from scripts.ops.claude_read_session import json_bytes
from scripts.ops.m9_native_read import run_native_read
from scripts.ops.m9_owner_approval import StandingApproval
from scripts.ops.m9_read_window import WindowLimits

from constructicon.api import change_review_advice as route
from constructicon.core.qualification import QualificationAuthorization
from constructicon.substrate.executors import codex_lane, operator_store, qualification
from tests.api.test_change_review_advice import DEMO, provider, turns
from tests.substrate import test_codex_adapter as adapter
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_adapter import substituted_guard as substituted_guard
from tests.substrate.test_codex_protocol import completed
from tests.test_m8_helper_contracts import fixture_contract
from tests.test_m9_owner_approval import forbid_supervisor_sleep
from tests.test_m9_qualification_boundary import ALIAS, BOOT, D2, PRIOR, RUNTIME, TARGET
from tests.test_m9_read_transport import bash

HOME = "/home/m8-service/"
ROOT = HOME + "advice-codex-g12"
LABEL = "g12"
STATE = HOME + "advice-s1"
AUTH_ID = "advice-read-1"
AUTH = command.AUTH_PARENT + "/" + AUTH_ID + ".json"
JOURNAL = STATE + "/" + AUTH_ID + ".sqlite"
ATTEMPT = STATE + "/" + AUTH_ID + ".attempt"
SUMMARY = (json.dumps(DEMO.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
           + "\n").encode("utf-8")
OUTPUT = b"fixture exact phase output\n"
LIMITS = WindowLimits(window=600, qualify=120, placement=120, dispatch=120, proof=60,
                      close=120, withdraw=30, park=30)


def selection(root: Path, *, summary: bytes = SUMMARY, target: str = TARGET, alias: str = ALIAS,
              **consumer) -> tuple[Path, str]:
    """A schema 3 selection: the shared twelve, then consumer-pins and consumer-mint."""
    bound = route.bound_values(DEMO)
    phases, contracts = {}, {}
    body, contract = fixture_contract(root)
    for phase in (*boundary.SHARED_PHASES, *command.ADVICE.phases, boundary.CLEANUP):
        raw = (f"# fixture template {phase}\nreadonly M9_BOOT=UNREVIEWED\n"
               f'test "$M9_BOOT" = {BOOT} || exit 3\n'
               "printf 'fixture exact phase output\\n'\n").encode()
        if phase in ("d2-preserve", "d2-verify"):
            raw = boundary._d2_script({
                "EXPECTED_BOOT": BOOT, "__d2_commit": D2["revision"],
                "__d2_workspace": D2["workspace"], "__drift_sha256": D2["drift_sha256"],
                "__drift_hex": D2["drift_hex"],
            }, phase).replace(BOOT.encode(), b"UNREVIEWED")
        if phase == "preflight-custody-floor":
            raw = body
        (root / (phase + ".sh")).write_bytes(raw)
        phases[phase] = {"script": sha256(raw).hexdigest()}
        contracts[phase] = [contract] if phase == "preflight-custody-floor" else []
        if phase not in {*command.ADVICE.phases, boundary.CLEANUP}:
            phases[phase]["stdout"] = sha256(OUTPUT).hexdigest()
    phases["h7-with-authorized-h8"]["stdout"] = [
        sha256(b"fixture alternative H7 receipt\n").hexdigest(), sha256(OUTPUT).hexdigest(),
    ]
    (root / "summary.json").write_bytes(summary)
    raw = json_bytes({
        "schema_version": 3, "target": target, "alias": alias, "previous_boot": PRIOR,
        "controller": "0" * 40, "d2": D2, "runtime": RUNTIME, "previous_generation": 11,
        "authorization_id": AUTH_ID, "phases": phases, "helper_contracts": contracts,
        "consumer": {
            "id": "change-review-advice", "source_graph": str(bound.source_graph_hash),
            "component": str(bound.component), "guard": str(route.guard_revision()),
            "summary_sha256": sha256(SUMMARY).hexdigest(),
            "instruction_digest": str(bound.instruction_digest),
            "session": {"root": ROOT, "label": LABEL}, "state": STATE, **consumer,
        },
    })
    path = root / "selection.json"
    path.write_bytes(raw)
    return path, sha256(raw).hexdigest()


# The fake guest privilege layer: root custody is one local leaf; the service
# child is relayed to the test process. Every other native argv refuses.
INJECTION = '''
import socket as _socket

def _check(work, boot, claim):
    if boot != BOOT_VALUE or claim != CLAIM_VALUE:
        raise ValueError("fixture boot mismatch")

def _log(name):
    with open("fake-calls", "a", encoding="ascii") as stream:
        stream.write(name + "\\n")

def _relay(argv, data):
    with _socket.create_connection(("127.0.0.1", PORT_VALUE), timeout=120) as conn:
        conn.sendall(json.dumps({"argv": argv, "input": None if data is None else data.hex()})
                     .encode("ascii"))
        conn.shutdown(_socket.SHUT_WR)
        reply = b""
        while chunk := conn.recv(65536):
            reply += chunk
    reply = json.loads(reply)
    return bytes.fromhex(reply["stdout"]), bytes.fromhex(reply["stderr"]), reply["rc"]

def fake_native(argv, **kw):
    auth = AUTH_VALUE
    leaf = Path("fake-authority")
    if argv[:-3] == [*SERVICE, _AUTH_CODE] and argv[-2] == auth:
        action, expected = argv[-3], argv[-1]
        _log("authority-" + action)
        if action == "fresh":
            if leaf.exists() or hashlib.sha256(kw["input"]).hexdigest() != expected:
                return subprocess.CompletedProcess(argv, 1, b"", b"fixture refused")
            out = b""
        elif action == "readback":
            out = leaf.read_bytes()
        elif action == "inspect":
            out = b"present\\n" if leaf.exists() else b"absent\\n"
        else:
            raise ValueError("fixture unexpected authority operation")
        return subprocess.CompletedProcess(argv, 0, out, b"")
    if argv[:3] == ["/usr/bin/sudo", "-n", "/usr/bin/install"] and argv[-1] == auth:
        _log("install")
        with leaf.open("xb") as stream:
            stream.write(Path(argv[-2]).read_bytes())
        return subprocess.CompletedProcess(argv, 0, b"", b"")
    if argv == ["/usr/bin/sudo", "-n", "/usr/bin/rm", "--", auth]:
        _log("rm")
        leaf.unlink()
        return subprocess.CompletedProcess(argv, 0, b"", b"")
    if argv[:len(SERVICE) - 1] == list(SERVICE[:-1]) and argv[len(SERVICE) - 1] in ("-c", "-"):
        _log("service")
        out, err, rc = _relay(argv, kw.get("input"))
        if hasattr(kw.get("stdout"), "write"):
            kw["stdout"].write(out)
            kw["stderr"].write(err)
            return subprocess.CompletedProcess(argv, rc)
        return subprocess.CompletedProcess(argv, rc, out, err)
    raise ValueError("fixture native argv mismatch")

subprocess.run = fake_native
'''
WINDOWS = '''
os.O_NOFOLLOW = 0
os.O_NONBLOCK = 0
os.geteuid = lambda: Path.cwd().stat().st_uid
os.fsync = lambda fd: None
def _sync_directory(path):
    pass
'''


class _Stdin:
    def __init__(self, data: bytes) -> None:
        self.buffer = io.BytesIO(data)


class Platform:
    """One closed fake platform: every external call has exactly one class."""

    def __init__(self, tmp_path, monkeypatch, binding, *, answer="Test the empty input.",
                 lose=False, occupy=None, crlf=None, drift=None):
        self.tmp, self.monkeypatch, self.binding = tmp_path, monkeypatch, binding
        self.home = (tmp_path / "guest-home").resolve()
        self.home.mkdir()
        (self.home / Path(ROOT).name).mkdir()
        (self.home / Path(STATE).name).mkdir()
        self.custody = (tmp_path / "custody")
        self.custody.mkdir(mode=0o700)
        self.guest = tmp_path / "guest"
        self.native = adapter.clean_native(records=[completed(answer=answer)])
        self.idle = []
        self.lose, self.occupy, self.crlf, self.drift = lose, occupy, crlf, drift
        self.counts = collections.Counter()
        self.staged = {}
        self.claimed = set()
        self.live_probes = 0
        self.server = socket.create_server(("127.0.0.1", 0))
        self.server.settimeout(0.05)
        monkeypatch.setattr(route, "operator_provider", self.assemble)
        monkeypatch.setattr(route, "read_authorization", self.permit)
        monkeypatch.setattr(qualification, "_read_authorization_bytes", self.permit_bytes)
        if occupy == "journal-before-mint":
            Path(self.local(JOURNAL)).write_bytes(b"occupied")

    # --- the Linux locator translation, the only path substitution ------------

    def local(self, value: str) -> str:
        return str(self.home / value[len(HOME):]) if value.startswith(HOME) else value

    def linux(self, value: str) -> str:
        prefix = str(self.home) + os.sep
        assert value.startswith(prefix)
        return HOME + value[len(prefix):].replace(os.sep, "/")

    # --- host assembly, substituted by its credential-free twin ---------------

    def assemble(self, host, authorization):
        assert (host.session, host.sealed, host.qualification, host.state, host.store_key) == (
            Path(self.local(ROOT)), Path(self.local(f"{ROOT}/{LABEL}.sealed.json")),
            Path(self.local(ROOT + "/s6a-qualification.json")), Path(self.local(STATE)),
            "n4-codex-pro",
        )
        if authorization is None:
            self.idle.append(adapter.clean_native(records=[]))
            return provider(self.tmp, self.binding, self.idle[-1])
        self.counts["host-assembly-permitted"] += 1
        assembled = provider(self.tmp, self.binding, self.native)
        assembled.qualification = authorization  # exactly the placed permit
        return assembled

    def permit_bytes(self, path):
        assert path.as_posix() == AUTH
        return (self.guest / "fake-authority").read_bytes()

    def permit(self, path):
        assert path.as_posix() == AUTH
        placed = QualificationAuthorization.model_validate_json(self.permit_bytes(path))
        return placed.model_copy(update={
            "journal": self.local(placed.journal),
            "attempt_record": self.local(placed.attempt_record),
        })

    # --- in-process programs, run on the actual emitted argv ------------------

    def program(self, code: str, argv: list[str], data: bytes | None, *, name="__main__"):
        out, err = io.StringIO(), io.StringIO()
        saved = sys.argv, sys.path[:], sys.stdin
        sys.argv, sys.stdin = ["-c", *[self.local(item) for item in argv]], _Stdin(data or b"")
        rc = 0
        try:
            with redirect_stdout(out), redirect_stderr(err):
                exec(compile(code, "relayed-program", "exec"), {"__name__": name})
        except SystemExit as stop:
            rc = stop.code if type(stop.code) is int else 1
            if type(stop.code) is str:
                err.write(stop.code)
        finally:
            sys.argv, sys.path[:], sys.stdin = saved[0], saved[1], saved[2]
        return out.getvalue().encode("utf-8"), err.getvalue().encode("utf-8"), rc

    def serve(self, request: dict) -> tuple[bytes, bytes, int]:
        argv, data = request["argv"], request["input"]
        data = None if data is None else bytes.fromhex(data)
        n = len(command.SERVICE)
        assert argv[:n - 1] == list(command.SERVICE[:-1])
        if argv[n - 1] == "-":
            self.counts["guest-closure"] += 1
            assert b"def accept_replay(" in data  # the embedded closure source
            module = types.ModuleType("relayed_closure")
            self.monkeypatch.setitem(sys.modules, module.__name__, module)
            namespace = module.__dict__
            exec(compile(data.decode("utf-8"), "relayed-closure", "exec"), namespace)
            if os.name == "nt":
                # Windows cannot reproduce the Linux no-follow, uid and 0600 contract.
                namespace["_read_attempt"] = lambda path: path.read_bytes()
            stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
            err = io.StringIO()
            saved = sys.stdout
            sys.stdout = stdout
            try:
                with redirect_stderr(err):
                    rc = namespace["main"]([self.local(item) for item in argv[n:]])
            finally:
                sys.stdout = saved
            stdout.flush()
            return stdout.buffer.getvalue(), err.getvalue().encode(), rc
        code = argv[n]
        assert data == SUMMARY, "the summary reaches the entry as exact stdin"
        if code == command._code(command._SERVICE_CODE, command.ADVICE):
            self.counts["guest-dispatch"] += 1
        else:
            assert code == command._code(command._REPLAY_CODE, command.ADVICE)
            assert "--authorization" not in argv
            self.counts["guest-replay"] += 1
        return self.program(code, argv[n + 1:], data)

    def run_guest(self, action, argv, kwargs):
        if not self.guest.exists():
            self.prepare(next(self.custody.glob("native-*/package")))
        with (self.guest / f"{action}.out").open("wb") as out, \
                (self.guest / f"{action}.err").open("wb") as err:
            child = subprocess.Popen([bash(), str(self.guest / "phase.sh"), action],
                                     cwd=self.guest, stdin=subprocess.DEVNULL, stdout=out,
                                     stderr=err, env=dict(os.environ, MSYS2_ARG_CONV_EXCL="*"))
            deadline = time.monotonic() + 120
            while child.poll() is None:
                assert time.monotonic() < deadline, "the guest program did not finish"
                try:
                    conn, _ = self.server.accept()
                except TimeoutError:
                    continue
                with conn:
                    conn.settimeout(120)
                    raw = b""
                    while chunk := conn.recv(65536):
                        raw += chunk
                    out_raw, err_raw, rc = self.serve(json.loads(raw))
                    conn.sendall(json.dumps({"stdout": out_raw.hex(), "stderr": err_raw.hex(),
                                             "rc": rc}).encode("ascii"))
        if action == "dispatch" and self.lose:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        kwargs["stdout"].write((self.guest / f"{action}.out").read_bytes())
        kwargs["stderr"].write((self.guest / f"{action}.err").read_bytes())
        return subprocess.CompletedProcess(argv, child.returncode)

    def prepare(self, package: Path) -> None:
        binding = json.loads((package / "bindings.json").read_bytes())
        self.guest.mkdir()
        if self.occupy == "permit-leaf":
            (self.guest / "fake-authority").write_bytes(b"someone else's permit\n")
        script = (package / "phase.sh").read_bytes().decode("utf-8").replace(
            "/usr/bin/python3 -I -S -B -",
            shlex.quote(Path(sys.executable).as_posix()) + " -I -S -B -", 1,
        )
        self.port = self.server.getsockname()[1]
        injection = INJECTION
        for key, value in (("BOOT_VALUE", BOOT), ("CLAIM_VALUE", binding["claim"]),
                           ("AUTH_VALUE", AUTH), ("PORT_VALUE", self.port)):
            injection = injection.replace(key, repr(value))
        if os.name == "nt":
            injection += WINDOWS
            script = script.replace(" and not info.st_mode & 0o077", "")
        start = 'if __name__ == "__main__":'
        assert script.count(start) == 1
        (self.guest / "phase.sh").write_bytes(script.replace(start, injection + "\n" + start)
                                              .encode("utf-8"))

    # --- the selected qualification phases' producers -------------------------

    def entry(self, *argv: str) -> tuple[bytes, int]:
        out, err, rc = self.program(
            "import sys\nfrom constructicon.api.change_review_advice import main\n"
            "raise SystemExit(main(sys.argv[1:]))\n",
            ["--summary", str(self.tmp / "summary.json"), *argv], None,
        )
        assert not err
        return out, rc

    def host_metadata(self) -> list[str]:
        return ["--session", ROOT, "--store-key", "n4-codex-pro",
                "--sealed", f"{ROOT}/{LABEL}.sealed.json",
                "--qualification", ROOT + "/s6a-qualification.json", "--state", STATE]

    def phase_output(self, phase: str) -> tuple[bytes, int]:
        if phase == "consumer-pins":
            out, rc = self.entry("--stage", "pins", *self.host_metadata())
            if self.drift == "component":
                record = json.loads(out)
                record["component"] = "sha256:" + "f" * 64
                out = json_bytes(record)
        elif phase == "consumer-mint":
            out, rc = self.entry("--stage", "mint", *self.host_metadata(), "--journal", JOURNAL,
                                 "--attempt-record", ATTEMPT, "--authorization-id", AUTH_ID)
            if rc == 0:
                # Translate only the platform-specific Linux locators back.
                minted = QualificationAuthorization.model_validate_json(out)
                out = json_bytes(minted.model_copy(update={
                    "journal": self.linux(minted.journal),
                    "attempt_record": self.linux(minted.attempt_record),
                }).model_dump(mode="json"))
        elif phase == boundary.CLEANUP:
            return b"codex-withdrawn-floor-12\n", 0
        else:
            return OUTPUT, 0
        if self.crlf == phase:
            out = out.replace(b"\n", b"\r\n")  # a Windows print() of the same record
        return out, rc

    def live(self, command_text: str) -> tuple[bytes, bytes, int]:
        self.live_probes += 1
        if self.occupy == "attempt-before-placement" and self.live_probes == 2:
            Path(self.local(ATTEMPT)).write_bytes(b"spent elsewhere")
        parts = shlex.split(command_text.split(" && ", 1)[1])
        n = len(command.SERVICE)
        assert parts[:n] == list(command.SERVICE) and parts[n] == boundary._ADVICE_LIVE
        store = self.binding[1].sealed

        class Store:
            def __init__(self, root, key, identity):
                assert key == "n4-codex-pro" and identity is store

            def open_candidate(self):
                return "opened"

            def _check_selection(self, opened):
                return SimpleNamespace(generation=12)

            def close_candidate(self, opened):
                pass

        with self.monkeypatch.context() as patch:
            patch.setattr(operator_store, "_sealed_file", lambda path, uid: store)
            patch.setattr(operator_store, "BindingStore", Store)
            patch.setattr(codex_lane, "_launcher",
                          lambda root: SimpleNamespace(expected_runtime=RUNTIME))
            patch.setattr(os, "getuid", lambda: 1000, raising=False)
            return self.program(parts[n], parts[n + 1:], None)

    # --- the closed external dispatch ------------------------------------------

    def __call__(self, argv, **kwargs):
        assert kwargs["stdin"] == subprocess.DEVNULL and kwargs["shell"] is False
        argv = list(argv)
        text = argv[-1]
        classes = [name for name, hit in {
            "scp": argv[0] == boundary.transport.SCP,
            "ssh-boot": text.startswith("/usr/bin/cat "),
            "ssh-preflight": "ok=u!=0 and h==h.resolve(strict=True)" in text,
            "ssh-mkdir": "umask 077;test ! -e" in text,
            "ssh-cleanup-hash": 'cd "$HOME/m9-qual-' in text and "/bin/bash phase.sh" not in text,
            "ssh-qualification-phase":
                'cd "$HOME/m9-qual-' in text and "/bin/bash phase.sh" in text,
            "ssh-guest-read": 'cd "$HOME/m9-read-' in text and "/bin/bash phase.sh " in text,
            "ssh-d2-readback": "/d2-records/lr2.out" in text,
            "ssh-live": "ACTIVE_BINDING_OR_STATE_DRIFT" in text,
            "ssh-withdrawal": "WITHDRAWAL_LOCK_UNAVAILABLE" in text,
            "ssh-park-boot": text == f'test "$(/usr/bin/cat {boundary._BOOT_FILE})" = {BOOT}',
            "powershell-park": "Stop-VM" in text,
            "powershell-usage": text == boundary.m8_vm_usage.QUERY,
        }.items() if hit]
        assert len(classes) == 1, f"unclassified or ambiguous external call: {classes}"
        kind = classes[0]
        self.counts[kind] += 1
        raw, rc = b"", 0
        if kind == "scp":
            remote = text.split(":", 1)[1].strip("/")
            assert remote in self.claimed and remote not in self.staged
            self.staged[remote] = Path(argv[-3]).parent.name
        elif kind == "ssh-mkdir":
            names = {part for part in text.split('"') if part.startswith("$HOME/")}
            self.claimed.add(names.pop().removeprefix("$HOME/"))
        elif kind == "ssh-boot":
            raw = (BOOT + "\n").encode()
        elif kind == "ssh-qualification-phase":
            remote = text.split('cd "$HOME/', 1)[1].split('"', 1)[0]
            raw, rc = self.phase_output(self.staged[remote])
        elif kind == "ssh-guest-read":
            action = text.split("/bin/bash phase.sh ", 1)[1].split()[0]
            return self.run_guest(action, argv, kwargs)
        elif kind == "ssh-d2-readback":
            raw = ((BOOT + "\nverify exit 0\n").encode() + json_bytes({
                "command": "verify", "commit": D2["revision"], "first_parent": True,
                "script_matches_commit": True, "installed": True,
            }) + b"probe exit 0\n" + json_bytes({
                "qualified": True, "commit": D2["revision"],
                "scope": "runner_prerequisites_only", "production_available": False,
            }))
        elif kind == "ssh-live":
            raw, err, rc = self.live(text)
            kwargs["stderr"].write(err)
        elif kind == "ssh-withdrawal":
            raw = json_bytes({"key": boundary.STORE_KEY, "generation_floor": 12})
        elif kind == "powershell-usage":
            raw = json_bytes({"name": "constructicon-m8", "state": "Off", "operational": ["Ok"],
                              "uptime_seconds": 0, "checkpoints": 0, "vmconnect": 0})
        kwargs["stdout"].write(raw)
        return subprocess.CompletedProcess(argv, rc)

    def guest_calls(self) -> collections.Counter:
        log = self.guest / "fake-calls"
        return collections.Counter(log.read_text("ascii").split() if log.exists() else [])

    def window(self, path: Path, digest: str, *, target: str = TARGET, record=None):
        host = boundary.QualificationBoundary(path, digest, self.tmp / "work", target=target,
                                              alias=ALIAS, run=self)
        if record is None:
            # The owner's issuance, from the reviewed selection, before the window.
            record = issued(self.custody, host.selected_pins())
        self.record = record
        approval = StandingApproval.load(*record, self.custody)

        forbid_supervisor_sleep(self.monkeypatch)
        try:
            result = run_native_read(self.custody, host, approval, LIMITS, run=self)
        finally:
            self.server.close()
        self.approval = approval
        challenge = result.record / "challenge.json"
        self.challenge = json.loads(challenge.read_bytes()) if challenge.exists() else None
        return host, result

    def turns(self) -> int:
        return len(turns(self.native)) + sum(len(turns(native)) for native in self.idle)


def world(tmp_path, monkeypatch, binding, **options):
    platform = Platform(tmp_path, monkeypatch, binding, **options)
    path, digest = selection(tmp_path)
    return platform, path, digest


def issued(custody: Path, selected: dict, *, days: float = 7, changes=None,
           name: str = "standing-approval.json") -> tuple[Path, str]:
    """A standing record from the issuance helper, placed in custody."""
    not_after = datetime.now(UTC).replace(microsecond=0) + timedelta(days=days)
    raw = owner.issue(selected, not_after=not_after, max_runs=3)
    if changes:
        record = {**json.loads(raw), **changes}
        raw = json_bytes({key: value for key, value in record.items() if value is not None})
    (custody / name).write_bytes(raw)
    return custody / name, sha256(raw).hexdigest()


def settled_read(platform, host):
    """The retained original and projection captures, decoded."""
    captures = next(platform.custody.glob("native-*/captures"))
    record = json.loads((captures / "read-original.stdout").read_bytes())
    stdout = base64.b64decode(record["stdout"])
    projection = (captures / "read-projection.stdout").read_bytes()
    return host._qualification.closure, projection, stdout


# --- the accepting path and its controls -------------------------------------------


@pytest.mark.parametrize("answer", [
    "x" * route.MODEL_ADVICE_MAX_BYTES,
    "\N{SNOWMAN}" * (route.MODEL_ADVICE_MAX_BYTES // 3),
    "\x01" * route.MODEL_ADVICE_MAX_BYTES,
], ids=["ascii-at-bound", "non-ascii-at-bound", "worst-escaping-at-bound"])
def test_an_advice_read_settles_and_is_accepted_through_the_whole_chain(
    tmp_path, monkeypatch, portable_binding, substituted_guard, answer,
):
    platform, path, digest = world(tmp_path, monkeypatch, portable_binding, answer=answer)
    host, result = platform.window(path, digest)
    assert (result.reason, result.dispatch, result.cleanup, result.custody_retained) == (
        "read-settled", "terminal", "clean", False,
    )
    pins, projection, stdout = settled_read(platform, host)
    assert result.accepted_read_sha256 == closure.accept_replay(pins, projection, stdout, b"", 0)
    original = json.loads(stdout)
    # The whole advice, never the preview's truncation marker.
    assert original["advice"]["advice"] == answer and original["replayed"] is False
    assert original["advice"]["reply_bytes"] == len(answer.encode("utf-8"))
    if answer.startswith("\x01"):
        # The bound binds: the escaped reply alone is six times the reply bound.
        assert len(stdout) > command.ESCAPE * route.MODEL_ADVICE_MAX_BYTES
        assert len(stdout) <= command.ADVICE.log_limit
    assert platform.challenge["consumer"] == "change-review-advice"
    assert platform.challenge["procedure"] == command.ADVICE.procedure
    # No human step: one standing slot is spent, and an accepted, clean end
    # leaves the approval usable for its remaining slots.
    assert platform.challenge["approval_sha256"] == platform.approval.sha256
    assert [path.name for path in platform.custody.glob("selection-*")] == [
        "selection-" + platform.approval.decision(1)]
    assert result.approval_suspended is False
    assert not platform.approval.suspension(platform.custody).exists()
    assert platform.approval.free_slot(platform.custody) == 2
    assert platform.turns() == 1
    # One permitted assembly; one real turn; everything else a counted fixture.
    assert platform.counts == {
        "host-assembly-permitted": 1, "guest-dispatch": 1, "guest-replay": 1,
        "guest-closure": 1, "scp": 16, "ssh-preflight": 16, "ssh-mkdir": 16,
        "ssh-boot": 2, "ssh-cleanup-hash": 1, "ssh-qualification-phase": 15,
        "ssh-d2-readback": 1, "ssh-live": 4, "ssh-guest-read": 7, "ssh-withdrawal": 1,
        "ssh-park-boot": 1, "powershell-park": 1, "powershell-usage": 1,
    }
    assert platform.guest_calls() == {
        "authority-fresh": 1, "install": 1, "authority-readback": 1, "service": 3,
        "authority-inspect": 2, "rm": 1,
    }
    assert not (platform.guest / "fake-authority").exists()
    # CRLF producer bytes, replayed through the unpatched acceptance gate.
    with pytest.raises(ValueError, match="CHANGE_REVIEW_READ_CLOSURE_UNPROVED"):
        closure.accept_replay(pins, projection, stdout.replace(b"\n", b"\r\n"), b"", 0)


def test_a_lost_dispatch_response_is_proved_and_does_not_strand_custody(
    tmp_path, monkeypatch, portable_binding, substituted_guard,
):
    platform, path, digest = world(tmp_path, monkeypatch, portable_binding, lose=True)
    _, result = platform.window(path, digest)
    assert (result.reason, result.dispatch, result.cleanup, result.custody_retained) == (
        "read-settled", "terminal", "clean", False,
    )
    assert result.accepted_read_sha256 is not None and platform.turns() == 1
    recorded = json.loads((result.record / "result.json").read_bytes())
    assert recorded["dispatch_transport"] == "raised"
    assert not (platform.custody / "active").exists()


def test_a_failed_reply_settles_cleanly_and_is_never_accepted(
    tmp_path, monkeypatch, portable_binding, substituted_guard,
):
    platform, path, digest = world(tmp_path, monkeypatch, portable_binding, answer="")
    host, result = platform.window(path, digest)
    assert (result.reason, result.dispatch, result.cleanup, result.custody_retained) == (
        "read-settled", "terminal", "clean", False,
    )
    assert result.accepted_read_sha256 is None and platform.turns() == 1
    _, _, stdout = settled_read(platform, host)
    original = json.loads(stdout)
    assert original["result"]["status"] == "failed" and original["advice"] is None
    assert not (platform.guest / "fake-authority").exists()
    # Not accepted: the approval is suspended, and the next window refuses
    # before any process until a new record is issued.
    assert result.approval_suspended and platform.approval.suspension(platform.custody).exists()
    calls = []
    retry = boundary.QualificationBoundary(path, digest, tmp_path / "retry-work", target=TARGET,
                                           alias=ALIAS, run=calls.append)
    with pytest.raises(ValueError, match=r"^approval-suspended$"):
        run_native_read(platform.custody, retry, StandingApproval.load(
            *platform.record, platform.custody), LIMITS, run=calls.append)
    assert calls == [] and not (tmp_path / "retry-work").exists()


# --- refusals before dispatch ------------------------------------------------------


def _no_process(*args, **kwargs):
    pytest.fail("a selection refusal must precede every external call")


@pytest.mark.parametrize("change", ["digest", "summary-tamper", "summary-crlf", "m9-session"])
def test_selection_drift_and_summary_tamper_refuse_before_any_process(tmp_path, change):
    path, digest = selection(tmp_path, **({"session": {"root": command.SESSION, "label": LABEL}}
                                         if change == "m9-session" else {}))
    if change == "digest":
        digest = "0" * 64
    elif change == "summary-tamper":
        (tmp_path / "summary.json").write_bytes(SUMMARY.replace(b"false", b"true", 1))
    elif change == "summary-crlf":
        (tmp_path / "summary.json").write_bytes(SUMMARY.replace(b"\n", b"\r\n"))
    code = {"digest": "READ_QUALIFICATION_SELECTION_DIGEST",
            "summary-tamper": "CHANGE_REVIEW_QUALIFICATION_SUMMARY_BYTES",
            "summary-crlf": "CHANGE_REVIEW_QUALIFICATION_SUMMARY_BYTES",
            "m9-session": "CHANGE_REVIEW_QUALIFICATION_CONSUMER_SELECTION"}[change]
    with pytest.raises(ValueError, match=code):
        boundary.QualificationBoundary(path, digest, tmp_path / "work", target=TARGET,
                                       alias=ALIAS, run=_no_process)
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize(("options", "reason", "cleanup"), [
    ({"drift": "component"}, "qualification-unproved", "clean"),
    ({"crlf": "consumer-pins"}, "qualification-unproved", "clean"),
    ({"crlf": "consumer-mint"}, "qualification-unproved", "clean"),
    # The mint refuses nonzero after the store phases mutated: as for M9's
    # trial phases, that never licenses the read-only withdrawal escape.
    ({"occupy": "journal-before-mint"}, "withdraw-unproved", "unknown"),
    ({"occupy": "attempt-before-placement"}, "claim-unproved", "clean"),
], ids=["installed-drift", "crlf-pins", "crlf-mint", "occupied-journal", "occupied-attempt"])
def test_drift_crlf_and_occupied_outputs_refuse_before_dispatch(
    tmp_path, monkeypatch, portable_binding, substituted_guard, options, reason, cleanup,
):
    platform, path, digest = world(tmp_path, monkeypatch, portable_binding, **options)
    _, result = platform.window(path, digest)
    assert (result.reason, result.dispatch, result.cleanup, result.custody_retained) == (
        reason, "not-issued", cleanup, cleanup != "clean",
    )
    assert result.accepted_read_sha256 is None and platform.turns() == 0
    assert platform.counts["ssh-guest-read"] == 0 and platform.counts["guest-dispatch"] == 0
    assert "host-assembly-permitted" not in platform.counts
    assert platform.counts["powershell-park"] == (cleanup == "clean")
    # Every refusal here precedes the claim: no slot spent, but the approval
    # is suspended because the window did not end accepted and clean.
    assert not list(platform.custody.glob("selection-*"))
    assert result.approval_suspended and platform.approval.suspension(platform.custody).exists()
    if options.get("occupy") == "attempt-before-placement":
        assert platform.live_probes == 2
        assert Path(platform.local(ATTEMPT)).read_bytes() == b"spent elsewhere"
    if options.get("occupy") == "journal-before-mint":
        assert Path(platform.local(JOURNAL)).read_bytes() == b"occupied"


def test_an_occupied_permit_leaf_refuses_placement_and_is_never_removed(
    tmp_path, monkeypatch, portable_binding, substituted_guard,
):
    platform, path, digest = world(tmp_path, monkeypatch, portable_binding,
                                   occupy="permit-leaf")
    _, result = platform.window(path, digest)
    # The leaf is not this window's to remove, so custody stays retained.
    assert (result.reason, result.dispatch) == ("close-unproved", "not-issued")
    assert result.cleanup == "unknown" and result.custody_retained
    assert (platform.guest / "fake-authority").read_bytes() == b"someone else's permit\n"
    assert platform.turns() == 0 and platform.counts["guest-dispatch"] == 0
    assert "rm" not in platform.guest_calls()


# --- the standing approval: check point (a) before any process ---------------------


def refused_before_any_process(tmp_path, path, digest, record, *, alias=ALIAS) -> str:
    """Run the real entry chain; return the refusal and prove no process ran."""
    custody = tmp_path / "custody"
    calls = []
    host = boundary.QualificationBoundary(path, digest, tmp_path / "work", target=TARGET,
                                          alias=alias, run=calls.append)
    before = set(custody.iterdir())
    with pytest.raises(ValueError) as refused:
        approval = StandingApproval.load(*record, custody)
        run_native_read(custody, host, approval, LIMITS, run=calls.append)
    assert calls == [], "check point (a) precedes every transport call"
    assert set(custody.iterdir()) == before and not (tmp_path / "work").exists()
    return str(refused.value)


@pytest.mark.parametrize(("changes", "code"), [
    ({"controller": "1" * 40}, "approval-controller"),
    ({"runtime": "sha256:" + "9" * 64}, "approval-runtime"),
    ({"source_graph": "sha256:" + "9" * 64}, "approval-source_graph"),
    ({"component": "sha256:" + "9" * 64}, "approval-component"),
    ({"guard": "sha256:" + "9" * 64}, "approval-guard"),
    ({"capability": "codex-operator-write"}, "approval-capability"),
    ({"actor": "static:someone-else"}, "approval-actor"),
    ({"scope": "change-review/other"}, "approval-scope"),
    ({"grants": {**route.READ_GRANTS.model_dump(mode="json"), "timeout_s": 300}},
     "approval-grants"),
    ({"instruction_max_bytes": 16}, "approval-instruction_max_bytes"),
    ({"host_key_alias": "another-host-key"}, "approval-host_key_alias"),
    ({"boot": BOOT}, "approval-forbidden-boot"),
    ({"generation": 12}, "approval-forbidden-generation"),
    ({"provider_revision": "sha256:" + "9" * 64}, "approval-forbidden-provider_revision"),
    ({"operator_binding_digest": "sha256:" + "9" * 64},
     "approval-forbidden-operator_binding_digest"),
    ({"candidate": "sha256:" + "9" * 64}, "approval-forbidden-candidate"),
    ({"target": TARGET}, "approval-forbidden-target"),
    ({"reviewer": "someone"}, "approval-unknown-key"),
], ids=lambda value: value if isinstance(value, str) else next(iter(value)))
def test_a_record_that_does_not_fit_the_selection_refuses_before_any_process(
    tmp_path, changes, code,
):
    path, digest = selection(tmp_path)
    (tmp_path / "custody").mkdir(mode=0o700)
    selected = boundary.QualificationBoundary(path, digest, tmp_path / "work", target=TARGET,
                                              alias=ALIAS).selected_pins()
    record = issued(tmp_path / "custody", selected, changes=changes)
    assert refused_before_any_process(tmp_path, path, digest, record) == code


@pytest.mark.parametrize("state", ["expired", "suspended", "revoked", "exhausted", "digest"])
def test_an_expired_suspended_revoked_or_spent_record_refuses_before_any_process(
    tmp_path, state,
):
    path, digest = selection(tmp_path)
    custody = tmp_path / "custody"
    custody.mkdir(mode=0o700)
    selected = boundary.QualificationBoundary(path, digest, tmp_path / "work", target=TARGET,
                                              alias=ALIAS).selected_pins()
    record = issued(custody, selected, days=-1 if state == "expired" else 7)
    approval = StandingApproval.load(*record, custody)
    if state == "suspended":
        approval.suspension(custody).write_bytes(b"an earlier window")
    elif state == "revoked":
        approval.revocation(custody).write_bytes(b"")
    elif state == "exhausted":
        for slot in range(1, approval.max_runs + 1):
            (custody / ("selection-" + approval.decision(slot))).write_bytes(b"spent")
    elif state == "digest":
        record = (record[0], "0" * 64)
    assert refused_before_any_process(tmp_path, path, digest, record) == "approval-" + state


def test_a_different_host_key_alias_refuses_before_any_process(tmp_path):
    path, digest = selection(tmp_path)
    (tmp_path / "custody").mkdir(mode=0o700)
    selected = boundary.QualificationBoundary(path, digest, tmp_path / "work", target=TARGET,
                                              alias=ALIAS).selected_pins()
    record = issued(tmp_path / "custody", selected)
    # A reviewed selection for another host: its strict alias differs.
    other_path, other_digest = selection(tmp_path, alias="another-host-key")
    assert refused_before_any_process(
        tmp_path, other_path, other_digest, record, alias="another-host-key",
    ) == "approval-host_key_alias"


def test_m9_has_no_standing_record_and_refuses_before_any_process(tmp_path):
    from tests.test_m9_qualification_boundary import selected as m9_selection

    advice_path, advice_digest = selection(tmp_path)
    (tmp_path / "custody").mkdir(mode=0o700)
    record = issued(tmp_path / "custody", boundary.QualificationBoundary(
        advice_path, advice_digest, tmp_path / "work", target=TARGET, alias=ALIAS,
    ).selected_pins())
    (tmp_path / "m9").mkdir()
    m9_path, m9_digest = m9_selection(tmp_path / "m9")
    assert refused_before_any_process(tmp_path, m9_path, m9_digest, record) == "approval-consumer"
    with pytest.raises(ValueError, match=r"^approval-consumer$"):
        owner.issue(boundary.QualificationBoundary(
            m9_path, m9_digest, tmp_path / "work", target=TARGET, alias=ALIAS,
        ).selected_pins(), not_after=datetime.now(UTC) + timedelta(days=7))


def test_a_new_dhcp_address_with_the_same_strict_alias_is_accepted(
    tmp_path, monkeypatch, portable_binding, substituted_guard,
):
    """The record pins the host-key alias, never the per-boot address."""
    platform = Platform(tmp_path, monkeypatch, portable_binding)
    path, digest = selection(tmp_path)
    record = issued(platform.custody, boundary.QualificationBoundary(
        path, digest, tmp_path / "unused", target=TARGET, alias=ALIAS,
    ).selected_pins())
    moved = TARGET.rsplit(".", 1)[0] + ".99"
    path, digest = selection(tmp_path, target=moved)  # the next boot's reviewed selection
    _, result = platform.window(path, digest, target=moved, record=record)
    assert (result.reason, result.dispatch, result.cleanup, result.custody_retained) == (
        "read-settled", "terminal", "clean", False,
    )
    assert result.accepted_read_sha256 is not None and platform.turns() == 1
    assert json.loads((result.record / "result.json").read_bytes())["approval_slot"] == 1


def test_the_issuance_cli_writes_a_canonical_record_the_entry_accepts(tmp_path):
    path, digest = selection(tmp_path)
    custody = tmp_path / "custody"
    custody.mkdir(mode=0o700)
    out = custody / "standing-approval.json"
    printed = io.StringIO()
    with redirect_stdout(printed):
        assert owner.main(["--selection", str(path), "--selection-sha256", digest,
                           "--out", str(out)]) == 0
    approval = StandingApproval.load(out, printed.getvalue().strip(), custody)
    assert approval.max_runs == 3
    assert timedelta(days=6) < approval.not_after - datetime.now(UTC) <= timedelta(days=7)
    assert approval.record["host_key_alias"] == ALIAS and "target" not in approval.record
    assert not (custody / "unused-issuance-work").exists()


def test_m9_keeps_its_own_descriptor_and_a_scoped_site_is_closed():
    assert command.CONSUMERS == {"m9": command.M9, "change-review-advice": command.ADVICE}
    assert (command.SUMMARY_LIMIT, command.REPLY_LIMIT) == (
        route.INSTRUCTION_MAX_BYTES, route.MODEL_ADVICE_MAX_BYTES,
    )
    site = command.Site(command.ADVICE, ROOT, LABEL, STATE)
    assert command.paths(site, AUTH_ID) == {
        "root": ROOT, "sealed": f"{ROOT}/{LABEL}.sealed.json",
        "qualification": ROOT + "/s6a-qualification.json", "state": STATE, "id": AUTH_ID,
        "authorization": AUTH, "attempt": ATTEMPT, "journal": JOURNAL,
    }
    for root, state in ((command.SESSION, STATE), (ROOT, command.SERVICE_STATE), (ROOT, ROOT),
                        ("/home/m8-service/a/b", STATE), (ROOT, "/tmp/state")):
        with pytest.raises(ValueError, match="CHANGE_REVIEW_READ_BAD_SITE"):
            command.Site(command.ADVICE, root, LABEL, state)
    with pytest.raises(ValueError, match="M9_READ_BAD_SITE"):
        command.Site(command.M9, ROOT, LABEL, STATE)
