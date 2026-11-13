"""The advisory occupant of the model seat, proven without a network (#407).

``tests/advisory_replay.py`` asks a real model, through a public API, for each
next call of the channel stored-reply turn. These cases seat it with a scripted
endpoint, so the loop itself is tested: the request it builds from a capture,
what it hands back after each call, and that the adapter, worker, capture and
gate below it are the same ones the hostile cases run.

The last case is the advisory run itself. It is skipped unless a person turns
the network on, and it is never acceptance: see the module's warning and LIMITS.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from constructicon.substrate.executors.codex_protocol import CONTAINED_PYTHON_TOOL, MAX_TOOL_CALLS
from tests import advisory_replay
from tests.advisory_replay import (
    API_KEY,
    ENDPOINT,
    LIMITS,
    MODEL,
    NETWORK,
    OUTPUT,
    REQUEST,
    AdvisoryRefused,
    advisory,
    commitment,
    first_request,
    network_transport,
    public_body,
)
from tests.api import test_channel_reply_hostile_replies as hostile_cases
from tests.api.test_channel_reply_hostile_replies import (
    ACCEPTED,
    CHANNEL,
    EDIT,
    PEEK,
    PORTABLE,
    READ,
    RECORDED,
    SHARED,
    attempt,
    rewrite,
)
from tests.maintenance_instructions import CHANNEL_INSTRUCTION, WRITE_INSTRUCTION
from tests.model_seat import Turn
from tests.substrate.test_codex_adapter import portable_binding as portable_binding

concrete_application = hostile_cases.concrete_application
ADVISORY = replace(PORTABLE, model="advisory")
TOOL = {"type": "function", "name": CONTAINED_PYTHON_TOOL["name"],
        "description": CONTAINED_PYTHON_TOOL["description"],
        "parameters": CONTAINED_PYTHON_TOOL["inputSchema"]}


def message(role: str, *texts: str) -> dict:
    return {"id": f"msg-{role}-{len(texts)}", "type": "message", "role": role,
            "content": [{"type": "input_text", "text": text} for text in texts]}


def captured(instruction: str = CHANNEL_INSTRUCTION, tool: dict | None = None) -> dict:
    """A first request in the shape the placement lane retains (its keys, not its text)."""
    return {
        "model": "fixture-model", "stream": True, "store": False, "tool_choice": "auto",
        "parallel_tool_calls": False, "prompt_cache_key": "fixture-thread",
        "client_metadata": {"thread_id": "fixture-thread"},
        "include": ["reasoning.encrypted_content"],
        "reasoning": {"context": "all_turns", "effort": "low"}, "text": {"verbosity": "low"},
        "input": [
            {"id": "at-1", "role": "developer", "type": "additional_tools", "tools": [
                {"type": "namespace", "name": "functions", "description": "",
                 "tools": [{**(tool or TOOL), "strict": False}]}]},
            message("developer", "vendor base text"),
            message("developer", "skills", "`sandbox_mode` is `read-only`", "collaboration"),
            message("user", "<environment_context/>"),
            message("user", instruction),
        ],
    }


def call(program: str, number: int, *, name: str = "contained_python", arguments=None) -> list:
    """One response's output: an opaque reasoning item, then the function call."""
    return [{"type": "reasoning", "id": f"rs-{number}", "encrypted_content": "opaque"},
            {"type": "function_call", "id": f"fc-{number}", "name": name,
             "call_id": f"call-{number}",
             "arguments": json.dumps({"program": program}) if arguments is None else arguments}]


def says(text: str) -> list:
    return [{"type": "message", "role": "assistant",
             "content": [{"type": "output_text", "text": text}]}]


class ScriptedEndpoint:
    """Answers each request from a script; a step may read the request it answers."""

    def __init__(self, *steps) -> None:
        self.steps, self.bodies = steps, []

    def __call__(self, body: dict) -> dict:
        self.bodies.append(json.loads(json.dumps(body)))
        step = self.steps[min(len(self.bodies), len(self.steps)) - 1]
        output = step(body) if callable(step) else step
        if isinstance(output, BaseException):
            raise output
        if isinstance(output, dict):
            return output  # A whole response, as the case wrote it.
        return {"status": "completed", "error": None, "output": output, "usage": {
            "input_tokens": 7, "output_tokens": 3, "note": "a provider's free text"}}


def test_the_request_sent_is_the_capture_without_the_vendors_plumbing():
    capture = captured()
    body = public_body(first_request(json.dumps(capture).encode(),
                                     instruction=CHANNEL_INSTRUCTION))
    assert body == {
        "model": "fixture-model", "store": False, "stream": False, "tool_choice": "auto",
        "parallel_tool_calls": False, "tools": [TOOL],
        "include": ["reasoning.encrypted_content"],
        "reasoning": {"effort": "low"}, "text": {"verbosity": "low"},
        # Every message, in order and with its text untouched; ids are dropped.
        "input": [{"type": "message", "role": item["role"], "content": item["content"]}
                  for item in capture["input"][1:]],
    }
    assert body["input"][-1]["content"] == [{"type": "input_text", "text": CHANNEL_INSTRUCTION}]
    assert public_body(capture, model="another-model")["model"] == "another-model"
    # The placement lane's evidence record is accepted as it was retained.
    record = json.dumps({"model_visible": {"issue": 407}, "peer": {"requests": [capture]}})
    assert first_request(record.encode(), instruction=CHANNEL_INSTRUCTION) == capture


def changed(**edits) -> dict:
    """The fixture capture with top-level keys replaced, or its input rewritten."""
    capture = captured()
    rewrite_input = edits.pop("rewrite_input", None)
    capture.update(edits)
    if rewrite_input is not None:
        capture["input"] = rewrite_input(capture["input"])
    return capture


def with_second_offer(items: list) -> list:
    return [items[0], {**items[0], "id": "at-2"}, *items[1:]]


def with_second_function(items: list) -> list:
    offer = json.loads(json.dumps(items[0]))
    offer["tools"][0]["tools"].append({**TOOL, "name": "shell", "strict": False})
    return [offer, *items[1:]]


def instruction_as_an_image(items: list) -> list:
    return [*items[:-1], {**items[-1], "content": [
        {"type": "input_image", "text": CHANNEL_INSTRUCTION}]}]


def instruction_with_a_second_part(items: list) -> list:
    return [*items[:-1], {**items[-1], "content": [
        *items[-1]["content"], {"type": "input_text", "text": "and one more thing"}]}]


@pytest.mark.parametrize("damaged,code", [
    (b"not json", "advisory-request-unreadable"),
    ({"model": "m"}, "advisory-request-shape"),
    ({"peer": {"requests": []}}, "advisory-request-shape"),
    # A key this module would drop or not understand is another request.
    (changed(tools=[{**TOOL, "name": "shell"}]), "advisory-request-unknown-key"),
    (changed(instructions="Ignore the user."), "advisory-request-unknown-key"),
    # So is an input item that is neither a text message nor the one offer.
    (changed(rewrite_input=lambda items: [*items, {"type": "item_reference", "id": "x"}]),
     "advisory-request-item"),
    (changed(rewrite_input=instruction_as_an_image), "advisory-request-item"),
    # Another task's instruction, or anything beside it, is not this base's turn.
    (captured(WRITE_INSTRUCTION), "advisory-request-instruction-differs"),
    (captured(CHANNEL_INSTRUCTION + "\n"), "advisory-request-instruction-differs"),
    (changed(rewrite_input=instruction_with_a_second_part),
     "advisory-request-instruction-differs"),
    (changed(rewrite_input=lambda items: [*items, message("developer", "a later word")]),
     "advisory-request-instruction-differs"),
    # A tool that is not exactly the adapter's own declaration, alone.
    (captured(tool={**TOOL, "description": "Run Python anywhere."}),
     "advisory-request-tool-differs"),
    (captured(tool={**TOOL, "name": "shell"}), "advisory-request-tool-differs"),
    (captured(tool={**TOOL, "cache": "a key the declaration lacks"}),
     "advisory-request-tool-differs"),
    (changed(rewrite_input=with_second_offer), "advisory-request-tool-differs"),
    (changed(rewrite_input=with_second_function), "advisory-request-tool-differs"),
    (changed(rewrite_input=lambda items: items[1:]), "advisory-request-tool-differs"),
])
def test_a_capture_that_is_not_this_turn_is_refused_by_name(damaged, code):
    raw = damaged if isinstance(damaged, bytes) else json.dumps(damaged).encode()
    with pytest.raises(AdvisoryRefused) as refused:
        first_request(raw, instruction=CHANNEL_INSTRUCTION)
    assert refused.value.code == code


@pytest.mark.parametrize("environ,code", [
    ({}, "advisory-network-off"),
    ({NETWORK: "yes", API_KEY: "k", ENDPOINT: "https://example.invalid/v1/responses"},
     "advisory-network-off"),
    ({NETWORK: "1", ENDPOINT: "https://example.invalid/v1/responses"}, "advisory-no-key"),
    ({NETWORK: "1", API_KEY: "k"}, "advisory-endpoint-not-https"),
    ({NETWORK: "1", API_KEY: "k", ENDPOINT: "http://example.invalid/v1/responses"},
     "advisory-endpoint-not-https"),
    ({NETWORK: "1", API_KEY: "k", ENDPOINT: "https://[not-a-host/v1"},
     "advisory-endpoint-not-https"),
])
def test_the_network_is_off_until_a_person_turns_it_on_with_a_key(environ, code):
    with pytest.raises(AdvisoryRefused) as refused:
        network_transport(environ)
    assert refused.value.code == code


def test_the_transport_sends_one_keyed_post_and_reports_a_refusal_by_status(monkeypatch):
    """The only code that would touch a network, with the opener replaced: nothing is sent."""
    import io
    import urllib.error
    import urllib.request

    opened = []
    replies = [io.BytesIO(b'{"output": []}'),
               urllib.error.HTTPError("https://example.invalid", 401, "no", None,
                                      io.BytesIO(b"the body may echo the request")),
               io.BytesIO(b" " * (advisory_replay.MAX_RESPONSE_BYTES + 1))]

    def opener(request, timeout):
        opened.append((request, timeout))
        reply = replies[len(opened) - 1]
        if isinstance(reply, BaseException):
            raise reply
        return reply

    # A redirect would carry the key elsewhere; the opener refuses to follow one.
    request = urllib.request.Request("https://example.invalid/v1/responses")
    with pytest.raises(AdvisoryRefused) as redirected:
        advisory_replay._NoRedirect().redirect_request(
            request, None, 302, "Found", {}, "http://elsewhere.invalid/collect")
    assert str(redirected.value) == "advisory-endpoint-redirected: HTTP 302"
    monkeypatch.setattr(advisory_replay, "_open", opener)
    send = network_transport({NETWORK: "1", API_KEY: "the-key",
                              ENDPOINT: "https://example.invalid/v1/responses"})
    assert send({"model": "m", "input": []}) == {"output": []}
    (request, timeout), = opened
    assert request.full_url == "https://example.invalid/v1/responses"
    assert request.get_method() == "POST" and timeout == advisory_replay.SOCKET_TIMEOUT_S
    assert request.get_header("Authorization") == "Bearer the-key"
    assert json.loads(request.data) == {"model": "m", "input": []}
    for code, text in (("advisory-endpoint-refused", "advisory-endpoint-refused: HTTP 401"),
                       ("advisory-response-too-large", "advisory-response-too-large")):
        with pytest.raises(AdvisoryRefused) as refused:
            send({})
        assert refused.value.code == code and str(refused.value) == text
        assert "the-key" not in str(refused.value)


async def advised(concrete_application, binding, tmp_path, monkeypatch, endpoint):
    resources, _executor, _system, control, launch = concrete_application
    await control.shutdown()
    seat = advisory(captured(), endpoint)
    observed, realness, _content = await attempt(resources, launch, binding, tmp_path,
                                                 monkeypatch, seat)
    # Below the seat it is the hostile cases' world, and the worker is its launcher.
    assert realness == ADVISORY and realness.worker is type(launch)
    return seat, observed


@CHANNEL
async def test_a_scripted_model_reads_then_edits_through_the_real_path(
    concrete_application, portable_binding, tmp_path, monkeypatch,
):
    endpoint = ScriptedEndpoint(call(READ, 1), call(EDIT, 2), says("done"))
    seat, observed = await advised(concrete_application, portable_binding, tmp_path,
                                   monkeypatch, endpoint)
    assert observed == SHARED["read-then-edit"][1] and observed["outcome"] == ACCEPTED
    assert seat.conversation.refusal is None and seat.conversation.requests == 3
    first, second, third = endpoint.bodies
    assert first == public_body(captured())
    # Each later request is the first one, then everything the model sent, verbatim,
    # then what the adapter handed back for the call: the text the peer was shown.
    assert second["input"] == [*first["input"], *call(READ, 1), {
        "type": "function_call_output", "call_id": "call-1", "output": seat.seen[0]}]
    assert third["input"] == [*second["input"], *call(EDIT, 2), {
        "type": "function_call_output", "call_id": "call-2", "output": seat.seen[1]}]
    assert {key: value for key, value in second.items() if key != "input"} == {
        key: value for key, value in first.items() if key != "input"}
    # What it recorded is the record a replay runs from.
    recorded = Turn.from_json(seat.recording().to_json())
    assert recorded == RECORDED["read-then-edit"]
    # The two files: the turn is the record, and the outcome holds nothing a model
    # or a provider wrote, only counts and commitments.
    outcome = write_outcome(tmp_path / "advisory", seat, observed)
    assert Turn.from_json((tmp_path / "advisory/turn.json").read_text("utf-8")) == recorded
    assert outcome["usage"] == [{"input_tokens": 7, "output_tokens": 3}] * 3
    assert outcome["turn"] == commitment(recorded.to_json()) and outcome["calls"] == 2
    public = (tmp_path / "advisory/outcome.json").read_text("utf-8")
    assert json.loads(public) == outcome and outcome["observed"] == observed
    assert not any(text in public for text in (
        "free text", "_stored_reply", "read_bytes", "opaque", CHANNEL_INSTRUCTION[:60]))


@CHANNEL
async def test_the_scripted_models_edit_depends_on_the_output_it_was_handed(
    concrete_application, portable_binding, tmp_path, monkeypatch,
):
    endpoint = ScriptedEndpoint(
        call(READ, 1), lambda body: call(rewrite((body["input"][-1]["output"],)), 2),
        says("rewrote it"))
    seat, observed = await advised(concrete_application, portable_binding, tmp_path,
                                   monkeypatch, endpoint)
    assert observed == SHARED["rewrite-from-what-it-read"][1]
    assert seat.recording().reply == "rewrote it" and seat.conversation.refusal is None


@CHANNEL
async def test_a_scripted_model_that_only_talks_changes_nothing(
    concrete_application, portable_binding, tmp_path, monkeypatch,
):
    endpoint = ScriptedEndpoint(says("The sandbox is read-only, so I changed nothing."))
    seat, observed = await advised(concrete_application, portable_binding, tmp_path,
                                   monkeypatch, endpoint)
    assert observed == SHARED["text-only"][1]
    assert seat.recording() == Turn((), True, "The sandbox is read-only, so I changed nothing.")
    assert seat.conversation.requests == 1


@CHANNEL
async def test_the_adapter_and_not_this_loop_refuses_the_ninth_call(
    concrete_application, portable_binding, tmp_path, monkeypatch,
):
    endpoint = ScriptedEndpoint(lambda body: call(PEEK, len(body["input"])))
    seat, observed = await advised(concrete_application, portable_binding, tmp_path,
                                   monkeypatch, endpoint)
    assert observed == SHARED["nine-calls"][1]
    assert len(seat.sent) == MAX_TOOL_CALLS + 1 == seat.conversation.requests
    assert seat.conversation.refusal is None


@CHANNEL
@pytest.mark.parametrize("second,refusal", [
    (call(EDIT, 2, name="shell"), "advisory-unknown-tool"),
    (call(EDIT, 2, arguments="not json"), "advisory-tool-arguments"),
    (call(EDIT, 2, arguments=json.dumps({"program": EDIT, "cwd": "/"})),
     "advisory-tool-arguments"),
    ([*call(EDIT, 2), *call(PEEK, 3)], "advisory-parallel-tool-calls"),
    ("not a list", "advisory-response-shape"),
    (OSError("connection reset"), "advisory-transport-failed (OSError)"),
    # An endpoint's failure is not the model choosing to stop.
    ({"status": "failed", "error": {"message": "overloaded"}, "output": []},
     "advisory-response-error"),
    ({"status": "incomplete", "error": None, "output": says("I was cut")},
     "advisory-response-incomplete"),
    ({"output": says("no status at all")}, "advisory-response-incomplete"),
])
async def test_what_the_loop_cannot_carry_ends_the_turn_with_a_name(
    concrete_application, portable_binding, tmp_path, monkeypatch, second, refusal,
):
    endpoint = ScriptedEndpoint(call(READ, 1), second)
    seat, observed = await advised(concrete_application, portable_binding, tmp_path,
                                   monkeypatch, endpoint)
    # The turn ended after the read; the edit never reached the worker.
    assert seat.conversation.refusal == refusal
    assert observed == SHARED["read-then-end"][1] and seat.sent == [READ]
    assert seat.recording() == Turn(RECORDED["read-then-end"].calls, True, None)


def test_an_answer_after_the_run_ended_changes_nothing():
    """The adapter closed the peer while the endpoint was thinking: the record stays put."""
    seat = advisory(captured(), ScriptedEndpoint(call(READ, 1), call(EDIT, 2)))
    assert seat.conversation.refusal is None and seat.conversation.requests == 1
    before = list(seat.emitted)
    seat.stdin_closed = True
    seat._deliver(0, EDIT)
    assert seat.emitted == before
    assert seat.conversation.refusal == "advisory-answer-after-the-run-ended"
    # Once the record is frozen, a step asks nothing and uses nothing.
    late = advisory(captured(), ScriptedEndpoint(call(READ, 1), call(EDIT, 2)))
    late.close()
    assert late._program(1) is None and late.conversation.requests == 1
    assert late.conversation.refusal == "advisory-answer-after-the-run-ended"


def test_one_request_has_one_elapsed_deadline_and_a_late_answer_is_never_read():
    import threading

    release = threading.Event()

    def slow(body):
        release.wait(30)
        return {"status": "completed", "error": None, "output": call(READ, 1)}

    seat = advisory(captured(), slow, deadline_s=0.05)
    try:
        # No call was sent: the seat ended its turn, and says why.
        assert seat.conversation.refusal == "advisory-request-deadline"
        assert not seat.callbacks and seat.conversation.items == []
    finally:
        release.set()


def write_outcome(out: Path, seat, observed: dict | None) -> dict:
    """Freeze the record and write the two files; return what may be shared."""
    seat.close()
    if seat.asking is not None:
        seat.asking.join(advisory_replay.REQUEST_DEADLINE_S)
    out.mkdir(parents=True, exist_ok=True)
    recorded = seat.recording()
    # The turn holds the model's programs: private. The outcome holds none.
    turn = recorded.to_json()
    (out / "turn.json").write_text(turn, encoding="utf-8")
    outcome = {
        "advisory": True, "meaning": "not acceptance and not evidence for a live attempt",
        "model": seat.conversation.body["model"], "observed": observed,
        "refusal": seat.conversation.refusal, "requests": seat.conversation.requests,
        "usage": seat.conversation.usage, "calls": len(recorded.calls),
        "completed": recorded.completed, "replied": recorded.reply is not None,
        "instruction": commitment(CHANNEL_INSTRUCTION), "turn": commitment(turn),
        "limits": list(LIMITS),
    }
    (out / "outcome.json").write_text(json.dumps(outcome, indent=1), encoding="utf-8")
    return outcome


@CHANNEL
async def test_a_real_model_attempts_the_stored_reply_task(
    concrete_application, portable_binding, tmp_path, monkeypatch,
):
    """ADVISORY: sends the captured request to an endpoint and runs what comes back.

    Skipped unless a person turns the network on. The model's programs run
    UNCONTAINED on this machine with this user's rights, and what they print is
    sent to the endpoint: run it in WSL2 or a disposable virtual machine, and
    read the warning at the top of ``tests/advisory_replay.py`` first. Whatever
    happens here is never acceptance.
    """
    if os.environ.get(NETWORK) != "1":
        pytest.skip(f"advisory replay is off; it sends a request only with {NETWORK}=1")
    send = network_transport(os.environ)
    # The worker inherits this process's environment; the key must not be in it.
    monkeypatch.delenv(API_KEY)
    if not os.environ.get(REQUEST):
        raise AdvisoryRefused("advisory-no-request", f"set {REQUEST} to the captured request")
    capture = first_request(Path(os.environ[REQUEST]).read_bytes(),
                            instruction=CHANNEL_INSTRUCTION)
    out = Path(os.environ.get(OUTPUT) or tmp_path / "advisory")
    resources, _executor, _system, control, launch = concrete_application
    await control.shutdown()
    seat = advisory(capture, send, model=os.environ.get(MODEL))
    observed: dict | None = None
    try:
        if seat.conversation.refusal is None:
            observed, realness, _content = await attempt(
                resources, launch, portable_binding, tmp_path, monkeypatch, seat)
            assert realness == ADVISORY
    finally:
        outcome = write_outcome(out, seat, observed)
        print(f"\nadvisory outcome ({out / 'outcome.json'}):\n{json.dumps(outcome, indent=1)}")
    # No task success is asserted: the outcome is the finding. A refusal means
    # this loop, and not the model, ended the turn.
    assert seat.conversation.refusal is None, seat.conversation.refusal
