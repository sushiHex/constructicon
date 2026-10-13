"""Pure pinned Claude initialization bytes, not a startup or availability gate.

Only this reply's reported mode is judged. Correlation is not arrival freshness,
empty pending lists are not absence of inherited prompts, and the reported
version is not physical artifact identity. Other bounded initialization metadata
is deliberately unjudged. No account, prompt or error wire data is published.
See M8-N6a-state-review.md for the independent 2.1.296 source evidence.
"""

from __future__ import annotations

import json
from enum import StrEnum

from constructicon.core.identity import parse_json_value

RECORD_BYTES = 256 * 1024
"""Adapter policy per complete record, including LF; not a vendor promise."""

CLAUDE_CODE_VERSION = "2.1.296"


class ClaudePlan(StrEnum):
    PRO = "Claude Pro"
    MAX = "Claude Max"


class ClaudeInitializeVerdict(StrEnum):
    MODE_MATCH = "mode-match"
    RECORD_INVALID = "record-invalid"
    RECORD_TOO_LARGE = "record-too-large"
    RESPONSE_INVALID = "response-invalid"
    REQUEST_MISMATCH = "request-mismatch"
    INITIALIZE_ERROR = "initialize-error"
    INITIALIZE_BUSY = "initialize-busy"
    MODE_MISMATCH = "mode-mismatch"


def _require_id(value: str) -> None:
    if type(value) is not str or not value:
        raise ValueError("invalid initialize request id")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("invalid initialize request id") from None


def initialize_request(request_id: str) -> bytes:
    """Build only bare initialize; an opaque caller-owned id adds no authority."""
    _require_id(request_id)
    request = {"type": "control_request", "request_id": request_id,
               "request": {"subtype": "initialize"}}
    record = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
    if len(record) > RECORD_BYTES:
        raise ValueError("initialize request too large")
    return record


def judge_initialize(
    record: bytes, *, expected_request_id: str, selected_plan: ClaudePlan
) -> ClaudeInitializeVerdict:
    """Return one finite mode verdict, never the vendor's fields or exceptions.

    This accepts a complete LF-terminated record, not arbitrary ProcessIO chunks.
    The future sole-reader conversation owns framing, freshness and dispatch.
    """
    _require_id(expected_request_id)
    if type(selected_plan) is not ClaudePlan:
        raise ValueError("invalid selected Claude plan")
    verdict = ClaudeInitializeVerdict
    if type(record) is not bytes:
        return verdict.RECORD_INVALID
    if len(record) > RECORD_BYTES:
        return verdict.RECORD_TOO_LARGE
    if not record.endswith(b"\n") or b"\n" in record[:-1] or b"\r" in record:
        return verdict.RECORD_INVALID
    try:
        value = parse_json_value(record[:-1].decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        return verdict.RECORD_INVALID
    if type(value) is not dict or set(value) != {"type", "response"}:
        return verdict.RESPONSE_INVALID
    if value.get("type") != "control_response":
        return verdict.RESPONSE_INVALID
    envelope = value.get("response")
    if type(envelope) is not dict:
        return verdict.RESPONSE_INVALID
    subtype = envelope.get("subtype")
    if subtype not in ("success", "error"):
        return verdict.RESPONSE_INVALID
    if type(envelope.get("request_id")) is not str:
        return verdict.RESPONSE_INVALID
    if envelope["request_id"] != expected_request_id:
        return verdict.REQUEST_MISMATCH
    pending = {"pending_permission_requests", "pending_user_dialog_requests"}
    if subtype == "error":
        allowed = {"subtype", "request_id", "error", "error_code"} | pending
        if not set(envelope) <= allowed or type(envelope.get("error")) is not str:
            return verdict.RESPONSE_INVALID
        if "error_code" in envelope and type(envelope["error_code"]) is not str:
            return verdict.RESPONSE_INVALID
        if any(type(envelope[key]) is not list for key in pending if key in envelope):
            return verdict.RESPONSE_INVALID
        return verdict.INITIALIZE_ERROR
    if set(envelope) != {"subtype", "request_id", "response"} | pending:
        return verdict.RESPONSE_INVALID
    if any(type(envelope[key]) is not list for key in pending):
        return verdict.RESPONSE_INVALID
    if any(envelope[key] for key in pending):
        return verdict.INITIALIZE_BUSY
    body = envelope.get("response")
    if type(body) is not dict:
        return verdict.RESPONSE_INVALID
    if not {"claude_code_version", "session_state", "account"} <= set(body):
        return verdict.RESPONSE_INVALID
    if body["claude_code_version"] != CLAUDE_CODE_VERSION:
        return verdict.RESPONSE_INVALID
    if body["session_state"] not in ("idle", "running", "requires_action"):
        return verdict.RESPONSE_INVALID
    if body["session_state"] != "idle":
        return verdict.INITIALIZE_BUSY
    account = body["account"]
    if type(account) is not dict:
        return verdict.MODE_MISMATCH
    fields = {"apiProvider", "subscriptionType", "email", "organization",
              "tokenSource", "apiKeySource"}
    if not set(account) <= fields:
        return verdict.MODE_MISMATCH
    if "tokenSource" in account or "apiKeySource" in account:
        return verdict.MODE_MISMATCH
    if any(type(item) is not str for item in account.values()):
        return verdict.MODE_MISMATCH
    if account.get("apiProvider") != "firstParty":
        return verdict.MODE_MISMATCH
    if account.get("subscriptionType") != selected_plan.value:
        return verdict.MODE_MISMATCH
    return verdict.MODE_MATCH
