"""The N4 operator lanes, portably: scripted launcher, relay and custody.

Only the launcher's exchange, the relay and the sealed memfd are substituted;
the lane's composition, its evidence and its stop rules are production code
(M8-N4-state-review.md, section 5). The real launch is the operator session.
"""

from __future__ import annotations

import io
import json
import os
from collections import Counter
from pathlib import Path
from typing import ClassVar

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.substrate.executors import codex_lane
from constructicon.substrate.executors.codex_lane import (
    DENIAL_FAULT,
    EVIDENCE_DOMAIN,
    Custody,
    run_login,
    run_startup,
    write_evidence,
)
from constructicon.substrate.executors.codex_protocol import ExpectedAccount
from constructicon.substrate.executors.egress import EgressDestination, EgressPolicy
from constructicon.substrate.executors.linux import ProcessResult
from constructicon.substrate.executors.operator_store import BindingCheck
from tests.operator_store_world import StoreWorld
from tests.substrate.test_codex_adapter import bare_launcher, clean_native
from tests.substrate.test_codex_matrix import EIGHT
from tests.substrate.test_codex_protocol import ACCOUNT_ID, EMAIL

CONFIGURATION = 'model = "gpt-5.6-sol"\n'
CODE = b"Enter this one-time code ABCD-1234 at https://auth.openai.com/codex/device\n"
FINISHED = ProcessResult(0, CODE, b"login ok\n", 1.0, payload_returncode=0)
POLICY = EgressPolicy((
    EgressDestination("auth.openai.com", 443, "8.8.8.8"),
    EgressDestination("chatgpt.com", 443, "8.8.4.4"),
), 8)


class FakeRelay:
    """Stands in for the relay; the lane reads its two counters only."""

    instances: ClassVar[list[FakeRelay]] = []

    def __init__(self, policy, directory, deadline, check):
        self.directory = directory
        self.observed: Counter[str] = Counter()
        self.destinations: Counter[str] = Counter()
        FakeRelay.instances.append(self)

    async def __aenter__(self):
        self.directory.mkdir()
        return None

    async def __aexit__(self, *exc):
        self.directory.rmdir()
        return None


class Lane:
    """A scripted exchange and the custody the lane's launch consumes."""

    def __init__(self, tmp_path: Path, native=None, *, result=FINISHED, during=None):
        self.native = native
        self.result = result
        self.during = during
        self.credential = tmp_path / "credential"
        self.credential.write_bytes(b"harmless")
        self.opened: list[int] = []
        self.mounts: list = []
        self.lock = os.open(os.devnull, os.O_RDONLY)
        self.checks = 0

    def open_credential(self) -> int:
        fd = os.open(self.credential, os.O_RDONLY)
        self.opened.append(fd)
        return fd

    def check(self) -> BindingCheck:
        self.checks += 1
        return BindingCheck(digest("native-operator-maintenance", 1, {"k": 1}))

    def custody(self) -> Custody:
        return Custody("maintenance", self.lock, self.open_credential, self.check,
                       {"generation_floor": 1})

    def launcher(self):
        lane = self
        base = bare_launcher(clean_native() if self.native is None else self.native)

        async def exchange(command, *, workspace, posture, guard_fds, conversation,
                           timeout_s, native_store=None):
            lane.mounts.append((command, guard_fds, native_store))
            native_store.before_spawn()
            await conversation(base.native)
            if lane.during is not None:
                lane.during(lane)
            return lane.result

        object.__setattr__(base, "exchange", exchange)
        return base


@pytest.fixture(autouse=True)
def substituted(monkeypatch, tmp_path):
    FakeRelay.instances = []
    monkeypatch.setattr(codex_lane, "EgressRelay", FakeRelay)

    def sealed(data):
        path = tmp_path / f"sealed-{len(os.listdir(tmp_path))}"
        path.write_bytes(data)
        return os.open(path, os.O_RDONLY)

    monkeypatch.setattr(codex_lane, "sealed_data_fd", sealed)


def closed(fd: int) -> bool:
    try:
        os.fstat(fd)
    except OSError:
        return True
    return False


# --- login -------------------------------------------------------------------


class Printing:
    """A native peer that prints the device prompt and exits: the login's shape."""

    def __init__(self, output: bytes = CODE):
        self.pending = bytearray(output)
        self.stdin_closed = False

    async def read(self, maximum: int = 8192) -> bytes:
        chunk, self.pending[:] = bytes(self.pending[:maximum]), self.pending[maximum:]
        return chunk

    async def write(self, data: bytes) -> None:
        raise AssertionError("the login lane writes nothing to the client")

    async def close_stdin(self) -> None:
        self.stdin_closed = True


async def test_the_login_code_reaches_the_operator_and_never_the_evidence(tmp_path):
    lane = Lane(tmp_path, Printing())
    out = io.BytesIO()
    evidence = await run_login(
        lane.custody(), lane.launcher(), POLICY, binary="/usr/bin/codex",
        configuration=CONFIGURATION, lane_dir=tmp_path / "lane", deadline_s=30, out=out,
    )
    assert out.getvalue() == CODE
    text = json.dumps(evidence)
    assert b"ABCD-1234".decode() not in text and "auth.openai.com/codex" not in text
    assert evidence["faults"] == [] and evidence["lane"] == "login"
    (command, guards, mount), = lane.mounts
    assert command == ("/usr/bin/codex", "login", "--device-auth")
    assert guards == (lane.lock,) and mount.lock_fd == lane.lock
    assert mount.credential_fd == lane.opened[0] and lane.checks == 1
    assert all(closed(fd) for fd in mount.mount_fds)
    assert not (tmp_path / "lane").exists()


async def test_a_failed_or_denied_login_is_a_fault(tmp_path):
    def deny(lane):
        FakeRelay.instances[-1].observed["denied:destination"] += 1

    lane = Lane(tmp_path, Printing(), result=ProcessResult(
        1, b"", b"", 1.0, payload_returncode=1,
    ), during=deny)
    evidence = await run_login(
        lane.custody(), lane.launcher(), POLICY, binary="/usr/bin/codex",
        configuration=CONFIGURATION, lane_dir=tmp_path / "lane", deadline_s=30,
        out=io.BytesIO(),
    )
    assert DENIAL_FAULT in evidence["faults"]
    assert "the device login did not exit cleanly" in evidence["faults"]
    assert evidence["relay"]["denied"] == {"denied:destination": 1}


async def test_an_existing_lane_directory_refuses_before_anything_opens(tmp_path):
    lane = Lane(tmp_path, Printing())
    (tmp_path / "lane").mkdir()
    with pytest.raises(FileExistsError):
        await run_login(
            lane.custody(), lane.launcher(), POLICY, binary="/usr/bin/codex",
            configuration=CONFIGURATION, lane_dir=tmp_path / "lane", deadline_s=30,
            out=io.BytesIO(),
        )
    assert lane.opened == [] and lane.mounts == []


# --- startup -----------------------------------------------------------------


async def startup(tmp_path, native=None, **kwargs):
    lane = Lane(tmp_path, native, during=kwargs.pop("during", None))
    evidence = await run_startup(
        lane.custody(), lane.launcher(), POLICY, binary="/usr/bin/codex",
        configuration=CONFIGURATION, expected=kwargs.pop("expected", ExpectedAccount(
            plan_type="pro", alternatives=("prolite",),
        )), lane_dir=tmp_path / "lane", deadline_s=30, **kwargs,
    )
    return lane, evidence


async def test_a_clean_startup_records_the_four_methods_and_nothing_identifying(tmp_path):
    lane, evidence = await startup(tmp_path)
    assert evidence["methods_sent"] == [f"'{method}'" for method in EIGHT[:4]]
    assert evidence["gate"] == {"completed": True, "plan": "pro"}
    assert evidence["readback"]["has_credits"] is False
    assert evidence["faults"] == [] and evidence["refresh"] == "unmeasured"
    assert evidence["vendor_identity"] == "unverified"
    assert evidence["vendor_conformance_qualified"] is False
    (command, _, _), = lane.mounts
    assert command == ("/usr/bin/codex", "app-server", "--strict-config", "--stdio")
    text = json.dumps(evidence)
    for planted in (EMAIL, ACCOUNT_ID, "Codex "):
        assert planted not in text


async def test_refresh_is_measured_only_with_a_connection_a_write_and_a_clean_readback(
    tmp_path,
):
    def refresh(lane):
        FakeRelay.instances[-1].destinations["accepted:auth.openai.com:443"] += 1
        stat = lane.credential.stat()
        os.utime(lane.credential, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))

    _, evidence = await startup(tmp_path, during=refresh)
    assert evidence["refresh"] == "measured"
    assert evidence["credential"]["mtime_changed"] is True


async def test_a_connection_without_a_write_is_not_a_measured_refresh(tmp_path):
    def connect(lane):
        FakeRelay.instances[-1].destinations["accepted:auth.openai.com:443"] += 1

    _, evidence = await startup(tmp_path, during=connect)
    assert evidence["refresh"] == "unmeasured"


async def test_any_denial_in_a_clean_startup_is_a_fault(tmp_path):
    def deny(lane):
        FakeRelay.instances[-1].observed["denied:destination"] += 1

    _, evidence = await startup(tmp_path, during=deny)
    assert DENIAL_FAULT in evidence["faults"]


@pytest.mark.parametrize("denied", [True, False])
async def test_a_declared_control_denial_must_occur(tmp_path, denied):
    def deny(lane):
        if denied:
            FakeRelay.instances[-1].observed["denied:destination"] += 1

    _, evidence = await startup(tmp_path, during=deny, expect_denial=True)
    if denied:
        assert DENIAL_FAULT not in evidence["faults"]
    else:
        assert "the declared control denial did not occur" in evidence["faults"]


async def test_an_undeclared_plan_is_a_fault_and_is_not_recorded_as_the_plan(tmp_path):
    native = clean_native(accounts=[{"result": {"account": {
        "type": "chatgpt", "email": EMAIL, "planType": "plus",
    }, "requiresOpenaiAuth": True}}])
    _, evidence = await startup(tmp_path, native)
    assert evidence["faults"] and evidence["gate"] == {"completed": False, "plan": None}
    assert evidence["readback"] is None and evidence["methods_sent"] == [
        f"'{method}'" for method in EIGHT[:3]
    ]


# --- evidence ----------------------------------------------------------------


def test_evidence_is_create_exclusive_completed_last_and_content_addressed(tmp_path):
    path = tmp_path / "evidence.json"
    revision = write_evidence(path, {"schema_version": 1, "faults": []})
    written = json.loads(path.read_text())
    assert list(written)[-1] == "completed" and written["completed"] is True
    assert revision == digest(EVIDENCE_DOMAIN, 1, written)
    with pytest.raises(FileExistsError):
        write_evidence(path, {"schema_version": 1, "faults": []})


def test_evidence_never_marks_itself_completed_early(tmp_path):
    with pytest.raises(ContractViolation, match="last act"):
        write_evidence(tmp_path / "evidence.json", {"completed": True})
    assert not (tmp_path / "evidence.json").exists()


def test_a_failed_evidence_write_leaves_no_completed_file(tmp_path, monkeypatch):
    def failing(fd, data):
        raise OSError("disk full")

    monkeypatch.setattr(codex_lane.os, "write", failing)
    with pytest.raises(OSError):
        write_evidence(tmp_path / "evidence.json", {"faults": []})
    assert "completed" not in (tmp_path / "evidence.json").read_text()


def test_hold_must_lie_within_the_deadline():
    with pytest.raises(SystemExit):
        codex_lane.main([
            "startup", "--store-root", "/s", "--key", "k", "--launch-root", "/r",
            "--binary", "/b", "--configuration", "/c", "--policy", "/p",
            "--lane-dir", "/l", "--evidence", "/e", "--hold", "200", "--deadline", "100",
        ])


def test_the_binary_defaults_to_the_runtime_images_vendor_path(tmp_path, monkeypatch):
    seen = {}

    async def login(custody, launcher, policy, *, binary, **_):
        seen["binary"] = binary
        return {"faults": []}

    class Withdrawn:
        def __enter__(self):
            return object()

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(codex_lane, "_launcher", lambda root: None)
    monkeypatch.setattr(codex_lane, "_policy", lambda path: None)
    monkeypatch.setattr(codex_lane, "maintain_offline", lambda *a, **k: Withdrawn())
    monkeypatch.setattr(codex_lane, "maintenance_custody", lambda withdrawn: None)
    monkeypatch.setattr(codex_lane, "run_login", login)
    monkeypatch.setattr(codex_lane, "write_evidence", lambda path, evidence: "r")
    (tmp_path / "config.toml").write_text("", encoding="utf-8")
    assert codex_lane.main([
        "login", "--store-root", "/s", "--key", "k", "--launch-root", "/r",
        "--configuration", str(tmp_path / "config.toml"), "--policy", "/p",
        "--lane-dir", "/l", "--evidence", "/e",
    ]) == 0
    assert seen["binary"] == codex_lane.RUNTIME_BINARY == "/opt/codex/bin/codex"
    assert codex_lane.RUNTIME_CATALOG == "/opt/codex-models.json"


# --- custody -----------------------------------------------------------------


async def test_active_custody_is_the_providers_own_path_and_releases_its_lock(
    tmp_path, monkeypatch,
):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    world.exclusive = True
    async with codex_lane.active_custody(world.binding()) as custody:
        assert custody.kind == "active"
        assert custody.detail == {"binding_digest": str(world.sealed.operator_binding_digest)}
        assert custody.check() == BindingCheck(world.sealed.operator_binding_digest)
        assert world.holder == custody.lock_fd
        fd = custody.open_credential()
        assert world.credential_opens == [fd]
        os.close(fd)
    assert world.holder is None, "leaving custody released the retained lock"


def test_maintenance_custody_carries_the_contexts_lock_check_and_floor(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    with codex_lane.maintain_offline(world.root, world.key, wait_s=0) as withdrawn:
        custody = codex_lane.maintenance_custody(withdrawn)
        assert custody.kind == "maintenance" and custody.lock_fd == withdrawn.lock_fd
        assert custody.detail == {"generation_floor": withdrawn.generation_floor}
        assert custody.check() == withdrawn.check()
