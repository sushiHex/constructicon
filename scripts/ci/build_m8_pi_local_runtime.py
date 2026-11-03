"""Stage pinned local model/server bytes into a disposable immutable runtime."""

import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

from verify_m8_pi_local_artifacts import PINS, verify

from constructicon.substrate.executors.linux import runtime_digest, runtime_inventory


def stage_server(archive, destination):
    verify(archive, *PINS["server"])
    prefix = "llama-b12069/"
    seen = set()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            name = member.name.removeprefix(prefix)
            if not member.name.startswith(prefix) or "/" in name:
                continue
            if name != "llama-server" and not (name.startswith("lib") and ".so" in name):
                continue
            if name in seen:
                raise ValueError("duplicate server member")
            seen.add(name)
            target = destination / name
            if member.isfile():
                source = tar.extractfile(member)
                if source is None:
                    raise ValueError("unreadable server member")
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
            elif (member.issym() and member.linkname.startswith("lib")
                  and "/" not in member.linkname):
                target.symlink_to(member.linkname)
            else:
                raise ValueError("unsupported server member")
    if "llama-server" not in seen or "libllama-server-impl.so" not in seen:
        raise ValueError("server executable or implementation missing")
    # Resolve every staged link inside the verified directory before sealing.
    for target in destination.iterdir():
        if target.is_symlink() and (not target.resolve().is_file() or
                                   target.resolve().parent != destination.resolve()):
            raise ValueError("server library link leaves staged closure")
    verify(archive, *PINS["server"])


def main():
    if os.getuid() != 0 or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise SystemExit("local runtime requires the disposable hosted runner")
    if len(sys.argv) != 5:
        raise SystemExit("usage: build_m8_pi_local_runtime.py BASE DEST SERVER MODEL")
    base, destination, server, model = map(Path, sys.argv[1:])
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        raise SystemExit("runtime destination must be fresh and absolute")
    runtime_inventory(base)
    verify(model, *PINS["model"])
    shutil.copytree(base, destination, symlinks=True)
    payload = destination / "opt/pi-local"
    payload.mkdir(parents=True)
    # Root-only copy closes replacement races on the runner-owned download path.
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        archived = Path(temporary) / "server.tar.gz"
        shutil.copyfile(server, archived)
        stage_server(archived, payload)
    shutil.copyfile(model, payload / "model.gguf")
    # Reverify copied bytes: verification before copy does not grant custody.
    verify(payload / "model.gguf", *PINS["model"])
    for name in ("libgomp.so.1", "libstdc++.so.6", "libgcc_s.so.1", "libssl.so.3",
                 "libcrypto.so.3"):
        target = destination / "lib/x86_64-linux-gnu" / name
        if not target.exists():
            shutil.copyfile(Path("/usr/lib/x86_64-linux-gnu") / name, target)
    (payload / "llama-server").chmod(0o555)
    for path in [*destination.rglob("*"), destination]:
        if not path.is_symlink():
            path.chmod(0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444)
    print(json.dumps({"runtime_digest": str(runtime_digest(destination))}, sort_keys=True))


if __name__ == "__main__":
    main()
