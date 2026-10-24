"""Actual pinned settings/hooks projections; no vendor process or credentials."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from constructicon.substrate.executors import claude_startup as startup
from tests.substrate._claude_wire import MODEL, hooks_body, settings_body

EFFORT = "high"
_EXPECTED_ENVIRONMENT = {
    "CLAUDE_CODE_ENVIRONMENT_KIND": "byoc",
    "DISABLE_GROWTHBOOK": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_CLASSIFIER_SUMMARY": "0",
    "CLAUDE_CODE_ENABLE_REMOTE_RECAP": "0",
    "_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL": "0",
    "NODE_TLS_REJECT_UNAUTHORIZED": "1",
    "CLAUDE_CODE_CERT_STORE": "bundled",
    "CLAUDE_CODE_SIMPLE": "",
    "CLAUDE_INTERNAL_FC_OVERRIDES": "",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "",
    "CLAUDE_CODE_BYOC_ENABLE_DATADOG": "",
    "ANTHROPIC_API_KEY": "",
    "ANTHROPIC_AUTH_TOKEN": "",
    "CLAUDE_CODE_OAUTH_TOKEN": "",
    "CLAUDE_CODE_OAUTH_REFRESH_TOKEN": "",
    "CLAUDE_CODE_OAUTH_SCOPES": "",
    "CLAUDE_CODE_OAUTH_CLIENT_ID": "",
    "AWS_BEARER_TOKEN_BEDROCK": "",
    "ANTHROPIC_FOUNDRY_API_KEY": "",
    "ANTHROPIC_FOUNDRY_AUTH_TOKEN": "",
    "ANTHROPIC_AWS_API_KEY": "",
    "CLAUDE_CODE_USE_BEDROCK": "",
    "CLAUDE_CODE_USE_VERTEX": "",
    "CLAUDE_CODE_USE_FOUNDRY": "",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS": "",
    "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD": "",
    "CLAUDE_CODE_USE_MANTLE": "",
    "CLAUDE_CODE_USE_GATEWAY": "",
    "ANTHROPIC_BASE_URL": "",
    "CLAUDE_CODE_API_BASE_URL": "",
    "CLAUDE_CODE_CUSTOM_OAUTH_URL": "",
    "ANTHROPIC_CUSTOM_HEADERS": "",
    "ANTHROPIC_FEDERATION_RULE_ID": "",
    "ANTHROPIC_ORGANIZATION_ID": "",
    "ANTHROPIC_WORKSPACE_ID": "",
    "ANTHROPIC_SERVICE_ACCOUNT_ID": "",
    "ANTHROPIC_IDENTITY_TOKEN": "",
    "ANTHROPIC_IDENTITY_TOKEN_FILE": "",
    "ANTHROPIC_SCOPE": "",
    "ANTHROPIC_PROFILE": "",
    "CLAUDE_CODE_CLIENT_CERT": "",
    "CLAUDE_CODE_CLIENT_KEY": "",
    "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE": "",
    "NODE_EXTRA_CA_CERTS": "",
    "NODE_OPTIONS": "",
    "HTTP_PROXY": "",
    "HTTPS_PROXY": "",
    "ALL_PROXY": "",
    "NO_PROXY": "",
    "CLAUDE_CODE_HTTP_PROXY": "",
    "CLAUDE_CODE_HTTPS_PROXY": "",
}


def wire(body, request_id="observe-1", **envelope):
    return json.dumps({"type": "control_response", "response": {
        "subtype": "success", "request_id": request_id, "response": body,
        **envelope,
    }}, separators=(",", ":")).encode() + b"\n"


def settings():
    return settings_body(model=MODEL, effort=EFFORT)


def hooks():
    return hooks_body()


def judge_settings(body):
    return startup.judge_settings(wire(body), expected_request_id="observe-1",
                                  model=MODEL, effort=EFFORT)


def judge_hooks(body):
    return startup.judge_hooks(wire(body), expected_request_id="observe-1")


def test_authentic_minimal_settings_and_hooks_accept():
    assert len(hooks()["eventCatalog"]) == 33
    assert judge_settings(settings()) is startup.ClaudeStartupVerdict.MATCH
    assert judge_hooks(hooks()) is startup.ClaudeStartupVerdict.MATCH
    body = settings()
    body["effective"]["env"] = {"DISABLE_GROWTHBOOK": "untrusted-ignored"}
    body["sources"][0]["settings"]["env"] = {"DISABLE_GROWTHBOOK": "untrusted-ignored"}
    assert judge_settings(body) is startup.ClaudeStartupVerdict.MATCH


@pytest.mark.parametrize("reason", list(startup.ClaudeSettingsMismatchReason))
def test_settings_reasons_are_finite_and_keep_the_original_refusal(reason):
    body = settings()
    reasons = startup.ClaudeSettingsMismatchReason
    if reason is reasons.BODY_FIELDS:
        body["remote_control_policy_lock_reason"] = "private-sentinel"
    elif reason is reasons.REPORTED_ERRORS:
        body["errors"] = [{"private-sentinel": "private-value"}]
    elif reason is reasons.EFFECTIVE_SETTINGS:
        body["effective"]["private-sentinel"] = "private-value"
    elif reason is reasons.SOURCE_LIST:
        body["sources"] = []
    elif reason is reasons.SOURCE_ENTRY:
        body["sources"][0]["private-sentinel"] = "private-value"
    elif reason is reasons.SOURCE_NAME:
        body["sources"][0]["source"] = "private-sentinel"
    elif reason is reasons.SOURCE_SETTINGS:
        body["sources"][0]["settings"]["forceRemoteSettingsRefresh"] = False
    elif reason is reasons.POLICY_SOURCE_MISSING:
        body["sources"][0]["source"] = "flagSettings"
    elif reason is reasons.APPLIED_FIELDS:
        body["applied"]["private-sentinel"] = "private-value"
    elif reason is reasons.MODEL_MISMATCH:
        body["applied"]["model"] = "private-sentinel"
    elif reason is reasons.EFFORT_MISMATCH:
        body["applied"]["effort"] = None
    else:
        body["applied"]["advisor"] = "private-sentinel"
    verdict, observed = startup.classify_settings(
        wire(body), expected_request_id="observe-1", model=MODEL, effort=EFFORT,
    )
    assert verdict is judge_settings(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH
    assert observed is reason
    assert "private" not in repr((verdict, observed)) and len(reason.value) <= 24


@pytest.mark.parametrize("raw,expected", [
    (wire(settings()), startup.ClaudeStartupVerdict.MATCH),
    (b"{}", startup.ClaudeStartupVerdict.RECORD_INVALID),
    (wire(settings(), "other"), startup.ClaudeStartupVerdict.REQUEST_MISMATCH),
])
def test_settings_reason_is_absent_without_a_configuration_mismatch(raw, expected):
    assert startup.classify_settings(
        raw, expected_request_id="observe-1", model=MODEL, effort=EFFORT,
    ) == (expected, None)


def test_requests_are_exact_bounded_controls_and_do_not_add_initialize_fields():
    for build, subtype in [(startup.settings_request, "get_settings"),
                           (startup.hooks_request, "get_hooks_listing")]:
        assert json.loads(build("observe-1")) == {
            "type": "control_request", "request_id": "observe-1",
            "request": {"subtype": subtype}}
        assert build("observe-1").endswith(b"\n")
        with pytest.raises(ValueError):
            build("secret\ud800")


def test_recipe_is_fresh_exact_and_has_continuous_suppressors():
    env = startup.fixed_environment()
    # Independently written launch contract, including every protected empty
    # key: neither missing keys nor unexpected host markers may be normalized.
    assert env == _EXPECTED_ENVIRONMENT
    env.clear()
    assert startup.fixed_environment() == _EXPECTED_ENVIRONMENT
    policy = startup.fixed_policy()
    policy["deniedMcpServers"].clear()
    assert startup.fixed_policy()["deniedMcpServers"] == [{"serverUrl": "*"}]


@pytest.mark.parametrize("part", ["effective", "source"])
@pytest.mark.parametrize("key,value", [
    ("forceRemoteSettingsRefresh", 1), ("forceRemoteSettingsRefresh", False),
    ("deniedMcpServers", []), ("deniedMcpServers", [{"serverUrl": "other"}]),
    ("hooks", {}), ("forceLoginGatewayUrl", "secret"), ("model", MODEL),
    ("env", {"UNKNOWN": "secret"}), ("env", {"DISABLE_GROWTHBOOK": True}),
    ("env", {"disable_growthbook": "secret"}),
])
def test_policy_mismatches_never_coerce_or_widen(part, key, value):
    body = settings()
    target = body["effective"] if part == "effective" else body["sources"][0]["settings"]
    target[key] = value
    assert judge_settings(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH


@pytest.mark.parametrize("part", ["effective", "sources", "applied"])
def test_required_settings_facts_are_affirmative(part):
    body = settings()
    del body[part]
    assert judge_settings(body) is not startup.ClaudeStartupVerdict.MATCH


@pytest.mark.parametrize("change", ["empty", "unknown", "duplicate", "no-policy"])
def test_sources_cannot_be_invented_or_omitted(change):
    body = settings()
    if change == "empty":
        body["sources"] = []
    elif change == "unknown":
        body["sources"][0]["source"] = "managed"
    elif change == "duplicate":
        body["sources"].append(deepcopy(body["sources"][0]))
    else:
        body["sources"][0]["source"] = "flagSettings"
    assert judge_settings(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH


@pytest.mark.parametrize("key,value", [("model", "different"), ("effort", "low"),
    ("advisor", "secret"), ("ultracode", 0), ("ultracode", True),
    ("ultracodeRequested", True), ("ultracodeAvailable", 1)])
def test_applied_session_state_matches_sealed_expectations(key, value):
    body = settings()
    body["applied"][key] = value
    assert judge_settings(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH


@pytest.mark.parametrize("key,value", [("events", [{}]), ("hooks", [{}]),
    ("bareMode", {}), ("errors", [{}]), ("safeMode", {}), ("startup_ok", True)])
def test_hooks_reject_configuration_and_unknown_clearance(key, value):
    body = hooks()
    body[key] = value
    assert judge_hooks(body) is not startup.ClaudeStartupVerdict.MATCH


@pytest.mark.parametrize("key,value", [("policyHookCount", False),
    ("policyHookCount", 1), ("managedOnly", True), ("pluginOnly", True),
    ("disabledByPolicy", 0), ("allDisabled", True), ("policyUnreadable", True)])
def test_policy_hook_facts_use_exact_types(key, value):
    body = hooks()
    body["policy"][key] = value
    assert judge_hooks(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH


@pytest.mark.parametrize("judge", [startup.judge_hooks, startup.judge_settings])
def test_record_bounds_correlation_and_strict_json(judge):
    kwargs = {"expected_request_id": "observe-1"}
    if judge is startup.judge_settings:
        kwargs.update(model=MODEL, effort=EFFORT)
    result = judge(b"x" * (startup.RECORD_BYTES + 1), **kwargs)
    assert result is startup.ClaudeStartupVerdict.RECORD_TOO_LARGE
    for raw in [b"{}", b"{}\r\n", b"{}\n{}\n", b'{"x":1,"x":2}\n',
                b'{"x":NaN}\n', b'"\\ud800"\n', b"\xff\n"]:
        assert judge(raw, **kwargs) is startup.ClaudeStartupVerdict.RECORD_INVALID
    body = hooks() if judge is startup.judge_hooks else settings()
    assert judge(wire(body, "other"), **kwargs) is startup.ClaudeStartupVerdict.REQUEST_MISMATCH
    result = judge(wire(body, extra="secret"), **kwargs)
    assert result is startup.ClaudeStartupVerdict.RESPONSE_INVALID
    with pytest.raises(ValueError):
        judge(wire(body), **{**kwargs, "expected_request_id": True})


def test_error_and_private_metadata_never_escape_finite_verdict():
    raw = (b'{"type":"control_response","response":{"subtype":"error",'
           b'"request_id":"observe-1","error":"secret-value"}}\n')
    result = startup.judge_hooks(raw, expected_request_id="observe-1")
    assert result is startup.ClaudeStartupVerdict.CONTROL_ERROR
    assert "secret" not in repr(result)
    body = settings()
    body["errors"] = [{"message": "secret-value"}]
    assert judge_settings(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH


def test_sealed_arguments_and_catalog_bounds_bind():
    for value in [True, "", "secret\ud800", "a" * 129, "model\nother"]:
        with pytest.raises(ValueError):
            startup.judge_settings(wire(settings()), expected_request_id="observe-1",
                                   model=value, effort=EFFORT)
    with pytest.raises(ValueError):
        startup.judge_settings(wire(settings()), expected_request_id="observe-1",
                               model=MODEL, effort="unknown")
    body = hooks()
    body["eventCatalog"] *= startup.MAX_HOOK_EVENTS + 1
    assert judge_hooks(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH
    body = hooks()
    body["eventCatalog"][0]["supportsMatcher"] = 1
    assert judge_hooks(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH


def test_record_limit_accepts_at_bound_and_refuses_one_byte_more():
    raw = wire(settings())
    padded = raw[:-1] + b" " * (startup.RECORD_BYTES - len(raw)) + b"\n"
    assert len(padded) == startup.RECORD_BYTES
    kwargs = {"expected_request_id": "observe-1", "model": MODEL, "effort": EFFORT}
    assert startup.judge_settings(padded, **kwargs) is startup.ClaudeStartupVerdict.MATCH
    result = startup.judge_settings(padded[:-1] + b" \n", **kwargs)
    assert result is startup.ClaudeStartupVerdict.RECORD_TOO_LARGE


@pytest.mark.parametrize("part", ["effective", "policy-source", "source-row", "applied"])
def test_every_missing_fixed_fact_refuses(part):
    original = settings()
    target = {"effective": original["effective"],
              "policy-source": original["sources"][0]["settings"],
              "source-row": original["sources"][0], "applied": original["applied"]}[part]
    for key in target:
        body = deepcopy(original)
        edited = {"effective": body["effective"],
                  "policy-source": body["sources"][0]["settings"],
                  "source-row": body["sources"][0], "applied": body["applied"]}[part]
        del edited[key]
        assert judge_settings(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH


def test_every_missing_hook_fact_refuses():
    original = hooks()
    for location in [None, "policy", "safeMode", "event"]:
        target = (original if location is None else original["eventCatalog"][0]
                  if location == "event" else original[location])
        for key in target:
            body = deepcopy(original)
            edited = (body if location is None else body["eventCatalog"][0]
                      if location == "event" else body[location])
            del edited[key]
            assert judge_hooks(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH


def test_hook_catalog_count_and_summary_bounds_bind_without_learning_authority():
    body = hooks()
    template = body["eventCatalog"][0]
    body["eventCatalog"] = [{**template, "name": f"event-{i}"}
                            for i in range(startup.MAX_HOOK_EVENTS)]
    assert judge_hooks(body) is startup.ClaudeStartupVerdict.MATCH
    body["eventCatalog"].append({**template, "name": "one-too-many"})
    assert judge_hooks(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH
    body = hooks()
    body["eventCatalog"][0]["summary"] = "x" * 4096
    assert judge_hooks(body) is startup.ClaudeStartupVerdict.MATCH
    body["eventCatalog"][0]["summary"] += "x"
    assert judge_hooks(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH


@pytest.mark.parametrize("name", ["userSettings", "projectSettings",
                                 "localSettings", "flagSettings"])
def test_real_additional_source_names_only_admit_protected_env(name):
    body = settings()
    body["sources"].append({"source": name, "settings": {"env": {"NODE_OPTIONS": "ignored"}}})
    assert judge_settings(body) is startup.ClaudeStartupVerdict.MATCH
    body["sources"][-1]["settings"]["hooks"] = {}
    assert judge_settings(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH


@pytest.mark.parametrize("raw", [None, True, "{}\n", b"\n"])
def test_nonbytes_and_nonobjects_refuse(raw):
    result = startup.judge_hooks(raw, expected_request_id="observe-1")
    assert result is not startup.ClaudeStartupVerdict.MATCH


@pytest.mark.parametrize("envelope", [
    {}, {"subtype": "success", "request_id": True, "response": {}},
    {"subtype": "unknown", "request_id": "observe-1", "response": {}},
    {"subtype": "success", "request_id": "observe-1", "response": []},
    {"subtype": "error", "request_id": "observe-1", "error": 1},
    {"subtype": "error", "request_id": "observe-1", "error": "secret", "error_code": 1},
])
def test_control_envelope_has_no_coercive_success(envelope):
    raw = json.dumps({"type": "control_response", "response": envelope}).encode() + b"\n"
    result = startup.judge_hooks(raw, expected_request_id="observe-1")
    assert result is startup.ClaudeStartupVerdict.RESPONSE_INVALID


def test_bytearray_of_accepting_record_is_not_bytes():
    result = startup.judge_hooks(bytearray(wire(hooks())), expected_request_id="observe-1")
    assert result is startup.ClaudeStartupVerdict.RECORD_INVALID


def test_outer_extra_field_and_tag_are_not_discarded():
    value = json.loads(wire(hooks()))
    value["private-extra"] = "secret"
    raw = json.dumps(value).encode() + b"\n"
    result = startup.judge_hooks(raw, expected_request_id="observe-1")
    assert result is startup.ClaudeStartupVerdict.RESPONSE_INVALID
    del value["private-extra"]
    value["type"] = "other"
    raw = json.dumps(value).encode() + b"\n"
    result = startup.judge_hooks(raw, expected_request_id="observe-1")
    assert result is startup.ClaudeStartupVerdict.RESPONSE_INVALID


def test_hooks_catalog_rejects_duplicate_names_and_unknown_row_fields():
    body = hooks()
    body["eventCatalog"].append(deepcopy(body["eventCatalog"][0]))
    assert judge_hooks(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH
    body = hooks()
    body["eventCatalog"][0]["unknown"] = "secret"
    assert judge_hooks(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH


def test_safe_mode_is_exact_and_cannot_be_inferred_from_hook_absence():
    for value in [{"managedHooksStillApply": False, "exitHint": "restart without --safe-mode"},
                  {"managedHooksStillApply": True, "exitHint": "unset CLAUDE_CODE_SAFE_MODE"},
                  True]:
        body = hooks()
        body["safeMode"] = value
        assert judge_hooks(body) is startup.ClaudeStartupVerdict.CONFIGURATION_MISMATCH


def test_successful_request_builders_bind_their_own_record_ceiling():
    for build in [startup.settings_request, startup.hooks_request]:
        overhead = len(build("x")) - 1
        assert len(build("x" * (startup.RECORD_BYTES - overhead))) == startup.RECORD_BYTES
        with pytest.raises(ValueError, match="Claude startup request too large"):
            build("x" * (startup.RECORD_BYTES - overhead + 1))


def test_sealed_strings_are_exact_types():
    class StringSubclass(str):
        pass

    for model, effort in [(StringSubclass(MODEL), EFFORT), (MODEL, StringSubclass(EFFORT))]:
        with pytest.raises(ValueError, match="invalid sealed Claude model or effort"):
            startup.judge_settings(wire(settings()), expected_request_id="observe-1",
                                   model=model, effort=effort)
