"""The N4 operator lanes, portably: scripted launcher, relay and custody.

Only the launcher's exchange, the relay and the sealed memfd are substituted;
the lane's composition, its evidence and its stop rules are production code
(M8-N4-state-review.md, section 5). The real launch is the operator session.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.substrate.executors import codex_lane, linux, operator_store
from constructicon.substrate.executors.codex_lane import (
    DENIAL_FAULT,
    EVIDENCE_DOMAIN,
    LOGIN_FIELDS,
    STARTUP_FIELDS,
    Custody,
    EvidenceFile,
    Executable,
    run_login,
    run_startup,
    write_evidence,
)
from constructicon.substrate.executors.codex_protocol import ExpectedAccount
from constructicon.substrate.executors.egress import EgressDestination, EgressPolicy
from constructicon.substrate.executors.linux import ProcessExchangeError, ProcessResult
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
EXECUTABLE = Executable("/opt/codex/bin/codex", "a" * 64)
REGULAR = (stat.S_IFREG | 0o600, 1, 1000)
FOUR = [f"'{method}'" for method in EIGHT[:4]]


class FakeRelay:
    """Stands in for the relay; the lane reads its counters and its closure."""

    instances: ClassVar[list[FakeRelay]] = []
    closes = True

    def __init__(self, policy, directory, deadline, check):
        self.directory = directory
        self.observed: Counter[str] = Counter()
        self.destinations: Counter[str] = Counter()
        self.closed = False
        FakeRelay.instances.append(self)

    async def __aenter__(self):
        self.directory.mkdir()
        return None

    async def __aexit__(self, *exc):
        self.directory.rmdir()
        self.closed = FakeRelay.closes
        return None


class Lane:
    """A scripted exchange and the custody the lane's launch consumes."""

    def __init__(self, tmp_path: Path, native=None, *, result=FINISHED, during=None,
                 kind="maintenance", writes=None):
        self.native = native
        self.result = result
        self.during = during
        self.kind = kind
        self.credential = tmp_path / "credential"
        self.credential.write_bytes(b"harmless")
        self.opened: list[int] = []
        self.mounts: list = []
        self.lock = os.open(os.devnull, os.O_RDONLY)
        self.checks = 0
        self.check_fails_after = None
        self.facts = REGULAR
        self.created = 0
        self.raises: BaseException | None = None
        # A login (a printing peer, not a scripted app-server) writes the
        # credential it was given; a startup does not unless a test says so.
        printing = native is not None and not hasattr(native, "received")
        self.writes = printing if writes is None else writes

    def open_credential(self) -> int:
        fd = os.open(self.credential, os.O_RDONLY)
        self.opened.append(fd)
        return fd

    def check(self) -> BindingCheck:
        self.checks += 1
        if self.check_fails_after is not None and self.checks > self.check_fails_after:
            raise ContractViolation("native store maintenance is unavailable")
        return BindingCheck(digest("native-operator-maintenance", 1, {"k": 1}))

    def create(self) -> None:
        self.created += 1

    def custody(self) -> Custody:
        return Custody(self.kind, self.lock, self.open_credential, self.check,
                       {"generation_floor": 1}, facts=lambda fd: self.facts,
                       create_credential=self.create if self.kind == "maintenance" else None)

    def launcher(self):
        lane = self
        base = bare_launcher(clean_native() if self.native is None else self.native)

        async def exchange(command, *, workspace, posture, guard_fds, conversation,
                           timeout_s, native_store=None):
            lane.mounts.append((command, guard_fds, native_store))
            native_store.before_spawn()
            if lane.result.returncode != 125:  # 125: the probe expired, nothing conversed
                await conversation(base.native)
            if lane.writes:
                info = lane.credential.stat()
                os.utime(lane.credential, ns=(info.st_atime_ns, info.st_mtime_ns + 10**9))
            if lane.during is not None:
                lane.during(lane)
            if lane.raises is not None:
                raise lane.raises
            return lane.result

        object.__setattr__(base, "exchange", exchange)
        return base


@pytest.fixture(autouse=True)
def substituted(monkeypatch, tmp_path):
    FakeRelay.instances = []
    FakeRelay.closes = True
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


async def login(lane: Lane, tmp_path: Path, **kwargs):
    return await run_login(
        lane.custody(), lane.launcher(), POLICY, executable=EXECUTABLE,
        configuration=CONFIGURATION, lane_dir=tmp_path / "lane", deadline_s=30,
        out=kwargs.pop("out", io.BytesIO()), **kwargs,
    )


async def test_the_login_code_reaches_the_operator_and_never_the_evidence(tmp_path):
    lane = Lane(tmp_path, Printing())
    out = io.BytesIO()
    evidence = await login(lane, tmp_path, out=out)
    assert out.getvalue() == CODE
    text = json.dumps(evidence)
    assert b"ABCD-1234".decode() not in text and "auth.openai.com/codex" not in text
    assert evidence["faults"] == [] and evidence["lane"] == "login"
    assert evidence["credential"] == {
        "present": True, "regular_0600": True, "mtime_changed": True, "checked": True,
    }
    (command, guards, mount), = lane.mounts
    assert command == ("/opt/codex/bin/codex", "login", "--device-auth")
    assert guards == (lane.lock,) and mount.lock_fd == lane.lock
    assert mount.credential_fd == lane.opened[0] and lane.checks == 2
    assert all(closed(fd) for fd in mount.mount_fds)
    assert not (tmp_path / "lane").exists()


async def test_a_login_never_runs_under_the_active_selection(tmp_path):
    """CC-1: a login rewrites the credential; only maintenance may allow that."""

    lane = Lane(tmp_path, Printing(), kind="active")
    with pytest.raises(ContractViolation, match="only inside maintenance"):
        await login(lane, tmp_path)
    assert lane.opened == [] and lane.mounts == []


async def test_a_failed_or_denied_login_is_a_fault(tmp_path):
    def deny(lane):
        FakeRelay.instances[-1].observed["denied:destination"] += 1

    lane = Lane(tmp_path, Printing(), result=ProcessResult(
        1, b"", b"", 1.0, payload_returncode=1,
    ), during=deny)
    evidence = await login(lane, tmp_path)
    assert DENIAL_FAULT in evidence["faults"]
    assert "the native client did not exit cleanly" in evidence["faults"]
    assert evidence["relay"]["denied"] == {"denied:destination": 1}


async def test_a_login_that_wrote_nothing_is_a_fault(tmp_path):
    """CC-2: exit 0 alone is not a login."""

    evidence = await login(Lane(tmp_path, Printing(), writes=False), tmp_path)
    assert evidence["faults"] == ["the device login wrote no credential"]
    assert evidence["credential"]["mtime_changed"] is False


async def test_the_first_login_creates_the_empty_credential_under_the_same_custody(tmp_path):
    lane = Lane(tmp_path, Printing())
    evidence = await login(lane, tmp_path, first_login=True)
    assert lane.created == 1 and evidence["faults"] == []


async def test_only_a_custody_that_can_create_one_makes_a_first_credential(tmp_path):
    lane = Lane(tmp_path, Printing())
    custody = replace(lane.custody(), create_credential=None)
    with pytest.raises(ContractViolation, match="first credential"):
        await run_login(
            custody, lane.launcher(), POLICY, executable=EXECUTABLE,
            configuration=CONFIGURATION, lane_dir=tmp_path / "lane", deadline_s=30,
            out=io.BytesIO(), first_login=True,
        )
    assert lane.mounts == []


async def test_an_existing_lane_directory_refuses_before_anything_opens(tmp_path):
    lane = Lane(tmp_path, Printing())
    (tmp_path / "lane").mkdir()
    with pytest.raises(FileExistsError):
        await login(lane, tmp_path)
    assert lane.opened == [] and lane.mounts == []


# --- startup -----------------------------------------------------------------


async def startup(tmp_path, native=None, *, lane=None, **kwargs):
    lane = lane or Lane(tmp_path, native, during=kwargs.pop("during", None))
    evidence = await run_startup(
        lane.custody(), lane.launcher(), POLICY, executable=EXECUTABLE,
        configuration=CONFIGURATION, expected=kwargs.pop("expected", ExpectedAccount(
            plan_type="pro", alternatives=("prolite",),
        )), lane_dir=tmp_path / "lane", deadline_s=30, **kwargs,
    )
    return lane, evidence


def startup_native(**overrides):
    return clean_native(accounts=[{"result": {"account": {
        "type": "chatgpt", "email": EMAIL, "planType": "pro",
    }, "requiresOpenaiAuth": True}}], **overrides)


async def test_a_clean_startup_records_the_four_methods_and_nothing_identifying(tmp_path):
    lane, evidence = await startup(tmp_path, startup_native())
    assert evidence["methods_sent"] == FOUR
    assert evidence["gate"] == {"completed": True, "plan": "pro"}
    assert evidence["readback"]["has_credits"] is False
    assert evidence["faults"] == [] and evidence["refresh"] == "unmeasured"
    assert evidence["vendor_identity"] == "unverified"
    assert evidence["vendor_conformance_qualified"] is False
    assert evidence["executable"] == {"path": EXECUTABLE.path, "sha256": EXECUTABLE.sha256}
    (command, _, _), = lane.mounts
    assert command == ("/opt/codex/bin/codex", "app-server", "--strict-config", "--stdio")
    text = json.dumps(evidence)
    for planted in (EMAIL, ACCOUNT_ID, "Codex "):
        assert planted not in text


def outcome(returncode=0, payload=0, **changes):
    return ProcessResult(returncode, b"", b"", 1.0, payload_returncode=payload, **changes)


AFFIRMATIVE = {
    # The launcher returned before any conversation: nothing may read as a pass.
    "never-conversed": (lambda lane: setattr(lane, "result", outcome(125, None, timed_out=True)),
                        {"the startup gate did not complete", "no spend readback was judged",
                         "the startup did not send exactly the four authorized methods",
                         "the launch timed out", "the native client did not exit cleanly"}),
    "killed": (lambda lane: setattr(lane, "result", outcome(137, 137)),
               {"the native client did not exit cleanly"}),
    "no-payload-status": (lambda lane: setattr(lane, "result", outcome(0, None)),
                          {"the native client did not exit cleanly"}),
    "timed-out": (lambda lane: setattr(lane, "result", outcome(timed_out=True)),
                  {"the launch timed out"}),
    "bound": (lambda lane: setattr(lane, "result", outcome(bound_exceeded="stdout")),
              {"a launch bound was exceeded"}),
    "exchange-raised": (
        lambda lane: setattr(lane, "raises", ProcessExchangeError(outcome(1, 1))),
        {"the exchange raised after the launch", "the native client did not exit cleanly"},
    ),
    "relay-unclosed": (lambda lane: setattr(FakeRelay, "closes", False),
                       {"the relay did not close cleanly"}),
    "terminal-check": (lambda lane: setattr(lane, "check_fails_after", 1),
                       {"the terminal custody check failed"}),
    "credential-mode": (lambda lane: setattr(lane, "facts", (stat.S_IFREG | 0o644, 1, 1000)),
                        {"the credential is not one regular 0600 file after the run"}),
    "credential-unlinked": (lambda lane: setattr(lane, "facts", (stat.S_IFREG | 0o600, 0, 1000)),
                            {"the credential is not one regular 0600 file after the run"}),
}


@pytest.mark.parametrize("change", AFFIRMATIVE)
async def test_a_startup_passes_only_on_affirmative_facts(tmp_path, change):
    """SPEND-1 / RL-1: a missing fact is a fault that names it, never silence."""

    alter, expected = AFFIRMATIVE[change]
    lane = Lane(tmp_path, startup_native())
    alter(lane)
    _, evidence = await startup(tmp_path, lane=lane)
    assert set(evidence["faults"]) == expected, evidence["faults"]


async def test_the_four_methods_are_compared_not_assumed(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_lane, "STARTUP_METHODS", ("initialize", "initialized"))
    _, evidence = await startup(tmp_path, startup_native())
    assert evidence["faults"] == ["the startup did not send exactly the four authorized methods"]


async def test_session_damage_is_a_startup_fault(tmp_path, monkeypatch):
    class Damaged(codex_lane.CodexConversation):
        async def __call__(self, io):
            await super().__call__(io)
            self.observation = replace(self.observation, malformed_records=1)

    monkeypatch.setattr(codex_lane, "CodexConversation", Damaged)
    _, evidence = await startup(tmp_path, startup_native())
    assert evidence["faults"] == ["the session emitted damaged or unattributed records"]
    assert evidence["observation"] == {"malformed_records": 1, "first_error": False}


async def test_refresh_is_measured_only_with_a_connection_a_write_and_a_clean_readback(
    tmp_path,
):
    def refresh(lane):
        FakeRelay.instances[-1].destinations["accepted:auth.openai.com:443"] += 1

    lane = Lane(tmp_path, startup_native(), during=refresh, writes=True)
    _, evidence = await startup(tmp_path, lane=lane)
    assert evidence["refresh"] == "measured"
    assert evidence["credential"]["mtime_changed"] is True


async def test_a_connection_without_a_write_is_not_a_measured_refresh(tmp_path):
    def connect(lane):
        FakeRelay.instances[-1].destinations["accepted:auth.openai.com:443"] += 1

    _, evidence = await startup(tmp_path, startup_native(), during=connect)
    assert evidence["refresh"] == "unmeasured"


async def test_any_denial_in_a_clean_startup_is_a_fault(tmp_path):
    def deny(lane):
        FakeRelay.instances[-1].observed["denied:destination"] += 1

    _, evidence = await startup(tmp_path, startup_native(), during=deny)
    assert DENIAL_FAULT in evidence["faults"]


@pytest.mark.parametrize("denied", [True, False])
async def test_a_declared_control_denial_must_occur(tmp_path, denied):
    def deny(lane):
        if denied:
            FakeRelay.instances[-1].observed["denied:destination"] += 1

    _, evidence = await startup(tmp_path, startup_native(), during=deny, expect_denial=True)
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
    assert evidence["readback"] is None and evidence["methods_sent"] == FOUR[:3]


async def test_the_hold_runs_inside_the_live_exchange(tmp_path):
    """RL-3: the pause is the conversation's, before stdin closes."""

    native = startup_native()
    _, evidence = await startup(tmp_path, native, hold_s=0.01)
    assert evidence["hold_s"] == 0.01 and evidence["faults"] == []
    assert native.stdin_closed


@pytest.mark.parametrize("hold", [-1.0, 30.0, 31.0])
async def test_a_hold_outside_the_deadline_refuses_before_launch(tmp_path, hold):
    lane = Lane(tmp_path, startup_native())
    with pytest.raises(ContractViolation, match="hold"):
        await startup(tmp_path, lane=lane, hold_s=hold)
    assert lane.mounts == []


# --- the closed schema (F1) ----------------------------------------------------


async def test_each_lane_emits_exactly_its_closed_schema(tmp_path):
    _, started = await startup(tmp_path, startup_native())
    assert set(started) == STARTUP_FIELDS
    logged = await login(Lane(tmp_path, Printing()), tmp_path)
    assert set(logged) == LOGIN_FIELDS


def test_the_design_documents_the_emitted_schema():
    review = (Path(__file__).parents[2] / "docs" / "plans" / "handoffs"
              / "M8-N4-state-review.md").read_text(encoding="utf-8")
    block = review.split("<!-- lane-evidence-schema -->", 2)[1]
    documented = {
        lane: set(re.findall(r"`([a-z_0-9]+)`", line.split(":", 1)[1]))
        for lane, line in (
            ("login", next(item for item in block.splitlines() if item.startswith("- login:"))),
            ("startup",
             next(item for item in block.splitlines() if item.startswith("- startup adds:"))),
        )
    }
    assert documented["login"] == LOGIN_FIELDS
    assert documented["login"] | documented["startup"] == STARTUP_FIELDS


# --- evidence ----------------------------------------------------------------


def test_evidence_is_create_exclusive_completed_last_and_content_addressed(tmp_path):
    path = tmp_path / "evidence.json"
    revision = write_evidence(path, {"schema_version": 1, "faults": []})
    written = json.loads(path.read_text())
    assert list(written)[-1] == "completed" and written["completed"] is True
    assert revision == digest(EVIDENCE_DOMAIN, 1, written)
    with pytest.raises(FileExistsError):
        write_evidence(path, {"schema_version": 1, "faults": []})
    assert os.listdir(tmp_path) == ["evidence.json"]


def test_evidence_never_marks_itself_completed_early(tmp_path):
    with pytest.raises(ContractViolation, match="last act"):
        write_evidence(tmp_path / "evidence.json", {"completed": True})
    assert os.listdir(tmp_path) == []


@pytest.mark.parametrize("failing", ["write", "fsync", "link"])
def test_a_failed_evidence_write_leaves_no_file_at_all(tmp_path, monkeypatch, failing):
    """RL-6: the final name appears only for a complete, synced record."""

    def fail(*args, **kwargs):
        raise OSError(5, "injected")

    monkeypatch.setattr(codex_lane.os, failing, fail)
    with pytest.raises(OSError):
        write_evidence(tmp_path / "evidence.json", {"faults": []})
    assert os.listdir(tmp_path) == []


def test_publish_syncs_the_records_fd_before_it_links_the_name(tmp_path, monkeypatch):
    """RL-6, by order: a mutant that drops the fsync must fail this by

    assertion. ``os.fsync`` and ``os.link`` are replaced with recording
    wrappers that delegate to the real functions, so the write still lands;
    only the order of calls is observed. The record's own fsync must appear,
    and it must appear before the temporary is linked to its final name --
    portable across Windows (no directory fsync) and Linux (one more fsync,
    of the directory, after the link).
    """

    calls: list[str] = []
    real_fsync, real_link = os.fsync, os.link

    def fsync(fd):
        calls.append("fsync")
        return real_fsync(fd)

    def link(src, dst):
        calls.append("link")
        return real_link(src, dst)

    monkeypatch.setattr(codex_lane.os, "fsync", fsync)
    monkeypatch.setattr(codex_lane.os, "link", link)
    write_evidence(tmp_path / "evidence.json", {"faults": []})
    assert "fsync" in calls and "link" in calls
    assert calls.index("fsync") < calls.index("link")


def test_a_failure_after_the_link_removes_the_published_name_too(tmp_path, monkeypatch):
    def fail(path):
        raise OSError(5, "injected")

    monkeypatch.setattr(codex_lane, "_fsync_directory", fail)
    with pytest.raises(OSError):
        write_evidence(tmp_path / "evidence.json", {"faults": []})
    assert os.listdir(tmp_path) == []


def test_a_reservation_never_replaces_an_existing_file(tmp_path):
    path = tmp_path / "evidence.json"
    reservation = EvidenceFile(path)
    path.write_text("someone else's")
    with pytest.raises(OSError) as raised:
        reservation.publish({"faults": []})
    assert raised.type is FileExistsError, raised.value
    assert path.read_text() == "someone else's"
    assert os.listdir(tmp_path) == ["evidence.json"]


def lane_command(tmp_path, *extra: str, evidence: Path | None = None, lane: str = "login"):
    (tmp_path / "config.toml").write_text(CONFIGURATION, encoding="utf-8")
    return [
        lane, "--store-root", "/s", "--key", "k", "--launch-root", "/r",
        "--configuration", str(tmp_path / "config.toml"), "--policy", "/p",
        "--lane-dir", "/l", "--evidence", str(evidence or tmp_path / "evidence.json"), *extra,
    ]


class Recorded:
    """A context manager that records entry and exit into a shared event list."""

    def __init__(self, events: list, value: object) -> None:
        self.events, self.value = events, value

    def __enter__(self):
        self.events.append("enter")
        return self.value

    def __exit__(self, *_):
        self.events.append("exit")
        return False


def main_world(monkeypatch) -> dict[str, Any]:
    """``main`` with only its custody and launch substituted; the rest is real."""

    seen: dict[str, Any] = {"events": []}

    async def lane(custody, launcher, policy, *, executable, deadline_s, **options):
        seen["events"].append("lane")
        seen["executable"], seen["deadline"] = executable, deadline_s
        seen["options"] = options
        return {"faults": []}

    def inherited(root, key, lock_fd, **options):
        seen["inherited"] = (root, key, lock_fd, options)
        return Recorded(seen["events"], object())

    def launcher(root):
        seen["events"].append("launcher")
        return None

    monkeypatch.setattr(codex_lane, "_launcher", launcher)
    monkeypatch.setattr(codex_lane, "vendor_executable", lambda launcher: EXECUTABLE)
    monkeypatch.setattr(codex_lane, "_policy", lambda path: None)
    monkeypatch.setattr(codex_lane, "inherit_maintenance", inherited)
    monkeypatch.setattr(codex_lane, "maintenance_custody", lambda withdrawn: None)
    monkeypatch.setattr(codex_lane, "run_login", lane)
    monkeypatch.setattr(codex_lane, "run_startup", lane)
    return seen


def test_a_maintenance_lane_proves_the_custody_its_parent_passed(tmp_path, monkeypatch):
    seen = main_world(monkeypatch)
    assert codex_lane.main(lane_command(
        tmp_path, "--custody=maintenance", "--lock-fd=7", "--floor=3",
    )) == 0
    assert seen["inherited"] == (Path("/s"), "k", 7, {
        "generation_floor": 3, "parent": os.getppid(),
    })
    assert seen["events"] == ["launcher", "enter", "lane", "exit"]
    assert seen["executable"] == EXECUTABLE
    assert json.loads((tmp_path / "evidence.json").read_text())["completed"] is True


@pytest.mark.parametrize("extra", [(), ("--lock-fd", "7"), ("--floor", "3")],
                         ids=["neither", "no-floor", "no-lock"])
def test_a_maintenance_lane_never_starts_without_an_inherited_lock(tmp_path, monkeypatch, extra):
    seen = main_world(monkeypatch)
    with pytest.raises(SystemExit):
        codex_lane.main(lane_command(tmp_path, *extra))
    assert seen["events"] == []


def test_the_command_line_never_runs_a_login_under_the_active_selection(tmp_path, monkeypatch):
    """CC-1, at the second of its two places."""

    seen = main_world(monkeypatch)
    with pytest.raises(BaseException) as raised:
        codex_lane.main(lane_command(tmp_path, "--custody", "active", "--sealed", "/x"))
    assert raised.type is SystemExit, raised.value
    assert seen["events"] == []


def test_the_login_deadline_covers_the_vendors_device_flow(tmp_path, monkeypatch):
    """RL-7: 900 s of vendor polling plus a margin, unless the operator states one."""

    seen = main_world(monkeypatch)
    codex_lane.main(lane_command(tmp_path, "--lock-fd=7", "--floor=3"))
    assert seen["deadline"] == codex_lane.LOGIN_DEADLINE_S == 960.0
    seen = main_world(monkeypatch)
    codex_lane.main(lane_command(
        tmp_path, "--lock-fd=7", "--floor=3", evidence=tmp_path / "startup.json",
        lane="startup",
    ))
    assert seen["deadline"] == codex_lane.STARTUP_DEADLINE_S


@pytest.mark.parametrize("extra", [
    ("--hold", "120"), ("--hold", "-1"), ("--first-login",),
], ids=["hold-at-deadline", "negative-hold", "first-login-for-startup"])
def test_startup_options_are_bounded_and_lane_specific(tmp_path, monkeypatch, extra):
    seen = main_world(monkeypatch)
    with pytest.raises(SystemExit):
        codex_lane.main(lane_command(tmp_path, "--lock-fd=7", "--floor=3", *extra,
                                     lane="startup"))
    assert seen["events"] == []


def test_a_login_takes_no_hold(tmp_path, monkeypatch):
    seen = main_world(monkeypatch)
    with pytest.raises(SystemExit):
        codex_lane.main(lane_command(tmp_path, "--lock-fd=7", "--floor=3", "--hold", "1"))
    assert seen["events"] == []


def test_an_unusable_evidence_path_refuses_before_any_launch(tmp_path, monkeypatch):
    """RL-2: a duplicate or missing-parent path is found first, not last."""

    seen = main_world(monkeypatch)
    (tmp_path / "evidence.json").write_text("an earlier run")
    with pytest.raises(FileExistsError):
        codex_lane.main(lane_command(tmp_path, "--lock-fd=7", "--floor=3"))
    with pytest.raises(FileNotFoundError):
        codex_lane.main(lane_command(
            tmp_path, "--lock-fd=7", "--floor=3", evidence=tmp_path / "absent" / "e.json",
        ))
    assert seen["events"] == []
    assert (tmp_path / "evidence.json").read_text() == "an earlier run"


def test_a_failed_run_leaves_no_evidence_and_no_reservation(tmp_path, monkeypatch):
    seen = main_world(monkeypatch)

    async def crash(*args, **kwargs):
        raise RuntimeError("the lane failed")

    monkeypatch.setattr(codex_lane, "run_login", crash)
    with pytest.raises(RuntimeError):
        codex_lane.main(lane_command(tmp_path, "--lock-fd=7", "--floor=3"))
    assert seen["events"] == ["launcher", "enter", "exit"]
    assert sorted(os.listdir(tmp_path)) == ["config.toml"]


def test_the_first_login_flag_reaches_the_login_lane(tmp_path, monkeypatch):
    seen = main_world(monkeypatch)
    codex_lane.main(lane_command(tmp_path, "--lock-fd=7", "--floor=3", "--first-login"))
    assert seen["options"]["first_login"] is True


def test_the_lane_entry_point_runs_isolated_with_explicit_paths_only():
    """The controller invocation's shape: ``-I -S -B -c``, no site, no ``.pth``.

    The verify lane's import proof runs the real flat tree; this is the
    portable half, with this checkout's ``src`` and dependencies named
    explicitly instead of through site processing.
    """

    import subprocess
    import sys
    import sysconfig

    source = Path(codex_lane.__file__).parents[3]
    entry = (
        "import sys; sys.path[:0] = sys.argv[1:3]; del sys.argv[1:3]; "
        "from constructicon.substrate.executors.codex_lane import main; "
        "raise SystemExit(main())"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", entry, str(source),
         sysconfig.get_paths()["purelib"], "--help"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "--first-login" in result.stdout and "--binary" not in result.stdout


# --- the bound vendor client (CC-3) ---------------------------------------------


def test_the_executable_is_the_bound_vendor_client_hashed_from_its_source(tmp_path):
    tree = tmp_path / "native-codex"
    (tree / "bin").mkdir(parents=True)
    (tree / "bin" / "codex").write_bytes(b"pinned client")
    launcher = replace(bare_launcher(clean_native()), vendor=linux.NativeVendor(
        tree, tmp_path / "codex-models.json",
    ))
    assert codex_lane.vendor_executable(launcher) == Executable(
        "/opt/codex/bin/codex", hashlib.sha256(b"pinned client").hexdigest(),
    )
    assert codex_lane.RUNTIME_BINARY == linux.VENDOR_MOUNT + "/bin/codex"
    assert codex_lane.RUNTIME_CATALOG == linux.CATALOG_MOUNT == "/opt/codex-models.json"


def test_a_launcher_without_the_bound_vendor_runs_no_lane():
    with pytest.raises(Exception) as raised:
        codex_lane.vendor_executable(bare_launcher(clean_native()))
    assert raised.type is ContractViolation and "bound vendor" in str(raised.value)


def test_the_installed_launcher_binds_the_launch_sets_vendor(tmp_path):
    (tmp_path / "runtime.json").write_text(json.dumps({
        "runtime_digest": str(digest("runtime", 1, "x")), "policy": "/p",
        "policy_sha256": "0" * 64,
    }))
    launcher = codex_lane._launcher(tmp_path)
    assert launcher.vendor == linux.NativeVendor(
        tmp_path / "native-codex", tmp_path / "codex-models.json",
    )


# --- custody -----------------------------------------------------------------


async def test_active_custody_is_the_providers_own_path_and_releases_its_lock(
    tmp_path, monkeypatch,
):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    world.exclusive = True
    async with codex_lane.active_custody(world.binding()) as custody:
        assert custody.kind == "active" and custody.create_credential is None
        assert custody.detail == {"binding_digest": str(world.sealed.operator_binding_digest)}
        assert custody.check() == BindingCheck(world.sealed.operator_binding_digest)
        assert world.holder == custody.lock_fd
        fd = custody.open_credential()
        assert world.credential_opens == [fd]
        assert custody.facts(fd) == world.credential
        os.close(fd)
    assert world.holder is None, "leaving custody released the retained lock"


def test_maintenance_custody_carries_the_contexts_lock_check_and_floor(tmp_path, monkeypatch):
    world = StoreWorld(tmp_path)
    world.install(monkeypatch)
    with operator_store.maintain_offline(world.root, world.key, wait_s=0) as withdrawn:
        custody = codex_lane.maintenance_custody(withdrawn)
        assert custody.kind == "maintenance" and custody.lock_fd == withdrawn.lock_fd
        assert custody.detail == {"generation_floor": withdrawn.generation_floor}
        assert custody.check() == withdrawn.check()
        assert custody.create_credential == withdrawn.create_credential
