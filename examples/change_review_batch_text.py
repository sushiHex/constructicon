"""Bounded terminal text derived solely from an already-built batch response."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

MAX_REPORT_BYTES = 256 * 1024
MAX_FIELD_BYTES = 4 * 1024
MAX_FILE_BLOCK_BYTES = 12 * 1024


def _json(value: Any) -> str:
    # Quoting every data value also escapes ANSI, line controls, bidi controls,
    # and non-ASCII paths. Data can never manufacture another report line.
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def render_batch_text(response: Mapping[str, Any]) -> str:
    """Render retained machine facts; perform no reads, advice parsing or effects.

    Each optional file block has a 12 KiB budget. Identity/status precede these
    blocks so large advice cannot hide another file, root metering, or recovery
    guidance. Individual metadata values are bounded too; omissions are named.
    The final UTF-8 bound includes its LF, just like the JSON entry.
    """
    omissions: list[str] = []

    def data(value: Any) -> str:
        encoded = _json(value)
        size = len(encoded.encode("utf-8"))
        if size <= MAX_FIELD_BYTES:
            return encoded
        omissions.append("batch_text_field_bytes_exceeded")
        return _json({"omitted": "batch_text_field_bytes_exceeded", "encoded_bytes": size})

    result = response["result"]
    status = result["status"]
    first = response["files"][0]
    lines = [
        "Change review batch",
        "succeeded means workflow recorded; it does not establish correctness or merge approval.",
        "Structural facts compare public top-level definitions only; no tests were executed.",
        f"root_run_id: {data(response['run_id'])}",
        f"before_commit: {data(first['before_ref']['commit'])}",
        f"after_commit: {data(first['after_ref']['commit'])}",
        f"status: {data(status)}",
        f"through_event_seq: {data(response['through_event_seq'])}",
        f"partial: {data(response['partial'])}",
        f"mapping_status: {data(response['mapping_status'])}",
        f"wait_status: {data(response.get('wait_status'))}",
        "A null wait_status means no wait was requested.",
        f"limitations: {data(response['limitations'])}",
        f"failures_partial: {data(result['failures_partial'])}",
        f"root_failures: {data(result['failures'])}",
    ]
    for name in ("submission", "reply"):
        if name in response:
            lines.append(f"{name}_command_id: {data(response[name]['command']['command_id'])}")
            lines.append(f"{name}_replayed: {data(response[name]['command']['replayed'])}")
    if response["partial"] or result["failures"] or result["failures_partial"]:
        lines.append(f"result_detail: {data(result['detail'])}")
    if response.get("wait_status") == "timed_out":
        action = (
            "Inspect status with the retained root_run_id; to recover, retry the original "
            "mutation with its identical arguments and original key. Timeout did not cancel it."
        )
    elif status in {"failed", "cancelled"}:
        action = "Inspect status, failures and retained detail."
    elif status == "succeeded":
        action = (
            "Review the retained facts and untrusted advice; status reads do not start workers."
        )
    else:
        action = (
            "Inspect status; reply only to a returned file_id with an unanswered retained request. "
            "Retry an interrupted mutation only with its identical arguments and original key; "
            "status reads do not start workers."
        )
    lines.append(f"next_action: {action}")
    metering = result["metering"]
    lines.extend([
        "root_metering:",
        "Source-scoped known subtotals at the metering cut, once per root.",
        f"metering_coverage: {data(metering['coverage'])}",
        f"metering_through_event_seq: {data(metering['through_event_seq'])}",
        f"metering_attempt_count: {data(metering['attempt_count'])}",
        "null tokens/estimate/confirmed_charge mean unknown, never zero cost. Empty groups are "
        "not a zero-cost claim.",
        "attempt_count counts recorded native dispatch intents, not backend requests. "
        "No per-file usage allocation is known.",
    ])
    if not metering["groups"]:
        lines.append("metering_sources: [] (no recorded source groups)")
    for group in metering["groups"]:
        lines.extend([
            f"metering_source: {data(group['source'])}",
            "  native outcomes: " + "; ".join(
                f"{name}={data(group[name])}"
                for name in ("intent_only", "unavailable", "partial", "observed")
            ),
            f"  known_input_tokens: {data(group['known_input_tokens'])}",
            f"  known_output_tokens: {data(group['known_output_tokens'])}",
        ])
    lines.extend(f"{name}: {data(metering[name])}" for name in (
        "estimate", "estimate_coverage", "confirmed_charge", "confirmed_charge_coverage",
    ))

    # All file identities/statuses remain visible even if optional payloads do
    # not fit. Paths and identities are producer-bounded, not interpreted here.
    for item in response["files"]:
        analysis = item["analysis"]
        lines.extend([
            "",
            f"file_id: {data(item['file_id'])}",
            f"path: {data(item['path'])}",
            f"status: {data(item['status'])}",
            f"analysis_provenance: {data(item['analysis_provenance'])}",
            f"comparison_available: {data(analysis['comparison_available'] if analysis else None)}",
            f"symbols_partial: {data(analysis['symbols_partial'] if analysis else None)}",
            f"omitted_in_machine_response: {data(item.get('omitted', []))}",
        ])

    blocks = []
    for item in response["files"]:
        # The actual batch producer emits V1 facts. Render them as retained,
        # without inventing the model-advice route's richer structural fields.
        analysis = item["analysis"]
        facts = ["analysis: null (not available in the machine response)"]
        if analysis is not None:
            facts = [f"{field}: {_json(analysis[field])}" for field in (
                "scope", "syntax_errors", "tests_executed",
            )]
            for kind in ("added", "removed", "changed"):
                facts.extend([
                    f"{kind}_count: {_json(analysis['counts'].get(kind))}",
                    f"{kind}_names: {_json(analysis['symbols'].get(kind))}",
                ])
        block_lines = [
            "",
            f"Details for file_id: {data(item['file_id'])}",
            *facts,
            "Parser errors make symbol comparison unavailable; symbols_partial discloses "
            "bounded symbol lists. These facts do not establish runtime behavior or compatibility.",
            f"failures: {_json(item['failures'])}",
            # Preserve the payload as opaque data, including its recorded actor.
            # Never infer a model source or parse/grade claims in the advice.
            f"advice (UNTRUSTED; MAY BE WRONG): {_json(item['advice'])}",
        ]
        request, reply = item["request"], item["reply"]
        details = [
            f"request_detail: {data(request['detail'] if request is not None else None)}",
            f"reply_detail: {data(reply['detail'] if reply is not None else None)}",
        ]
        if response["partial"] or item.get("omitted") or item["failures"]:
            block_lines.extend(details)
        block = "\n".join(block_lines)
        if len(block.encode("utf-8")) > MAX_FILE_BLOCK_BYTES:
            omissions.append("batch_text_file_block_bytes_exceeded")
            block = (
                f"\nDetails for file_id: {data(item['file_id'])}\n"
                "omitted: batch_text_file_block_bytes_exceeded; analysis, failures and "
                "UNTRUSTED advice block omitted; inspect the JSON response and retained details.\n"
                + "\n".join(details)
            )
        blocks.append(block)

    def finish(details: list[str]) -> str:
        return "\n".join([
            *lines, *details,
            f"report_partial: {_json(bool(omissions))}",
            f"report_limitations: {_json(sorted(set(omissions)))}",
        ]) + "\n"

    report = finish(blocks)
    if len(report.encode("utf-8")) > MAX_REPORT_BYTES:
        omissions.append("batch_text_response_bytes_exceeded")
        references = [f"result_detail: {data(result['detail'])}"]
        for item in response["files"]:
            references.append(f"Details for file_id: {data(item['file_id'])}")
            for name in ("request", "reply"):
                message = item[name]
                references.append(
                    f"{name}_detail: {data(message['detail'] if message is not None else None)}"
                )
        report = finish([
            "Optional file details omitted: batch_text_response_bytes_exceeded; inspect "
            "the JSON response and its retained detail references.", *references,
        ])
    if len(report.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("batch_text_response_unbounded: metadata exceeds the 256 KiB report limit")
    return report
