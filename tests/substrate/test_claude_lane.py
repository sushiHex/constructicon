"""Credential-free tests of the reviewed Claude maintenance entry surface."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.identity import Digest, digest
from constructicon.substrate.executors import claude_lane
from constructicon.substrate.executors.claude_maintenance_login import (
    ClaudeLoginConversationFacts,
    ClaudeLoginConversationLifecycle,
)
from constructicon.substrate.executors.claude_maintenance_mode import (
    ClaudeMaintenanceLifecycle,
    ClaudeMaintenanceObservation,
    ClaudeMaintenancePhase,
    ClaudeMaintenanceRefusalCode,
)
from constructicon.substrate.executors.claude_maintenance_session import (
    ClaudeMaintenanceSessionFacts,
    ClaudeMaintenanceSessionLifecycle,
    ClaudeMaintenanceSessionPhase,
)
from constructicon.substrate.executors.claude_native import ClaudeNativeRecipe
from constructicon.substrate.executors.claude_native_events import ClaudeSystemRecordCategory
from constructicon.substrate.executors.claude_protocol import (
    ClaudeApiKeySourceCategory,
    ClaudeInitializeVerdict,
    ClaudeModeMismatchReason,
    ClaudePlan,
    ClaudeTokenSourceCategory,
)
from constructicon.substrate.executors.claude_startup import (
    ClaudeSettingsMismatchReason,
    ClaudeStartupVerdict,
)
from constructicon.substrate.executors.claude_startup_qualification import (
    ClaudeQualificationLifecycle,
    ClaudeStartupQualificationFacts,
)
from constructicon.substrate.executors.linux import BWRAP_SHA256


def configuration(tmp_path: Path) -> Path:
    value = {
        "schema_version": 1,
        "launch_root": str(tmp_path / "launch"),
        "runtime_digest": "sha256:" + "1" * 64,
        "bubblewrap_sha256": BWRAP_SHA256,
        "launch_policy": str(tmp_path / "claude.apparmor"),
        "launch_policy_sha256": "2" * 64,
        "vendor_tree": str(tmp_path / "vendor"),
        "vendor_digest": "sha256:" + "3" * 64,
        "vendor_version": "2.1.296",
        "model": "reviewed-model",
        "effort": "low",
        "egress": {
            "login": {"destinations": [["platform.claude.com", 443, "8.8.8.8"]],
                      "connections": 4},
            "observe": {"destinations": [["platform.claude.com", 443, "8.8.8.8"],
                                         ["api.anthropic.com", 443, "1.1.1.1"]],
                        "connections": 6},
            "reload": {"destinations": [["platform.claude.com", 443, "8.8.8.8"],
                                        ["api.anthropic.com", 443, "1.1.1.1"]],
                       "connections": 6},
        },
    }
    path = tmp_path / "launch-config.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def args(tmp_path: Path, phase: str, *extra: str) -> list[str]:
    config = tmp_path / "launch-config.json"
    return [
        phase, "--launch-config", str(config),
        "--launch-config-sha256", hashlib.sha256(config.read_bytes()).hexdigest(),
        "--lane-dir", str(tmp_path / "lane"),
        "--evidence", str(tmp_path / "evidence.json"),
        *extra,
        "--store-root", str(tmp_path / "store"), "--key", "test-claude",
        "--custody=maintenance", "--lock-fd=9", "--floor=0",
    ]


def facts(phase: ClaudeMaintenanceSessionPhase) -> ClaudeMaintenanceSessionFacts:
    if phase is ClaudeMaintenanceSessionPhase.LOGIN:
        login = ClaudeLoginConversationFacts(
            ClaudeLoginConversationLifecycle.COMPLETED, True, True, True, 12,
        )
        mode = None
        process_clean = True
    elif phase is ClaudeMaintenanceSessionPhase.QUALIFY:
        login, mode, process_clean = None, None, True
    else:
        login = None
        mode = ClaudeMaintenanceObservation(
            ClaudeMaintenancePhase.OBSERVE if phase is ClaudeMaintenanceSessionPhase.OBSERVE
            else ClaudeMaintenancePhase.RELOAD,
            ClaudeInitializeVerdict.MODE_MATCH,
            ClaudeMaintenanceLifecycle.OBSERVED, 1, 0, True, True,
            token_source_category=ClaudeTokenSourceCategory.ABSENT,
            api_key_source_category=ClaudeApiKeySourceCategory.ABSENT,
        )
        process_clean = None
    return ClaudeMaintenanceSessionFacts(
        phase=phase, lifecycle=ClaudeMaintenanceSessionLifecycle.JOINED_CLEAN,
        login_facts=login, mode_observation=mode, relay_closed=True,
        custody_current=True, credential_closed=True, process_clean=process_clean,
        qualification=(ClaudeStartupQualificationFacts(
            ClaudeQualificationLifecycle.QUALIFIED, ClaudeInitializeVerdict.MODE_MATCH,
            ClaudeStartupVerdict.MATCH, ClaudeStartupVerdict.MATCH, 3, 0, True, True,
            token_source_category=ClaudeTokenSourceCategory.ABSENT,
            api_key_source_category=ClaudeApiKeySourceCategory.ABSENT,
        ) if phase is ClaudeMaintenanceSessionPhase.QUALIFY else None),
    )


def test_closed_config_selects_only_paired_launcher_and_phase_egress(tmp_path):
    path = configuration(tmp_path)
    loaded = claude_lane.read_configuration(
        path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    assert (loaded.launcher(ClaudeMaintenanceSessionPhase.LOGIN).claude_recipe
            is ClaudeNativeRecipe.LOGIN)
    assert (loaded.launcher(ClaudeMaintenanceSessionPhase.OBSERVE).claude_recipe
            is ClaudeNativeRecipe.STREAM_JSON)
    assert loaded.runtime_digest == Digest("sha256:" + "1" * 64)
    assert loaded.vendor_digest == Digest("sha256:" + "3" * 64)
    assert loaded.launch_policy_sha256 == "2" * 64
    launcher = loaded.launcher(ClaudeMaintenanceSessionPhase.LOGIN)
    assert launcher.expected_runtime == loaded.runtime_digest
    assert launcher.claude is not None and launcher.claude.expected_tree == loaded.vendor_digest
    assert set(loaded.egress) == {"login", "observe", "reload"}
    assert [item.host for item in loaded.egress["login"].destinations] == ["platform.claude.com"]
    assert {item.host for item in loaded.egress["observe"].destinations} == {
        "platform.claude.com", "api.anthropic.com",
    }
    assert loaded.launcher(ClaudeMaintenanceSessionPhase.QUALIFY).claude_recipe is (
        ClaudeNativeRecipe.STREAM_JSON
    )


@pytest.mark.parametrize("name,expected", [("pro", ClaudePlan.PRO), ("max", ClaudePlan.MAX)])
def test_actual_qualification_record_seals_for_exact_plan(tmp_path, name, expected):
    from constructicon.substrate.executors import claude_host
    from tests.substrate.test_claude_host import seal

    path = configuration(tmp_path)
    loaded = claude_lane.read_configuration(
        path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    phase = ClaudeMaintenanceSessionPhase.QUALIFY
    plan = ClaudePlan.PRO if name == "pro" else ClaudePlan.MAX
    record = claude_lane._record(
        facts(phase), loaded.launcher(phase), loaded.egress["observe"], loaded,
        selected_plan=plan,
    )
    record["completed"] = True
    evidence = tmp_path / "actual-qualification.json"
    assert claude_host.sealed_plan(seal(record, evidence), evidence, loaded) is expected


@pytest.mark.parametrize("source", [
    "claude_startup_qualification.py", "claude_initialize.py",
    "identity.py", "_lifetime.py",
])
def test_qualification_revision_binds_actual_source_bytes(monkeypatch, source):
    initial = claude_lane.qualification_revision()
    original = Path.read_bytes

    def changed(path):
        raw = original(path)
        return raw + b"# changed\n" if path.name == source else raw

    monkeypatch.setattr(Path, "read_bytes", changed)
    assert claude_lane.qualification_revision() != initial


@pytest.mark.parametrize("symbol", ["EvidenceFile", "_fsync_directory"])
def test_qualification_revision_binds_evidence_publication_source(monkeypatch, symbol):
    initial = claude_lane.qualification_revision()
    original = claude_lane.inspect.getsource

    def changed(obj):
        source = original(obj)
        return source + "\n# changed" if obj is getattr(claude_lane, symbol) else source

    monkeypatch.setattr(claude_lane.inspect, "getsource", changed)
    assert claude_lane.qualification_revision() != initial


def test_refused_qualification_retains_bounded_partial_facts(tmp_path):
    path = configuration(tmp_path)
    loaded = claude_lane.read_configuration(
        path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    phase = ClaudeMaintenanceSessionPhase.QUALIFY
    partial = replace(facts(phase), lifecycle=ClaudeMaintenanceSessionLifecycle.REFUSED,
                      process_clean=False)
    record = claude_lane._record(
        partial, loaded.launcher(phase), loaded.egress["observe"], loaded,
        selected_plan=ClaudePlan.PRO,
    )
    assert record["facts"]["lifecycle"] == "refused"
    assert record["facts"]["process_clean"] is False
    assert record["facts"]["qualification"]["lifecycle"] == "qualified"
    assert record["subscription_qualified"] is record["production_available"] is False


def test_config_hash_uses_exact_crlf_bytes(tmp_path):
    path = configuration(tmp_path)
    raw = path.read_bytes().replace(b'"schema_version": 1,',
                                    b'"schema_version": 1,\r\n', 1)
    assert b"\r\n" in raw
    path.write_bytes(raw)
    expected = hashlib.sha256(raw).hexdigest()
    loaded = claude_lane.read_configuration(path, expected_sha256=expected)
    assert loaded.configuration_sha256 == expected


def test_config_open_uses_nonblocking_nofollow_flags(tmp_path, monkeypatch):
    path = configuration(tmp_path)
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    seen = []

    def opened(name, flags):
        assert Path(name) == path
        seen.append(flags)
        return os.open(name, os.O_RDONLY)

    flags = SimpleNamespace(
        O_RDONLY=os.O_RDONLY, O_NONBLOCK=1 << 20, O_NOFOLLOW=1 << 21,
        O_BINARY=1 << 22,
        open=opened, fstat=os.fstat, read=os.read, close=os.close,
    )
    monkeypatch.setattr(claude_lane, "os", flags)
    assert claude_lane.read_configuration(path, expected_sha256=expected).runtime_digest
    assert len(seen) == 1
    assert seen[0] & flags.O_NONBLOCK
    assert seen[0] & flags.O_NOFOLLOW
    assert seen[0] & flags.O_BINARY


def test_opened_nonregular_config_refuses_even_if_identity_matches(tmp_path, monkeypatch):
    path = configuration(tmp_path)
    raw = path.read_bytes()
    expected = hashlib.sha256(raw).hexdigest()
    info = path.lstat()
    read_fd, write_fd = os.pipe()
    real_fstat = os.fstat
    calls = 0

    def opened(name, flags):
        assert Path(name) == path
        return read_fd

    def fstat(fd):
        if fd == read_fd:
            return SimpleNamespace(st_mode=stat.S_IFIFO | 0o600,
                                   st_dev=info.st_dev, st_ino=info.st_ino)
        return real_fstat(fd)

    def read(fd, maximum):
        nonlocal calls
        assert fd == read_fd
        calls += 1
        return raw if calls == 1 else b""

    monkeypatch.setattr(claude_lane.os, "open", opened)
    monkeypatch.setattr(claude_lane.os, "fstat", fstat)
    monkeypatch.setattr(claude_lane.os, "read", read)
    try:
        with pytest.raises(ValueError, match="changed"):
            claude_lane.read_configuration(path, expected_sha256=expected)
        assert calls == 0
        with pytest.raises(OSError):
            real_fstat(read_fd)
    finally:
        os.close(write_fd)


def test_regular_config_swap_refuses_even_with_same_bytes(tmp_path, monkeypatch):
    path = configuration(tmp_path)
    alternate = tmp_path / "alternate.json"
    alternate.write_bytes(path.read_bytes())
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    real_open = os.open

    def swapped(name, flags):
        assert Path(name) == path
        return real_open(alternate, flags)

    monkeypatch.setattr(claude_lane.os, "open", swapped)
    with pytest.raises(ValueError, match="changed"):
        claude_lane.read_configuration(path, expected_sha256=expected)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux FIFO and O_NOFOLLOW")
@pytest.mark.parametrize("replacement", ["fifo", "symlink"])
def test_linux_config_replacement_after_lstat_refuses_without_blocking(
    tmp_path, monkeypatch, replacement,
):
    path = configuration(tmp_path)
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    alternate = tmp_path / "alternate.json"
    alternate.write_bytes(path.read_bytes())
    real_open = os.open

    def swapped(name, flags):
        assert Path(name) == path
        path.unlink()
        if replacement == "fifo":
            os.mkfifo(path)
            assert flags & os.O_NONBLOCK
        else:
            path.symlink_to(alternate)
            assert flags & os.O_NOFOLLOW
        return real_open(path, flags)

    monkeypatch.setattr(claude_lane.os, "open", swapped)
    with pytest.raises((ValueError, OSError)):
        claude_lane.read_configuration(path, expected_sha256=expected)


@pytest.mark.parametrize("damage", ["duplicate", "extra", "boolean", "wrong-schema",
                                    "wrong-host",
                                    "wrong-port", "wrong-bubblewrap", "wrong-version",
                                    "oversized"])
def test_config_refuses_ambiguity_or_policy_widening_before_entry(tmp_path, damage):
    path = configuration(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if damage == "duplicate":
        path.write_text(path.read_text(encoding="utf-8").replace(
            '"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1,
        ), encoding="utf-8")
    elif damage == "extra":
        value["arbitrary_command"] = ["/bin/sh"]
    elif damage == "boolean":
        value["egress"]["login"]["connections"] = True
    elif damage == "wrong-schema":
        value["schema_version"] = 2
    elif damage == "wrong-host":
        value["egress"]["login"]["destinations"][0][0] = "api.anthropic.com"
    elif damage == "wrong-port":
        value["egress"]["login"]["destinations"][0][1] = 80
    elif damage == "wrong-bubblewrap":
        value["bubblewrap_sha256"] = "0" * 64
    elif damage == "wrong-version":
        value["vendor_version"] = "other-version"
    else:
        # The JSON remains valid and within the closed schema if the size guard
        # is removed; trailing whitespace alone exceeds the read bound.
        raw = json.dumps(value).encode("utf-8")
        path.write_bytes(raw + b" " * (claude_lane.CONFIG_BYTES + 1 - len(raw)))
    if damage not in {"duplicate", "oversized"}:
        path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises((ValueError, TypeError)):
        claude_lane.read_configuration(
            path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )


@pytest.mark.parametrize("phase", [ClaudeMaintenanceSessionPhase.LOGIN,
                                   ClaudeMaintenanceSessionPhase.OBSERVE,
                                   ClaudeMaintenanceSessionPhase.RELOAD,
                                   ClaudeMaintenanceSessionPhase.QUALIFY])
def test_main_reserves_evidence_and_publishes_only_finite_unqualified_facts(
    tmp_path, monkeypatch, capsys, phase,
):
    configured = configuration(tmp_path)
    if phase is ClaudeMaintenanceSessionPhase.QUALIFY:
        changed = json.loads(configured.read_text(encoding="utf-8"))
        changed["egress"]["reload"]["connections"] = 5
        configured.write_text(json.dumps(changed), encoding="utf-8")
    seen = []
    revisions = []
    original_publish = claude_lane.EvidenceFile.publish

    def publish(self, evidence):
        revision = original_publish(self, evidence)
        revisions.append(revision)
        return revision

    @contextmanager
    def inherit(root, key, lock_fd, *, generation_floor, parent):
        seen.append(("custody", root, key, lock_fd, generation_floor, parent))
        yield object()

    class PrivateIO:
        def __init__(self, *, input_fd, output_fd, error_fd, deadline):
            seen.append(("private", input_fd, output_fd, error_fd, deadline))

    async def engine(custody, launcher, policy, lane_dir, **kwargs):
        assert (tmp_path / "evidence.json").parent == tmp_path
        assert not (tmp_path / "evidence.json").exists()
        assert any(path.name.endswith(".pending") for path in tmp_path.iterdir())
        assert custody is not None and lane_dir == tmp_path / "lane"
        assert "reviewed_connections" not in kwargs
        remaining = kwargs["deadline"] - asyncio.get_running_loop().time()
        assert 0 < remaining <= (600 if phase is ClaudeMaintenanceSessionPhase.LOGIN else 120)
        assert (kwargs["operator"] is not None) == (phase is ClaudeMaintenanceSessionPhase.LOGIN)
        assert kwargs["selected_plan"] == (
            None if phase is ClaudeMaintenanceSessionPhase.LOGIN else ClaudePlan.PRO
        )
        assert launcher.claude_recipe is (
            ClaudeNativeRecipe.LOGIN if phase is ClaudeMaintenanceSessionPhase.LOGIN
            else ClaudeNativeRecipe.STREAM_JSON
        )
        assert launcher.limits.input_bytes == (
            4096 if phase is ClaudeMaintenanceSessionPhase.LOGIN else 8192
        )
        assert launcher.limits.stdout_bytes == (
            256 * 1024 if phase is ClaudeMaintenanceSessionPhase.LOGIN else 512 * 1024
        )
        if phase is ClaudeMaintenanceSessionPhase.QUALIFY:
            assert policy == claude_lane.read_configuration(
                tmp_path / "launch-config.json",
                expected_sha256=hashlib.sha256(
                    (tmp_path / "launch-config.json").read_bytes(),
                ).hexdigest(),
            ).egress["observe"]
        seen.append(("engine", phase))
        return facts(phase)

    monkeypatch.setattr(claude_lane, "inherit_maintenance", inherit)
    monkeypatch.setattr(claude_lane, "ClaudeOperatorFDIO", PrivateIO)
    monkeypatch.setattr(claude_lane, "run_maintenance_session", engine)
    monkeypatch.setattr(claude_lane.EvidenceFile, "publish", publish)
    selector = [] if phase is ClaudeMaintenanceSessionPhase.LOGIN else ["--selected-plan", "pro"]
    assert claude_lane.main(args(tmp_path, phase.value, *selector)) == 0
    assert capsys.readouterr().out == ""
    first = "private" if phase is ClaudeMaintenanceSessionPhase.LOGIN else "custody"
    assert seen[0][0] == first
    assert any(event[:5] == ("custody", tmp_path / "store", "test-claude", 9, 0)
               for event in seen)
    assert any(event[0] == "engine" for event in seen)
    written = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    assert written["completed"] is True
    assert written["subscription_qualified"] is False
    assert written["production_available"] is False
    assert written["facts"]["lifecycle"] == "joined-clean"
    assert written["facts"]["phase"] == phase.value
    assert revisions == [digest(claude_lane.EVIDENCE_DOMAIN, 1, written)]
    assert revisions != [digest("codex-authenticated-startup-evidence", 1, written)]
    assert written["launch_config_sha256"] == hashlib.sha256(
        (tmp_path / "launch-config.json").read_bytes(),
    ).hexdigest()
    if phase is ClaudeMaintenanceSessionPhase.LOGIN:
        assert written["facts"]["login"]["stdout_bytes"] == 12
    elif phase is ClaudeMaintenanceSessionPhase.QUALIFY:
        assert written["facts"]["qualification"]["request_writes"] == 3
        assert written["facts"]["qualification"]["model"] == "reviewed-model"
    else:
        assert written["facts"]["mode"]["request_writes"] == 1
        assert written["facts"]["mode"]["ui_records"] == 0
    serialized = json.dumps(written)
    for private in (str(tmp_path), "test-claude", "8.8.8.8", "1.1.1.1"):
        assert private not in serialized


def test_main_failure_abandons_reservation_without_leaking_private_exception(
    tmp_path, monkeypatch, capsys,
):
    configuration(tmp_path)

    @contextmanager
    def inherit(*args, **kwargs):
        yield object()

    class PrivateIO:
        def __init__(self, **kwargs):
            pass

    async def engine(*args, **kwargs):
        raise RuntimeError("private vendor output")

    monkeypatch.setattr(claude_lane, "inherit_maintenance", inherit)
    monkeypatch.setattr(claude_lane, "ClaudeOperatorFDIO", PrivateIO)
    monkeypatch.setattr(claude_lane, "run_maintenance_session", engine)
    assert claude_lane.main(args(tmp_path, "login")) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Claude maintenance entry refused\n"
    assert list(tmp_path.glob("*evidence*")) == []


@pytest.mark.parametrize(("phase", "extra"), [
    ("observe", ("--first-login", "--selected-plan", "pro")),
    ("observe", ()),
    ("reload", ()),
    ("login", ("--selected-plan", "max")),
    ("login", ("--command", "/bin/sh")),
])
def test_cli_rejects_invalid_phase_options_with_static_text_before_effects(
    tmp_path, monkeypatch, capsys, phase, extra,
):
    configuration(tmp_path)

    def no_read(path):
        raise AssertionError("configuration must not be opened")

    monkeypatch.setattr(claude_lane, "read_configuration", no_read)
    with pytest.raises(SystemExit) as caught:
        claude_lane.main(args(tmp_path, phase, *extra))
    assert caught.value.code == 2
    assert capsys.readouterr().err == "Claude maintenance entry refused\n"


def test_existing_evidence_refuses_before_store_or_engine(tmp_path, monkeypatch, capsys):
    configuration(tmp_path)
    (tmp_path / "evidence.json").write_text("existing", encoding="utf-8")

    entered = []

    def no_entry(*args, **kwargs):
        entered.append(True)
        raise AssertionError("store and engine must not be entered")

    monkeypatch.setattr(claude_lane, "inherit_maintenance", no_entry)
    assert claude_lane.main(args(tmp_path, "observe", "--selected-plan", "pro")) == 1
    assert capsys.readouterr().err == "Claude maintenance entry refused\n"
    assert (tmp_path / "evidence.json").read_text(encoding="utf-8") == "existing"
    assert entered == []


def test_wrong_reviewed_config_digest_refuses_before_reservation_or_store(
    tmp_path, monkeypatch, capsys,
):
    configuration(tmp_path)

    entered = []

    def no_entry(*args, **kwargs):
        entered.append(True)
        raise AssertionError("store must not be entered")

    monkeypatch.setattr(claude_lane, "inherit_maintenance", no_entry)
    command = args(tmp_path, "observe", "--selected-plan", "pro")
    command[command.index("--launch-config-sha256") + 1] = "0" * 64
    assert claude_lane.main(command) == 1
    assert capsys.readouterr().err == "Claude maintenance entry refused\n"
    assert not (tmp_path / "evidence.json").exists()
    assert entered == []


@pytest.mark.parametrize("phase", list(ClaudeMaintenanceSessionPhase))
def test_every_published_field_has_a_declared_finite_bound(tmp_path, phase):
    """A new public field must acquire a bound, not evade a secret blacklist."""
    path = configuration(tmp_path)
    loaded = claude_lane.read_configuration(
        path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    record = claude_lane._record(
        facts(phase), loaded.launcher(phase),
        loaded.egress["observe" if phase is ClaudeMaintenanceSessionPhase.QUALIFY
                      else phase.value], loaded,
        selected_plan=ClaudePlan.PRO if phase is ClaudeMaintenanceSessionPhase.QUALIFY else None,
    )
    published = tmp_path / "bounded-evidence.json"
    claude_lane.EvidenceFile(published, domain=claude_lane.EVIDENCE_DOMAIN).publish(record)
    record = json.loads(published.read_text(encoding="utf-8"))
    assert set(record) == {
        "schema_version", "subscription_qualified", "production_available", "facts",
        "runtime_digest", "vendor_digest", "launch_policy_sha256", "launch_config_sha256",
        "launch_revision", "egress", "completed",
    } | ({"qualification_revision"} if phase is ClaudeMaintenanceSessionPhase.QUALIFY else set())
    assert record["completed"] is True
    assert type(record["schema_version"]) is int and record["schema_version"] == 7
    assert record["subscription_qualified"] is record["production_available"] is False
    for key in ("runtime_digest", "vendor_digest", "launch_revision", *(
        ("qualification_revision",) if phase is ClaudeMaintenanceSessionPhase.QUALIFY else ()
    )):
        value = record[key]
        assert type(value) is str and len(value) == 71 and value.startswith("sha256:")
        assert set(value[7:]) <= set("0123456789abcdef")
    if phase is ClaudeMaintenanceSessionPhase.QUALIFY:
        assert record["qualification_revision"] == str(claude_lane.qualification_revision())
    for key in ("launch_policy_sha256", "launch_config_sha256"):
        assert type(record[key]) is str and len(record[key]) == 64
        assert set(record[key]) <= set("0123456789abcdef")
    assert set(record["egress"]) == {
        "enforcement_build_digest", "destination_policy_digest", "resolver_policy_digest",
        "tls_assumptions_digest", "configuration_digest",
    }
    for value in record["egress"].values():
        assert type(value) is str and len(value) == 71 and value.startswith("sha256:")
        assert set(value[7:]) <= set("0123456789abcdef")
    public = record["facts"]
    assert set(public) == {
        "phase", "lifecycle", "login", "mode", "relay_closed", "custody_current",
        "credential_closed", "process_clean",
    } | ({"qualification"} if phase is ClaudeMaintenanceSessionPhase.QUALIFY else set())
    assert public["phase"] in {"login", "observe", "reload", "qualify"}
    assert public["lifecycle"] in {"joined-clean", "refused", "incomplete"}
    for key in ("relay_closed", "custody_current", "credential_closed", "process_clean"):
        assert public[key] is None or type(public[key]) is bool
    if phase is ClaudeMaintenanceSessionPhase.LOGIN:
        assert public["mode"] is None
        login = public["login"]
        assert set(login) == {
            "lifecycle", "input_write_attempted", "stdin_closed", "stdout_eof", "stdout_bytes",
        }
        assert login["lifecycle"] in {"new", "running", "completed", "refused"}
        for key in ("input_write_attempted", "stdin_closed", "stdout_eof"):
            assert type(login[key]) is bool
        assert type(login["stdout_bytes"]) is int and 0 <= login["stdout_bytes"] <= 256 * 1024
    elif phase is ClaudeMaintenanceSessionPhase.QUALIFY:
        assert public["login"] is public["mode"] is None
        qual = public["qualification"]
        assert set(qual) == {"lifecycle", "initialize_verdict", "settings_verdict",
                             "settings_mismatch_reason", "mode_mismatch_reason",
                             "token_source_category", "api_key_source_category",
                             "hooks_verdict", "request_writes", "ui_records",
                             "stdin_closed", "eof", "selected_plan", "model", "effort"}
        assert qual["lifecycle"] in {item.value for item in ClaudeQualificationLifecycle}
        assert qual["initialize_verdict"] in {
            item.value for item in ClaudeInitializeVerdict
        } | {None}
        for key in ("settings_verdict", "hooks_verdict"):
            assert qual[key] in {item.value for item in ClaudeStartupVerdict} | {None}
        assert qual["settings_mismatch_reason"] in {
            item.value for item in ClaudeSettingsMismatchReason
        } | {None}
        assert qual["mode_mismatch_reason"] in {
            item.value for item in ClaudeModeMismatchReason
        } | {None}
        assert type(qual["request_writes"]) is int and 0 <= qual["request_writes"] <= 3
        assert type(qual["ui_records"]) is int and 0 <= qual["ui_records"] <= 8
        assert type(qual["stdin_closed"]) is type(qual["eof"]) is bool
        assert qual["selected_plan"] in {"pro", "max"}
        assert qual["model"] == loaded.model and qual["effort"] == loaded.effort
    else:
        assert public["login"] is None
        mode = public["mode"]
        assert set(mode) == {
            "phase", "mode_verdict", "mode_mismatch_reason", "classified_responses",
            "token_source_category", "api_key_source_category",
            "refusal_code", "rejected_system_category",
            "lifecycle", "request_writes", "ui_records",
            "stdin_closed", "eof",
        }
        assert mode["phase"] in {"observe", "reload"}
        assert mode["mode_verdict"] in {item.value for item in ClaudeInitializeVerdict} | {None}
        assert mode["mode_mismatch_reason"] in {
            item.value for item in ClaudeModeMismatchReason
        } | {None}
        count = mode["classified_responses"]
        assert mode["refusal_code"] in {
            code.value for code in ClaudeMaintenanceRefusalCode
        } | {None}
        assert mode["rejected_system_category"] in {
            category.value for category in ClaudeSystemRecordCategory
        } | {None}
        assert all(len(category.value.encode()) <= 32 for category in ClaudeSystemRecordCategory)
        assert mode["rejected_system_category"] is None  # This fixture is an observed phase.
        assert count is None or (type(count) is int and 0 <= count <= mode["request_writes"])
        assert mode["lifecycle"] in {"observed", "refused", "incomplete", "process-refused"}
        for key in ("stdin_closed", "eof"):
            assert type(mode[key]) is bool
        assert type(mode["request_writes"]) is int and 0 <= mode["request_writes"] <= 2
        assert type(mode["ui_records"]) is int and 0 <= mode["ui_records"] <= 8
    if phase is not ClaudeMaintenanceSessionPhase.LOGIN:
        diagnostic = (public["qualification"] if phase is ClaudeMaintenanceSessionPhase.QUALIFY
                      else public["mode"])
        for key, enum in (("token_source_category", ClaudeTokenSourceCategory),
                          ("api_key_source_category", ClaudeApiKeySourceCategory)):
            assert diagnostic[key] in {item.value for item in enum} | {None}
            assert all(len(item.value.encode()) <= 32 for item in enum)


@pytest.mark.parametrize("reason", [None, *ClaudeModeMismatchReason])
def test_public_mode_reason_is_only_closed_diagnostic_evidence(reason):
    original = facts(ClaudeMaintenanceSessionPhase.OBSERVE)
    mode = replace(
        original.mode_observation,
        mode_verdict=(ClaudeInitializeVerdict.MODE_MATCH if reason is None
                      else ClaudeInitializeVerdict.MODE_MISMATCH),
        lifecycle=ClaudeMaintenanceLifecycle.REFUSED, mode_mismatch_reason=reason,
        token_source_category=(None if reason is ClaudeModeMismatchReason.ACCOUNT_SHAPE
                               else ClaudeTokenSourceCategory.NULL if reason is
                               ClaudeModeMismatchReason.CREDENTIAL_SOURCE_PRESENT
                               else ClaudeTokenSourceCategory.ABSENT),
        api_key_source_category=(None if reason is ClaudeModeMismatchReason.ACCOUNT_SHAPE
                                 else ClaudeApiKeySourceCategory.ABSENT),
        classified_responses=1,
    )
    public = claude_lane._public_facts(replace(
        original, lifecycle=ClaudeMaintenanceSessionLifecycle.REFUSED, mode_observation=mode,
    ))
    assert public["mode"]["mode_mismatch_reason"] == (None if reason is None else reason.value)
    assert set(public["mode"]) == {
        "phase", "mode_verdict", "mode_mismatch_reason", "classified_responses", "lifecycle",
        "token_source_category", "api_key_source_category",
        "refusal_code", "rejected_system_category",
        "request_writes", "ui_records", "stdin_closed", "eof",
    }
    assert len(json.dumps(public)) < 1024
    assert all(len(item.value.encode()) <= 32 for item in ClaudeModeMismatchReason)
    assert "private" not in json.dumps(public)


@pytest.mark.parametrize("code", [None, *ClaudeMaintenanceRefusalCode])
def test_public_refusal_code_is_only_a_closed_first_guard_not_raw_data(code):
    original = facts(ClaudeMaintenanceSessionPhase.OBSERVE)
    mode = replace(original.mode_observation, lifecycle=ClaudeMaintenanceLifecycle.REFUSED,
                   refusal_code=code, rejected_system_category=(ClaudeSystemRecordCategory.OTHER
                   if code is ClaudeMaintenanceRefusalCode.UI_RECORD else None))
    public = claude_lane._public_facts(replace(
        original, lifecycle=ClaudeMaintenanceSessionLifecycle.REFUSED, mode_observation=mode,
    ))
    assert public["mode"]["refusal_code"] == (None if code is None else code.value)
    assert set(public["mode"]) == {
        "phase", "mode_verdict", "mode_mismatch_reason", "classified_responses", "refusal_code",
        "token_source_category", "api_key_source_category",
        "rejected_system_category",
        "lifecycle", "request_writes", "ui_records", "stdin_closed", "eof",
    }
    assert len(json.dumps(public)) < 1024
    assert "private" not in json.dumps(public)


@pytest.mark.parametrize("category", list(ClaudeSystemRecordCategory))
def test_public_rejected_system_category_is_only_a_closed_first_fault(category):
    original = facts(ClaudeMaintenanceSessionPhase.OBSERVE)
    mode = replace(original.mode_observation, lifecycle=ClaudeMaintenanceLifecycle.REFUSED,
                   refusal_code=ClaudeMaintenanceRefusalCode.UI_RECORD,
                   rejected_system_category=category)
    public = claude_lane._public_facts(replace(
        original, lifecycle=ClaudeMaintenanceSessionLifecycle.REFUSED, mode_observation=mode,
    ))
    assert public["mode"]["rejected_system_category"] == category.value
    assert public["mode"]["refusal_code"] == "ui-record"
    assert len(json.dumps(public)) < 1024
    assert "private" not in json.dumps(public)


@pytest.mark.parametrize("account,expected", [
    ("private-account", "ACCOUNT_SHAPE"),
    ({"private-field": "private-value"}, "UNSUPPORTED_ACCOUNT_FIELD"),
    ({"tokenSource": "private-source"}, "CREDENTIAL_SOURCE_PRESENT"),
    ({"email": {"private-nested": "private-value"}}, "ACCOUNT_VALUE_TYPE"),
    ({"apiProvider": "private-provider"}, "PROVIDER_MISMATCH"),
    ({"apiProvider": "firstParty", "subscriptionType": "Claude API",
      "email": "private-email", "organization": "private-organization"}, "AMBIGUOUS_API"),
    ({"apiProvider": "firstParty", "subscriptionType": "private-plan"}, "SUBSCRIPTION_MISMATCH"),
    ({"apiProvider": "firstParty", "subscriptionType": "Claude Pro",
      "email": "private-email", "organization": "private-organization"}, None),
])
async def test_wire_account_data_never_enters_published_mode_fields(account, expected):
    from tests.substrate.test_claude_maintenance_mode import Channel, observe, response

    value = json.loads(response("@ID@"))
    value["response"]["response"]["account"] = account
    raw = json.dumps(value, separators=(",", ":")).encode() + b"\n"
    report, _, _ = await observe(Channel([raw]), phase=ClaudeMaintenancePhase.RELOAD)
    original = facts(ClaudeMaintenanceSessionPhase.RELOAD)
    public = claude_lane._public_facts(replace(
        original, lifecycle=ClaudeMaintenanceSessionLifecycle.REFUSED, mode_observation=report,
    ))
    assert public["mode"]["mode_mismatch_reason"] == (
        None if expected is None else ClaudeModeMismatchReason[expected].value
    )
    assert public["mode"]["classified_responses"] == 1
    assert "private" not in json.dumps(public)
    assert len(json.dumps(public)) < 1024


@pytest.mark.parametrize("reason", list(ClaudeSettingsMismatchReason))
def test_public_qualification_reason_has_only_its_declared_finite_value(tmp_path, reason):
    path = configuration(tmp_path)
    config = claude_lane.read_configuration(
        path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    original = facts(ClaudeMaintenanceSessionPhase.QUALIFY)
    qualification = replace(
        original.qualification, lifecycle=ClaudeQualificationLifecycle.REFUSED,
        settings_verdict=ClaudeStartupVerdict.CONFIGURATION_MISMATCH,
        settings_mismatch_reason=reason, hooks_verdict=None,
        request_writes=2, stdin_closed=False, eof=False,
    )
    record = claude_lane._record(
        replace(original, lifecycle=ClaudeMaintenanceSessionLifecycle.REFUSED,
                qualification=qualification),
        config.launcher(ClaudeMaintenanceSessionPhase.QUALIFY), config.egress["observe"],
        config, selected_plan=ClaudePlan.MAX,
    )
    public = record["facts"]["qualification"]
    assert public["settings_mismatch_reason"] == reason.value
    assert set(public) == {
        "lifecycle", "initialize_verdict", "settings_verdict", "settings_mismatch_reason",
        "mode_mismatch_reason", "token_source_category", "api_key_source_category",
        "hooks_verdict", "request_writes", "ui_records", "stdin_closed", "eof",
        "selected_plan", "model", "effort",
    }
    assert len(public["settings_mismatch_reason"]) <= 24
