"""Pure fixed Claude startup policy; not physical or vendor qualification.

Settings/hook projections corroborate the reviewed pinned source restrictions.
They do not observe process.env, retained hook snapshots, omitted native tools,
or physical arrival freshness. The conversation owns correlation and lifecycle;
reviewed source and separately qualified assembly supply mechanical boundaries.
Only finite verdicts leave this module; raw settings and errors remain private.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum

from constructicon.core.identity import parse_json_value
from constructicon.substrate.executors.claude_protocol import RECORD_BYTES, initialize_request

MAX_HOOK_EVENTS = 64
_SOURCES = frozenset({"userSettings", "projectSettings", "localSettings",
                      "flagSettings", "policySettings"})
_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_EMPTY_ENV = (
    "CLAUDE_CODE_SIMPLE", "CLAUDE_INTERNAL_FC_OVERRIDES",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY", "CLAUDE_CODE_BYOC_ENABLE_DATADOG",
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "CLAUDE_CODE_OAUTH_SCOPES",
    "CLAUDE_CODE_OAUTH_CLIENT_ID", "AWS_BEARER_TOKEN_BEDROCK",
    "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_AUTH_TOKEN", "ANTHROPIC_AWS_API_KEY",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS", "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",
    "CLAUDE_CODE_USE_MANTLE", "CLAUDE_CODE_USE_GATEWAY", "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_API_BASE_URL", "CLAUDE_CODE_CUSTOM_OAUTH_URL", "ANTHROPIC_CUSTOM_HEADERS",
    "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID", "ANTHROPIC_WORKSPACE_ID",
    "ANTHROPIC_SERVICE_ACCOUNT_ID", "ANTHROPIC_IDENTITY_TOKEN", "ANTHROPIC_IDENTITY_TOKEN_FILE",
    "ANTHROPIC_SCOPE", "ANTHROPIC_PROFILE", "CLAUDE_CODE_CLIENT_CERT",
    "CLAUDE_CODE_CLIENT_KEY", "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE", "NODE_EXTRA_CA_CERTS",
    "NODE_OPTIONS", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "CLAUDE_CODE_HTTP_PROXY", "CLAUDE_CODE_HTTPS_PROXY",
)


class ClaudeStartupVerdict(StrEnum):
    MATCH = "match"
    RECORD_INVALID = "record-invalid"
    RECORD_TOO_LARGE = "record-too-large"
    RESPONSE_INVALID = "response-invalid"
    REQUEST_MISMATCH = "request-mismatch"
    CONTROL_ERROR = "control-error"
    CONFIGURATION_MISMATCH = "configuration-mismatch"


class ClaudeSettingsMismatchReason(StrEnum):
    BODY_FIELDS = "body-fields"
    REPORTED_ERRORS = "reported-errors"
    EFFECTIVE_SETTINGS = "effective-settings"
    SOURCE_LIST = "source-list"
    SOURCE_ENTRY = "source-entry"
    SOURCE_NAME = "source-name"
    SOURCE_SETTINGS = "source-settings"
    POLICY_SOURCE_MISSING = "policy-source-missing"
    APPLIED_FIELDS = "applied-fields"
    MODEL_MISMATCH = "model-mismatch"
    EFFORT_MISMATCH = "effort-mismatch"
    APPLIED_OPTIONS = "applied-options"


def fixed_environment() -> dict[str, str]:
    """Fresh nonlocator controls; assembly separately seals locators and argv."""
    return {**dict.fromkeys(_EMPTY_ENV, ""),
            "CLAUDE_CODE_ENVIRONMENT_KIND": "byoc", "DISABLE_GROWTHBOOK": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "CLAUDE_CODE_CLASSIFIER_SUMMARY": "0", "CLAUDE_CODE_ENABLE_REMOTE_RECAP": "0",
            "_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL": "0",
            "NODE_TLS_REJECT_UNAUTHORIZED": "1", "CLAUDE_CODE_CERT_STORE": "bundled"}


def fixed_policy() -> dict[str, object]:
    """Fresh exact admin settings, not a parent managedSettings substitute."""
    return {"forceRemoteSettingsRefresh": True,
            "deniedMcpServers": [{"serverUrl": "*"}]}


def _request(request_id: str, subtype: str) -> bytes:
    initialize_request(request_id)  # Reuse strict ID/Unicode/bound validation.
    value = {"type": "control_request", "request_id": request_id,
             "request": {"subtype": subtype}}
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
    if len(raw) > RECORD_BYTES:
        raise ValueError("Claude startup request too large")
    return raw


def settings_request(request_id: str) -> bytes:
    return _request(request_id, "get_settings")


def hooks_request(request_id: str) -> bytes:
    return _request(request_id, "get_hooks_listing")


def _body(record: bytes, expected_request_id: str) -> dict[str, object] | ClaudeStartupVerdict:
    initialize_request(expected_request_id)
    verdict = ClaudeStartupVerdict
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
    if value["type"] != "control_response" or type(value["response"]) is not dict:
        return verdict.RESPONSE_INVALID
    envelope = value["response"]
    if type(envelope.get("request_id")) is not str:
        return verdict.RESPONSE_INVALID
    if envelope["request_id"] != expected_request_id:
        return verdict.REQUEST_MISMATCH
    if envelope.get("subtype") == "error":
        if (not set(envelope) <= {"subtype", "request_id", "error", "error_code"}
                or type(envelope.get("error")) is not str
                or ("error_code" in envelope and type(envelope["error_code"]) is not str)):
            return verdict.RESPONSE_INVALID
        return verdict.CONTROL_ERROR
    if (set(envelope) != {"subtype", "request_id", "response"}
            or envelope["subtype"] != "success" or type(envelope["response"]) is not dict):
        return verdict.RESPONSE_INVALID
    return envelope["response"]


def _configuration(value: object, *, require_policy: bool) -> bool:
    if type(value) is not dict or not set(value) <= {"env", *fixed_policy()}:
        return False
    if require_policy and not set(fixed_policy()) <= set(value):
        return False
    if "forceRemoteSettingsRefresh" in value and value["forceRemoteSettingsRefresh"] is not True:
        return False
    if "deniedMcpServers" in value:
        denied = value["deniedMcpServers"]
        if (type(denied) is not list or len(denied) != 1 or type(denied[0]) is not dict
                or set(denied[0]) != {"serverUrl"}
                or type(denied[0]["serverUrl"]) is not str or denied[0]["serverUrl"] != "*"):
            return False
    if "env" in value:
        env = value["env"]
        if (type(env) is not dict or not set(env) <= set(fixed_environment())
                or any(type(item) is not str for item in env.values())):
            return False
    return True


def _classify_settings(
    record: bytes, *, expected_request_id: str, model: str, effort: str,
) -> ClaudeStartupVerdict | ClaudeSettingsMismatchReason:
    """Judge emitted current settings, not effective process env or hook caches."""
    if (type(model) is not str or _MODEL.fullmatch(model) is None
            or type(effort) is not str or effort not in _EFFORTS):
        raise ValueError("invalid sealed Claude model or effort")
    body = _body(record, expected_request_id)
    if isinstance(body, ClaudeStartupVerdict):
        return body
    reason = ClaudeSettingsMismatchReason
    if (not {"effective", "sources", "applied"} <= set(body)
            or not set(body) <= {"effective", "sources", "applied", "errors"}):
        return reason.BODY_FIELDS
    if "errors" in body and body["errors"] != []:
        return reason.REPORTED_ERRORS
    if not _configuration(body["effective"], require_policy=True):
        return reason.EFFECTIVE_SETTINGS
    sources = body["sources"]
    if type(sources) is not list or not 1 <= len(sources) <= len(_SOURCES):
        return reason.SOURCE_LIST
    seen: set[str] = set()
    for source in sources:
        if type(source) is not dict or set(source) != {"source", "settings"}:
            return reason.SOURCE_ENTRY
        name = source["source"]
        if type(name) is not str or name not in _SOURCES or name in seen:
            return reason.SOURCE_NAME
        seen.add(name)
        if not _configuration(source["settings"], require_policy=name == "policySettings"):
            return reason.SOURCE_SETTINGS
    if "policySettings" not in seen:
        return reason.POLICY_SOURCE_MISSING
    applied = body["applied"]
    if (type(applied) is not dict or set(applied) != {
            "model", "effort", "advisor", "ultracode", "ultracodeRequested", "ultracodeAvailable"}):
        return reason.APPLIED_FIELDS
    if type(applied["model"]) is not str or applied["model"] != model:
        return reason.MODEL_MISMATCH
    if type(applied["effort"]) is not str or applied["effort"] != effort:
        return reason.EFFORT_MISMATCH
    if (applied["advisor"] is not None or applied["ultracode"] is not False
            or applied["ultracodeRequested"] is not False
            or type(applied["ultracodeAvailable"]) is not bool):
        return reason.APPLIED_OPTIONS
    return ClaudeStartupVerdict.MATCH


def classify_settings(
    record: bytes, *, expected_request_id: str, model: str, effort: str,
) -> tuple[ClaudeStartupVerdict, ClaudeSettingsMismatchReason | None]:
    """Classify once, retaining only a finite settings mismatch reason."""
    result = _classify_settings(
        record, expected_request_id=expected_request_id, model=model, effort=effort,
    )
    if isinstance(result, ClaudeSettingsMismatchReason):
        return ClaudeStartupVerdict.CONFIGURATION_MISMATCH, result
    return result, None


def judge_settings(
    record: bytes, *, expected_request_id: str, model: str, effort: str,
) -> ClaudeStartupVerdict:
    """Preserve the original finite verdict projection without settings data."""
    verdict, _ = classify_settings(
        record, expected_request_id=expected_request_id, model=model, effort=effort,
    )
    return verdict


def judge_hooks(record: bytes, *, expected_request_id: str) -> ClaudeStartupVerdict:
    """Judge actual listed/current hooks; source ordering separately closes q4."""
    body = _body(record, expected_request_id)
    if isinstance(body, ClaudeStartupVerdict):
        return body
    mismatch = ClaudeStartupVerdict.CONFIGURATION_MISMATCH
    if (not {"events", "hooks", "eventCatalog", "policy", "safeMode"} <= set(body)
            or not set(body) <= {"events", "hooks", "eventCatalog", "policy", "safeMode", "errors"}
            or body["events"] != [] or body["hooks"] != []
            or ("errors" in body and body["errors"] != [])):
        return mismatch
    policy, safe, catalog = body["policy"], body["safeMode"], body["eventCatalog"]
    if (type(policy) is not dict or set(policy) != {
            "disabledByPolicy", "managedOnly", "pluginOnly", "allDisabled", "policyHookCount"}
            or any(policy[key] is not False for key in (
                "disabledByPolicy", "managedOnly", "pluginOnly", "allDisabled"))
            or type(policy["policyHookCount"]) is not int or policy["policyHookCount"] != 0
            or type(safe) is not dict or set(safe) != {"managedHooksStillApply", "exitHint"}
            or safe["managedHooksStillApply"] is not True
            or safe["exitHint"] != "restart without --safe-mode"
            or type(catalog) is not list or not 1 <= len(catalog) <= MAX_HOOK_EVENTS):
        return mismatch
    names: set[str] = set()
    for event in catalog:
        if (type(event) is not dict or set(event) != {"name", "summary", "supportsMatcher"}
                or type(event["name"]) is not str or not 1 <= len(event["name"]) <= 64
                or event["name"] in names or type(event["summary"]) is not str
                or len(event["summary"].encode("utf-8")) > 4096
                or type(event["supportsMatcher"]) is not bool):
            return mismatch
        names.add(event["name"])
    return ClaudeStartupVerdict.MATCH
