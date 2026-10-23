"""Pinned Claude initialize bytes, with no SDK, process, credentials or network."""

from __future__ import annotations

import json
from copy import deepcopy
from enum import StrEnum

import pytest

from constructicon.substrate.executors import claude_protocol as protocol


def reply(plan="Claude Pro"):
    return {
        "type": "control_response",
        "response": {
            "subtype": "success",
            "request_id": "initialize-1",
            "response": {
                "commands": [], "agents": [], "models": [],
                "output_style": "default", "available_output_styles": ["default"],
                "account": {"apiProvider": "firstParty", "subscriptionType": plan},
                "claude_code_version": "2.1.296", "session_state": "idle",
            },
            "pending_permission_requests": [], "pending_user_dialog_requests": [],
        },
    }


def wire(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"


def judge(record, plan=None):
    return protocol.judge_initialize(
        record, expected_request_id="initialize-1",
        selected_plan=protocol.ClaudePlan.PRO if plan is None else plan,
    )


@pytest.mark.parametrize("plan", ["PRO", "MAX"])
def test_selected_plan_permits_exact_current_initialize(plan):
    selected = protocol.ClaudePlan[plan]
    result = judge(wire(reply(selected.value)), selected)
    assert result is protocol.ClaudeInitializeVerdict.MODE_MATCH
    assert protocol.classify_initialize(
        wire(reply(selected.value)), expected_request_id="initialize-1", selected_plan=selected,
    ) == (result, None)


@pytest.mark.parametrize("plan", list(protocol.ClaudePlan))
@pytest.mark.parametrize("account,expected", [
    (None, "ACCOUNT_SHAPE"),
    ([], "ACCOUNT_SHAPE"),
    ({"private-field": "private-value", "tokenSource": None}, "UNSUPPORTED_ACCOUNT_FIELD"),
    ({"tokenSource": None}, "CREDENTIAL_SOURCE_PRESENT"),
    ({"apiKeySource": "private-source"}, "CREDENTIAL_SOURCE_PRESENT"),
    ({"apiProvider": "private-provider", "email": None}, "ACCOUNT_VALUE_TYPE"),
    ({"apiProvider": "private-provider", "subscriptionType": "Claude API"}, "PROVIDER_MISMATCH"),
    ({"subscriptionType": "Claude API"}, "PROVIDER_MISMATCH"),
    ({"apiProvider": "firstParty"}, "SUBSCRIPTION_MISMATCH"),
    ({"apiProvider": "firstParty", "subscriptionType": "private-plan"}, "SUBSCRIPTION_MISMATCH"),
    ({"apiProvider": "firstParty", "subscriptionType": "Claude API",
      "email": "private-identity", "organization": "private-organization"}, "AMBIGUOUS_API"),
])
def test_shared_classifier_preserves_refusal_categories_and_precedence(plan, account, expected):
    value = reply()
    value["response"]["response"]["account"] = account
    raw = wire(value)
    result = protocol.classify_initialize(
        raw, expected_request_id="initialize-1", selected_plan=plan,
    )
    assert result == (protocol.ClaudeInitializeVerdict.MODE_MISMATCH,
                      protocol.ClaudeModeMismatchReason[expected])
    assert judge(raw, plan) is result[0]
    assert "private" not in repr(result)


@pytest.mark.parametrize("damage,expected", [
    ("record", "RECORD_INVALID"), ("response", "RESPONSE_INVALID"),
    ("request", "REQUEST_MISMATCH"), ("error", "INITIALIZE_ERROR"),
    ("pending", "INITIALIZE_BUSY"), ("version", "RESPONSE_INVALID"),
    ("state", "INITIALIZE_BUSY"), ("bound", "RECORD_TOO_LARGE"),
])
def test_non_mode_refusals_never_publish_account_reason(damage, expected):
    value = reply("Claude API")
    envelope = value["response"]
    if damage == "response":
        value["private-field"] = "private-value"
    elif damage == "request":
        envelope["request_id"] = "private-id"
    elif damage == "error":
        value["response"] = {"subtype": "error", "request_id": "initialize-1",
                             "error": "private-error"}
    elif damage == "pending":
        envelope["pending_user_dialog_requests"] = [{"prompt": "private-prompt"}]
    elif damage == "version":
        envelope["response"]["claude_code_version"] = "private-version"
    elif damage == "state":
        envelope["response"]["session_state"] = "running"
    raw = wire(value)
    if damage == "record":
        raw = raw[:-1]
    elif damage == "bound":
        raw = b" " * protocol.RECORD_BYTES + raw
    result = protocol.classify_initialize(
        raw, expected_request_id="initialize-1", selected_plan=protocol.ClaudePlan.PRO,
    )
    assert result == (protocol.ClaudeInitializeVerdict[expected], None)
    assert judge(raw) is result[0]
    assert "private" not in repr(result)


def test_request_is_only_documented_bare_initialize_and_lf():
    raw = protocol.initialize_request("initialize-1")
    assert raw.endswith(b"\n") and raw.count(b"\n") == 1
    assert json.loads(raw) == {
        "type": "control_request", "request_id": "initialize-1",
        "request": {"subtype": "initialize"},
    }
    assert len(raw) <= protocol.RECORD_BYTES


def test_builder_and_judgment_argument_types_are_strict_and_static():
    class StringSubclass(str):
        pass

    class OtherPlan(StrEnum):
        PRO = "Claude Pro"

    with pytest.raises(ValueError, match=r"^invalid initialize request id$"):
        protocol.initialize_request(StringSubclass("initialize-1"))
    with pytest.raises(ValueError, match=r"^invalid selected Claude plan$"):
        judge(wire(reply()), OtherPlan.PRO)
    with pytest.raises(ValueError, match=r"^invalid selected Claude plan$"):
        judge(wire(reply()), "Claude Pro")
    with pytest.raises(ValueError, match=r"^invalid initialize request id$"):
        protocol.judge_initialize(
            wire(reply()), expected_request_id="secret\ud800",
            selected_plan=protocol.ClaudePlan.PRO,
        )


@pytest.mark.parametrize(
    "request_id", [None, True, 1, "", "secret\ud800", "s" * (256 * 1024)],
    ids=["null", "boolean", "integer", "empty", "surrogate", "over-bound"],
)
def test_request_invalid_arguments_have_static_errors(request_id):
    with pytest.raises(ValueError) as caught:
        protocol.initialize_request(request_id)
    assert str(caught.value) in {"invalid initialize request id", "initialize request too large"}
    assert caught.value.__cause__ is None


def test_other_subscription_plan_is_not_a_fallback():
    assert judge(wire(reply("Claude Max"))) is protocol.ClaudeInitializeVerdict.MODE_MISMATCH
    result = judge(wire(reply()), protocol.ClaudePlan.MAX)
    assert result is protocol.ClaudeInitializeVerdict.MODE_MISMATCH


@pytest.mark.parametrize("provider", ["bedrock", "vertex", "foundry", "anthropicAws",
                                      "anthropicGoogleCloud", "mantle", "gateway", "unknown"])
def test_every_other_provider_refuses(provider):
    value = reply()
    value["response"]["response"]["account"]["apiProvider"] = provider
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.MODE_MISMATCH


@pytest.mark.parametrize("plan", ["Claude Team", "Claude Enterprise", "Claude API", "", "unknown"])
def test_every_unselected_plan_refuses(plan):
    assert judge(wire(reply(plan))) is protocol.ClaudeInitializeVerdict.MODE_MISMATCH


@pytest.mark.parametrize("field", ["tokenSource", "apiKeySource"])
@pytest.mark.parametrize("value", [None, "secret-source"])
def test_auth_source_membership_refuses_even_explicit_null(field, value):
    record = reply()
    record["response"]["response"]["account"][field] = value
    assert judge(wire(record)) is protocol.ClaudeInitializeVerdict.MODE_MISMATCH


@pytest.mark.parametrize("field", ["email", "organization"])
def test_private_account_fields_are_typed_then_discarded(field):
    value = reply()
    value["response"]["response"]["account"][field] = "secret-account-identity"
    result = judge(wire(value))
    assert result is protocol.ClaudeInitializeVerdict.MODE_MATCH
    assert "secret" not in repr(result)
    value["response"]["response"]["account"][field] = None
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.MODE_MISMATCH


def test_unknown_account_field_refuses():
    value = reply()
    value["response"]["response"]["account"]["secret-unknown"] = "secret-value"
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.MODE_MISMATCH


@pytest.mark.parametrize("field", ["apiProvider", "subscriptionType"])
@pytest.mark.parametrize("value", [None, True, 1, [], {}])
def test_required_account_fields_never_coerce(field, value):
    record = reply()
    record["response"]["response"]["account"][field] = value
    assert judge(wire(record)) is protocol.ClaudeInitializeVerdict.MODE_MISMATCH


@pytest.mark.parametrize("field", ["apiProvider", "subscriptionType"])
def test_required_account_facts_are_not_inferred(field):
    value = reply()
    del value["response"]["response"]["account"][field]
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.MODE_MISMATCH


@pytest.mark.parametrize("part", ["outer", "envelope"])
def test_unknown_envelope_keys_refuse(part):
    value = reply()
    target = value if part == "outer" else value["response"]
    target["secret-extension"] = "secret-value"
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.RESPONSE_INVALID


@pytest.mark.parametrize("part", ["type", "subtype"])
def test_wrong_response_tags_refuse(part):
    value = reply()
    if part == "type":
        value["type"] = "control_request"
    else:
        value["response"]["subtype"] = "unknown"
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.RESPONSE_INVALID


@pytest.mark.parametrize("field", ["claude_code_version", "session_state", "account"])
def test_current_initialize_required_fields_cannot_be_omitted(field):
    value = reply()
    del value["response"]["response"][field]
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.RESPONSE_INVALID


@pytest.mark.parametrize("version", ["2.1.267", "2.1.295", "", None, 2.1296])
def test_reported_version_must_match_current_pin(version):
    value = reply()
    value["response"]["response"]["claude_code_version"] = version
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.RESPONSE_INVALID


@pytest.mark.parametrize("state", ["running", "requires_action", "unknown", None, True])
def test_nonidle_state_refuses_without_startup_claim(state):
    value = reply()
    value["response"]["response"]["session_state"] = state
    expected = (
        protocol.ClaudeInitializeVerdict.INITIALIZE_BUSY if state in ("running", "requires_action")
        else protocol.ClaudeInitializeVerdict.RESPONSE_INVALID
    )
    assert judge(wire(value)) is expected


@pytest.mark.parametrize("field", ["pending_permission_requests", "pending_user_dialog_requests"])
def test_pending_presence_is_not_inferred(field):
    value = reply()
    del value["response"][field]
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.RESPONSE_INVALID


@pytest.mark.parametrize("field", ["pending_permission_requests", "pending_user_dialog_requests"])
def test_pending_requests_refuse_without_publishing_prompt(field):
    value = reply()
    value["response"][field] = [{"request_id": "secret-id", "prompt": "secret-prompt"}]
    result = judge(wire(value))
    assert result is protocol.ClaudeInitializeVerdict.INITIALIZE_BUSY
    assert "secret" not in repr(result)


@pytest.mark.parametrize("field", ["pending_permission_requests", "pending_user_dialog_requests"])
@pytest.mark.parametrize("value", [None, {}, "secret-prompt", False])
def test_pending_lists_have_exact_type(field, value):
    record = reply()
    record["response"][field] = value
    assert judge(wire(record)) is protocol.ClaudeInitializeVerdict.RESPONSE_INVALID


@pytest.mark.parametrize("subtype", ["success", "error"])
def test_response_id_is_correlated_before_any_verdict(subtype):
    value = reply()
    if subtype == "error":
        value["response"] = {"subtype": "error", "request_id": "wrong-id", "error": "secret-error"}
    else:
        value["response"]["request_id"] = "wrong-id"
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.REQUEST_MISMATCH


def test_error_envelope_has_only_static_verdict():
    value = {"type": "control_response", "response": {
        "subtype": "error", "request_id": "initialize-1", "error": "secret-error",
        "error_code": "secret-code", "pending_permission_requests": [],
    }}
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.INITIALIZE_ERROR
    value["response"]["secret-extension"] = "secret-value"
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.RESPONSE_INVALID
    del value["response"]["secret-extension"]
    value["response"]["error_code"] = None
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.RESPONSE_INVALID


@pytest.mark.parametrize("field", ["error", "error_code", "pending_permission_requests",
                                    "pending_user_dialog_requests"])
def test_error_fields_are_typed_without_publishing_them(field):
    value = {"type": "control_response", "response": {
        "subtype": "error", "request_id": "initialize-1", "error": "secret-error",
    }}
    value["response"][field] = None
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.RESPONSE_INVALID


@pytest.mark.parametrize("request_id", [None, True, 1, [], {}])
def test_response_id_is_a_string_not_coerced(request_id):
    value = reply()
    value["response"]["request_id"] = request_id
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.RESPONSE_INVALID


@pytest.mark.parametrize("value", [None, True, 1, "secret", [], {}])
def test_wrong_outer_shapes_refuse(value):
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.RESPONSE_INVALID


@pytest.mark.parametrize("part", ["envelope", "body", "account"])
@pytest.mark.parametrize("value", [None, True, 1, "secret", []])
def test_wrong_nested_shapes_refuse(part, value):
    record = reply()
    if part == "envelope":
        record["response"] = value
    elif part == "body":
        record["response"]["response"] = value
    else:
        record["response"]["response"]["account"] = value
    expected = (protocol.ClaudeInitializeVerdict.MODE_MISMATCH if part == "account"
                else protocol.ClaudeInitializeVerdict.RESPONSE_INVALID)
    assert judge(wire(record)) is expected


@pytest.mark.parametrize("raw", [b"", b"{}", b"{}\r\n", b"{}\n{}\n", b"{\n}\n",
                                b"\xff\n", b"not-json-secret\n", b'{"secret":NaN}\n',
                                b'{"secret":Infinity}\n', b'{"secret":"\\ud800"}\n',
                                b'{' + b'"secret":0,' * 2 + b'"final":0}\n',
                                b"[" * 2000 + b"0" + b"]" * 2000 + b"\n"],
                         ids=["empty", "unterminated", "crlf", "multiple", "physical-newline",
                              "utf8", "json", "nan", "infinity", "surrogate", "duplicate",
                              "recursion"])
def test_malformed_records_have_static_invalid_verdict(raw):
    result = judge(raw)
    assert result is protocol.ClaudeInitializeVerdict.RECORD_INVALID
    assert "secret" not in repr(result)


def test_valid_looking_duplicate_key_is_not_last_value_wins():
    raw = wire(reply()).replace(b'"apiProvider":"firstParty"',
                               b'"apiProvider":"bedrock","apiProvider":"firstParty"')
    assert judge(raw) is protocol.ClaudeInitializeVerdict.RECORD_INVALID


def test_one_complete_lf_frame_is_required_even_for_matching_mode():
    raw = wire(reply())
    for malformed in (raw[:-1] + b" ", raw[:-1] + b"\r\n",
                      raw.replace(b'{"type"', b'{\n"type"')):
        assert judge(malformed) is protocol.ClaudeInitializeVerdict.RECORD_INVALID


def test_record_requires_exact_bytes_type():
    class BytesSubclass(bytes):
        pass

    assert judge(BytesSubclass(wire(reply()))) is protocol.ClaudeInitializeVerdict.RECORD_INVALID


@pytest.mark.parametrize("record", [None, "secret-record", bytearray(b"secret-record")])
def test_nonbytes_record_refuses(record):
    assert judge(record) is protocol.ClaudeInitializeVerdict.RECORD_INVALID


def test_record_byte_ceiling_accepts_limit_and_refuses_next_byte():
    value = reply()
    value["response"]["response"]["unjudged_metadata"] = ""
    padding = protocol.RECORD_BYTES - len(wire(value))
    value["response"]["response"]["unjudged_metadata"] = "x" * padding
    raw = wire(value)
    assert len(raw) == protocol.RECORD_BYTES
    assert judge(raw) is protocol.ClaudeInitializeVerdict.MODE_MATCH
    assert judge(raw[:-1] + b" \n") is protocol.ClaudeInitializeVerdict.RECORD_TOO_LARGE


def test_unjudged_bounded_metadata_is_not_a_new_initialize_schema():
    value = deepcopy(reply())
    value["response"]["response"]["commands"] = [{"description": "secret-description"}]
    value["response"]["response"]["new_vendor_metadata"] = {"secret": [1, 2, 3]}
    assert judge(wire(value)) is protocol.ClaudeInitializeVerdict.MODE_MATCH


def test_every_published_verdict_is_finite_and_privacy_safe():
    assert {item.value for item in protocol.ClaudeInitializeVerdict} == {
        "mode-match", "record-invalid", "record-too-large", "response-invalid",
        "request-mismatch", "initialize-error", "initialize-busy", "mode-mismatch",
    }
    assert max(len(item.value.encode()) for item in protocol.ClaudeInitializeVerdict) <= 16
    assert {item.value for item in protocol.ClaudePlan} == {"Claude Pro", "Claude Max"}
