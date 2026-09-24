"""Reviewed-artifact judgement and verification on the private host (#94).

Root executes no repository code: the script judges and verifies unprivileged,
and root's part is the runbook's fixed stock-tool sequence. Provenance, the
judgement of observed state and the command record run on every platform
against temporary git repositories. Custody, staging, ownership and modes run
on Linux only; a Windows skip is not evidence. There, the root sequence runs
through the real coreutils ``install`` without ``-o root -g root`` (the tests
are not root), and ownership is observed through a uid view in which the
temporary host's files read as owned by a stand-in root uid while the
operator's home keeps the real one. The other substitutions are the root path,
the git path, the host's bubblewrap bytes and pin, a fake ``apparmor_parser``
and the kernel's loaded-profile list. The real host installation is never
executed here.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest
from scripts.ci import m8_host_artifacts as artifacts
from scripts.ci import qualify_m8_runner as probe

REPOSITORY = Path(__file__).parents[1]
SOURCE = REPOSITORY / "scripts/ci/m8_host_artifacts.py"
RUNBOOK = REPOSITORY / "docs/plans/handoffs/M8-D2-host-installation.md"
LINUX = pytest.mark.skipif(
    sys.platform != "linux",
    reason="custody, O_NOFOLLOW, coreutils install and POSIX modes are Linux; Linux CI runs it",
)
FAKE_BWRAP = b"\x7fELF pinned bubblewrap stand-in\n"
PROBE_BYTES = b"# reviewed probe\n"
PROFILE_BYTES = b"profile constructicon-m8-bwrap /opt/constructicon-m8-qualification/bwrap {}\n"
INSTALL = "/" + artifacts.INSTALL
OWNER = ("-o", "root", "-g", "root")
KERNEL_LIST = "unpriv_bwrap (enforce)\n/usr/bin/man (enforce)\n"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(cwd: Path, *arguments: str, stdin: bytes | None = None) -> str:
    completed = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *arguments],
        cwd=cwd,
        input=stdin,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
        timeout=30,
    )
    return completed.stdout.decode().strip()


def commit(work: Path, message: str) -> str:
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", message)
    return git(work, "rev-parse", "HEAD")


def place(work: Path, files: dict[str, bytes]) -> None:
    for path, data in files.items():
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def reviewed(script_bytes: bytes | None = None) -> dict[str, bytes]:
    return {
        artifacts.SCRIPT: SOURCE.read_bytes() if script_bytes is None else script_bytes,
        artifacts.PROBE: PROBE_BYTES,
        artifacts.PROFILE: PROFILE_BYTES,
    }


def work_repository(tmp_path: Path, files: dict[str, bytes]) -> tuple[Path, str]:
    work = tmp_path / "work"
    work.mkdir(parents=True)
    git(work, "init", "-q", "--initial-branch=main")
    git(work, "config", "user.name", "Host Test")
    git(work, "config", "user.email", "host@example.invalid")
    place(work, files)
    return work, commit(work, "reviewed")


def bare(work: Path, destination: Path) -> Path:
    git(work, "clone", "-q", "--bare", str(work), str(destination))
    return destination


def feed(monkeypatch: pytest.MonkeyPatch, listing: str) -> None:
    """Standard input as root's ``cat`` of the kernel's profile list would supply it."""

    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(listing.encode())))


def root_sequence() -> list[list[str]]:
    """R4's root commands, rendered from the fixed inventory; the runbook must match."""

    mode = f"{artifacts.DIRECTORY_MODE:04o}"
    sequence = [[INSTALL, "-d", *OWNER, "-m", mode, "/" + artifacts.DIRECTORY]]
    for destination, (source, file_mode) in artifacts.FILES.items():
        name = PurePosixPath(destination).name
        origin = "/" + artifacts.BWRAP_SOURCE if source is None else f'"$W/staging/{name}"'
        sequence.append([INSTALL, *OWNER, "-m", f"{file_mode:04o}", origin, "/" + destination])
    parser = "/" + artifacts.PARSER
    sequence.append([parser, "--add", "--skip-cache", "/" + artifacts.PROFILE_DESTINATION])
    return sequence


@pytest.fixture(autouse=True)
def stock_git(monkeypatch: pytest.MonkeyPatch) -> None:
    located = shutil.which("git")
    assert located is not None, "these fixtures need git"
    monkeypatch.setattr(artifacts, "GIT", located)


# --- the repository side ---------------------------------------------------


def test_script_imports_only_the_standard_library() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import"
            modules.add((node.module or "").split(".")[0])
    assert modules, "the import walk found nothing, so it proved nothing"
    assert "constructicon" not in modules
    assert modules <= set(sys.stdlib_module_names) | {"__future__"}


def names_in_script() -> set[str]:
    return {
        node.attr if isinstance(node, ast.Attribute) else node.id
        for node in ast.walk(ast.parse(SOURCE.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute | ast.Name)
    }


def test_script_reads_no_environment_and_no_marker() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    names = names_in_script()
    assert "path" in names, "the name walk found nothing, so it proved nothing"
    assert not names & {"environ", "environb", "getenv", "getenvb", "putenv", "home"}
    for forbidden in ("RUNNER_ENVIRONMENT", "/etc/constructicon", "--replace"):
        assert forbidden not in source
    # Children get a fixed environment, never an inherited one.
    assert "env=ENVIRONMENT" in source
    assert artifacts.ENVIRONMENT == {
        "PATH": "/usr/bin:/bin",
        "HOME": "/nonexistent",
        "LANG": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_GRAFT_FILE": "/nonexistent",
    }


def test_only_the_stager_writes() -> None:
    """Judges and verifiers never write; ``materialize`` is the one writer, used by the stager.

    Every write on the host itself is root's stock tools.
    """

    names = names_in_script()
    assert "lstat" in names, "the name walk found nothing, so it proved nothing"
    writes = {
        "O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND", "write", "write_bytes",
        "write_text", "mkdir", "makedirs", "chmod", "fchmod", "chown", "fchown", "unlink",
        "remove", "rmdir", "rename", "replace", "symlink", "link", "truncate", "fsync",
        "copy", "copyfile", "move", "materialize",
    }  # fmt: skip
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    writers = {
        name
        for name, node in functions.items()
        for n in ast.walk(node)
        if (n.attr if isinstance(n, ast.Attribute) else getattr(n, "id", None)) in writes
    }
    assert writers == {"materialize", "stage_launch", "stage_controller"}, writers
    # Each stager's only write is the call to the writer.
    for name in ("stage_launch", "stage_controller"):
        stager = {
            n.attr if isinstance(n, ast.Attribute) else n.id
            for n in ast.walk(functions[name])
            if isinstance(n, ast.Attribute | ast.Name)
        }
        assert stager & writes == {"materialize"}, name
    writer = ast.unparse(functions["materialize"])
    assert "os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW" in writer
    # The builtin ``open`` is not used at all; every other ``os.open`` reads.
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "open"]
    opens = [
        (name, ast.unparse(n))
        for name, node in functions.items()
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "open"
    ]
    assert len(opens) == 6, opens
    for name, call in opens:
        assert (
            name == "materialize"
            or call.startswith("tarfile.open(fileobj=stream, mode='r:gz')")
            # ZipFile.open reads unless given a mode, and none is given.
            or call in ("archive.open(info)", "archives[wheel].open(member)")
            or ("os.O_RDONLY" in call and "O_WR" not in call and "O_CREAT" not in call)
        ), (name, call)


def test_production_root_and_destinations_are_fixed() -> None:
    assert Path("/") == artifacts.ROOT and artifacts.ROOT_UID == 0
    source = SOURCE.read_text(encoding="utf-8")
    # GIT itself is substituted by the autouse fixture, so pin its source line.
    assert source.count('\nGIT = "/usr/bin/git"\n') == 1
    fixed = (artifacts.DIRECTORY, *artifacts.FILES, artifacts.REPOSITORY, artifacts.STAGING)
    for destination in fixed:
        path = PurePosixPath(destination)
        assert not path.is_absolute() and ".." not in path.parts and "\\" not in destination
    assert "add_argument(\"--" not in source, "no option may move the root or a destination"


def test_linux_verify_runs_the_mutation_inventory() -> None:
    """Most custody, staging and ownership mutants can only be killed on Linux."""

    workflow = (REPOSITORY / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    assert "runs-on: ubuntu-latest" in workflow
    step = "      - run: uv run python scripts/check_m8_host_artifact_mutations.py\n"
    assert workflow.count(step) == 1
    assert workflow.index("      - run: uv run verify\n") < workflow.index(step)


def test_script_bubblewrap_pin_is_the_launcher_pin() -> None:
    """The script imports no repository code, so only a test holds these in step."""

    from constructicon.substrate.executors.linux import BWRAP_SHA256

    assert artifacts.BWRAP_SHA256 == BWRAP_SHA256 == probe.BWRAP_SHA256


def test_installed_layout_is_the_layout_the_probe_and_ci_use() -> None:
    assert "/" + artifacts.DIRECTORY + "/bwrap" == probe.BWRAP
    assert probe.POLICY.as_posix() == "/" + artifacts.PROFILE_DESTINATION
    assert "{}//&{} (enforce)".format(*artifacts.PROFILE_NAMES) == probe.CHILD_PROFILE
    workflow = (REPOSITORY / ".github/workflows/m8-runner-qualification.yml").read_text(
        encoding="utf-8"
    )
    assert f"install -d -m {artifacts.DIRECTORY_MODE:04o} /{artifacts.DIRECTORY}" in workflow
    for destination, (source, mode) in artifacts.FILES.items():
        origin = "/usr/bin/bwrap" if source is None else source
        assert f"install -m {mode:04o} {origin} /{destination}" in workflow
    assert f"apparmor_parser --add --skip-cache /{artifacts.PROFILE_DESTINATION}" in workflow


def runbook() -> str:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert text.count("\n# Operator runbook\n") == 1
    return text.split("\n# Operator runbook\n", 1)[1]


def test_the_runbook_root_sequence_is_the_fixed_inventory() -> None:
    text = runbook()
    positions = []
    for command in root_sequence():
        line = "sudo " + " ".join(command)
        assert text.count(line) == 1, line
        positions.append(text.index(line))
    assert positions == sorted(positions), "the runbook installs in the inventory's order"


def runbook_code() -> str:
    """Every command the runbook shows: fenced blocks without comments, and inline code."""

    text = runbook()
    fenced = re.findall(r"```[a-z]*\n(.*?)```", text, re.S)
    inline = re.findall(r"`([^`\n]+)`", re.sub(r"```.*?```", "", text, flags=re.S))
    lines = [re.sub(r"(^|\s)#.*", "", line) for block in fenced for line in block.splitlines()]
    return "\n".join(lines + inline)


def test_root_runs_only_named_stock_tools_in_the_runbook() -> None:
    """Root executes no repository code: every ``sudo`` names a stock tool or m8-probe."""

    invoked = re.findall(r"\bsudo\s+(-u\s+m8-probe|\S+)", runbook_code())
    assert len(invoked) >= 10, "the sudo walk found too little, so it proved nothing"
    stock = {
        "/usr/bin/install",
        "/usr/sbin/apparmor_parser",
        "/usr/bin/cat",
        "/usr/bin/rm",
        "/usr/bin/rmdir",
        "/usr/bin/apt-get",
        "/usr/sbin/useradd",
        "-l",
        "-u m8-probe",
    }
    assert set(invoked) <= stock, set(invoked) - stock
    # The judge proves custody of exactly the tools root runs in R4.
    assert {"/" + tool for tool in artifacts.ROOT_TOOLS} == {
        "/usr/bin/install",
        "/usr/bin/cat",
        "/usr/sbin/apparmor_parser",
    }
    assert {"/" + tool for tool in artifacts.ROOT_TOOLS} <= set(invoked)


def test_hosted_runner_guards_are_unchanged() -> None:
    guards = {
        "build_m8_runtime.py": (
            '    if os.getuid() != 0 or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":\n'
            '        raise SystemExit("provisioning requires the explicitly authorized '
            'disposable runner")\n'
        ),
        "build_m8_startup_fixture.py": (
            '    if os.getuid() != 0 or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":\n'
            '        raise SystemExit("startup fixture requires the authorized '
            'disposable runner")\n'
        ),
        "build_m8_store_fixture.py": (
            '    if os.geteuid() != 0 or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":\n'
            '        raise SystemExit("native-store fixture provisioning requires the disposable '
            'hosted runner")\n'
        ),
    }
    for name, guard in guards.items():
        text = (REPOSITORY / "scripts/ci" / name).read_text(encoding="utf-8")
        assert text.count(guard) == 1, name
    runtime = (REPOSITORY / "scripts/ci/build_m8_runtime.py").read_text(encoding="utf-8")
    comment = runtime.split("def main() -> None:\n", 1)[1].split("\n", 1)[0]
    assert comment.startswith("    # ") and "scripts/ci/m8_host_artifacts.py" in comment


# --- provenance (portable) -------------------------------------------------


def test_reviewed_commit_on_main_yields_raw_blobs(tmp_path: Path) -> None:
    work, reviewed_commit = work_repository(tmp_path, reviewed())
    later = commit_after(work)
    source = bare(work, tmp_path / "source.git")
    record: dict[str, object] = {}
    blobs = artifacts.prove(reviewed_commit, source, record)
    assert blobs == reviewed()
    assert record["main"] == later and record["first_parent"] is True
    assert record["script_matches_commit"] is True
    assert record["blobs"] == {
        path: {"oid": git(work, "rev-parse", f"{reviewed_commit}:{path}"), "sha256": sha256(data)}
        for path, data in reviewed().items()
    }


def commit_after(work: Path) -> str:
    place(work, {"README.md": b"later\n"})
    return commit(work, "later work on main")


def test_commit_off_main_is_refused(tmp_path: Path) -> None:
    work, _ = work_repository(tmp_path, reviewed())
    git(work, "switch", "-q", "-c", "side")
    place(work, {artifacts.PROBE: b"# unreviewed probe\n"})
    side = commit(work, "never merged")
    source = bare(work, tmp_path / "source.git")
    record: dict[str, object] = {}
    with pytest.raises(ValueError, match="not on the first-parent line of the fetched main"):
        artifacts.prove(side, source, record)
    assert record["first_parent"] is False
    assert "blobs" not in record


def test_a_merged_branch_commit_off_the_first_parent_line_is_refused(tmp_path: Path) -> None:
    """A merge commit makes every commit of the merged branch an ancestor of main."""

    work, _ = work_repository(tmp_path, reviewed())
    git(work, "switch", "-q", "-c", "feature")
    place(work, {artifacts.PROBE: b"# intermediate, unreviewed probe\n"})
    intermediate = commit(work, "intermediate branch commit")
    place(work, {artifacts.PROBE: PROBE_BYTES})
    commit(work, "reviewed branch head")
    git(work, "switch", "-q", "main")
    git(work, "merge", "-q", "--no-ff", "-m", "merge the reviewed branch", "feature")
    merged = git(work, "rev-parse", "HEAD")
    source = bare(work, tmp_path / "source.git")
    record: dict[str, object] = {}
    with pytest.raises(ValueError, match="not on the first-parent line"):
        artifacts.prove(intermediate, source, record)
    assert record["first_parent"] is False
    assert "blobs" not in record
    accepted: dict[str, object] = {}
    assert artifacts.prove(merged, source, accepted) == reviewed()
    assert accepted["first_parent"] is True


@pytest.mark.parametrize(
    "name",
    ["main", "HEAD", "--output=/tmp/x", "", "A" * 40, "a" * 39, "a" * 41, "g" * 40],
)
def test_commit_must_be_exact_hex_before_git_runs(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(argv: list[str]) -> None:
        pytest.fail("a malformed commit reached git")

    monkeypatch.setattr(artifacts, "run", unexpected)
    with pytest.raises(ValueError, match="exactly 40 lowercase hex"):
        artifacts.prove(name, tmp_path, {})


def test_uppercase_and_abbreviated_names_of_a_real_commit_are_refused(tmp_path: Path) -> None:
    work, reviewed_commit = work_repository(tmp_path, reviewed())
    source = bare(work, tmp_path / "source.git")
    for name in (reviewed_commit.upper(), reviewed_commit[:12]):
        with pytest.raises(ValueError, match="exactly 40 lowercase hex"):
            artifacts.prove(name, source, {})


def test_an_object_that_is_not_a_commit_is_refused(tmp_path: Path) -> None:
    """Only commit ids appear on the first-parent line, so no separate type check exists."""

    work, reviewed_commit = work_repository(tmp_path, reviewed())
    git(work, "tag", "-a", "v1", "-m", "an annotated tag naming the reviewed commit")
    source = bare(work, tmp_path / "source.git")
    blob = git(work, "rev-parse", f"{reviewed_commit}:{artifacts.PROBE}")
    tag = git(source, "rev-parse", "refs/tags/v1")
    assert tag != reviewed_commit
    for name in (blob, tag, "0123456789abcdef0123456789abcdef01234567"):
        with pytest.raises(ValueError, match="not on the first-parent line"):
            artifacts.prove(name, source, {})


def test_a_repository_without_main_is_refused(tmp_path: Path) -> None:
    work, reviewed_commit = work_repository(tmp_path, reviewed())
    git(work, "branch", "-q", "-m", "main", "trunk")
    source = bare(work, tmp_path / "source.git")
    with pytest.raises(ValueError, match="no fetched main"):
        artifacts.prove(reviewed_commit, source, {})


def index_entry(work: Path, mode: str, path: str, data: bytes) -> str:
    oid = git(work, "hash-object", "-w", "--stdin", stdin=data)
    git(work, "rm", "-q", "--cached", "--ignore-unmatch", path)
    git(work, "update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}")
    git(work, "commit", "-q", "-m", f"{path} as {mode}")
    return git(work, "rev-parse", "HEAD")


@pytest.mark.parametrize("path", [artifacts.SCRIPT, artifacts.PROBE, artifacts.PROFILE])
@pytest.mark.parametrize("mode", ["100755", "120000"])
def test_each_artifact_must_be_a_regular_non_executable_blob(
    path: str, mode: str, tmp_path: Path
) -> None:
    work, _ = work_repository(tmp_path, reviewed())
    drifted = index_entry(work, mode, path, reviewed()[path])
    source = bare(work, tmp_path / "source.git")
    with pytest.raises(ValueError, match=f"{path} is not one regular non-executable blob"):
        artifacts.prove(drifted, source, {})


def test_a_tree_or_missing_path_is_refused(tmp_path: Path) -> None:
    files = reviewed()
    del files[artifacts.PROFILE]
    files[artifacts.PROFILE + "/nested"] = PROFILE_BYTES
    work, drifted = work_repository(tmp_path, files)
    source = bare(work, tmp_path / "source.git")
    with pytest.raises(ValueError, match=f"{artifacts.PROFILE} is not one regular"):
        artifacts.prove(drifted, source, {})
    files = reviewed()
    del files[artifacts.PROBE]
    work, missing = work_repository(tmp_path / "second", files)
    source = bare(work, tmp_path / "second.git")
    with pytest.raises(ValueError, match=f"{artifacts.PROBE} is not one regular"):
        artifacts.prove(missing, source, {})


@pytest.mark.parametrize("drift", ["one byte", "line endings"])
def test_a_running_script_that_is_not_the_reviewed_blob_is_refused(
    drift: str, tmp_path: Path
) -> None:
    running = SOURCE.read_bytes()
    if drift == "one byte":
        committed = running.replace(b"Stdlib only", b"stdlib only", 1)
    elif b"\r\n" in running:
        # A Windows checkout materialises CRLF; the reviewed blob is LF.
        committed = running.replace(b"\r\n", b"\n")
    else:
        committed = running.replace(b"\n", b"\r\n")
    assert committed != running
    work, reviewed_commit = work_repository(tmp_path, reviewed(committed))
    source = bare(work, tmp_path / "source.git")
    record: dict[str, object] = {}
    with pytest.raises(ValueError, match="running script is not the script at commit"):
        artifacts.prove(reviewed_commit, source, record)
    assert "script_matches_commit" not in record


def test_a_replacement_ref_cannot_substitute_an_artifact(tmp_path: Path) -> None:
    work, reviewed_commit = work_repository(tmp_path, reviewed())
    source = bare(work, tmp_path / "source.git")
    original = git(work, "rev-parse", f"{reviewed_commit}:{artifacts.PROBE}")
    hostile = git(source, "hash-object", "-w", "--stdin", stdin=b"# substituted probe\n")
    git(source, "replace", original, hostile)
    assert git(source, "cat-file", "blob", original) == "# substituted probe"
    assert artifacts.prove(reviewed_commit, source, {})[artifacts.PROBE] == PROBE_BYTES


def test_a_grafts_file_cannot_move_a_commit_onto_the_first_parent_line(tmp_path: Path) -> None:
    """``--no-replace-objects`` does not disable ``info/grafts``; the fixed environment does."""

    work, _ = work_repository(tmp_path, reviewed())
    git(work, "switch", "-q", "-c", "feature")
    place(work, {artifacts.PROBE: b"# intermediate, unreviewed probe\n"})
    intermediate = commit(work, "intermediate branch commit")
    git(work, "switch", "-q", "main")
    git(work, "merge", "-q", "--no-ff", "-m", "merge the branch", "feature")
    merged = git(work, "rev-parse", "HEAD")
    source = bare(work, tmp_path / "source.git")
    (source / "info").mkdir(exist_ok=True)
    (source / "info" / "grafts").write_text(f"{merged} {intermediate}\n", encoding="utf-8")
    assert intermediate in git(source, "rev-list", "--first-parent", "main").split()
    record: dict[str, object] = {}
    with pytest.raises(ValueError, match="not on the first-parent line"):
        artifacts.prove(intermediate, source, record)
    assert record["first_parent"] is False


# --- the kernel's loaded-profile list (portable) ---------------------------


@pytest.mark.parametrize(
    "listing",
    ["", "\n", "sudo: a password is required\n", KERNEL_LIST + "no mode on this line\n"],
)
def test_an_empty_or_malformed_profile_list_proves_nothing(listing: str) -> None:
    """A failed ``sudo cat`` pipes nothing; that must never read as nothing loaded."""

    with pytest.raises(ValueError, match="empty or not in the kernel's format"):
        artifacts.loaded_profiles(listing)


def test_the_profile_list_keeps_only_constructicon_profiles() -> None:
    listing = KERNEL_LIST + "constructicon-m8-bwrap (enforce)\nconstructicon-m8-payload (kill)\n"
    assert artifacts.loaded_profiles(listing) == [
        "constructicon-m8-bwrap (enforce)",
        "constructicon-m8-payload (kill)",
    ]
    assert artifacts.loaded_profiles(KERNEL_LIST) == []


# --- judgement of observed state (portable) --------------------------------

DIGESTS = {artifacts.PROBE: sha256(PROBE_BYTES), artifacts.PROFILE: sha256(PROFILE_BYTES)}


def installed_observation() -> dict[str, object]:
    observed: dict[str, object] = {
        "/" + artifacts.DIRECTORY: {
            "state": "directory",
            "uid": 0,
            "mode": "0o755",
            "entries": ["bwrap", "probe.py"],
        },
        "loaded_profiles": [
            "constructicon-m8-bwrap (enforce)",
            "constructicon-m8-payload (enforce)",
        ],
    }
    for destination, (source, mode) in artifacts.FILES.items():
        digest = artifacts.BWRAP_SHA256 if source is None else DIGESTS[source]
        observed["/" + destination] = {
            "state": "file",
            "uid": 0,
            "mode": oct(mode),
            "sha256": digest,
        }
    return observed


def expected() -> dict[str, tuple[str, int, object]]:
    return artifacts.expected({artifacts.PROBE: PROBE_BYTES, artifacts.PROFILE: PROFILE_BYTES})


def test_the_reviewed_installation_is_assessed_installed() -> None:
    artifacts.assess(installed_observation(), expected())


PROBE_PATH = "/" + artifacts.DIRECTORY + "/probe.py"
BWRAP_PATH = "/" + artifacts.DIRECTORY + "/bwrap"
PROFILE_PATH = "/" + artifacts.PROFILE_DESTINATION
DIRECTORY_PATH = "/" + artifacts.DIRECTORY


@pytest.mark.parametrize(
    ("path", "field", "value", "fault"),
    [
        (PROBE_PATH, "state", "absent", "is not a file"),
        (PROBE_PATH, "state", "symlink", "is not a file"),
        (BWRAP_PATH, "state", "other", "is not a file"),
        (DIRECTORY_PATH, "state", "symlink", "is not a directory"),
        (PROBE_PATH, "uid", 1000, "is not root-owned"),
        (PROFILE_PATH, "uid", 1000, "is not root-owned"),
        (DIRECTORY_PATH, "uid", 1000, "is not root-owned"),
        (PROBE_PATH, "mode", "0o644", "mode is not 0o444"),
        (BWRAP_PATH, "mode", "0o4555", "mode is not 0o555"),
        (PROFILE_PATH, "mode", "0o666", "mode is not 0o444"),
        (DIRECTORY_PATH, "mode", "0o777", "mode is not 0o755"),
        (PROBE_PATH, "sha256", sha256(b"# reviewed probe\r\n"), "not the reviewed content"),
        (BWRAP_PATH, "sha256", sha256(b"other build"), "not the reviewed content"),
        (PROFILE_PATH, "sha256", sha256(PROFILE_BYTES.replace(b"\n", b"\r\n")), "reviewed content"),
        (DIRECTORY_PATH, "entries", ["bwrap", "extra", "probe.py"], "not the reviewed content"),
        (DIRECTORY_PATH, "entries", ["probe.py"], "not the reviewed content"),
    ],
)
def test_each_observed_fact_is_required(path: str, field: str, value: object, fault: str) -> None:
    observed = installed_observation()
    entry = observed[path]
    assert isinstance(entry, dict)
    entry[field] = value
    with pytest.raises(ValueError, match=fault):
        artifacts.assess(observed, expected())


def test_absence_is_never_assessed_installed() -> None:
    observed: dict[str, object] = {
        "/" + destination: {"state": "absent"}
        for destination in (artifacts.DIRECTORY, *artifacts.FILES)
    }
    observed["loaded_profiles"] = []
    with pytest.raises(ValueError, match="is not a directory"):
        artifacts.assess(observed, expected())


@pytest.mark.parametrize(
    "profiles",
    [
        [],
        ["constructicon-m8-bwrap (enforce)"],
        ["constructicon-m8-payload (enforce)"],
        ["constructicon-m8-bwrap (complain)", "constructicon-m8-payload (enforce)"],
        ["constructicon-m8-bwrap (enforce)", "constructicon-m8-payload (complain)"],
        "unobservable: ValueError",
    ],
)
def test_both_profiles_must_be_loaded_in_enforce_mode(profiles: object) -> None:
    observed = installed_observation()
    observed["loaded_profiles"] = profiles
    with pytest.raises(ValueError, match="loaded in enforce mode"):
        artifacts.assess(observed, expected())


def test_a_shrunken_inventory_is_never_assessed_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound binds only when a fixed entry goes unchecked."""

    files = dict(artifacts.FILES)
    del files[artifacts.PROFILE_DESTINATION]
    monkeypatch.setattr(artifacts, "FILES", files)
    with pytest.raises(ValueError, match="fixed inventory"):
        artifacts.assess(installed_observation(), expected())


# --- the command record (portable) -----------------------------------------

VERDICT = {"judge": "ready", "verify": "installed"}


@pytest.mark.parametrize("command", ["judge", "verify"])
@pytest.mark.parametrize("failure", [False, True])
def test_the_exit_status_follows_the_verdict(
    command: str,
    failure: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[tuple[str, Path, str]] = []

    def deciding(commit: str, root: Path, workspace: Path, listing: str, record: dict) -> None:
        seen.append((commit, workspace, listing))
        if failure:
            raise ValueError("deliberately unproven")
        record[VERDICT[command]] = True

    monkeypatch.setattr(artifacts, command, deciding)
    monkeypatch.setattr(artifacts, "observe", lambda root, listing: {"observed": listing})
    feed(monkeypatch, KERNEL_LIST)
    assert artifacts.main([command, "a" * 40, "/workspace"]) == int(failure)
    record = json.loads(capsys.readouterr().out)
    assert seen == [("a" * 40, Path("/workspace"), KERNEL_LIST)]
    assert record.get(VERDICT[command]) is (not failure)
    other = VERDICT["verify" if command == "judge" else "judge"]
    assert other not in record, "each command reports its own verdict only"
    assert ("failure" in record) == failure
    assert (record.get("observed") == {"observed": KERNEL_LIST}) == failure


@pytest.mark.parametrize("command", ["judge", "verify"])
@pytest.mark.parametrize("excess", [0, 1])
def test_a_profile_list_beyond_its_bound_refuses_before_the_command(
    command: str,
    excess: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The list must end within the bound; a truncated read proves nothing about the rest."""

    ran: list[str] = []

    def deciding(commit: str, root: Path, workspace: Path, listing: str, record: dict) -> None:
        ran.append(listing)
        record[VERDICT[command]] = True

    monkeypatch.setattr(artifacts, command, deciding)
    monkeypatch.setattr(artifacts, "observe", lambda root, listing: {})
    line = " (enforce)\n"
    listing = "p" * (artifacts.LISTING_LIMIT - len(line)) + line + "q" * excess
    assert len(listing.encode()) == artifacts.LISTING_LIMIT + excess
    feed(monkeypatch, listing)
    assert artifacts.main([command, "a" * 40, "/workspace"]) == excess
    record = json.loads(capsys.readouterr().out)
    if excess:
        assert ran == [] and "exceeds its bound" in record["failure"]
    else:
        assert ran == [listing] and record[VERDICT[command]] is True


@pytest.mark.parametrize("command", ["judge", "verify"])
def test_a_command_that_records_nothing_reports_false(
    command: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(artifacts, command, lambda *arguments: None)
    feed(monkeypatch, KERNEL_LIST)
    assert artifacts.main([command, "a" * 40, "/workspace"]) == 1
    record = json.loads(capsys.readouterr().out)
    assert record[VERDICT[command]] is False and "failure" not in record


def test_exits_without_a_record_are_limits_never_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Help and an uncaught exception print no record; the runbook requires the verdict."""

    with pytest.raises(SystemExit) as helped:
        artifacts.main(["verify", "-h"])
    assert helped.value.code == 0 and '"installed"' not in capsys.readouterr().out

    def crashing(*arguments: object) -> None:
        raise RuntimeError("not one of the recorded failure types")

    monkeypatch.setattr(artifacts, "verify", crashing)
    feed(monkeypatch, KERNEL_LIST)
    with pytest.raises(RuntimeError):
        artifacts.main(["verify", "a" * 40, "/workspace"])
    assert capsys.readouterr().out == ""


# --- judge, root's stock tools, verify on a temporary host (Linux only) ----


class Host:
    """A temporary host: root-owned by the uid view, with the operator's home kept real."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = tmp_path / "host"
        self.home = self.root / "home/operator"
        self.log = tmp_path / "parser.log"
        self.kernel = tmp_path / "kernel-profiles"
        self.kernel.write_text(KERNEL_LIST, encoding="utf-8")
        for directory in ("", "opt", "etc", "etc/apparmor.d", "usr", "usr/bin", "usr/sbin", "home"):
            (self.root / directory).mkdir(mode=0o755, exist_ok=True)
            (self.root / directory).chmod(0o755)
        self.home.mkdir(mode=0o750)
        self.home.chmod(0o750)
        self.workspace = self.home / "m8-host"
        self.workspace.mkdir(mode=0o700)
        self.workspace.chmod(0o700)
        bwrap = self.root / artifacts.BWRAP_SOURCE
        bwrap.write_bytes(FAKE_BWRAP)
        bwrap.chmod(0o755)
        # Stand-ins whose custody the judge proves; the sequence runs the real install.
        for tool in (artifacts.INSTALL, artifacts.CAT):
            (self.root / tool).write_bytes(b"#!/bin/sh\nexit 99\n")
            (self.root / tool).chmod(0o755)
        self.parser(0)
        work, self.commit = work_repository(tmp_path, reviewed())
        self.main = commit_after(work)
        self.work = work
        bare(work, self.workspace / artifacts.REPOSITORY)
        # R3's stock-git extraction; these are the blobs at the commit.
        (self.workspace / artifacts.STAGING).mkdir(mode=0o700)
        for destination, (source, _) in artifacts.FILES.items():
            if source is not None:
                self.staged(destination).write_bytes(reviewed()[source])
        self.root_uid = os.getuid() + 4000
        self.owners: dict[Path, int] = {}
        lstat = os.lstat

        def observing(path: object, *arguments: object, **options: object) -> os.stat_result:
            info = lstat(path, *arguments, **options)  # type: ignore[arg-type]
            if not isinstance(path, str | os.PathLike):
                return info
            target = Path(path)
            uid = self.owners.get(target)
            if (
                uid is None
                and info.st_uid == os.getuid()
                and target.is_relative_to(self.root)
                and not target.is_relative_to(self.home)
            ):
                uid = self.root_uid
            if uid is None:
                return info
            fields = list(info[:10])
            fields[4] = uid
            return os.stat_result(fields)

        monkeypatch.setattr(artifacts.os, "lstat", observing)
        monkeypatch.setattr(artifacts, "ROOT", self.root)
        monkeypatch.setattr(artifacts, "ROOT_UID", self.root_uid)
        monkeypatch.setattr(artifacts, "BWRAP_SHA256", sha256(FAKE_BWRAP))
        self.monkeypatch = monkeypatch

    def staged(self, destination: str) -> Path:
        return self.workspace / artifacts.STAGING / PurePosixPath(destination).name

    def parser(self, status: int) -> None:
        parser = self.root / artifacts.PARSER
        parser.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$*\" >> '{self.log}'\n"
            f"test {status} = 0 || exit {status}\n"
            "printf 'constructicon-m8-bwrap (enforce)\\nconstructicon-m8-payload (enforce)\\n'"
            f" >> '{self.kernel}'\n",
            encoding="utf-8",
        )
        parser.chmod(0o755)

    def run(
        self, command: str, capsys: pytest.CaptureFixture[str], listing: str | None = None
    ) -> tuple[int, dict]:
        if listing is None:
            listing = self.kernel.read_text(encoding="utf-8")
        feed(self.monkeypatch, listing)
        status = artifacts.main([command, self.commit, str(self.workspace)])
        return status, json.loads(capsys.readouterr().out)

    def install(self, steps: int | None = None) -> int:
        """Root's R4 sequence, chained like ``&&``, minus ``-o root -g root``."""

        installer = shutil.which("install")
        assert installer is not None, "coreutils install is required"
        for command in root_sequence()[:steps]:
            tool, *arguments = command
            if tool == INSTALL:
                argv = [installer]
                start = arguments.index("-o")
                assert tuple(arguments[start : start + 4]) == OWNER
                del arguments[start : start + 4]
            else:
                argv = [str(self.root / artifacts.PARSER)]
            for argument in arguments:
                if argument.startswith('"$W/'):
                    argv.append(str(self.workspace) + argument[3:-1])
                elif argument.startswith("/"):
                    argv.append(str(self.root) + argument)
                else:
                    argv.append(argument)
            status = subprocess.run(argv, check=False, capture_output=True, timeout=30).returncode
            if status:
                return status
        return 0

    def absent(self) -> bool:
        return not any(
            os.path.lexists(self.root / destination)
            for destination in (artifacts.DIRECTORY, *artifacts.FILES)
        )


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Host:
    return Host(tmp_path, monkeypatch)


def judged(host: Host, capsys: pytest.CaptureFixture[str]) -> dict:
    status, record = host.run("judge", capsys)
    assert status == 0 and record["ready"] is True, record
    return record


@LINUX
def test_judge_then_the_root_sequence_then_verify_accepts(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    record = judged(host, capsys)
    assert "failure" not in record and "installed" not in record
    assert record["first_parent"] is True and record["main"] == host.main
    assert record["script_matches_commit"] is True
    assert host.absent() and not host.log.exists(), "the judge wrote or loaded something"
    assert host.install() == 0
    profile = host.root / artifacts.PROFILE_DESTINATION
    assert host.log.read_text(encoding="utf-8") == f"--add --skip-cache {profile}\n"
    status, verified = host.run("verify", capsys)
    assert status == 0 and verified["installed"] is True and "failure" not in verified
    assert "ready" not in verified
    directory = host.root / artifacts.DIRECTORY
    assert verified["observed"]["/" + artifacts.DIRECTORY] == {
        "state": "directory",
        "uid": host.root_uid,
        "mode": "0o755",
        "entries": ["bwrap", "probe.py"],
    }
    assert sorted(os.listdir(directory)) == ["bwrap", "probe.py"]
    for destination, (source, mode) in artifacts.FILES.items():
        data = FAKE_BWRAP if source is None else reviewed()[source]
        assert (host.root / destination).read_bytes() == data
        assert verified["observed"]["/" + destination] == {
            "state": "file",
            "uid": host.root_uid,
            "mode": oct(mode),
            "sha256": sha256(data),
        }
    assert verified["observed"]["loaded_profiles"] == [
        "constructicon-m8-bwrap (enforce)",
        "constructicon-m8-payload (enforce)",
    ]


@LINUX
def test_the_root_sequence_modes_do_not_depend_on_the_umask(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    judged(host, capsys)
    previous = os.umask(0o277)
    try:
        assert host.install() == 0
    finally:
        os.umask(previous)
    status, verified = host.run("verify", capsys)
    assert status == 0 and verified["installed"] is True, verified


@LINUX
def test_nothing_installed_is_reported_itemized_and_not_installed(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    status, record = host.run("verify", capsys)
    assert status == 1 and record["installed"] is False
    assert "is not a directory" in record["failure"]
    for destination in (artifacts.DIRECTORY, *artifacts.FILES):
        assert record["observed"]["/" + destination] == {"state": "absent"}
    assert record["observed"]["loaded_profiles"] == []


def refused(host: Host, capsys: pytest.CaptureFixture[str], fault: str, **run: str) -> dict:
    status, record = host.run("judge", capsys, **run)
    assert status == 1 and record["ready"] is False
    assert fault in record["failure"], record["failure"]
    assert host.absent() and not host.log.exists()
    return record


@LINUX
@pytest.mark.parametrize("command", ["judge", "verify"])
def test_the_script_refuses_to_run_as_root(
    command: str, host: Host, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The effective uid reads 0 and the uid view shows the operator's home as
    # uid 0's, so custody and every other check pass for "this account": this
    # check alone refuses, and without it judge would succeed.
    monkeypatch.setattr(artifacts.os, "geteuid", lambda: 0)
    host.owners[host.workspace] = 0
    host.owners[host.home] = 0
    status, record = host.run(command, capsys)
    assert status == 1 and record[VERDICT[command]] is False
    assert "never runs as root" in record["failure"]


@LINUX
@pytest.mark.parametrize(
    "unsafe", ["group readable", "symlink", "not owned", "relative", "source symlink"]
)
def test_the_workspace_must_be_private_to_this_account(
    unsafe: str, host: Host, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    faults = {
        "group readable": "must be a private directory owned by this account",
        "symlink": "must be a private directory owned by this account",
        "not owned": "must be a private directory owned by this account",
        "relative": "must be an absolute path",
        "source symlink": "source.git must be a real directory",
    }
    if unsafe == "group readable":
        host.workspace.chmod(0o750)
    elif unsafe == "symlink":
        moved = host.home / "elsewhere"
        host.workspace.rename(moved)
        host.workspace.symlink_to(moved)
    elif unsafe == "not owned":
        host.owners[host.workspace] = os.getuid() + 1
    elif unsafe == "relative":
        # Relative to the root, every relative parent passes; only the check refuses.
        monkeypatch.chdir(host.root)
        host.workspace = host.workspace.relative_to(host.root)
    else:
        source = host.workspace / artifacts.REPOSITORY
        moved = host.home / "source.git"
        source.rename(moved)
        source.symlink_to(moved)
    refused(host, capsys, faults[unsafe])


@LINUX
@pytest.mark.parametrize("ancestor", ["home/operator", "home", ""])
@pytest.mark.parametrize("unsafe", ["group writable", "world writable", "symlink", "not owned"])
def test_workspace_ancestors_are_owned_by_root_or_this_account(
    ancestor: str, unsafe: str, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    path = host.root / ancestor
    if unsafe == "group writable":
        path.chmod(0o775)
    elif unsafe == "world writable":
        path.chmod(0o757)
    elif unsafe == "symlink":
        moved = path.with_name(path.name + ".real")
        path.rename(moved)
        path.symlink_to(moved)
    else:
        host.owners[path] = os.getuid() + 1
    refused(host, capsys, "must be a real directory owned by root or this account")


@LINUX
@pytest.mark.parametrize(
    "destination", [d for d, (source, _) in artifacts.FILES.items() if source is not None]
)
@pytest.mark.parametrize("drift", ["one byte", "line endings", "symlink", "fifo", "missing"])
def test_each_staged_copy_must_be_the_blob_at_commit(
    destination: str, drift: str, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    staged = host.staged(destination)
    data = staged.read_bytes()
    if drift == "one byte":
        staged.write_bytes(data.replace(b"reviewed", b"Reviewed").replace(b"profile", b"Profile"))
    elif drift == "line endings":
        staged.write_bytes(data.replace(b"\n", b"\r\n"))
    elif drift == "symlink":
        # Root's install follows a source symlink, so the judge must refuse one.
        copy = host.home / "same-bytes"
        copy.write_bytes(data)
        staged.unlink()
        staged.symlink_to(copy)
    elif drift == "fifo":
        # An unfed FIFO would read as empty; the regular-file check names it.
        staged.unlink()
        os.mkfifo(staged)
    else:
        staged.unlink()
    fault = {
        "one byte": f"the staged {staged.name} is not the blob at commit",
        "line endings": f"the staged {staged.name} is not the blob at commit",
        "symlink": "OSError",
        "fifo": "is not a regular file",
        "missing": "FileNotFoundError",
    }[drift]
    refused(host, capsys, fault)


@LINUX
def test_a_symlinked_staging_directory_is_refused(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    staging = host.workspace / artifacts.STAGING
    moved = host.home / "staging"
    staging.rename(moved)
    staging.symlink_to(moved)
    refused(host, capsys, "staging must be a real directory")


@LINUX
def test_unpinned_host_bubblewrap_is_refused(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    (host.root / artifacts.BWRAP_SOURCE).write_bytes(FAKE_BWRAP + b"drift")
    refused(host, capsys, "not the pinned build")


@LINUX
@pytest.mark.parametrize("path", [artifacts.BWRAP_SOURCE, *artifacts.ROOT_TOOLS])
@pytest.mark.parametrize(
    "unsafe",
    [
        "symlink",
        "directory",
        "fifo",
        "group writable",
        "not owned",
        "operator owned",
        "unsafe parent",
    ],
)
def test_what_root_copies_or_runs_is_roots_alone(
    path: str, unsafe: str, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    """No other account can swap bubblewrap or a root tool between judge and install."""

    target = host.root / path
    if unsafe == "symlink":
        moved = target.with_name(target.name + ".real")
        target.rename(moved)
        target.symlink_to(moved)
    elif unsafe == "directory":
        target.unlink()
        target.mkdir()
    elif unsafe == "fifo":
        target.unlink()
        os.mkfifo(target)
    elif unsafe == "group writable":
        target.chmod(0o775)
    elif unsafe == "not owned":
        host.owners[target] = os.getuid() + 1
    elif unsafe == "operator owned":
        host.owners[target] = os.getuid()
    else:
        target.parent.chmod(0o775)
    if unsafe == "unsafe parent":
        refused(host, capsys, "must be a real directory owned by root that")
    else:
        refused(host, capsys, "must be a regular file owned by root that")


@LINUX
@pytest.mark.parametrize("destination", [artifacts.DIRECTORY, *artifacts.FILES])
@pytest.mark.parametrize("residue", ["file", "dangling symlink"])
def test_any_existing_destination_refuses_judgement(
    destination: str, residue: str, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    path = host.root / destination
    path.parent.mkdir(mode=0o755, exist_ok=True)
    if residue == "file":
        path.write_bytes(b"residue")
    else:
        path.symlink_to(host.root / "nowhere")
    status, record = host.run("judge", capsys)
    assert status == 1 and record["ready"] is False
    assert "already exists" in record["failure"], record["failure"]
    assert record["observed"]["/" + destination]["state"] == (
        "file" if residue == "file" else "symlink"
    )


@LINUX
def test_an_unsearchable_destination_parent_is_not_absence(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only ENOENT is absence; a lookup the operator cannot make proves nothing."""

    parent = host.root / "etc/apparmor.d"
    parent.chmod(0o600)
    try:
        refused(host, capsys, "PermissionError")
    finally:
        parent.chmod(0o755)


@LINUX
@pytest.mark.parametrize("ancestor", ["opt", "etc/apparmor.d", "etc", ""])
@pytest.mark.parametrize(
    "unsafe", ["world writable", "group writable", "symlink", "not owned", "operator owned"]
)
def test_every_destination_ancestor_is_a_root_owned_unwritable_directory(
    ancestor: str, unsafe: str, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    path = host.root / ancestor
    if unsafe == "world writable":
        path.chmod(0o757)
    elif unsafe == "group writable":
        path.chmod(0o775)
    elif unsafe == "symlink":
        # For the root itself, ROOT then names the link.
        moved = path.with_name(path.name + ".real")
        path.rename(moved)
        path.symlink_to(moved)
    elif unsafe == "not owned":
        host.owners[path] = os.getuid() + 1
    else:
        # This account may own its workspace's ancestors, never a destination's.
        host.owners[path] = os.getuid()
    fault = "must be a real directory owned by root that"
    if ancestor == "" and unsafe != "operator owned":
        # The root is also a workspace ancestor, which is checked first.
        fault = "must be a real directory owned by root or this account"
    refused(host, capsys, fault)


@LINUX
def test_an_already_loaded_profile_refuses_judgement(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    host.kernel.write_text(KERNEL_LIST + "constructicon-m8-payload (complain)\n", encoding="utf-8")
    refused(host, capsys, "already loaded")


@LINUX
def test_loaded_launch_profiles_do_not_block_the_qualification_judge(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    """The judge refuses only its own two profiles, so the launch set can stay loaded."""

    launch = "constructicon-m8-launch (enforce)\nconstructicon-m8-workload (enforce)\n"
    host.kernel.write_text(KERNEL_LIST + launch, encoding="utf-8")
    judged(host, capsys)


@LINUX
@pytest.mark.parametrize("listing", ["", "sudo: a terminal is required to read the password\n"])
def test_a_failed_profile_list_refuses_judgement(
    listing: str, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    refused(host, capsys, "empty or not in the kernel's format", listing=listing)


@LINUX
@pytest.mark.parametrize("tool", artifacts.ROOT_TOOLS)
def test_a_missing_root_tool_refuses_judgement(
    tool: str, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    (host.root / tool).unlink()
    refused(host, capsys, "FileNotFoundError")


@LINUX
def test_staging_modified_after_judgement_is_caught_by_verify(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    judged(host, capsys)
    host.staged(artifacts.DIRECTORY + "/probe.py").write_bytes(b"# edited after judgement\n")
    assert host.install() == 0
    status, record = host.run("verify", capsys)
    assert status == 1 and record["installed"] is False
    assert PROBE_PATH + " is not the reviewed content" in record["failure"]


@LINUX
def test_verify_compares_against_git_never_against_staging(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    judged(host, capsys)
    assert host.install() == 0
    shutil.rmtree(host.workspace / artifacts.STAGING)
    status, record = host.run("verify", capsys)
    assert status == 0 and record["installed"] is True, record


@LINUX
@pytest.mark.parametrize("steps", [1, 2, 3, 4])
def test_a_partial_installation_is_never_installed_and_blocks_a_rerun(
    steps: int, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    judged(host, capsys)
    assert host.install(steps) == 0
    status, record = host.run("verify", capsys)
    assert status == 1 and record["installed"] is False
    observed = record["observed"]
    assert observed["/" + artifacts.DIRECTORY]["state"] == "directory"
    written = list(artifacts.FILES)[: steps - 1]
    for destination in artifacts.FILES:
        state = "file" if destination in written else "absent"
        assert observed["/" + destination]["state"] == state, destination
    assert observed["loaded_profiles"] == []
    status, rerun = host.run("judge", capsys)
    assert status == 1 and "already exists" in rerun["failure"]


@LINUX
def test_a_refused_profile_load_is_never_installed(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    judged(host, capsys)
    host.parser(1)
    assert host.install() == 1
    status, record = host.run("verify", capsys)
    assert status == 1 and "loaded in enforce mode" in record["failure"]
    for destination in (artifacts.DIRECTORY, *artifacts.FILES):
        assert record["observed"]["/" + destination]["state"] in {"directory", "file"}
    assert record["observed"]["loaded_profiles"] == []


def installed(host: Host, capsys: pytest.CaptureFixture[str]) -> None:
    judged(host, capsys)
    assert host.install() == 0


def replace(path: Path, data: bytes, mode: int) -> None:
    path.unlink()
    path.write_bytes(data)
    path.chmod(mode)


@LINUX
@pytest.mark.parametrize(
    ("drift", "fault"),
    [
        ("missing", DIRECTORY_PATH + " is not the reviewed content"),
        ("mode", PROBE_PATH + " mode is not 0o444"),
        ("one byte", PROBE_PATH + " is not the reviewed content"),
        ("crlf profile", PROFILE_PATH + " is not the reviewed content"),
        ("extra entry", DIRECTORY_PATH + " is not the reviewed content"),
        ("symlink", PROBE_PATH + " is not a file"),
        ("owner", PROBE_PATH + " is not root-owned"),
        ("ancestor", "/opt must be a real directory owned by root that"),
        ("profile ancestor", "/etc/apparmor.d must be a real directory owned by root that"),
    ],
)
def test_verify_refuses_drift_after_installation(
    drift: str, fault: str, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    installed(host, capsys)
    directory = host.root / artifacts.DIRECTORY
    probe_path = directory / "probe.py"
    profile = host.root / artifacts.PROFILE_DESTINATION
    if drift == "missing":
        (directory / "bwrap").unlink()
    elif drift == "mode":
        probe_path.chmod(0o644)
    elif drift == "one byte":
        replace(probe_path, PROBE_BYTES.replace(b"reviewed", b"Reviewed"), 0o444)
    elif drift == "crlf profile":
        replace(profile, PROFILE_BYTES.replace(b"\n", b"\r\n"), 0o444)
    elif drift == "extra entry":
        (directory / "extra").write_bytes(b"")
    elif drift == "symlink":
        copy = host.root / "probe-copy.py"
        copy.write_bytes(PROBE_BYTES)
        probe_path.unlink()
        probe_path.symlink_to(copy)
    elif drift == "owner":
        host.owners[probe_path] = os.getuid() + 1
    elif drift == "ancestor":
        (host.root / "opt").chmod(0o777)
    else:
        (host.root / "etc/apparmor.d").chmod(0o775)
    status, record = host.run("verify", capsys)
    assert status == 1 and record["installed"] is False, record
    assert fault in record["failure"], record["failure"]


@LINUX
def test_verify_recomputes_the_reviewed_bytes_from_the_named_commit(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    installed(host, capsys)
    place(host.work, {artifacts.PROBE: b"# a later reviewed probe\n"})
    later = commit(host.work, "probe changed on main")
    git(host.work, "push", "-q", str(host.workspace / artifacts.REPOSITORY), "main")
    feed(host.monkeypatch, host.kernel.read_text(encoding="utf-8"))
    status = artifacts.main(["verify", later, str(host.workspace)])
    record = json.loads(capsys.readouterr().out)
    assert status == 1 and record["first_parent"] is True
    assert "not the reviewed content" in record["failure"]
    status, again = host.run("verify", capsys)
    assert status == 0 and again["installed"] is True
