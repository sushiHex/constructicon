"""The recovery lane's fakes answer each case as the design says, portably."""

import base64
import json

import pytest

from tests.native_account import (
    ACCOUNT_ID,
    BACKEND,
    CHECK,
    ISSUER,
    NEW,
    OLD,
    OTHER,
    OTHER_USER_ID,
    RESET_CREDITS,
    TOKEN,
    USAGE,
    USER_ID,
    Script,
    classify,
    credential,
)


def claims(token):
    return json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))


def check(script, tokens):
    return script.respond(BACKEND, "GET", CHECK, {
        "authorization": f"Bearer {tokens.access}", "chatgpt-account-id": ACCOUNT_ID}, b"")


def refresh(script, token=OLD.refresh):
    return script.respond(ISSUER, "POST", TOKEN, {}, json.dumps({
        "client_id": "app_fixture", "grant_type": "refresh_token", "refresh_token": token,
    }).encode())


def test_the_fixture_credential_is_the_shape_that_takes_the_401_path():
    stored = json.loads(credential())
    assert stored["tokens"]["account_id"] == ACCOUNT_ID and stored["last_refresh"]
    auth = claims(stored["tokens"]["id_token"])["https://api.openai.com/auth"]
    assert (auth["chatgpt_user_id"], auth["chatgpt_plan_type"]) == (USER_ID, "pro")
    assert classify(stored["tokens"]["access_token"], "access") == "old"
    assert claims(OLD.access)["exp"] == claims(NEW.access)["exp"] > 0


@pytest.mark.parametrize("case", ["clean", "refused", "unauthorized", "changed", "unsealed"])
def test_the_old_bearer_is_always_refused(case):
    script = Script(case)
    assert check(script, OLD)[0] == 401
    assert script.log == [{"host": BACKEND, "method": "GET", "path": CHECK, "bearer": "old",
                           "account": ACCOUNT_ID, "status": 401}]


def test_clean_issues_the_same_accounts_new_tokens_and_then_answers_them():
    script = Script("clean")
    status, issued = refresh(script)
    assert status == 200 and issued["access_token"] == NEW.access
    assert issued["refresh_token"] == NEW.refresh
    assert claims(issued["id_token"])["https://api.openai.com/auth"]["chatgpt_user_id"] == USER_ID
    status, routed = check(script, NEW)
    assert status == 200 and routed["accounts"][0]["workspace_backend_origin"] == (
        "https://chatgpt.com")
    usage = script.respond(BACKEND, "GET", USAGE, {
        "authorization": f"Bearer {NEW.access}", "chatgpt-account-id": ACCOUNT_ID}, b"")
    assert usage == (200, {"plan_type": "pro"})
    assert script.respond(BACKEND, "GET", RESET_CREDITS, {}, b"")[0] == 404
    assert script.log[0]["refresh_token"] == "old" and script.log[0]["grant_type"] == (
        "refresh_token")


def test_each_failing_case_fails_where_the_design_says():
    assert refresh(Script("refused")) == (401, {"error": "invalid_grant"})
    unauthorized = Script("unauthorized")
    assert refresh(unauthorized)[0] == 200 and check(unauthorized, NEW)[0] == 401
    changed = Script("changed")
    _, issued = refresh(changed)
    assert claims(issued["id_token"])["https://api.openai.com/auth"]["chatgpt_user_id"] == (
        OTHER_USER_ID)
    assert issued["access_token"] == OTHER.access
    unsealed = Script("unsealed")
    status, routed = check(unsealed, NEW)
    assert status == 200 and routed["accounts"][0]["workspace_backend_origin"] == (
        "https://elsewhere.invalid")
    assert routed["accounts"][0]["account_routing_override"] == "NO_CONSTRAINT"


def test_the_log_names_tokens_only_by_class():
    script = Script("clean")
    refresh(script)
    check(script, NEW)
    script.respond(BACKEND, "GET", CHECK, {"authorization": "Bearer stranger"}, b"")
    text = json.dumps(script.log)
    for token in (OLD.access, OLD.refresh, NEW.access, NEW.refresh):
        assert token not in text
    assert [entry["bearer"] for entry in script.log] == [None, "new", "unknown"]


def test_an_unexpected_request_is_logged_and_refused():
    script = Script("clean")
    assert script.respond(BACKEND, "POST", CHECK, {}, b"")[0] == 404
    assert script.respond("stranger.invalid", "GET", "/", {}, b"")[0] == 404
    assert len(script.log) == 2


def test_an_unknown_case_is_refused():
    with pytest.raises(ValueError, match="unknown recovery case"):
        Script("lenient")
