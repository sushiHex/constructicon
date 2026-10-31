"""Closed source-label observations, never credential values or admission credit."""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

import pytest

from constructicon.substrate.executors import claude_maintenance_mode as maintenance
from constructicon.substrate.executors import claude_protocol as protocol
from constructicon.substrate.executors.claude_startup_qualification import (
    ClaudeStartupQualification,
    _Refused,
)
from tests.substrate.test_claude_maintenance_mode import Channel, response
from tests.substrate.test_claude_protocol import reply, wire

TOKEN_LABELS = {
    "none": "none", "ANTHROPIC_AUTH_TOKEN": "auth-token-env",
    "CLAUDE_CODE_OAUTH_TOKEN": "oauth-token-env",
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR": "oauth-token-fd",
    "CCR_OAUTH_TOKEN_FILE": "ccr-oauth-file", "apiKeyHelper": "api-key-helper",
    "claude.ai": "claude-ai",
}
API_LABELS = {"ANTHROPIC_API_KEY": "anthropic-api-key", "apiKeyHelper": "api-key-helper",
              "/login managed key": "login-managed-key"}


def observed(raw):
    try:
        return protocol.observe_initialize(
            raw, expected_request_id="initialize-1", mode=protocol.ClaudeAuthMode.SUBSCRIPTION,
        )
    except Exception:
        raise AssertionError("bounded initialization must return a closed observation") from None


@pytest.mark.parametrize("key,value,expected", [
    *(("tokenSource", value, category) for value, category in TOKEN_LABELS.items()),
    *(("apiKeySource", value, category) for value, category in API_LABELS.items()),
    *((key, value, expected) for key in ("tokenSource", "apiKeySource")
      for value, expected in ((None, "null"), (123, "non-string"), (False, "non-string"),
                              ([], "non-string"), ({"private-sentinel": 1}, "non-string"),
                              ("private-sentinel", "unknown"), ("", "unknown"))),
    ("tokenSource", "profile", "unknown"), ("tokenSource", "ANTHROPIC_API_KEY", "unknown"),
    ("apiKeySource", "none", "unknown"), ("apiKeySource", "claude.ai", "unknown"),
])
def test_per_key_reported_labels_are_finite_and_never_normalized_to_absence(key, value, expected):
    native = reply()
    native["response"]["response"]["account"].update({key: value})
    result = observed(wire(native))
    assert result.verdict is protocol.ClaudeInitializeVerdict.MODE_MISMATCH
    assert result.reason is protocol.ClaudeModeMismatchReason.CREDENTIAL_SOURCE_PRESENT
    token, api_key = result.token_source_category, result.api_key_source_category
    assert (token.value if key == "tokenSource" else api_key.value) == expected
    assert (api_key.value if key == "tokenSource" else token.value) == "absent"
    assert protocol.classify_initialize(
        wire(native), expected_request_id="initialize-1", mode=protocol.ClaudeAuthMode.SUBSCRIPTION,
    ) == (result.verdict, result.reason)
    assert "private-sentinel" not in json.dumps(asdict(result))
    assert protocol.initialize_diagnostics_valid(result.verdict, result.reason, token, api_key)


def test_absent_is_affirmative_only_after_account_classification():
    result = observed(wire(reply()))
    assert result.verdict is protocol.ClaudeInitializeVerdict.MODE_MATCH
    assert result.token_source_category is protocol.ClaudeTokenSourceCategory.ABSENT
    assert result.api_key_source_category is protocol.ClaudeApiKeySourceCategory.ABSENT
    for raw in (b"not-json\n", b"{}\n", wire({**reply(), "private-sentinel": True})):
        invalid = observed(raw)
        assert invalid.token_source_category is invalid.api_key_source_category is None
    native = reply()
    native["response"]["response"]["account"] = None
    invalid = observed(wire(native))
    assert invalid.reason is protocol.ClaudeModeMismatchReason.ACCOUNT_SHAPE
    assert invalid.token_source_category is invalid.api_key_source_category is None


@pytest.mark.parametrize("display", ["Claude Pro", "Claude Max", "Claude Team",
                                     "Claude Enterprise", "Claude Private-custom+"])
def test_compatible_display_observations_never_publish_account_or_tier(display):
    native = reply(display)
    native["response"]["response"]["account"].update({
        "email": "private-identity", "organization": "private-organization",
    })
    result = observed(wire(native))
    assert asdict(result) == {
        "verdict": protocol.ClaudeInitializeVerdict.MODE_MATCH,
        "reason": None,
        "token_source_category": protocol.ClaudeTokenSourceCategory.ABSENT,
        "api_key_source_category": protocol.ClaudeApiKeySourceCategory.ABSENT,
    }
    public = json.dumps(asdict(result))
    assert display not in public
    assert "private" not in public.lower()


@pytest.mark.parametrize("kind", ["mode", "qualification"])
@pytest.mark.parametrize("account,reason,token,api_key", [
    ({"tokenSource": "none"}, "credential-source-present", "none", "absent"),
    ({"apiKeySource": "private-sentinel"}, "credential-source-present", "absent", "unknown"),
    ({"tokenSource": None, "apiKeySource": False},
     "credential-source-present", "null", "non-string"),
    ({"apiProvider": "private-sentinel"}, "provider-mismatch", "absent", "absent"),
])
async def test_both_owned_conversations_capture_the_actual_observation_before_refusal(
    kind, account, reason, token, api_key,
):
    raw = response("@ID@", **account)
    channel = Channel([raw])
    limits = {"mode": protocol.ClaudeAuthMode.SUBSCRIPTION, "input_limit": 8192,
              "output_limit": 512 * 1024, "deadline": asyncio.get_running_loop().time() + 5}
    if kind == "mode":
        conversation = maintenance.ClaudeMaintenanceConversation(
            phase=maintenance.ClaudeMaintenancePhase.RELOAD, **limits,
        )
        error = maintenance._Refused
    else:
        conversation = ClaudeStartupQualification(model="reviewed-model", effort="low", **limits)
        error = _Refused
    with pytest.raises(error):
        await conversation(channel)
    # Assert captured state before constructing facts: capture-loss mutants
    # fail an assertion rather than merely erroring in fact validation.
    assert conversation.mode_mismatch_reason is not None
    assert conversation.mode_mismatch_reason.value == reason
    assert conversation.token_source_category is not None
    assert conversation.api_key_source_category is not None
    assert conversation.token_source_category.value == token
    assert conversation.api_key_source_category.value == api_key
    assert len(channel.writes) == 1 and not conversation.stdin_closed
    assert channel.active_readers == 0
    if kind == "qualification":
        facts = conversation.facts
        assert facts.mode_mismatch_reason.value == reason
        assert facts.token_source_category.value == token
        assert facts.api_key_source_category.value == api_key
        assert facts.settings_verdict is facts.hooks_verdict is None
        assert "private-sentinel" not in json.dumps(asdict(facts))


@pytest.mark.parametrize("kind", ["mode", "qualification"])
async def test_unclassified_conversations_do_not_invent_absent_sources(kind):
    limits = {"mode": protocol.ClaudeAuthMode.SUBSCRIPTION, "input_limit": 8192,
              "output_limit": 512 * 1024, "deadline": asyncio.get_running_loop().time() + 5}
    conversation = (maintenance.ClaudeMaintenanceConversation(
        phase=maintenance.ClaudeMaintenancePhase.OBSERVE, **limits,
    ) if kind == "mode" else ClaudeStartupQualification(model="model", effort="low", **limits))
    assert conversation.token_source_category is conversation.api_key_source_category is None


@pytest.mark.parametrize("account", [{}, {"tokenSource": "private-sentinel" * 1000},
                                      {"apiKeySource": "private-sentinel" * 1000}])
def test_all_initialization_public_fields_have_closed_types_and_finite_bounds(account):
    native = reply()
    native["response"]["response"]["account"].update(account)
    result = observed(wire(native))
    assert set(asdict(result)) == {
        "verdict", "reason", "token_source_category", "api_key_source_category",
    }
    fields = {"verdict": protocol.ClaudeInitializeVerdict,
              "reason": protocol.ClaudeModeMismatchReason,
              "token_source_category": protocol.ClaudeTokenSourceCategory,
              "api_key_source_category": protocol.ClaudeApiKeySourceCategory}
    for name, enum in fields.items():
        value = getattr(result, name)
        assert value is None or type(value) is enum
        assert all(len(tag.value.encode()) <= 32 for tag in enum)
    assert len(json.dumps(asdict(result)).encode()) < 256
    assert "private-sentinel" not in json.dumps(asdict(result))


@pytest.mark.parametrize("change", [
    {"verdict": None}, {"reason": protocol.ClaudeModeMismatchReason.PROVIDER_MISMATCH},
    {"token_source_category": protocol.ClaudeTokenSourceCategory.NONE},
    {"api_key_source_category": None}, {"token_source_category": "private-sentinel"},
])
def test_shared_observation_cannot_construct_incoherent_public_diagnostics(change):
    values = asdict(observed(wire(reply())))
    values.update(change)
    with pytest.raises(ValueError, match=r"^invalid Claude initialization observation$"):
        protocol.ClaudeInitializeObservation(**values)
