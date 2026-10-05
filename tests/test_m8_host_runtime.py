"""The launch set's stage, judge and verify on the private host (N4 host runtime, #77).

Design and runbook: docs/plans/handoffs/M8-N4-host-runtime.md. Derived values,
the closure plan, the vendor archive plan, dpkg attribution, the stdlib
identity digest, the tree comparison, the assessment and the command record run
on every platform. Custody, the writer, root's stock sequence and ownership run
on Linux only, on a temporary host whose files read as root's through M8-D2's
uid view; a Windows skip is not evidence. Two tests run only in the
containment workflow's foundation lane, against CI's installed runtime.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path

import pytest
from scripts.ci import m8_host_artifacts as artifacts

from constructicon.substrate.executors import linux
from tests.test_m8_host_artifacts import (
    FAKE_BWRAP,
    KERNEL_LIST,
    bare,
    feed,
    sha256,
    work_repository,
)

REPOSITORY = Path(__file__).parents[1]
DESIGN = REPOSITORY / "docs/plans/handoffs/M8-N4-host-runtime.md"
LINUX = pytest.mark.skipif(
    sys.platform != "linux",
    reason="custody, O_NOFOLLOW, the writer, coreutils and POSIX modes are Linux; Linux CI runs it",
)
LAUNCH_PATH = "/" + artifacts.LAUNCH
PROFILE_PATH = "/" + artifacts.LAUNCH_PROFILE_DESTINATION
LAUNCH_LOADED = "constructicon-m8-launch (enforce)\nconstructicon-m8-workload (enforce)\n"


@pytest.fixture(autouse=True)
def stock_git(monkeypatch: pytest.MonkeyPatch) -> None:
    located = shutil.which("git")
    assert located is not None, "these fixtures need git"
    monkeypatch.setattr(artifacts, "GIT", located)


def checkout(path: str) -> bytes:
    """A blob's bytes from this checkout, line endings as git stores them."""

    return (REPOSITORY / path).read_bytes().replace(b"\r\n", b"\n")


# --- values derived from their reviewed homes (portable) --------------------


def test_every_derived_value_is_read_from_its_one_reviewed_home() -> None:
    from constructicon.substrate.executors._egress_bridge import BRIDGE_SCRIPT
    from constructicon.substrate.executors._supervisor import NAMESPACE_SCRIPT
    from constructicon.substrate.executors.linux import BWRAP_SHA256

    blobs = {path: checkout(path) for path in artifacts.LAUNCH_BLOBS}
    record: dict[str, object] = {}
    values = artifacts.derive(blobs, record)
    pin = artifacts.vendor_pin(blobs[artifacts.WORKFLOW])
    assert values == {
        "bwrap_sha256": BWRAP_SHA256,
        "supervisor_path": NAMESPACE_SCRIPT,
        "bridge_path": BRIDGE_SCRIPT,
        **pin,
    }
    assert record["derived"] == values
    # The workflow's step is exactly the template filled with its own pin.
    assert blobs[artifacts.WORKFLOW].count(artifacts.render_vendor_step(pin).encode()) == 1


# Two pins written out by hand, never derived: the parser's independent oracle.
PIN_A = {
    "codex_url": "https://github.com/openai/codex/releases/download/rust-v0.153.4/"
                 "codex-package-x86_64-unknown-linux-musl.tar.gz",
    "codex_sha256": "a" * 64,
    "catalog_url": "https://raw.githubusercontent.com/openai/codex/" + "3" * 40
                   + "/codex-rs/models-manager/models.json",
    "catalog_sha256": "c" * 64,
}  # fmt: skip
PIN_B = {
    **PIN_A,
    "codex_url": PIN_A["codex_url"].replace("rust-v0.153.4", "rust-v0.160.0"),
    "catalog_url": PIN_A["catalog_url"].replace("3" * 40, "a" * 40),
    "codex_sha256": "b" * 64,
}


def workflow_with(*steps: str) -> bytes:
    head, tail = "name: m8\njobs:\n  lane:\n    steps:\n", "      - name: Next\n"
    return (head + "".join(steps) + tail).encode()


@pytest.mark.parametrize(
    ("pin", "version", "commit"), [(PIN_A, "0.153.4", "3" * 40), (PIN_B, "0.160.0", "a" * 40)]
)
def test_a_rendered_pin_parses_back_to_itself(pin: dict, version: str, commit: str) -> None:
    parsed = artifacts.vendor_pin(workflow_with(artifacts.render_vendor_step(pin)))
    assert parsed == {**pin, "version": version, "catalog_commit": commit}


def test_the_pin_outside_its_acquisition_step_is_ignored() -> None:
    decoy = f"      - name: Notes\n        run: |\n          echo {PIN_B['codex_url']}\n"
    parsed = artifacts.vendor_pin(workflow_with(decoy, artifacts.render_vendor_step(PIN_A)))
    assert parsed["codex_url"] == PIN_A["codex_url"]


@pytest.mark.parametrize(
    "fault",
    ["another host", "query", "another output", "unchecked", "two steps", "no step", "zero padded"],
)
def test_a_pin_not_bound_to_its_acquisition_refuses(fault: str) -> None:
    step = artifacts.render_vendor_step(PIN_A)
    if fault == "another host":
        step = step.replace("https://github.com/", "https://example.com/")
    elif fault == "query":
        step = step.replace(".tar.gz\n", ".tar.gz?x=1\n", 1)
    elif fault == "another output":
        step = step.replace('--output "$RUNNER_TEMP/codex.tar.gz"', '--output "$RUNNER_TEMP/other"')
    elif fault == "unchecked":
        step = step.replace(" | sha256sum --check --strict", "", 1)
    elif fault == "zero padded":
        step = step.replace("rust-v0.153.4", "rust-v0.153.04")
    steps = {"two steps": (step, step), "no step": ()}.get(fault, (step,))
    with pytest.raises(ValueError, match="exactly one vendor acquisition step"):
        artifacts.vendor_pin(workflow_with(*steps))


@pytest.mark.parametrize(
    ("key", "value"),
    [("codex_sha256", "A" * 64), ("codex_url", "http://github.com/x"), ("catalog_url", "")],
)
def test_a_malformed_pin_is_never_rendered(key: str, value: str) -> None:
    with pytest.raises(ValueError, match=f"the pin's {key} is malformed"):
        artifacts.render_vendor_step({**PIN_A, key: value})


@pytest.mark.parametrize("key", list(artifacts.DERIVED))
@pytest.mark.parametrize("count", [0, 2])
def test_a_value_named_zero_or_two_times_refuses(key: str, count: int) -> None:
    blobs = {path: checkout(path) for path in artifacts.LAUNCH_BLOBS}
    path, pattern = artifacts.DERIVED[key]
    match = re.search(pattern, blobs[path], re.MULTILINE)
    assert match is not None
    line = match.group(0)
    blobs[path] = blobs[path].replace(line, b"" if count == 0 else line + b"\n" + line)
    with pytest.raises(ValueError, match=f"does not name exactly one {key}"):
        artifacts.derive(blobs, {})


# --- the stdlib identity law (portable) --------------------------------------


def test_the_stdlib_identity_digest_is_constructicons(tmp_path: Path) -> None:
    from constructicon.core.identity import digest
    from constructicon.substrate.executors.linux import runtime_digest, runtime_inventory

    root = tmp_path / "runtime"
    (root / "usr/lib").mkdir(parents=True)
    (root / "usr/lib/a.py").write_bytes(b"first\n")
    (root / "usr/b").write_bytes(b"\xffsecond")
    inventory = runtime_inventory(root, require_immutable=False)
    assert artifacts.identity_digest("linux-runtime-root", 1, inventory) == str(
        runtime_digest(root, require_immutable=False)
    )
    payload = {"é": [1, "ü", None, True], "a": {"b": 2.5}}
    assert artifacts.identity_digest("any-domain", 3, payload) == str(
        digest("any-domain", 3, payload)
    )
    document = json.loads(artifacts.runtime_json(inventory, "b" * 64, "p" * 64, "a" * 64))
    assert document["runtime_digest"] == str(runtime_digest(root, require_immutable=False))
    assert document["entries"] == [list(entry) for entry in inventory]


# --- the closure plan (portable) ----------------------------------------------

LIBRARIES = {
    "usr/lib/x86_64-linux-gnu/libc.so.6": b"\x7fELF libc\n",
    "usr/lib/x86_64-linux-gnu/libonly.so.1": b"\x7fELF only\n",
    "lib64/ld-linux-x86-64.so.2": b"#!/bin/sh\n",
}
LIBRARY_TREE = {
    "os.py": b"# os\n",
    "encodings/utf_8.py": b"# utf-8\n",
    "lib-dynload/_ssl.so": b"\x7fELF ssl\n",
    "__pycache__/os.cpython-312.pyc": b"cached",
    "test/only.so": b"\x7fELF test extension\n",
    "tests/case.py": b"# a test\n",
    "ensurepip/__init__.py": b"# ensurepip\n",
    "idlelib/idle.py": b"# idle\n",
}
TRACE = (
    "\tlinux-vdso.so.1 (0x00007ffd)\n"
    "\tlibc.so.6 => /usr/lib/x86_64-linux-gnu/libc.so.6 (0x00007f00)\n"
    "\t/lib64/ld-linux-x86-64.so.2 (0x00007f01)\n"
)
ONLY = "\tlibonly.so.1 => /usr/lib/x86_64-linux-gnu/libonly.so.1 (0x00007f02)\n"
SUPERVISOR = b'NAMESPACE_SCRIPT = "/usr/libexec/constructicon-supervisor.py"\n'
BRIDGE = b'BRIDGE_SCRIPT = "/usr/libexec/constructicon-egress-bridge.py"\n'


def closure_host(root: Path) -> None:
    for path, data in {
        artifacts.PYTHON: b"\x7fELF python\n",
        artifacts.GIT_BINARY: b"\x7fELF git\n",
        artifacts.TRUST_BUNDLE: b"-----BEGIN CERTIFICATE-----\nroot\n-----END CERTIFICATE-----\n",
        **LIBRARIES,
        **{f"{artifacts.LIBRARY}/{name}": data for name, data in LIBRARY_TREE.items()},
    }.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for path in (artifacts.PYTHON, artifacts.GIT_BINARY, "usr/lib/x86_64-linux-gnu/libc.so.6"):
        (root / path).chmod(0o755)


def trace(loader: Path, binary: Path) -> list[str]:
    """The loader's output shape, parsed by the script's own pattern."""

    text = TRACE + (ONLY if binary.name == "only.so" else "")
    return re.findall(r"(?:=>\s+)?(/[\w./+-]+)", text)


def plan(root: Path) -> list[artifacts.Entry]:
    return artifacts.runtime_plan(
        root,
        SUPERVISOR,
        BRIDGE,
        "/usr/libexec/constructicon-supervisor.py",
        "/usr/libexec/constructicon-egress-bridge.py",
    )


def test_the_closure_plan_is_the_ci_rule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "host"
    closure_host(root)
    monkeypatch.setattr(artifacts, "resolve", trace)
    entries = plan(root)
    names = [entry[0] for entry in entries]
    assert names[0] == "." and names == sorted(names, key=lambda n: Path(n).parts)
    table = {name: (kind, mode, source) for name, kind, mode, source in entries}
    library = artifacts.LIBRARY
    files = {
        artifacts.PYTHON,
        artifacts.GIT_BINARY,
        artifacts.TRUST_BUNDLE,
        *LIBRARIES,
        f"{library}/os.py",
        f"{library}/encodings/utf_8.py",
        f"{library}/lib-dynload/_ssl.so",
        "usr/libexec/constructicon-supervisor.py",
        "usr/libexec/constructicon-egress-bridge.py",
        artifacts.EGRESS_LEAF,
        artifacts.CATALOG_MOUNT,
    }
    assert {n for n, (kind, _, _) in table.items() if kind == "file"} == files
    assert {n for n, (kind, _, _) in table.items() if kind == "link"} == {"usr/bin/python3"}
    assert table["usr/bin/python3"] == ("link", 0o777, "python3.12")
    # The zone's one trust store is the host's bundle, read-only, at the path
    # the launcher names to the vendor (#77, S3).
    assert table[artifacts.TRUST_BUNDLE] == (
        "file", 0o444, ("host", artifacts.real_source(root, root / artifacts.TRUST_BUNDLE)),
    )
    assert linux.TRUST_BUNDLE == "/" + artifacts.TRUST_BUNDLE
    # Excluded names are never copied, but the library they alone need still is.
    for ignored in artifacts.IGNORED:
        assert not [n for n in names if f"/{ignored}/" in n + "/"], ignored
    assert "usr/lib/x86_64-linux-gnu/libonly.so.1" in table
    for name in artifacts.RUNTIME_DIRECTORIES:
        assert table[name] == ("directory", 0o555, None)
    assert {mode for kind, mode, _ in table.values() if kind == "directory"} == {0o555}
    assert table["usr/libexec/constructicon-supervisor.py"] == (
        "file",
        0o444,
        ("bytes", SUPERVISOR),
    )
    assert table[artifacts.EGRESS_LEAF] == ("file", 0o444, ("bytes", b""))
    # The vendor tree and catalog are bound, never copied: two empty mount points.
    assert table[artifacts.VENDOR_MOUNT] == ("directory", 0o555, None)
    assert table[artifacts.CATALOG_MOUNT] == ("file", 0o444, ("bytes", b""))
    assert ("/" + artifacts.VENDOR_MOUNT, "/" + artifacts.CATALOG_MOUNT) == (
        linux.VENDOR_MOUNT, linux.CATALOG_MOUNT,
    )
    assert not [name for name in names if name.startswith(artifacts.VENDOR_MOUNT + "/")]
    for name in (artifacts.PYTHON, "usr/lib/x86_64-linux-gnu/libonly.so.1"):
        kind, mode, source = table[name]
        assert kind == "file"
        executable = os.stat(root / name).st_mode & 0o111
        assert mode == (0o555 if executable else 0o444)
        assert source == ("host", Path(os.path.realpath(root / name)))


def test_the_loader_trace_refuses_an_unresolved_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def traced(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
        output = TRACE + "\tlibgone.so.1 => not found\n"
        return subprocess.CompletedProcess(argv, 0, output.encode(), b"")

    monkeypatch.setattr(artifacts, "run", traced)
    with pytest.raises(ValueError, match="unresolved dependencies"):
        artifacts.resolve(tmp_path / "loader", tmp_path / "binary")
    monkeypatch.setattr(
        artifacts, "run", lambda argv: subprocess.CompletedProcess(argv, 1, TRACE.encode(), b"")
    )
    with pytest.raises(ValueError, match="unresolved dependencies"):
        artifacts.resolve(tmp_path / "loader", tmp_path / "binary")
    monkeypatch.setattr(
        artifacts, "run", lambda argv: subprocess.CompletedProcess(argv, 0, TRACE.encode(), b"")
    )
    assert artifacts.resolve(tmp_path / "loader", tmp_path / "binary") == [
        "/usr/lib/x86_64-linux-gnu/libc.so.6",
        "/lib64/ld-linux-x86-64.so.2",
    ]


def test_a_supervisor_path_that_replaces_a_runtime_file_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "host"
    closure_host(root)
    monkeypatch.setattr(artifacts, "resolve", trace)
    with pytest.raises(ValueError, match="would replace a runtime file"):
        artifacts.runtime_plan(
            root, SUPERVISOR, BRIDGE, "/" + artifacts.PYTHON, "/usr/libexec/b.py"
        )


# --- the pinned vendor archive (portable) -------------------------------------


def member(name: str, kind: bytes = tarfile.REGTYPE, mode: int = 0o644, data: bytes = b"") -> tuple:
    return name, kind, mode, data


VENDOR = (
    member("bin", tarfile.DIRTYPE, 0o755),
    member("bin/codex", mode=0o775, data=b"\x7fELF codex\n"),
    member("codex-package.json", mode=0o664, data=b"{}\n"),
    member("codex-resources/zsh/bin/zsh", mode=0o755, data=b"\x7fELF zsh\n"),
)


def archive_bytes(members: tuple = VENDOR) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, kind, mode, data in members:
            info = tarfile.TarInfo(name)
            info.type, info.mode, info.size = kind, mode, len(data)
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                # A symlink target is relative to its directory, a hard link's to the root.
                info.size = 0
                info.linkname = "codex" if kind == tarfile.SYMTYPE else "bin/codex"
            archive.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    return buffer.getvalue()


def vendor(data: bytes) -> tuple[list[artifacts.Entry], dict[str, str]]:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        return artifacts.vendor_plan(archive)


def test_the_pinned_package_is_planned_as_ci_extracts_it() -> None:
    entries, digests = vendor(archive_bytes())
    assert [(name, kind, mode) for name, kind, mode, _ in entries] == [
        (".", "directory", 0o755),
        ("bin", "directory", 0o755),
        ("bin/codex", "file", 0o755),
        ("codex-package.json", "file", 0o644),
        # Implicit parents are created, as tar creates them.
        ("codex-resources", "directory", 0o755),
        ("codex-resources/zsh", "directory", 0o755),
        ("codex-resources/zsh/bin", "directory", 0o755),
        ("codex-resources/zsh/bin/zsh", "file", 0o755),
    ]
    assert digests == {
        "bin/codex": sha256(b"\x7fELF codex\n"),
        "codex-package.json": sha256(b"{}\n"),
        "codex-resources/zsh/bin/zsh": sha256(b"\x7fELF zsh\n"),
    }


@pytest.mark.parametrize(
    ("bad", "fault"),
    [
        (member("bin/link", tarfile.SYMTYPE), "is not a file or directory"),
        (member("bin/hard", tarfile.LNKTYPE), "is not a file or directory"),
        (member("bin/fifo", tarfile.FIFOTYPE), "is not a file or directory"),
        (member("bin/device", tarfile.CHRTYPE), "is not a file or directory"),
        (member("/etc/passwd"), "is not a plain relative path"),
        (member("../outside"), "is not a plain relative path"),
        (member("bin/../../outside"), "is not a plain relative path"),
        (member("bin/codex"), "is duplicated"),
        (member("bin/setuid", mode=0o4755), "carries a special mode bit"),
        (member("sticky", tarfile.DIRTYPE, 0o1777), "carries a special mode bit"),
    ],
)
def test_an_unsafe_archive_member_refuses(bad: tuple, fault: str) -> None:
    with pytest.raises(ValueError, match=re.escape(fault)):
        vendor(archive_bytes((*VENDOR, bad)))


# --- dpkg attribution (portable) ----------------------------------------------


def dpkg_host(root: Path) -> list[Path]:
    files = {
        "usr/lib/x86_64-linux-gnu/libc.so.6": b"libc",
        "usr/lib/python3.12/os.py": b"os",
        "etc/python3.12/sitecustomize.py": b"site",
        "usr/lib/python3.12/lib2to3/Grammar.pickle": b"generated",
    }
    for path, data in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)
    md5 = {path: hashlib.md5(data).hexdigest() for path, data in files.items()}
    database = root / artifacts.DPKG
    (database / "info").mkdir(parents=True)
    tables = {
        "status": (
            "Package: libc6\nStatus: install ok installed\nArchitecture: amd64\n"
            "Version: 2.39-0ubuntu8\n\n"
            "Package: libpython3.12-stdlib\nStatus: install ok installed\nVersion: 3.12.3-1\n"
            "Conffiles:\n /etc/python3.12/sitecustomize.py "
            + md5["etc/python3.12/sitecustomize.py"]
            + "\n\nPackage: removed\nStatus: deinstall ok config-files\nVersion: 1\n"
        ),
        # dpkg knows libc by its pre-merge spelling.
        "info/libc6.list": "/lib/x86_64-linux-gnu/libc.so.6\n",
        "info/libc6.md5sums": (
            md5["usr/lib/x86_64-linux-gnu/libc.so.6"] + "  lib/x86_64-linux-gnu/libc.so.6\n"
        ),
        "info/libpython3.12-stdlib.list": (
            "/usr/lib/python3.12/os.py\n/etc/python3.12/sitecustomize.py\n"
        ),
        "info/libpython3.12-stdlib.md5sums": (
            md5["usr/lib/python3.12/os.py"] + "  usr/lib/python3.12/os.py\n"
        ),
    }
    for name, text in tables.items():
        (database / name).write_bytes(text.encode())
    return [root / path for path in files]


def test_attribution_names_each_package_and_lists_the_unattributed(tmp_path: Path) -> None:
    sources = dpkg_host(tmp_path)
    facts = artifacts.attribution(tmp_path, sources, Path.read_bytes)
    assert facts == {
        "packages": {"libc6": "2.39-0ubuntu8", "libpython3.12-stdlib": "3.12.3-1"},
        "unattributed": ["/usr/lib/python3.12/lib2to3/Grammar.pickle"],
        "unattributed_count": 1,
    }


@pytest.mark.parametrize(
    "path",
    [
        "usr/lib/x86_64-linux-gnu/libc.so.6",
        "usr/lib/python3.12/os.py",
        "etc/python3.12/sitecustomize.py",
    ],
)
def test_a_file_that_differs_from_its_packages_digest_refuses(tmp_path: Path, path: str) -> None:
    sources = dpkg_host(tmp_path)
    (tmp_path / path).write_bytes(b"locally modified")
    with pytest.raises(ValueError, match="dpkg digest"):
        artifacts.attribution(tmp_path, sources, Path.read_bytes)


def test_the_unattributed_list_is_bounded(tmp_path: Path) -> None:
    sources = dpkg_host(tmp_path)
    extra = []
    for index in range(artifacts.UNATTRIBUTED_LIMIT + 1):
        path = tmp_path / f"usr/lib/python3.12/generated/{index:03}.pickle"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        extra.append(path)
    facts = artifacts.attribution(tmp_path, [*sources, *extra], Path.read_bytes)
    assert len(facts["unattributed"]) == artifacts.UNATTRIBUTED_LIMIT
    assert facts["unattributed_count"] == artifacts.UNATTRIBUTED_LIMIT + 2


# --- comparison, account and assessment (portable) ----------------------------

EXPECTED: artifacts.Inventory = [(".", 0o555, "directory"), ("a", 0o444, "sha256:" + "0" * 64)]


@pytest.mark.parametrize(
    ("observed", "path"),
    [
        ([(".", 0o555, "directory", 0), ("a", 0o644, "sha256:" + "0" * 64, 0)], "a"),
        ([(".", 0o555, "directory", 0), ("a", 0o444, "sha256:" + "1" * 64, 0)], "a"),
        ([(".", 0o555, "directory", 0)], "a"),
        (
            [
                (".", 0o555, "directory", 0),
                ("a", 0o444, "sha256:" + "0" * 64, 0),
                ("b", 0o444, "directory", 0),
            ],
            "b",
        ),
        ([(".", 0o555, "directory", 0), ("a", 0o444, "sha256:" + "0" * 64, 7)], "a"),
    ],
)
def test_every_difference_in_a_tree_is_reported(observed: list, path: str) -> None:
    assert [d["path"] for d in artifacts.compare(observed, EXPECTED, 0)] == [path]
    reviewed = [(".", 0o555, "directory", 0), ("a", 0o444, "sha256:" + "0" * 64, 0)]
    assert artifacts.compare(reviewed, EXPECTED, 0) == []


@pytest.mark.parametrize(
    ("account", "accepted"),
    [
        ((1001, 1001, "m8-service", []), True),
        ((0, 1001, "m8-service", []), False),
        ((1001, 0, "m8-service", []), False),
        ((1001, 1001, "users", []), False),
        ((1001, 1001, "m8-service", ["sudo"]), False),
    ],
)
def test_the_service_account_is_unprivileged_and_alone(
    account: tuple, accepted: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(artifacts, "lookup_service", lambda: account)
    record: dict[str, object] = {}
    if accepted:
        assert artifacts.service_account(record) == account[1]
    else:
        with pytest.raises(ValueError, match="must be unprivileged"):
            artifacts.service_account(record)
    assert record["service"]["uid"] == account[0]  # type: ignore[index]


VALUES = {"bwrap_sha256": "b" * 64, "catalog_sha256": "c" * 64}
BLOBS = {artifacts.LAUNCH_PROFILE: b"profile\n"}
PLAN = {"runtime.json": b"{}\n"}
GID = 1001


def installed_launch() -> dict[str, object]:
    def file(mode: int, digest: str) -> dict[str, object]:
        return {"state": "file", "uid": 0, "gid": 0, "mode": oct(mode), "sha256": digest}

    tree = {"state": "tree", "uid": 0, "gid": 0, "mode": "0o555", "different": 0, "differences": []}
    return {
        LAUNCH_PATH: {
            "state": "directory",
            "uid": 0,
            "gid": 0,
            "mode": "0o755",
            "entries": sorted(artifacts.LAUNCH_ENTRIES),
            "count": 6,
        },
        LAUNCH_PATH + "/bwrap": file(0o555, "b" * 64),
        PROFILE_PATH: file(0o444, sha256(b"profile\n")),
        LAUNCH_PATH + "/runtime": tree,
        LAUNCH_PATH + "/runtime.json": file(0o444, sha256(b"{}\n")),
        LAUNCH_PATH + "/native-codex": dict(tree, mode="0o755"),
        LAUNCH_PATH + "/codex-models.json": file(0o444, "c" * 64),
        LAUNCH_PATH + "/operator-stores": {
            "state": "directory", "uid": 0, "gid": GID, "mode": "0o750",
        },
        "loaded_profiles": LAUNCH_LOADED.splitlines(),
    }


def test_the_operator_store_is_observed_without_listing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On the host the operator is outside ``m8-service``, so the ``0750`` store
    cannot be listed (#77, R13 at ``376a3fd``). Its contents are never part of the
    installation, so verify must not read them."""

    store = tmp_path / artifacts.LAUNCH / "operator-stores"
    store.mkdir(parents=True)
    listdir = os.listdir

    def operator_listdir(path: str | os.PathLike[str]) -> list[str]:
        if Path(path) == store:
            raise PermissionError(13, "Permission denied", str(path))
        return listdir(path)

    monkeypatch.setattr(os, "listdir", operator_listdir)
    observed = artifacts.observe_launch(tmp_path, "")
    assert observed[LAUNCH_PATH + "/operator-stores"]["state"] == "directory"
    assert observed[LAUNCH_PATH]["entries"] == ["operator-stores"]


def table() -> dict[str, tuple[str, int, object]]:
    return artifacts.launch_table(PLAN, BLOBS, VALUES, GID)


def test_the_reviewed_launch_set_is_assessed_installed() -> None:
    artifacts.assess_launch(installed_launch(), table())


@pytest.mark.parametrize(
    ("path", "field", "value", "fault"),
    [
        (LAUNCH_PATH, "entries", [*sorted(artifacts.LAUNCH_ENTRIES), "extra"], "reviewed content"),
        (LAUNCH_PATH, "mode", "0o775", "mode is not"),
        (LAUNCH_PATH + "/bwrap", "sha256", "0" * 64, "reviewed content"),
        (LAUNCH_PATH + "/bwrap", "uid", 1000, "is not root-owned"),
        (PROFILE_PATH, "state", "symlink", "is not a file"),
        (LAUNCH_PATH + "/runtime", "different", 1, "is not the reviewed tree"),
        (LAUNCH_PATH + "/runtime", "state", "directory", "is not the reviewed tree"),
        (LAUNCH_PATH + "/runtime.json", "sha256", "0" * 64, "reviewed content"),
        (LAUNCH_PATH + "/native-codex", "different", 3, "is not the reviewed tree"),
        (LAUNCH_PATH + "/codex-models.json", "mode", "0o644", "mode is not"),
        (LAUNCH_PATH + "/operator-stores", "gid", 0, "group's"),
        (LAUNCH_PATH + "/operator-stores", "mode", "0o755", "mode is not"),
        (LAUNCH_PATH + "/operator-stores", "uid", 1001, "is not root-owned"),
    ],
)
def test_each_launch_fact_is_required(path: str, field: str, value: object, fault: str) -> None:
    observed = installed_launch()
    observed[path] = {**observed[path], field: value}  # type: ignore[dict-item]
    with pytest.raises(ValueError, match=fault):
        artifacts.assess_launch(observed, table())


@pytest.mark.parametrize("missing", ["constructicon-m8-launch", "constructicon-m8-workload"])
@pytest.mark.parametrize("mode", ["complain", None])
def test_both_launch_profiles_must_be_loaded_in_enforce_mode(
    missing: str, mode: str | None
) -> None:
    observed = installed_launch()
    profiles = [line for line in LAUNCH_LOADED.splitlines() if not line.startswith(missing)]
    observed["loaded_profiles"] = profiles + ([f"{missing} ({mode})"] if mode else [])
    with pytest.raises(ValueError, match="both launch profiles"):
        artifacts.assess_launch(observed, table())


def test_a_loaded_launch_profile_past_the_records_bound_still_refuses() -> None:
    others = "".join(f"constructicon-m8-other{n} (enforce)\n" for n in range(20))
    listing = KERNEL_LIST + others + "constructicon-m8-workload (enforce)\n"
    assert len(artifacts.loaded_profiles(listing)) == 16
    assert artifacts.loaded_among(listing, artifacts.LAUNCH_PROFILE_NAMES) == [
        "constructicon-m8-workload (enforce)"
    ]


def test_mounts_are_read_unescaped_and_only_at_or_beneath_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = tmp_path / "mountinfo"
    table.write_text(
        "22 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
        "30 22 0:5 / /var/lib rw - tmpfs tmpfs rw\n"
        "31 22 0:6 / /var/lib/constructicon-m8-launch2 rw - tmpfs tmpfs rw\n"
        "32 22 0:7 / /var/lib/constructicon-m8-launch/a\\040b rw - tmpfs tmpfs rw\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(artifacts, "MOUNTINFO", table)
    launch = Path(LAUNCH_PATH)
    assert artifacts.mounts_beneath(launch) == [f"{LAUNCH_PATH}/a b"]
    table.write_text(f"40 22 0:8 / {LAUNCH_PATH} rw - tmpfs tmpfs rw\n", encoding="utf-8")
    assert artifacts.mounts_beneath(launch) == [LAUNCH_PATH]


# --- the command record (portable) --------------------------------------------

LAUNCH_COMMANDS = {
    "stage-launch": ("stage_launch", "staged"),
    "judge-launch": ("judge_launch", "ready"),
    "verify-launch": ("verify_launch", "installed"),
    "vendor-inputs": ("vendor_inputs", "listed"),
    "judge-retire": ("judge_retire", "ready"),
    "verify-retired": ("verify_retired", "retired"),
}


@pytest.mark.parametrize("command", list(LAUNCH_COMMANDS))
@pytest.mark.parametrize("failure", [False, True])
def test_each_launch_command_reports_its_own_verdict(
    command: str, failure: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    function, verdict = LAUNCH_COMMANDS[command]

    def deciding(commit: str, root: Path, workspace: Path, listing: str, record: dict) -> None:
        if failure:
            raise ValueError("deliberately unproven")
        record[verdict] = True

    monkeypatch.setattr(artifacts, function, deciding)
    monkeypatch.setattr(artifacts, "observe_launch", lambda root, listing: {"launch": listing})
    monkeypatch.setattr(artifacts, "observe", lambda root, listing: {"qualification": listing})
    feed(monkeypatch, KERNEL_LIST)
    assert artifacts.main([command, "a" * 40, "/workspace"]) == int(failure)
    record = json.loads(capsys.readouterr().out)
    assert record[verdict] is (not failure)
    assert set(record) & {"ready", "installed", "staged", "retired", "listed"} == {verdict}
    assert (record.get("observed") == {"launch": KERNEL_LIST}) == failure


def test_a_verifiers_own_observation_survives_its_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing(commit: str, root: Path, workspace: Path, listing: str, record: dict) -> None:
        record["observed"] = {"with": "tree differences"}
        raise ValueError("drift")

    monkeypatch.setattr(artifacts, "verify_launch", failing)
    monkeypatch.setattr(artifacts, "observe_launch", lambda root, listing: {"fresh": True})
    feed(monkeypatch, KERNEL_LIST)
    assert artifacts.main(["verify-launch", "a" * 40, "/workspace"]) == 1
    assert json.loads(capsys.readouterr().out)["observed"] == {"with": "tree differences"}


# --- the repository side: layout, runbook and CI (portable) -------------------


def test_the_launch_layout_is_the_layout_ci_provisions() -> None:
    workflow = (REPOSITORY / ".github/workflows/m8-containment.yml").read_text(encoding="utf-8")
    for line in (
        f"sudo install -d -m {artifacts.LAUNCH_MODE:04o} {LAUNCH_PATH}\n",
        f"sudo install -m 0555 /usr/bin/bwrap {LAUNCH_PATH}/bwrap\n",
        f"sudo install -m 0444 {artifacts.LAUNCH_PROFILE} {PROFILE_PATH}\n",
        f"sudo apparmor_parser --add --skip-cache {PROFILE_PATH}\n",
        f"scripts/ci/build_m8_runtime.py {LAUNCH_PATH}/runtime ",
        f'sudo install -m 0444 "$RUNNER_TEMP/m8-runtime.json" {LAUNCH_PATH}/runtime.json\n',
        f"sudo install -d -m 0755 {LAUNCH_PATH}/native-codex\n",
        f'sudo install -m 0444 "$RUNNER_TEMP/codex-models.json" {LAUNCH_PATH}/codex-models.json\n',
    ):
        assert workflow.count(line) == 1, line
    store = (REPOSITORY / "scripts/ci/build_m8_store_fixture.py").read_text(encoding="utf-8")
    assert f'RUNNER_ROOT = Path("{LAUNCH_PATH}")' in store
    assert 'STORE_ROOT = RUNNER_ROOT / "operator-stores"' in store
    assert f"STORE_ROOT.mkdir(mode={artifacts.STORE_MODE:#o})" in store
    profile = checkout(artifacts.LAUNCH_PROFILE).decode()
    assert f"profile constructicon-m8-launch {LAUNCH_PATH}/bwrap " in profile
    assert "profile constructicon-m8-workload " in profile
    launcher = checkout(artifacts.LAUNCHER).decode()
    assert "constructicon-m8-launch//&constructicon-m8-workload (enforce)" in launcher
    assert tuple(artifacts.LAUNCH_PROFILE_NAMES) == (
        "constructicon-m8-launch",
        "constructicon-m8-workload",
    )


def test_ci_builds_the_runtime_from_the_shared_plan() -> None:
    builder = (REPOSITORY / "scripts/ci/build_m8_runtime.py").read_text(encoding="utf-8")
    assert "from m8_host_artifacts import contents, materialize, runtime_plan\n" in builder
    assert "materialize(plan, destination, contents())" in builder
    assert "ldd" not in builder and "copytree" not in builder and "shutil" not in builder


def test_the_foundation_lane_runs_the_parity_tests_as_the_service_user() -> None:
    workflow = (REPOSITORY / ".github/workflows/m8-containment.yml").read_text(encoding="utf-8")
    for test in (
        "tests/test_m8_host_runtime.py::test_the_host_writer_reproduces_the_ci_runtime",
        "tests/test_m8_host_runtime.py::test_the_loader_list_resolves_as_ldd_does",
    ):
        assert workflow.count(test) == 1, test
    step = workflow.split("name: Prove containment as the non-sudo service user", 1)[1]
    step = step.split("\n      - name:", 1)[0]
    assert "tests/test_m8_host_runtime.py::test_the_host_writer" in step
    assert "M8_CONTAINMENT_REQUIRED=1" in step and "sudo -u m8-service" in step


OWNER = ("-o", "root", "-g", "root")
STORE_OWNER = ("-o", "root", "-g", "m8-service")
CP_FLAGS = ("-R", "-P", "--preserve=mode", "--no-target-directory")


def launch_sequence() -> list[list[str]]:
    """R13's root commands; the runbook must show exactly these, in this order."""

    install, cp, parser = "/" + artifacts.INSTALL, "/" + artifacts.CP, "/" + artifacts.PARSER
    return [
        [install, "-d", *OWNER, "-m", f"{artifacts.LAUNCH_MODE:04o}", LAUNCH_PATH],
        [install, *OWNER, "-m", "0555", "/" + artifacts.BWRAP_SOURCE, LAUNCH_PATH + "/bwrap"],
        [install, *OWNER, "-m", "0444", '"$W/staging/constructicon-m8-launch"', PROFILE_PATH],
        [cp, *CP_FLAGS, '"$W/staging/runtime"', LAUNCH_PATH + "/runtime"],
        [install, *OWNER, "-m", "0444", '"$W/staging/runtime.json"', LAUNCH_PATH + "/runtime.json"],
        [cp, *CP_FLAGS, '"$W/staging/native-codex"', LAUNCH_PATH + "/native-codex"],
        [
            install,
            *OWNER,
            "-m",
            "0444",
            '"$W/staging/codex-models.json"',
            LAUNCH_PATH + "/codex-models.json",
        ],
        [
            install,
            "-d",
            *STORE_OWNER,
            "-m",
            f"{artifacts.STORE_MODE:04o}",
            LAUNCH_PATH + "/operator-stores",
        ],
        [parser, "--add", "--skip-cache", PROFILE_PATH],
    ]


def retire_sequence() -> list[list[str]]:
    """The replacement runbook's root removals, in order: never ``L``, never the store."""

    rm, parser = "/" + artifacts.RM, "/" + artifacts.PARSER
    launch = [f"{LAUNCH_PATH}/{name}" for name in artifacts.DISPOSABLE]
    return [
        [parser, "-R", PROFILE_PATH],
        [rm, "-f", PROFILE_PATH],
        [rm, "-rf", "--one-file-system", *(p for p in launch if p.endswith(("runtime", "codex")))],
        [rm, "-f", *(p for p in launch if not p.endswith(("runtime", "codex")))],
    ]


def replacement_sequence() -> list[list[str]]:
    """R13 into the kept ``L``: every command but the two that create a directory."""

    return [command for command in launch_sequence() if "-d" not in command]


def runbook() -> str:
    text = DESIGN.read_text(encoding="utf-8")
    assert text.count("\n# Operator runbook (R8-R14)\n") == 1
    launch = text.split("\n# Operator runbook (R8-R14)\n", 1)[1]
    return launch.split("\n# Controller runbook (R15-R20)\n", 1)[0]


def test_the_runbook_root_sequence_is_the_launch_inventory() -> None:
    text = runbook()
    r13 = text.split("## R13", 1)[1].split("\n## ", 1)[0]
    positions = []
    for command in launch_sequence():
        line = "sudo " + " ".join(command)
        assert r13.count(line) == 1, line
        positions.append(r13.index(line))
    assert positions == sorted(positions), "the runbook installs in the inventory's order"
    destinations = {command[-1] for command in launch_sequence()} - {PROFILE_PATH, LAUNCH_PATH}
    assert destinations == {f"{LAUNCH_PATH}/{name}" for name in artifacts.LAUNCH_ENTRIES}
    staged = {
        c[-2].removeprefix('"$W/staging/').strip('"') for c in launch_sequence() if "$W" in c[-2]
    }
    assert staged == set(artifacts.STAGED)


def test_root_runs_only_named_stock_tools_in_the_launch_runbook() -> None:
    code = runbook()
    invoked = re.findall(r"\bsudo\s+([^\s`]+)", code)
    assert len(invoked) >= 15, "the sudo walk found too little, so it proved nothing"
    stock = {
        "/usr/bin/install",
        "/usr/sbin/apparmor_parser",
        "/usr/bin/cat",
        "/usr/bin/cp",
        "/usr/bin/rm",
        "/usr/sbin/useradd",
        "/usr/bin/passwd",
        "-l",
    }
    assert set(invoked) <= stock, set(invoked) - stock
    assert {"/" + tool for tool in artifacts.LAUNCH_ROOT_TOOLS} == {
        "/usr/bin/install",
        "/usr/bin/cat",
        "/usr/bin/cp",
        "/usr/sbin/apparmor_parser",
    }
    assert {"/" + tool for tool in artifacts.LAUNCH_ROOT_TOOLS} <= set(invoked)


REPLACEMENT = REPOSITORY / "docs/plans/handoffs/M8-N4-launch-replacement.md"


@pytest.mark.parametrize(
    ("step", "sequence"), [("LR4", retire_sequence), ("LR6", replacement_sequence)]
)
def test_the_replacement_runbook_runs_exactly_the_tested_root_commands(
    step: str, sequence: Callable[[], list[list[str]]]
) -> None:
    text = REPLACEMENT.read_text(encoding="utf-8")
    section = text.split(f"## {step}.", 1)[1].split("\n## ", 1)[0]
    block = section.split("```bash\n", 1)[1].split("```", 1)[0]
    invoked = [
        re.sub(r"\s*(;;|\\)?$", "", line.split("sudo ", 1)[1])
        for line in block.splitlines()
        if "sudo " in line and "apparmor/profiles" not in line
    ]
    assert invoked == [" ".join(command) for command in sequence()]


def bash_block(section: str) -> list[str]:
    return section.split("```bash\n", 1)[1].split("```", 1)[0].splitlines()


def test_the_r11_variant_is_r11_with_its_pins_read_from_the_commit() -> None:
    """Only the stated differences: no literal T and M, the listing, the digest check."""

    r11 = bash_block(runbook().split("## R11", 1)[1].split("\n## ", 1)[0])
    text = REPLACEMENT.read_text(encoding="utf-8")
    variant = bash_block(text.split("**The R11 variant.**", 1)[1])
    listing = [
        '  && /usr/bin/python3 -I "$W/m8_host_artifacts.py" vendor-inputs "$C" "$W" < /dev/null'
        ' > "$W/vendor.json" \\',
        "  && V=(/usr/bin/python3 -I -c 'import json, sys; print(json.load(sys.stdin)"
        '["vendor"][sys.argv[1]][sys.argv[2]])\') \\',
        '  && T=$("${V[@]}" codex url < "$W/vendor.json")'
        ' && TS=$("${V[@]}" codex sha256 < "$W/vendor.json") \\',
        '  && M=$("${V[@]}" catalog url < "$W/vendor.json")'
        ' && MS=$("${V[@]}" catalog sha256 < "$W/vendor.json") \\',
    ]
    check = (
        "  && printf '%s  %s\\n%s  %s\\n' \"$TS\" \"$W/codex.tar.gz\" \"$MS\""
        ' "$W/codex-models.json" | sha256sum --check --strict \\'
    )
    expected: list[str] = []
    for line in r11:
        if line.startswith(("T=", "M=")):
            continue
        if line.startswith("C="):
            line = "C=<40-hex merge commit named in LR0>"
        if line.startswith('  && sha256sum "$W/m8_host_artifacts.py"'):
            expected.append(check)
        expected.append(line)
        if line.startswith('  && "${G[@]}" cat-file blob'):
            expected.extend(listing)
    expected.append('cat "$W/vendor.json"')
    assert variant == expected


def test_the_replacement_runbook_never_removes_the_launch_root_or_its_store() -> None:
    code = "".join(re.findall(r"```bash\n(.*?)```", REPLACEMENT.read_text(encoding="utf-8"), re.S))
    removals = [line for line in code.splitlines() if "/usr/bin/rm " in line]
    assert removals, "the walk found no removal, so it proved nothing"
    for line in removals:
        targets = line.split("/usr/bin/rm ", 1)[1].split()
        assert LAUNCH_PATH not in targets and f"{LAUNCH_PATH}/{artifacts.STORE}" not in targets
    assert "install -d" not in code
    assert set(re.findall(r"\bsudo\s+(/[^\s`]+)", code)) == {
        "/usr/bin/cat", "/usr/sbin/apparmor_parser", "/usr/bin/rm", "/usr/bin/install",
        "/usr/bin/cp", "/usr/bin/passwd",
    }


def test_the_runbook_proves_every_launch_blob_with_stock_git() -> None:
    r11 = runbook().split("## R11", 1)[1].split("\n## ", 1)[0]
    listed = r11.split("ls-tree", 1)[1].split("&&", 1)[0]
    assert re.findall(r"[\w./-]+\.(?:py|apparmor|yml)", listed) == list(artifacts.LAUNCH_BLOBS)


# --- stage, judge, root's stock tools, verify on a temporary host (Linux) -----

# Every run leaves one line in TRACED, so a test can show the loader never ran.
FAKE_LOADER = (
    "#!/bin/sh\n"
    "printf '%s\\n' \"$2\" >> 'TRACED'\n"
    "printf '\\tlinux-vdso.so.1 (0x0)\\n'\n"
    "printf '\\tlibc.so.6 => /usr/lib/x86_64-linux-gnu/libc.so.6 (0x0)\\n'\n"
    "printf '\\t/lib64/ld-linux-x86-64.so.2 (0x0)\\n'\n"
    'case "$2" in *only.so) printf \'\\tlibonly.so.1 => '
    "/usr/lib/x86_64-linux-gnu/libonly.so.1 (0x0)\\n';; esac\n"
)
CATALOG_BYTES = b'{"models": []}\n'


def launch_blobs(archive: bytes, catalog: bytes = CATALOG_BYTES) -> dict[str, bytes]:
    return {
        artifacts.SCRIPT: (REPOSITORY / artifacts.SCRIPT).read_bytes(),
        artifacts.LAUNCH_PROFILE: b"profile constructicon-m8-launch /var/lib/x/bwrap {}\n",
        artifacts.SUPERVISOR: b"# supervisor\n" + SUPERVISOR,
        artifacts.BRIDGE: b"# bridge\n" + BRIDGE,
        artifacts.LAUNCHER: f'BWRAP_SHA256 = "{sha256(FAKE_BWRAP)}"\n'.encode(),
        artifacts.WORKFLOW: workflow_with(artifacts.render_vendor_step(
            {**PIN_A, "codex_sha256": sha256(archive), "catalog_sha256": sha256(catalog)}
        )),
    }


class LaunchHost:
    """A temporary host: root-owned by the uid view, the operator's home kept real."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = tmp_path / "host"
        self.home = self.root / "home/operator"
        self.kernel = tmp_path / "kernel-profiles"
        self.kernel.write_text(KERNEL_LIST, encoding="utf-8")
        self.log = tmp_path / "parser.log"
        self.traced = tmp_path / "loader.log"
        for directory in (
            "",
            "etc",
            "etc/apparmor.d",
            "etc/apparmor.d/abi",
            "usr",
            "usr/bin",
            "usr/sbin",
            "var",
            "var/lib",
            "home",
        ):
            (self.root / directory).mkdir(mode=0o755, exist_ok=True)
            (self.root / directory).chmod(0o755)
        closure_host(self.root)
        (self.root / artifacts.LOADER).write_text(
            FAKE_LOADER.replace("TRACED", str(self.traced)), encoding="utf-8"
        )
        (self.root / artifacts.LOADER).chmod(0o755)
        (self.root / artifacts.LOADER_CACHE).write_bytes(b"ld.so cache")
        (self.root / artifacts.ABI).write_bytes(b"abi 4.0\n")
        (self.root / artifacts.BWRAP_SOURCE).write_bytes(FAKE_BWRAP)
        (self.root / artifacts.BWRAP_SOURCE).chmod(0o755)
        for tool in (artifacts.INSTALL, artifacts.CAT, artifacts.CP, artifacts.RM):
            (self.root / tool).write_bytes(b"#!/bin/sh\nexit 99\n")
            (self.root / tool).chmod(0o755)
        self.parser(0)
        dpkg_host(self.root)
        for directory in (
            self.root / "usr",
            self.root / "var",
            self.root / "etc",
            self.root / "lib64",
        ):
            for path in [directory, *directory.rglob("*")]:
                if path.is_dir():
                    path.chmod(0o755)
        self.home.mkdir(mode=0o750)
        self.home.chmod(0o750)
        self.workspace = self.home / "m8-launch"
        self.workspace.mkdir(mode=0o700)
        self.workspace.chmod(0o700)
        self.archive = archive_bytes()
        (self.workspace / artifacts.TARBALL).write_bytes(self.archive)
        (self.workspace / artifacts.CATALOG).write_bytes(CATALOG_BYTES)
        self.work, self.commit = work_repository(tmp_path, launch_blobs(self.archive))
        bare(self.work, self.workspace / artifacts.REPOSITORY)
        self.root_uid = os.getuid() + 4000
        self.owners: dict[Path, int] = {}
        self.gids: dict[Path, int] = {}
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
            fields = list(info[:10])
            fields[4] = info.st_uid if uid is None else uid
            fields[5] = self.gids.get(target, info.st_gid)
            return os.stat_result(fields)

        monkeypatch.setattr(artifacts.os, "lstat", observing)
        self.mountinfo = tmp_path / "mountinfo"
        self.mountinfo.write_text("22 1 8:1 / / rw - ext4 /dev/sda1 rw\n", encoding="utf-8")
        monkeypatch.setattr(artifacts, "MOUNTINFO", self.mountinfo)
        monkeypatch.setattr(artifacts, "ROOT", self.root)
        monkeypatch.setattr(artifacts, "ROOT_UID", self.root_uid)
        monkeypatch.setattr(
            artifacts, "lookup_service", lambda: (4242, os.getgid(), "m8-service", [])
        )
        self.monkeypatch = monkeypatch

    def parser(self, status: int) -> None:
        parser = self.root / artifacts.PARSER
        parser.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$*\" >> '{self.log}'\n"
            f"test {status} = 0 || exit {status}\n"
            'if test "$1" = -R; then\n'
            "  grep -v -e '^constructicon-m8-launch ' -e '^constructicon-m8-workload '"
            f" '{self.kernel}' > '{self.kernel}.left'\n"
            f"  exec mv '{self.kernel}.left' '{self.kernel}'\n"
            "fi\n"
            "printf 'constructicon-m8-launch (enforce)\\nconstructicon-m8-workload (enforce)\\n'"
            f" >> '{self.kernel}'\n",
            encoding="utf-8",
        )
        parser.chmod(0o755)

    def mount(self, path: Path) -> None:
        """Something mounted at ``path``, as the kernel escapes it in mountinfo."""

        point = str(path).replace(" ", "\\040")
        with self.mountinfo.open("a", encoding="utf-8") as table:
            table.write(f"99 22 0:5 / {point} rw - tmpfs tmpfs rw\n")

    def run(self, command: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
        feed(self.monkeypatch, self.kernel.read_text(encoding="utf-8"))
        status = artifacts.main([command, self.commit, str(self.workspace)])
        return status, json.loads(capsys.readouterr().out)

    def install(self, steps: int | None = None, sequence: list[list[str]] | None = None) -> int:
        """A root sequence (R13 by default), chained like ``&&``, minus owner and group options."""

        tools = {
            "/" + artifacts.INSTALL: shutil.which("install"),
            "/" + artifacts.CP: shutil.which("cp"),
            "/" + artifacts.RM: shutil.which("rm"),
            "/" + artifacts.PARSER: str(self.root / artifacts.PARSER),
        }
        for command in (launch_sequence() if sequence is None else sequence)[:steps]:
            tool, *arguments = command
            for owner in (OWNER, STORE_OWNER):
                for start in range(len(arguments) - 3):
                    if tuple(arguments[start : start + 4]) == owner:
                        del arguments[start : start + 4]
                        break
            argv = [str(tools[tool])]
            for argument in arguments:
                if argument.startswith('"$W/'):
                    argv.append(str(self.workspace) + argument[3:-1])
                elif argument.startswith("/"):
                    argv.append(str(self.root) + argument)
                    target = Path(argv[-1])
                    if tool == "/" + artifacts.RM and target.is_dir() and not target.is_symlink():
                        # Root's removal ignores the read-only modes the operator's rm obeys.
                        subprocess.run(["chmod", "-R", "u+w", argv[-1]], check=True)
                else:
                    argv.append(argument)
            status = subprocess.run(argv, check=False, capture_output=True, timeout=30).returncode
            if status:
                return status
        return 0

    def staged(self) -> Path:
        return self.workspace / artifacts.STAGING

    def launch(self) -> Path:
        return self.root / artifacts.LAUNCH


@pytest.fixture
def launch_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LaunchHost:
    return LaunchHost(tmp_path, monkeypatch)


def staged(host: LaunchHost, capsys: pytest.CaptureFixture[str]) -> dict:
    status, record = host.run("stage-launch", capsys)
    assert status == 0 and record["staged"] is True, record
    return record


def judged(host: LaunchHost, capsys: pytest.CaptureFixture[str]) -> dict:
    staged(host, capsys)
    status, record = host.run("judge-launch", capsys)
    assert status == 0 and record["ready"] is True, record
    return record


def installed(host: LaunchHost, capsys: pytest.CaptureFixture[str]) -> dict:
    judged(host, capsys)
    assert host.install() == 0
    status, record = host.run("verify-launch", capsys)
    assert status == 0 and record["installed"] is True, record
    assert record["replacement"] is False
    return record


def unlocked(path: Path) -> None:
    """The operator's own staged tree is read-only; make one path writable to alter it."""

    path.parent.chmod(0o755)
    if path.exists() and not path.is_symlink():
        path.chmod(0o644 if path.is_file() else 0o755)


@LINUX
def test_stage_judge_root_sequence_then_verify_accepts(
    launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    record = staged(launch_host, capsys)
    assert sorted(os.listdir(launch_host.staged())) == list(artifacts.STAGED)
    assert record["packages"] == {"libc6": "2.39-0ubuntu8", "libpython3.12-stdlib": "3.12.3-1"}
    assert f"/{artifacts.LOADER}" in record["unattributed"]
    assert not os.path.lexists(launch_host.launch()), "the stager wrote outside staging"
    status, judgement = launch_host.run("judge-launch", capsys)
    assert status == 0 and judgement["ready"] is True, judgement
    assert judgement["first_parent"] is True and judgement["script_matches_commit"] is True
    assert judgement["derived"]["bwrap_sha256"] == sha256(FAKE_BWRAP)
    assert not os.path.lexists(launch_host.launch()) and not launch_host.log.exists()
    assert launch_host.install() == 0
    status, verified = launch_host.run("verify-launch", capsys)
    assert status == 0 and verified["installed"] is True, verified
    assert verified["replacement"] is False and judgement["replacement"] is False
    observed = verified["observed"]
    assert observed[LAUNCH_PATH + "/runtime"]["different"] == 0
    assert observed[LAUNCH_PATH + "/native-codex"]["different"] == 0
    assert sorted(os.listdir(launch_host.launch())) == sorted(artifacts.LAUNCH_ENTRIES)
    document = json.loads((launch_host.launch() / "runtime.json").read_text(encoding="utf-8"))
    assert document["runtime_digest"] == verified["runtime_digest"]
    assert (launch_host.launch() / "runtime/usr/bin/python3").readlink() == Path("python3.12")
    assert (launch_host.launch() / "runtime/usr/lib/x86_64-linux-gnu/libonly.so.1").exists()
    assert (launch_host.launch() / "native-codex/bin/codex").read_bytes() == b"\x7fELF codex\n"


@LINUX
def test_vendor_inputs_lists_the_pinned_package_and_catalog_and_writes_nothing(
    launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    before = sorted(path.name for path in launch_host.workspace.iterdir())
    status, record = launch_host.run("vendor-inputs", capsys)
    assert status == 0 and record["listed"] is True, record
    assert record["vendor"] == {
        "codex": {"url": PIN_A["codex_url"], "sha256": sha256(launch_host.archive)},
        "catalog": {"url": PIN_A["catalog_url"], "sha256": sha256(CATALOG_BYTES)},
    }
    assert sorted(path.name for path in launch_host.workspace.iterdir()) == before


@LINUX
def test_the_launch_sequence_modes_do_not_depend_on_the_umask(
    launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    judged(launch_host, capsys)
    previous = os.umask(0o277)
    try:
        assert launch_host.install() == 0
    finally:
        os.umask(previous)
    status, verified = launch_host.run("verify-launch", capsys)
    assert status == 0 and verified["installed"] is True, verified


@LINUX
def test_a_valid_installation_verifies_with_staging_deleted(
    launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    """The accepting control: verify recomputes, so staging's absence changes nothing."""

    judged(launch_host, capsys)
    assert launch_host.install() == 0
    subprocess.run(["chmod", "-R", "u+w", str(launch_host.staged())], check=True)
    shutil.rmtree(launch_host.staged())
    status, verified = launch_host.run("verify-launch", capsys)
    assert status == 0 and verified["installed"] is True, verified


@LINUX
def test_staging_modified_after_judgement_is_caught_by_verify(
    launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    judged(launch_host, capsys)
    target = launch_host.staged() / "runtime" / artifacts.LIBRARY / "os.py"
    unlocked(target)
    target.write_bytes(b"# edited after judgement\n")
    # Restore the staged modes, which root's cp preserves, so only the content differs.
    target.chmod(0o444)
    target.parent.chmod(0o555)
    assert launch_host.install() == 0
    status, record = launch_host.run("verify-launch", capsys)
    assert status == 1 and "runtime is not the reviewed tree" in record["failure"]
    differences = record["observed"][LAUNCH_PATH + "/runtime"]["differences"]
    assert [d["path"] for d in differences] == [f"{artifacts.LIBRARY}/os.py"]
    (difference,) = differences
    assert difference["observed"][0] == difference["expected"][0] == 0o444
    assert difference["observed"][1] != difference["expected"][1]


@LINUX
def test_the_stager_refuses_an_existing_staging(
    launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    launch_host.staged().mkdir(mode=0o700)
    status, record = launch_host.run("stage-launch", capsys)
    assert status == 1 and "FileExistsError" in record["failure"]


@LINUX
@pytest.mark.parametrize("command", list(LAUNCH_COMMANDS))
def test_every_launch_command_refuses_to_run_as_root(
    command: str,
    launch_host: LaunchHost,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(artifacts.os, "geteuid", lambda: 0)
    launch_host.owners[launch_host.workspace] = 0
    launch_host.owners[launch_host.home] = 0
    status, record = launch_host.run(command, capsys)
    assert status == 1 and "never runs as root" in record["failure"]


def alter_staging(host: LaunchHost, fault: str) -> None:
    runtime = host.staged() / "runtime"
    library = runtime / artifacts.LIBRARY
    if fault == "runtime byte":
        unlocked(library / "os.py")
        (library / "os.py").write_bytes(b"# Os\n")
    elif fault == "runtime mode":
        (library / "os.py").chmod(0o555)
    elif fault == "runtime extra":
        unlocked(library / "os.py")
        (library / "extra.py").write_bytes(b"")
    elif fault == "runtime missing":
        unlocked(library / "os.py")
        (library / "os.py").unlink()
    elif fault == "runtime fifo":
        unlocked(library / "os.py")
        (library / "os.py").unlink()
        os.mkfifo(library / "os.py")
    elif fault == "retargeted link":
        link = runtime / "usr/bin/python3"
        unlocked(link)
        link.unlink()
        link.symlink_to("git")
    elif fault == "vendor member":
        target = host.staged() / "native-codex/bin/codex"
        target.chmod(0o755)
        target.write_bytes(b"\x7fELF other\n")
    else:
        name = {"runtime.json": "runtime.json", "profile": "constructicon-m8-launch"}[fault]
        host.staged().chmod(0o700)
        (host.staged() / name).chmod(0o644)
        (host.staged() / name).write_bytes(b"{}\n")


@LINUX
@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("runtime byte", "the staged runtime is not the reviewed plan"),
        ("runtime mode", "the staged runtime is not the reviewed plan"),
        ("runtime extra", "the staged runtime is not the reviewed plan"),
        ("runtime missing", "the staged runtime is not the reviewed plan"),
        ("runtime fifo", "is not a file, directory or link"),
        ("retargeted link", "the staged runtime is not the reviewed plan"),
        ("vendor member", "the staged native-codex is not the reviewed plan"),
        ("runtime.json", "the staged runtime.json is not the reviewed file"),
        ("profile", "the staged constructicon-m8-launch is not the reviewed file"),
    ],
)
def test_staging_must_equal_the_recomputed_plan(
    fault: str, message: str, launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    staged(launch_host, capsys)
    alter_staging(launch_host, fault)
    status, record = launch_host.run("judge-launch", capsys)
    assert status == 1 and record["ready"] is False
    assert message in record["failure"], record["failure"]
    assert not os.path.lexists(launch_host.launch())


@LINUX
@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("tarball", "codex.tar.gz is not the pinned package"),
        ("catalog", "codex-models.json is not the pinned catalog"),
        ("account", "must be unprivileged"),
        ("host source owner", "must be a regular file owned by root that"),
        ("host source parent", "must be a real directory owned by root that"),
        ("loader", "must be a regular file owned by root that"),
        ("loader cache", "must be a regular file owned by root that"),
        ("cp", "must be a regular file owned by root that"),
        ("cp missing", "FileNotFoundError"),
        ("bubblewrap", "not the pinned build"),
        ("launch root exists", "already exists"),
        ("profile exists", "already exists"),
        ("unsafe ancestor", "must be a real directory owned by root that"),
        ("launch loaded", "a launch profile is already loaded"),
        ("workload loaded", "a launch profile is already loaded"),
        ("dpkg digest", "dpkg digest"),
    ],
)
def test_each_launch_precondition_refuses_judgement(
    fault: str,
    message: str,
    launch_host: LaunchHost,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged(launch_host, capsys)
    assert launch_host.traced.exists(), "staging traced nothing, so the log proves nothing"
    launch_host.traced.unlink()
    root = launch_host.root
    if fault == "tarball":
        (launch_host.workspace / artifacts.TARBALL).write_bytes(launch_host.archive + b"\0")
    elif fault == "catalog":
        (launch_host.workspace / artifacts.CATALOG).write_bytes(CATALOG_BYTES + b" ")
    elif fault == "account":
        monkeypatch.setattr(
            artifacts, "lookup_service", lambda: (4242, 4242, "m8-service", ["sudo"])
        )
    elif fault == "host source owner":
        launch_host.owners[root / artifacts.PYTHON] = os.getuid()
    elif fault == "host source parent":
        (root / "usr/lib/x86_64-linux-gnu").chmod(0o775)
    elif fault == "loader":
        (root / artifacts.LOADER).chmod(0o775)
    elif fault == "loader cache":
        (root / artifacts.LOADER_CACHE).chmod(0o666)
    elif fault == "cp":
        launch_host.owners[root / artifacts.CP] = os.getuid() + 1
    elif fault == "cp missing":
        (root / artifacts.CP).unlink()
    elif fault == "bubblewrap":
        (root / artifacts.BWRAP_SOURCE).write_bytes(FAKE_BWRAP + b"drift")
    elif fault == "launch root exists":
        launch_host.launch().mkdir(mode=0o755)
    elif fault == "profile exists":
        (root / artifacts.LAUNCH_PROFILE_DESTINATION).symlink_to(root / "nowhere")
    elif fault == "unsafe ancestor":
        (root / "var/lib").chmod(0o775)
    elif fault == "launch loaded":
        launch_host.kernel.write_text(KERNEL_LIST + "constructicon-m8-launch (complain)\n")
    elif fault == "workload loaded":
        launch_host.kernel.write_text(KERNEL_LIST + "constructicon-m8-workload (enforce)\n")
    else:
        (root / "usr/lib/x86_64-linux-gnu/libc.so.6").write_bytes(b"patched libc")
    status, record = launch_host.run("judge-launch", capsys)
    assert status == 1 and record["ready"] is False
    assert message in record["failure"], record["failure"]
    assert not launch_host.log.exists()
    if fault in ("loader", "loader cache"):
        # Custody is proved before the loader runs, never after.
        assert not launch_host.traced.exists(), "the judge ran an unproven loader"


@LINUX
@pytest.mark.parametrize("steps", range(1, 9))
def test_a_partial_launch_installation_is_never_installed_and_blocks_a_rerun(
    steps: int, launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    judged(launch_host, capsys)
    assert launch_host.install(steps) == 0
    status, record = launch_host.run("verify-launch", capsys)
    assert status == 1 and record["installed"] is False
    assert record["observed"][LAUNCH_PATH]["state"] == "directory"
    status, rerun = launch_host.run("judge-launch", capsys)
    assert status == 1 and "already exists" in rerun["failure"]


@LINUX
def test_a_refused_launch_profile_load_is_never_installed(
    launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    judged(launch_host, capsys)
    launch_host.parser(1)
    assert launch_host.install() == 1
    status, record = launch_host.run("verify-launch", capsys)
    assert status == 1 and "both launch profiles" in record["failure"]


@LINUX
@pytest.mark.parametrize(
    ("drift", "fault"),
    [
        ("runtime byte", LAUNCH_PATH + "/runtime is not the reviewed tree"),
        ("runtime mode", LAUNCH_PATH + "/runtime is not the reviewed tree"),
        ("runtime extra", LAUNCH_PATH + "/runtime is not the reviewed tree"),
        ("runtime owner", LAUNCH_PATH + "/runtime is not the reviewed tree"),
        ("retargeted link", LAUNCH_PATH + "/runtime is not the reviewed tree"),
        ("runtime.json", LAUNCH_PATH + "/runtime.json is not the reviewed content"),
        ("vendor member", LAUNCH_PATH + "/native-codex is not the reviewed tree"),
        ("store mode", LAUNCH_PATH + "/operator-stores mode is not 0o750"),
        ("store group", LAUNCH_PATH + "/operator-stores is not the m8-service group's"),
        ("extra entry", LAUNCH_PATH + " is not the reviewed content"),
        ("profile unloaded", "both launch profiles"),
        ("host package update", LAUNCH_PATH + "/runtime is not the reviewed tree"),
        ("ancestor", "must be a real directory owned by root that"),
    ],
)
def test_verify_launch_refuses_drift_after_installation(
    drift: str, fault: str, launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    installed(launch_host, capsys)
    launch = launch_host.launch()
    runtime = launch / "runtime"
    os_py = runtime / artifacts.LIBRARY / "os.py"
    if drift == "runtime byte":
        unlocked(os_py)
        os_py.write_bytes(b"# Os\n")
        os_py.chmod(0o444)
    elif drift == "runtime mode":
        os_py.chmod(0o555)
    elif drift == "runtime extra":
        unlocked(os_py)
        (os_py.parent / "extra.py").write_bytes(b"")
        os_py.parent.chmod(0o555)
    elif drift == "runtime owner":
        launch_host.owners[os_py] = os.getuid() + 1
    elif drift == "retargeted link":
        link = runtime / "usr/bin/python3"
        unlocked(link)
        link.unlink()
        link.symlink_to("git")
        link.parent.chmod(0o555)
    elif drift == "runtime.json":
        (launch / "runtime.json").chmod(0o644)
        (launch / "runtime.json").write_bytes(b"{}\n")
        (launch / "runtime.json").chmod(0o444)
    elif drift == "vendor member":
        (launch / "native-codex/bin/codex").write_bytes(b"\x7fELF other\n")
    elif drift == "store mode":
        (launch / "operator-stores").chmod(0o755)
    elif drift == "store group":
        launch_host.gids[launch / "operator-stores"] = os.getgid() + 1
    elif drift == "extra entry":
        (launch / "extra").write_bytes(b"")
    elif drift == "profile unloaded":
        launch_host.kernel.write_text(KERNEL_LIST, encoding="utf-8")
    elif drift == "host package update":
        # The installed closure is intact; the host it was copied from moved on.
        # (utf_8.py is unattributed, so only the recomputed tree can notice.)
        (launch_host.root / artifacts.LIBRARY / "encodings/utf_8.py").write_bytes(b"# new\n")
    else:
        (launch_host.root / "var/lib").chmod(0o777)
    status, record = launch_host.run("verify-launch", capsys)
    assert status == 1 and record["installed"] is False, record
    assert fault in record["failure"], record["failure"]


# --- replacement after the first login: the store is kept (Linux) -------------

SENTINEL = b"credential-free sentinel\n"


def with_binding(host: LaunchHost, capsys: pytest.CaptureFixture[str]) -> Path:
    """An installed launch set whose store holds a sentinel binding."""

    installed(host, capsys)
    sentinel = host.launch() / artifacts.STORE / "binding"
    sentinel.write_bytes(SENTINEL)
    return sentinel


def retired(host: LaunchHost, capsys: pytest.CaptureFixture[str], steps: int | None = None) -> dict:
    """``judge-retire``, its record saved as the runbook saves it, then root's removals."""

    status, judgement = host.run("judge-retire", capsys)
    assert status == 0 and judgement["ready"] is True, judgement
    (host.workspace / artifacts.RETIREMENT).write_text(json.dumps(judgement), encoding="utf-8")
    assert host.install(steps, retire_sequence()) == 0
    return judgement


def restaged(host: LaunchHost, capsys: pytest.CaptureFixture[str]) -> dict:
    subprocess.run(["chmod", "-R", "u+w", str(host.staged())], check=True)
    shutil.rmtree(host.staged())
    staged(host, capsys)
    status, record = host.run("judge-launch", capsys)
    assert status == 0 and record["ready"] is True and record["replacement"] is True, record
    return record


def substitute_store(host: LaunchHost) -> None:
    """The same name, mode, owner and group: only the identity differs."""

    store = host.launch() / artifacts.STORE
    # Made before the original goes, so the file system cannot reuse its inode.
    other = store.with_name("other")
    other.mkdir(mode=artifacts.STORE_MODE)
    other.chmod(artifacts.STORE_MODE)
    for child in store.iterdir():
        child.unlink()
    store.rmdir()
    other.rename(store)


@LINUX
def test_a_replacement_keeps_the_store_and_what_it_holds(
    launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    """The accepting path: host drift, retirement, a fresh R13 into the kept ``L``."""

    sentinel = with_binding(launch_host, capsys)
    store = sentinel.parent
    before = (os.stat(store).st_ino, os.stat(sentinel).st_ino)
    # The host moved on, as an unattended upgrade moves it.
    (launch_host.root / artifacts.LIBRARY / "encodings/utf_8.py").write_bytes(b"# new\n")
    status, _ = launch_host.run("verify-launch", capsys)
    assert status == 1
    judgement = retired(launch_host, capsys)
    status, record = launch_host.run("verify-retired", capsys)
    assert status == 0 and record["retired"] is True, record
    assert record["observed"][PROFILE_PATH] == {"state": "absent"}
    restaged(launch_host, capsys)
    assert launch_host.install(sequence=replacement_sequence()) == 0
    status, verified = launch_host.run("verify-launch", capsys)
    assert status == 0 and verified["installed"] is True, verified
    assert verified["replacement"] is True
    assert sentinel.read_bytes() == SENTINEL
    assert (os.stat(store).st_ino, os.stat(sentinel).st_ino) == before
    assert judgement["retained"]["ino"] == before[0]


@LINUX
def test_a_partial_retirement_completes_on_a_rerun(
    launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    sentinel = with_binding(launch_host, capsys)
    retired(launch_host, capsys, steps=3)
    retired(launch_host, capsys)
    status, record = launch_host.run("verify-retired", capsys)
    assert status == 0 and record["retired"] is True, record
    assert sentinel.read_bytes() == SENTINEL


RETIREMENT_FAULTS = {
    "mount beneath": "has mounts at or beneath it",
    "launch mounted": "has mounts at or beneath it",
    "launch mode": "is not a real root-owned 0o755 directory",
    "store mode": "is not a real root-owned 0o750 directory",
    "store owner": "is not a real root-owned 0o750 directory",
    "store group": "is not a real root-owned 0o750 directory",
    "store symlink": "is not a real root-owned 0o750 directory",
    "unknown entry": "does not name",
    "rm": "must be a regular file owned by root",
    "profile gone while loaded": "constructicon-m8-launch",
    "unsafe ancestor": "must be a real directory owned by root",
}


@LINUX
@pytest.mark.parametrize("fault", list(RETIREMENT_FAULTS))
def test_each_retirement_precondition_refuses(
    fault: str, launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    message = RETIREMENT_FAULTS[fault]
    with_binding(launch_host, capsys)
    launch = launch_host.launch()
    store = launch / artifacts.STORE
    if fault == "mount beneath":
        launch_host.mount(launch / "runtime" / "usr")
    elif fault == "launch mounted":
        launch_host.mount(launch)
    elif fault == "launch mode":
        launch.chmod(0o775)
    elif fault == "store mode":
        store.chmod(0o755)
    elif fault == "store owner":
        launch_host.owners[store] = os.getuid() + 1
    elif fault == "store group":
        launch_host.gids[store] = os.getgid() + 1
    elif fault == "store symlink":
        (store / "binding").unlink()
        store.rmdir()
        store.symlink_to(launch_host.home)
    elif fault == "unknown entry":
        (launch / "extra").write_bytes(b"")
    elif fault == "rm":
        launch_host.owners[launch_host.root / artifacts.RM] = os.getuid() + 1
    elif fault == "profile gone while loaded":
        (launch_host.root / artifacts.LAUNCH_PROFILE_DESTINATION).unlink()
    else:
        (launch_host.root / "var/lib").chmod(0o775)
    status, record = launch_host.run("judge-retire", capsys)
    assert status == 1 and record["ready"] is False
    assert message in record["failure"], record["failure"]


@LINUX
@pytest.mark.parametrize("steps", range(1, 4))
def test_verify_retired_refuses_an_incomplete_retirement(
    steps: int, launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    with_binding(launch_host, capsys)
    retired(launch_host, capsys, steps=steps)
    status, record = launch_host.run("verify-retired", capsys)
    assert status == 1 and record["retired"] is False
    assert "holds more than its store" in record["failure"], record["failure"]


@LINUX
def test_verify_retired_refuses_a_launch_profile_still_loaded(
    launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    with_binding(launch_host, capsys)
    retired(launch_host, capsys)
    with launch_host.kernel.open("a", encoding="utf-8") as kernel:
        kernel.write("constructicon-m8-workload (enforce)\n")
    status, record = launch_host.run("verify-retired", capsys)
    assert status == 1 and "still loaded" in record["failure"], record


@LINUX
@pytest.mark.parametrize("command", ["verify-retired", "judge-launch", "verify-launch"])
def test_a_substituted_store_is_never_kept(
    command: str, launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    with_binding(launch_host, capsys)
    retired(launch_host, capsys)
    if command == "verify-launch":
        restaged(launch_host, capsys)
        assert launch_host.install(sequence=replacement_sequence()) == 0
    elif command == "judge-launch":
        subprocess.run(["chmod", "-R", "u+w", str(launch_host.staged())], check=True)
        shutil.rmtree(launch_host.staged())
        staged(launch_host, capsys)
    substitute_store(launch_host)
    status, record = launch_host.run(command, capsys)
    assert status == 1, record
    assert "is not the store judge-retire found" in record["failure"], record["failure"]


@LINUX
def test_a_retirement_from_another_commit_is_never_kept(
    launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    with_binding(launch_host, capsys)
    retired(launch_host, capsys)
    record_path = launch_host.workspace / artifacts.RETIREMENT
    judgement = json.loads(record_path.read_text(encoding="utf-8"))
    for forged in (
        {**judgement, "commit": "f" * 40}, [judgement], {**judgement, "retained": None}
    ):
        record_path.write_text(json.dumps(forged), encoding="utf-8")
        status, record = launch_host.run("verify-retired", capsys)
        assert status == 1 and "not a ready retirement judgement" in record["failure"], record


@LINUX
def test_verify_launch_with_nothing_installed_itemizes_absence(
    launch_host: LaunchHost, capsys: pytest.CaptureFixture[str]
) -> None:
    status, record = launch_host.run("verify-launch", capsys)
    assert status == 1 and record["installed"] is False
    for name in artifacts.LAUNCH_ENTRIES:
        assert record["observed"][f"{LAUNCH_PATH}/{name}"] == {"state": "absent"}
    assert record["observed"][LAUNCH_PATH] == {"state": "absent"}
    assert record["observed"][PROFILE_PATH] == {"state": "absent"}


@LINUX
def test_the_writer_never_overwrites(tmp_path: Path) -> None:
    entries: list[artifacts.Entry] = [
        (".", "directory", 0o755, None),
        ("a", "file", 0o644, ("bytes", b"first")),
        ("a", "file", 0o644, ("bytes", b"second")),
    ]
    with pytest.raises(FileExistsError):
        artifacts.materialize(entries, tmp_path / "tree", artifacts.contents())
    assert (tmp_path / "tree/a").read_bytes() == b"first"
    with pytest.raises(FileExistsError):
        artifacts.materialize(entries[:1], tmp_path / "tree", artifacts.contents())


@LINUX
def test_a_tree_summary_is_bounded(tmp_path: Path) -> None:
    root = tmp_path / "host"
    runtime = root / artifacts.LAUNCH / "runtime"
    runtime.mkdir(parents=True)
    for index in range(artifacts.TREE_SUMMARY + 8):
        (runtime / f"{index:03}").write_bytes(b"")
    expected = {"runtime": [(".", 0o555, "directory")], "vendor": []}
    observed = artifacts.observe_launch(root, KERNEL_LIST, expected)
    entry = observed["/" + artifacts.LAUNCH + "/runtime"]
    assert entry["different"] == artifacts.TREE_SUMMARY + 9  # type: ignore[index]
    assert len(entry["differences"]) == artifacts.TREE_SUMMARY  # type: ignore[index]


@LINUX
def test_a_host_source_that_resolves_outside_the_root_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "host"
    closure_host(root)
    outside = tmp_path / "outside.py"
    outside.write_bytes(b"# not the host's\n")
    (root / artifacts.LIBRARY / "escape.py").symlink_to(outside)
    monkeypatch.setattr(artifacts, "resolve", trace)
    with pytest.raises(ValueError, match="resolves outside the host root"):
        plan(root)


# --- CI's installed runtime (foundation lane, as m8-service) ------------------


@pytest.fixture
def ci_runtime() -> Path:
    location = os.environ.get("M8_LINUX_ROOT")
    if not location or sys.platform != "linux":
        if os.environ.get("M8_CONTAINMENT_REQUIRED"):
            pytest.fail("the required Linux containment environment is missing")
        pytest.skip("CI's installed runtime exists only in the containment lanes")
    return Path(location)


@pytest.fixture
def ci_package() -> Path:
    location = os.environ.get("M8_CODEX_TARBALL")
    if not location or sys.platform != "linux":
        if os.environ.get("M8_CONTAINMENT_REQUIRED"):
            pytest.fail("the required Linux containment environment is missing")
        pytest.skip("CI's downloaded package exists only in the containment lanes")
    return Path(location)


def test_the_host_planner_accepts_the_package_ci_installed(
    ci_runtime: Path, ci_package: Path
) -> None:
    """The release CI unpacked with tar passes the host's archive rules, to the same tree.

    A package the host would refuse is found here, before any host retires its old one.
    """

    from tests.vendor_pin import CODEX_SHA256

    with artifacts.open_vendor(ci_package, CODEX_SHA256) as archive:
        plan, digests = artifacts.vendor_plan(archive)
    expected = artifacts.expected_inventory(plan, lambda entry: digests[entry[0]])
    installed = artifacts.tree_inventory(ci_runtime / "native-codex")
    assert artifacts.compare(installed, expected, 0) == []


def checkout_plan() -> list[artifacts.Entry]:
    from constructicon.substrate.executors import _egress_bridge, _supervisor

    return artifacts.runtime_plan(
        Path("/"),
        Path(_supervisor.__file__).read_bytes(),
        Path(_egress_bridge.__file__).read_bytes(),
        _supervisor.NAMESPACE_SCRIPT,
        _egress_bridge.BRIDGE_SCRIPT,
    )


def test_the_host_writer_reproduces_the_ci_runtime(ci_runtime: Path, tmp_path: Path) -> None:
    """The stager's writer, then root's exact ``cp``, give CI's runtime and runtime.json."""

    from constructicon.substrate.executors.linux import BWRAP_SHA256, runtime_inventory

    entries = checkout_plan()
    staging = tmp_path / "staged-runtime"
    artifacts.materialize(entries, staging, artifacts.contents())
    copy = tmp_path / "runtime"
    subprocess.run(["/usr/bin/cp", *CP_FLAGS, str(staging), str(copy)], check=True, timeout=120)
    assert runtime_inventory(copy, require_immutable=False) == runtime_inventory(
        ci_runtime / "runtime"
    )

    def digest(entry: artifacts.Entry) -> str:
        kind, value = entry[3]  # type: ignore[misc]
        return artifacts.hash_regular(value) if kind == "host" else sha256(value)

    inventory = artifacts.expected_inventory(entries, digest)
    policy = Path("/" + artifacts.LAUNCH_PROFILE_DESTINATION).read_bytes()
    abi = Path("/" + artifacts.ABI).read_bytes()
    document = artifacts.runtime_json(inventory, BWRAP_SHA256, sha256(policy), sha256(abi))
    installed = (ci_runtime / "runtime.json").read_bytes()
    assert json.loads(document) == json.loads(installed)


def test_the_loader_list_resolves_as_ldd_does(ci_runtime: Path) -> None:
    """The one change to CI's builder, ``ldd`` to the loader's ``--list``, changes nothing."""

    root = Path("/")
    loader = root / artifacts.LOADER  # the canonical path, as the shared plan runs it
    library = root / artifacts.LIBRARY
    binaries = [
        root / artifacts.PYTHON,
        root / artifacts.GIT_BINARY,
        *sorted(library.rglob("*.so")),
    ]
    assert len(binaries) > 10, "too few binaries to prove anything"
    for binary in binaries:
        traced = subprocess.run(
            ["/usr/bin/ldd", str(binary)], capture_output=True, text=True, check=True, timeout=60
        )
        by_ldd = re.findall(r"(?:=>\s+)?(/[\w./+-]+)", traced.stdout)
        assert artifacts.resolve(loader, binary) == by_ldd, binary
