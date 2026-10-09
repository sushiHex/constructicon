"""Refresh docs/plans/MANIFEST.sha256 for the documents you name, and only those.

Usage, from the repository root, after `git add` of the documents:

    python scripts/regen_plan_manifest.py handoffs/NEW.md handoffs/M8-implementation-record.md

Paths are canonical Markdown paths relative to `docs/plans/`. A named path is
(re)hashed from its staged bytes, and a new one is registered. Naming a path
does not approve editing a frozen plan: that remains governed by AGENTS.md.
Every unnamed entry must be present with its committed HEAD digest, and its
staged bytes must match that digest. Every staged new document must be named.
Refusals write nothing. A conflicted working manifest is accepted only when
every side retains the committed digests for unnamed entries; named entries
are recomputed. Staged documents must be resolved first. Deletion and renaming
are not supported: removing a manifest line cannot bypass these checks.
tests/test_m8_ci_scope.py checks the result against the working tree, so commit
documents as LF (docs/plans/.gitattributes).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "plans" / "MANIFEST.sha256"
MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


def git(*arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        check=True, capture_output=True, stdin=subprocess.DEVNULL,
    ).stdout


def plan_path(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (not parsed.is_absolute() and parsed.as_posix() == path
            and ".." not in parsed.parts and "\\" not in path
            and ":" not in path and "\n" not in path and "\r" not in path
            and parsed.suffix == ".md")


def entries(blob: bytes, *, conflicts: bool = False) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for line in blob.decode("utf-8").splitlines():
        if not line.strip() or (conflicts and line.startswith(MARKERS)):
            continue
        digest, path = line.split("  ", 1)
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not plan_path(path):
            raise ValueError(f"invalid manifest entry: {line}")
        if path in found and not conflicts:
            raise ValueError(f"duplicate committed manifest entry: {path}")
        found.setdefault(path, []).append(digest)
    return found


def staged_documents() -> set[str]:
    paths: set[str] = set()
    for entry in git("ls-files", "--stage", "-z", "--", "docs/plans/").split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        path = raw_path.decode("utf-8").removeprefix("docs/plans/")
        if PurePosixPath(path).suffix != ".md":
            continue
        mode, _oid, stage = metadata.split()
        if stage != b"0" or mode not in (b"100644", b"100755") or not plan_path(path):
            raise ValueError(f"unresolved or non-regular staged document: {path}")
        paths.add(path)
    return paths


def main(named: list[str]) -> int:
    try:
        if any(not plan_path(path) for path in named):
            raise ValueError("name canonical Markdown paths relative to docs/plans/")
        baseline = {path: digests[0] for path, digests in
                    entries(git("show", "HEAD:docs/plans/MANIFEST.sha256")).items()}
        current = entries(MANIFEST.read_bytes(), conflicts=True)
        staged = staged_documents()
        wanted = set(baseline) | set(named)
        if staged != wanted:
            raise ValueError("staged document inventory differs; missing or unnamed new paths: "
                             + ", ".join(sorted(staged ^ wanted)))
        if set(current) - wanted:
            raise ValueError("manifest contains unknown unnamed paths: "
                             + ", ".join(sorted(set(current) - wanted)))
        drift = [path for path, digest in baseline.items() if path not in named and (
            path not in current or any(value != digest for value in current[path])
            or hashlib.sha256(git("show", f":docs/plans/{path}")).hexdigest() != digest
        )]
        if drift:
            raise ValueError("committed digests differ or entries are missing for documents "
                             "not named: " + ", ".join(drift))
        updated = dict(baseline)
        for path in named:
            updated[path] = hashlib.sha256(git("show", f":docs/plans/{path}")).hexdigest()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    MANIFEST.write_bytes("".join(f"{d}  {p}\n" for p, d in updated.items()).encode("utf-8"))
    print(f"{len(updated)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
