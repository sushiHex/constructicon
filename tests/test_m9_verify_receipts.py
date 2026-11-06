"""Exercise the real checker in a fresh interpreter with synthetic receipts."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ops/m9_verify_receipts.py"


@pytest.mark.parametrize("replacement", [False, True])
def test_fresh_process_receipts(tmp_path, replacement):
    digest = "sha256:" + "a" * 64
    witness = "b" * 64
    manifest = json.dumps(
        {
            "runtime_digest": digest,
            "entries": [[f"lib/path-{i:04d}", 0o444, "sha256:" + "e" * 64] for i in range(900)],
        }
    ).encode()
    assert len(manifest) > 65536
    manifest_sha = hashlib.sha256(manifest).hexdigest()
    launch_root, controller_root = "/launch", "/controller"
    tree = {"state": "tree", "different": 0, "differences": []}
    common = {
        "schema_version": 2,
        "first_parent": True,
        "script_matches_commit": True,
        "installed": True,
        "blobs": {"scripts/ci/m8_host_artifacts.py": {"sha256": witness}},
    }
    launch = {
        **common,
        "command": "verify-launch",
        "commit": "launch-commit",
        "replacement": replacement,
        "runtime_digest": digest,
        "observed": {
            launch_root + "/runtime": tree,
            launch_root + "/native-codex": tree,
            launch_root + "/runtime.json": {"state": "file", "sha256": manifest_sha},
        },
    }
    controller = {
        **common,
        "command": "verify-controller",
        "commit": "controller-commit",
        "observed": {controller_root: tree},
    }

    def write(name, value):
        path = tmp_path / name
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        path.chmod(0o600)
        return str(path)

    paths = {
        "manifest": write("manifest", manifest),
        "profiles": write("profiles", b"ok\n"),
        "launch": write("launch", launch),
        "controller": write("controller", controller),
        "retirement": str(tmp_path / "missing"),
    }
    args = {
        "selection": "kept",
        "old-digest": digest,
        "runtime-digest": digest,
        "manifest-sha": manifest_sha,
        "retirement-sha": "none",
        "launch-commit": "launch-commit",
        "controller-commit": "controller-commit",
        "witness": witness,
        "launch-root": launch_root,
        "controller-root": controller_root,
        **paths,
    }
    if replacement:
        retired = {
            **common,
            "command": "judge-retire",
            "commit": args["controller-commit"],
            "ready": True,
            "retained": {"dev": 1, "ino": 2, "gid": 3, "qualification": None},
        }
        args["retirement"] = write("retire", retired)
        args["retirement-sha"] = hashlib.sha256(Path(args["retirement"]).read_bytes()).hexdigest()
        args["old-digest"] = "sha256:" + "d" * 64
        args["selection"] = "replaced"
    # Only platform-bound file flags and ownership are substituted on Windows.
    bootstrap = """
import os, runpy, sys
if os.name == "nt":
    old_fstat = os.fstat
    class Stat:
        def __init__(self, original): self.original = original
        def __getattr__(self, name):
            value = getattr(self.original, name)
            return value & ~0o022 if name == "st_mode" else value
    os.fstat = lambda fd: Stat(old_fstat(fd))
os.O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
os.O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
os.getuid = getattr(os, "getuid", lambda: 0)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
"""

    def run():
        return subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                bootstrap,
                str(SCRIPT),
                *[part for item in args.items() for part in ("--" + item[0], item[1])],
            ],
            capture_output=True,
            text=True,
        )

    result = run()
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "m9-selected-launch-and-controller-checked"
    write("manifest", b"{}")
    result = run()
    assert result.returncode != 0 and "manifest bytes" in result.stderr
    write("manifest", manifest)
    controller["installed"] = False
    write("controller", controller)
    result = run()
    assert result.returncode != 0 and "affirmative native verifier facts" in result.stderr
    assert "NameError" not in result.stderr
