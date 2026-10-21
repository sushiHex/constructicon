"""Install the pinned member for credential-free hosted startup observation only.

The unprivileged workflow downloads an archive, not an installer. This helper
never executes its contents and never alters the existing fake-peer fixture.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
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
    require(not vendor.exists() and not vendor.is_symlink()
            and not report_path.exists() and not report_path.is_symlink(),
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
    report: dict[str, object] = {
        "schema_version": 1, "scope": "credential_free_native_startup_fixture",
        "version": VERSION, "archive_sha256": ARCHIVE_SHA256,
        "member_sha256": MEMBER_SHA256, "member_size": MEMBER_SIZE,
        "vendor_digest": str(runtime_digest(vendor)),
        "production_available": False, "subscription_qualified": False,
        "claude_qualified": False,
    }
    with report_path.open("x") as destination:
        destination.write(json.dumps(report, sort_keys=True) + "\n")
    report_path.chmod(0o444)
    return report


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True))
