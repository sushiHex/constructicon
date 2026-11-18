"""Write one successor's private input from a checked, completed advice READ.

This is offline preparation, not compilation, approval or a host observation.
Only four predecessor fields are understood; the remaining template is opaque.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from scripts import m8_vm_usage
from scripts.ops import change_review_reply as reply
from scripts.ops.claude_read_commands import sha
from scripts.ops.claude_read_session import json_bytes, retain
from scripts.ops.m9_qualification_boundary import CLEANUP, STORE_KEY, QualificationBoundary
from scripts.ops.m9_read_command import ADVICE, BOOT

FIELDS = frozenset({"previous_boot", "previous_generation", "prior_session", "prior_label"})
LIMIT = 65536
_COMPLETE = {"completed": True, "returncode": 0, "timed_out": False}


class PreparationRefused(ValueError):
    """A closed refusal which never includes private values."""


def _need(condition: bool, field: str) -> None:
    if not condition:
        raise PreparationRefused("preparation-" + field)


def _read(path: Path, limit: int = LIMIT, field: str = "evidence") -> bytes:
    try:
        return reply._read(path, limit, "preparation-" + field)
    except reply.ReplyRefused as exc:
        raise PreparationRefused("preparation-" + field) from exc


def _object(raw: bytes) -> dict:
    try:
        return reply._object(raw, "preparation-evidence")
    except reply.ReplyRefused as exc:
        raise PreparationRefused("preparation-evidence") from exc


def _capture(captures: Path, name: str, limit: int = LIMIT) -> bytes:
    # Producer: scripts/ops/claude_read_session.py:capture writes status only
    # after run returns, and retains stderr separately. Absence is not success.
    _need(reply._same(_object(_read(captures / (name + ".status.json"))), _COMPLETE),
          "completion")
    _need(_read(captures / (name + ".stderr"), 4096) == b"", "completion")
    return _read(captures / (name + ".stdout"), limit)


def prepare_input(
    template: Path, template_sha256: str, previous_selection: Path,
    previous_selection_sha256: str, work: Path, prior_record: Path,
    prior_packet: Path, out: Path,
) -> dict:
    """Derive four facts from the real producer, then exclusively retain LF bytes.

    The caller independently selects the prior selection and template digests.
    No directory is searched, no compiler is imported or executed, and no
    interrupted output is resumed, replaced or removed.
    """
    try:
        try:
            for directory in (template.parent, previous_selection.parent, out.parent):
                reply.private_directory(directory)
        except (OSError, ValueError) as exc:
            raise PreparationRefused("preparation-custody") from exc
        raw = _read(template, field="template-unreadable")
        _need(sha(raw) == template_sha256, "template-digest")
        values = _object(raw)
        _need(raw == json_bytes(values), "template-canonical")
        selected = _object(_read(previous_selection, 2 * 1024 * 1024,
                                 "selection-unreadable"))
        try:
            host = QualificationBoundary(
                previous_selection, previous_selection_sha256,
                work / ("qualification-" + previous_selection_sha256),
                target=selected.get("target"), alias=selected.get("alias"),
            )
        except (OSError, ValueError, TypeError) as exc:
            raise PreparationRefused("preparation-selection") from exc
        _need(host.selected_pins()["consumer"] == ADVICE.id, "consumer")
        try:
            delivered = reply.collect(work, prior_record, prior_packet)
        except reply.ReplyRefused as exc:
            raise PreparationRefused("preparation-accepted-window") from exc
        _need(delivered["status"] == "delivered", "accepted-window")
        # Any current window or suspension blocks preparation, including a
        # different nonce. collect only decides this historical reply's state.
        _need(not os.path.lexists(work / "active") and not os.path.lexists(
            work / ("suspended-" + delivered["approval_sha256"])), "custody")

        challenge_raw = _read(prior_record / "challenge.json", 4096)
        challenge = _object(challenge_raw)
        qwork = work / ("qualification-" + previous_selection_sha256)
        captures = qwork / "captures"
        for directory in (qwork, captures):
            reply.private_directory(directory)
        boot_raw = _capture(captures, "boot", 64)
        boot = boot_raw.removesuffix(b"\n").decode("ascii")
        _need(BOOT.fullmatch(boot) is not None and boot != selected["previous_boot"]
              and boot_raw == (boot + "\n").encode("ascii")
              and _capture(captures, "independent-boot", 64) == boot_raw, "boot")
        live = _object(_capture(captures, "live-before-selection", 8192))
        generation = selected["previous_generation"] + 1
        _need(set(live) == {"pins", "generation", "qualification", "runtime"}
              and reply._same(live["generation"], generation)
              and live["runtime"] == selected["runtime"]
              and type(live["pins"]) is dict
              and set(live["pins"]) == {"provider_revision", "operator_binding_digest"},
              "qualification")
        pins = {**host.selected_pins()["pins"], **live["pins"]}
        _need(_capture(captures, "consumer-pins", 8192) == json_bytes(pins), "pins")
        candidate = _capture(captures, "consumer-mint", 8192)
        identity = {"target": selected["target"], "boot": boot,
                    "generation": generation, "qualification": live["qualification"]}
        # Producer: scripts/ops/m9_qualification_boundary.py:
        # QualificationBoundary.qualify builds this exact packet and identity.
        # These hashes bind selection captures to the accepted challenge.
        packet = {**live, "pins": pins, **identity, "alias": selected["alias"],
                  "selection_sha256": previous_selection_sha256,
                  "controller": selected["controller"], "authorization": host._authorization,
                  "candidate_sha256": sha(candidate)}
        _need(challenge["pins_sha256"] == sha(json_bytes(packet))
              and challenge["candidate_sha256"] == sha(candidate)
              and challenge["window_sha256"] == sha(json_bytes(identity)), "challenge")
        prepared_packet = _object(_read(prior_packet / "packet.json"))
        _need(prepared_packet["controller"] == selected["controller"]
              and delivered["summary_sha256"] == selected["consumer"]["summary_sha256"],
              "packet")
        native = work / ("native-" + sha(challenge_raw)) / "captures"
        _need(_object(_read(native / "read-original.stdout", ADVICE.original_limit))["boot"]
              == boot, "boot")

        # Producers: scripts/ops/m9_qualification_boundary.py:
        # QualificationBoundary._stage binds cleanup to the selected source;
        # QualificationBoundary.withdraw hashes the checked receipt, retained by
        # scripts/ops/m9_read_window.py:run_window's cleanup_receipt.
        cleanup = qwork / CLEANUP
        reply.private_directory(cleanup)
        source = _object(_read(cleanup / "SOURCE-PINS.json"))
        _need(source.get("selection_sha256") == previous_selection_sha256
              and _read(cleanup / "phase.sh", 128 * 1024)
              == host._templates[CLEANUP].replace(b"UNREVIEWED", boot.encode("ascii"))
              and _read(cleanup / "bindings.json") == json_bytes({
                  "boot": boot, "controller": selected["controller"], "phase": CLEANUP}),
              "cleanup-selection")
        withdrawn = _capture(captures, CLEANUP, 128)
        floor_raw = _capture(captures, "withdraw-readback", 8192)
        _need(withdrawn == f"codex-withdrawn-floor-{generation}\n".encode("ascii")
              and floor_raw == json_bytes({"key": STORE_KEY,
                                           "generation_floor": generation}), "withdrawal")
        checked = _read(captures / "withdraw-checked.json")
        _need(checked == json_bytes({"boot": boot,
              "withdrawal_receipts": [sha(withdrawn), sha(floor_raw)]})
              and _object(_read(prior_record / "withdraw.json")) == {"sha256": sha(checked)},
              "withdrawal")
        park_raw = _capture(captures, "park-usage", m8_vm_usage.MAX_SOURCE_BYTES)
        park = m8_vm_usage._parse(park_raw)
        park_checked = _read(captures / "park-checked.json")
        # Producer: scripts/ops/m9_qualification_boundary.py:
        # QualificationBoundary.check_park retains only the parsed idle report.
        _need(park["verdict"] == "idle-observed" and park_checked == json_bytes(park)
              and _object(_read(prior_record / "park.json")) == {"sha256": sha(park_checked)},
              "park")
        derived = {"previous_boot": boot, "previous_generation": generation,
                   "prior_session": selected["consumer"]["session"]["root"],
                   "prior_label": selected["consumer"]["session"]["label"]}
        output = {**values, **derived}
        output_raw = json_bytes(output)
        _need(len(output_raw) <= LIMIT, "output-bound")
        changed = sorted(key for key in derived if not reply._same(values.get(key), derived[key]))
        # All validation precedes the exclusive claim; only this file is owned.
        try:
            retain(out, output_raw)
        except FileExistsError as exc:
            raise PreparationRefused("preparation-output-occupied") from exc
        except OSError as exc:
            raise PreparationRefused("preparation-output-write") from exc
        _need(_read(out) == output_raw and b"\r" not in output_raw, "readback")
    except PreparationRefused:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        raise PreparationRefused("preparation-unproved") from exc
    return {"status": "input-prepared", "host_values_sha256": sha(output_raw),
            "previous_selection_sha256": previous_selection_sha256,
            "accepted_read_sha256": delivered["accepted_read_sha256"],
            "changed_fields": changed, "compiler_executed": False,
            "fresh_host_facts_verified": False, "execution_authorized": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("template", "previous-selection", "work", "prior-record", "prior-packet", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    parser.add_argument("--previous-selection-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_input(args.template, args.template_sha256, args.previous_selection,
                               args.previous_selection_sha256, args.work, args.prior_record,
                               args.prior_packet, args.out)
    except PreparationRefused as exc:
        parser.exit(2, f"M9 preparation refused: {exc}\n")
    sys.stdout.buffer.write(json_bytes(result))
    return 0
