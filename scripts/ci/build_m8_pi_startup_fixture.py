"""Provision only the pinned release's runtime files in a disposable CI image."""

import hashlib
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path, PurePosixPath

from constructicon.substrate.executors.linux import runtime_digest, runtime_inventory

ARCHIVE_SHA = "24f5be328b66d4da36876296989501974f43ab8434fbb57c35c523a3ea505ded"
BINARY_SHA = "c2415d6e6f7c67b0a55744c5ace5054936e252fcc3cf56ce087bc314061315ca"
RELEASE = "71023aec1546d6d677a65669c5665c0927ce0dd0"
RUNTIME_FILES = frozenset({
    "pi/pi", "pi/package.json", "pi/theme/light.json", "pi/theme/dark.json",
    "pi/assets/clankolas.png", "pi/photon_rs_bg.wasm",
    "pi/native/linux/prebuilds/linux-x64/linux-platform-x11.node",
    "pi/export-html/template.css", "pi/export-html/template.html",
    "pi/export-html/index.js", "pi/export-html/ansi-to-html.js",
    "pi/export-html/tool-renderer.js", "pi/export-html/template.js",
    "pi/export-html/vendor/marked.min.js", "pi/export-html/vendor/highlight.min.js",
})


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stage_release(archive, destination):
    if sha(archive) != ARCHIVE_SHA:
        raise ValueError("Pi release archive digest differs")
    observed = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if member.name not in RUNTIME_FILES:
                continue
            if not member.isreg() or member.name in observed:
                raise ValueError("Pi runtime member is not a unique regular file")
            target = destination / PurePosixPath(member.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            assert source is not None
            with source, target.open("xb") as stream:
                shutil.copyfileobj(source, stream)
            observed[member.name] = sha(target)
    if observed.keys() != RUNTIME_FILES or observed["pi/pi"] != BINARY_SHA:
        raise ValueError("Pi runtime member set or executable digest differs")
    if (destination / "pi/pi").stat().st_size != 107174016:
        raise ValueError("Pi executable size differs")
    (destination / "pi/pi").chmod(0o555)
    return observed


def main():
    if os.getuid() != 0 or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise SystemExit("startup fixture requires the authorized disposable runner")
    base, destination, archive = map(Path, sys.argv[1:])
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        raise SystemExit("startup fixture destination must be fresh and absolute")
    runtime_inventory(base)
    shutil.copytree(base, destination, symlinks=True)
    payload = destination / "opt/pi-startup"
    payload.mkdir(parents=True)
    members = stage_release(archive, payload)
    # Reviewed ELF DT_NEEDED closure on the selected Ubuntu x64 runner.
    # Do not invoke ldd/ld.so on the vendor binary during root provisioning.
    library = Path("usr/lib/x86_64-linux-gnu")
    for name in (
        "libpthread.so.0", "libdl.so.2", "libxcb.so.1", "libXau.so.6",
        "libXdmcp.so.6", "libbsd.so.0", "libmd.so.0",
    ):
        relative = library / name
        target = destination / relative
        if not target.exists():
            shutil.copyfile(Path("/") / relative, target)
        members[str(relative)] = sha(target)
    for path in [*destination.rglob("*"), destination]:
        if not path.is_symlink():
            path.chmod(0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444)
    print(json.dumps({
        "release_commit": RELEASE, "archive_sha256": ARCHIVE_SHA, "members": members,
        "runtime_digest": str(runtime_digest(destination)),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
