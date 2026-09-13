"""Prove N1's schema-3 records changed no gateway v1 byte, revision or decode.

Run with ``uv run python scripts/check_m8_native_operator_compatibility.py``.

No worktree mutation or dependency installation: the temporary export runs the
current interpreter and dependencies against the base commit's own src/tests,
so this proves code compatibility, not an old dependency-environment recreation.
The five compared facts are exactly the ones ADR 0021 requires to be preserved.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

BASE = "d2b8f9421e3b3a5d9edeec42064fa3b42100fa52"
GOLDENS = "tests/core/test_executor_v1_goldens.py"
FACTS = (
    "source-derived law revision",
    "legacy profile bytes",
    "complete profile bytes",
    "launch identity bytes",
    "content-derived launch revision",
)
SNIPPET = (
    "from constructicon.core.executor import EXECUTOR_LAW_REVISION; "
    "from constructicon.substrate.executors.fake import FakeExecutor; "
    "from tests.executorworld import FakeExecutorProvider; "
    "identity = FakeExecutorProvider().identity; "
    "print(str(EXECUTOR_LAW_REVISION)); "
    "print(FakeExecutor({}).profile.model_dump_json()); "
    "print(identity.profile.model_dump_json()); "
    "print(identity.model_dump_json()); "
    "print(identity.revision)"
)


def checked(args, *, cwd, env):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def path_env(location):
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(location / "src"), str(location))),
        "PYTHONIOENCODING": "utf-8",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    archive = subprocess.run(
        ["git", "archive", "--format=zip", BASE, "src", "tests", "pyproject.toml"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    with TemporaryDirectory(prefix="constructicon-n1-base-") as scratch:
        base = Path(scratch)
        with zipfile.ZipFile(io.BytesIO(archive)) as files:
            files.extractall(base)
        observed = {}
        for label, location in ((BASE, base), ("working tree", root)):
            observed[label] = checked(
                [sys.executable, "-c", SNIPPET], cwd=location, env=path_env(location)
            ).splitlines()
        for index, fact in enumerate(FACTS):
            at_base, at_head = observed[BASE][index], observed["working tree"][index]
            assert at_base == at_head, f"{fact} changed:\n  base {at_base}\n  head {at_head}"
            print(f"{fact}: identical at {BASE[:7]} and the working tree", flush=True)
        print(
            checked([sys.executable, "-m", "pytest", "-q", GOLDENS], cwd=root, env=path_env(root)),
            flush=True,
        )
    print("Gateway v1 bytes, revisions and decoded round trips are unchanged by N1.")


if __name__ == "__main__":
    main()
