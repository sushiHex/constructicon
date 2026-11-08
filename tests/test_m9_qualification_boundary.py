"""Use the installed selector candidate producer and the real staging argv."""

import io
import json
import subprocess
import sys
import time
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from scripts.ops import m9_qualification_boundary as boundary
from scripts.ops.claude_read_commands import sha
from scripts.ops.claude_read_session import json_bytes
from scripts.ops.m9_native_read import run_native_read
from scripts.ops.m9_read_window import WindowLimits

from constructicon.api import m9_trial
from constructicon.api._m9 import proposer
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import json_value
from constructicon.core.manifest import source_graph_hash_for
from constructicon.substrate.executors import codex_host, operator_store
from tests.operator_store_world import StoreWorld
from tests.test_m9_read_transport import bash

BOOT = "01234567-89ab-cdef-0123-456789abcdef"
PRIOR = "ffffffff-ffff-ffff-ffff-ffffffffffff"
TARGET = "fixture@192.168.10.11"
ALIAS = "fixture"
AUTH = "/var/lib/constructicon-m8-launch/qualification/fixture.json"
RUNTIME = "sha256:" + "1" * 64
QUALIFICATION = "sha256:" + "2" * 64
D2 = {
    "revision": "d" * 40,
    "workspace": "/home/fixture/m8-host",
    "helper_sha256": "a" * 64,
    "drift_sha256": "b" * 64,
    "drift_hex": b"fixture drift observation\n".hex(),
}
SELECTOR = json_value(
    {
        "source": proposer.SOURCE,
        "source_graph": source_graph_hash_for(proposer.graph()),
        "component": proposer.definition().content_hash(),
    }
)


def selected(root):
    phases = {}
    for phase in (*boundary.PHASES, boundary.CLEANUP):
        raw = (
            f"# fixture template {phase}\nreadonly M9_BOOT=UNREVIEWED\n"
            f'test "$M9_BOOT" = {BOOT} || exit 3\n'
            "printf 'fixture exact phase output\\n'\n"
        ).encode()
        if phase in ("d2-preserve", "d2-verify"):
            raw = boundary._d2_script(
                {
                    "EXPECTED_BOOT": BOOT,
                    "__d2_commit": D2["revision"],
                    "__d2_workspace": D2["workspace"],
                    "__drift_sha256": D2["drift_sha256"],
                    "__drift_hex": D2["drift_hex"],
                },
                phase,
            ).replace(BOOT.encode(), b"UNREVIEWED")
        (root / (phase + ".sh")).write_bytes(raw)
        phases[phase] = {"script": sha(raw)}
        if phase not in {*boundary.TRIAL_PHASES, boundary.CLEANUP}:
            phases[phase]["stdout"] = sha(b"fixture exact phase output\n")
    phases["h7-with-authorized-h8"]["stdout"] = [
        sha(b"fixture alternative H7 receipt\n"),
        sha(b"fixture exact phase output\n"),
    ]
    raw = json_bytes(
        {
            "schema_version": 1,
            "target": TARGET,
            "alias": ALIAS,
            "previous_boot": PRIOR,
            "controller": "0" * 40,
            "d2": D2,
            "runtime": RUNTIME,
            "previous_generation": 11,
            "authorization": AUTH,
            "authorization_id": "fixture",
            "phases": phases,
            "selector": SELECTOR,
        }
    )
    path = root / "selection.json"
    path.write_bytes(raw)
    return path, sha(raw)


class NativeTwin:
    def __init__(self, monkeypatch, work, *, lose=None, shell=None):
        self.lose = lose
        self.work = work
        self.shell = shell
        self.shell_executed = False
        self.events = []
        self.staged = {}
        self.pins = {
            **boundary._fixed_pins(SELECTOR),
            "provider_revision": "sha256:" + "3" * 64,
            "operator_binding_digest": "sha256:" + "4" * 64,
        }
        self.live = {
            "pins": self.pins,
            "generation": 12,
            "qualification": QUALIFICATION,
            "runtime": RUNTIME,
        }
        monkeypatch.setattr(m9_trial, "pins", lambda options, trial: self.pins)
        candidate = m9_trial.mint(
            Namespace(
                authorization_id="fixture",
                attempt_record=work / "fixture-missing",
                store=work,
            ),
            boundary.TRIAL,
        ).model_copy(
            update={
                # Translate only platform-specific Linux locators for the real producer.
                "journal": boundary.STORE + "/journal.sqlite",
                "attempt_record": boundary.ATTEMPT,
            }
        )
        self.candidate = json_bytes(candidate.model_dump(mode="json"))
        self.d2_boot = BOOT

    def __call__(self, argv, **kwargs):
        assert kwargs["stdin"] == subprocess.DEVNULL and kwargs["shell"] is False
        assert 0 < kwargs["timeout"] <= 10
        command = argv[-1]
        raw = b""
        if argv[0] == boundary.transport.SCP:
            # This is the actual emitted SCP argv; only the native I/O is fake.
            phase = Path(argv[-3]).parent.name
            self.staged[command.split(":", 1)[1].strip("/")] = phase
        elif command.startswith("/usr/bin/cat "):
            raw = (BOOT + "\n").encode()
        elif "/bin/bash phase.sh" in command:
            remote = command.split('cd "$HOME/', 1)[1].split('"', 1)[0]
            phase = self.staged[remote]
            assert BOOT in command
            if phase in ("d2-preserve", "d2-verify"):
                helper = D2["workspace"] + "/m8_host_artifacts.py"
                assert "/usr/bin/sudo -n true < /dev/null" in command
                assert f"test ! -L {helper}" in command
                assert f"/usr/bin/sha256sum -- {helper}" in command
                assert D2["helper_sha256"] in command
            self.events.append(phase)
            if phase == self.lose:
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            if phase == "trial-seed":
                raw = json_bytes(
                    {
                        "status": "seeded",
                        **{name: self.pins[name] for name in ("source", "task", "input")},
                    }
                )
            elif phase == "trial-pins":
                raw = json_bytes(self.pins)
            elif phase == "trial-mint":
                raw = self.candidate
            elif phase == boundary.CLEANUP:
                raw = b"codex-withdrawn-floor-12\n"
            elif phase == "physical-preflight" and self.shell:
                package = self.work / "work" / phase
                script = 'cd "$PWD" && /usr/bin/sha256sum --check --strict --quiet MANIFEST.sha256 '
                script += command[command.index("&& /bin/bash phase.sh") :]
                child = subprocess.run(
                    [self.shell, "-c", script],
                    cwd=package,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=5,
                    check=True,
                )
                assert not child.stderr
                raw = child.stdout
                self.shell_executed = True
            else:
                raw = b"fixture exact phase output\n"
        elif "/d2-records/lr2.out" in command:
            remote = next(name for name, phase in self.staged.items() if phase == "d2-verify")
            assert f"/home/fixture/{remote}/d2-records/lr2.out operator 65536" in command
            raw = (
                (self.d2_boot + "\nverify exit 0\n").encode()
                + json_bytes(
                    {
                        "command": "verify",
                        "commit": D2["revision"],
                        "first_parent": True,
                        "script_matches_commit": True,
                        "installed": True,
                    }
                )
                + b"probe exit 0\n"
                + json_bytes(
                    {
                        "qualified": True,
                        "commit": D2["revision"],
                        "scope": "runner_prerequisites_only",
                        "production_available": False,
                    }
                )
            )
        elif "ACTIVE_BINDING_OR_ATTEMPT_DRIFT" in command:
            raw = json_bytes(self.live)
        elif "WITHDRAWAL_LOCK_UNAVAILABLE" in command:
            raw = json_bytes({"key": boundary.STORE_KEY, "generation_floor": 12})
        elif "Stop-VM" in command:
            self.events.append("park")
        elif command == boundary.m8_vm_usage.QUERY:
            raw = json_bytes(
                {
                    "name": "constructicon-m8",
                    "state": "Off",
                    "operational": ["Ok"],
                    "uptime_seconds": 0,
                    "checkpoints": 0,
                    "vmconnect": 0,
                }
            )
        kwargs["stdout"].write(raw)
        return subprocess.CompletedProcess(argv, 0)


def make(tmp_path, twin, *, target=TARGET):
    path, expected = selected(tmp_path)
    return boundary.QualificationBoundary(
        path,
        expected,
        tmp_path / "work",
        target=target,
        alias=ALIAS,
        run=twin,
    )


def test_fresh_pins_drift_and_checked_park(tmp_path, monkeypatch):
    twin = NativeTwin(monkeypatch, tmp_path, shell=bash())
    host = make(tmp_path, twin)
    assert not twin.events
    assert not (tmp_path / "work").exists()
    cutoff = time.monotonic() + 10
    qualified = host.qualify(cutoff)
    assert twin.events == list(boundary.PHASES)
    assert twin.shell_executed
    assert qualified.boot == BOOT and qualified.closure.qualification_revision == QUALIFICATION
    assert qualified.qualification.candidate == twin.candidate
    assert json.loads(qualified.qualification.pins)["generation"] == 12
    assert host.check_live(qualified, cutoff)
    twin.live["qualification"] = "sha256:" + "5" * 64
    assert not host.check_live(qualified, cutoff)
    assert len(host.withdraw(qualified, cutoff)) == 64
    host.park(cutoff)
    assert len(host.check_park(cutoff)) == 64
    assert twin.events[-2:] == [boundary.CLEANUP, "park"]


def test_lost_mutation_response_retains_custody(tmp_path, monkeypatch):
    twin = NativeTwin(monkeypatch, tmp_path, lose="h5-lock")
    host = make(tmp_path, twin)
    cutoff = time.monotonic() + 10
    with pytest.raises(ValueError, match="COMMAND_UNPROVED"):
        host.qualify(cutoff)
    with pytest.raises(ValueError, match="WITHDRAW_UNSAFE"):
        host.withdraw(None, cutoff)
    with pytest.raises(ValueError, match="PARK_UNSAFE"):
        host.park(cutoff)
    assert twin.events[-1] == "h5-lock"


def test_d2_marker_does_not_substitute_for_current_boot_record(tmp_path, monkeypatch):
    twin = NativeTwin(monkeypatch, tmp_path)
    twin.d2_boot = PRIOR
    host = make(tmp_path, twin)
    with pytest.raises(ValueError):
        host.qualify(time.monotonic() + 10)
    assert twin.events == ["d2-preserve", "d2-verify"]


def test_selected_d2_script_must_match_the_reviewed_compiler(tmp_path, monkeypatch):
    twin = NativeTwin(monkeypatch, tmp_path)
    path, _ = selected(tmp_path)
    record = json.loads(path.read_bytes())
    template = path.with_name("d2-preserve.sh")
    raw = template.read_bytes() + b"# different selected script\n"
    template.write_bytes(raw)
    record["phases"]["d2-preserve"]["script"] = sha(raw)
    raw_selection = json_bytes(record)
    path.write_bytes(raw_selection)
    host = boundary.QualificationBoundary(
        path, sha(raw_selection), tmp_path / "work", target=TARGET, alias=ALIAS, run=twin
    )
    with pytest.raises(ValueError, match="D2_SCRIPT_SELECTION"):
        host.qualify(time.monotonic() + 10)
    assert twin.events == []


def test_wrong_target_refuses_before_process(tmp_path, monkeypatch):
    twin = NativeTwin(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="SELECTION_SHAPE"):
        make(tmp_path, twin, target="fixture@192.168.10.12")
    assert not twin.staged and not (tmp_path / "work").exists()


def test_retired_owner_key_selection_refuses_before_process(tmp_path):
    def unexpected_process(*args, **kwargs):
        pytest.fail("obsolete selection must not run a subprocess")

    path, _ = selected(tmp_path)
    raw = json_bytes({**json.loads(path.read_bytes()), "owner_key_sha256": "a" * 64})
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="SELECTION_SHAPE"):
        boundary.QualificationBoundary(
            path, sha(raw), tmp_path / "work", target=TARGET, alias=ALIAS, run=unexpected_process
        )
    assert not (tmp_path / "work").exists()


class TerminalFailureTwin(NativeTwin):
    """Real phase capture and locked withdrawal reader; external I/O is fake.

    StoreWorld substitutes OS/descriptor primitives only. The emitted _WITHDRAWN
    code still calls the real _open_offline/_current_withdrawal under the lock;
    missing active.json refuses rather than proving withdrawal by absence.
    """

    def __init__(self, monkeypatch, work, *, phase="fresh-workspaces", code=1,
                 probe_fault=None, park_fault=False):
        super().__init__(monkeypatch, work)
        self.phase, self.code = phase, code
        self.probe_fault, self.park_fault = probe_fault, park_fault
        self.probes = 0
        self.world = StoreWorld(work / "physical", key=boundary.STORE_KEY, generation=11)
        self.world.root = self.world.root.with_name("operator-stores")
        self.world.root.mkdir()
        self.world.exclusive = True
        self.world.install(monkeypatch)
        with operator_store.maintain_offline(self.world.root, self.world.key, wait_s=0):
            pass
        self.withdrawn_metadata = dict(self.world.metadata)
        self.world.events.clear()
        self.locked_reads = 0
        read = operator_store._read_metadata
        def locked_read(opened, name):
            if name == "active.json":
                assert self.world.holder == opened.lock_fd
                self.locked_reads += 1
            return read(opened, name)
        monkeypatch.setattr(operator_store, "_read_metadata", locked_read)
        monkeypatch.setattr(codex_host, "LAUNCH_ROOT", self.world.root.parent)

    def __call__(self, argv, **kwargs):
        assert kwargs["stdin"] == subprocess.DEVNULL and kwargs["shell"] is False
        command = argv[-1]
        if "/bin/bash phase.sh" in command:
            remote = command.split('cd "$HOME/', 1)[1].split('"', 1)[0]
            phase = self.staged[remote]
            if phase == self.phase:
                self.events.append(phase)
                if self.code == "timeout":
                    raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
                if self.code == "lost":
                    raise OSError("fixture transport lost")
                kwargs["stderr"].write(b"fixture synchronous guard refusal\n")
                return subprocess.CompletedProcess(argv, self.code)
        if "WITHDRAWAL_LOCK_UNAVAILABLE" in command:
            self.probes += 1
            self.events.append("withdraw-probe")
            if self.probe_fault == "timeout":
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            if self.probe_fault == "missing":
                self.world.metadata.pop("active.json")
            if self.probe_fault == "locked":
                self.world.lock_after = self.world.lock_attempts + 1
            output = io.StringIO()
            prior_argv, prior_path = sys.argv, sys.path[:]
            try:
                sys.argv = ["withdrawal-probe", str(self.work), self.world.key]
                with redirect_stdout(output):
                    exec(compile(boundary._WITHDRAWN, "actual-withdrawal-probe", "exec"), {})
            except ContractViolation:
                kwargs["stderr"].write(b"fixture withdrawal refused\n")
                return subprocess.CompletedProcess(argv, 1)
            finally:
                sys.argv, sys.path[:] = prior_argv, prior_path
            raw = output.getvalue().encode()
            if self.probe_fault == "altered":
                raw = json_bytes({"key": self.world.key, "generation_floor": 12})
            kwargs["stdout"].write(raw)
            return subprocess.CompletedProcess(argv, 0)
        if command == boundary.m8_vm_usage.QUERY and self.park_fault:
            kwargs["stdout"].write(json_bytes({"name": "constructicon-m8", "state": "Running",
                "operational": ["Ok"], "uptime_seconds": 1, "checkpoints": 0, "vmconnect": 0}))
            return subprocess.CompletedProcess(argv, 0)
        return super().__call__(argv, **kwargs)


def failed_window(tmp_path, monkeypatch, **options):
    twin = TerminalFailureTwin(monkeypatch, tmp_path, **options)
    host = make(tmp_path, twin)
    custody = tmp_path / "custody"
    custody.mkdir(mode=0o700)
    limits = WindowLimits(window=100, qualify=8, placement=1, dispatch=1, proof=1,
                          close=1, withdraw=9, park=10)
    # No owner method may be reached: qualification fails before a pin packet.
    result = run_native_read(custody, host, Namespace(), limits, run=twin)
    return result, host, twin, custody


@pytest.mark.parametrize("code", [1, 127])
def test_completed_pre_store_failure_uses_locked_withdrawal_then_verified_off(
    tmp_path, monkeypatch, code,
):
    result, host, twin, custody = failed_window(tmp_path, monkeypatch, code=code)
    assert result.reason == "qualification-unproved" and result.cleanup == "clean"
    assert result.dispatch == "not-issued" and result.accepted_read_sha256 is None
    assert not result.custody_retained and not (custody / "active").exists()
    assert host._uncertain is True and host._qualification is None
    assert twin.probes == 1 and twin.events[-2:] == ["withdraw-probe", "park"]
    assert boundary.CLEANUP not in twin.events and "lock" in twin.world.events
    assert twin.locked_reads == 1
    assert twin.world.holder is None and twin.world.metadata == twin.withdrawn_metadata
    assert not list(result.record.glob("challenge*"))
    status = json.loads((tmp_path / "work/captures/fresh-workspaces.status.json").read_bytes())
    assert status == {"completed": True, "returncode": code, "timed_out": False}


@pytest.mark.parametrize("code", ["timeout", "lost", None, True, 0, -15, 128, 255])
def test_unclear_pre_store_exit_retains_custody_without_probe(tmp_path, monkeypatch, code):
    result, host, twin, custody = failed_window(tmp_path, monkeypatch, code=code)
    assert result.cleanup == "unknown" and result.custody_retained
    assert result.dispatch == "not-issued" and result.accepted_read_sha256 is None
    assert (custody / "active").exists() and host._uncertain is True
    assert twin.probes == 0 and "park" not in twin.events and boundary.CLEANUP not in twin.events


@pytest.mark.parametrize("phase", [*sorted(boundary.STORE_MUTATIONS), "trial-seed"])
def test_completed_store_phase_failure_cannot_use_read_only_escape(tmp_path, monkeypatch, phase):
    result, host, twin, custody = failed_window(tmp_path, monkeypatch, phase=phase)
    assert result.cleanup == "unknown" and result.custody_retained and (custody / "active").exists()
    assert host._mutated and host._uncertain
    assert twin.probes == 0 and "park" not in twin.events and boundary.CLEANUP not in twin.events


@pytest.mark.parametrize("fault", ["missing", "locked", "altered", "timeout"])
def test_completed_failure_probe_refusal_never_parks_or_retries(tmp_path, monkeypatch, fault):
    result, host, twin, custody = failed_window(tmp_path, monkeypatch, probe_fault=fault)
    assert result.cleanup == "unknown" and result.custody_retained and (custody / "active").exists()
    assert host._uncertain and twin.probes == 1 and "park" not in twin.events
    assert host._completed_phase_exit is None
    with pytest.raises(ValueError, match="WITHDRAW_UNSAFE"):
        host.withdraw(None, time.monotonic() + 10)
    with pytest.raises(ValueError, match="PARK_UNSAFE"):
        host.park(time.monotonic() + 10)
    assert twin.probes == 1 and boundary.CLEANUP not in twin.events


def test_completed_failure_requires_independent_off_observation(tmp_path, monkeypatch):
    result, host, twin, custody = failed_window(tmp_path, monkeypatch, park_fault=True)
    assert result.reason == "park-unproved" and result.cleanup == "unknown"
    assert result.custody_retained and (custody / "active").exists()
    assert host._uncertain and twin.probes == 1 and twin.events[-1] == "park"


def test_new_phase_discards_stale_exit_before_transport_loss(tmp_path, monkeypatch):
    twin = TerminalFailureTwin(monkeypatch, tmp_path, code="lost")
    host = make(tmp_path, twin)
    stage = host._stage
    def stale_after_staging(phase, cutoff):
        argv = stage(phase, cutoff)
        if phase == twin.phase:
            host._completed_phase_exit = 1
        return argv
    monkeypatch.setattr(host, "_stage", stale_after_staging)
    with pytest.raises(OSError, match="fixture transport lost"):
        host.qualify(time.monotonic() + 10)
    assert host._completed_phase_exit is None
    with pytest.raises(ValueError, match="WITHDRAW_UNSAFE"):
        host.withdraw(None, time.monotonic() + 10)
    assert host._completed_phase_exit is None and twin.probes == 0


@pytest.mark.parametrize("change", [
    {"completed": False}, {"completed": 1}, {"timed_out": True},
    {"returncode": 1.0}, {"extra": "not-the-capture-contract"},
])
def test_malformed_phase_completion_cannot_license_withdrawal(tmp_path, monkeypatch, change):
    capture = boundary.transport.capture
    def altered(name, *args, **kwargs):
        status, out, err = capture(name, *args, **kwargs)
        return ({**status, **change} if name == "fresh-workspaces" else status), out, err
    monkeypatch.setattr(boundary.transport, "capture", altered)
    result, host, twin, custody = failed_window(tmp_path, monkeypatch)
    assert result.cleanup == "unknown" and result.custody_retained
    assert host._uncertain and (custody / "active").exists()
    assert twin.probes == 0 and "park" not in twin.events
