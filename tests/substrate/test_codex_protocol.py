"""The pure Codex operator protocol: framing, requests, the mode gate, decode.

Cross-platform, credential-free, and with no process anywhere (I7). Every
account reply here is scripted; nothing in this file reaches a vendor.
"""

import ast
import inspect
import json

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import RateLimitInfo, TaskSpec, Usage
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.substrate.executors import codex_protocol
from constructicon.substrate.executors.codex_protocol import (
    ACCOUNT_NAMESPACE,
    ACCOUNT_NOTICE_FAULT,
    ACCOUNT_TYPE_KEY,
    NAMEABLE_VALUE,
    NO_ACCOUNT_FAULT,
    NO_PLAN_FAULT,
    NO_RESULT_FAULT,
    PLAN_TYPE_KEY,
    PROVIDER_FLAG_KEY,
    PROVIDER_OVERRIDE_FAULT,
    RATE_LIMIT_KEY_LENGTH,
    RATE_LIMIT_KEYS,
    READ_WINDOW,
    RECORD_BYTES,
    TRANSCRIPT_CHARS,
    ExpectedAccount,
    RecordDamaged,
    RecordStream,
    TurnObservation,
    account_change_faults,
    account_faults,
    account_read_request,
    decode_turn,
    encode_record,
    initialize_request,
    initialized_notification,
    is_account_record,
    is_terminal_record,
    is_turn_evidence,
    named_method,
    named_value,
    observe_turn,
    parse_record,
    split_records,
    thread_start_request,
    turn_request,
    unavailable_outcome,
)

THREAD = "thread-n2"
TURN = "turn-n2"
EMAIL = "operator@example.invalid"
MANAGED = {ACCOUNT_TYPE_KEY: "chatgpt", "email": EMAIL, PLAN_TYPE_KEY: "pro"}
EXPECTED = ExpectedAccount(plan_type="pro")

GRANTS = EffectiveGrants(
    posture=Posture.READ,
    model_selection=ModelSelection(kind="explicit", model="gpt-5.6-sol"),
    effort="low",
    allowed_tools=(),
    env_allowlist=(),
    network="allow",
    timeout_s=600,
)


class Facts:
    """A ProcessFacts double: read-only members, exactly as ProcessResult has."""

    def __init__(
        self,
        *,
        returncode: int = 0,
        payload_returncode: int | None = 0,
        timed_out: bool = False,
        bound_exceeded: str | None = None,
        elapsed_s: float = 1.5,
        stderr: bytes = b"",
    ) -> None:
        self._facts = (returncode, payload_returncode, timed_out, bound_exceeded,
                       elapsed_s, stderr)

    @property
    def returncode(self):
        return self._facts[0]

    @property
    def payload_returncode(self):
        return self._facts[1]

    @property
    def timed_out(self):
        return self._facts[2]

    @property
    def bound_exceeded(self):
        return self._facts[3]

    @property
    def elapsed_s(self):
        return self._facts[4]

    @property
    def stderr(self):
        return self._facts[5]


def account_reply(identifier=1, *, account=None, flag=True, present=True):
    result = {"requiresOpenaiAuth": flag}
    if present:
        result["account"] = account
    return {"id": identifier, "result": result}


def record(value):
    return encode_record(value).removesuffix(b"\n")


def completed(*, thread=THREAD, turn=TURN, status="completed", **fields):
    return {"method": "turn/completed", "params": {
        "threadId": thread, "turn": {"id": turn, "status": status, **fields},
    }}


def folded(records, **kwargs):
    return observe_turn(records, thread_id=THREAD, turn_id=TURN, **kwargs)


# --- framing -----------------------------------------------------------------


def test_the_protocol_module_never_reaches_a_launcher_or_the_platform():
    """Process facts arrive structurally, so this module stays pure and portable."""
    source = inspect.getsource(codex_protocol)
    assert "executors.linux" not in source and "LinuxLauncher" not in source
    assert "acquisition_guard" not in source
    assert "\nimport asyncio" not in source and "\nimport os" not in source
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert all(
        module in {"json", "__future__", "collections.abc", "dataclasses", "typing"}
        or module.startswith("constructicon.core.")
        for module in imported
    ), imported


def test_records_split_on_boundaries_and_a_short_read_makes_progress():
    stream = RecordStream()
    first = encode_record({"method": "one"})
    second = encode_record({"method": "two"})
    whole = first + second
    seen = []
    for index in range(0, len(whole), 7):  # deliberately smaller than a record
        seen.extend(stream.feed(whole[index:index + 7]))
    assert seen == [first.removesuffix(b"\n"), second.removesuffix(b"\n")]
    assert stream.damage is None and not stream.pending


def test_every_clamped_read_stays_inside_the_launchers_window_and_the_budget():
    stream = RecordStream()
    assert stream.next_read() == READ_WINDOW <= 8192
    stream.feed(b"x" * (RECORD_BYTES - 3))
    assert stream.next_read() == 3
    assert stream.damage is None


def test_an_oversized_record_is_damage_rather_than_an_exception():
    stream = RecordStream()
    assert stream.feed(b"x" * RECORD_BYTES) == []
    assert stream.damage is not None
    # The clamped read argument can never become zero after the ceiling is hit.
    assert 1 <= stream.next_read() <= READ_WINDOW


def test_a_stream_ending_inside_a_record_is_refused_not_accepted():
    stream = RecordStream()
    assert stream.feed(b'{"method": "partial"') == []
    assert stream.feed(b"") == []
    assert stream.damage is not None


def test_split_records_consumes_only_complete_lines():
    buffer = bytearray(b"a\nb\nincomplete")
    assert split_records(buffer) == [b"a", b"b"]
    assert bytes(buffer) == b"incomplete"


DEEP_RECORD = ("[" * 4000 + "]" * 4000).encode()
"""Thousands of nested arrays: far inside the record ceiling, yet the decoder
exhausts the stack on it. ``RecursionError`` is neither a ``ValueError`` nor a
``UnicodeError``, which is how it used to escape every parse site."""


@pytest.mark.parametrize("line", [
    DEEP_RECORD,
    b"{not json",
    b'{"method": "\xff\xfe"}',
    b'{"a": 1, "a": 2}',
], ids=["pathological", "malformed", "not-utf8", "duplicate-keys"])
def test_every_decoder_failure_is_one_damage_type(line):
    with pytest.raises(RecordDamaged):
        parse_record(line)


def test_a_valid_record_decodes_and_keeps_its_shape_checks_with_the_caller():
    assert parse_record(b'{"method": "x"}') == {"method": "x"}
    # A non-object is not damage here; each caller decides what shape it needs.
    assert parse_record(b'"just a string"') == "just a string"


def test_a_pathological_record_escapes_no_parse_site():
    assert is_terminal_record(DEEP_RECORD, thread_id=THREAD, turn_id=TURN) is False
    observation = folded([DEEP_RECORD, record(completed())])
    assert observation.malformed_records == 1 and observation.first_error is not None
    assert observation.terminal


def test_an_oversized_outbound_record_is_refused_before_it_is_sent():
    with pytest.raises(ContractViolation):
        encode_record({"method": "x", "params": {"text": "y" * RECORD_BYTES}})


# --- requests ----------------------------------------------------------------


def test_initialize_never_requests_the_experimental_capability():
    request = initialize_request(1, client="constructicon", version="0")
    assert b"experimentalApi" not in encode_record(request)
    assert request["params"]["capabilities"] == {}
    assert initialized_notification() == {"method": "initialized"}


def test_account_read_observes_and_never_causes_a_refresh():
    assert b'"refreshToken":false' in encode_record(account_read_request(4)).replace(b" ", b"")
    assert account_read_request(4)["params"] == {"refreshToken": False}


def test_neither_session_request_can_carry_a_model_or_a_provider():
    started = thread_start_request(2, cwd="/tmp")
    turn = turn_request(3, thread_id=THREAD, task=TaskSpec(instruction="x"), grants=GRANTS)
    for request in (started, turn):
        assert not {"model", "modelProvider"} & set(request["params"])
        assert b"modelProvider" not in encode_record(request)
    assert set(turn["params"]) == {"threadId", "input"}


def test_the_account_namespace_is_the_wire_prefix():
    assert ACCOUNT_NAMESPACE == "account/"
    assert account_read_request(1)["method"].startswith(ACCOUNT_NAMESPACE)


def test_a_thread_never_opts_into_an_approval_policy():
    """The field is experimental-nested at the pin and this adapter never opts in."""
    started = thread_start_request(2, cwd="/tmp")
    assert set(started["params"]) == {"cwd", "sandbox", "ephemeral"}
    assert b"approvalPolicy" not in encode_record(started)


def test_a_provider_override_field_is_refused_structurally():
    with pytest.raises(ContractViolation):
        codex_protocol._sealed({"id": 1, "method": "thread/start", "params": {
            "cwd": "/tmp", "modelProvider": "somewhere-else",
        }})


def test_a_turn_requires_the_explicit_sealed_model_even_though_it_never_sends_it():
    backend_default = GRANTS.model_copy(
        update={"model_selection": ModelSelection(kind="backend_default")},
    )
    with pytest.raises(ContractViolation):
        turn_request(3, thread_id=THREAD, task=TaskSpec(instruction="x"), grants=backend_default)


# --- the mode gate -----------------------------------------------------------


def test_a_clean_managed_reply_is_accepted():
    assert account_faults(account_reply(account=MANAGED), EXPECTED) == ()


@pytest.mark.parametrize("reply", [
    {"id": 1, "error": {"code": -32603, "message": "internal"}},
    {"id": 1},
    "not an object",
    {"id": 1, "result": []},
], ids=["error", "no-result", "not-an-object", "result-is-not-an-object"])
def test_an_error_or_missing_result_refuses(reply):
    assert account_faults(reply, EXPECTED) == (NO_RESULT_FAULT,)


def test_a_null_account_refuses_without_naming_a_cause():
    assert account_faults(account_reply(account=None), EXPECTED) == (NO_ACCOUNT_FAULT,)
    # A null account has at least four distinct causes at the pin; the message
    # must not pick one of them.
    assert "log" not in NO_ACCOUNT_FAULT and "expire" not in NO_ACCOUNT_FAULT


def test_a_missing_account_field_refuses_exactly_as_a_null_one_does():
    assert account_faults(account_reply(present=False), EXPECTED) == (NO_ACCOUNT_FAULT,)


@pytest.mark.parametrize("kind", ["apiKey", "amazonBedrock"])
def test_an_api_or_cloud_credential_refuses(kind):
    reply = account_reply(account={ACCOUNT_TYPE_KEY: kind, PLAN_TYPE_KEY: "pro"})
    faults = account_faults(reply, EXPECTED)
    assert len(faults) == 1 and kind in faults[0]


@pytest.mark.parametrize("flag", [False, None, "true", 1], ids=["false", "absent", "text", "one"])
def test_a_provider_override_refuses_independently_of_the_account(flag):
    reply = account_reply(account=MANAGED, flag=flag, present=True)
    if flag is None:
        del reply["result"][PROVIDER_FLAG_KEY]
    assert account_faults(reply, EXPECTED) == (PROVIDER_OVERRIDE_FAULT,)


def test_a_null_account_and_a_provider_override_are_both_named():
    reply = account_reply(account=None, flag=False)
    assert account_faults(reply, EXPECTED) == (NO_ACCOUNT_FAULT, PROVIDER_OVERRIDE_FAULT)


def test_a_missing_plan_fact_refuses():
    reply = account_reply(account={ACCOUNT_TYPE_KEY: "chatgpt"})
    assert account_faults(reply, EXPECTED) == (NO_PLAN_FAULT,)


def test_a_different_plan_refuses():
    reply = account_reply(account={**MANAGED, PLAN_TYPE_KEY: "free"})
    faults = account_faults(reply, EXPECTED)
    assert len(faults) == 1 and "free" in faults[0] and "pro" in faults[0]


def test_the_expected_plan_is_required_so_a_lapse_to_free_cannot_pass():
    with pytest.raises(TypeError):
        ExpectedAccount()  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        ExpectedAccount(plan_type="  ")


def test_the_gate_cannot_separate_the_chatgpt_credential_variants():
    """The screen's finding, asserted so a later "fix" would be noticed.

    Four pinned credential variants collapse onto one wire account shape, so a
    managed session and an externally supplied one can be identical bytes. The
    gate says nothing about which is in use, and must not start guessing: the
    precise carrier is the deprecated operation this adapter excludes.
    """
    managed = account_reply(account=MANAGED)
    external = account_reply(account=dict(MANAGED))
    assert encode_record(managed) == encode_record(external)
    assert account_faults(managed, EXPECTED) == account_faults(external, EXPECTED) == ()
    source = inspect.getsource(codex_protocol)
    assert "getAuthStatus" not in source and "authMode" not in source


def test_a_wire_value_reaches_a_public_detail_only_when_it_is_short_and_lexical():
    assert named_value("pro") == "'pro'" and named_value("free") == "'free'"
    assert named_value("apiKey") == "'apiKey'"
    assert named_value(None) == "absent" and named_value(True) == "True"
    assert named_value("x" * (NAMEABLE_VALUE + 1)) == "a str value"
    assert named_value({"email": EMAIL}) == "a dict value"
    assert named_value([EMAIL]) == "a list value"
    assert named_value("has space") == "a str value"
    # A method carries "/" by construction, so it has its own bounded form;
    # sharing the value charset would make every real method unnameable and
    # strip the account refusal of its only specificity.
    assert named_method("account/updated") == "'account/updated'"
    assert named_value("account/updated") == "a str value"
    assert named_method("account/" + "m" * 200) == "a str value"
    assert named_method({"email": EMAIL}) == "a dict value"


@pytest.mark.parametrize("account,leak", [
    ({ACCOUNT_TYPE_KEY: {"chatgpt": {"email": EMAIL}}, PLAN_TYPE_KEY: "pro"}, EMAIL),
    ({ACCOUNT_TYPE_KEY: "chatgpt", PLAN_TYPE_KEY: "p" * 200_000}, "p" * 200_000),
], ids=["nested-type", "oversized-plan"])
def test_no_unbounded_wire_value_reaches_a_public_fault_detail(account, leak):
    faults = account_faults(account_reply(account=account), EXPECTED)
    joined = "; ".join(faults)
    assert faults and leak not in joined
    assert len(joined) < 512


def test_a_changed_reading_reports_a_type_rather_than_an_object():
    after = account_reply(account={ACCOUNT_TYPE_KEY: {"nested": EMAIL}, PLAN_TYPE_KEY: "pro"})
    faults = account_change_faults(account_reply(account=MANAGED), after)
    joined = "; ".join(faults)
    assert faults and EMAIL not in joined and "a dict value" in joined


def test_the_account_notice_fault_classifies_its_wire_method():
    long = "account/" + "m" * 200
    detail = ACCOUNT_NOTICE_FAULT.format(method=named_method(long))
    assert long not in detail and len(detail) < 200
    named = ACCOUNT_NOTICE_FAULT.format(method=named_method("account/updated"))
    assert "account/updated" in named


def test_two_agreeing_readings_carry_no_change_fault():
    reply = account_reply(account=MANAGED)
    assert account_change_faults(reply, account_reply(2, account=MANAGED)) == ()
    assert account_change_faults(reply, reply) == ()


@pytest.mark.parametrize("after,named", [
    (account_reply(account={**MANAGED, ACCOUNT_TYPE_KEY: "apiKey"}), "type"),
    (account_reply(account={**MANAGED, PLAN_TYPE_KEY: "free"}), "plan"),
    (account_reply(account=MANAGED, flag=False), "authentication"),
    (account_reply(account=None), "type"),
], ids=["type", "plan", "provider", "vanished"])
def test_a_reading_that_differs_from_the_pre_turn_one_refuses(after, named):
    faults = account_change_faults(account_reply(account=MANAGED), after)
    assert faults and any(named in fault for fault in faults)


# --- observing one turn ------------------------------------------------------


def test_a_clean_turn_reports_only_what_the_stream_emitted():
    observation = folded([
        record({"method": "turn/delta", "params": {"threadId": THREAD}}),
        record(completed()),
    ])
    assert observation.terminal and observation.first_error is None
    assert observation.malformed_records == 0
    # I4: nothing was emitted, so nothing is inferred.
    assert observation.served_model is None
    assert observation.usage is None and observation.rate_limit is None
    assert observation.output is None
    assert "turn/delta" in observation.raw


def test_emitted_model_usage_and_rate_limit_are_carried_through():
    observation = folded([record(completed(
        model="gpt-5.6-sol", output={"summary": "done"},
        usage={"inputTokens": 11, "outputTokens": 3},
        rateLimits={"usingOverage": True, "windowMinutes": 300},
    ))])
    assert observation.served_model == "gpt-5.6-sol"
    assert observation.usage == Usage(input_tokens=11, output_tokens=3)
    assert observation.rate_limit == RateLimitInfo(
        is_using_overage=True, detail={"usingOverage": True, "windowMinutes": 300},
    )
    assert observation.output == {"summary": "done"}


def test_an_accepted_turn_publishes_only_numeric_rate_limit_facts():
    """The accepting path, which every refusal-shaped leak test misses.

    ADR 0021 asks to surface emitted rate-limit facts, not to copy a vendor
    object. Identity facts are strings and objects, so constraining by value
    shape excludes them mechanically.
    """
    observation = folded([record(completed(rateLimits={
        "usingOverage": True, "windowMinutes": 300, "usedPercent": 12.5,
        "accountId": "acct_9182736455", "email": EMAIL, "planType": "pro",
        "note": "n" * 5000, "limits": [{"email": EMAIL}],
    }))])
    outcome = decode_turn(observation, Facts(), requested_model=None)
    assert outcome.status == "success"
    published = outcome.model_dump(mode="json")
    transcript = published.pop("raw_reply")
    for leaked in (EMAIL, "acct_9182736455", "pro", "n" * 5000):
        assert leaked not in json.dumps(published)
    assert outcome.rate_limit.is_using_overage is True
    assert outcome.rate_limit.detail == {
        "usedPercent": 12.5, "usingOverage": True, "windowMinutes": 300,
    }
    # The stated limit, pinned by a test rather than left in prose: a legitimate
    # turn record's payload is the vendor's and passes through raw_reply. No
    # filter can change that without a payload vocabulary this slice does not
    # hold; qualifying what those payloads may contain is an N3/N4 prerequisite.
    assert EMAIL in transcript


def test_a_rate_limit_object_of_only_identity_facts_publishes_no_detail():
    observation = folded([record(completed(rateLimits={"email": EMAIL}))])
    outcome = decode_turn(observation, Facts(), requested_model=None)
    assert outcome.status == "success" and outcome.rate_limit.detail is None
    published = outcome.model_dump(mode="json")
    published.pop("raw_reply")  # the vendor's own record; see the stated limit
    assert EMAIL not in json.dumps(published)


def test_the_dropped_string_rate_limit_fact_is_a_pinned_cost_not_an_accident():
    """The stated cost of constraining by value shape, as a test rather than prose."""
    observation = folded([record(completed(rateLimits={
        "resetsAt": "2026-01-01T00:00:00Z", "windowMinutes": 300,
    }))])
    outcome = decode_turn(observation, Facts(), requested_model=None)
    assert outcome.rate_limit.detail == {"windowMinutes": 300}


def test_a_rate_limit_object_is_bounded_in_key_count_and_key_length():
    emitted = {f"metric{index}": index for index in range(40)}
    emitted["k" * 200] = 1
    observation = folded([record(completed(rateLimits=emitted))])
    outcome = decode_turn(observation, Facts(), requested_model=None)
    assert len(outcome.rate_limit.detail) <= RATE_LIMIT_KEYS
    assert all(len(key) <= RATE_LIMIT_KEY_LENGTH for key in outcome.rate_limit.detail)


def test_a_malformed_record_is_damage_a_later_success_cannot_promote():
    observation = folded([b"{not json", record(completed())])
    assert observation.malformed_records == 1
    assert observation.terminal and observation.first_error is not None


def test_two_terminal_records_are_contradictory_rather_than_last_wins():
    observation = folded([
        record(completed(output={"first": True})),
        record(completed(output={"second": True})),
    ])
    assert observation.terminal and observation.output == {"first": True}
    assert "contradictory" in (observation.first_error or "")


def test_a_terminal_record_naming_another_invocation_is_damage():
    observation = folded([record(completed(turn="another-turn"))])
    assert not observation.terminal and observation.first_error is not None


def test_a_non_completed_terminal_status_is_damage_not_a_quiet_success():
    observation = folded([record(completed(status="failed"))])
    assert observation.terminal and "failed" in (observation.first_error or "")


def test_a_reply_or_a_native_request_never_reaches_the_transcript():
    """E: an account reply in the stream must not become ``raw_reply``."""
    observation = folded([
        record(account_reply(9, account=MANAGED)),
        record({"id": 10, "method": "item/tool/call", "params": {}}),
        record(completed()),
    ])
    assert EMAIL not in observation.raw
    assert "item/tool/call" not in observation.raw
    assert observation.malformed_records == 2 and observation.terminal


ACCOUNT_NOTICE = {"method": "account/updated", "params": {
    "account": {ACCOUNT_TYPE_KEY: "chatgpt", "email": EMAIL, PLAN_TYPE_KEY: "pro"},
    "authMode": "chatgptAuthTokens",
}}


def test_an_id_less_account_notification_never_reaches_the_transcript():
    """The pin emits account notifications carrying auth mode and plan type."""
    observation = folded([record(ACCOUNT_NOTICE), record(completed())])
    assert EMAIL not in observation.raw
    assert "chatgptAuthTokens" not in observation.raw and "account/updated" not in observation.raw
    # It is not malformed; it is simply not this turn's evidence.
    assert observation.malformed_records == 0 and observation.first_error is None
    assert observation.terminal


@pytest.mark.parametrize("damaged", [
    b'{"method": "account/updated", "params": {"email": "' + EMAIL.encode() + b'"',
    b'{"id": 3, "result": {"account": {"type": "chatgpt", "email": "' + EMAIL.encode()
    + b'", "planType": "pro"}, "requiresOpenaiAuth"',
    b'{"method": "authStatusChange", "params": {"email": "' + EMAIL.encode() + b'"',
    b"thread 'main' panicked: signed in as " + EMAIL.encode(),
    b"[INFO] refreshed credentials for " + EMAIL.encode(),
], ids=["account-notification", "account-reply", "other-namespace", "panic", "diagnostic"])
def test_no_unparseable_byte_is_ever_published(damaged):
    """Bytes we could not parse we could not classify, so none are published.

    A marker on the word "account" was a heuristic: it closed the two shapes it
    was tested against and left the class open — a diagnostic line, a panic, or a
    truncation one field earlier all name an operator without that word.
    """
    observation = folded([damaged, record(completed())])
    assert EMAIL not in observation.raw
    assert damaged.decode("utf-8", errors="replace") not in observation.raw
    # I4: the count and the damage still report them, so this is not silence.
    assert observation.malformed_records == 1 and observation.first_error is not None
    assert observation.terminal


@pytest.mark.parametrize("method", [
    "account/updated", "account/read", "account/login/start", "account/anythingUnenumerated",
])
def test_the_whole_account_namespace_is_refused_not_a_list_of_known_methods(method):
    assert is_account_record({"method": method})


@pytest.mark.parametrize("method", [
    "account/updated", "account/read", "account/login/start", "account/anythingUnenumerated",
])
def test_no_account_method_is_attested_turn_evidence(method):
    """``observe_turn`` needs no account clause, and this is why.

    The allowlist already excludes the namespace, so a second clause there would
    have no observable effect and could not be falsified. This assertion is what
    an author widening the allowlist to admit ``account/`` would break.
    """
    assert not is_turn_evidence({"method": method})
    assert EMAIL not in folded([
        record({"method": method, "params": {"email": EMAIL}}), record(completed()),
    ]).raw
    assert EMAIL not in folded([record({"method": method, "params": {"email": EMAIL}})]).raw


@pytest.mark.parametrize("record_value", [
    {"method": "item/started"}, {"method": "turn/completed"}, {"method": 7}, {"params": {}},
    {"method": "accounts/other"},
])
def test_an_ordinary_notification_is_not_an_account_record(record_value):
    assert not is_account_record(record_value)


def test_the_account_fault_names_the_method_and_nothing_from_its_params():
    detail = ACCOUNT_NOTICE_FAULT.format(method="account/updated")
    assert "account/updated" in detail
    assert EMAIL not in detail and "pro" not in detail and "chatgptAuthTokens" not in detail
    # Neutral about what changed: a non-updated account record need not be one.
    assert "mode change" not in detail


@pytest.mark.parametrize("method", ["turn/delta", "turn/anything", "error", "warning"])
def test_an_attested_turn_notification_is_kept_as_evidence(method):
    observation = folded([record({"method": method, "params": {"x": 1}}), record(completed())])
    assert method in observation.raw and observation.malformed_records == 0


@pytest.mark.parametrize("method", [
    "authStatusChange", "sessionConfigured", "hook/started", "item/started",
])
def test_an_unattested_method_is_excluded_without_being_called_damage(method):
    """An unknown method is an open assumption, not evidence, and not damage."""
    notice = {"method": method, "params": {"email": EMAIL}}
    observation = folded([record(notice), record(completed())])
    assert EMAIL not in observation.raw and method not in observation.raw
    assert observation.malformed_records == 0 and observation.first_error is None
    assert observation.terminal


def test_the_item_namespace_is_excluded_and_says_so_rather_than_going_silent():
    """``item/`` has never been observed emitting a notification, so it is out.

    Its only attested member is the id-bearing ``item/tool/call`` request. The
    exclusion is deliberate and must be *visible*: a near-empty transcript with
    no count is an evidence blackout, which is the same class of defect as
    something consequential happening invisibly.
    """
    records = [record({"method": "item/started", "params": {"index": index}})
               for index in range(37)]
    observation = folded([*records, record(completed())])
    assert "item/started" not in observation.raw
    assert "[37 records excluded as unclassified]" in observation.raw
    # Our own classification is not transport damage.
    assert observation.malformed_records == 0 and observation.first_error is None
    assert decode_turn(observation, Facts(), requested_model=None).status == "success"


def test_a_fully_classified_turn_carries_no_exclusion_marker():
    observation = folded([record({"method": "turn/delta"}), record(completed())])
    assert "excluded as unclassified" not in observation.raw


def test_the_transcript_is_bounded_and_says_how_much_it_dropped():
    chatty = [record({"method": "turn/delta", "params": {"text": "x" * 2000}})
              for _ in range(200)]
    observation = folded([*chatty, record(completed())])
    assert len(observation.raw) <= TRANSCRIPT_CHARS + 200
    assert "further records not shown" in observation.raw
    # Our own bound is not transport damage and must not demote a clean success.
    assert observation.first_error is None and observation.malformed_records == 0
    assert decode_turn(observation, Facts(), requested_model=None).status == "success"


def test_transport_damage_from_the_framing_is_carried_into_the_observation():
    observation = folded([record(completed())], transport_damage="record bound")
    assert observation.first_error == "record bound"


def test_a_terminal_record_is_recognized_only_for_its_own_invocation():
    assert is_terminal_record(record(completed()), thread_id=THREAD, turn_id=TURN)
    assert not is_terminal_record(record(completed(turn="x")), thread_id=THREAD, turn_id=TURN)
    assert not is_terminal_record(b"{not json", thread_id=THREAD, turn_id=TURN)
    assert not is_terminal_record(record({"method": "item/started"}),
                                  thread_id=THREAD, turn_id=TURN)


# --- decode ------------------------------------------------------------------


CLEAN = TurnObservation(
    output={"summary": "done"}, served_model="gpt-5.6-sol", usage=None, rate_limit=None,
    terminal=True, malformed_records=0, first_error=None, raw='{"method":"turn/completed"}',
)


def test_a_clean_turn_with_a_complete_exit_report_succeeds():
    outcome = decode_turn(CLEAN, Facts(), requested_model="gpt-5.6-sol")
    assert outcome.status == "success"
    assert outcome.output == {"summary": "done"} and outcome.served_model == "gpt-5.6-sol"
    assert outcome.requested_model == "gpt-5.6-sol" and outcome.elapsed_s == 1.5


def test_a_timeout_salvages_the_output_it_did_see():
    outcome = decode_turn(CLEAN, Facts(timed_out=True, returncode=143, payload_returncode=None),
                          requested_model="gpt-5.6-sol")
    assert outcome.status == "failure" and outcome.error.kind == "timeout"
    assert outcome.output == {"summary": "done"} and outcome.error.produced_output is True


def test_a_nonzero_exit_without_a_bound_breach_is_an_exit_failure():
    outcome = decode_turn(CLEAN, Facts(returncode=2, payload_returncode=2),
                          requested_model=None)
    assert outcome.status == "failure" and outcome.error.kind == "exit"
    assert outcome.error.exit_code == 2


@pytest.mark.parametrize("payload", [None, 1], ids=["absent", "mismatched"])
def test_an_incomplete_private_exit_report_is_never_a_success_or_an_exit(payload):
    outcome = decode_turn(CLEAN, Facts(returncode=0, payload_returncode=payload),
                          requested_model=None)
    assert outcome.status == "partial"
    assert "complete" in outcome.damage.first_error


def test_an_incomplete_exit_report_outranks_a_nonzero_return_code():
    outcome = decode_turn(CLEAN, Facts(returncode=2, payload_returncode=None),
                          requested_model=None)
    assert outcome.status == "partial"


def test_a_bound_breach_demotes_to_partial_with_bounded_stderr_evidence():
    outcome = decode_turn(
        CLEAN,
        Facts(returncode=137, payload_returncode=None, bound_exceeded="record",
              stderr=b"e" * 4096),
        requested_model=None,
    )
    assert outcome.status == "partial" and outcome.damage.first_error == "record"
    assert len(outcome.damage.evidence_excerpt) == 256


def test_the_stderr_excerpt_is_unfiltered_vendor_output_by_decision():
    """A pinned limit, not an oversight: filtering it is the unwinnable heuristic.

    An author who starts filtering this field breaks this test and has to revisit
    the stated N4 prerequisite rather than quietly closing the edge.
    """
    outcome = decode_turn(
        CLEAN, Facts(bound_exceeded="record", stderr=f"signed in as {EMAIL}".encode()),
        requested_model=None,
    )
    assert outcome.status == "partial" and EMAIL in outcome.damage.evidence_excerpt


def test_a_malformed_record_demotes_to_partial():
    observation = TurnObservation(
        output=None, served_model=None, usage=None, rate_limit=None, terminal=True,
        malformed_records=3, first_error="malformed protocol", raw="",
    )
    outcome = decode_turn(observation, Facts(), requested_model=None)
    assert outcome.status == "partial" and outcome.damage.malformed_records == 3


def test_a_turn_with_no_terminal_record_demotes_to_partial():
    observation = TurnObservation(
        output=None, served_model=None, usage=None, rate_limit=None, terminal=False,
        malformed_records=0, first_error=None, raw="",
    )
    outcome = decode_turn(observation, Facts(), requested_model=None)
    assert outcome.status == "partial" and "terminal" in outcome.damage.first_error


def test_a_refused_gate_discards_the_result_and_still_reports_that_a_turn_ran():
    outcome = unavailable_outcome(
        (NO_ACCOUNT_FAULT, PROVIDER_OVERRIDE_FAULT), CLEAN, Facts(), requested_model="m",
    )
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert NO_ACCOUNT_FAULT in outcome.error.detail
    assert PROVIDER_OVERRIDE_FAULT in outcome.error.detail
    assert outcome.error.produced_output is True
    # The turn's result is refused, not reported: none of it survives.
    assert outcome.output is None and outcome.raw_reply is None
    assert outcome.served_model is None and outcome.requested_model == "m"
