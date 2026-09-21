"""Create a credential-free native-store fixture on the disposable M8 runner.

This is CI provisioning only. It creates one fresh, fixed fixture and emits its
sealed identity; it never prints the fixture locator or metadata contents.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

from constructicon.core.identity import canonical_json, digest
from constructicon.substrate.executors import operator_store

RUNNER_ROOT = Path("/var/lib/constructicon-m8-launch")
STORE_ROOT = RUNNER_ROOT / "operator-stores"
STORE_KEY = "n3a-fixture"
GENERATION = 1
MARKER_NAME = "fixture-marker"


def _write_exclusive(path: Path, content: bytes, *, mode: int) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, mode,
    )
    try:
        remaining = memoryview(content)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("short write while creating native-store fixture metadata")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_runner() -> tuple[int, int]:
    if sys.platform != "linux":
        raise SystemExit("native-store fixture provisioning requires Linux")
    if os.geteuid() != 0 or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise SystemExit("native-store fixture provisioning requires the disposable hosted runner")
    if len(sys.argv) != 1:
        raise SystemExit("native-store fixture provisioning accepts no arguments")

    import grp
    import pwd

    try:
        service = pwd.getpwnam("m8-service")
        service_group = grp.getgrgid(service.pw_gid)
    except KeyError as exc:
        raise SystemExit("native-store fixture service account is unavailable") from exc
    if service.pw_uid == 0 or service.pw_gid == 0 or service_group.gr_gid == 0:
        raise SystemExit("native-store fixture service account must be unprivileged")

    try:
        parent = RUNNER_ROOT.lstat()
    except OSError as exc:
        raise SystemExit("native-store fixture runtime root is unavailable") from exc
    if (
        not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022
    ):
        raise SystemExit("native-store fixture runtime root is not trusted")
    if STORE_ROOT.exists() or STORE_ROOT.is_symlink():
        raise SystemExit("native-store fixture destination must be fresh")
    return service.pw_uid, service.pw_gid


def _activate(bundle: Path, *, service_gid: int) -> None:
    descriptor_path = bundle / "descriptors" / f"{GENERATION}.json"
    descriptor = operator_store._descriptor(descriptor_path.read_bytes())
    active = {
        "schema_version": 1,
        "key": STORE_KEY,
        "generation": GENERATION,
        "binding_digest": str(descriptor.binding_digest),
        "descriptor_digest": str(descriptor.descriptor_digest),
    }
    active_path = bundle / "active.json"
    _write_exclusive(active_path, canonical_json(active).encode("utf-8"), mode=0o440)
    os.chown(active_path, 0, service_gid)
    os.chmod(active_path, 0o440)
    directory_fd = os.open(bundle, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _seal_metadata(bundle: Path, *, service_gid: int) -> None:
    descriptor_dir = bundle / "descriptors"
    for metadata_file in (bundle / "anchor.json", bundle / "active.json",
                          descriptor_dir / f"{GENERATION}.json"):
        os.chown(metadata_file, 0, service_gid)
        os.chmod(metadata_file, 0o440)
    os.chown(descriptor_dir, 0, service_gid)
    os.chmod(descriptor_dir, 0o750)
    os.chown(bundle, 0, service_gid)
    os.chmod(bundle, 0o750)


def main() -> None:
    service_uid, service_gid = _require_runner()
    STORE_ROOT.mkdir(mode=0o750)
    os.chown(STORE_ROOT, 0, service_gid)
    os.chmod(STORE_ROOT, 0o750)

    mode_revision = digest("native-operator-store-fixture", 1, "subscription-mode")
    conformance_revision = digest(
        "native-operator-store-fixture", 1, "fixture-only-unqualified",
    )
    identity = operator_store.publish_descriptor_offline(
        STORE_ROOT,
        STORE_KEY,
        GENERATION,
        runtime_uid=service_uid,
        subscription_mode_adapter_revision=mode_revision,
        store_conformance_revision=conformance_revision,
    )

    bundle = STORE_ROOT / operator_store._bundle_token(STORE_KEY)
    store = bundle / "store"
    lock = bundle / "retained.lock"
    marker = store / MARKER_NAME
    _write_exclusive(
        marker,
        b"harmless fixture\n",
        mode=0o600,
    )
    os.chown(marker, service_uid, service_gid)
    os.chmod(marker, 0o600)
    os.chown(store, -1, service_gid)
    os.chown(lock, -1, service_gid)

    store_info = store.stat()
    lock_info = lock.stat()
    if (
        store_info.st_uid != service_uid or store_info.st_gid != service_gid
        or stat.S_IMODE(store_info.st_mode) != 0o700
        or lock_info.st_uid != service_uid or lock_info.st_gid != service_gid
        or stat.S_IMODE(lock_info.st_mode) != 0o600
    ):
        raise SystemExit("native-store fixture publisher ownership is unexpected")

    _activate(bundle, service_gid=service_gid)
    _seal_metadata(bundle, service_gid=service_gid)
    print(json.dumps(identity.model_dump(mode="json"), sort_keys=True))


if __name__ == "__main__":
    main()
