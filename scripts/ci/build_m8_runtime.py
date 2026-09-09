"""Trusted disposable-runner provisioning: curate, freeze, and identify userspace.

Never imported by Constructicon. Copies only installed Python and its dynamic
link closure, not the host /usr, home, project, package cache, or credentials.
The resulting content digest is the exact pin supplied to this job's assembly.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if os.getuid() != 0 or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise SystemExit("provisioning requires the explicitly authorized disposable runner")
    destination = Path(sys.argv[1])
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        raise SystemExit("runtime destination must be a fresh absolute path")
    destination.mkdir(mode=0o755)
    binaries: list[Path] = []

    def copy(source: Path) -> None:
        target = destination / source.relative_to("/")
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        shutil.copymode(source, target)

    executable = Path("/usr/bin/python3.12")
    copy(executable)
    binaries.append(executable)
    copy(Path("/usr/bin/git"))
    binaries.append(Path("/usr/bin/git"))
    library = Path("/usr/lib/python3.12")
    shutil.copytree(
        library, destination / "usr/lib/python3.12",
        ignore=shutil.ignore_patterns("__pycache__", "test", "tests", "ensurepip", "idlelib"),
    )
    binaries.extend(library.rglob("*.so"))
    for binary in binaries:
        result = subprocess.run(["ldd", str(binary)], capture_output=True, text=True, check=True)
        for value in re.findall(r"(?:=>\s+)?(/[\w./+-]+)", result.stdout):
            copy(Path(value))
    (destination / "usr/bin/python3").symlink_to("python3.12")
    for name in ("proc", "dev", "tmp", "workspace"):
        (destination / name).mkdir()
    for path in [*destination.rglob("*"), destination]:
        if not path.is_symlink():
            path.chmod(0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444)
    # The installed package supplies the one identity algorithm used at launch.
    from constructicon.substrate.executors.linux import runtime_digest

    print(json.dumps({"runtime_digest": str(runtime_digest(destination))}, sort_keys=True))


if __name__ == "__main__":
    main()
