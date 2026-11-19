"""Hand one checked native window back to its pinned durable batch request.

This trusted local operator composition calls no vendor. Binding files select
data, not authority; the existing collector owns private native evidence and
ControlPlane owns the fixed actor's one reply and command replay law.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from examples import change_review as source
from examples import change_review_batch as batch
from scripts.ops import change_review_batch_prepare as preparation
from scripts.ops import change_review_input as producer
from scripts.ops import change_review_reply as collector

from constructicon.api import change_review_advice as native
from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.channel import ChannelMessage
from constructicon.core.control import ControlRejected, RunResultPreviewV3, command_id_for
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import Digest, canonical_json
from constructicon.core.run import RunStatus

MAX_REPLY_BYTES = 65_536


class HandbackRefused(RuntimeError):
    """Preserve an affirmative Core refusal without private fault details."""

    def __init__(self, outcome: ControlRejected) -> None:
        self.response = {
            "status": "refused", "reason": "batch_reply_rejected", "partial": False,
            "fault_codes": [fault.code.value for fault in outcome.faults],
        }
        super().__init__(json.dumps(self.response))


class HandbackUnverified(RuntimeError):
    """A dispatched command cannot be described as a preflight refusal."""

    def __init__(self, reason: str, selection: dict[str, Any], reply: Any = None) -> None:
        super().__init__(reason)
        self.response = {
            "status": "unverified", "reason": reason, "partial": True,
            "root_run_id": selection["root_run_id"], "file_id": selection["file_id"],
            "request_id": selection["request_id"],
            "reply_command": None if reply is None else reply.model_dump(mode="json"),
            "next_action": "Inspect retained batch state; replay only the original key and inputs.",
        }


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _prepared(path: Path, expected: str) -> tuple[dict[str, Any], dict[str, bytes], Any]:
    """Read bounded private inputs and verify the explicitly selected raw pin."""
    _require(re.fullmatch(r"[0-9a-f]{64}", expected) is not None, "batch_binding_pin_invalid")
    _require(path.name == "binding.json", "batch_binding_path_invalid")
    collector._private(path.parent, "batch_binding_private")
    raw = collector._read(path, preparation.BINDING_LIMIT, "batch_binding_invalid")
    _require(hashlib.sha256(raw).hexdigest() == expected, "batch_binding_pin_mismatch")
    try:
        binding = json.loads(raw)
        _require(isinstance(binding, dict) and set(binding) == preparation.BINDING_FIELDS,
                 "batch_binding_invalid")
        _require(type(binding["schema_version"]) is int and binding["schema_version"] == 1,
                 "batch_binding_invalid")
        _require(all(isinstance(binding[name], str) for name in (
            "root_run_id", "manifest_hash", "input_hash", "file_id", "request_id",
            "request_sha256",
        )), "batch_binding_invalid")
        _require(isinstance(binding["before_ref"], dict) and isinstance(binding["after_ref"], dict),
                 "batch_binding_invalid")
        pins = binding["packet_sha256"]
        _require(isinstance(pins, dict) and set(pins) == set(preparation.PACKET_FILES),
                 "batch_packet_pin_invalid")
        _require(all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                     for value in pins.values()), "batch_packet_pin_invalid")
        packet = {
            name: collector._read(path.parent / name, collector.PACKET_LIMIT,
                                  "batch_packet_invalid")
            for name in preparation.PACKET_FILES
        }
        _require(all(hashlib.sha256(packet[name]).hexdigest() == pins[name] for name in packet),
                 "batch_packet_pin_mismatch")
        _record, bound = collector._packet(packet["packet.json"], packet["summary.json"],
                                           packet["instruction.txt"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("batch_binding_invalid") from error
    return binding, packet, bound


async def handback(
    system: Constructicon, control: ControlPlane, *, binding_file: Path, binding_sha256: str,
    work: Path, record: Path, key: str,
) -> dict[str, Any]:
    """Validate first, then delegate the sole mutation to existing command law."""
    binding, packet, bound = _prepared(binding_file, binding_sha256)
    run_id = RunId(binding["root_run_id"])
    file_id = binding["file_id"]
    selected = preparation.select_binding(system, control, run_id, file_id,
                                           require_unanswered=False)
    _require(canonical_json({name: binding[name] for name in preparation.STABLE_FIELDS})
             == canonical_json(selected), "batch_binding_selection_mismatch")

    # The existing collector reads the closed window's own private custody,
    # capture and cleanup records. Never accept a caller's 'delivered' JSON.
    delivered = collector.collect(work, record, binding_file.parent)
    _require(delivered["status"] == "delivered", "batch_native_not_delivered")
    before, after = selected["before_ref"], selected["after_ref"]
    _require(canonical_json(delivered["change"]) == canonical_json({
        "before": before["commit"], "after": after["commit"], "path": before["paths"][0],
    }), "batch_native_change_mismatch")
    _require(delivered["summary_sha256"] == binding["packet_sha256"]["summary.json"]
             and delivered["instruction_digest"] == str(bound.instruction_digest)
             and delivered["run_id"] == str(bound.run_id), "batch_native_binding_mismatch")
    advice = native.ModelAdvicePayload.model_validate(delivered["advice"])
    _require(advice.instruction_digest == bound.instruction_digest,
             "batch_native_binding_mismatch")
    _require(len(advice.advice.encode("utf-8")) <= batch.MAX_ADVICE_BYTES,
             "batch_native_advice_too_large")
    # Join the collector's result to the exact packet bytes selected above,
    # while retaining the collector's existing trusted-private-input contract.
    _require(all(hashlib.sha256(collector._read(
        binding_file.parent / name, collector.PACKET_LIMIT, "batch_packet_invalid",
    )).hexdigest() == hashlib.sha256(raw).hexdigest() for name, raw in packet.items()),
        "batch_packet_changed")

    request_summary = source.checked(control.channels_message(
        source.OPERATOR, Digest(selected["request_id"]),
    ))
    request = ChannelMessage.model_validate(batch.read_detail(control, request_summary.detail))
    answered = batch._reply_for(control, request) is not None
    if answered:
        # Positive existing command evidence permits Core to distinguish exact
        # replay from a conflicting use of this key. Unknown keys cannot add a
        # new rejected command merely to discover an already answered request.
        known = control.commands_status(source.OPERATOR, command_id_for(
            source.OPERATOR.actor_id, "channels_reply", key,
        ))
        _require(not isinstance(known, ControlRejected), "batch_request_answered")
    else:
        status = source.checked(control.runs_status(source.OPERATOR, run_id))
        _require(status.status not in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED},
                 "batch_run_terminal")

    try:
        outcome = await control.channels_reply(
            source.OPERATOR, message_id=Digest(selected["request_id"]), payload=advice.advice,
            idempotency_key=key,
        )
    except Exception as error:
        raise HandbackUnverified("batch_reply_outcome_unverified", selected) from error
    # A typed Core refusal is affirmative; an exception during dispatch is not.
    if isinstance(outcome, ControlRejected):
        raise HandbackRefused(outcome)
    reply = outcome
    try:
        settled = await batch.wait_for_settlement(system, control, run_id, file_id=file_id)
        result = source.checked(control.runs_result(source.OPERATOR, run_id))
        _require(isinstance(result, RunResultPreviewV3), "batch_root_result_invalid")
        response = {
            "schema_version": 1, "file_id": file_id, "request_id": selected["request_id"],
            "binding_sha256": binding_sha256, "reply_command": reply.model_dump(mode="json"),
            "wait_status": "settled" if settled else "timed_out", "partial": not settled,
            "batch_root": {"run_id": str(run_id), "status": result.status.value,
                           "metering": result.metering.model_dump(mode="json")},
            "native_window": {name: delivered[name] for name in (
                "run_id", "window", "accepted_read_sha256", "approval_sha256", "approval_slot",
                "summary_sha256", "instruction_digest", "metering",
            )},
            "usage_relation": "separate_not_attributed",
        }
        _require(len(producer._wire(response)) <= MAX_REPLY_BYTES,
                 "batch_bridge_response_unbounded")
        return response
    except Exception as error:
        reason = ("batch_bridge_response_unbounded"
                  if str(error) == "batch_bridge_response_unbounded"
                  else "batch_handback_reporting_unverified")
        raise HandbackUnverified(reason, selected, reply) from error


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    db = args.state / "review.db"
    _require(db.is_file(), "review_store_missing")
    system, control = source.assemble(db)
    try:
        return await handback(system, control, binding_file=args.binding,
                              binding_sha256=args.binding_sha256, work=args.work,
                              record=args.record, key=args.key)
    finally:
        await control.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args(argv)
    try:
        response = asyncio.run(execute(args))
    except HandbackRefused as error:
        sys.stdout.buffer.write(producer._wire(error.response))
        return 1
    except HandbackUnverified as error:
        sys.stdout.buffer.write(producer._wire(error.response))
        return 1
    except (OSError, ValueError, RuntimeError, ContractViolation) as error:
        # No private path, advice, native capture or account data in diagnostics.
        reason = str(error).partition(":")[0]
        refused = isinstance(error, ValueError) and re.fullmatch(
            r"batch_[a-z_]+|review_store_missing", reason,
        ) is not None
        if isinstance(error, collector.ReplyRefused):
            reason = error.code
            refused = True
        elif not refused:
            reason = "batch_handback_unproved"
        # Unexpected failures (including shutdown) cannot prove no mutation.
        sys.stdout.buffer.write(producer._wire({
            "status": "refused" if refused else "unverified", "reason": reason,
            "partial": not refused,
        }))
        return 1
    sys.stdout.buffer.write(producer._wire(response))
    if response["batch_root"]["status"] in {"failed", "cancelled"}:
        return 1
    return 2 if response["partial"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
