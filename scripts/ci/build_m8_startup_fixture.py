"""Curate a separate immutable startup-test image; no production recipe change."""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from constructicon.substrate.executors.linux import runtime_digest, runtime_inventory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.native_codex_probe import CATALOG_SHA256, catalog_for


def main():
    if os.getuid() != 0 or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise SystemExit("startup fixture requires the authorized disposable runner")
    arguments = sys.argv[1:]
    placement = arguments[-1:] == ["--provider-placement"]
    base, destination, binary, catalog = map(Path, arguments[:-1] if placement else arguments)
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        raise SystemExit("startup fixture destination must be fresh and absolute")
    # This is a copy of the already curated immutable closure, not host /usr.
    runtime_inventory(base)
    shutil.copytree(base, destination, symlinks=True)
    destination.chmod(0o755)
    payload = destination / "opt/native-startup"
    payload.mkdir(parents=True)
    # Preserve the pinned package's own executable layout and runtime assets.
    shutil.copytree(binary.parent.parent, payload / "native", symlinks=True)
    raw_catalog = catalog.read_bytes()
    if hashlib.sha256(raw_catalog).hexdigest() != CATALOG_SHA256:
        raise SystemExit("catalog differs from pinned source")
    (payload / "catalog.json").write_bytes(catalog_for(raw_catalog, restricted=True))
    shutil.copyfile("tests/substrate/_native_startup_bootstrap.py", payload / "bootstrap.py")
    if placement:
        # The positive control uses the unchanged pinned catalog. Keep it in the
        # immutable fixture, not a setup RPC that exceeds the existing bound.
        (payload / "source-catalog.json").write_bytes(raw_catalog)
        for name in ("_provider_transport.py", "_provider_bridge.py", "_provider_bootstrap.py"):
            shutil.copyfile(Path("tests/substrate") / name, payload / name)
        (payload / "provider.sock").touch()  # Only this immutable leaf is overmounted.
    for path in [*destination.rglob("*"), destination]:
        if not path.is_symlink():
            path.chmod(0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444)
    print(json.dumps({
        "runtime_digest": str(runtime_digest(destination)),
        "entries": runtime_inventory(destination),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
