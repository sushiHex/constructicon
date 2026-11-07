"""Exercise the real checker in a fresh interpreter with synthetic receipts."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ops/m9_verify_receipts.py"


@pytest.mark.parametrize("authority", ["kept", "absent", "created", "retained"])
def test_fresh_process_receipts(tmp_path, authority):
    replacement = authority != "kept"
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
    launch_root, controller_root = (tmp_path / "launch-root").as_posix(), "/controller"
    directory = Path(launch_root) / "qualification"
    if authority in ("created", "retained"):
        directory.mkdir(parents=True)
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
        prior = None
        if authority == "retained":
            info = directory.lstat()
            prior = {"dev": info.st_dev, "ino": info.st_ino}
        retired = {
            **common,
            "command": "judge-retire",
            "commit": args["launch-commit"],
            "ready": True,
            "retained": {"dev": 1, "ino": 2, "gid": 3, "qualification": prior},
        }

        def record_retirement():
            args["retirement"] = write("retire", retired)
            raw = Path(args["retirement"]).read_bytes()
            args["retirement-sha"] = hashlib.sha256(raw).hexdigest()

        record_retirement()
        args["old-digest"] = "sha256:" + "d" * 64
        args["selection"] = "replaced"
    # Model root ownership only for the synthetic manifest's exact inode.
    # Windows also needs its unavailable POSIX flags and mode bits substituted.
    bootstrap = """
import os, runpy, sys
from pathlib import Path
manifest_path, owner, qualification, qualification_mode = sys.argv[1:5]
manifest = os.stat(manifest_path)
identity = (manifest.st_dev, manifest.st_ino)
old_fstat = os.fstat
old_lstat = Path.lstat
class Stat:
    def __init__(self, original): self.original = original
    def __getattr__(self, name):
        value = getattr(self.original, name)
        if name == "st_uid" and (self.original.st_dev, self.original.st_ino) == identity:
            return int(owner)
        return value & ~0o022 if os.name == "nt" and name == "st_mode" else value
os.fstat = lambda fd: Stat(old_fstat(fd))
class DirectoryStat(Stat):
    st_uid = st_gid = 0
    @property
    def st_mode(self):
        return (self.original.st_mode & ~0o7777) | int(qualification_mode, 8)
def lstat(path):
    info = old_lstat(path)
    return DirectoryStat(info) if path.as_posix() == qualification else info
Path.lstat = lstat
os.O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
os.O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
os.getuid = getattr(os, "getuid", lambda: 0)
sys.argv = sys.argv[5:]
runpy.run_path(sys.argv[0], run_name="__main__")
"""

    def run(owner=0, mode="755"):
        return subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                bootstrap,
                paths["manifest"],
                str(owner),
                directory.as_posix(),
                mode,
                str(SCRIPT),
                *[part for item in args.items() for part in ("--" + item[0], item[1])],
            ],
            capture_output=True,
            text=True,
        )

    result = run()
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "m9-selected-launch-and-controller-checked"
    if authority == "created":
        result = run(mode="775")
        assert result.returncode != 0 and "qualification directory identity" in result.stderr
        retired["commit"] = args["controller-commit"]
        record_retirement()
        result = run()
        assert result.returncode != 0 and "affirmative native verifier facts" in result.stderr
        retired["commit"] = args["launch-commit"]
        record_retirement()
    if authority == "retained":
        assert prior is not None
        retired["retained"]["qualification"] = {**prior, "ino": prior["ino"] + 1}
        record_retirement()
        result = run()
        assert result.returncode != 0 and "qualification directory identity" in result.stderr
        retired["retained"]["qualification"] = prior
        record_retirement()
    result = run(owner=1)
    assert result.returncode != 0 and "unsafe file" in result.stderr
    write("manifest", b"{}")
    result = run()
    assert result.returncode != 0 and "manifest bytes" in result.stderr
    write("manifest", manifest)
    controller["installed"] = False
    write("controller", controller)
    result = run()
    assert result.returncode != 0 and "affirmative native verifier facts" in result.stderr
    assert "NameError" not in result.stderr
