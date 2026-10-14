"""Execute the continuation's read-only prerequisites with private fake files."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_m8_n5_g6_session import SEAL, _run
from tests.test_m8_n5_host_session import HANDOFFS, _fences, _section, _text
from tests.test_m8_operator_commands import PYTHON_PROGRAM, _bash

DOCUMENT = HANDOFFS / "M8-maintenance-continuation.md"
NAMES = ("profiles-verify", "verify.json", "qualification.json")


def _block(heading: str) -> str:
    block, = _fences(_section(_text(DOCUMENT), heading))
    return block.strip()


def _portable(program: str, link: Path | None = None) -> str:
    # Preserve the production read/compare program. Only Unix flag, uid/mode
    # and symlink metadata boundaries differ on a native Windows filesystem.
    if os.name == "nt":
        program = program.replace("os.O_NOFOLLOW", "0")
        program = program.replace("os.O_NONBLOCK", "0")
        program = program.replace("os.getuid()", "0")
        program = program.replace("archive_info.st_mode & 0o077 == 0", "True")
        program = program.replace("info.st_mode & 0o077 == 0", "True")
        if link is not None:
            program = (
                "import os, stat\nfrom pathlib import Path\n"
                "original_lstat = Path.lstat\n"
                "def fake_lstat(path):\n"
                "    info = original_lstat(path)\n"
                "    if path == Path(" + repr(str(link)) + "):\n"
                "        fields = list(info); fields[0] = stat.S_IFLNK | 0o777\n"
                "        return os.stat_result(fields)\n"
                "    return info\nPath.lstat = fake_lstat\n" + program
            )
    return program


def _program(heading: str, link: Path | None = None) -> str:
    program, = PYTHON_PROGRAM.findall(_block(heading))
    return _portable(program, link)


def _python(program: str, *arguments: Path | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", program, *map(str, arguments)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, check=False,
    )


def _clean(result: subprocess.CompletedProcess[str], marker: str) -> None:
    assert result.returncode == 0, result.stderr
    assert result.stdout == marker + "\n"
    assert result.stderr == ""


def _facts(root: Path) -> dict[str, tuple[object, ...]]:
    facts = {}
    for path in [root, *sorted(root.rglob("*"))]:
        info = path.lstat()
        content = path.read_bytes() if stat.S_ISREG(info.st_mode) else None
        facts[str(path.relative_to(root))] = (
            content, info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
        )
    return facts


def _link(path: Path, target: Path) -> Path | None:
    if os.name == "nt":
        return path
    path.unlink() if path.is_file() else path.rmdir()
    path.symlink_to(target, target_is_directory=target.is_dir())
    return None


def test_continuation_bash_parses_with_frozen_common_and_keeps_delegate_limits():
    document = _text(DOCUMENT)
    operator = _text(HANDOFFS / "M8-N4-operator-commands.md")
    common = "\n".join(_fences(operator.split("## Setup", 1)[1].split("\n### ", 1)[0]))
    for block in re.findall(r"```bash\n(.*?)```", document, re.S):
        result = subprocess.run([_bash(), "-n"], input=common + "\n" + block,
                                capture_output=True, text=True, timeout=30, check=False)
        assert result.returncode == 0 and result.stdout == "" and result.stderr == ""
    for expected in (
        "P2 from LR2 onward and P3-P10 exactly", "at most one",
        "conditional H8 request", "one application attempt", "No R6",
        "No LR2,", "not a failed or partial copy", "no stderr allowlist",
        "fresh continuation packages", "same reviewed immutable bundle",
    ):
        assert expected in document
    assert "/usr/bin/cp" not in document
    assert "printf" not in _block("C1: repeat controller check, compare existing capture")


@pytest.mark.parametrize("failure", [
    "none", "missing", "empty", "changed", "no-lf", "extra-lf", "oversized",
    "directory", "symlink", "hardlink", "nonprivate", "wrong-owner",
])
def test_existing_capture_accepts_exact_private_bytes_and_refuses_without_mutation(
    tmp_path: Path, failure: str,
):
    path = tmp_path / "maintenance-g9-account.seal"
    path.write_bytes((SEAL + "\n").encode())
    path.chmod(0o600)
    link = None
    if failure == "missing":
        path.unlink()
    elif failure == "directory":
        path.unlink()
        path.mkdir()
    elif failure == "symlink":
        target = tmp_path / "target"
        target.write_bytes(path.read_bytes())
        link = _link(path, target)
    elif failure == "hardlink":
        os.link(path, tmp_path / "alias")
    elif failure == "nonprivate":
        if os.name == "nt":
            # Exercise the actual private-mode predicate with substituted
            # permission metadata; native Windows does not implement chmod.
            program = PYTHON_PROGRAM.findall(_block(
                "C1: repeat controller check, compare existing capture"))[0]
            program = program.replace("os.getuid()", "0").replace("os.O_NOFOLLOW", "0")
            program = program.replace("os.O_NONBLOCK", "0")
        else:
            path.chmod(0o644)
    elif failure in {"empty", "changed", "no-lf", "extra-lf", "oversized"}:
        path.write_bytes({
            "empty": b"", "changed": (SEAL.replace("a", "b") + "\n").encode(),
            "no-lf": SEAL.encode(), "extra-lf": (SEAL + "\n\n").encode(),
            "oversized": b"x" * 257,
        }[failure])
    before = _facts(tmp_path)
    if failure != "nonprivate" or os.name != "nt":
        program = _program("C1: repeat controller check, compare existing capture", link)
    if failure == "wrong-owner":
        program = program.replace("info.st_uid == " + ("0" if os.name == "nt" else "os.getuid()"),
                                  "info.st_uid == -1")
    result = _python(program, path, SEAL)
    assert _facts(tmp_path) == before
    if failure == "none":
        _clean(result, "historical-account-capture-revalidated")
    else:
        assert result.returncode != 0 and result.stdout == "" and result.stderr
        assert "AssertionError" in result.stderr or "FileNotFoundError" in result.stderr


@pytest.mark.parametrize("failure", ["none", "anchor", "qualification", "seal", "plan"])
def test_capture_comparison_follows_fresh_historical_checks(tmp_path: Path, failure: str):
    path = tmp_path / "maintenance-g9-account.seal"
    path.write_bytes((SEAL + "\n").encode())
    path.chmod(0o600)
    block = _block("C1: repeat controller check, compare existing capture")
    program, = PYTHON_PROGRAM.findall(block)
    block = block.replace(program, _portable(program)).replace(
        "/usr/bin/python3", '"$TEST_PY"',
    )
    before = _facts(tmp_path)
    result = _run("\n".join([
        "set -Eeuo pipefail; W=historical",
        'binding_check() { test "$*" = "historical/g8.sealed.json reboot-anchor -"; '
        'test "$FAILURE" != anchor; }',
        'load_final_qualification() { test "$FAILURE" != qualification; Q=q; SEAL="$FAKE_SEAL"; }',
        'check_sealed() { test "$*" = "historical/g8.sealed.json q"; test "$FAILURE" != seal; }',
        block,
    ]), HOME=tmp_path.as_posix(), TEST_PY=Path(sys.executable).as_posix(), FAILURE=failure,
        FAKE_SEAL="plus/private" if failure == "plan" else SEAL)
    assert _facts(tmp_path) == before
    if failure == "none":
        _clean(result, "historical-account-capture-revalidated")
    else:
        assert result.returncode != 0 and result.stdout == ""


@pytest.mark.parametrize("failure", [
    "none", "missing-archive", "archive-file", "archive-link", "source-link",
    "extra", "extra-dangling-link", "empty", "oversized", "changed-source",
    "changed-archive", "member-directory", "member-link", "source-member-link", "hardlink",
    "wrong-owner", "nonprivate", "same-directory", "source-missing", "source-file", "at-bound",
    *[side + "-missing-" + name for side in ("source", "archive") for name in NAMES],
])
def test_existing_archive_accepts_exact_three_files_and_refuses_without_mutation(
    tmp_path: Path, failure: str,
):
    source, archive = tmp_path / "m8-host", tmp_path / "maintenance-g9-d2-prior"
    source.mkdir()
    archive.mkdir(mode=0o700)
    for name in NAMES:
        for directory in (source, archive):
            (directory / name).write_bytes(("historical-" + name).encode())
    link = None
    if "-missing-" in failure:
        side, name = failure.split("-missing-", 1)
        ((source if side == "source" else archive) / name).unlink()
    elif failure in {
        "missing-archive", "archive-file", "archive-link", "source-link",
        "source-missing", "source-file",
    }:
        directory = source if failure.startswith("source-") else archive
        for path in directory.iterdir():
            path.unlink()
        if failure in {"archive-link", "source-link"}:
            target = tmp_path / "redirected"
            target.mkdir()
            link = _link(directory, target)
        else:
            directory.rmdir()
            if failure in {"archive-file", "source-file"}:
                directory.write_bytes(b"not-a-directory")
    elif failure in {"extra", "extra-dangling-link"}:
        extra = archive / "extra"
        if failure == "extra-dangling-link" and os.name != "nt":
            extra.symlink_to(tmp_path / "absent")
        else:
            extra.write_bytes(b"extra")
    elif failure in {"empty", "oversized", "at-bound"}:
        content = b"" if failure == "empty" else b"x" * (
            1048576 if failure == "at-bound" else 1048577)
        for directory in (source, archive):
            (directory / "verify.json").write_bytes(
                content,
            )
    elif failure in {"changed-source", "changed-archive"}:
        directory = source if failure == "changed-source" else archive
        (directory / "verify.json").write_bytes(b"changed")
    elif failure == "member-directory":
        (archive / "verify.json").unlink()
        (archive / "verify.json").mkdir()
    elif failure in {"member-link", "source-member-link"}:
        directory = source if failure == "source-member-link" else archive
        target = tmp_path / "redirected-file"
        target.write_bytes((directory / "verify.json").read_bytes())
        link = _link(directory / "verify.json", target)
    elif failure == "hardlink":
        (archive / "verify.json").unlink()
        os.link(source / "verify.json", archive / "verify.json")
    elif failure == "nonprivate" and os.name != "nt":
        archive.chmod(0o755)
    program = _program("C2: validate completed archive before LR2", link)
    if failure == "wrong-owner":
        program = program.replace(
            "archive_info.st_uid == " + ("0" if os.name == "nt" else "os.getuid()"),
            "archive_info.st_uid == -1",
        )
    elif failure == "nonprivate" and os.name == "nt":
        program = PYTHON_PROGRAM.findall(_block("C2: validate completed archive before LR2"))[0]
        program = program.replace("os.getuid()", "0").replace("os.O_NOFOLLOW", "0")
        program = program.replace("os.O_NONBLOCK", "0")
    before = _facts(tmp_path)
    result = _python(program, source, source if failure == "same-directory" else archive)
    assert _facts(tmp_path) == before
    if failure in {"none", "at-bound"}:
        _clean(result, "d2-prior-records-revalidated")
    else:
        assert result.returncode != 0 and result.stdout == "" and result.stderr
        assert "AssertionError" in result.stderr or "FileNotFoundError" in result.stderr


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_accepting_path_assertion_rejects_additional_diagnostics(tmp_path: Path, stream: str):
    path = tmp_path / "maintenance-g9-account.seal"
    path.write_bytes((SEAL + "\n").encode())
    path.chmod(0o600)
    program = _program("C1: repeat controller check, compare existing capture")
    program += '\nprint("warning", file=sys.' + stream + ")"
    result = _python(program, path, SEAL)
    assert result.returncode == 0
    assert "warning\n" in getattr(result, stream)
    with pytest.raises(AssertionError):
        _clean(result, "historical-account-capture-revalidated")


@pytest.mark.parametrize("failure", ["none", "missing", "changed", "extra"])
def test_archive_guard_stops_before_the_separate_lr2_boundary(tmp_path: Path, failure: str):
    source, archive = tmp_path / "m8-host", tmp_path / "maintenance-g9-d2-prior"
    source.mkdir()
    archive.mkdir(mode=0o700)
    for name in NAMES:
        for directory in (source, archive):
            (directory / name).write_bytes(("historical-" + name).encode())
    if failure == "missing":
        (archive / "verify.json").unlink()
    elif failure == "changed":
        (archive / "verify.json").write_bytes(b"changed")
    elif failure == "extra":
        (archive / "extra").write_bytes(b"extra")
    block = _block("C2: validate completed archive before LR2")
    program, = PYTHON_PROGRAM.findall(block)
    block = block.replace(program, _portable(program)).replace(
        "/usr/bin/python3", '"$TEST_PY"',
    )
    before = _facts(tmp_path)
    result = _run(block + "\necho LR2-permitted", HOME=tmp_path.as_posix(),
                  TEST_PY=Path(sys.executable).as_posix())
    assert _facts(tmp_path) == before
    if failure == "none":
        assert result.returncode == 0 and result.stderr == ""
        assert result.stdout == "d2-prior-records-revalidated\nLR2-permitted\n"
    else:
        assert result.returncode != 0 and result.stdout == "" and result.stderr
        assert "AssertionError" in result.stderr or "FileNotFoundError" in result.stderr


def test_hs_h2_and_capture_replacement_have_distinct_affirmative_output(tmp_path: Path):
    path = tmp_path / "maintenance-g9-account.seal"
    path.write_bytes((SEAL + "\n").encode())
    path.chmod(0o600)
    historical = _text(HANDOFFS / "M8-N5-host-session.md")
    h2, = _fences(_section(historical, "H2. S0 at `C`"))
    # Substitute only host authority and drift command boundaries; keep the
    # exact frozen H2 commands and the continuation block's real file compare.
    h2 = h2.replace("/usr/local/bin/m8-host-drift", "drift")
    block = _block("C1: repeat controller check, compare existing capture")
    program, = PYTHON_PROGRAM.findall(block)
    block = block.replace(program, _portable(program)).replace(
        "/usr/bin/python3", '"$TEST_PY"',
    )
    before = _facts(tmp_path)
    result = _run("\n".join([
        "set -Eeuo pipefail; W=historical",
        'sudo() { test "$*" = "-n true"; }',
        'drift() { echo "NO DRIFT"; }',
        'binding_check() { test "$*" = "historical/g8.sealed.json reboot-anchor -"; }',
        'load_final_qualification() { Q=q; SEAL="$FAKE_SEAL"; }',
        'check_sealed() { test "$*" = "historical/g8.sealed.json q"; }',
        h2, block,
    ]), HOME=tmp_path.as_posix(), TEST_PY=Path(sys.executable).as_posix(), FAKE_SEAL=SEAL)
    assert _facts(tmp_path) == before
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout == "NO DRIFT\nhistorical-account-capture-revalidated\n"
