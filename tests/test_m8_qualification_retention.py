"""Retained authority metadata, with only POSIX/source primitives substituted.

The full stock-tool installation sequence remains in test_m8_host_runtime;
these portable cases execute the real retirement/replacement judges locally.
No authorization content is interpreted and no vendor executable runs.
"""

import hashlib
import json
import os
import stat
from contextlib import nullcontext
from pathlib import Path

import pytest
from scripts.ci import m8_host_artifacts as artifacts

from tests.test_m8_host_artifacts import KERNEL_LIST, feed

COMMIT = "a" * 40
QUALIFICATION = "qualification"


@pytest.fixture
def authority_host(tmp_path, monkeypatch):
    root = tmp_path / "host"
    launch = root / artifacts.LAUNCH
    launch.mkdir(parents=True)
    store = launch / artifacts.STORE
    store.mkdir()
    authority = launch / QUALIFICATION
    authority.mkdir()
    files = {
        "stage3-read-g6.json": b"expired READ authority retained unchanged\n",
        "stage4-write.json": b"opaque WRITE authority history, not admission input\n",
    }
    for name, content in files.items():
        (authority / name).write_bytes(content)
    profile = root / artifacts.LAUNCH_PROFILE_DESTINATION
    profile.parent.mkdir(parents=True)
    profile.write_bytes(b"profile")
    for name in artifacts.DISPOSABLE:
        path = launch / name
        if name in ("runtime", "native-codex"):
            path.mkdir()
        else:
            path.write_bytes(b"artifact")
    for name in artifacts.RETIRE_ROOT_TOOLS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"tool")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    table = tmp_path / "mountinfo"
    table.write_text("22 1 8:1 / / rw - ext4 /dev/sda1 rw\n")
    modes, owners, groups = {}, {}, {store: 17}
    original = os.lstat

    def lstat(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        path = Path(path)
        fields = list(info[:10])
        mode = artifacts.STORE_MODE if path == store else 0o755
        if path == profile or path.name in ("runtime.json", "codex-models.json"):
            mode = 0o444
        elif path == launch / "bwrap":
            mode = 0o555
        fields[0] = modes.get(path, stat.S_IFMT(info.st_mode) | mode)
        fields[4] = owners.get(path, 0 if path.is_relative_to(root) else 1000)
        fields[5] = groups.get(path, 0)
        return os.stat_result(fields)

    monkeypatch.setattr(artifacts.os, "lstat", lstat)
    monkeypatch.setattr(artifacts, "ROOT", root)
    monkeypatch.setattr(artifacts, "MOUNTINFO", table)
    blobs = {artifacts.LAUNCH_PROFILE: b"profile"}
    values = {"codex_sha256": "synthetic", "bwrap_sha256": hashlib.sha256(b"artifact").hexdigest(),
              "catalog_sha256": hashlib.sha256(b"artifact").hexdigest()}
    expected = {"runtime": [(".", 0o755, "directory")],
                "vendor": [(".", 0o755, "directory")],
                "runtime.json": b"artifact", "catalog": b"artifact"}
    monkeypatch.setattr(artifacts, "launch_inputs", lambda *args: (blobs, values))
    monkeypatch.setattr(artifacts, "open_vendor", lambda *args: nullcontext(None))
    monkeypatch.setattr(artifacts, "launch_expectation", lambda *args: expected)
    monkeypatch.setattr(artifacts.os, "geteuid", lambda: 1000, raising=False)
    for name in (artifacts.BWRAP_SOURCE, *artifacts.LAUNCH_ROOT_TOOLS):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"artifact")
    monkeypatch.setattr(artifacts, "service_account", lambda *args: 17)
    # O_NOFOLLOW is the substituted Windows primitive, not a relaxed judge.
    monkeypatch.setattr(artifacts, "read_regular", lambda path: path.read_bytes())
    monkeypatch.setattr(artifacts, "open_regular", lambda path: path.open("rb"))
    return root, launch, authority, workspace, table, modes, owners, groups, files


def retirement_record(host):
    root, _, _, workspace, *_ = host
    record = {"command": "judge-retire", "commit": COMMIT, "ready": False}
    artifacts.judge_retire(COMMIT, root, workspace, KERNEL_LIST, record)
    assert record["ready"] is True
    (workspace / artifacts.RETIREMENT).write_text(json.dumps(record))
    return record


def remove_disposable(host):
    root, launch, *_ = host
    for name in artifacts.DISPOSABLE:
        path = launch / name
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()
    (root / artifacts.LAUNCH_PROFILE_DESTINATION).unlink()


def stage_replacement(host):
    workspace = host[3]
    staging = workspace / artifacts.STAGING
    staging.mkdir()
    for name in artifacts.STAGED:
        path = staging / name
        if name in ("runtime", "native-codex"):
            path.mkdir()
        else:
            path.write_bytes(b"profile" if name == "constructicon-m8-launch" else b"artifact")


def install_replacement(host):
    root, launch, *_ = host
    for name in artifacts.DISPOSABLE:
        path = launch / name
        if name in ("runtime", "native-codex"):
            path.mkdir()
        else:
            path.write_bytes(b"artifact")
    (root / artifacts.LAUNCH_PROFILE_DESTINATION).write_bytes(b"profile")


ACTIVE = KERNEL_LIST + "constructicon-m8-launch (enforce)\nconstructicon-m8-workload (enforce)\n"


def prepare_command(host, command):
    if command == "judge-retire":
        return artifacts.judge_retire, KERNEL_LIST
    retirement_record(host)
    remove_disposable(host)
    if command == "judge-launch":
        stage_replacement(host)
        return artifacts.judge_launch, KERNEL_LIST
    if command == "verify-launch":
        install_replacement(host)
        return artifacts.verify_launch, ACTIVE
    return artifacts.verify_retired, KERNEL_LIST


def test_retirement_preserves_installed_read_and_write_authority_without_interpreting_it(
    authority_host,
):
    root, _, authority, workspace, *_, files = authority_host
    before = os.lstat(authority)
    record = retirement_record(authority_host)
    assert record["retained"]["qualification"] == {"dev": before.st_dev, "ino": before.st_ino}
    remove_disposable(authority_host)
    verified = {}
    artifacts.verify_retired(COMMIT, root, workspace, KERNEL_LIST, verified)
    assert verified["retired"] is True
    assert {path.name: path.read_bytes() for path in authority.iterdir()} == files
    assert QUALIFICATION not in artifacts.DISPOSABLE
    stage_replacement(authority_host)
    judgement = {}
    artifacts.judge_launch(COMMIT, root, workspace, KERNEL_LIST, judgement)
    assert judgement["ready"] is True and judgement["replacement"] is True
    install_replacement(authority_host)
    installed = {}
    artifacts.verify_launch(COMMIT, root, workspace, ACTIVE, installed)
    assert installed["installed"] is True and installed["replacement"] is True
    assert {path.name: path.read_bytes() for path in authority.iterdir()} == files
    assert os.lstat(authority).st_ino == before.st_ino


@pytest.mark.parametrize(
    "command", ["judge-retire", "verify-retired", "judge-launch", "verify-launch"],
)
@pytest.mark.parametrize(
    "fault", ["owner", "group", "mode", "file", "symlink", "mount", "ancestor"],
)
def test_each_retained_authority_custody_guard_refuses(authority_host, command, fault):
    root, _, authority, workspace, table, modes, owners, groups, _ = authority_host
    function, listing = prepare_command(authority_host, command)
    if fault == "owner":
        owners[authority] = 123
    elif fault == "group":
        groups[authority] = 123
    elif fault == "mode":
        modes[authority] = stat.S_IFDIR | 0o775
    elif fault == "file":
        modes[authority] = stat.S_IFREG | 0o755
    elif fault == "symlink":
        modes[authority] = stat.S_IFLNK | 0o777
    elif fault == "mount":
        table.write_text(f"22 1 8:1 / {authority.as_posix()}/history rw - tmpfs tmpfs rw\n")
    else:
        owners[root / "var/lib"] = 123
    with pytest.raises(ValueError):
        function(COMMIT, root, workspace, listing, {})


@pytest.mark.parametrize("command", ["verify-retired", "judge-launch", "verify-launch"])
@pytest.mark.parametrize("fault", ["substitution", "disappearance", "missing fact"])
def test_recorded_authority_identity_cannot_disappear_or_be_inferred(
    authority_host, command, fault,
):
    root, _, authority, workspace, *_ = authority_host
    function, listing = prepare_command(authority_host, command)
    if fault == "missing fact":
        path = workspace / artifacts.RETIREMENT
        record = json.loads(path.read_text())
        del record["retained"]["qualification"]
        path.write_text(json.dumps(record))
    else:
        moved = authority.with_name("qualification-history")
        authority.rename(moved)
        if fault == "substitution":
            authority.mkdir()
        # Preserve history outside L; the only changed retained fact is identity.
        moved.rename(root / "history")
    with pytest.raises(ValueError, match=r"qualification|authority"):
        function(COMMIT, root, workspace, listing, {})


@pytest.mark.parametrize(
    "command", ["judge-retire", "verify-retired", "judge-launch", "verify-launch"],
)
def test_unknown_launch_sibling_is_not_authority(authority_host, command):
    root, launch, _, workspace, *_ = authority_host
    function, listing = prepare_command(authority_host, command)
    (launch / "qualification-other").mkdir()
    with pytest.raises(ValueError):
        function(COMMIT, root, workspace, listing, {})


def test_observed_absence_is_pinned_before_install_but_allows_later_root_creation(
    authority_host, monkeypatch, capsys,
):
    root, _, authority, workspace, *_ = authority_host
    authority.rename(root / "history")
    record = retirement_record(authority_host)
    assert record["retained"]["qualification"] is None
    remove_disposable(authority_host)
    authority.mkdir()
    with pytest.raises(ValueError, match="authority"):
        artifacts.require_kept(COMMIT, root, workspace, 17)
    authority.rmdir()
    artifacts.require_kept(COMMIT, root, workspace, 17)
    install_replacement(authority_host)
    authority.mkdir()
    feed(monkeypatch, ACTIVE)
    assert artifacts.main(["verify-launch", COMMIT, str(workspace)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["installed"] is True


def test_ordinary_postinstall_verifier_checks_authority_even_without_a_retirement_record(
    authority_host,
):
    root, _, authority, workspace, _, _, owners, _, _ = authority_host
    verified = {}
    artifacts.verify_launch(COMMIT, root, workspace, ACTIVE, verified)
    assert verified["installed"] is True and verified["replacement"] is False
    owners[authority] = 123
    with pytest.raises(ValueError, match="root:root"):
        artifacts.verify_launch(COMMIT, root, workspace, ACTIVE, {})


@pytest.mark.parametrize(
    "fault", ["owner", "group", "mode", "file", "symlink", "mount", "ancestor"],
)
def test_optional_authority_metadata_law_refuses_each_unsafe_premise(authority_host, fault):
    root, _, authority, _, table, modes, owners, groups, _ = authority_host
    if fault == "owner":
        owners[authority] = 123
    elif fault == "group":
        groups[authority] = 123
    elif fault == "mode":
        modes[authority] = stat.S_IFDIR | 0o775
    elif fault == "file":
        modes[authority] = stat.S_IFREG | 0o755
    elif fault == "symlink":
        modes[authority] = stat.S_IFLNK | 0o777
    elif fault == "mount":
        table.write_text(f"22 1 8:1 / {authority.as_posix()} rw - tmpfs tmpfs rw\n")
    else:
        owners[root / "var/lib"] = 123
    with pytest.raises(ValueError):
        artifacts.retained_qualification(root)


@pytest.mark.parametrize("command", ["verify-retired", "judge-launch", "verify-launch"])
def test_retained_store_identity_is_still_preserved(authority_host, command):
    root, launch, _, workspace, *_ = authority_host
    function, listing = prepare_command(authority_host, command)
    (launch / artifacts.STORE).rename(root / "store-history")
    (launch / artifacts.STORE).mkdir()
    with pytest.raises(ValueError, match="not the store judge-retire found"):
        function(COMMIT, root, workspace, listing, {})


def test_retirement_requires_an_explicit_authority_presence_fact(authority_host):
    record = retirement_record(authority_host)
    del record["retained"]["qualification"]
    workspace = authority_host[3]
    (workspace / artifacts.RETIREMENT).write_text(json.dumps(record))
    with pytest.raises(ValueError, match="no observed qualification presence or absence"):
        artifacts.retirement(COMMIT, workspace)


@pytest.mark.parametrize("installed", [True, False])
def test_launch_entry_law_names_only_the_exact_optional_sibling(installed):
    base = set(artifacts.LAUNCH_ENTRIES) if installed else {artifacts.STORE}
    assert artifacts.launch_entries(None, installed=installed) == base
    assert artifacts.launch_entries({"dev": 1, "ino": 2}, installed=installed) == (
        base | {QUALIFICATION}
    )


def test_authority_observation_never_hashes_even_a_malformed_authority_file(
    authority_host, monkeypatch,
):
    root, _, authority, *_ = authority_host
    authority.rename(root / "history")
    authority.write_bytes(b"opaque bytes never read by the observer")
    hashed = []

    def hash_regular(path):
        hashed.append(path)
        return "synthetic artifact hash"

    monkeypatch.setattr(artifacts, "hash_regular", hash_regular)
    observed = artifacts.observe_launch(root, KERNEL_LIST)
    assert authority not in hashed
    assert observed["/" + artifacts.LAUNCH + "/" + QUALIFICATION]["state"] == "file"
    assert "sha256" not in observed["/" + artifacts.LAUNCH + "/" + QUALIFICATION]


def test_judge_retire_accepts_existing_read_and_write_authority(
    authority_host, monkeypatch, capsys,
):
    feed(monkeypatch, KERNEL_LIST)
    assert artifacts.main(["judge-retire", COMMIT, str(authority_host[3])]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["ready"] is True and record["retained"]["qualification"] is not None


def test_authority_lookup_failure_is_not_observed_absence(authority_host, monkeypatch):
    root, _, authority, *_ = authority_host
    lstat = artifacts.os.lstat

    def denied(path, *args, **kwargs):
        if Path(path) == authority:
            raise PermissionError("synthetic denied lookup")
        return lstat(path, *args, **kwargs)

    monkeypatch.setattr(artifacts.os, "lstat", denied)
    with pytest.raises(PermissionError, match="synthetic denied lookup"):
        artifacts.retained_qualification(root)
