"""Every public bound binds; copies and malformed structures fail closed."""

import json

import pytest

from constructicon.core.executor import (
    ExecutorError,
    ExecutorFailure,
    ExecutorPartial,
    ExecutorSuccess,
    TransportDamage,
    Usage,
)
from constructicon.substrate.executors import pi_protocol as protocol
from constructicon.substrate.executors.linux import ProcessResult
from tests.piworld import cycle, record, state

CLEAN = ProcessResult(0, b"", b"", .01, payload_returncode=0)


def decoded(*, transform=lambda records: records, text="fixture", instruction="read"):
    decoder = protocol.PiDecoder(instruction)
    decoder.request("get_state", "state")
    decoder.feed(record(state("state")))
    decoder.request("prompt", "prompt")
    for item in transform(cycle(instruction, text)):
        decoder.feed(record(item))
    decoder.feed(record({"type": "response", "id": "prompt", "command": "prompt",
                         "success": True, "data": {"disposition": "started"}}))
    decoder.finish()
    return decoder


def test_clean_protocol_has_affirmative_completion():
    decoder = decoded()
    assert decoder.outcome(CLEAN).status == "success"
    assert decoder.started and decoder.ended and decoder.settled and decoder.eof
    assert decoder.accepted and decoder.expected is None
    assert len(decoder.calls) == 1
    assert all(call.result is not None for call in decoder.calls.values())


@pytest.mark.parametrize("replacement", [None, [], 1, "wrong"])
@pytest.mark.parametrize("event,field", [
    ("message_end", "message"), ("message_update", "assistantMessageEvent"),
    ("tool_execution_end", "result"),
])
def test_malformed_container_shapes_demote_without_escaping(event, field, replacement):
    def change(records):
        next(item for item in records if item["type"] == event)[field] = replacement
        return records

    outcome = decoded(transform=change).outcome(CLEAN)
    assert outcome.status == "partial"
    assert protocol.publication_fits(outcome)


@pytest.mark.parametrize("model", [None, [], 1, "wrong"])
def test_malformed_state_model_demotes_without_escaping(model):
    decoder = protocol.PiDecoder("read")
    decoder.request("get_state", "state")
    reply = state("state")
    reply["data"]["model"] = model
    decoder.feed(record(reply))
    assert decoder.outcome(CLEAN).status == "partial"


@pytest.mark.parametrize("block", [None, [], "wrong", {"type": "image", "data": "no"}])
def test_malformed_or_unsupported_content_block_demotes(block):
    def change(records):
        next(item for item in records if item["type"] == "message_end"
             and item["message"]["role"] == "assistant")["message"]["content"] = [block]
        return records

    assert decoded(transform=change).outcome(CLEAN).status == "partial"


@pytest.mark.parametrize("copy", ["turn_end", "agent_end"])
def test_copies_compare_canonical_bytes_including_boolean_integer_distinction(copy):
    def change(records):
        item = next(item for item in records if item["type"] == copy)
        # Round-trip breaks the fixture's aliases, as independent wire records do.
        copied = json.loads(json.dumps(item))
        target = copied["message"] if copy == "turn_end" else copied["messages"][1]
        target["timestamp"] = 2.0  # Python equality would incorrectly agree with 2.
        return [copied if candidate is item else candidate for candidate in records]

    assert decoded(transform=change).outcome(CLEAN).status == "partial"


@pytest.mark.parametrize("payload", [
    b'{"type":"agent_settled","aborted":false,"aborted":true}\n',
    b'{"type":"unknown","number":NaN}\n', b'{"type":"unknown","number":Infinity}\n',
    b'{"type":"unknown","text":"\\ud800"}\n', b'{"type":"unknown","text":"\xff"}\n',
    b'{"type":"unknown"',
])
def test_damaged_tail_demotes_otherwise_complete_analysis(payload):
    decoder = decoded()
    decoder.eof = False
    decoder.feed(payload)
    decoder.finish()
    outcome = decoder.outcome(CLEAN)
    assert outcome.status == "partial" and outcome.output == "Read: fixture"
    assert protocol.publication_fits(outcome)


@pytest.mark.parametrize("bound", ["record", "stdout", "count"])
def test_framing_byte_and_count_limits_bind_exactly(bound):
    decoder = protocol.PiDecoder("read")
    decoder.refused = True  # Isolate framing: records still count before semantic refusal.
    if bound == "record":
        decoder.feed(b"{}" + b" " * (protocol.RECORD_BYTES - 3) + b"\n")
    elif bound == "stdout":
        for _ in range(protocol.STDOUT_BYTES // protocol.RECORD_BYTES):
            decoder.feed(b"{}" + b" " * (protocol.RECORD_BYTES - 3) + b"\n")
    else:
        decoder.feed(b"{}\n" * protocol.RECORD_COUNT)
    assert decoder.damage_count == 0
    if bound == "record":
        decoder.feed(b"{}" + b" " * (protocol.RECORD_BYTES - 2) + b"\n")
    elif bound == "stdout":
        decoder.feed(b" ")
    else:
        decoder.feed(b"{}\n")
    assert decoder.damage_count > 0
    assert decoder.error == {"record": "record byte limit exceeded",
                             "stdout": "stdout byte limit exceeded",
                             "count": "record count exceeded"}[bound]


def test_depth_is_checked_before_recursive_parsing_and_strings_do_not_count():
    just_at = b'{"nested":' + b"[" * 31 + b'"[[["' + b"]" * 31 + b"}"
    assert protocol.parse_record(just_at)
    with pytest.raises(ValueError, match="depth"):
        protocol.parse_record(b'{"nested":' + b"[" * 32 + b"0" + b"]" * 32 + b"}")


def test_reply_bound_binds_at_encoded_json_bytes_and_salvages_one_over():
    just_at = decoded(text="x" * (protocol.REPLY_BYTES - 8)).outcome(CLEAN)
    assert just_at.status == "success" and len(protocol.encoded(just_at.output)) == 16384
    one_over = decoded(text="x" * (protocol.REPLY_BYTES - 7)).outcome(CLEAN)
    assert one_over.status == "partial" and len(protocol.encoded(one_over.output)) == 16384
    assert protocol.publication_fits(one_over)


@pytest.mark.parametrize("field,limit", [("output", 16384), ("raw_reply", 16384),
                                          ("served_model", 256), ("requested_model", 256)])
def test_every_published_string_field_obeys_its_encoded_bound(field, limit):
    assert protocol.publication_fits(ExecutorSuccess(**{field: "x" * (limit - 2)}))
    assert not protocol.publication_fits(ExecutorSuccess(**{field: "x" * (limit - 1)}))


def test_global_bound_and_nested_new_sites_are_walked():
    outcome = ExecutorSuccess(output=["x" * 250] * 250)
    assert protocol.publication_fits(outcome)
    assert not protocol.publication_fits(ExecutorSuccess(output=["x" * 250] * 260))
    assert not protocol.publication_fits(ExecutorSuccess(output={"new": "x" * 255}))
    assert protocol.publication_fits(
        ExecutorSuccess(usage=Usage(input_tokens=protocol.MAX_INTEGER)),
    )
    assert not protocol.publication_fits(
        ExecutorSuccess(usage=Usage(input_tokens=protocol.MAX_INTEGER + 1)),
    )


@pytest.mark.parametrize("usage", [None, {}, {"input": True}, {"input": -1},
                                  {"input": 2**63}, {"input": 3.5}])
def test_incomplete_or_invalid_usage_is_none(usage):
    def change(records):
        next(item for item in records if item["type"] == "message_end"
             and item["message"]["role"] == "assistant")["message"]["usage"] = usage
        return records

    assert decoded(transform=change).outcome(CLEAN).usage is None


@pytest.mark.parametrize("disposition", ["handled", "queued", "unknown"])
def test_prompt_disposition_is_acceptance_not_completion(disposition):
    decoder = decoded()
    decoder.accepted = False
    decoder.eof = False
    decoder.request("prompt", "another")
    decoder.feed(record({"type": "response", "id": "another", "command": "prompt",
                         "success": True, "data": {"disposition": disposition}}))
    decoder.finish()
    assert decoder.outcome(CLEAN).status == "failure"


def test_pre_request_complete_and_partial_response_cannot_become_fresh():
    for prefix in (record(state("state")), record(state("state"))[:20]):
        decoder = protocol.PiDecoder("read")
        decoder.feed(prefix)
        decoder.request("get_state", "state")
        decoder.feed(record(state("state"))[len(prefix):])
        assert decoder.outcome(CLEAN).status == "partial"


@pytest.mark.parametrize("content", [None, {}, "not blocks", [None], [{"type": "text"}],
                                     [{"type": "text", "text": []}]])
def test_matching_malformed_read_content_is_not_schema_proof(content):
    def change(records):
        for item in records:
            if item["type"] == "tool_execution_end":
                item["result"]["content"] = content
            elif item["type"] == "message_end" and item["message"]["role"] == "toolResult":
                item["message"]["content"] = content
        return records

    assert decoded(transform=change).outcome(CLEAN).status == "partial"


@pytest.mark.parametrize("update", [
    {"type": "text_delta", "contentIndex": True, "delta": "x"},
    {"type": "text_delta", "contentIndex": 0, "delta": []},
    {"type": "text_start", "contentIndex": -1},
    {"type": "thinking_end", "contentIndex": 0, "content": None},
    {"type": "toolcall_start", "contentIndex": 0, "id": "call", "toolName": "bash"},
    {"type": "toolcall_end", "contentIndex": 0, "toolCall": {}},
    {"type": "done", "reason": "stop", "message": None},
])
def test_stream_update_payloads_have_finite_shapes(update):
    def change(records):
        next(item for item in records if item["type"] == "message_update")[
            "assistantMessageEvent"
        ] = update
        return records

    assert decoded(transform=change).outcome(CLEAN).status == "partial"


def test_final_analysis_requires_actual_completed_read():
    def change(records):
        final = next(item["message"] for item in records if item["type"] == "message_end"
                     and item["message"].get("stopReason") == "stop")
        user = records[2]["message"]
        return [records[0], records[1], records[2], records[3],
                {"type": "message_start", "message": final},
                {"type": "message_end", "message": final},
                {"type": "turn_end", "message": final, "toolResults": []},
                {"type": "agent_end", "messages": [user, final], "willRetry": False},
                {"type": "agent_settled", "aborted": False}]

    assert decoded(transform=change).outcome(CLEAN).status == "partial"


@pytest.mark.parametrize("text", [[""], [" \t\n"], ["", "", ""]],
                         ids=["empty", "whitespace", "all-empty-blocks"])
def test_terminal_analysis_requires_nonblank_joined_reply(text):
    def change(records):
        final = next(item["message"] for item in records if item["type"] == "message_end"
                     and item["message"].get("stopReason") == "stop")
        final["content"] = [{"type": "text", "text": block} for block in text]
        return records

    outcome = decoded(transform=change).outcome(CLEAN)
    assert outcome.status == "partial"
    assert outcome.output is outcome.raw_reply is None


def test_terminal_analysis_keeps_meaningful_text_among_empty_blocks_unchanged():
    text = ["", " \t", " meaningful analysis é ", "\n", ""]

    def change(records):
        final = next(item["message"] for item in records if item["type"] == "message_end"
                     and item["message"].get("stopReason") == "stop")
        final["content"] = [{"type": "text", "text": block} for block in text]
        return records

    outcome = decoded(transform=change).outcome(CLEAN)
    assert outcome.status == "success"
    assert outcome.output == outcome.raw_reply == "".join(text)


def test_message_completions_require_matching_starts():
    def change(records):
        return [item for item in records if item["type"] not in ("message_start", "message_update")]

    assert decoded(transform=change).outcome(CLEAN).status == "partial"


@pytest.mark.parametrize("reason", ["stop", "toolUse", "length", "error", "aborted"])
def test_provider_done_update_latches_non_success_and_agrees_with_message_end(reason):
    def change(records):
        index = next(index for index, item in enumerate(records) if item["type"] == "message_end"
                     and item["message"].get("stopReason") == (
                         "toolUse" if reason == "toolUse" else "stop"
                     ))
        message = json.loads(json.dumps(records[index]["message"]))
        message["stopReason"] = reason
        records.insert(index, {"type": "message_update", "assistantMessageEvent": {
            "type": "done", "reason": reason, "message": message,
        }})
        return records

    decoder = decoded(transform=change)
    outcome = decoder.outcome(CLEAN)
    assert (outcome.status == "success") == (reason in ("stop", "toolUse"))
    if reason not in ("stop", "toolUse"):
        assert decoder.refused  # Revocation is affirmative before later completion can arrive.


def test_provider_done_copy_must_agree_canonically_with_message_end():
    def change(records):
        index = next(index for index, item in enumerate(records) if item["type"] == "message_end"
                     and item["message"].get("stopReason") == "stop")
        message = json.loads(json.dumps(records[index]["message"]))
        message["timestamp"] = 2.0
        records.insert(index, {"type": "message_update", "assistantMessageEvent": {
            "type": "done", "reason": "stop", "message": message,
        }})
        return records

    assert decoded(transform=change).outcome(CLEAN).status == "partial"


@pytest.mark.parametrize("damage", ["duplicate-call", "unknown-role", "tool-result-error"])
def test_remaining_read_cycle_refusals_have_an_accepting_control(damage):
    assert decoded().outcome(CLEAN).status == "success"

    def change(records):
        if damage == "duplicate-call":
            message = next(item["message"] for item in records if item["type"] == "message_end"
                           and item["message"].get("stopReason") == "toolUse")
            message["content"].append(dict(message["content"][0]))
        elif damage == "unknown-role":
            records[2]["message"]["role"] = "controller"
        else:
            message = next(item["message"] for item in records if item["type"] == "message_end"
                           and item["message"].get("role") == "toolResult")
            message["isError"] = True
        return records

    decoder = decoded(transform=change)
    assert decoder.outcome(CLEAN).status == "partial"
    assert decoder.damage_count > 0


@pytest.mark.parametrize("damage", ["wrong-id", "wrong-command", "duplicate", "pre-prompt-work"])
def test_remaining_response_order_refusals_have_an_accepting_control(damage):
    decoder = protocol.PiDecoder("read")
    decoder.request("get_state", "state")
    response = state("state")
    if damage == "wrong-id":
        response["id"] = "another-request"
    elif damage == "wrong-command":
        response["command"] = "prompt"
    elif damage == "pre-prompt-work":
        decoder.feed(record({"type": "agent_start"}))
    decoder.feed(record(response))
    if damage == "duplicate":
        assert decoder.state_observed and not decoder.damage_count
        decoder.feed(record(response))
    assert decoder.outcome(CLEAN).status == "partial"
    assert decoder.damage_count > 0
    assert decoded().outcome(CLEAN).status == "success"


@pytest.mark.parametrize("field,limit", [
    ("first_error", 256), ("evidence_excerpt", 1024), ("error_detail", 256),
])
def test_diagnostic_publication_bound_binds_at_encoded_bytes(field, limit):
    def outcome(value):
        if field == "error_detail":
            return ExecutorFailure(error=ExecutorError(kind="exit", detail=value))
        return ExecutorPartial(damage=TransportDamage(
            malformed_records=1, first_error=value if field == "first_error" else None,
            evidence_excerpt=value if field == "evidence_excerpt" else None,
        ))

    assert protocol.publication_fits(outcome("x" * (limit - 2)))
    assert not protocol.publication_fits(outcome("x" * (limit - 1)))
    decoder = protocol.PiDecoder("read")
    decoder.damage("x" * 255, b"x" * 1023)
    assert len(protocol.encoded(decoder.error)) == 256
    assert len(protocol.encoded(decoder.excerpt)) == 1024
    assert protocol.publication_fits(decoder.outcome(CLEAN))


def test_entire_serialized_outcome_cap_binds_at_exact_byte():
    outcome = ExecutorSuccess(output=["x" * 250] * 250)
    while protocol.OUTCOME_BYTES - len(protocol.encoded(outcome.model_dump(mode="json"))) > 256:
        outcome.output.append("x" * 250)
    remaining = protocol.OUTCOME_BYTES - len(protocol.encoded(outcome.model_dump(mode="json")))
    assert 3 <= remaining <= 256
    outcome.output.append("x" * (remaining - 3))
    assert len(protocol.encoded(outcome.model_dump(mode="json"))) == protocol.OUTCOME_BYTES
    assert protocol.publication_fits(outcome)
    outcome.output[-1] += "x"
    assert len(protocol.encoded(outcome.output[-1])) <= 256
    assert len(protocol.encoded(outcome.model_dump(mode="json"))) == protocol.OUTCOME_BYTES + 1
    assert not protocol.publication_fits(outcome)
