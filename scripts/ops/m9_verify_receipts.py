"""Check captured native verifier receipts; caller supplies independently selected pins.

This checks evidence, not transport, command execution, or owner authority.
"""

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

LIMIT = 65536
SCRIPT = "scripts/ci/m8_host_artifacts.py"


def require(condition, label):
    if not condition:
        raise ValueError(label)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON member")
        result[key] = value
    return result


def record(raw, limit=LIMIT):
    require(0 < len(raw) <= limit, "record bound")
    value = json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("JSON constant")),
    )
    require(type(value) is dict, "record object")
    return value


def read(path, uid, limit=LIMIT):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_uid == uid
            and before.st_nlink == 1
            and not before.st_mode & 0o022
            and 0 < before.st_size <= limit,
            "unsafe file",
        )
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        require(
            len(raw) == before.st_size
            and before.st_ctime_ns == after.st_ctime_ns
            and before.st_mtime_ns == after.st_mtime_ns,
            "file changed",
        )
        return raw


def obj(parent, key):
    value = parent.get(key)
    require(type(value) is dict, "missing record object")
    return value


def successful(raw, command, commit, verdict, witness):
    result = record(raw)
    require(
        type(result.get("schema_version")) is int
        and result["schema_version"] == 2
        and result.get("command") == command
        and result.get("commit") == commit
        and result.get(verdict) is True
        and "failure" not in result
        and result.get("first_parent") is True
        and result.get("script_matches_commit") is True,
        "affirmative native verifier facts",
    )
    require(obj(obj(result, "blobs"), SCRIPT).get("sha256") == witness, "verifier source blob")
    return result


def zero_tree(entry):
    require(
        entry.get("state") == "tree"
        and type(entry.get("different")) is int
        and entry["different"] == 0
        and entry.get("differences") == [],
        "tree equality",
    )


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    for name in (
        "selection",
        "old-digest",
        "runtime-digest",
        "manifest-sha",
        "retirement-sha",
        "launch-commit",
        "controller-commit",
        "witness",
        "launch-root",
        "controller-root",
        "retirement",
        "manifest",
        "profiles",
        "launch",
        "controller",
    ):
        parser.add_argument("--" + name, required=True)
    p = parser.parse_args()

    def hex64(value):
        return re.fullmatch(r"[0-9a-f]{64}", value) is not None

    require(
        hex64(p.witness)
        and hex64(p.manifest_sha)
        and all(re.fullmatch(r"sha256:[0-9a-f]{64}", v) for v in (p.old_digest, p.runtime_digest)),
        "selected pins",
    )
    require(read(p.profiles, os.getuid()).endswith(b"\n"), "incomplete profiles")
    replacement = p.selection == "replaced"
    require(p.selection in ("kept", "replaced"), "owner-selected branch required")
    if replacement:
        require(
            p.old_digest != p.runtime_digest and hex64(p.retirement_sha), "replacement identity"
        )
        raw = read(p.retirement, os.getuid())
        require(hashlib.sha256(raw).hexdigest() == p.retirement_sha, "retirement record hash")
        retired = successful(raw, "judge-retire", p.controller_commit, "ready", p.witness)
        kept = obj(retired, "retained")
        require(
            set(kept) == {"dev", "ino", "gid", "qualification"}
            and all(type(kept[k]) is int and kept[k] >= 0 for k in ("dev", "ino", "gid")),
            "retained roots recorded",
        )
        path = Path(p.launch_root) / "qualification"
        try:
            q = path.lstat()
        except FileNotFoundError:
            require(kept["qualification"] is None, "missing retained qualification directory")
        else:
            require(
                kept["qualification"] == {"dev": q.st_dev, "ino": q.st_ino}
                and stat.S_ISDIR(q.st_mode)
                and q.st_uid == q.st_gid == 0
                and stat.S_IMODE(q.st_mode) == 0o755,
                "qualification directory identity changed",
            )
    else:
        require(
            p.old_digest == p.runtime_digest
            and p.retirement_sha == "none"
            and not os.path.lexists(p.retirement),
            "kept identity",
        )
    manifest = read(p.manifest, 0, 4 * 1024 * 1024)
    require(
        hashlib.sha256(manifest).hexdigest() == p.manifest_sha
        and record(manifest, 4 * 1024 * 1024).get("runtime_digest") == p.runtime_digest,
        "manifest bytes",
    )
    launch = successful(
        read(p.launch, os.getuid()), "verify-launch", p.launch_commit, "installed", p.witness
    )
    require(
        launch.get("replacement") is replacement
        and launch.get("runtime_digest") == p.runtime_digest,
        "selected launch",
    )
    observed = obj(launch, "observed")
    for name in ("runtime", "native-codex"):
        zero_tree(obj(observed, p.launch_root + "/" + name))
    entry = obj(observed, p.launch_root + "/runtime.json")
    require(
        entry.get("state") == "file" and entry.get("sha256") == p.manifest_sha,
        "installed manifest observation",
    )
    controller = successful(
        read(p.controller, os.getuid()),
        "verify-controller",
        p.controller_commit,
        "installed",
        p.witness,
    )
    zero_tree(obj(obj(controller, "observed"), p.controller_root))
    print("m9-selected-launch-and-controller-checked")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("M9_VERIFIER_RECEIPT_REFUSED: " + str(exc), file=sys.stderr)
        sys.exit(1)
