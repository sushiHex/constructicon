"""Credential-free proofs for the proposed Claude host artifact installer."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import claude_host_artifacts as host


def selection() -> bytes:
    return json.dumps({
        "schema_version": 1, "model": "reviewed-model", "effort": "low",
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
    }, sort_keys=True).encode()


def archive(path: Path, payload: bytes, *, duplicate: bool = False,
            kind: bytes = tarfile.REGTYPE, prelude: int = 0) -> bytes:
    with tarfile.open(path, "w:gz") as package:
        for index in range(prelude):
            package.addfile(tarfile.TarInfo(f"package/unused-{index}"))
        for _ in range(2 if duplicate else 1):
            item = tarfile.TarInfo("package/claude")
            item.type = kind
            item.size = len(payload) if kind == tarfile.REGTYPE else 0
            package.addfile(item, io.BytesIO(payload) if kind == tarfile.REGTYPE else None)
    return path.read_bytes()


def test_selection_is_closed_bounded_and_phase_specific():
    parsed = host.read_selection(selection())
    assert parsed["egress"]["login"]["connections"] == 4
    for value in (
        selection()[:-1] + b',"extra":true}',
        selection().replace(b'"model": "reviewed-model"',
                            b'"model": "reviewed-model", "model": "other"'),
        selection().replace(b'"8.8.8.8"', b'"127.0.0.1"'),
        selection().replace(b'"connections": 4', b'"connections": true'),
        selection().replace(b'"platform.claude.com"', b'"example.com"'),
        selection() + b" " * host.SELECTION_BYTES,
    ):
        with pytest.raises(ValueError):
            host.read_selection(value)


def test_archive_selects_only_pinned_regular_member_from_exact_bytes(tmp_path, monkeypatch):
    path = tmp_path / "claude.tgz"
    payload = b"synthetic, never executed"
    raw = archive(path, payload)
    monkeypatch.setattr(host, "ARCHIVE_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(host, "MEMBER_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(host, "MEMBER_SIZE", len(payload))
    assert host.read_vendor(path) == payload
    for defect in ("archive", "member", "duplicate", "link"):
        if defect == "archive":
            path.write_bytes(raw + b"changed")
        elif defect == "member":
            changed = b"synthetic, never execute!"
            assert len(changed) == len(payload)
            tampered = archive(path, changed)
            monkeypatch.setattr(host, "ARCHIVE_SHA256", hashlib.sha256(tampered).hexdigest())
        elif defect == "duplicate":
            tampered = archive(path, payload, duplicate=True)
            monkeypatch.setattr(host, "ARCHIVE_SHA256", hashlib.sha256(tampered).hexdigest())
        else:
            tampered = archive(path, payload, kind=tarfile.SYMTYPE)
            monkeypatch.setattr(host, "ARCHIVE_SHA256", hashlib.sha256(tampered).hexdigest())
        with pytest.raises(ValueError):
            host.read_vendor(path)


def test_archive_total_bytes_and_member_count_bounds_bind(tmp_path, monkeypatch):
    path = tmp_path / "claude.tgz"
    payload = b"inert member"
    raw = archive(path, payload)
    monkeypatch.setattr(host, "ARCHIVE_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(host, "MEMBER_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(host, "MEMBER_SIZE", len(payload))
    monkeypatch.setattr(host, "ARCHIVE_BYTES", len(raw) - 1)
    with pytest.raises(ValueError, match="bounded"):
        host.read_vendor(path)
    monkeypatch.setattr(host, "ARCHIVE_BYTES", len(raw) + 1024)
    many = archive(path, payload, prelude=host.ARCHIVE_MEMBERS)
    monkeypatch.setattr(host, "ARCHIVE_SHA256", hashlib.sha256(many).hexdigest())
    with pytest.raises(ValueError, match="too many members"):
        host.read_vendor(path)


def test_linked_selected_member_cannot_qualify_by_resolving_pinned_bytes(
    tmp_path, monkeypatch,
):
    path = tmp_path / "claude.tgz"
    payload = b"same bytes behind an inadmissible link"
    with tarfile.open(path, "w:gz") as package:
        target = tarfile.TarInfo("package/target")
        target.size = len(payload)
        package.addfile(target, io.BytesIO(payload))
        selected = tarfile.TarInfo("package/claude")
        selected.type = tarfile.SYMTYPE
        selected.linkname = "target"
        selected.size = len(payload)
        package.addfile(selected)
    monkeypatch.setattr(host, "ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(host, "MEMBER_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(host, "MEMBER_SIZE", len(payload))
    with pytest.raises(ValueError, match="kind or size"):
        host.read_vendor(path)


def test_emitted_config_is_closed_and_pins_installed_artifacts():
    raw = host.configuration_bytes(
        host.read_selection(selection()), runtime_digest="sha256:" + "1" * 64,
        vendor_digest="sha256:" + "2" * 64, policy_sha256="3" * 64,
    )
    value = json.loads(raw)
    assert set(value) == {
        "schema_version", "launch_root", "runtime_digest", "bubblewrap_sha256",
        "launch_policy", "launch_policy_sha256", "vendor_tree", "vendor_digest",
        "vendor_version", "model", "effort", "egress",
    }
    assert value["launch_root"] == "/var/lib/constructicon-m8-claude"
    assert value["vendor_tree"] == "/var/lib/constructicon-m8-claude/vendor"
    assert value["launch_policy"] == "/etc/apparmor.d/constructicon-m8-claude"
    assert value["runtime_digest"] == "sha256:" + "1" * 64
    assert value["vendor_digest"] == "sha256:" + "2" * 64
    assert raw.endswith(b"\n") and len(raw) <= host.CONFIG_BYTES


@pytest.fixture
def fake_plan(tmp_path, monkeypatch):
    workspace = tmp_path / "private"
    workspace.mkdir()
    (workspace / "selection.json").write_bytes(selection())
    payload = b"synthetic vendor bytes" * 256
    raw = archive(workspace / "claude.tgz", payload)
    monkeypatch.setattr(host, "ARCHIVE_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(host, "MEMBER_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(host, "MEMBER_SIZE", len(payload))
    monkeypatch.setattr(host, "FILE_BYTES", 4096)
    root = tmp_path / "host"
    root.mkdir()
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/bin/bwrap").write_bytes(b"fake bwrap bytes")
    (root / "etc/apparmor.d").mkdir(parents=True)
    (root / host.ABI).parent.mkdir(parents=True, exist_ok=True)
    (root / host.ABI).write_bytes(b"fake ABI bytes")
    source = tmp_path / "source.py"
    source.write_bytes(b"source")

    def source_blobs(commit, workspace_arg):
        assert commit == "a" * 40 and workspace_arg == workspace
        policy = (Path(host.__file__).parent / "constructicon-m8-claude.apparmor").read_bytes()
        return {host.POLICY_SOURCE: policy, host.SUPERVISOR: b"supervisor",
                host.BRIDGE: b"bridge"}

    def runtime_plan(host_root, blobs):
        assert host_root == root
        assert blobs[host.SUPERVISOR] == b"supervisor"
        return [host.Entry(".", "directory", 0o555, None),
                host.Entry("usr", "directory", 0o555, None),
                host.Entry("usr/bin", "directory", 0o555, None),
                host.Entry("usr/bin/python3", "file", 0o555, ("host", source)),
                host.Entry("opt", "directory", 0o555, None),
                host.Entry("opt/claude", "directory", 0o555, None),
                host.Entry("vendor-egress.sock", "file", 0o444, ("bytes", b""))]

    monkeypatch.setattr(host, "prove_sources", source_blobs)
    monkeypatch.setattr(host, "verify_source_constants",
                        lambda blobs: ("/usr/libexec/constructicon-supervisor.py",
                                       "/usr/libexec/constructicon-egress-bridge.py"))
    monkeypatch.setattr(host, "runtime_plan", runtime_plan)
    monkeypatch.setattr(host, "BWRAP_SHA256", hashlib.sha256(b"fake bwrap bytes").hexdigest())
    monkeypatch.setattr(host, "require_unprivileged", lambda: None)
    monkeypatch.setattr(host, "require_custody", lambda workspace_arg: None)
    monkeypatch.setattr(host, "require_root_file", lambda path: None)
    monkeypatch.setattr(host, "require_tools", lambda host_root: None)
    monkeypatch.setattr(host, "require_destination_ancestors", lambda host_root: None)
    monkeypatch.setattr(host, "ROOT_UID", os.stat(root).st_uid)
    if os.name == "nt":
        real_differences = host.differences

        def portable_differences(observed, expected, owner):
            # NTFS cannot represent POSIX modes; Linux hosted proof keeps this real.
            modes = {name: mode for name, mode, _ in expected}
            translated = tuple((name, modes.get(name, mode), content, uid)
                               for name, mode, content, uid in observed)
            return real_differences(translated, expected, owner)

        monkeypatch.setattr(host, "differences", portable_differences)
    return workspace, root


def test_stage_judge_verify_independent_of_staging_and_fail_closed(fake_plan):
    workspace, root = fake_plan
    staged = host.stage("a" * 40, workspace, host_root=root)
    expected = staged["launch_config_sha256"]
    assert staged["staged"] is True
    assert host.judge("a" * 40, workspace, expected_sha256="0" * 64,
                      profile_list="other (enforce)\n", host_root=root)["ready"] is False
    assert host.judge("a" * 40, workspace, expected_sha256=expected,
                      profile_list="other (enforce)\n", host_root=root)["ready"] is True
    installed = root / host.INSTALL_ROOT
    installed.parent.mkdir(parents=True)
    shutil.copytree(workspace / "staging" / "constructicon-m8-claude", installed)
    policy = root / host.POLICY_DEST
    policy.write_bytes((workspace / "staging" / "constructicon-m8-claude.apparmor").read_bytes())
    policy.chmod(0o444)
    assert host.verify("a" * 40, workspace, expected_sha256=expected,
                       profile_list=host.CLAUDE_PROFILES, host_root=root)["installed"] is True
    (workspace / "staging").rename(workspace / "stage-discarded-for-proof")
    assert host.verify("a" * 40, workspace, expected_sha256=expected,
                       profile_list=host.CLAUDE_PROFILES, host_root=root)["installed"] is True
    (installed / "vendor/claude").chmod(0o666)
    (installed / "vendor/claude").write_bytes(b"drift")
    assert host.verify("a" * 40, workspace, expected_sha256=expected,
                       profile_list=host.CLAUDE_PROFILES, host_root=root)["installed"] is False


def test_main_accepts_staged_then_installed_facts_without_private_values(
    fake_plan, monkeypatch, capsys,
):
    workspace, root = fake_plan
    monkeypatch.setattr(host, "HOST_ROOT", root)

    def call(command, *args, listing=""):
        monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(listing.encode())))
        result = host.main([command, "a" * 40, str(workspace), *args])
        output = capsys.readouterr().out
        assert "reviewed-model" not in output and "8.8.8.8" not in output
        return result, json.loads(output)

    code, staged = call("stage")
    assert code == 0 and staged["staged"] is True
    pin = staged["launch_config_sha256"]
    assert call("judge", "--launch-config-sha256", "0" * 64,
                listing="other (enforce)\n") == (1, {"ready": False})
    code, judged = call("judge", "--launch-config-sha256", pin,
                        listing="other (enforce)\n")
    assert code == 0 and judged["ready"] is True
    installed = root / host.INSTALL_ROOT
    installed.parent.mkdir(parents=True)
    shutil.copytree(workspace / "staging" / "constructicon-m8-claude", installed)
    policy = root / host.POLICY_DEST
    policy.write_bytes((workspace / "staging" / "constructicon-m8-claude.apparmor").read_bytes())
    policy.chmod(0o444)
    assert call("verify", "--launch-config-sha256", pin,
                listing="other (enforce)\n") == (1, {"installed": False})
    code, verified = call("verify", "--launch-config-sha256", pin,
                          listing=host.CLAUDE_PROFILES)
    assert code == 0 and verified["installed"] is True
    (workspace / "staging").rename(workspace / "stage-no-longer-at-name")
    assert call("verify", "--launch-config-sha256", pin,
                listing=host.CLAUDE_PROFILES)[0] == 0
    policy.chmod(0o666)
    assert call("verify", "--launch-config-sha256", pin,
                listing=host.CLAUDE_PROFILES) == (1, {"installed": False})
    policy.chmod(0o444)
    (installed / "extra").write_bytes(b"unreviewed")
    assert call("verify", "--launch-config-sha256", pin,
                listing=host.CLAUDE_PROFILES) == (1, {"installed": False})


def test_fresh_stage_and_target_are_mandatory(fake_plan):
    workspace, root = fake_plan
    pin = host.stage("a" * 40, workspace, host_root=root)["launch_config_sha256"]
    with pytest.raises(ValueError, match="fresh"):
        host.stage("a" * 40, workspace, host_root=root)
    destination = root / host.INSTALL_ROOT
    destination.parent.mkdir(parents=True)
    destination.mkdir()
    assert host.judge("a" * 40, workspace, expected_sha256=pin,
                      profile_list="other (enforce)\n", host_root=root) == {"ready": False}
    assert host.verify("a" * 40, workspace, expected_sha256=pin,
                       profile_list=host.CLAUDE_PROFILES, host_root=root) == {"installed": False}


def test_judge_rechecks_staged_bytes_not_prior_stage_report(fake_plan):
    workspace, root = fake_plan
    pin = host.stage("a" * 40, workspace, host_root=root)["launch_config_sha256"]
    placeholder = (workspace / "staging" / "constructicon-m8-claude" /
                   "runtime/vendor-egress.sock")
    placeholder.chmod(0o666)
    placeholder.write_bytes(b"changed after stage")
    assert host.judge("a" * 40, workspace, expected_sha256=pin,
                      profile_list="other (enforce)\n", host_root=root) == {"ready": False}


def test_plan_uses_one_runtime_inventory_even_if_host_source_changes_after_hash(
    fake_plan, monkeypatch,
):
    workspace, root = fake_plan
    source = workspace.parent / "source.py"
    original = host.inventory
    changed = False

    def drift_after_runtime_hash(entries):
        nonlocal changed
        result = original(entries)
        if not changed and any(item.name == "usr/bin/python3" for item in entries):
            changed = True
            source.write_bytes(b"changed after runtime hash")
        return result

    monkeypatch.setattr(host, "inventory", drift_after_runtime_hash)
    current = host.plan("a" * 40, workspace, root)
    assert changed
    expected = "sha256:" + host.sha256(b"source")
    runtime_record = json.loads(next(
        host.entry_bytes(item.source) for item in current.entries
        if item.name == "runtime.json"
    ))
    assert ["usr/bin/python3", 0o555, expected] in runtime_record["entries"]
    assert ("runtime/usr/bin/python3", 0o555, expected) in current.inventory


def test_plan_uses_checked_bwrap_identity_without_later_host_reread(fake_plan, monkeypatch):
    workspace, root = fake_plan
    bwrap = root / "usr/bin/bwrap"
    original = host.inventory
    changed = False

    def drift_after_runtime_hash(entries):
        nonlocal changed
        result = original(entries)
        if not changed and any(item.name == "usr/bin/python3" for item in entries):
            changed = True
            bwrap.write_bytes(b"changed after checked pin")
        return result

    monkeypatch.setattr(host, "inventory", drift_after_runtime_hash)
    current = host.plan("a" * 40, workspace, root)
    assert changed
    assert ("bwrap", 0o555, "sha256:" + host.BWRAP_SHA256) in current.inventory


def test_stage_refuses_host_source_drift_after_plan_before_copy(fake_plan, monkeypatch):
    workspace, root = fake_plan
    source = workspace.parent / "source.py"
    original = host.materialize

    def drift_before_copy(entries, destination):
        source.write_bytes(b"changed before staged copy")
        return original(entries, destination)

    monkeypatch.setattr(host, "materialize", drift_before_copy)
    with pytest.raises(ValueError, match="staging differs"):
        host.stage("a" * 40, workspace, host_root=root)


def test_judge_refuses_staged_and_host_drift_after_plan_before_staging_check(
    fake_plan, monkeypatch,
):
    workspace, root = fake_plan
    pin = host.stage("a" * 40, workspace, host_root=root)["launch_config_sha256"]
    captured = host.staging_inventory(host.plan("a" * 40, workspace, root))
    source = workspace.parent / "source.py"
    original_tree = host.tree_inventory
    original_differences = host.differences
    compared = []

    def drift_after_staging_read(top):
        if top == workspace / host.STAGING:
            source.write_bytes(b"changed after judge plan")
            staged = top / "constructicon-m8-claude/runtime/usr/bin/python3"
            staged.chmod(0o755)
            staged.write_bytes(b"changed after judge plan")
            staged.chmod(0o555)
        return original_tree(top)

    def compare(observed, expected, owner):
        compared.append(expected)
        return original_differences(observed, expected, owner)

    monkeypatch.setattr(host, "tree_inventory", drift_after_staging_read)
    monkeypatch.setattr(host, "differences", compare)
    assert host.judge("a" * 40, workspace, expected_sha256=pin,
                      profile_list="other (enforce)\n", host_root=root) == {"ready": False}
    assert compared == [captured]


def test_staging_expectation_projects_only_captured_plan_bytes(fake_plan):
    workspace, root = fake_plan
    current = host.plan("a" * 40, workspace, root)
    captured = dict((name, content) for name, _, content in current.inventory)
    (workspace.parent / "source.py").write_bytes(b"later host bytes")
    expected = host.staging_inventory(current)
    assert ("constructicon-m8-claude/runtime/usr/bin/python3", 0o555,
            captured["runtime/usr/bin/python3"]) in expected
    assert ("constructicon-m8-claude.apparmor", 0o444,
            "sha256:" + current.policy_sha256) in expected
    assert expected[0] == (".", 0o700, "directory")


def test_verify_accepts_unchanged_installed_artifact_after_host_source_change(
    fake_plan, monkeypatch,
):
    workspace, root = fake_plan
    pin = host.stage("a" * 40, workspace, host_root=root)["launch_config_sha256"]
    installed = root / host.INSTALL_ROOT
    installed.parent.mkdir(parents=True)
    shutil.copytree(workspace / "staging" / "constructicon-m8-claude", installed)
    policy = root / host.POLICY_DEST
    policy.write_bytes((workspace / "staging" / "constructicon-m8-claude.apparmor").read_bytes())
    policy.chmod(0o444)
    source = workspace.parent / "source.py"
    original = host.tree_inventory

    def drift_after_installed_read(top):
        observed = original(top)
        if top == installed:
            source.write_bytes(b"changed after verify plan")
        return observed

    monkeypatch.setattr(host, "tree_inventory", drift_after_installed_read)
    result = host.verify("a" * 40, workspace, expected_sha256=pin,
                         profile_list=host.CLAUDE_PROFILES, host_root=root)
    assert result["installed"] is True


def test_full_tree_comparison_includes_mode_owner_and_extra_entries():
    expected = ((".", 0o755, "directory"), ("vendor/claude", 0o555, "sha256:abc"))
    accepted = ((".", 0o755, "directory", 0),
                ("vendor/claude", 0o555, "sha256:abc", 0))
    assert host.differences(accepted, expected, 0) == []
    assert host.differences((accepted[0], ("vendor/claude", 0o777, "sha256:abc", 0)),
                            expected, 0) == ["vendor/claude"]
    assert host.differences((accepted[0], ("vendor/claude", 0o555, "sha256:abc", 123)),
                            expected, 0) == ["vendor/claude"]
    assert host.differences((*accepted, ("extra", 0o444, "sha256:xyz", 0)),
                            expected, 0) == ["extra"]


def test_first_parent_provenance_and_running_helper_bytes(tmp_path, monkeypatch):
    workspace = tmp_path / "private"
    workspace.mkdir()
    commit = "a" * 40
    head = "b" * 40
    blobs = {path: path.encode() for path in host.SOURCE_BLOBS}
    blobs[host.SCRIPT] = Path(host.__file__).read_bytes()
    object_ids = {path: f"{index + 1:040x}" for index, path in
                  enumerate(host.SOURCE_BLOBS)}
    by_oid = {object_ids[path]: data for path, data in blobs.items()}
    state = {"first_parent": True, "bad_mode": False}

    def git(repository, *arguments):
        assert repository == workspace / host.REPOSITORY
        if arguments[0] == "rev-parse":
            return subprocess.CompletedProcess(arguments, 0, (head + "\n").encode(), b"")
        if arguments[0] == "rev-list":
            line = commit + "\n" if state["first_parent"] else "c" * 40 + "\n"
            return subprocess.CompletedProcess(arguments, 0, line.encode(), b"")
        if arguments[0] == "ls-tree":
            path = arguments[-1]
            mode = "100755" if state["bad_mode"] and path == host.SCRIPT else "100644"
            line = f"{mode} blob {object_ids[path]}\t{path}\0"
            return subprocess.CompletedProcess(arguments, 0, line.encode(), b"")
        assert arguments[:2] == ("cat-file", "blob")
        return subprocess.CompletedProcess(arguments, 0, by_oid[arguments[2]], b"")

    monkeypatch.setattr(host, "git", git)
    assert host.prove_sources(commit, workspace)[host.SCRIPT] == blobs[host.SCRIPT]
    state["first_parent"] = False
    with pytest.raises(ValueError, match="first-parent"):
        host.prove_sources(commit, workspace)
    state["first_parent"] = True
    state["bad_mode"] = True
    with pytest.raises(ValueError, match="regular blob"):
        host.prove_sources(commit, workspace)
    state["bad_mode"] = False
    by_oid[object_ids[host.SCRIPT]] = b"altered helper"
    with pytest.raises(ValueError, match="differs"):
        host.prove_sources(commit, workspace)


def test_runtime_identity_matches_production_linux_digest(tmp_path):
    from constructicon.substrate.executors.linux import runtime_digest, runtime_inventory

    root = tmp_path / "runtime"
    root.mkdir()
    (root / "vendor-egress.sock").write_bytes(b"")
    (root / "entry").write_bytes(b"finite")
    actual = runtime_inventory(root, require_immutable=False)
    assert host.identity_digest("linux-runtime-root", actual) == str(
        runtime_digest(root, require_immutable=False))


def test_empty_runtime_module_is_staged_and_inventoried(fake_plan):
    workspace, root = fake_plan
    empty = workspace / "__init__.py"
    empty.write_bytes(b"")
    original = host.runtime_plan

    def with_empty_module(host_root, blobs):
        entries = original(host_root, blobs)
        entries.extend([
            host.Entry("usr/lib", "directory", 0o555, None),
            host.Entry("usr/lib/python3.12", "directory", 0o555, None),
            host.Entry("usr/lib/python3.12/__init__.py", "file", 0o444,
                       ("host", empty)),
        ])
        return entries

    from pytest import MonkeyPatch

    with MonkeyPatch.context() as patch:
        patch.setattr(host, "runtime_plan", with_empty_module)
        staged = host.stage("a" * 40, workspace, host_root=root)
        copied = (workspace / "staging/constructicon-m8-claude/runtime/usr/lib/"
                  "python3.12/__init__.py")
        assert copied.read_bytes() == b""
        assert host.judge("a" * 40, workspace,
                          expected_sha256=staged["launch_config_sha256"],
                          profile_list="other (enforce)\n", host_root=root)["ready"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX runtime source custody requires Linux")
def test_runtime_plan_accepts_empty_stdlib_module(tmp_path, monkeypatch):
    root = tmp_path / "host"
    required = [host.PYTHON, host.GIT_BINARY, host.TRUST_BUNDLE,
                "bin/sh", host.LOADER, host.LOADER_CACHE, host.ABI]
    required += [f"{host.HOST_LIB}/{name}" for name in host.EXTRA_LIBRARIES]
    for name in required:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic fixed host file")
        path.chmod(0o555)
    module = root / host.LIBRARY / "pydoc_data" / "__init__.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_bytes(b"")
    monkeypatch.setattr(host, "ROOT_UID", root.stat().st_uid)
    monkeypatch.setattr(host, "require_root_file", lambda path: None)
    monkeypatch.setattr(host, "source_path", lambda host_root, path: path)
    monkeypatch.setattr(host, "require_original_path", lambda path, host_root: None)
    monkeypatch.setattr(host, "checked_dependencies", lambda host_root, binary: [])
    monkeypatch.setattr(host, "verify_source_constants",
                        lambda blobs: ("/usr/libexec/constructicon-supervisor.py",
                                       "/usr/libexec/constructicon-egress-bridge.py"))
    entries = host.runtime_plan(root, {host.SUPERVISOR: b"supervisor",
                                       host.BRIDGE: b"bridge"})
    found = next(entry for entry in entries if entry.name ==
                 f"{host.LIBRARY}/pydoc_data/__init__.py")
    assert host.entry_bytes(found.source) == b""
    assert (found.name, 0o444, "sha256:" + host.sha256(b"")) in host.inventory(entries)


def test_pins_equal_existing_credential_free_fixture_and_launcher():
    from scripts.ci import build_m8_claude_startup_fixture as fixture

    from constructicon.substrate.executors.claude_protocol import CLAUDE_CODE_VERSION
    from constructicon.substrate.executors.linux import BWRAP_SHA256

    assert (host.ARCHIVE_SHA256, host.MEMBER_SHA256, host.MEMBER_SIZE, host.VERSION) == (
        fixture.ARCHIVE_SHA256, fixture.MEMBER_SHA256, fixture.MEMBER_SIZE,
        fixture.VERSION,
    )
    assert host.VERSION == CLAUDE_CODE_VERSION
    assert host.BWRAP_SHA256 == BWRAP_SHA256


def test_production_policy_has_exact_three_profiles_and_fixed_launcher():
    policy = (Path(host.__file__).parent / "constructicon-m8-claude.apparmor").read_bytes()
    host.require_policy(policy)
    with pytest.raises(ValueError, match="unexpected profiles"):
        host.require_policy(policy + b"\nprofile extra /bin/sh {}\n")
    with pytest.raises(ValueError, match="another executable"):
        host.require_policy(policy.replace(b"/var/lib/constructicon-m8-claude/bwrap",
                                           b"/tmp/bwrap"))


@pytest.mark.parametrize("untrusted", ["loader", "input"])
def test_loader_and_input_custody_precede_any_loader_execution(
    tmp_path, monkeypatch, untrusted,
):
    root = tmp_path / "host"
    loader = root / host.LOADER
    binary = root / "usr/bin/python3.12"
    for path in (loader, binary):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic, not executed")
    calls = []

    def source_path(host_root, path):
        calls.append(("guard", path))
        if path == (loader if untrusted == "loader" else binary):
            raise ValueError("untrusted source")
        return path

    def resolve(loader_arg, binary_arg):
        calls.append(("execute", loader_arg, binary_arg))
        return []

    monkeypatch.setattr(host, "source_path", source_path)
    monkeypatch.setattr(host, "resolve_dependencies", resolve)
    with pytest.raises(ValueError, match="untrusted"):
        host.checked_dependencies(root, binary)
    assert not any(item[0] == "execute" for item in calls)


@pytest.mark.skipif(os.name == "nt", reason="POSIX usr-merge symlinks require Linux")
def test_root_owned_usr_merge_links_are_accepted_before_loader_trace(tmp_path, monkeypatch):
    root = tmp_path / "host"
    loader = root / "usr/lib64/ld-linux-x86-64.so.2"
    binary = root / "usr/bin/python3.12"
    for path in (loader, binary):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic, never executed")
        path.chmod(0o555)
    (root / "lib64").symlink_to("usr/lib64", target_is_directory=True)
    (root / "bin").symlink_to("usr/bin", target_is_directory=True)
    monkeypatch.setattr(host, "ROOT_UID", root.stat().st_uid)
    monkeypatch.setattr(host, "require_root_file", lambda path: None)
    calls = []

    def traced(loader_arg, binary_arg):
        calls.append((loader_arg, binary_arg))
        return ["/lib/x86_64-linux-gnu/libc.so.6"]

    monkeypatch.setattr(host, "resolve_dependencies", traced)
    assert host.checked_dependencies(root, root / "bin/python3.12") == [
        "/lib/x86_64-linux-gnu/libc.so.6"]
    assert calls == [(root / host.LOADER, root / "bin/python3.12")]
    (root / "lib64").unlink()
    (root / "lib64").symlink_to(tmp_path / "outside", target_is_directory=True)
    (tmp_path / "outside").mkdir()
    with pytest.raises(ValueError, match="escapes root"):
        host.checked_dependencies(root, root / "bin/python3.12")
    assert len(calls) == 1
