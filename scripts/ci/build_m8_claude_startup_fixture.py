"""Install the pinned member for credential-free hosted startup observation only.

The unprivileged workflow downloads an archive, not an installer. This helper
never executes its contents and never alters the existing fake-peer fixture.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import sys
import tarfile
from pathlib import Path

from constructicon.substrate.executors.linux import runtime_digest, runtime_inventory

ROOT = Path("/var/lib/constructicon-m8-claude")
VERSION = "2.1.296"
ARCHIVE_BYTES = 268435456
ARCHIVE_SHA256 = "eef5a2e2b09a5e7d2ce784d1b3ba335ae7fc6c7f6256c802a0ebf2c21e4fd0e1"
MEMBER = "package/claude"
MEMBER_SIZE = 257068216
MEMBER_SHA256 = "24972e3bc859fab2b46ed4c1e51f7d6130f06d3bd550811a114640de3370d0de"
HOST_LIB = Path("/usr/lib/x86_64-linux-gnu")
LIBRARIES = ("librt.so.1", "libpthread.so.0", "libdl.so.2")
LIBRARY_BYTES = 1024 * 1024


def curate_runtime(destination: Path) -> dict[str, str]:
    """Add only the three statically identified missing glibc compatibility DSOs.

    This is a distinct hosted diagnostic image, not a private-host recipe or
    a dependency resolver. Actual startup, not the sonames, establishes closure.
    """
    for parent in (HOST_LIB, *HOST_LIB.parents):
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0
                and not info.st_mode & 0o022,
                "host library ancestors must be fixed root directories")
    libraries = {}
    for name in LIBRARIES:
        source = HOST_LIB / name
        require(source.resolve(strict=True) == source,
                "host library source must resolve to its fixed path")
        info = source.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
                and not info.st_mode & 0o6022,
                "host library source must be a fixed regular root file")
        with source.open("rb") as library:
            raw = library.read(LIBRARY_BYTES + 1)
        require(0 < len(raw) <= LIBRARY_BYTES, "host library exceeds its read bound")
        libraries[name] = raw
    shutil.copytree(ROOT / "runtime", destination, symlinks=True)
    # Thaw only directories in the fresh copy, never the source image. Root
    # could write through read-only modes; this also makes the operation honest
    # when portable tests substitute root custody rather than process privilege.
    destination.chmod(0o755)
    directory = destination
    for part in ("lib", "x86_64-linux-gnu"):
        directory /= part
        if directory.exists():
            require(directory.is_dir() and not directory.is_symlink(),
                    "runtime library destination must be a real directory")
            directory.chmod(0o755)
        else:
            directory.mkdir(mode=0o755)
    hashes = {}
    for name, raw in libraries.items():
        with (directory / name).open("xb") as target:
            target.write(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    for path in [*destination.rglob("*"), destination]:
        if not path.is_symlink():
            path.chmod(0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444)
    runtime_inventory(destination)
    return hashes


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def build() -> dict[str, object]:
    require(len(sys.argv) == 2, "startup provisioning requires one archive path")
    require(sys.platform == "linux" and os.geteuid() == 0
            and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted",
            "startup provisioning requires the disposable hosted CI runner")
    archive = Path(sys.argv[1])
    require(archive.is_absolute(), "archive path must be absolute")
    before = archive.lstat()
    require(stat.S_ISREG(before.st_mode), "archive must be a regular file")
    require(0 < before.st_size <= ARCHIVE_BYTES, "archive exceeds the download bound")
    with archive.open("rb") as archive_source:
        opened = os.fstat(archive_source.fileno())
        require((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
                "archive changed before opening")
        # A bounded immutable byte snapshot prevents a writable download from
        # changing between digest verification and tar parsing.
        raw = archive_source.read(ARCHIVE_BYTES + 1)
    require(len(raw) <= ARCHIVE_BYTES, "archive exceeds the read bound")
    require(hashlib.sha256(raw).hexdigest() == ARCHIVE_SHA256,
            "archive differs from the pinned source")
    runtime_inventory(ROOT / "runtime")
    pins = json.loads((ROOT / "fixture.json").read_text())
    require(str(runtime_digest(ROOT / "runtime")) == pins["runtime_digest"],
            "existing runtime differs from the fake fixture")
    vendor, report_path = ROOT / "pinned-vendor", ROOT / "pinned-startup.json"
    runtime = ROOT / "pinned-runtime"
    require(not vendor.exists() and not vendor.is_symlink()
            and not report_path.exists() and not report_path.is_symlink()
            and not runtime.exists() and not runtime.is_symlink(),
            "startup fixture must be fresh")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as package:
        selected = []
        for index, member in enumerate(package):
            require(index < 32, "archive member count exceeds its bound")
            if member.name == MEMBER:
                selected.append(member)
        require(len(selected) == 1, "archive must contain exactly one selected member")
        member = selected[0]
        require(member.isreg(), "selected member must be regular, not a link")
        require(member.size == MEMBER_SIZE, "selected member has the wrong size")
        vendor.mkdir(mode=0o755)
        payload = vendor / "claude"
        member_source = package.extractfile(member)
        if member_source is None:
            raise ValueError("selected member cannot be read")
        observed = hashlib.sha256()
        written = 0
        with member_source, payload.open("xb") as destination:
            while part := member_source.read(1024 * 1024):
                written += len(part)
                require(written <= MEMBER_SIZE, "selected member exceeds its bound")
                observed.update(part)
                destination.write(part)
        require(written == MEMBER_SIZE and observed.hexdigest() == MEMBER_SHA256,
                "selected member differs from the pinned source")
    payload.chmod(0o555)
    vendor.chmod(0o555)
    runtime_inventory(vendor)
    libraries = curate_runtime(runtime)
    report: dict[str, object] = {
        "schema_version": 1, "scope": "credential_free_native_startup_fixture",
        "version": VERSION, "archive_sha256": ARCHIVE_SHA256,
        "member_sha256": MEMBER_SHA256, "member_size": MEMBER_SIZE,
        "vendor_digest": str(runtime_digest(vendor)),
        "runtime_digest": str(runtime_digest(runtime)), "added_libraries": libraries,
        "production_available": False, "subscription_qualified": False,
        "claude_qualified": False,
    }
    with report_path.open("x") as destination:
        destination.write(json.dumps(report, sort_keys=True) + "\n")
    report_path.chmod(0o444)
    return report


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True))
