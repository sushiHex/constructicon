"""Physical Linux producer defaults behind a private traversal boundary."""

import inspect
import io
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import m8_procedure_package as package
from scripts.ci import m8_host_artifacts as host

LINUX = pytest.mark.skipif(sys.platform != "linux", reason="physical Linux custody observations")


def emitted():
    source = package.private_tree_inventory_source()
    scope = {}
    exec(compile(source, "selected-private-inventory", "exec"), scope)
    return source, scope["inventory"]


def test_emitted_inventory_uses_exact_shared_source_and_existing_mount_check(tmp_path):
    source, inventory = emitted()
    assert inspect.getsource(package.private_tree_inventory).encode() in source
    assert inspect.getsource(package.private_tree_facts).encode() in source
    assert inspect.getsource(host.mounts_beneath).encode() in source
    assert b"import scripts" not in source and b"from scripts" not in source
    if sys.platform != "linux":
        with pytest.raises(ValueError, match="Linux physical observations required"):
            inventory(tmp_path)


def test_shared_mount_matcher_consumes_checked_snapshot_without_rereading(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "MOUNTINFO", tmp_path / "missing-kernel-query")
    listing = "22 1 8:1 / /private/a\\040b rw - ext4 /dev/fixture rw\n"
    assert host.mounts_beneath(Path("/private"), listing=listing) == ["/private/a b"]


def test_emitted_source_runs_with_isolated_stdlib_python(tmp_path):
    source, _ = emitted()
    script = tmp_path / "selected-inventory.py"
    script.write_bytes(source + b'''
import sys
try:
    inventory(Path(sys.argv[1]))
except ValueError as exc:
    if sys.platform == "linux":
        raise
    assert str(exc) == "private tree: Linux physical observations required"
    sys.stdout.buffer.write(b"physical-inventory-unavailable\\n")
else:
    sys.stdout.buffer.write(b"physical-inventory-checked\\n")
''')
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(script), str(tmp_path)],
        stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=10,
    )
    assert result.returncode == 0 and not result.stderr
    assert result.stdout == (b"physical-inventory-checked\n" if sys.platform == "linux"
                             else b"physical-inventory-unavailable\n")


def produce(root):
    root.mkdir(mode=0o700)
    previous = os.umask(0o002)
    try:
        result = subprocess.run(
            ["git", "-c", "init.defaultBranch=main", "init", "--bare", str(root / "closure.git")],
            stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=10,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
        )
        assert result.returncode == 0, result.stderr
        trial = root / "trial"
        trial.mkdir()
        (trial / "trial-id").write_bytes(b"fixture-installed-trial\n")
        for suffix in ("", "-wal", "-shm"):
            (trial / ("journal.sqlite" + suffix)).write_bytes(
                b"synthetic closed archive sidecar " + suffix.encode())
    finally:
        os.umask(previous)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "trial").stat().st_mode) == 0o775
    assert stat.S_IMODE((root / "trial/trial-id").stat().st_mode) == 0o664
    assert stat.S_IMODE((root / "closure.git/objects").stat().st_mode) == 0o775
    return root


@LINUX
def test_native_git_umask002_inventory_is_repeatable_and_preserves_rename(tmp_path):
    root = produce(tmp_path / "state")
    before = package.private_tree_inventory(root, host.mounts_beneath)
    source, inventory = emitted()
    assert source
    assert inventory(root) == before == inventory(root)
    assert before["trial"]["mode"] == 0o775 and before["trial/trial-id"]["mode"] == 0o664
    destination = tmp_path / "preserved"
    root.rename(destination)
    assert inventory(destination) == before
    assert (destination / "trial/trial-id").read_bytes() == b"fixture-installed-trial\n"


@LINUX
def test_descendant_modes_are_observations_and_private_root_is_the_boundary(tmp_path):
    root = produce(tmp_path / "state")
    (root / "trial").chmod(0o777)
    (root / "trial/trial-id").chmod(0o666)
    _, inventory = emitted()
    observed = inventory(root)
    assert observed["trial"]["mode"] == 0o777
    assert observed["trial/trial-id"]["mode"] == 0o666
    assert observed == package.private_tree_inventory(root, host.mounts_beneath)
    root.chmod(0o777)
    with pytest.raises(ValueError, match="root mode"):
        package.private_tree_inventory(root, host.mounts_beneath)


@LINUX
def test_sidecar_facts_require_the_explicit_private_boundary(tmp_path):
    root = produce(tmp_path / "state")
    leaf = root / "trial/trial-id"
    assert stat.S_IMODE(package.private_tree_facts(leaf, root).st_mode) == 0o664
    with pytest.raises(ValueError, match="outside root"):
        package.private_tree_facts(tmp_path, root)
    root.chmod(0o775)
    with pytest.raises(ValueError, match="root mode"):
        package.private_tree_facts(leaf, root)


@LINUX
def test_facts_refuse_a_symlink_ancestor_even_when_leaf_is_regular(tmp_path):
    root = produce(tmp_path / "state")
    (root / "alias").symlink_to(root / "trial", target_is_directory=True)
    with pytest.raises(ValueError, match="noncanonical node"):
        package.private_tree_facts(root / "alias/trial-id", root)


@LINUX
@pytest.mark.parametrize("bad", ["root-mode", "root-file", "alias", "hardlink", "symlink", "fifo"])
def test_native_custody_refusals(tmp_path, bad):
    root = produce(tmp_path / "state")
    if bad == "root-mode":
        root.chmod(0o775)
    elif bad == "root-file":
        root = root / "trial/trial-id"
        root.chmod(0o700)
    elif bad == "alias":
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        root = alias
    elif bad == "hardlink":
        os.link(root / "trial/trial-id", root / "second-link")
    elif bad == "symlink":
        (root / "link").symlink_to(root / "trial/trial-id")
    else:
        os.mkfifo(root / "fifo")
    with pytest.raises(ValueError):
        package.private_tree_inventory(root, host.mounts_beneath)


@LINUX
def test_foreign_owner_refuses_native_system_directory():
    if os.geteuid() == 0:
        pytest.fail("physical inventory lane must run as an unprivileged owner")
    with pytest.raises(ValueError, match="ownership"):
        package.private_tree_inventory(Path("/"), host.mounts_beneath)


@LINUX
def test_foreign_descendant_and_mounted_tree_refuse(tmp_path, monkeypatch):
    root = produce(tmp_path / "state")
    leaf = root / "trial/trial-id"
    original = Path.lstat

    def foreign(path):
        info = original(path)
        if path == leaf:
            values = list(info)
            values[4] = info.st_uid + 1
            return os.stat_result(values)
        return info

    # Only the unavailable chown-to-another-user primitive is substituted here;
    # the producer/mode/traversal tests above use native Linux metadata.
    monkeypatch.setattr(Path, "lstat", foreign)
    with pytest.raises(ValueError, match="ownership"):
        package.private_tree_inventory(root, host.mounts_beneath)
    monkeypatch.undo()
    with pytest.raises(ValueError, match="mount at or beneath"):
        package.private_tree_inventory(root, lambda _, **kwargs: [str(root / "closure.git")])


@LINUX
@pytest.mark.parametrize("bad", ["empty", "malformed", "missing-root", "oversize", "read-error",
                                 "nested-mount"])
def test_emitted_inventory_refuses_unproved_or_nested_mount_snapshot(tmp_path, monkeypatch, bad):
    root = produce(tmp_path / "state")
    original = Path.open
    listing = b"22 1 8:1 / / rw - ext4 /dev/fixture rw\n"
    if bad == "empty":
        listing = b""
    elif bad == "malformed":
        listing += b"not a mount row\n"
    elif bad == "missing-root":
        listing = b"22 1 8:1 / /other rw - ext4 /dev/fixture rw\n"
    elif bad == "oversize":
        listing = b"x" * (8 * 1024 * 1024 + 1)
    elif bad == "nested-mount":
        point = (root / "closure.git").as_posix().replace(" ", "\\040")
        listing += f"23 22 8:1 /other {point} rw - ext4 /dev/fixture rw\n".encode()

    def mount_source(path, *args, **kwargs):
        if path == Path("/proc/self/mountinfo"):
            if bad == "read-error":
                raise OSError("fixture kernel query unavailable")
            return io.BytesIO(listing)
        return original(path, *args, **kwargs)

    # This substitutes only the kernel-query bytes/failure. Custody/producer
    # metadata and the emitted shared matcher execute on native Linux.
    monkeypatch.setattr(Path, "open", mount_source)
    with pytest.raises((ValueError, OSError)):
        package.private_tree_inventory(root, host.mounts_beneath)
    _, inventory = emitted()
    with pytest.raises((ValueError, OSError)):
        inventory(root)


@LINUX
@pytest.mark.parametrize("bad", [False, True])
def test_complete_archive_fixture_uses_emitted_inventory_before_any_mutation(tmp_path, bad):
    roots = {name: produce(tmp_path / name) for name in ("session", "state")}
    _, inventory = emitted()
    if bad:
        roots["state"].chmod(0o775)
    archive = tmp_path / "archive"
    mutations = []

    def preserve():
        before = {name: inventory(root) for name, root in roots.items()}
        # The archive's sidecar reader must bind facts to state, too. Replacing
        # only inventory while retaining a flat-mode sidecar guard is incomplete.
        facts = inventory.__globals__["private_tree_facts"]
        for suffix in ("", "-wal", "-shm"):
            path = roots["state"] / "trial" / ("journal.sqlite" + suffix)
            assert stat.S_IMODE(facts(path, roots["state"]).st_mode) == 0o664
            with pytest.raises(ValueError, match="outside root"):
                facts(path, roots["session"])
        archive.mkdir(mode=0o700)
        mutations.append("archive-created")
        for name, root in roots.items():
            assert inventory(root) == before[name]
            root.rename(archive / name)
            assert inventory(archive / name) == before[name]
            mutations.append(name + "-preserved")
        return before

    if bad:
        with pytest.raises(ValueError, match="root mode"):
            preserve()
        assert mutations == [] and not archive.exists()
        assert all(root.exists() for root in roots.values())
    else:
        before = preserve()
        assert mutations == ["archive-created", "session-preserved", "state-preserved"]
        assert all(inventory(archive / name) == before[name] for name in roots)
        assert all(not root.exists() for root in roots.values())
