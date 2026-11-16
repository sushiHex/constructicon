"""Prepare exact consumer input offline; no host or execution authority.

Run from a reviewed checkout with its project environment. Repository objects,
the imported source and the output parent are trusted local preparation inputs.
The host independently derives its actual component/provider/binding pins later.
An interrupted output directory is retained and is never resumed or replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from examples import change_review

from constructicon.api import change_review_advice as advice
from constructicon.core import control, identity


def _wire(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def prepare(repository: Path, controller: str, before: str, after: str,
            path: str, out: Path) -> dict:
    if (re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", controller) is None
            or change_review.git(repository, "cat-file", "-t", controller) != b"commit\n"):
        raise ValueError("consumer input controller is not an exact commit")
    sources = {}
    for name, module in (
        ("examples/change_review.py", change_review),
        ("src/constructicon/api/change_review_advice.py", advice),
        ("src/constructicon/core/control.py", control),
        ("src/constructicon/core/identity.py", identity),
    ):
        observed = Path(module.__file__).read_bytes()
        size = int(change_review.git(repository, "cat-file", "-s", f"{controller}:{name}"))
        if size != len(observed):
            raise ValueError("consumer input imported source differs from the selected commit")
        selected = change_review.git(repository, "cat-file", "blob", f"{controller}:{name}")
        if observed != selected:
            raise ValueError("consumer input imported source differs from the selected commit")
        sources[name] = hashlib.sha256(selected).hexdigest()
    _, left = change_review.committed_source(repository, before, path)
    _, right = change_review.committed_source(repository, after, path)
    report = change_review.compare_sources(left, right).model_dump(
        mode="json", exclude={"tests_executed"}
    )
    summary = advice.ChangeSummaryV1.model_validate(report)
    raw = _wire(summary.model_dump(mode="json"))
    bound = advice.bound_values(summary)
    record = {
        "schema_version": 1,
        "controller": controller,
        "checked_source_files": sources,
        "change": {"before": before, "after": after, "path": path},
        "summary_sha256": hashlib.sha256(raw).hexdigest(),
        "offline_pins": bound.projection(),
        "offline_pins_are_provisional": True,
        "execution_authorized": False,
    }
    # All validation precedes the exclusive claim. No overwrite or inferred reuse.
    out.mkdir(mode=0o700)
    for name, contents in (
        ("summary.json", raw),
        ("instruction.txt", bound.instruction.encode("utf-8")),
        ("packet.json", _wire(record)),
    ):
        with (out / name).open("xb") as stream:
            stream.write(contents)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--controller", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--out", type=Path, required=True)
    options = parser.parse_args(argv)
    try:
        record = prepare(options.repository, options.controller, options.before,
                         options.after, options.path, options.out)
    except (OSError, ValueError):
        print(json.dumps({"status": "refused", "reason": "consumer-input-unproved"}))
        return 1
    print(json.dumps({"status": "prepared", "summary_sha256": record["summary_sha256"],
                      "execution_authorized": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
