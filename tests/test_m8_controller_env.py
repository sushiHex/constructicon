"""The controller environment's stage, judge and verify (N4 host runtime, owner decision 2).

Design and runbook: docs/plans/handoffs/M8-N4-host-runtime.md ("Addendum: the
controller environment", "Controller runbook"). The lock closure, the wheel
tag rule, the wheel unpack rules, the package extraction and the command record
run on every platform. Custody, the writer, root's ``cp`` and ownership run on
Linux only, on a temporary host whose files read as root's through M8-D2's uid
view. One test runs only in the verify lane with ``M8_CONTROLLER_REQUIRED=1``:
it downloads the locked wheels and imports the controller under the host's
interpreter version, ``/usr/bin/python3.12 -I -S -B``.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
import warnings
import zipfile
from pathlib import Path

import pytest
from scripts.ci import m8_host_artifacts as artifacts

from tests.test_m8_host_artifacts import (
    bare,
    commit,
    feed,
    git,
    place,
    sha256,
    work_repository,
)

REPOSITORY = Path(__file__).parents[1]
DESIGN = REPOSITORY / "docs/plans/handoffs/M8-N4-host-runtime.md"
LINUX = pytest.mark.skipif(
    sys.platform != "linux",
    reason="custody, O_NOFOLLOW, the writer, coreutils and POSIX modes are Linux; Linux CI runs it",
)
CONTROLLER_PATH = "/" + artifacts.CONTROLLER
REAL_CLOSURE = {
    "annotated-types",
    "pydantic",
    "pydantic-core",
    "typing-extensions",
    "typing-inspection",
}


@pytest.fixture(autouse=True)
def stock_git(monkeypatch: pytest.MonkeyPatch) -> None:
    located = shutil.which("git")
    assert located is not None, "these fixtures need git"
    monkeypatch.setattr(artifacts, "GIT", located)


def checkout(path: str) -> bytes:
    return (REPOSITORY / path).read_bytes().replace(b"\r\n", b"\n")


# --- the lock closure (portable) ------------------------------------------------


def wheel_line(filename: str, digest: str = "0" * 64) -> str:
    return f'    {{ url = "https://files.example/{filename}", hash = "sha256:{digest}" }},\n'


def package(name: str, dependencies: str = "", wheels: str = "") -> str:
    text = f'\n[[package]]\nname = "{name}"\nversion = "1.0"\n'
    text += 'source = { registry = "https://pypi.org/simple" }\n'
    if dependencies:
        text += f"dependencies = [\n{dependencies}]\n"
    return text + f"wheels = [\n{wheels}]\n"


def fixture_lock(
    demo_dependency: str = '    { name = "leaf" },\n', demo_wheels: str | None = None
) -> bytes:
    """constructicon -> demo -> leaf; the extra and the dev group name other packages."""

    text = (
        'version = 1\nrevision = 3\nrequires-python = ">=3.11"\n\n'
        '[[package]]\nname = "constructicon"\nversion = "0.1.0"\n'
        'source = { editable = "." }\n'
        'dependencies = [\n    { name = "demo" },\n]\n\n'
        '[package.optional-dependencies]\nmcp = [\n    { name = "extra-only" },\n]\n\n'
        '[package.dev-dependencies]\ndev = [\n    { name = "dev-only" },\n]\n'
    )
    text += package(
        "demo",
        demo_dependency,
        wheel_line("demo-1.0-py3-none-any.whl") if demo_wheels is None else demo_wheels,
    )
    text += package("leaf", wheels=wheel_line("leaf-1.0-py3-none-any.whl"))
    text += package("extra-only", wheels=wheel_line("extra_only-1.0-py3-none-any.whl"))
    text += package("dev-only", wheels=wheel_line("dev_only-1.0-py3-none-any.whl"))
    return text.encode()


def test_the_closure_is_the_locked_runtime_dependencies_only() -> None:
    names = [p["name"] for p in artifacts.controller_closure(fixture_lock())]
    assert names == ["demo", "leaf"], "no extra, no dev group"
    real = {p["name"] for p in artifacts.controller_closure(checkout(artifacts.LOCK))}
    assert real == REAL_CLOSURE


@pytest.mark.parametrize(
    "dependency",
    [
        '    { name = "leaf", marker = "python_full_version < \'3.13\'" },\n',
        '    { name = "leaf", version = "1.0" },\n',
        '    { name = "leaf", source = { registry = "https://pypi.org/simple" } },\n',
        '    { name = "leaf", extra = ["x"] },\n',
    ],
)
def test_a_qualified_dependency_refuses(dependency: str) -> None:
    with pytest.raises(ValueError, match="is a qualified dependency"):
        artifacts.controller_closure(fixture_lock(dependency))


def test_a_name_locked_twice_refuses() -> None:
    lock = fixture_lock() + package("leaf", wheels=wheel_line("leaf-2.0-py3-none-any.whl")).encode()
    with pytest.raises(ValueError, match="is locked twice"):
        artifacts.controller_closure(lock)


@pytest.mark.parametrize("fault", ["not editable", "missing dependency"])
def test_the_closure_needs_its_editable_root_and_every_named_package(fault: str) -> None:
    if fault == "not editable":
        lock = fixture_lock().replace(b'source = { editable = "." }', b'source = { virtual = "." }')
        message = "has no editable constructicon"
    else:
        lock = fixture_lock('    { name = "absent" },\n')
        message = "absent is not in the lock"
    with pytest.raises(ValueError, match=message):
        artifacts.controller_closure(lock)


# --- the tag rule and the one-wheel selection (portable) ------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "x-1-py3-none-any.whl",
        "x-1-py312-none-any.whl",
        "x-1-cp312-none-any.whl",
        "x-1-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
        "x-1-cp38-abi3-manylinux_2_28_x86_64.whl",
        "x-1-cp312-abi3-manylinux_2_39_x86_64.whl",
        "x-1-cp312-none-manylinux1_x86_64.whl",
        "x-1-2-py3-none-any.whl",
    ],
)
def test_each_accepted_triple_is_compatible(filename: str) -> None:
    assert artifacts.wheel_triples(filename) & artifacts.accepted_triples(39)


@pytest.mark.parametrize(
    ("filename", "glibc"),
    [
        ("x-1-py3-cp312-any.whl", 39),
        ("x-1-py3-abi3-any.whl", 39),
        ("x-1-cp311-cp311-manylinux_2_17_x86_64.whl", 39),
        ("x-1-cp313-cp313-manylinux_2_17_x86_64.whl", 39),
        ("x-1-cp313-abi3-manylinux_2_17_x86_64.whl", 39),
        ("x-1-cp312-cp312-musllinux_1_1_x86_64.whl", 39),
        ("x-1-cp312-cp312-macosx_10_12_x86_64.whl", 39),
        ("x-1-cp312-cp312-manylinux_2_17_aarch64.whl", 39),
        ("x-1-cp312-cp312-manylinux_2_40_x86_64.whl", 39),
        ("x-1-cp312-cp312-manylinux2014_x86_64.whl", 16),
        ("x-1-pp310-pypy310_pp73-manylinux_2_17_x86_64.whl", 39),
    ],
)
def test_every_other_pairing_is_refused(filename: str, glibc: int) -> None:
    assert not artifacts.wheel_triples(filename) & artifacts.accepted_triples(glibc)


def test_the_locked_wheels_select_one_each_for_cpython_312() -> None:
    selected = {
        wheel["name"]: wheel["file"]
        for wheel in (
            artifacts.select_wheel(p, 39)
            for p in artifacts.controller_closure(checkout(artifacts.LOCK))
        )
    }
    assert selected["pydantic-core"] == (
        "pydantic_core-2.46.4-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
    )
    assert {name for name, file in selected.items() if file.endswith("-py3-none-any.whl")} == (
        REAL_CLOSURE - {"pydantic-core"}
    )


@pytest.mark.parametrize(
    ("wheels", "fault"),
    [
        (wheel_line("demo-1.0-py3-none-any.whl") + wheel_line("demo-1.0-py312-none-any.whl"),
         "has 2 compatible wheels"),
        (wheel_line("demo-1.0-cp311-cp311-manylinux_2_17_x86_64.whl"), "has 0 compatible wheels"),
        ('    { url = "https://files.example/demo-1.0-py3-none-any.whl", hash = "md5:00" },\n',
         "has no sha256"),
    ],
)  # fmt: skip
def test_the_selection_refuses_anything_but_one_pinned_wheel(wheels: str, fault: str) -> None:
    demo = artifacts.controller_closure(fixture_lock(demo_wheels=wheels))[0]
    with pytest.raises(ValueError, match=fault):
        artifacts.select_wheel(demo, 39)


def test_the_host_glibc_is_read_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(artifacts.os, "confstr", lambda name: "glibc 2.39", raising=False)
    assert artifacts.host_glibc() == 39
    monkeypatch.setattr(artifacts.os, "confstr", lambda name: "musl 1.2", raising=False)
    with pytest.raises(ValueError, match="unexpected libc"):
        artifacts.host_glibc()


def test_the_controller_needs_cpython_312(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(artifacts, "require_unprivileged", lambda: None)
    monkeypatch.setattr(artifacts, "require_custody", lambda workspace: None)
    monkeypatch.setattr(artifacts, "prove", lambda *arguments: {artifacts.LOCK: fixture_lock()})
    monkeypatch.setattr(artifacts, "host_glibc", lambda: 39)
    for found in (("cpython", (3, 11)), ("cpython", (3, 13)), ("pypy", (3, 12))):
        monkeypatch.setattr(artifacts, "interpreter", lambda found=found: found)
        with pytest.raises(ValueError, match=r"needs CPython 3.12"):
            artifacts.controller_selection("a" * 40, Path("/w"), {})
    monkeypatch.setattr(artifacts, "interpreter", lambda: ("cpython", (3, 12)))
    record: dict[str, object] = {}
    _, selected = artifacts.controller_selection("a" * 40, Path("/w"), record)
    assert [wheel["name"] for wheel in selected] == ["demo", "leaf"]
    assert record["interpreter"] == "cpython 3.12" and record["glibc_minor"] == 39


# --- the wheel unpack rules (portable) -------------------------------------------


def record_line(name: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{name},sha256={digest},{len(data)}"


def make_wheel(
    files: dict[str, bytes] | None = None,
    *,
    modes: dict[str, int] | None = None,
    record: str | None = None,
    extra: list[tuple[zipfile.ZipInfo, bytes]] = (),  # type: ignore[assignment]
) -> bytes:
    """A wheel with an exact RECORD unless ``record`` replaces it."""

    files = (
        {"demo/__init__.py": b"VALUE = 1\n", "demo/_native.so": b"\x7fELF"}
        if files is None
        else files
    )
    modes = {"demo/_native.so": 0o755} if modes is None else modes
    lines = [record_line(name, data) for name, data in files.items()]
    lines.append("demo-1.0.dist-info/RECORD,,")
    buffer = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # a duplicate name is written on purpose
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in files.items():
                info = zipfile.ZipInfo(name)
                info.external_attr = (stat.S_IFREG | modes.get(name, 0o644)) << 16
                archive.writestr(info, data)
            for info, data in extra:
                archive.writestr(info, data)
            archive.writestr(
                "demo-1.0.dist-info/RECORD", "\n".join(lines) + "\n" if record is None else record
            )
    return buffer.getvalue()


def entries_of(data: bytes) -> tuple[list[artifacts.Entry], dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return artifacts.wheel_entries(archive, "demo-1.0-py3-none-any.whl")


def test_a_pinned_wheel_unpacks_as_pip_target_lays_it_out() -> None:
    entries, digests = entries_of(make_wheel())
    table = {name: (kind, mode) for name, kind, mode, _ in entries}
    assert table == {
        "demo": ("directory", 0o555),
        "demo/__init__.py": ("file", 0o444),
        "demo/_native.so": ("file", 0o555),
        "demo-1.0.dist-info": ("directory", 0o555),
        "demo-1.0.dist-info/RECORD": ("file", 0o444),
    }
    assert digests["demo/__init__.py"] == sha256(b"VALUE = 1\n")
    sources = {name: source for name, kind, _, source in entries if kind == "file"}
    assert sources["demo/_native.so"] == ("zip", "demo-1.0-py3-none-any.whl", "demo/_native.so")


def test_a_member_without_type_bits_is_a_regular_file() -> None:
    wheel = make_wheel()
    with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
        names = archive.namelist()
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(wheel)) as source, zipfile.ZipFile(buffer, "w") as target:
        for info in source.infolist():
            info.external_attr = stat.S_IMODE(info.external_attr >> 16) << 16
            target.writestr(info, source.read(info))
    entries, _ = entries_of(buffer.getvalue())
    assert {name for name, kind, _, _ in entries if kind == "file"} == set(names)


def link(name: str) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info, b"__init__.py"


def member(name: str, data: bytes = b"x") -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name)
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info, data


@pytest.mark.parametrize(
    ("wheel", "fault"),
    [
        (lambda: make_wheel(extra=[link("demo/link.py")]), "is not a regular file"),
        (lambda: make_wheel(extra=[member("demo-1.0.data/scripts/tool")]), "has a .data directory"),
        (lambda: make_wheel(extra=[member("demo/__init__.py")]), "repeats demo/__init__.py"),
        (lambda: make_wheel(extra=[member("../escape.py")]), "is not a plain relative path"),
        (lambda: make_wheel(extra=[member("a/../../x.py")]), "is not a plain relative path"),
        (lambda: make_wheel(extra=[member("/etc/passwd")]), "is not a plain relative path"),
        (lambda: make_wheel(extra=[member("demo/" + "n" * 260 + ".py")]),
         "is not a plain relative path"),
        (lambda: make_wheel(extra=[member("demo/unlisted.py")]), "members are not its RECORD"),
        (lambda: make_wheel(record="demo/__init__.py,sha256=AAAA,1\ndemo-1.0.dist-info/RECORD,,\n"),
         "members are not its RECORD"),
        (lambda: make_wheel(record="demo-1.0.dist-info/RECORD,sha256=AAAA,1\n"),
         "does not list itself unhashed"),
    ],
)  # fmt: skip
def test_an_unsafe_or_unrecorded_wheel_refuses(wheel, fault: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match=re.escape(fault)):
        entries_of(wheel())


def test_a_wheel_without_a_record_refuses() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("demo/__init__.py", "")
    with pytest.raises(ValueError, match="has no single RECORD"):
        entries_of(buffer.getvalue())


@pytest.mark.parametrize("bound", ["members", "bytes", "zip64"])
def test_every_extraction_bound_binds(bound: str, monkeypatch: pytest.MonkeyPatch) -> None:
    wheel = make_wheel()
    entries_of(wheel)  # accepted at the production bounds
    if bound == "members":
        monkeypatch.setattr(artifacts, "WHEEL_MEMBERS", 2)
        fault = "has too many members"
    elif bound == "bytes":
        monkeypatch.setattr(artifacts, "WHEEL_BYTES", 8)
        fault = "unpacks too large"
    else:
        monkeypatch.setattr(artifacts, "needs_zip64", lambda info: info.filename.endswith(".so"))
        fault = "needs ZIP64"
    with pytest.raises(ValueError, match=fault):
        entries_of(wheel)


def test_zip64_is_needed_at_the_four_gibibyte_boundary() -> None:
    info = zipfile.ZipInfo("big")
    info.header_offset = 0  # set on every member of an archive read back
    assert not artifacts.needs_zip64(info)
    info.file_size = 0xFFFFFFFF
    assert artifacts.needs_zip64(info)


# --- the package from the commit, and the combined tree (portable) --------------


def package_repository(
    tmp_path: Path, files: dict[str, bytes], mode: str | None = None
) -> tuple[Path, str]:
    work, reviewed = work_repository(tmp_path, files)
    if mode is not None:
        # The index alone carries the mode: ``add -A`` would restage the file's.
        git(work, "update-index", "--chmod=+x", "src/constructicon/tool.py")
        git(work, "commit", "-q", "-m", "executable")
        reviewed = git(work, "rev-parse", "HEAD")
    return bare(work, tmp_path / "source.git"), reviewed


PACKAGE = {
    "src/constructicon/__init__.py": b"# package\n",
    "src/constructicon/sub/mod.py": b"VALUE = 2\n",
    "tests/not_shipped.py": b"# outside the package\n",
}


def test_the_package_is_every_regular_blob_under_src_at_the_commit(tmp_path: Path) -> None:
    source, reviewed = package_repository(tmp_path, PACKAGE)
    blobs = artifacts.package_blobs(reviewed, source)
    assert blobs == {
        "src/constructicon/__init__.py": b"# package\n",
        "src/constructicon/sub/mod.py": b"VALUE = 2\n",
    }


def test_a_package_blob_that_is_not_mode_100644_refuses(tmp_path: Path) -> None:
    source, reviewed = package_repository(
        tmp_path, {**PACKAGE, "src/constructicon/tool.py": b"# tool\n"}, mode="+x"
    )
    with pytest.raises(ValueError, match=r"tool.py is not a regular blob"):
        artifacts.package_blobs(reviewed, source)


def test_a_package_without_its_init_refuses(tmp_path: Path) -> None:
    source, reviewed = package_repository(tmp_path, {"src/constructicon/only.py": b""})
    with pytest.raises(ValueError, match="is not a package"):
        artifacts.package_blobs(reviewed, source)


def test_the_tree_joins_the_package_and_every_wheel_once() -> None:
    blobs = {"src/constructicon/__init__.py": b"# package\n"}
    entries, digests = artifacts.controller_entries(blobs, [entries_of(make_wheel())])
    names = [name for name, *_ in entries]
    assert names[0] == "." and "constructicon/__init__.py" in names and "demo/_native.so" in names
    assert digests["constructicon/__init__.py"] == sha256(b"# package\n")
    clash = make_wheel({"constructicon/__init__.py": b"# shadow\n"}, modes={})
    with pytest.raises(ValueError, match="would be installed twice"):
        artifacts.controller_entries(blobs, [entries_of(clash)])
    shape = make_wheel({"constructicon": b"a file where a package is\n"}, modes={})
    with pytest.raises(ValueError, match="would be installed twice"):
        artifacts.controller_entries(blobs, [entries_of(shape)])


# --- the command shape and the check (portable) ---------------------------------


def test_the_command_runs_a_module_as_python_m_would(tmp_path: Path) -> None:
    (tmp_path / "argvprobe.py").write_text(
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8"
    )
    command = artifacts.controller_command(tmp_path.as_posix())
    assert command[:5] == ("/usr/bin/python3", "-I", "-S", "-B", "-c")
    result = subprocess.run(
        [sys.executable, *command[1:], "argvprobe", "first", "--second"],
        capture_output=True, text=True, check=True, timeout=60,
    )  # fmt: skip
    assert json.loads(result.stdout) == ["first", "--second"]
    assert artifacts.controller_command()[-1].count(f'"{CONTROLLER_PATH}"') == 1


@LINUX
def test_the_check_refuses_a_module_loaded_from_outside_the_tree(tmp_path: Path) -> None:
    tree, outside = tmp_path / "tree", tmp_path / "outside"
    tree.mkdir()
    outside.mkdir()
    (outside / "outsider.py").write_text("", encoding="utf-8")
    (tree / "inside.py").write_text("", encoding="utf-8")
    (tree / "reacher.py").write_text(
        f"import sys\nsys.path.append({str(outside)!r})\nimport outsider\n", encoding="utf-8"
    )
    base = [sys.executable, "-I", "-S", "-B", "-c", artifacts.controller_check(str(tree))]
    passed = subprocess.run([*base, "inside"], capture_output=True, text=True, timeout=60)
    assert passed.returncode == 0 and json.loads(passed.stdout)["passed"] is True, passed
    failed = subprocess.run([*base, "reacher"], capture_output=True, text=True, timeout=60)
    assert failed.returncode == 1, failed
    assert json.loads(failed.stdout)["outside"] == [str(outside / "outsider.py")]


# --- the runbook (portable) ---------------------------------------------------------


def controller_runbook() -> str:
    text = DESIGN.read_text(encoding="utf-8")
    assert text.count("\n# Controller runbook (R15-R20)\n") == 1
    return text.split("\n# Controller runbook (R15-R20)\n", 1)[1]


def section(title: str) -> str:
    return controller_runbook().split(f"## {title}", 1)[1].split("\n## ", 1)[0]


def test_root_runs_one_stock_cp_and_nothing_else() -> None:
    text = controller_runbook()
    invoked = re.findall(r"\bsudo\s+([^\s`]+)", text)
    assert len(invoked) >= 3, "the sudo walk found too little, so it proved nothing"
    assert set(invoked) <= {"/usr/bin/cp", "/usr/bin/rm", "-u"}, set(invoked)
    install = (
        'sudo /usr/bin/cp -R -P --preserve=mode --no-target-directory "$W/staging/'
        f'{artifacts.CONTROLLER_STAGED}" {CONTROLLER_PATH}'
    )
    assert section("R18").count(install) == 1
    assert re.findall(r"sudo -u (\S+)", text) == ["m8-service"]


def test_the_runbook_check_is_the_scripts_check_over_the_proof_modules() -> None:
    r19 = section("R19")
    assert r19.count(f"-c '{artifacts.controller_check()}'") == 1
    assert "/usr/bin/python3 -I -S -B -c '" in r19
    assert " ".join(artifacts.PROOF_MODULES) in r19


def test_the_verify_lane_runs_the_controller_import_proof() -> None:
    workflow = (REPOSITORY / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    assert "runs-on: ubuntu-latest" in workflow
    step = (
        "      - run: M8_CONTROLLER_REQUIRED=1 uv run python -m pytest "
        "tests/test_m8_controller_env.py::test_the_staged_controller_imports_under_isolated_python"
        " -v -p no:cacheprovider\n"
    )
    assert workflow.count(step) == 1
    assert workflow.index("      - run: uv run verify\n") < workflow.index(step)


def test_the_runbook_proves_the_script_and_the_lock_with_stock_git() -> None:
    r17 = section("R17")
    listed = r17.split("ls-tree", 1)[1].split("&&", 1)[0]
    assert re.findall(r"[\w./-]+\.(?:py|lock)", listed) == list(artifacts.CONTROLLER_BLOBS)
    assert "controller-wheels" in r17 and "files.pythonhosted.org" in r17


# --- the command record (portable) ----------------------------------------------------

CONTROLLER_COMMANDS = {
    "controller-wheels": ("controller_wheels", "listed"),
    "stage-controller": ("stage_controller", "staged"),
    "judge-controller": ("judge_controller", "ready"),
    "verify-controller": ("verify_controller", "installed"),
}


@pytest.mark.parametrize("command", list(CONTROLLER_COMMANDS))
@pytest.mark.parametrize("failure", [False, True])
def test_each_controller_command_reports_its_own_verdict(
    command: str, failure: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    function, verdict = CONTROLLER_COMMANDS[command]

    def deciding(commit: str, root: Path, workspace: Path, listing: str, record: dict) -> None:
        if failure:
            raise ValueError("deliberately unproven")
        record[verdict] = True

    monkeypatch.setattr(artifacts, function, deciding)
    monkeypatch.setattr(artifacts, "observe_controller", lambda root, listing: {"controller": 1})
    monkeypatch.setattr(artifacts, "observe", lambda root, listing: {"qualification": 1})
    feed(monkeypatch, "")
    assert artifacts.main([command, "a" * 40, "/workspace"]) == int(failure)
    record = json.loads(capsys.readouterr().out)
    assert record[verdict] is (not failure)
    assert set(record) & {"ready", "installed", "staged", "listed"} == {verdict}
    assert (record.get("observed") == {"controller": 1}) == failure


# --- stage, judge, root's cp, verify on a temporary host (Linux) -----------------------

WHEEL_NAME = "demo-1.0-py3-none-any.whl"


class ControllerHost:
    """A temporary host: root-owned by the uid view, the operator's home kept real."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = tmp_path / "host"
        self.home = self.root / "home/operator"
        for directory in ("", "opt", "usr", "usr/bin", "home"):
            (self.root / directory).mkdir(mode=0o755, exist_ok=True)
            (self.root / directory).chmod(0o755)
        (self.root / artifacts.CP).write_bytes(b"#!/bin/sh\nexit 99\n")
        (self.root / artifacts.CP).chmod(0o755)
        self.home.mkdir(mode=0o750)
        self.home.chmod(0o750)
        self.workspace = self.home / "m8-controller"
        self.workspace.mkdir(mode=0o700)
        self.workspace.chmod(0o700)
        self.wheel = make_wheel()
        (self.workspace / artifacts.WHEELS).mkdir()
        (self.workspace / artifacts.WHEELS / WHEEL_NAME).write_bytes(self.wheel)
        lock = (
            'version = 1\nrevision = 3\n\n[[package]]\nname = "constructicon"\n'
            'version = "0.1.0"\nsource = { editable = "." }\n'
            'dependencies = [\n    { name = "demo" },\n]\n'
            + package("demo", wheels=wheel_line(WHEEL_NAME, sha256(self.wheel)))
        )
        files = {
            artifacts.SCRIPT: (REPOSITORY / artifacts.SCRIPT).read_bytes(),
            artifacts.LOCK: lock.encode(),
            "src/constructicon/__init__.py": b"# package\n",
            "src/constructicon/sub/mod.py": b"VALUE = 2\n",
        }
        self.work, self.commit = work_repository(tmp_path, files)
        bare(self.work, self.workspace / artifacts.REPOSITORY)
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
        monkeypatch.setattr(artifacts, "interpreter", lambda: ("cpython", (3, 12)))
        monkeypatch.setattr(artifacts, "host_glibc", lambda: 39)
        self.monkeypatch = monkeypatch

    def run(self, command: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
        feed(self.monkeypatch, "")
        status = artifacts.main([command, self.commit, str(self.workspace)])
        return status, json.loads(capsys.readouterr().out)

    def install(self) -> int:
        """R18's one root command, run as this account."""

        cp = shutil.which("cp")
        assert cp is not None
        staged = self.workspace / artifacts.STAGING / artifacts.CONTROLLER_STAGED
        argv = [cp, "-R", "-P", "--preserve=mode", "--no-target-directory", str(staged),
                str(self.root / artifacts.CONTROLLER)]  # fmt: skip
        return subprocess.run(argv, check=False, capture_output=True, timeout=30).returncode

    def installed(self) -> Path:
        return self.root / artifacts.CONTROLLER


@pytest.fixture
def controller_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ControllerHost:
    return ControllerHost(tmp_path, monkeypatch)


def judged(host: ControllerHost, capsys: pytest.CaptureFixture[str]) -> None:
    status, record = host.run("stage-controller", capsys)
    assert status == 0 and record["staged"] is True, record
    status, record = host.run("judge-controller", capsys)
    assert status == 0 and record["ready"] is True, record


@LINUX
def test_stage_judge_cp_then_verify_accepts(
    controller_host: ControllerHost, capsys: pytest.CaptureFixture[str]
) -> None:
    status, listed = controller_host.run("controller-wheels", capsys)
    assert status == 0 and listed["listed"] is True
    assert listed["wheels"] == [{
        "name": "demo", "file": WHEEL_NAME, "url": f"https://files.example/{WHEEL_NAME}",
        "sha256": sha256(controller_host.wheel),
    }]  # fmt: skip
    judged(controller_host, capsys)
    assert not os.path.lexists(controller_host.installed()), "the judge or stager installed"
    assert controller_host.install() == 0
    status, verified = controller_host.run("verify-controller", capsys)
    assert status == 0 and verified["installed"] is True, verified
    tree = controller_host.installed()
    assert sorted(os.listdir(tree)) == ["constructicon", "demo", "demo-1.0.dist-info"]
    assert (tree / "constructicon/sub/mod.py").read_bytes() == b"VALUE = 2\n"
    assert stat.S_IMODE((tree / "demo/_native.so").stat().st_mode) == 0o555
    assert stat.S_IMODE((tree / "demo/__init__.py").stat().st_mode) == 0o444
    assert stat.S_IMODE(tree.stat().st_mode) == 0o555


@LINUX
def test_a_valid_controller_verifies_with_staging_deleted(
    controller_host: ControllerHost, capsys: pytest.CaptureFixture[str]
) -> None:
    judged(controller_host, capsys)
    assert controller_host.install() == 0
    staging = controller_host.workspace / artifacts.STAGING
    subprocess.run(["chmod", "-R", "u+w", str(staging)], check=True)
    shutil.rmtree(staging)
    status, verified = controller_host.run("verify-controller", capsys)
    assert status == 0 and verified["installed"] is True, verified


def drift(tree: Path, fault: str) -> None:
    target = tree / "constructicon/sub/mod.py"
    if fault == "mode":
        target.chmod(0o555)
        return
    target.parent.chmod(0o755)
    target.chmod(0o644)
    if fault == "byte":
        target.write_bytes(b"VALUE = 3\n")
    elif fault == "extra":
        (target.parent / "extra.py").write_bytes(b"")
    else:
        target.unlink()
        target.parent.chmod(0o555)
        return
    target.chmod(0o444)
    target.parent.chmod(0o555)


@LINUX
@pytest.mark.parametrize("fault", ["byte", "mode", "extra", "missing"])
def test_staging_must_equal_the_recomputed_plan(
    fault: str, controller_host: ControllerHost, capsys: pytest.CaptureFixture[str]
) -> None:
    status, _ = controller_host.run("stage-controller", capsys)
    assert status == 0
    drift(controller_host.workspace / artifacts.STAGING / artifacts.CONTROLLER_STAGED, fault)
    status, record = controller_host.run("judge-controller", capsys)
    assert status == 1 and "the staged controller is not the reviewed plan" in record["failure"]
    assert [d["path"] for d in record["staged_differences"]] == [
        "constructicon/sub/extra.py" if fault == "extra" else "constructicon/sub/mod.py"
    ]


@LINUX
@pytest.mark.parametrize("fault", ["byte", "mode", "extra", "missing", "owner"])
def test_verify_refuses_a_drifted_installation(
    fault: str, controller_host: ControllerHost, capsys: pytest.CaptureFixture[str]
) -> None:
    judged(controller_host, capsys)
    assert controller_host.install() == 0
    tree = controller_host.installed()
    if fault == "owner":
        controller_host.owners[tree / "constructicon/sub/mod.py"] = os.getuid() + 1
    else:
        drift(tree, fault)
    status, record = controller_host.run("verify-controller", capsys)
    assert status == 1 and f"{CONTROLLER_PATH} is not the reviewed tree" in record["failure"]
    assert record["observed"][CONTROLLER_PATH]["different"] == 1


@LINUX
@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("wheel digest", "is not the locked wheel"),
        ("existing destination", "already exists"),
        ("cp", "must be a regular file owned by root that"),
        ("unsafe opt", "must be a real directory owned by root that"),
    ],
)
def test_each_controller_precondition_refuses_judgement(
    fault: str, message: str, controller_host: ControllerHost, capsys: pytest.CaptureFixture[str]
) -> None:
    status, _ = controller_host.run("stage-controller", capsys)
    assert status == 0
    root = controller_host.root
    if fault == "wheel digest":
        (controller_host.workspace / artifacts.WHEELS / WHEEL_NAME).write_bytes(
            controller_host.wheel + b"\0"
        )
    elif fault == "existing destination":
        controller_host.installed().mkdir(mode=0o755)
    elif fault == "cp":
        controller_host.owners[root / artifacts.CP] = os.getuid() + 1
    else:
        (root / "opt").chmod(0o775)
    status, record = controller_host.run("judge-controller", capsys)
    assert status == 1 and record["ready"] is False
    assert message in record["failure"], record["failure"]


@LINUX
@pytest.mark.parametrize("command", list(CONTROLLER_COMMANDS))
def test_every_controller_command_refuses_to_run_as_root(
    command: str,
    controller_host: ControllerHost,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(artifacts.os, "geteuid", lambda: 0)
    controller_host.owners[controller_host.workspace] = 0
    controller_host.owners[controller_host.home] = 0
    status, record = controller_host.run(command, capsys)
    assert status == 1 and "never runs as root" in record["failure"]


@LINUX
def test_verify_controller_with_nothing_installed_itemizes_absence(
    controller_host: ControllerHost, capsys: pytest.CaptureFixture[str]
) -> None:
    status, record = controller_host.run("verify-controller", capsys)
    assert status == 1 and record["observed"] == {CONTROLLER_PATH: {"state": "absent"}}


@LINUX
def test_the_package_follows_the_named_commit(
    controller_host: ControllerHost, capsys: pytest.CaptureFixture[str]
) -> None:
    judged(controller_host, capsys)
    assert controller_host.install() == 0
    place(controller_host.work, {"src/constructicon/sub/mod.py": b"VALUE = 4\n"})
    later = commit(controller_host.work, "package changed on main")
    subprocess.run(
        ["git", "push", "-q", str(controller_host.workspace / artifacts.REPOSITORY), "main"],
        cwd=controller_host.work, check=True, capture_output=True,
    )  # fmt: skip
    feed(controller_host.monkeypatch, "")
    status = artifacts.main(["verify-controller", later, str(controller_host.workspace)])
    record = json.loads(capsys.readouterr().out)
    assert status == 1 and "is not the reviewed tree" in record["failure"]


# --- the verify lane: the locked wheels under the host's interpreter version -----------


def test_the_staged_controller_imports_under_isolated_python(tmp_path: Path) -> None:
    """Every PROOF_MODULES import resolves inside a copy of the tree, under 3.12 -I -S -B."""

    if not os.environ.get("M8_CONTROLLER_REQUIRED"):
        pytest.skip("the controller proof runs only in its verify-lane step")
    python = Path("/usr/bin/python3.12")
    assert sys.platform == "linux" and python.exists(), "the proof needs the host interpreter"
    glibc = artifacts.host_glibc()
    selected = [
        artifacts.select_wheel(p, glibc)
        for p in artifacts.controller_closure(checkout(artifacts.LOCK))
    ]
    archives: dict[str, zipfile.ZipFile] = {}
    planned = []
    for wheel in selected:
        with urllib.request.urlopen(wheel["url"], timeout=120) as response:
            data = response.read()
        assert sha256(data) == wheel["sha256"], wheel
        archives[wheel["file"]] = zipfile.ZipFile(io.BytesIO(data))
        planned.append(artifacts.wheel_entries(archives[wheel["file"]], wheel["file"]))
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", artifacts.PACKAGE_SOURCE],
        cwd=REPOSITORY, capture_output=True, check=True,
    ).stdout.decode().split("\0")[:-1]  # fmt: skip
    blobs = {path: (REPOSITORY / path).read_bytes() for path in tracked}
    entries, _ = artifacts.controller_entries(blobs, planned)
    staged, copy = tmp_path / "staged", tmp_path / "controller"
    artifacts.materialize(entries, staged, artifacts.controller_contents(archives))
    subprocess.run(
        ["/usr/bin/cp", "-R", "-P", "--preserve=mode", "--no-target-directory", str(staged),
         str(copy)], check=True, timeout=120,
    )  # fmt: skip
    check = subprocess.run(
        [str(python), "-I", "-S", "-B", "-c", artifacts.controller_check(str(copy)),
         *artifacts.PROOF_MODULES],
        capture_output=True, text=True, timeout=120, env={"PATH": "/usr/bin:/bin"},
    )  # fmt: skip
    assert check.returncode == 0, check
    result = json.loads(check.stdout)
    assert result["passed"] is True and result["outside"] == [] and result["files"] > 50
    assert not list(copy.rglob("__pycache__")), "-B must keep the tree unwritten"
