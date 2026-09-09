"""Run pre-M8 compatibility proofs against the complete committed base source.

No worktree mutation or dependency installation. The temporary export uses the
current interpreter/dependencies, with the base's own src/tests/config. This
proves code/manifest compatibility, not an old dependency-environment recreation.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

BASE = "3ee1beb6a58fac0bab85841a1f34d96b514c3c34"
COMPATIBILITY = "tests/runtime/test_membership_compatibility.py"
PROFILE = (
    "from constructicon.substrate.executors.fake import FakeExecutor; "
    "print(FakeExecutor({}).profile.model_dump_json())"
)


def checked(args, *, cwd, env):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    archive = subprocess.run(
        ["git", "archive", "--format=zip", BASE, "src", "tests", "pyproject.toml"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    with TemporaryDirectory(prefix="constructicon-m8-base-") as scratch:
        base = Path(scratch)
        with zipfile.ZipFile(io.BytesIO(archive)) as files:
            files.extractall(base)
        profiles = []
        for label, location in ((BASE, base), ("working tree", root)):
            env = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join((str(location / "src"), str(location))),
            }
            profiles.append(checked([sys.executable, "-c", PROFILE], cwd=location, env=env))
            output = checked(
                [sys.executable, "-m", "pytest", "-q", COMPATIBILITY],
                cwd=location,
                env=env,
            )
            print(f"{label}: {output}", flush=True)
        assert profiles[0] == profiles[1], "legacy executor profile bytes changed"
        assert '"grant_policy"' not in profiles[0]
        print("Full-base legacy profile bytes and six manifest goldens agree exactly.")


if __name__ == "__main__":
    main()
