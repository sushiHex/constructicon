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
    SPEND_CONTROL_FAULT,
    SPEND_FIELDS,
    SPEND_UNREADABLE_FAULT,
    USAGE_FIELDS,
    ExpectedAccount,
    account_faults,
    account_notice_faults,
    encode_record,
    notice_stop_faults,
    rate_limit_of,
    rate_limits_read_request,
    readback_faults,
    settings_notice_faults,
    spend_faults,
    spend_reading,
    updated_plan,
)
from tests.substrate.test_codex_protocol import (
    ACCOUNT_ID,
    CLEAN_SPEND,
    EMAIL,
    EXPECTED,
    codex_bucket,
    managed,
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


CREDIT_STATES = [
    {"hasCredits": False, "unlimited": False, "balance": "0"},
    {"hasCredits": True, "unlimited": False, "balance": "25.00"},
    {"hasCredits": False, "unlimited": True, "balance": None},
    {"hasCredits": "false", "unlimited": False, "balance": None},
    {"unlimited": False, "balance": None},
    "none",
    None,
]
CREDIT_IDS = [
    "zero", "purchased", "unlimited", "string-flag", "flag-absent", "non-object", "absent",
]


@pytest.mark.parametrize("credits", CREDIT_STATES, ids=CREDIT_IDS)
def test_no_credit_state_refuses_a_turn(credits):
    """The owner's bound (#78): the account's own settings bound overage."""

    reading = spend_reading({"result": spend_result(credits=credits)})
    assert spend_faults(reading, EXPECTED) == ()


@pytest.mark.parametrize("balance,zero", [
    ("0", True), ("0.00", True), ("-0", True), ("000", True),
    ("0.01", False), ("1", False), ("-1", False), ("25.00", False),
    ("1e400", None), ("abc", None), ("0." + "0" * 31, None), (0, None), (None, None),
], ids=[
    "zero", "zero-cents", "negative-zero", "zeros", "cents", "one", "negative", "grant",
    "exponent", "text", "over-long", "non-string", "absent",
])
def test_the_balance_is_published_as_measured_and_malformed_is_unknown(balance, zero):
    reading = spend_reading({"result": spend_result(credits={
        "hasCredits": True, "unlimited": False, "balance": balance,
    })})
    assert reading.balance_zero is zero


def test_a_reached_spend_control_starts_no_turn():
    reading = spend_reading({"result": spend_result(spendControlReached=True)})
    assert spend_faults(reading, EXPECTED) == (SPEND_CONTROL_FAULT,)
    assert readback_faults(reading, EXPECTED) == ()


@pytest.mark.parametrize("stop", [False, None, ...], ids=["false", "null", "absent"])
def test_a_spend_control_not_reported_reached_starts(stop):
    bucket = codex_bucket(spendControlReached=stop)
    if stop is ...:
        del bucket["spendControlReached"]
    reply = {"result": {**CLEAN_SPEND, "rateLimitsByLimitId": {"codex": bucket}}}
    assert spend_faults(spend_reading(reply), EXPECTED) == ()


@pytest.mark.parametrize("stop", ["true", 1, {}], ids=["string", "number", "object"])
def test_a_malformed_spend_control_is_unreadable_never_open(stop):
    reply = {"result": spend_result(spendControlReached=stop)}
    assert spend_reading(reply) is None
    for judge in (readback_faults, spend_faults):
        assert judge(spend_reading(reply), EXPECTED) == (SPEND_UNREADABLE_FAULT,)


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

    dirty = codex_bucket(limitId="other", spendControlReached=True)
    clean_headline = {**CLEAN_SPEND, "rateLimitsByLimitId": {
        "codex": codex_bucket(spendControlReached=True),
    }}
    assert spend_faults(spend_reading({"result": clean_headline}), EXPECTED) == (
        SPEND_CONTROL_FAULT,
    )
    dirty_headline = {**CLEAN_SPEND, "rateLimits": dirty}
    assert spend_faults(spend_reading({"result": dirty_headline}), EXPECTED) == ()


@pytest.mark.parametrize("judge", [readback_faults, spend_faults])
@pytest.mark.parametrize("plan", [None, "pro"])
def test_an_absent_or_expected_readback_plan_passes(plan, judge):
    assert judge(spend_reading({"result": spend_result(planType=plan)}), EXPECTED) == ()


@pytest.mark.parametrize("judge", [readback_faults, spend_faults])
def test_another_readback_plan_refuses_and_names_only_a_short_literal(judge):
    faults = judge(spend_reading({"result": spend_result(planType="plus")}), EXPECTED)
    assert any("'plus'" in fault for fault in faults)
    faults = judge(spend_reading({"result": spend_result(planType=EMAIL)}), EXPECTED)
    assert faults and not any(EMAIL in fault for fault in faults)


# --- after the turn ----------------------------------------------------------


@pytest.mark.parametrize("changes", [
    {"credits": {"hasCredits": True, "unlimited": False, "balance": "24.99"}},
    {"credits": {"hasCredits": False, "unlimited": True, "balance": None}},
    {"spendControlReached": True},
    {"rateLimitReachedType": "rate_limit_reached"},
    {"primary": {"usedPercent": 100, "windowDurationMins": 300, "resetsAt": 1}},
], ids=["credits-drawn", "unlimited", "spend-control", "limit-reached", "usage"])
def test_a_completed_turn_is_never_second_guessed_on_spend(changes):
    """Carry-over is authorized (#78): only the bucket and its plan are judged."""

    assert readback_faults(spend_reading({"result": spend_result(**changes)}), EXPECTED) == ()


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


EXACT_UPDATE = {"authMode": "chatgpt", "planType": "pro"}


@pytest.mark.parametrize(("expected", "plan"), [
    (EXPECTED, "pro"), (QUALIFYING, "pro"), (QUALIFYING, "prolite"),
])
def test_an_exact_account_update_naming_an_accepted_plan_passes(expected, plan):
    """Decision 1 of M8-N5-state-review.md: exactly ``{authMode, planType}``."""
    update = notice("account/updated", {**EXACT_UPDATE, "planType": plan})
    assert account_notice_faults(update, expected) == ()
    assert updated_plan(update, expected) == plan
    # The envelope's top-level timestamp (``common.rs:2048-2058``) is not params.
    assert updated_plan({**update, "emittedAtMs": 1}, expected) == plan


@pytest.mark.parametrize("update", [
    notice("account/updated", {**EXACT_UPDATE, "planType": "plus"}),
    notice("account/updated", {**EXACT_UPDATE, "planType": None}),
    notice("account/updated", {**EXACT_UPDATE, "planType": ["pro"]}),
    notice("account/updated", {**EXACT_UPDATE, "authMode": None}),
    notice("account/updated", {**EXACT_UPDATE, "authMode": "chatgptAuthTokens"}),
    notice("account/updated", {**EXACT_UPDATE, "authMode": "apikey"}),
    notice("account/updated", {**EXACT_UPDATE, "authMode": "ChatGPT"}),
    notice("account/updated", {"planType": "pro"}),
    notice("account/updated", {"authMode": "chatgpt"}),
    notice("account/updated", {**EXACT_UPDATE, "email": EMAIL}),
    notice("account/updated", [EXACT_UPDATE]),
    notice("account/updated", None),
    {"method": "account/updated"},
    {**notice("account/updated", EXACT_UPDATE), "result": {}},
    {**notice("account/updated", EXACT_UPDATE), "error": {}},
])
def test_any_other_account_update_refuses(update):
    assert account_notice_faults(update, QUALIFYING) == (
        ACCOUNT_NOTICE_FAULT.format(method="'account/updated'"),
    )
    assert updated_plan(update, QUALIFYING) is None
    assert EMAIL not in json.dumps(account_notice_faults(update, QUALIFYING))


def test_an_exact_account_update_never_admits_any_other_method():
    for method in ("account/login/completed", "account/rateLimits/updated", "account/x"):
        assert updated_plan(notice(method, EXACT_UPDATE), EXPECTED) is None


@pytest.mark.parametrize("method", [
    "account/login/completed", "account/rateLimits/changed", "account/x",
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
    {"credits": "none"}, {"credits": None},
    {"spendControlReached": True}, {"spendControlReached": False}, {"spendControlReached": None},
], ids=[
    "purchased", "unlimited", "non-object", "null-credits",
    "spend-control", "spend-control-false", "spend-control-null",
])
def test_a_rate_limit_updates_spend_facts_are_never_judged(changes):
    """The bound is judged once, before a turn starts (#78); a notice only checks the plan."""

    snapshot = codex_bucket(**changes)
    assert account_notice_faults(
        notice("account/rateLimits/updated", {"rateLimits": snapshot}), EXPECTED,
    ) == ()
    del snapshot["credits"], snapshot["spendControlReached"]
    assert account_notice_faults(
        notice("account/rateLimits/updated", {"rateLimits": snapshot}), EXPECTED,
    ) == ()


@pytest.mark.parametrize("stop,refused", [
    (True, True), ("true", True), (1, True), (False, False), (None, False), (..., False),
], ids=["reached", "string", "number", "false", "null", "absent"])
def test_a_notice_reports_the_spend_control_reached_unless_null_absent_or_false(stop, refused):
    snapshot = codex_bucket(spendControlReached=stop)
    if stop is ...:
        del snapshot["spendControlReached"]
    faults = notice_stop_faults(notice("account/rateLimits/updated", {"rateLimits": snapshot}))
    assert faults == ((SPEND_CONTROL_FAULT,) if refused else ())


def test_only_a_rate_limit_update_can_report_the_spend_control():
    stopped = {"rateLimits": codex_bucket(spendControlReached=True)}
    assert notice_stop_faults(notice("account/updated", stopped)) == ()
    assert notice_stop_faults(notice("account/rateLimits/updated", None)) == ()


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
    reply = {"result": managed(planType=plan)}
    assert account_faults(reply, QUALIFYING) == ()
    assert spend_faults(spend_reading({"result": spend_result(planType=plan)}), QUALIFYING) == ()


@pytest.mark.parametrize("plan", ["plus", "free", "team", ["pro"]])
def test_qualification_refuses_every_other_plan(plan):
    reply = {"result": managed(planType=plan)}
    assert account_faults(reply, QUALIFYING)


def test_a_production_binding_accepts_only_its_recorded_literal():
    recorded = ExpectedAccount(plan_type="prolite")
    reply = {"result": managed(planType="pro")}
    assert account_faults(reply, recorded)
    assert not recorded.accepts("pro") and recorded.accepts("prolite")


@pytest.mark.parametrize("alternatives", [("",), (" ",), ["prolite"], (1,)])
def test_alternatives_are_non_empty_literals_in_a_tuple(alternatives):
    with pytest.raises(ValueError, match="alternatives"):
        ExpectedAccount(plan_type="pro", alternatives=alternatives)
