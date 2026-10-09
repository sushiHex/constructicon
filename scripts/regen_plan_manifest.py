"""Refresh docs/plans/MANIFEST.sha256 for the documents you name, and only those.

Usage, from the repository root, after `git add` of the documents:

    python scripts/regen_plan_manifest.py handoffs/NEW.md handoffs/M8-implementation-record.md

Paths are relative to `docs/plans/`. A named path is (re)hashed from its staged
bytes, and a new one is registered. Every other entry must still match its
staged bytes, or the tool refuses and writes nothing: approved plans are frozen
bytes (AGENTS.md), and the manifest is what holds them. A conflicted manifest
is accepted (both sides, first digest per path, then named paths recomputed),
so name the documents a rebase changed. To delete or rename a document, remove
its line by hand first. tests/test_m8_ci_scope.py checks the result against the
working tree, so commit documents as LF (docs/plans/.gitattributes).
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "plans" / "MANIFEST.sha256"
MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


def staged(path: str) -> str:
    blob = subprocess.run(
        ["git", "-C", str(ROOT), "show", f":docs/plans/{path}"],
        check=True, capture_output=True, stdin=subprocess.DEVNULL,
    ).stdout
    return hashlib.sha256(blob).hexdigest()


def main(named: list[str]) -> int:
    entries: dict[str, str] = {}
    for line in MANIFEST.read_bytes().decode("utf-8").splitlines():
        if line.startswith(MARKERS) or not line.strip():
            continue
        digest, path = line.split("  ", 1)
        entries.setdefault(path, digest)
    drift = [path for path in entries if path not in named and staged(path) != entries[path]]
    if drift:
        print("refused: staged bytes differ for documents not named:", *drift,
              sep="\n  ", file=sys.stderr)
        return 1
    for path in named:
        entries[path] = staged(path)
    MANIFEST.write_bytes("".join(f"{d}  {p}\n" for p, d in entries.items()).encode("utf-8"))
    print(f"{len(entries)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
