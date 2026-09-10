"""Portable proofs of the investigation instrument, not native CLI evidence."""

import asyncio
import json
import os
import sys

import pytest

from tests.native_codex_probe import (
    RECORD_BYTES,
    TOTAL_BYTES,
    Dispatch,
    ProbeRefused,
    Wire,
    run_probe,
)


def call(**changes):
    params = {"threadId": "thread", "turnId": "turn", "callId": "call",
              "tool": "contained_python", "arguments": {"program": "pass"}}
    params.update(changes)
    return {"id": 10, "method": "item/tool/call", "params": params}


@pytest.mark.parametrize("change", [
    {"threadId": "other"}, {"turnId": "other"}, {"tool": "shell"},
    {"namespace": "host"}, {"callId": ""}, {"callId": True},
    {"workspace": "/host"}, {"arguments": {"program": "pass", "grants": "all"}},
    {"arguments": {"program": 1}}, {"arguments": {"program": "x" * (RECORD_BYTES + 1)}},
], ids=["thread", "turn", "tool", "namespace", "empty-call", "bool-call", "workspace",
        "grants", "program-type", "program-bound"])
async def test_dispatch_never_accepts_authority_or_identity_from_peer(change):
    invoked = []

    async def worker(program):
        invoked.append(program)
        return "ok"

    with pytest.raises(ProbeRefused):
        await Dispatch("thread", "turn", worker).answer(call(**change))
    assert not invoked


async def test_response_loss_cannot_repeat_work_and_sessions_do_not_share_calls():
    invoked = []

    async def worker(program):
        invoked.append(program)
        return "observed"

    first = Dispatch("thread", "turn", worker)
    result = await first.answer(call())  # Drop this response as if the connection died.
    assert result["result"]["contentItems"][0]["text"] == "observed"
    with pytest.raises(ProbeRefused, match="repeated"):
        await first.answer(call())
    assert invoked == ["pass"]
    second = Dispatch("sibling", "turn", worker)
    with pytest.raises(ProbeRefused, match="foreign"):
        await second.answer(call())
    await second.answer(call(threadId="sibling"))
    assert len(invoked) == 2


async def test_cancellation_joins_the_worker_and_does_not_reopen_its_call():
    entered, exited = asyncio.Event(), asyncio.Event()

    async def worker(program):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            exited.set()

    dispatch = Dispatch("thread", "turn", worker)
    pending = asyncio.create_task(dispatch.answer(call()))
    await asyncio.wait_for(entered.wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert exited.is_set()
    with pytest.raises(ProbeRefused, match="repeated"):
        await dispatch.answer(call())


@pytest.mark.parametrize("payload", [
    b'', b'{}', b'[]\n', b'{"a":1,"a":2}\n', b'{"a":NaN}\n', b'\xff\n',
    b'{"a":"\\ud800"}\n', b'x' * (RECORD_BYTES + 1) + b'\n',
], ids=["eof", "truncated", "array", "duplicate", "nan", "encoding", "unicode", "bound"])
async def test_bad_frames_refuse_before_dispatch(payload):
    reader = asyncio.StreamReader(limit=RECORD_BYTES)
    reader.feed_data(payload)
    reader.feed_eof()
    with pytest.raises(ProbeRefused):
        await Wire(reader, None).read()


async def test_valid_frames_still_obey_total_budget():
    reader = asyncio.StreamReader(limit=RECORD_BYTES)
    payload = (json.dumps({"method": "notice", "data": "x" * 100_000}) + "\n").encode()
    reader.feed_data(payload * 30)
    wire = Wire(reader, None)
    with pytest.raises(ProbeRefused, match="oversized"):
        for _ in range(30):
            await wire.read()
    assert wire.received > TOTAL_BYTES


async def test_worker_output_is_bounded():
    async def worker(program):
        return "x" * (RECORD_BYTES + 1)

    with pytest.raises(ProbeRefused, match="output bound"):
        await Dispatch("thread", "turn", worker).answer(call())


PEER = '''
import json, sys, time
def read(): return json.loads(sys.stdin.readline())
def send(value): print(json.dumps(value), flush=True)
assert read()['method'] == 'initialize'
send({'id': 1, 'result': {}})
assert read()['method'] == 'initialized'
assert read()['method'] == 'thread/start'
send({'id': 2, 'result': {'thread': {'id': 'thread'}}})
assert read()['method'] == 'turn/start'
send({'id': 3, 'result': {'turn': {'id': 'turn'}}})
MODE
send({'method': 'item/tool/call', 'id': 10, 'params': {
    'threadId': 'thread', 'turnId': 'turn', 'callId': 'call',
    'tool': 'contained_python', 'arguments': {'program': 'pass'}}})
assert read()['result']['success'] is True
send({'method': 'turn/completed', 'params': {
    'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'completed'}}})
time.sleep(60)
'''


@pytest.mark.parametrize("mode", ["success", "eof", "stderr", "timeout", "cancel"])
async def test_real_pipe_lifetime_with_scripted_peer(tmp_path, mode):
    invoked = []

    async def worker(program):
        invoked.append(program)
        return "ok"

    modes = {"success": "pass", "eof": "sys.exit(0)",
             "stderr": f"sys.stderr.write('x' * {RECORD_BYTES + 1}); sys.stderr.flush()",
             "timeout": "time.sleep(60)", "cancel": "time.sleep(60)"}
    env = {key: os.environ[key] for key in ("SYSTEMROOT",) if key in os.environ}
    pending = asyncio.create_task(run_probe(
        [sys.executable, "-I", "-u", "-c", PEER.replace("MODE", modes[mode])],
        cwd=tmp_path, env=env, worker=worker, timeout=1 if mode == "timeout" else 5,
    ))
    if mode == "cancel":
        await asyncio.sleep(.1)
        pending.cancel()
    if mode == "success":
        result = await asyncio.wait_for(pending, 6)
        assert result["calls"] == ["call"] and invoked == ["pass"]
    else:
        with pytest.raises((ExceptionGroup, TimeoutError, asyncio.CancelledError)):
            await asyncio.wait_for(pending, 6)
        # The two OS pipes have no shared ordering. Overflow must fail the
        # probe, but may be observed after the preceding tool dispatch.
        assert invoked in ([], ["pass"]) if mode == "stderr" else not invoked
