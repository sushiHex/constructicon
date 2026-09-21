"""The fixed WRITE callback's accepting and refusing wire boundaries."""

import copy

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors.codex_protocol import (
    CONTAINED_PYTHON_TOOL,
    TOOL_IDENTIFIER_BYTES,
    TOOL_OUTPUT_BYTES,
    TOOL_PROGRAM_BYTES,
    initialize_request,
    parse_tool_call,
    thread_start_request,
    tool_call_response,
)


def callback():
    return {"id": "server-1", "method": "item/tool/call", "params": {
        "threadId": "thread", "turnId": "turn", "callId": "call",
        "tool": "contained_python", "arguments": {"program": "print('ok')"},
    }}


def parse(record):
    return parse_tool_call(record, thread_id="thread", turn_id="turn")


def test_write_opt_in_and_catalog_are_explicit_while_read_bytes_stay_narrow():
    assert initialize_request(1, client="fixture", version="0")["params"]["capabilities"] == {}
    assert initialize_request(
        1, client="fixture", version="0", experimental_api=True,
    )["params"]["capabilities"] == {"experimentalApi": True}
    read = thread_start_request(2, cwd="/tmp")
    assert read["params"] == {"cwd": "/tmp", "sandbox": "read-only", "ephemeral": True}
    write = thread_start_request(2, cwd="/tmp", dynamic_tools=(CONTAINED_PYTHON_TOOL,))
    assert write["params"] == {**read["params"], "dynamicTools": [CONTAINED_PYTHON_TOOL]}
    write["params"]["dynamicTools"][0]["inputSchema"]["properties"].clear()
    assert thread_start_request(2, cwd="/tmp", dynamic_tools=(CONTAINED_PYTHON_TOOL,))[
        "params"
    ]["dynamicTools"][0]["inputSchema"]["properties"] == {"program": {"type": "string"}}
    changed = copy.deepcopy(CONTAINED_PYTHON_TOOL)
    changed["name"] = "another_tool"
    with pytest.raises(ContractViolation):
        thread_start_request(2, cwd="/tmp", dynamic_tools=(changed,))


@pytest.mark.parametrize("flag", [1, "true", None])
def test_opt_in_selector_is_not_truthiness(flag):
    with pytest.raises(ContractViolation):
        initialize_request(1, client="fixture", version="0", experimental_api=flag)


@pytest.mark.parametrize("request_id", [1, "server-1"])
@pytest.mark.parametrize("namespace", ["omitted", None])
def test_exact_callback_and_terminal_response_are_permitted(request_id, namespace):
    record = callback()
    record["id"] = request_id
    if namespace is None:
        record["params"]["namespace"] = None
    call = parse(record)
    assert (call.request_id, call.thread_id, call.turn_id, call.call_id, call.program) == (
        request_id, "thread", "turn", "call", "print('ok')",
    )
    assert tool_call_response(call, "ok") == {"id": request_id, "result": {
        "contentItems": [{"type": "inputText", "text": "ok"}], "success": True,
    }}


@pytest.mark.parametrize("field,value", [
    ("threadId", "other"), ("turnId", "other"), ("turnId", ""),
    ("callId", ""), ("callId", False), ("tool", "shell"),
    ("namespace", "foreign"), ("arguments", {"program": "ok", "path": "/host"}),
    ("arguments", {"program": False}), ("arguments", {}),
])
def test_callback_parameters_cannot_widen_the_fixed_exchange(field, value):
    record = callback()
    record["params"][field] = value
    with pytest.raises(ContractViolation):
        parse(record)


@pytest.mark.parametrize("field,value", [
    ("id", True), ("id", 1.0), ("id", []), ("id", ""),
    ("method", "process/exec"), ("result", {}), ("error", {}),
])
def test_callback_envelope_has_one_exact_shape(field, value):
    record = callback()
    record[field] = value
    with pytest.raises(ContractViolation):
        parse(record)


@pytest.mark.parametrize("field", ["callId", "turnId"])
def test_wire_identifier_limit_binds_before_turn_identity_is_known(field):
    record = callback()
    record["params"][field] = "x" * TOOL_IDENTIFIER_BYTES
    assert parse_tool_call(record, thread_id="thread", turn_id=None)
    record["params"][field] += "x"
    with pytest.raises(ContractViolation):
        parse_tool_call(record, thread_id="thread", turn_id=None)


def test_inbound_request_id_has_the_same_byte_bound():
    record = callback()
    record["id"] = "é" * (TOOL_IDENTIFIER_BYTES // 2)
    assert parse(record).request_id == record["id"]
    record["id"] += "x"
    with pytest.raises(ContractViolation):
        parse(record)


def test_program_and_output_bounds_permit_the_exact_byte_limit_and_refuse_one_more():
    record = callback()
    program = "é" * (TOOL_PROGRAM_BYTES // 2)
    record["params"]["arguments"]["program"] = program
    call = parse(record)
    assert call.program == program
    record["params"]["arguments"]["program"] += "x"
    with pytest.raises(ContractViolation):
        parse(record)
    output = "é" * (TOOL_OUTPUT_BYTES // 2)
    assert tool_call_response(call, output)["result"]["contentItems"][0]["text"] == output
    with pytest.raises(ContractViolation):
        tool_call_response(call, output + "x")
