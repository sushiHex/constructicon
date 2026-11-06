"""Use the installed selector candidate producer and the real staging argv."""

import json
import subprocess
import time
from argparse import Namespace
from pathlib import Path

import pytest
from scripts.ops import m9_qualification_boundary as boundary
from scripts.ops.claude_read_commands import sha
from scripts.ops.claude_read_session import json_bytes

from constructicon.api import m9_trial
from constructicon.api._m9 import proposer
from constructicon.core.identity import json_value
from constructicon.core.manifest import source_graph_hash_for
from tests.test_m9_read_transport import bash

BOOT = "01234567-89ab-cdef-0123-456789abcdef"
PRIOR = "ffffffff-ffff-ffff-ffff-ffffffffffff"
TARGET = "fixture@192.168.10.11"
ALIAS = "fixture"
AUTH = "/var/lib/constructicon-m8-launch/qualification/fixture.json"
RUNTIME = "sha256:" + "1" * 64
QUALIFICATION = "sha256:" + "2" * 64
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
            "runtime": RUNTIME,
            "previous_generation": 11,
            "authorization": AUTH,
            "authorization_id": "fixture",
            "owner_key_sha256": "a" * 64,
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
    assert not twin.events and host.owner_key_sha256 == "a" * 64
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


def test_wrong_target_refuses_before_process(tmp_path, monkeypatch):
    twin = NativeTwin(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="SELECTION_SHAPE"):
        make(tmp_path, twin, target="fixture@192.168.10.12")
    assert not twin.staged and not (tmp_path / "work").exists()
