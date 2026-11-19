"""Prepare one explicit durable batch request offline, without execution authority.

The extra binding is prepared input, not a ledger or permission. The original
three consumer files retain their existing producer and byte representation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from examples import change_review as source
from examples import change_review_batch as batch
from scripts.ops import change_review_input as consumer

from constructicon.api import Constructicon
from constructicon.api.control import ControlPlane
from constructicon.core.address import RunId
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import canonical_json
from constructicon.core.run import RunStatus

STABLE_FIELDS = frozenset({
    "schema_version", "root_run_id", "manifest_hash", "input_hash", "file_id",
    "request_id", "request_sha256", "before_ref", "after_ref",
})
BINDING_FIELDS = STABLE_FIELDS | {"packet_sha256"}
BINDING_LIMIT = 65_536
PACKET_FILES = ("packet.json", "summary.json", "instruction.txt")


def select_binding(
    system: Constructicon, control: ControlPlane, run_id: RunId, file_id: str,
    *, require_unanswered: bool = True,
) -> dict:
    """Read exact sealed membership and request; never recover or mutate a run.

    No lifecycle revision enters the binding: progress of another file does not
    change this immutable selection. ControlPlane owns reply race/replay rules.
    """
    files, manifest = batch.retained_batch(system, control, run_id)
    if file_id not in files:
        raise ValueError("batch_file_unknown: select one retained file_id")
    change = files[file_id]
    if len(change.before_ref.repository.encode("utf-8")) > 4_096:
        raise ValueError("batch_repository_unbounded: retained locator exceeds 4096 bytes")
    requests, partial = batch.requests_for(control, run_id, {file_id: change}, manifest)
    if partial or file_id not in requests:
        raise ValueError("batch_request_missing: selected file has no current exact request")
    summary, request = requests[file_id]
    if require_unanswered:
        status = source.checked(control.runs_status(source.OPERATOR, run_id))
        if status.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            raise ValueError("batch_run_terminal: preparation requires a live request")
        if batch._reply_for(control, request) is not None:
            raise ValueError("batch_request_answered: select an unanswered request")
    return {
        "schema_version": 1,
        "root_run_id": str(run_id),
        "manifest_hash": str(manifest.manifest_hash),
        "input_hash": str(manifest.input_hash),
        "file_id": file_id,
        "request_id": str(summary.message_id),
        "request_sha256": hashlib.sha256(canonical_json(request).encode("utf-8")).hexdigest(),
        "before_ref": change.before_ref.model_dump(mode="json"),
        "after_ref": change.after_ref.model_dump(mode="json"),
    }


def prepare_batch_input(
    system: Constructicon, control: ControlPlane, *, run_id: RunId, file_id: str,
    controller: str, controller_repository: Path, out: Path,
) -> dict:
    """Re-read real source, verify retained V1, then call the actual V2 producer."""
    binding = select_binding(system, control, run_id, file_id)
    before, after = binding["before_ref"], binding["after_ref"]
    repository, path = Path(before["repository"]), before["paths"][0]
    try:
        before_ref, left = source.committed_source(repository, before["commit"], path)
        after_ref, right = source.committed_source(repository, after["commit"], path)
    except (OSError, ValueError) as error:
        raise ValueError("batch_source_unreadable: exact retained source cannot be read") from error
    regenerated = source.ReviewInput(
        **source.compare_sources(left, right).model_dump(),
        before_ref=before_ref, after_ref=after_ref,
    )
    retained, _manifest = batch.retained_batch(system, control, run_id)
    if (before_ref.model_dump(mode="json") != before
            or after_ref.model_dump(mode="json") != after
            or canonical_json(regenerated) != canonical_json(retained[file_id])):
        raise ValueError("batch_source_mismatch: source does not reproduce the retained input")
    # This preserves the existing source checks, V2 producer, pins and exclusive
    # directory claim. The target repository need not contain controller objects.
    consumer.prepare(repository, controller, before["commit"], after["commit"], path, out,
                     controller_repository=controller_repository)
    binding["packet_sha256"] = {
        name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in PACKET_FILES
    }
    raw = consumer._wire(binding)
    if len(raw) > BINDING_LIMIT:
        raise ValueError("batch_binding_unbounded: prepared binding exceeds 65536 bytes")
    with (out / "binding.json").open("xb") as stream:
        stream.write(raw)
    return binding


async def execute(args: argparse.Namespace) -> dict:
    db = args.state / "review.db"
    if not db.is_file():
        raise ValueError("review_store_missing: submit a review batch first")
    system, control = source.assemble(db)
    try:
        binding = prepare_batch_input(
            system, control, run_id=RunId(args.run_id), file_id=args.file_id,
            controller=args.controller, controller_repository=args.controller_repository,
            out=args.out,
        )
        return {"status": "prepared", "binding_sha256": hashlib.sha256(
            (args.out / "binding.json").read_bytes()).hexdigest(),
            "file_id": binding["file_id"], "execution_authorized": False}
    finally:
        await control.shutdown()


def main(argv: list[str] | None = None) -> int:
    import asyncio

    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--file-id", required=True)
    parser.add_argument("--controller", required=True)
    parser.add_argument("--controller-repository", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        response = asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, ContractViolation) as error:
        # A closed code only: underlying exceptions can carry private locators.
        code = str(error).partition(":")[0]
        if not code.startswith("batch_") and code != "review_store_missing":
            code = "batch_preparation_unproved"
        print(json.dumps({"status": "refused", "reason": code}))
        return 1
    sys.stdout.buffer.write(consumer._wire(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
