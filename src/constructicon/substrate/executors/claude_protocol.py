"""Pure pinned Claude initialization bytes, not a startup or availability gate.

Only this reply's reported mode is judged. Correlation is not arrival freshness,
empty pending lists are not absence of inherited prompts, and the reported
version is not physical artifact identity. Other bounded initialization metadata
is deliberately unjudged. No account, prompt or error wire data is published.
See M8-N6a-state-review.md for the independent 2.1.296 source evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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


class ClaudeModeMismatchReason(StrEnum):
    ACCOUNT_SHAPE = "account-shape"
    UNSUPPORTED_ACCOUNT_FIELD = "unsupported-account-field"
    CREDENTIAL_SOURCE_PRESENT = "credential-source-present"
    ACCOUNT_VALUE_TYPE = "account-value-type"
    PROVIDER_MISMATCH = "provider-mismatch"
    AMBIGUOUS_API = "ambiguous-api"
    SUBSCRIPTION_MISMATCH = "subscription-mismatch"


class ClaudeTokenSourceCategory(StrEnum):
    ABSENT = "absent"
    NULL = "null"
    NON_STRING = "non-string"
    UNKNOWN = "unknown"
    NONE = "none"
    AUTH_TOKEN_ENV = "auth-token-env"
    OAUTH_TOKEN_ENV = "oauth-token-env"
    OAUTH_TOKEN_FD = "oauth-token-fd"
    CCR_OAUTH_FILE = "ccr-oauth-file"
    API_KEY_HELPER = "api-key-helper"
    CLAUDE_AI = "claude-ai"


class ClaudeApiKeySourceCategory(StrEnum):
    ABSENT = "absent"
    NULL = "null"
    NON_STRING = "non-string"
    UNKNOWN = "unknown"
    ANTHROPIC_API_KEY = "anthropic-api-key"
    API_KEY_HELPER = "api-key-helper"
    LOGIN_MANAGED_KEY = "login-managed-key"


# Emitted labels only, from pinned CLI 2.1.296 xRe/vl/FE/I$; see the living
# implementation record for artifact identity and byte offsets. These are
# source labels, never credentials or admission exceptions. xRe suppresses
# token 'profile' and API-key 'none'; neither belongs to its emitted allowlist.
_TOKEN_SOURCES = {
    "none": ClaudeTokenSourceCategory.NONE,
    "ANTHROPIC_AUTH_TOKEN": ClaudeTokenSourceCategory.AUTH_TOKEN_ENV,
    "CLAUDE_CODE_OAUTH_TOKEN": ClaudeTokenSourceCategory.OAUTH_TOKEN_ENV,
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR": ClaudeTokenSourceCategory.OAUTH_TOKEN_FD,
    "CCR_OAUTH_TOKEN_FILE": ClaudeTokenSourceCategory.CCR_OAUTH_FILE,
    "apiKeyHelper": ClaudeTokenSourceCategory.API_KEY_HELPER,
    "claude.ai": ClaudeTokenSourceCategory.CLAUDE_AI,
}
_API_KEY_SOURCES = {
    "ANTHROPIC_API_KEY": ClaudeApiKeySourceCategory.ANTHROPIC_API_KEY,
    "apiKeyHelper": ClaudeApiKeySourceCategory.API_KEY_HELPER,
    "/login managed key": ClaudeApiKeySourceCategory.LOGIN_MANAGED_KEY,
}


def initialize_diagnostics_valid(
    verdict: ClaudeInitializeVerdict | None, reason: ClaudeModeMismatchReason | None,
    token: ClaudeTokenSourceCategory | None, api_key: ClaudeApiKeySourceCategory | None,
) -> bool:
    """One coherence law for captured facts and strict evidence readers."""
    if ((verdict is not None and type(verdict) is not ClaudeInitializeVerdict)
            or (reason is not None and type(reason) is not ClaudeModeMismatchReason)
            or (token is not None and type(token) is not ClaudeTokenSourceCategory)
            or (api_key is not None and type(api_key) is not ClaudeApiKeySourceCategory)):
        return False
    if verdict is ClaudeInitializeVerdict.MODE_MATCH:
        return (reason is None and token is ClaudeTokenSourceCategory.ABSENT
                and api_key is ClaudeApiKeySourceCategory.ABSENT)
    if verdict is not ClaudeInitializeVerdict.MODE_MISMATCH:
        return reason is None and token is None and api_key is None
    if reason is None:
        return False
    if reason is ClaudeModeMismatchReason.ACCOUNT_SHAPE:
        return token is None and api_key is None
    if token is None or api_key is None:
        return False
    absent = (token is ClaudeTokenSourceCategory.ABSENT
              and api_key is ClaudeApiKeySourceCategory.ABSENT)
    if reason is ClaudeModeMismatchReason.CREDENTIAL_SOURCE_PRESENT:
        return not absent
    return reason is ClaudeModeMismatchReason.UNSUPPORTED_ACCOUNT_FIELD or absent


def initialize_diagnostic_fields_valid(
    verdict: object, reason: object, token: object, api_key: object,
) -> bool:
    """Strict schema-6 enum projection, without parsing any native reply again."""
    if ((verdict is not None and type(verdict) is not str)
            or (reason is not None and type(reason) is not str)
            or (token is not None and type(token) is not str)
            or (api_key is not None and type(api_key) is not str)):
        return False
    try:
        return initialize_diagnostics_valid(
            None if verdict is None else ClaudeInitializeVerdict(verdict),
            None if reason is None else ClaudeModeMismatchReason(reason),
            None if token is None else ClaudeTokenSourceCategory(token),
            None if api_key is None else ClaudeApiKeySourceCategory(api_key),
        )
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class ClaudeInitializeObservation:
    """One parsed reply's closed diagnostics; None means unobserved, not absent."""

    verdict: ClaudeInitializeVerdict
    reason: ClaudeModeMismatchReason | None
    token_source_category: ClaudeTokenSourceCategory | None
    api_key_source_category: ClaudeApiKeySourceCategory | None

    def __post_init__(self) -> None:
        if self.verdict is None or not initialize_diagnostics_valid(
            self.verdict, self.reason, self.token_source_category, self.api_key_source_category,
        ):
            raise ValueError("invalid Claude initialization observation")


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


def _classify_initialize(
    record: bytes, *, expected_request_id: str, selected_plan: ClaudePlan
) -> ClaudeInitializeObservation:
    """Return one finite mode verdict, never the vendor's fields or exceptions.

    This accepts a complete LF-terminated record, not arbitrary ProcessIO chunks.
    The future sole-reader conversation owns framing, freshness and dispatch.
    """
    token_category: ClaudeTokenSourceCategory | None = None
    api_key_category: ClaudeApiKeySourceCategory | None = None

    def observed(
        value: ClaudeInitializeVerdict | ClaudeModeMismatchReason,
    ) -> ClaudeInitializeObservation:
        return ClaudeInitializeObservation(
            (ClaudeInitializeVerdict.MODE_MISMATCH
             if isinstance(value, ClaudeModeMismatchReason) else value),
            value if isinstance(value, ClaudeModeMismatchReason) else None,
            token_category, api_key_category,
        )

    _require_id(expected_request_id)
    if type(selected_plan) is not ClaudePlan:
        raise ValueError("invalid selected Claude plan")
    verdict = ClaudeInitializeVerdict
    if type(record) is not bytes:
        return observed(verdict.RECORD_INVALID)
    if len(record) > RECORD_BYTES:
        return observed(verdict.RECORD_TOO_LARGE)
    if not record.endswith(b"\n") or b"\n" in record[:-1] or b"\r" in record:
        return observed(verdict.RECORD_INVALID)
    try:
        value = parse_json_value(record[:-1].decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        return observed(verdict.RECORD_INVALID)
    if type(value) is not dict or set(value) != {"type", "response"}:
        return observed(verdict.RESPONSE_INVALID)
    if value.get("type") != "control_response":
        return observed(verdict.RESPONSE_INVALID)
    envelope = value.get("response")
    if type(envelope) is not dict:
        return observed(verdict.RESPONSE_INVALID)
    subtype = envelope.get("subtype")
    if subtype not in ("success", "error"):
        return observed(verdict.RESPONSE_INVALID)
    if type(envelope.get("request_id")) is not str:
        return observed(verdict.RESPONSE_INVALID)
    if envelope["request_id"] != expected_request_id:
        return observed(verdict.REQUEST_MISMATCH)
    pending = {"pending_permission_requests", "pending_user_dialog_requests"}
    if subtype == "error":
        allowed = {"subtype", "request_id", "error", "error_code"} | pending
        if not set(envelope) <= allowed or type(envelope.get("error")) is not str:
            return observed(verdict.RESPONSE_INVALID)
        if "error_code" in envelope and type(envelope["error_code"]) is not str:
            return observed(verdict.RESPONSE_INVALID)
        if any(type(envelope[key]) is not list for key in pending if key in envelope):
            return observed(verdict.RESPONSE_INVALID)
        return observed(verdict.INITIALIZE_ERROR)
    if set(envelope) != {"subtype", "request_id", "response"} | pending:
        return observed(verdict.RESPONSE_INVALID)
    if any(type(envelope[key]) is not list for key in pending):
        return observed(verdict.RESPONSE_INVALID)
    if any(envelope[key] for key in pending):
        return observed(verdict.INITIALIZE_BUSY)
    body = envelope.get("response")
    if type(body) is not dict:
        return observed(verdict.RESPONSE_INVALID)
    if not {"claude_code_version", "session_state", "account"} <= set(body):
        return observed(verdict.RESPONSE_INVALID)
    if body["claude_code_version"] != CLAUDE_CODE_VERSION:
        return observed(verdict.RESPONSE_INVALID)
    if body["session_state"] not in ("idle", "running", "requires_action"):
        return observed(verdict.RESPONSE_INVALID)
    if body["session_state"] != "idle":
        return observed(verdict.INITIALIZE_BUSY)
    account = body["account"]
    reason = ClaudeModeMismatchReason
    if type(account) is not dict:
        return observed(reason.ACCOUNT_SHAPE)
    if "tokenSource" not in account:
        token_category = ClaudeTokenSourceCategory.ABSENT
    elif account["tokenSource"] is None:
        token_category = ClaudeTokenSourceCategory.NULL
    elif type(account["tokenSource"]) is not str:
        token_category = ClaudeTokenSourceCategory.NON_STRING
    else:
        token_category = _TOKEN_SOURCES.get(
            account["tokenSource"], ClaudeTokenSourceCategory.UNKNOWN,
        )
    if "apiKeySource" not in account:
        api_key_category = ClaudeApiKeySourceCategory.ABSENT
    elif account["apiKeySource"] is None:
        api_key_category = ClaudeApiKeySourceCategory.NULL
    elif type(account["apiKeySource"]) is not str:
        api_key_category = ClaudeApiKeySourceCategory.NON_STRING
    else:
        api_key_category = _API_KEY_SOURCES.get(
            account["apiKeySource"], ClaudeApiKeySourceCategory.UNKNOWN,
        )
    fields = {"apiProvider", "subscriptionType", "email", "organization",
              "tokenSource", "apiKeySource"}
    if not set(account) <= fields:
        return observed(reason.UNSUPPORTED_ACCOUNT_FIELD)
    if "tokenSource" in account or "apiKeySource" in account:
        return observed(reason.CREDENTIAL_SOURCE_PRESENT)
    if any(type(item) is not str for item in account.values()):
        return observed(reason.ACCOUNT_VALUE_TYPE)
    if account.get("apiProvider") != "firstParty":
        return observed(reason.PROVIDER_MISMATCH)
    if account.get("subscriptionType") != selected_plan.value:
        if account.get("subscriptionType") == "Claude API":
            return observed(reason.AMBIGUOUS_API)
        return observed(reason.SUBSCRIPTION_MISMATCH)
    return observed(verdict.MODE_MATCH)


def observe_initialize(
    record: bytes, *, expected_request_id: str, selected_plan: ClaudePlan,
) -> ClaudeInitializeObservation:
    """Classify once for the mode and qualification conversation consumers."""
    return _classify_initialize(
        record, expected_request_id=expected_request_id, selected_plan=selected_plan,
    )


def classify_initialize(
    record: bytes, *, expected_request_id: str, selected_plan: ClaudePlan,
) -> tuple[ClaudeInitializeVerdict, ClaudeModeMismatchReason | None]:
    """Classify once, retaining only a closed reported-mode mismatch reason."""
    result = _classify_initialize(
        record, expected_request_id=expected_request_id, selected_plan=selected_plan,
    )
    return result.verdict, result.reason


def judge_initialize(
    record: bytes, *, expected_request_id: str, selected_plan: ClaudePlan,
) -> ClaudeInitializeVerdict:
    """Preserve the original finite verdict projection, without account data."""
    verdict, _ = classify_initialize(
        record, expected_request_id=expected_request_id, selected_plan=selected_plan,
    )
    return verdict
