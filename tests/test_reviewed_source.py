"""Raw-blob preparation, including the actual Windows Git archive failure mode."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.ops import reviewed_source as source

SCRIPT = Path(source.__file__)
TEXT = b"first line\nsecond line\n"
BINARY = b"\x00\xff\r\n\n"


def git(repository, *arguments, input_bytes=None):
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(
        ["git", "-C", str(repository), "-c", "commit.gpgsign=false", *arguments],
        input=input_bytes, stdin=subprocess.DEVNULL if input_bytes is None else None,
        capture_output=True, check=True, timeout=30, env=environment,
    ).stdout


@pytest.fixture
def repository(tmp_path):
    path = tmp_path / "repository"
    path.mkdir()
    git(path, "init", "-q", "--initial-branch=main")
    git(path, "config", "user.name", "Source Fixture")
    git(path, "config", "user.email", "source@example.invalid")
    git(path, "config", "core.autocrlf", "false")
    (path / "nested").mkdir()
    (path / "nested/tool.py").write_bytes(TEXT)
    (path / "payload.bin").write_bytes(BINARY)
    (path / "empty").write_bytes(b"")
    git(path, "add", "--all")
    git(path, "commit", "-q", "-m", "reviewed source")
    commit = git(path, "rev-parse", "HEAD").decode().strip()
    return path, commit


def cli(repository, commit, target, action):
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(SCRIPT), action,
         "--repository", str(repository), "--commit", commit,
         "--out" if action == "export" else "--source", str(target)],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
    )


def test_autocrlf_archive_and_checkout_convert_but_raw_export_succeeds(repository, tmp_path):
    repo, commit = repository
    git(repo, "config", "core.autocrlf", "true")
    archive = git(repo, "archive", "--format=zip", commit)
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        assert zipped.comment == commit.encode()
        assert zipped.read("nested/tool.py") == TEXT.replace(b"\n", b"\r\n")
    (repo / "nested/tool.py").unlink()
    git(repo, "checkout", "--", "nested/tool.py")
    assert (repo / "nested/tool.py").read_bytes() == TEXT.replace(b"\n", b"\r\n")

    target = tmp_path / "selected"
    exported = cli(repo, commit, target, "export")
    assert exported.returncode == 0 and exported.stderr == b""
    assert (target / "nested/tool.py").read_bytes() == TEXT
    assert (target / "payload.bin").read_bytes() == BINARY
    assert (target / "empty").read_bytes() == b""
    verified = cli(repo, commit, target, "verify")
    assert verified.returncode == 0 and verified.stderr == b""
    assert verified.stdout == f"reviewed-source-verify-checked {commit} 3\n".encode()
    (target / "nested/tool.py").write_bytes(TEXT.replace(b"\n", b"\r\n"))
    damaged = cli(repo, commit, target, "verify")
    assert damaged.returncode == 1 and damaged.stdout == b""
    assert damaged.stderr == b"reviewed-source-refused\n"
    assert git(repo, "config", "--get", "core.autocrlf") == b"true\n"


@pytest.mark.parametrize("kind", ["file", "directory", "dangling-link"])
def test_export_refuses_existing_target_without_changes(repository, tmp_path, kind):
    repo, commit = repository
    target = tmp_path / "selected"
    if kind == "file":
        target.write_bytes(b"keep")
    elif kind == "directory":
        target.mkdir()
        (target / "keep").write_bytes(b"keep")
    else:
        try:
            target.symlink_to(tmp_path / "absent")
        except OSError:
            pytest.skip("creating a symlink requires platform permission")
    with pytest.raises(FileExistsError):
        source.export(repo, commit, target)
    if kind == "file":
        assert target.read_bytes() == b"keep"
    elif kind == "directory":
        assert list(target.iterdir()) == [target / "keep"]
        assert (target / "keep").read_bytes() == b"keep"
    else:
        assert target.is_symlink() and not target.exists()


@pytest.mark.parametrize("damage", ["missing", "extra-file", "extra-directory", "modified",
                                    "file-to-directory", "directory-to-file", "symlink"])
def test_verify_checks_whole_materialized_tree(repository, tmp_path, damage):
    repo, commit = repository
    target = tmp_path / "selected"
    source.export(repo, commit, target)
    path = target / "nested/tool.py"
    if damage == "extra-file":
        (target / "unexpected").write_bytes(b"private-extra")
    elif damage == "extra-directory":
        (target / "unexpected").mkdir()
    elif damage == "modified":
        path.write_bytes(TEXT.replace(b"first", b"other"))  # Same byte length.
    elif damage == "directory-to-file":
        path.unlink()
        path.parent.rmdir()
        path.parent.write_bytes(TEXT)
    else:
        path.unlink()
        if damage == "file-to-directory":
            path.mkdir()
        elif damage == "symlink":
            try:
                path.symlink_to(target / "payload.bin")
            except OSError:
                pytest.skip("creating a symlink requires platform permission")
    with pytest.raises(source.Refused):
        source.verify(repo, commit, target)


@pytest.mark.parametrize("mode", ["120000", "160000"])
def test_git_symlink_and_gitlink_refuse_before_export_claim(repository, tmp_path, mode):
    repo, commit = repository
    oid = (git(repo, "hash-object", "-w", "--stdin", input_bytes=b"nested/tool.py").decode().strip()
           if mode == "120000" else commit)
    git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{oid},nonregular")
    tree = git(repo, "write-tree").decode().strip()
    unsafe = git(repo, "commit-tree", tree, "-m", "nonregular source").decode().strip()
    target = tmp_path / "selected"
    with pytest.raises(source.Refused):
        source.export(repo, unsafe, target)
    assert not target.exists()


@pytest.mark.parametrize("pin", ["HEAD", "a" * 39, "A" * 40, "a" * 40])
def test_only_an_existing_exact_commit_is_accepted(repository, tmp_path, pin):
    repo, _ = repository
    with pytest.raises(source.Refused):
        source.export(repo, pin, tmp_path / "selected")
    assert not (tmp_path / "selected").exists()


def test_an_exact_blob_oid_is_not_an_explicit_commit(repository, tmp_path):
    repo, commit = repository
    blob = git(repo, "rev-parse", commit + ":payload.bin").decode().strip()
    with pytest.raises(source.Refused):
        source.export(repo, blob, tmp_path / "selected")
    assert not (tmp_path / "selected").exists()


def test_regular_executable_blob_is_preserved_where_supported(repository, tmp_path):
    repo, _ = repository
    git(repo, "update-index", "--chmod=+x", "nested/tool.py")
    git(repo, "commit", "-q", "-m", "executable source")
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    target = tmp_path / "selected"
    assert source.export(repo, commit, target) == 3
    assert (target / "nested/tool.py").read_bytes() == TEXT
    if os.name != "nt":
        assert (target / "nested/tool.py").stat().st_mode & 0o111
    assert source.verify(repo, commit, target) == 3


@pytest.mark.parametrize("reported_mode,accepted", [(0o755, True), (0o641, False), (0o744, False)])
def test_verify_checks_complete_posix_execute_pattern(
    repository, tmp_path, monkeypatch, reported_mode, accepted,
):
    repo, _ = repository
    git(repo, "update-index", "--chmod=+x", "nested/tool.py")
    git(repo, "commit", "-q", "-m", "executable source")
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    target = tmp_path / "selected"
    source.export(repo, commit, target)
    executable = target / "nested/tool.py"
    original = Path.lstat

    def lstat(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == executable:
            return SimpleNamespace(
                st_mode=(info.st_mode & ~0o777) | reported_mode,
                st_nlink=info.st_nlink, st_size=info.st_size,
                st_dev=info.st_dev, st_ino=info.st_ino,
            )
        return info

    # Substitute only the platform choice and its stat result. Real Git, reads,
    # directory inventory and opened-file identity still exercise production verify.
    # This runs the POSIX condition on Windows instead of skipping the regression.
    monkeypatch.setattr(source, "os", SimpleNamespace(**{**vars(os), "name": "posix"}))
    monkeypatch.setattr(Path, "lstat", lstat)
    if accepted:
        assert source.verify(repo, commit, target) == 3
    else:
        with pytest.raises(source.Refused):
            source.verify(repo, commit, target)


@pytest.mark.parametrize("name", [b"/absolute", b"../escape", b"a//b", b"a/./b", b"a/../b",
                                  b"a\\b", b"C:drive", b"a/.git/config", b"CON.txt",
                                  b"file.", b"file ", b"line\nfeed", b"a\xff"])
def test_paths_cannot_escape_or_alias_portable_source_names(name):
    with pytest.raises((source.Refused, UnicodeError)):
        source._path(name)


@pytest.mark.parametrize("bound", ["MAX_ENTRIES", "MAX_BLOB_BYTES", "MAX_TOTAL_BYTES"])
def test_source_bounds_bind_before_export_claim(repository, tmp_path, monkeypatch, bound):
    repo, commit = repository
    monkeypatch.setattr(source, bound, 1)
    with pytest.raises(source.Refused):
        source.export(repo, commit, tmp_path / "selected")
    assert not (tmp_path / "selected").exists()


def test_replace_objects_cannot_change_selected_commit(repository, tmp_path):
    repo, commit = repository
    (repo / "nested/tool.py").write_bytes(b"unreviewed replacement\n")
    git(repo, "add", "--all")
    git(repo, "commit", "-q", "-m", "replacement")
    replacement = git(repo, "rev-parse", "HEAD").decode().strip()
    git(repo, "replace", commit, replacement)
    target = tmp_path / "selected"
    assert source.export(repo, commit, target) == 3
    assert (target / "nested/tool.py").read_bytes() == TEXT
    assert source.verify(repo, commit, target) == 3
