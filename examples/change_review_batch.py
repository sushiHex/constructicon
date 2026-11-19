"""Review at most sixteen explicitly selected committed Python files durably.

This trusted local entry composes the existing single-file review graph. It
executes no submitted source, calls no model, and keeps all durable authority
in the existing journal and ControlPlane. Status never starts recovery workers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from constructicon.api import Constructicon
from constructicon.api.control import ControlPlane
from constructicon.api.detail import MAX_DETAIL_BYTES as MAX_DETAIL_CHUNK_BYTES
from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.channel import ChannelMessage, reply_message_id, request_message_id
from constructicon.core.control import (
    ChannelMessageSummary,
    ControlCode,
    ControlRejected,
    DetailRef,
    EventSummary,
    RunResultPreviewV3,
    RunSubmission,
)
from constructicon.core.errors import ContractViolation
from constructicon.core.graph import Graph, GraphNode
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.manifest import ExecutionManifest
from constructicon.core.run import RunStatus
from examples.change_review import (
    ADVICE_REPLY,
    ADVISOR_COMPONENT,
    ANALYSIS,
    CHANGE,
    CHANNEL_ID,
    OPERATOR,
    ReviewInput,
    assemble,
    checked,
    committed_source,
    compare_sources,
    register,
    review_graph,
)

MAX_FILES = 16
MAX_RESPONSE_BYTES = 256 * 1024
MAX_DETAIL_BYTES = 4 * 1024 * 1024
MAX_OBSERVATIONS = 10_000
MAX_ADVICE_BYTES = 4_096
WAIT_SECONDS = 180.0
POLL_SECONDS = 1.0
ROOT_NAME = "python-change-review-batch"
PREPARE_COMPONENT = "example/prepare-python-review"


def file_identity(repository: str, path: str) -> str:
    """A file's identity survives changes to its commits and batch position."""
    return "file_" + str(
        digest(
            "example-review-batch-file",
            1,
            {
                "repository": repository,
                "path": path,
            },
        )
    ).removeprefix("sha256:")


def prepare_batch(
    repository: Path,
    before_commit: str,
    after_commit: str,
    paths: Sequence[str],
) -> dict[str, ReviewInput]:
    """Validate every immutable blob before opening any application state."""
    if not 1 <= len(paths) <= MAX_FILES:
        raise ValueError(f"batch_file_count_invalid: select between 1 and {MAX_FILES} files")
    if len(set(paths)) != len(paths):
        raise ValueError("batch_path_duplicate: select each path once")
    if len(str(repository.resolve()).encode("utf-8")) > 4_096:
        raise ValueError("batch_repository_unbounded: repository locator exceeds 4096 bytes")
    changes = {}
    for path in sorted(paths):
        before_ref, before = committed_source(repository, before_commit, path)
        after_ref, after = committed_source(repository, after_commit, path)
        identity = file_identity(before_ref.repository, path)
        if identity in changes:
            raise ValueError("batch_file_identity_collision: distinct paths have one identity")
        changes[identity] = ReviewInput(
            **compare_sources(before, after).model_dump(),
            before_ref=before_ref,
            after_ref=after_ref,
        )
    return changes


def batch_graph(versions: Mapping[str, Digest], files: Mapping[str, ReviewInput]) -> Graph:
    """Rename boundaries only; each child remains the existing review_graph."""
    nodes = []
    inputs = []
    outputs = []
    for identity in sorted(files, key=lambda key: files[key].after_ref.paths[0]):
        incoming = CHANGE.model_copy(update={"name": f"change_{identity}"})
        analysis = ANALYSIS.model_copy(update={"name": f"analysis_{identity}"})
        advice = ADVICE_REPLY.model_copy(update={"name": f"advice_{identity}"})
        child = review_graph(versions).model_copy(
            update={
                "inputs": (incoming,),
                "outputs": (analysis, advice),
            }
        )
        nodes.append(GraphNode(id=identity, body=child))
        inputs.append(incoming)
        outputs.extend((analysis, advice))
    return Graph(name=ROOT_NAME, nodes=tuple(nodes), inputs=tuple(inputs), outputs=tuple(outputs))


def read_detail(control: ControlPlane, reference: DetailRef) -> Any:
    """Follow public digest-bound cursors, with a cumulative UTF-8 byte limit."""
    cursor = None
    parts = []
    consumed = 0
    while True:
        chunk = checked(
            control.details_read(
                OPERATOR,
                reference,
                cursor=cursor,
                max_bytes=MAX_DETAIL_CHUNK_BYTES,
            )
        )
        if chunk.total_bytes > MAX_DETAIL_BYTES:
            raise ValueError("batch_detail_bytes_exceeded: detail exceeds the 4 MiB read limit")
        raw = chunk.text.encode("utf-8")
        if (
            chunk.uri != reference.uri
            or chunk.digest != reference.digest
            or chunk.offset != consumed
            or consumed + len(raw) > MAX_DETAIL_BYTES
        ):
            raise ValueError(
                "batch_detail_invalid: detail chunks contradict their reference or offset"
            )
        parts.append(chunk.text)
        consumed += len(raw)
        cursor = chunk.next_cursor
        if cursor is None:
            if consumed != chunk.total_bytes:
                raise ValueError(
                    "batch_detail_invalid: detail ended before its declared byte count"
                )
            return json.loads("".join(parts))


def retained_batch(
    system: Constructicon,
    control: ControlPlane,
    run_id: RunId,
) -> tuple[dict[str, ReviewInput], ExecutionManifest]:
    """Recover mapping from public durable inputs, including a prepared command.

    The trusted local transport owns this assembled system. inputs_for_run is
    its existing public read API; using it avoids a second ledger and still
    works before the first RunStarted event or command completion exists.
    Every mutation continues through ControlPlane.
    """
    summary = checked(control.runs_status(OPERATOR, run_id))
    # Public local reads avoid re-resolving the entire manifest on every
    # 16 KiB detail page. The seal still comes from the authorized summary.
    manifest = system.manifest_for_run(run_id)
    if len(canonical_json(manifest).encode("utf-8")) > MAX_DETAIL_BYTES:
        raise ValueError("batch_detail_bytes_exceeded: manifest exceeds the 4 MiB read limit")
    inputs = system.inputs_for_run(run_id)
    if (
        digest("inputs", 1, inputs) != summary.input_hash
        or manifest.input_hash != summary.input_hash
        or manifest.manifest_hash != summary.manifest_hash
    ):
        raise ValueError("batch_inputs_invalid: retained inputs contradict the sealed run")
    if not 1 <= len(inputs) <= MAX_FILES:
        raise ValueError("batch_membership_invalid: run does not contain a bounded review batch")
    files = {}
    subject = None
    for name, raw in inputs.items():
        change = ReviewInput.model_validate(raw)
        before, after = change.before_ref, change.after_ref
        if (
            len(before.paths) != 1
            or before.paths != after.paths
            or before.repository != after.repository
        ):
            raise ValueError(
                "batch_membership_invalid: each review must select one consistent file"
            )
        path = before.paths[0]
        # Enforce the same path boundary without reading the repository again.
        if (
            not path
            or len(path) > 200
            or path.startswith("/")
            or ":" in path
            or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise ValueError("batch_membership_invalid: retained path is not canonical")
        current = (before.repository, before.commit, after.commit)
        if subject is not None and current != subject:
            raise ValueError("batch_membership_invalid: reviews do not share a commit pair")
        subject = current
        identity = file_identity(before.repository, path)
        if name != f"change_{identity}" or identity in files:
            raise ValueError("batch_membership_invalid: retained input has the wrong file identity")
        files[identity] = change
    versions = {}
    for resolution in manifest.resolved_components:
        previous = versions.setdefault(resolution.component, resolution.resolved_version)
        if previous != resolution.resolved_version:
            raise ValueError("batch_membership_invalid: review children use inconsistent pins")
    if set(versions) != {PREPARE_COMPONENT, ADVISOR_COMPONENT}:
        raise ValueError(
            "batch_membership_invalid: run contains components outside the review batch"
        )
    if canonical_json(batch_graph(versions, files)) != canonical_json(manifest.source_graph):
        raise ValueError("batch_membership_invalid: run is not the exact review batch composition")
    return dict(sorted(files.items(), key=lambda item: item[1].after_ref.paths[0])), manifest


def events_for(control: ControlPlane, run_id: RunId) -> tuple[list[EventSummary], int, bool]:
    cursor = None
    events = []
    through = 0
    while True:
        page = checked(control.runs_events(OPERATOR, run_id, cursor=cursor, limit=100))
        through = page.through_seq
        events.extend(page.items)
        cursor = page.page.next_cursor
        if cursor is None:
            return events, through, False
        if len(events) >= MAX_OBSERVATIONS:
            return events, through, True


def requests_for(
    control: ControlPlane,
    run_id: RunId,
    files: Mapping[str, ReviewInput],
    manifest: ExecutionManifest,
) -> tuple[dict[str, tuple[ChannelMessageSummary, ChannelMessage]], bool]:
    """At most one addressed lookup per file, independent of inbox history."""
    requests: dict[str, tuple[ChannelMessageSummary, ChannelMessage]] = {}
    for identity, change in files.items():
        bindings = [
            binding
            for binding in manifest.capability_bindings
            if binding.scope.segments == (ROOT_NAME, identity, "review")
            and binding.capability_id == CHANNEL_ID
            and binding.channel is not None
        ]
        if len(bindings) != 1:
            raise ValueError("batch_request_invalid: file has no unique sealed advisor channel")
        binding = bindings[0]
        channel = binding.channel
        assert channel is not None
        path = ExecutionPath(scope=binding.scope)
        # This is the same identity function the producer uses in
        # runtime/walker.py:208 (_intent), never a second ID law.
        message_id = request_message_id(
            run_id=run_id,
            path=path,
            channel_id=binding.capability_id,
            channel_revision=binding.revision,
            lane=channel.endpoint.lane,
            interaction=channel.endpoint.interaction,
            port=channel.port,
        )
        item = control.channels_message(OPERATOR, message_id)
        if isinstance(item, ControlRejected):
            if len(item.faults) == 1 and item.faults[0].code is ControlCode.CHANNEL_MESSAGE_UNKNOWN:
                continue
            checked(item)
        message = ChannelMessage.model_validate(read_detail(control, item.detail))
        expected = change.model_dump(mode="json")
        if (
            message.envelope.run_id != run_id
            or message.envelope.path != path
            or message.kind != "request"
            or message.channel_id != CHANNEL_ID
            or canonical_json(message.envelope.payload)
            != canonical_json(
                {
                    "question": "What tests or follow-up does this change need?",
                    "analysis": expected,
                }
            )
        ):
            raise ValueError(
                "batch_request_invalid: request does not match its retained file input"
            )
        requests[identity] = (item, message)
    return requests, False


def _reply_for(
    control: ControlPlane,
    request: ChannelMessage,
) -> tuple[ChannelMessageSummary, ChannelMessage] | None:
    if request.reply_port is None:
        raise ValueError("batch_request_invalid: advice request has no pinned reply port")
    identity = reply_message_id(request_id=request.message_id, reply_port=request.reply_port)
    summary = control.channels_message(OPERATOR, identity)
    if isinstance(summary, ControlRejected):
        if (
            len(summary.faults) == 1
            and summary.faults[0].code is ControlCode.CHANNEL_MESSAGE_UNKNOWN
        ):
            return None
        checked(summary)
    message = ChannelMessage.model_validate(read_detail(control, summary.detail))
    if (
        message.kind != "reply"
        or message.reply_to != request.message_id
        or message.envelope.run_id != request.envelope.run_id
        or message.envelope.path != request.envelope.path
    ):
        raise ValueError("batch_reply_invalid: retained reply contradicts its request")
    return summary, message


def bounded_response(response: dict[str, Any]) -> dict[str, Any]:
    """Omit payloads explicitly when the public response limit binds."""
    # main prints one trailing LF; it is part of the public byte bound too.
    if len(canonical_json(response).encode("utf-8")) + 1 <= MAX_RESPONSE_BYTES:
        return response
    response["partial"] = True
    response["limitations"].append(
        "batch_response_bytes_exceeded: payloads omitted; follow detail references"
    )
    for item in response["files"]:
        for field in ("analysis", "advice"):
            if item[field] is not None:
                item[field] = None
                item.setdefault("omitted", []).append(field)
    if len(canonical_json(response).encode("utf-8")) + 1 > MAX_RESPONSE_BYTES:
        raise ValueError("batch_response_unbounded: metadata exceeds the 256 KiB response limit")
    return response


def observe(system: Constructicon, control: ControlPlane, run_id: RunId) -> dict[str, Any]:
    files, manifest = retained_batch(system, control, run_id)
    events, through, events_partial = events_for(control, run_id)
    requests, inbox_partial = requests_for(control, run_id, files, manifest)
    result = checked(control.runs_result(OPERATOR, run_id))
    assert isinstance(result, RunResultPreviewV3)
    response: dict[str, Any] = {
        "schema_version": 1,
        "run_id": str(run_id),
        "mapping_status": "complete",
        "partial": events_partial or inbox_partial,
        "limitations": [],
        "through_event_seq": through,
        "files": [],
        "result": result.model_dump(mode="json"),
    }
    if events_partial:
        response["limitations"].append("batch_events_partial: observation limit reached")
    if inbox_partial:
        response["limitations"].append("batch_inbox_partial: observation limit reached")
    outputs = {}
    if result.status is RunStatus.SUCCEEDED and result.detail is not None:
        outputs = read_detail(control, result.detail)["outputs"]
    for identity, change in files.items():
        prefix = f"{ROOT_NAME}/{identity}/"
        relevant = [event for event in events if event.path and event.path.startswith(prefix)]
        completed = any(
            event.path == prefix + "review"
            and event.kind
            in {
                "NodeCompleted",
                "NodeRestored",
            }
            for event in relevant
        )
        inspected = any(
            event.path == prefix + "inspect" and event.kind in {"NodeCompleted", "NodeRestored"}
            for event in relevant
        )
        failures = [
            event.payload
            for event in relevant
            if event.kind == "NodeFailed" and event.payload is not None
        ]
        request_pair = requests.get(identity)
        reply_pair = _reply_for(control, request_pair[1]) if request_pair else None
        status = "unknown" if events_partial else "pending"
        if request_pair is not None:
            status = "awaiting_advice"
            if any(
                event.kind == "NodeParked" and event.path == prefix + "review" for event in relevant
            ):
                status = "parked"
        if reply_pair is not None:
            status = "reply_recorded"
        if result.status in {RunStatus.FAILED, RunStatus.CANCELLED}:
            status = "not_completed"
        if failures:
            status = "failed"
        if completed or result.status is RunStatus.SUCCEEDED:
            status = "succeeded"
        response["files"].append(
            {
                "file_id": identity,
                "path": change.after_ref.paths[0],
                "before_ref": change.before_ref.model_dump(mode="json"),
                "after_ref": change.after_ref.model_dump(mode="json"),
                "status": status,
                "analysis": outputs.get(f"analysis_{identity}", change.model_dump(mode="json")),
                "analysis_provenance": (
                    "completed_output"
                    if inspected or result.status is RunStatus.SUCCEEDED
                    else "sealed_preflight"
                ),
                "request": request_pair[0].model_dump(mode="json") if request_pair else None,
                "reply": reply_pair[0].model_dump(mode="json") if reply_pair else None,
                "advice": outputs.get(
                    f"advice_{identity}", (reply_pair[1].envelope.payload if reply_pair else None)
                ),
                "failures": failures,
                "usage": {
                    "coverage": "unknown",
                    "reason": "run metering is not attributed per file",
                },
            }
        )
    return bounded_response(response)


async def wait_for_settlement(
    system: Constructicon,
    control: ControlPlane,
    run_id: RunId,
    *,
    file_id: str | None = None,
) -> bool:
    """Observe bounded settlement without repeatedly rendering manifest details.

    run_state is the existing public durable projection (api/system.py:539),
    including journal-derived liveness. Its read still validates the run, so
    coarse polling gives the existing worker time between observations.
    """
    deadline = asyncio.get_running_loop().time() + WAIT_SECONDS
    path = f"{ROOT_NAME}/{file_id}/review" if file_id is not None else None
    while True:
        state = system.run_state(run_id)
        if state is None:
            raise ValueError("batch_run_unknown: admitted run has no durable state")
        if state.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return True
        if state.status is RunStatus.PARKED:
            if path is None:
                return True
            # Read target evidence only after parking. A reply may initially
            # observe the old PARKED state before its worker starts; it must
            # not return until the target completed and the root settled.
            events, _through, partial = events_for(control, run_id)
            settled = any(
                event.path == path
                and event.kind
                in {
                    "NodeCompleted",
                    "NodeRestored",
                    "NodeFailed",
                }
                for event in events
            )
            if settled:
                # Join the current root transition after the event read, as a
                # node checkpoint itself precedes terminal/parking closure.
                current = system.run_state(run_id)
                if current is not None and current.status in {
                    RunStatus.PARKED,
                    RunStatus.SUCCEEDED,
                    RunStatus.FAILED,
                    RunStatus.CANCELLED,
                }:
                    return True
            if partial:
                return False
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(POLL_SECONDS, remaining))


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    files = None
    if args.command == "submit":
        files = prepare_batch(args.repository, args.before_commit, args.after_commit, args.path)
    elif args.command == "reply" and len(args.advice.encode("utf-8")) > MAX_ADVICE_BYTES:
        raise ValueError("batch_advice_bytes_exceeded: advice exceeds 4096 UTF-8 bytes")
    db = args.state / "review.db"
    if files is None and not db.is_file():
        raise ValueError("review_store_missing: submit a review batch first")
    if files is not None:
        args.state.mkdir(parents=True, exist_ok=True)
    system, control = assemble(db)
    submission = None
    reply = None
    settled = None
    try:
        if files is not None:
            # Discover the assembled vocabulary; exact retained refs need no
            # stable promotion. The existing two definitions are all we use.
            system.describe()
            versions = await register(control)
            submission = checked(
                await control.runs_start(
                    OPERATOR,
                    proposal=batch_graph(versions, files),
                    inputs={
                        f"change_{identity}": change.model_dump(mode="json")
                        for identity, change in files.items()
                    },
                    idempotency_key=args.key,
                )
            )
            if not isinstance(submission, RunSubmission):
                raise ValueError(f"batch_admission_rejected: {submission.model_dump_json()}")
            run_id = submission.run_id
            settled = await wait_for_settlement(system, control, run_id)
        else:
            run_id = RunId(args.run_id)
        if args.command == "reply":
            retained, manifest = retained_batch(system, control, run_id)
            if args.file_id not in retained:
                raise ValueError("batch_file_unknown: select a file_id returned by this batch")
            requests, partial = requests_for(
                control, run_id, {args.file_id: retained[args.file_id]}, manifest,
            )
            request = requests.get(args.file_id)
            if request is None:
                code = "batch_inbox_partial" if partial else "batch_request_missing"
                raise ValueError(f"{code}: no retained request was observed for this file")
            # Keep answered requests actionable here: ControlPlane must decide
            # same-key replay versus changed-key/already-replied conflict.
            reply = checked(
                await control.channels_reply(
                    OPERATOR,
                    message_id=request[0].message_id,
                    payload=args.advice,
                    idempotency_key=args.key,
                )
            )
            settled = await wait_for_settlement(system, control, run_id, file_id=args.file_id)
        response = observe(system, control, run_id)
        if submission is not None:
            response["submission"] = submission.model_dump(mode="json")
        if reply is not None:
            response["reply"] = reply.model_dump(mode="json")
        if settled is not None:
            response["wait_status"] = "settled" if settled else "timed_out"
            if not settled:
                response["partial"] = True
                response["limitations"].append(
                    "batch_wait_timeout: durable run retained; inspect status or replay the "
                    "original command with the same key"
                )
        return bounded_response(response)
    finally:
        await control.shutdown()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    submit = commands.add_parser(
        "submit", help="compare explicit committed files and park for advice"
    )
    submit.add_argument("--repository", type=Path, required=True)
    submit.add_argument("--before-commit", required=True)
    submit.add_argument("--after-commit", required=True)
    submit.add_argument("--path", action="append", required=True)
    submit.add_argument("--key", required=True)
    status = commands.add_parser("status", help="read retained state without starting recovery")
    status.add_argument("--run-id", required=True)
    reply = commands.add_parser(
        "reply", help="advise one retained file as the fixed local operator"
    )
    reply.add_argument("--run-id", required=True)
    reply.add_argument("--file-id", required=True)
    reply.add_argument("--advice", required=True)
    reply.add_argument("--key", required=True)
    try:
        response = asyncio.run(execute(parser.parse_args(argv)))
        # Write the protocol bytes directly: a Windows text wrapper may expand
        # LF to CRLF and violate the byte bound checked by bounded_response.
        sys.stdout.buffer.write((canonical_json(response) + "\n").encode("utf-8"))
        if response["result"]["status"] in {"failed", "cancelled"}:
            return 1
        return 2 if response.get("wait_status") == "timed_out" else 0
    except ContractViolation as exc:
        print(
            json.dumps({"error": str(exc), "refusal": [str(code) for code in exc.refusal]}),
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
