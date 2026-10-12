"""Public-record shell composition, not historical production adjudication.

The reviewed R11/LR4 blocks run in separate Bash processes. Git/network and
the artifact-judge tool boundary are scripted; shell redirects, hashes, JSON,
paths and rename are real. Linux proves emitted POSIX modes under a trusted
ancestor chain. Windows substitutes POSIX metadata only and proves no modes.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import stat
import sys
import tempfile
from pathlib import Path

import pytest

from tests.test_m8_n5_g6_session import _run
from tests.test_m8_n5_g7_retention_resume import (
    CONTROLLER,
    FAILURE,
    OLD,
    SCRIPT,
    SHA,
    P,
)
from tests.test_m8_n5_host_session import HANDOFFS, _fences, _section, _text
from tests.test_m8_operator_commands import PYTHON_PROGRAM

DOCUMENT = HANDOFFS / "M8-N5-g7-archive-custody.md"
ORIGINAL = HANDOFFS / "M8-N5-g7-retention-resume.md"
ROOT = Path(__file__).parents[1]
SOURCE = "\n".join([
    "import hashlib, json, sys",
    "from pathlib import Path",
    "command, commit, workspace = sys.argv[1:]",
    f"assert commit == {P!r}",
    "assert Path(workspace).name == 'm8-launch'",
    "assert command in ('vendor-inputs', 'judge-retire', 'verify-retired')",
    "sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()",
    f"r = {{'schema_version': 2, 'command': command, 'commit': {P!r},",
    "     'first_parent': True, 'script_matches_commit': True,",
    f"     'blobs': {{{SCRIPT!r}: {{'sha256': sha}}}}}}",
    "if command == 'vendor-inputs':",
    "    payload = hashlib.sha256(b'public fixture payload\\n').hexdigest()",
    "    r.update(listed=True, vendor={name: {'url': 'https://fixture.invalid/' + name,",
    "        'sha256': payload} for name in ('codex', 'catalog')})",
    "elif command == 'judge-retire':",
    f"    r.update(ready=False, failure={FAILURE!r})",
    "else:",
    "    r.update(retired=False, failure='fixture retirement was refused')",
    "print(json.dumps(r))",
    "raise SystemExit(0 if command == 'vendor-inputs' else 1)",
    "",
]).encode()
SOURCE_SHA = hashlib.sha256(SOURCE).hexdigest()


@pytest.fixture
def shell_home(tmp_path: Path):
    # /tmp's 1777 is intentionally outside the custody law. Linux uses the
    # checkout's real trusted chain, never fabricated ancestor metadata.
    parent = ROOT if sys.platform == "linux" else tmp_path
    if sys.platform == "linux":
        for path in (parent, *parent.parents):
            info = path.lstat()
            assert stat.S_ISDIR(info.st_mode)
            assert info.st_uid in (0, os.getuid()) and not info.st_mode & 0o022, path
    with tempfile.TemporaryDirectory(prefix=".archive-custody-", dir=parent) as temporary:
        home = Path(temporary).resolve() / "operator"
        home.mkdir(mode=0o700)
        home.chmod(0o700)
        for name in ("m8-launch-" + OLD, "m8-controller"):
            directory = home / name
            directory.mkdir(mode=0o700)
            directory.chmod(0o700)
            (directory / "preserved").write_bytes(name.encode())
        yield home


def _boundaries(home: Path) -> str:
    source = home / "fixture-source.py"
    source.write_bytes(SOURCE)
    return "\n".join([
        f"PYTHON_BIN={shlex.quote(sys.executable)}",
        f"FAKE_SOURCE={shlex.quote(str(source))}",
        f"EXPECTED_P={P}",
        'env_boundary() {',
        '  test "$1" = -i || return 91; shift',
        '  while [[ "$1" = *=* ]]; do shift; done',
        '  "$@"',
        '}',
        'git_boundary() {',
        '  if test "$1" = --no-replace-objects; then shift; fi',
        '  if [[ "$1" = --git-dir=* ]]; then shift; fi',
        '  case "$1" in',
        '    init) test "$*" = "init -q --bare $HOME/m8-launch/source.git" || return 92;',
        '      /usr/bin/mkdir "$HOME/m8-launch/source.git" ;;',
        '    fetch) test "$*" = "fetch -q --no-tags https://github.com/sushiHex/constructicon.git '
        '+refs/heads/main:refs/heads/main" ;;',
        '    rev-parse|rev-list|ls-remote) printf "%s\\n" "$EXPECTED_P" ;;',
        '    ls-tree) printf "100644 blob fixture\\tpublic-input\\n" ;;',
        '    cat-file) test "$*" = "cat-file blob $EXPECTED_P:scripts/ci/m8_host_artifacts.py" '
        '&& /usr/bin/cat "$FAKE_SOURCE" ;;',
        '    *) return 93 ;;',
        '  esac',
        '}',
        'curl_boundary() {',
        '  test "$*" = "-q --fail --location --proto =https --silent --show-error --output '
        '$HOME/m8-launch/codex.tar.gz https://fixture.invalid/codex" ||',
        '  test "$*" = "-q --fail --location --proto =https --silent --show-error --output '
        '$HOME/m8-launch/codex-models.json https://fixture.invalid/catalog" || return 94',
        '  printf "public fixture payload\\n" > "${9}"',
        '}',
        'python_boundary() { "$PYTHON_BIN" "$@"; }',
        'sudo() {',
        '  printf "%s\\n" "$*" >> "$HOME/platform-calls"',
        '  test "$*" = "/usr/bin/cat /sys/kernel/security/apparmor/profiles" || return 95',
        '  printf "constructicon-m8-bwrap (enforce)\\nconstructicon-m8-payload (enforce)\\n"',
        '}',
    ])


def _tools(block: str) -> str:
    for tool in ("env", "git", "curl", "python3"):
        block = block.replace("/usr/bin/" + tool, tool.replace("python3", "python") + "_boundary")
    return block


def _produce(home: Path, mask: int) -> None:
    replacement = _text(HANDOFFS / "M8-N4-launch-replacement.md")
    _, r11 = _fences(_section(replacement, "LR3. Preconditions and provenance"))
    r11 = r11.replace("C=<40-hex merge commit named in LR0>", "C=" + P)
    first = _run(_boundaries(home) + "\n" + _tools(r11), HOME=str(home))
    assert first.returncode == 0 and "R11 complete\n" in first.stdout, first.stderr
    lr4, = _fences(_section(replacement, "LR4. Retire (judge, then root)"))
    second = _run(
        _boundaries(home) + f"\numask {mask:03o}\nC={P}\nW=\"$HOME/m8-launch\"\n"
        + _tools(lr4), HOME=str(home),
    )
    assert "exit 1\n" in second.stdout and "LR4 retired" not in second.stdout, second.stderr
    assert "verify exit 1\n" in second.stdout
    assert json.loads((home / "m8-launch/retire.json").read_text())["failure"] == FAILURE
    assert not (home / "m8-launch/staging").exists()
    calls = (home / "platform-calls").read_text().splitlines()
    assert calls == ["/usr/bin/cat /sys/kernel/security/apparmor/profiles"] * 2
    if sys.platform == "linux":
        assert stat.S_IMODE((home / "m8-launch").stat().st_mode) == 0o700
        for leaf in ("vendor.json", "m8_host_artifacts.py"):
            assert stat.S_IMODE((home / "m8-launch" / leaf).stat().st_mode) == 0o600
        assert stat.S_IMODE((home / "m8-launch/retire.json").stat().st_mode) == 0o666 & ~mask


def _archive(home: Path, mask: int, *, original: bool = False, fault: str = "none",
             leaf: str = "retire.json", public_mode: int | None = None) -> str:
    document = ORIGINAL if original else DOCUMENT
    heading = ("Complete LR3 workspace-resume override" if original
               else "Complete archive-custody override")
    block, = _fences(_section(_text(document), heading))
    match = PYTHON_PROGRAM.search(block)
    assert match is not None
    body = match["body"].replace(SHA, SOURCE_SHA)
    # Portable fault injection changes only POSIX metadata. On Linux the
    # permitting path uses the actual lstat unchanged, including ancestors.
    if os.name == "nt" or fault != "none":
        metadata = "\n".join([
            "import os, stat, sys",
            "from pathlib import Path",
            "real_lstat = os.lstat",
            "real_uid = getattr(os, 'getuid', lambda: 0)()",
            "os.getuid = lambda: real_uid",
            f"fault = {fault!r}; record_mode = {0o666 & ~mask}",
            f"leaf = {leaf!r}; public_mode = {public_mode!r}",
            "def metadata(path, *args, **kwargs):",
            "    info = real_lstat(path, *args, **kwargs); fields = list(info)",
            "    target = Path(path)",
            "    if os.name == 'nt':",
            "        fields[4] = real_uid",
            "        fields[0] = stat.S_IFMT(info.st_mode) | (0o700 if target.is_dir() else 0o600)",
            "        if target.name == 'retire.json': fields[0] = stat.S_IFREG | record_mode",
            "        public = target.name in (",
            "            'retire.json', 'vendor.json', 'm8_host_artifacts.py')",
            "        if public and public_mode is not None:",
            "            fields[0] = stat.S_IFREG | public_mode",
            "    if target.name == leaf:",
            "        if fault == 'record-owner': fields[4] = real_uid + 1",
            "        if fault == 'record-kind': fields[0] = stat.S_IFDIR | 0o700",
            "        if fault == 'record-links': fields[3] = 2",
            "    if target.name == 'm8-launch':",
            "        if fault == 'cross-device': fields[2] = info.st_dev + 1",
            "        if fault == 'directory-owner': fields[4] = real_uid + 1",
            "        if fault == 'directory-mode': fields[0] |= 0o020",
            "        if fault == 'directory-kind': fields[0] = stat.S_IFLNK | 0o700",
            "    if target.name == 'operator':",
            "        if fault == 'ancestor-owner': fields[4] = real_uid + 1",
            "        if fault == 'ancestor-write': fields[0] |= 0o020",
            "        if fault == 'ancestor-kind': fields[0] = stat.S_IFREG | 0o700",
            "    return os.stat_result(fields)",
            "os.lstat = metadata",
            "if fault == 'cross-device': Path.lstat = lambda path: metadata(path)",
            "if fault == 'canonical':",
            "    real_resolve = Path.resolve",
            "    Path.resolve = lambda path, *a, **kw: (path.parent / 'outside'",
            "        if path.name == 'm8-launch' else real_resolve(path, *a, **kw))",
        ])
        body = metadata.replace("'", '"') + "\n" + body
    return block.replace(match["body"], body).replace(
        "/usr/bin/python3", shlex.quote(sys.executable),
    )


@pytest.mark.parametrize("mask", [0o077, 0o027, 0o022, 0o007, 0o002, 0o000])
def test_successor_archives_the_actual_fresh_shell_producers(shell_home: Path, mask: int):
    _produce(shell_home, mask)
    w = shell_home / "m8-launch"
    before = {path.name: (path.read_bytes(), path.stat().st_dev, path.stat().st_ino,
                          stat.S_IMODE(path.stat().st_mode))
              for path in (w / "vendor.json", w / "retire.json", w / "m8_host_artifacts.py")}
    identity = w.stat().st_ino
    kept = {name: ((shell_home / name).stat().st_ino,
                   (shell_home / name / "preserved").read_bytes())
            for name in ("m8-launch-" + OLD, "m8-controller")}
    result = _run(_archive(shell_home, mask), HOME=str(shell_home), C=CONTROLLER)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "paused-workspace-preserved\n"
    archive = shell_home / ("m8-launch-refused-" + P)
    assert not w.exists() and archive.stat().st_ino == identity
    after = {path.name: (path.read_bytes(), path.stat().st_dev, path.stat().st_ino,
                         stat.S_IMODE(path.stat().st_mode)) for path in
             (archive / "vendor.json", archive / "retire.json", archive / "m8_host_artifacts.py")}
    assert after == before
    assert {name: ((shell_home / name).stat().st_ino,
                   (shell_home / name / "preserved").read_bytes()) for name in kept} == kept


@pytest.mark.parametrize("mask", [0o022, 0o002, 0o000])
def test_original_guard_refuses_public_record_modes_before_move(shell_home: Path, mask: int):
    _produce(shell_home, mask)
    w = shell_home / "m8-launch"
    identity = w.stat().st_ino
    result = _run(_archive(shell_home, mask, original=True), HOME=str(shell_home), C=CONTROLLER)
    assert result.returncode != 0
    assert "AssertionError" in result.stderr
    assert result.stdout == ""
    assert w.stat().st_ino == identity
    assert not (shell_home / ("m8-launch-refused-" + P)).exists()


@pytest.mark.parametrize("fault", [
    "record-owner", "record-kind", "record-links", "directory-owner", "directory-mode",
    "directory-kind", "ancestor-owner", "ancestor-write", "ancestor-kind", "cross-device",
    "canonical",
])
def test_custody_faults_refuse_before_archive(shell_home: Path, fault: str):
    _produce(shell_home, 0o002)
    result = _run(_archive(shell_home, 0o002, fault=fault), HOME=str(shell_home), C=CONTROLLER)
    assert result.returncode != 0 and result.stdout == ""
    assert (shell_home / "m8-launch").is_dir()
    assert not (shell_home / ("m8-launch-refused-" + P)).exists()


@pytest.mark.parametrize("leaf", ["retire.json", "vendor.json", "m8_host_artifacts.py"])
@pytest.mark.parametrize("fault", ["record-owner", "record-kind", "record-links"])
def test_each_public_record_requires_regular_single_link_operator_custody(
    shell_home: Path, leaf: str, fault: str,
):
    _produce(shell_home, 0o002)
    result = _run(_archive(shell_home, 0o002, fault=fault, leaf=leaf),
                  HOME=str(shell_home), C=CONTROLLER)
    assert result.returncode != 0 and result.stdout == ""
    assert (shell_home / "m8-launch").is_dir()
    assert not (shell_home / ("m8-launch-refused-" + P)).exists()


def test_all_three_public_leaf_modes_are_preserved_not_repaired(shell_home: Path):
    _produce(shell_home, 0o000)
    w = shell_home / "m8-launch"
    leaves = [w / name for name in ("retire.json", "vendor.json", "m8_host_artifacts.py")]
    for path in leaves:
        path.chmod(0o666)
    before = [(p.read_bytes(), p.stat().st_ino, stat.S_IMODE(p.stat().st_mode)) for p in leaves]
    result = _run(_archive(shell_home, 0o000, public_mode=0o666),
                  HOME=str(shell_home), C=CONTROLLER)
    assert result.returncode == 0, result.stderr
    archive = shell_home / ("m8-launch-refused-" + P)
    after = [(p.read_bytes(), p.stat().st_ino, stat.S_IMODE(p.stat().st_mode))
             for p in (archive / path.name for path in leaves)]
    assert after == before


@pytest.mark.parametrize("fault", [
    "schema_version", "command", "commit", "ready", "first_parent", "script_matches_commit",
    "failure",
    "record-hash", "source-bytes", "vendor-command", "vendor-commit", "vendor-listed",
    "vendor-schema_version", "vendor-first_parent", "vendor-script_matches_commit", "vendor-hash",
    "malformed",
    "staging", "old-archive-missing", "controller-archived", "existing-archive",
])
def test_exact_paused_facts_and_absence_guards_still_stop(shell_home: Path, fault: str):
    _produce(shell_home, 0o002)
    w = shell_home / "m8-launch"
    if fault.startswith("vendor-"):
        path = w / "vendor.json"
        record = json.loads(path.read_text())
        key = fault.removeprefix("vendor-")
        if key == "hash":
            record["blobs"][SCRIPT]["sha256"] = "0" * 64
        else:
            record[key] = False if isinstance(record.get(key), bool) else "different"
        path.write_text(json.dumps(record))
    elif fault in ("schema_version", "command", "commit", "ready", "first_parent",
                   "script_matches_commit", "failure", "record-hash"):
        path = w / "retire.json"
        record = json.loads(path.read_text())
        if fault == "record-hash":
            record["blobs"][SCRIPT]["sha256"] = "0" * 64
        else:
            record[fault] = not record[fault] if isinstance(record[fault], bool) else "different"
        path.write_text(json.dumps(record))
    elif fault == "source-bytes":
        (w / "m8_host_artifacts.py").write_bytes(b"different public source")
    elif fault == "malformed":
        (w / "retire.json").write_text("not json")
    elif fault == "staging":
        (w / "staging").mkdir()
    elif fault == "old-archive-missing":
        (shell_home / ("m8-launch-" + OLD)).rename(shell_home / "old-preserved")
    elif fault == "controller-archived":
        (shell_home / ("m8-controller-" + OLD)).mkdir()
    else:
        (shell_home / ("m8-launch-refused-" + P)).mkdir()
    result = _run(_archive(shell_home, 0o002), HOME=str(shell_home), C=CONTROLLER)
    assert result.returncode != 0 and result.stdout == ""
    assert w.is_dir()


@pytest.mark.parametrize(("before", "after", "fault"), [
    ("assert stat.S_ISDIR(info.st_mode) and info.st_uid in (0, uid)",
     "assert info.st_uid in (0, uid)", "ancestor-kind"),
    ("assert stat.S_ISDIR(info.st_mode) and info.st_uid in (0, uid)",
     "assert stat.S_ISDIR(info.st_mode)", "ancestor-owner"),
    ("assert stat.S_IMODE(info.st_mode) & 0o022 == 0", "assert True", "ancestor-write"),
    ("assert stat.S_ISREG(info.st_mode) and info.st_uid == uid and info.st_nlink == 1",
     "assert info.st_uid == uid and info.st_nlink == 1", "record-kind"),
    ("assert stat.S_ISREG(info.st_mode) and info.st_uid == uid and info.st_nlink == 1",
     "assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1", "record-owner"),
    ("assert stat.S_ISREG(info.st_mode) and info.st_uid == uid and info.st_nlink == 1",
     "assert stat.S_ISREG(info.st_mode) and info.st_uid == uid", "record-links"),
    ("assert stat.S_IMODE(info.st_mode) == 0o700 and path.resolve(strict=True) == path",
     "assert path.resolve(strict=True) == path", "directory-mode"),
    ("assert stat.S_IMODE(info.st_mode) == 0o700 and path.resolve(strict=True) == path",
     "assert stat.S_IMODE(info.st_mode) == 0o700", "canonical"),
    ("assert w.lstat().st_dev == home.lstat().st_dev", "assert True", "cross-device"),
])
def test_removed_runbook_guard_is_assertion_killed(
    shell_home: Path, monkeypatch: pytest.MonkeyPatch, before: str, after: str, fault: str,
):
    document = _text(DOCUMENT)
    assert document.count(before) == 1
    changed = document.replace(before, after)
    real_text = _text
    monkeypatch.setattr(sys.modules[__name__], "_text",
                        lambda path: changed if path == DOCUMENT else real_text(path))
    # The removed guard must admit the bad world. A syntax/runtime error would
    # leave the refusal test passing and therefore fail this mutation proof.
    with pytest.raises(AssertionError) as killed:
        test_custody_faults_refuse_before_archive(shell_home, fault)
    assert killed.traceback[-1].name == "test_custody_faults_refuse_before_archive"


def test_reintroduced_private_leaf_mode_is_assertion_killed(
    shell_home: Path, monkeypatch: pytest.MonkeyPatch,
):
    document = _text(DOCUMENT)
    before = "    return path.read_bytes()"
    assert document.count(before) == 1
    changed = document.replace(before, "    assert stat.S_IMODE(info.st_mode) == 0o600\n" + before)
    real_text = _text
    monkeypatch.setattr(sys.modules[__name__], "_text",
                        lambda path: changed if path == DOCUMENT else real_text(path))
    with pytest.raises(AssertionError) as killed:
        test_successor_archives_the_actual_fresh_shell_producers(shell_home, 0o002)
    assert killed.traceback[-1].name == "test_successor_archives_the_actual_fresh_shell_producers"
