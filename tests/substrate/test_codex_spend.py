"""N4's pure protocol additions: the spend readback and the notice allowlist.

Portable, credential-free, scripted values only (M8-N4-state-review.md,
sections 2 and 3). Every refusal has an accepting twin.
"""

from __future__ import annotations

import json

import pytest

from constructicon.core.executor import RateLimitInfo
from constructicon.substrate.executors.codex_protocol import (
    ACCOUNT_NOTICE_FAULT,
    CREDITS_FAULT,
    SPEND_FIELDS,
    SPEND_UNREADABLE_FAULT,
    USAGE_FIELDS,
    ExpectedAccount,
    account_faults,
    account_notice_faults,
    encode_record,
    rate_limit_of,
    rate_limits_read_request,
    settings_notice_faults,
    spend_change_faults,
    spend_faults,
    spend_reading,
)
from tests.substrate.test_codex_protocol import (
    ACCOUNT_ID,
    CLEAN_SPEND,
    EMAIL,
    EXPECTED,
    MANAGED,
    codex_bucket,
    spend_result,
)

QUALIFYING = ExpectedAccount(plan_type="pro", alternatives=("prolite",))


# --- the request -------------------------------------------------------------


def test_the_readback_request_is_exactly_the_pinned_wire_form():
    assert rate_limits_read_request(7) == {"id": 7, "method": "account/rateLimits/read"}
    assert encode_record(rate_limits_read_request(7)) == (
        b'{"id": 7, "method": "account/rateLimits/read"}\n'
    )


# --- the bound ---------------------------------------------------------------


@pytest.mark.parametrize("balance", [None, "0", "0.00", "-0", "000"])
def test_zero_purchased_credits_pass_the_bound(balance):
    reply = {"result": spend_result(credits={
        "hasCredits": False, "unlimited": False, "balance": balance,
    })}
    assert spend_faults(spend_reading(reply), EXPECTED) == ()


@pytest.mark.parametrize("credits", [
    {"hasCredits": True, "unlimited": False, "balance": None},
    {"hasCredits": False, "unlimited": True, "balance": None},
    {"hasCredits": False, "unlimited": False, "balance": "0.01"},
    {"hasCredits": False, "unlimited": False, "balance": "1"},
    {"hasCredits": False, "unlimited": False, "balance": "-1"},
    {"hasCredits": False, "unlimited": False, "balance": "1e400"},
    {"hasCredits": False, "unlimited": False, "balance": "abc"},
    {"hasCredits": False, "unlimited": False, "balance": "0." + "0" * 31},
    {"hasCredits": False, "unlimited": False, "balance": 0},
    {"hasCredits": "false", "unlimited": False, "balance": None},
    {"unlimited": False, "balance": None},
    None,
], ids=[
    "has-credits", "unlimited", "cents", "one", "negative", "exponent", "text",
    "over-long", "non-string", "string-flag", "flag-absent", "credits-absent",
])
def test_anything_but_proven_zero_credits_refuses(credits):
    reading = spend_reading({"result": spend_result(credits=credits)})
    assert CREDITS_FAULT in spend_faults(reading, EXPECTED)


@pytest.mark.parametrize("reply", [
    {"error": {"code": -32600, "message": "codex account authentication required"}},
    {"result": None},
    {"result": {"rateLimits": codex_bucket()}},
    {"result": {**CLEAN_SPEND, "rateLimitsByLimitId": {}}},
    {"result": {**CLEAN_SPEND, "rateLimitsByLimitId": {"codex": codex_bucket(limitId=None)}}},
    {"result": {**CLEAN_SPEND, "rateLimitsByLimitId": {"codex": codex_bucket(limitId="other")}}},
    {"result": {**CLEAN_SPEND, "rateLimitsByLimitId": ["codex"]}},
], ids=["error", "no-result", "headline-only", "empty-map", "id-less", "other-id", "not-a-map"])
def test_an_unreadable_or_unidentified_codex_bucket_refuses(reply):
    assert spend_reading(reply) is None
    assert spend_faults(spend_reading(reply), EXPECTED) == (SPEND_UNREADABLE_FAULT,)


def test_the_headline_bucket_is_never_the_one_judged():
    """The vendor falls back to the first bucket when no ``codex`` one exists."""

    dirty = codex_bucket(limitId="other", credits={
        "hasCredits": True, "unlimited": False, "balance": "5",
    })
    clean_headline = {**CLEAN_SPEND, "rateLimitsByLimitId": {
        "codex": codex_bucket(credits={"hasCredits": True, "unlimited": False, "balance": "5"}),
    }}
    assert CREDITS_FAULT in spend_faults(spend_reading({"result": clean_headline}), EXPECTED)
    dirty_headline = {**CLEAN_SPEND, "rateLimits": dirty}
    assert spend_faults(spend_reading({"result": dirty_headline}), EXPECTED) == ()


@pytest.mark.parametrize("plan", [None, "pro"])
def test_an_absent_or_expected_readback_plan_passes(plan):
    assert spend_faults(spend_reading({"result": spend_result(planType=plan)}), EXPECTED) == ()


def test_another_readback_plan_refuses_and_names_only_a_short_literal():
    faults = spend_faults(spend_reading({"result": spend_result(planType="plus")}), EXPECTED)
    assert any("'plus'" in fault for fault in faults)
    faults = spend_faults(spend_reading({"result": spend_result(planType=EMAIL)}), EXPECTED)
    assert faults and not any(EMAIL in fault for fault in faults)


# --- the change rule ---------------------------------------------------------


@pytest.mark.parametrize("field,changes", [
    ("has_credits", {"credits": {"hasCredits": True, "unlimited": False, "balance": None}}),
    ("unlimited", {"credits": {"hasCredits": False, "unlimited": True, "balance": None}}),
    ("balance_zero", {"credits": {"hasCredits": False, "unlimited": False, "balance": "0"}}),
    ("spend_control_reached", {"spendControlReached": True}),
    ("rate_limit_reached", {"rateLimitReachedType": "rate_limit_reached"}),
])
def test_each_overage_field_that_moves_across_the_turn_refuses(field, changes):
    before = spend_reading({"result": CLEAN_SPEND})
    after = spend_reading({"result": spend_result(**changes)})
    assert getattr(before, field) != getattr(after, field)
    faults = spend_change_faults(before, after)
    assert faults == (f"readback {field.replace('_', ' ')} changed across the turn",)


def test_usage_moving_across_the_turn_is_expected():
    before = spend_reading({"result": CLEAN_SPEND})
    after = spend_reading({"result": spend_result(
        primary={"usedPercent": 40, "windowDurationMins": 300, "resetsAt": 1},
    )})
    assert spend_change_faults(before, after) == ()


# --- publication -------------------------------------------------------------


def test_only_the_fixed_vocabulary_is_published_and_no_identity_fact():
    before = spend_reading({"result": CLEAN_SPEND})
    after = spend_reading({"result": spend_result(
        primary={"usedPercent": 9, "windowDurationMins": 300, "resetsAt": 1},
    )})
    published = rate_limit_of(before, after)
    assert isinstance(published, RateLimitInfo) and published.is_using_overage is None
    vocabulary = {
        f"{phase}.{name}" for phase in ("before", "after") for name in SPEND_FIELDS + USAGE_FIELDS
    }
    assert set(published.detail) <= vocabulary
    # Only emitted facts: an absent field is absent, never published as None.
    assert all(value is not None for value in published.detail.values())
    assert published.detail["before.primary_used_percent"] == 3
    assert published.detail["after.primary_used_percent"] == 9
    assert published.detail["after.has_credits"] is False
    text = json.dumps(published.model_dump(mode="json"))
    for planted in (EMAIL, ACCOUNT_ID, "pro", "Codex", "codex"):
        assert planted not in text


def test_no_readback_publishes_nothing_rather_than_an_inferred_zero():
    assert rate_limit_of(None, None) is None


def test_an_oversized_usage_number_is_not_a_fact():
    reading = spend_reading({"result": spend_result(
        primary={"usedPercent": 10 ** 40, "windowDurationMins": 300, "resetsAt": 1},
    )})
    assert reading.primary_used_percent is None


# --- the notice allowlist ----------------------------------------------------


def notice(method, params):
    return {"method": method, "params": params}


@pytest.mark.parametrize("snapshot", [
    codex_bucket(planType=None), {"limitId": "codex"}, codex_bucket(),
], ids=["null-plan", "absent-plan", "expected-plan"])
def test_a_rate_limit_update_with_no_plan_change_passes(snapshot):
    assert account_notice_faults(
        notice("account/rateLimits/updated", {"rateLimits": snapshot}), EXPECTED,
    ) == ()


@pytest.mark.parametrize("params", [
    {"rateLimits": codex_bucket(planType="plus")},
    {"rateLimits": codex_bucket(), "extra": 1},
    {"rateLimits": ["not", "an", "object"]},
    ["rateLimits"],
    None,
], ids=["other-plan", "extra-key", "non-object-snapshot", "non-object-params", "no-params"])
def test_any_other_rate_limit_update_refuses(params):
    faults = account_notice_faults(notice("account/rateLimits/updated", params), EXPECTED)
    assert faults == (ACCOUNT_NOTICE_FAULT.format(method="'account/rateLimits/updated'"),)


@pytest.mark.parametrize("method", [
    "account/updated", "account/login/completed", "account/rateLimits/changed", "account/x",
    "modelProvider/authRecoveryStarted", "modelProvider/authRecoveryCompleted",
    "modelProvider/x",
])
def test_every_other_account_or_provider_notice_refuses_naming_only_the_method(method):
    params = {"provider": "Amazon Bedrock", "message": EMAIL, "authMode": "apikey"}
    faults = account_notice_faults(notice(method, params), EXPECTED)
    assert len(faults) == 1 and method in faults[0]
    assert "Bedrock" not in faults[0] and EMAIL not in faults[0]


@pytest.mark.parametrize("method", ["warning", "item/started", "turn/started", "model/rerouted"])
def test_an_unrelated_notification_is_not_a_refusal(method):
    assert account_notice_faults(notice(method, {"message": EMAIL}), EXPECTED) == ()


def test_the_notice_fault_claims_no_turn():
    """N4-NOTICE-5: the startup phase has no turn, so the text names none."""

    faults = account_notice_faults(notice("account/updated", {}), EXPECTED)
    assert faults == ("the session reported 'account/updated'",)
    assert "turn" not in ACCOUNT_NOTICE_FAULT


@pytest.mark.parametrize("changes", [
    {"credits": {"hasCredits": True, "unlimited": False, "balance": "25.00"}},
    {"credits": {"hasCredits": False, "unlimited": True, "balance": None}},
    {"credits": {"hasCredits": False, "unlimited": False, "balance": "0.01"}},
    {"credits": {"unlimited": False, "balance": None}},
    {"credits": "none"},
    {"spendControlReached": True},
], ids=["purchased", "unlimited", "balance", "no-has-credits", "non-object", "spend-control"])
def test_a_rate_limit_update_showing_spend_refuses(changes):
    """SPEND-3: the one in-band spend record inside the bracketed window."""

    faults = account_notice_faults(
        notice("account/rateLimits/updated", {"rateLimits": codex_bucket(**changes)}), EXPECTED,
    )
    assert faults == (ACCOUNT_NOTICE_FAULT.format(method="'account/rateLimits/updated'"),)


@pytest.mark.parametrize("changes", [
    {"credits": None}, {"credits": {"hasCredits": False, "unlimited": False, "balance": "0"}},
    {"spendControlReached": False}, {"spendControlReached": None},
], ids=["null-credits", "zero-credits", "spend-control-false", "spend-control-null"])
def test_a_sparse_or_zero_spend_update_passes(changes):
    snapshot = codex_bucket(**changes)
    assert account_notice_faults(
        notice("account/rateLimits/updated", {"rateLimits": snapshot}), EXPECTED,
    ) == ()
    del snapshot["credits"], snapshot["spendControlReached"]
    assert account_notice_faults(
        notice("account/rateLimits/updated", {"rateLimits": snapshot}), EXPECTED,
    ) == ()


def settings(**changes):
    thread_settings = {"model": "gpt-5.6-sol", "modelProvider": "openai", **changes}
    return notice("thread/settings/updated", {
        "threadId": "thread-1", "threadSettings": thread_settings,
    })


def test_a_settings_update_naming_the_sealed_model_and_provider_passes():
    assert settings_notice_faults(settings(), model="gpt-5.6-sol", provider="openai") == ()


@pytest.mark.parametrize("record", [
    settings(model="gpt-4.1"), settings(modelProvider="amazon-bedrock"),
    settings(model=None), settings(modelProvider=7),
    notice("thread/settings/updated", {"threadId": "thread-1"}),
    notice("thread/settings/updated", None),
], ids=["model", "provider", "no-model", "non-string-provider", "no-settings", "no-params"])
def test_a_settings_update_changing_or_hiding_model_or_provider_refuses(record):
    """N4-NOTICE-4: a provider change is refused, never silently withheld."""

    faults = settings_notice_faults(record, model="gpt-5.6-sol", provider="openai")
    assert faults == (ACCOUNT_NOTICE_FAULT.format(method="'thread/settings/updated'"),)
    assert "bedrock" not in faults[0]


def test_other_notifications_are_not_settings_updates():
    assert settings_notice_faults(
        notice("turn/started", {"model": "x"}), model="gpt-5.6-sol", provider="openai",
    ) == ()


# --- the qualification plan set (orchestrator decision 1) --------------------


@pytest.mark.parametrize("plan", ["pro", "prolite"])
def test_qualification_accepts_either_declared_literal(plan):
    reply = {"result": {"account": {**MANAGED, "planType": plan}, "requiresOpenaiAuth": True}}
    assert account_faults(reply, QUALIFYING) == ()
    assert spend_faults(spend_reading({"result": spend_result(planType=plan)}), QUALIFYING) == ()


@pytest.mark.parametrize("plan", ["plus", "free", "team", ["pro"]])
def test_qualification_refuses_every_other_plan(plan):
    reply = {"result": {"account": {**MANAGED, "planType": plan}, "requiresOpenaiAuth": True}}
    assert account_faults(reply, QUALIFYING)


def test_a_production_binding_accepts_only_its_recorded_literal():
    recorded = ExpectedAccount(plan_type="prolite")
    reply = {"result": {"account": {**MANAGED, "planType": "pro"}, "requiresOpenaiAuth": True}}
    assert account_faults(reply, recorded)
    assert not recorded.accepts("pro") and recorded.accepts("prolite")


@pytest.mark.parametrize("alternatives", [("",), (" ",), ["prolite"], (1,)])
def test_alternatives_are_non_empty_literals_in_a_tuple(alternatives):
    with pytest.raises(ValueError, match="alternatives"):
        ExpectedAccount(plan_type="pro", alternatives=alternatives)
