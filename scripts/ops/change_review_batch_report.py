"""Bounded offline metering report over finished change-review windows.

Each input delegates to the existing private reply collector. This projection
does not read a journal, retain a second ledger, call a vendor or infer prices.
Native attempts and known token subtotals keep their original source scope.
An unavailable reply supplies no usage evidence, including no evidence of zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from scripts.ops import change_review_reply as reply

from constructicon.core.control import MeteringSummary

MAX_WINDOWS = 32
REPORT_LIMIT = 32768
BOUND = "BATCH_REPORT_BOUND"
CONFLICT = "BATCH_REPORT_WINDOW_CONFLICT"
INVALID = "BATCH_REPORT_METERING_INVALID"
IDENTITY = "BATCH_REPORT_WINDOW_IDENTITY"
_COUNTS = ("intent_only", "unavailable", "partial", "observed")
_TOKENS = ("known_input_tokens", "known_output_tokens")


def _metering(value: object) -> dict[str, Any]:
    """Use the native result contract; never translate a new amount to unknown."""
    try:
        summary = MeteringSummary.model_validate_json(json.dumps(value, allow_nan=False))
    except (ValueError, TypeError, RecursionError) as error:
        raise reply.ReplyRefused(INVALID) from error
    groups = summary.groups
    # Producer: substrate/journal/_sqlite_metering.py:415-462 (_snapshot)
    # keys groups by source and increments count once per retained intent;
    # :395-404 (_Subtotal.add) assigns exactly one category to each intent.
    reply._need(
        len({group.source for group in groups}) == len(groups)
        and sum(sum(getattr(group, key) for key in _COUNTS) for group in groups)
        == summary.attempt_count,
        INVALID,
    )
    # Detail-by-reference stays with the original private reply. The report
    # retains its immutable cut and accepted evidence digest instead.
    projected = summary.model_dump(mode="json")
    projected.pop("detail")
    return projected


def _groups(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add existing source-scoped known subtotals, preserving unknown axes."""
    groups: dict[str, dict[str, Any]] = {}
    for window in windows:
        metering = window["metering"]
        if metering is None:
            continue
        for group in metering["groups"]:
            source = group["source"]
            if source not in groups:
                groups[source] = {"source": source, **dict.fromkeys(_COUNTS, 0),
                                  **dict.fromkeys(_TOKENS)}
            total = groups[source]
            for key in _COUNTS:
                total[key] += group[key]
            for key in _TOKENS:
                if group[key] is not None:
                    total[key] = (total[key] if total[key] is not None else 0) + group[key]
    return [groups[source] for source in sorted(groups)]


def collect(entries: list[tuple[Path, Path, Path]]) -> dict[str, Any]:
    """Collect 1..32 windows; canonical custody/record identity deduplicates inputs.

    RunId alone is not an observation identity: separate native windows can run
    the same deterministic request in fresh journals. Count both windows.
    Repeated inputs must still pass the real collector and agree on the whole
    reply and exact prepared packet bytes; a stale duplicate cannot hide damage.
    """
    reply._need(1 <= len(entries) <= MAX_WINDOWS, BOUND)
    seen: dict[tuple[Path, Path], bytes] = {}
    windows: list[dict[str, Any]] = []
    for index, (work, record, packet) in enumerate(entries, 1):
        try:
            identity = (work.resolve(strict=True), record.resolve(strict=True))
        except (OSError, RuntimeError, ValueError) as error:
            raise reply.ReplyRefused(IDENTITY) from error
        collected = reply.collect(work, record, packet)
        packet_hashes = [hashlib.sha256(reply._read(packet / name, limit, reply.PACKET)).hexdigest()
                         for name, limit in (("packet.json", reply.PACKET_LIMIT),
                                             ("summary.json", reply.SUMMARY_LIMIT),
                                             ("instruction.txt", reply.SUMMARY_LIMIT))]
        fingerprint = hashlib.sha256(reply._wire([collected, packet_hashes])).digest()
        if identity in seen:
            reply._need(seen[identity] == fingerprint, CONFLICT)
            continue
        seen[identity] = fingerprint
        delivered = collected["status"] == "delivered"
        windows.append({
            "first_input_index": index, "window": collected["window"],
            "status": collected["status"],
            "run_id": collected["run_id"] if delivered else None,
            "accepted_read_sha256": collected["accepted_read_sha256"] if delivered else None,
            "metering": _metering(collected["metering"]) if delivered else None,
        })
    coverage = dict.fromkeys(("supported_observations", "unmeasured", "legacy_unmeasured",
                              "unavailable"), 0)
    for window in windows:
        coverage[window["metering"]["coverage"] if window["metering"] else "unavailable"] += 1
    result = {
        "schema_version": 1,
        "projection": "change-review-window-run-result-v3-metering",
        "input_count": len(entries), "window_count": len(windows),
        "duplicate_input_count": len(entries) - len(windows),
        "coverage_counts": coverage,
        "recorded_attempt_count": sum(window["metering"]["attempt_count"]
                                      for window in windows if window["metering"] is not None),
        "groups": _groups(windows),
        "estimate": None, "estimate_coverage": "unknown",
        "confirmed_charge": None, "confirmed_charge_coverage": "unknown",
        "money_aggregation": "unsupported; original per-window values retained",
        "elapsed_s": None, "timing_coverage": "unavailable",
        "timing_reason": "not retained in run-result-v3 metering",
        "backend_request_count": None,
        "backend_request_count_coverage": "unknown",
        "windows": windows,
    }
    reply._need(len(reply._wire(result)) <= REPORT_LIMIT, BOUND)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--window", nargs=3, action="append", type=Path, required=True,
                        metavar=("WORK", "RECORD", "PACKET"))
    options = parser.parse_args(argv)
    try:
        report = collect(options.window)
    except reply.ReplyRefused as error:
        print(json.dumps({"status": "refused", "reason": error.code}))
        return 1
    sys.stdout.buffer.write(reply._wire(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
