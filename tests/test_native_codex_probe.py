"""Portable proofs of the investigation instrument, not native CLI evidence."""

import asyncio
import json
import os
import struct
import sys
import tomllib
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.native_codex_probe import (
    CANARY_PNG,
    RECORD_BYTES,
    TOTAL_BYTES,
    Dispatch,
    ProbeRefused,
    Wire,
    run_probe,
)
from tests.substrate import test_native_codex_mediation as native_probe


def test_native_fixture_creates_private_config_before_first_cli(tmp_path, monkeypatch):
    """Fixture ownership only; the subprocess and Linux host facts are doubles."""
    proc = {
        "/proc/net/dev": SimpleNamespace(read_text=lambda: "header\nheader\n lo: 0\n"),
        "/proc/net/route": SimpleNamespace(read_text=lambda: "header\n"),
    }
    monkeypatch.setattr(native_probe, "Path", lambda value: proc.get(value, Path(value)))
    monkeypatch.setattr(native_probe, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(native_probe, "os", SimpleNamespace(
        environ={"M8_CODEX_BINARY": "pinned-codex"}, getuid=lambda: 1000,
    ))
    calls = []

    def check_output(argv, *, env, cwd, timeout):
        assert cwd == tmp_path and timeout == 15
        assert set(env) == {"HOME", "CODEX_HOME", "PATH", "LANG"}
        assert Path(env["HOME"]) == tmp_path / "empty-home"
        config = Path(env["CODEX_HOME"])
        assert config == Path(env["HOME"]) / ".codex"
        assert config.is_dir()
        assert not tuple(config.iterdir())
        calls.append(argv)
        return b"codex-cli 0.153.4\n"

    monkeypatch.setattr(native_probe, "subprocess", SimpleNamespace(check_output=check_output))
    native = native_probe.native.__wrapped__(tmp_path)
    assert calls == [["pinned-codex", "--version"]]
    native_probe.argv_for(native, tmp_path, "http://127.0.0.1:1/v1", images=False)
    assert (Path(native[1]["CODEX_HOME"]) / "config.toml").is_file()


def test_native_canary_is_a_valid_image_not_a_decoder_failure():
    assert CANARY_PNG[:8] == b"\x89PNG\r\n\x1a\n"
    offset = 8
    types = []
    while offset < len(CANARY_PNG):
        size = struct.unpack("!I", CANARY_PNG[offset:offset + 4])[0]
        chunk = CANARY_PNG[offset + 4:offset + 8 + size]
        crc = struct.unpack("!I", CANARY_PNG[offset + 8 + size:offset + 12 + size])[0]
        assert zlib.crc32(chunk) == crc
        types.append(chunk[:4])
        if chunk[:4] == b"IDAT":
            assert len(zlib.decompress(chunk[4:])) == 3  # Filter + one gray/alpha pixel.
        offset += size + 12
    assert types == [b"IHDR", b"IDAT", b"IEND"]


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


@pytest.mark.parametrize("method", ["fs/readFile", "process/spawn", "config/value/write"])
async def test_client_rpc_names_never_become_server_dispatch_authority(method):
    invoked = []

    async def worker(program):
        invoked.append(program)
        return "ok"

    message = {**call(), "method": method}
    with pytest.raises(ProbeRefused, match="unknown operation"):
        await Dispatch("thread", "turn", worker).answer(message)
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


@pytest.mark.parametrize("model", ["probe-model", "gpt-5.5", "gpt-5.6-sol"])
async def test_model_selection_reaches_configuration_and_thread(tmp_path, model):
    config = tmp_path / "config"
    config.mkdir()
    native_probe.argv_for((Path("pinned-codex"), {"CODEX_HOME": str(config)}),
                          tmp_path, "http://127.0.0.1:1/v1", images=False, model=model)
    assert tomllib.loads((config / "config.toml").read_text())["model"] == model
    program = PEER.replace("MODE", "pass").replace(
        "assert read()['method'] == 'thread/start'",
        "selection = read()['params']['model']",
    ).replace("'program': 'pass'", "'program': selection")
    observed = []

    async def worker(program):
        observed.append(program)
        return "ok"

    env = {key: os.environ[key] for key in ("SYSTEMROOT",) if key in os.environ}
    result = await run_probe([sys.executable, "-I", "-u", "-c", program],
                             cwd=tmp_path, env=env, worker=worker, model=model, timeout=5)
    assert result["calls"] == ["call"]
    assert observed == [model]


@pytest.mark.parametrize("restricted", [False, True])
def test_catalog_changes_only_the_named_tool_selectors(tmp_path, restricted):
    entries = [{"slug": slug, "instructions": "preserve verbatim", "unknown": [1, True],
                "apply_patch_tool_type": "freeform", "tool_mode": "code_mode_only",
                "multi_agent_version": "v2"}
               for slug in ("gpt-5.5", "gpt-5.6-sol", "unselected")]
    original = {"models": entries, "unrelated": {"keep": True}}
    effective = json.loads(native_probe.catalog_for(json.dumps(original).encode(),
                                                    restricted=restricted))
    expected = json.loads(json.dumps(original))
    if restricted:
        for entry in expected["models"][:2]:
            entry.update(apply_patch_tool_type=None, tool_mode="direct", multi_agent_version=None)
    assert effective == expected
    config = tmp_path / "config"
    config.mkdir()
    path = config / "catalog.json"
    native_probe.argv_for((Path("pinned-codex"), {"CODEX_HOME": str(config)}),
                          tmp_path, "http://127.0.0.1:1/v1", images=False, catalog=path)
    configured = tomllib.loads((config / "config.toml").read_text())
    assert configured.get("model_catalog_json") == str(path)


def test_native_cleanup_tolerates_process_exit_race(monkeypatch):
    monkeypatch.setattr(native_probe.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(native_probe, "process_state", lambda pid: ("S", "same-start"))
    called = []

    def disappeared(pid, sig):
        called.append(pid)
        raise ProcessLookupError("exited after stat")

    monkeypatch.setattr(native_probe.os, "kill", disappeared)
    try:
        native_probe.stop_native(123, "same-start")
    except ProcessLookupError:
        pytest.fail("native exit during cleanup must not replace the original failure")
    assert called == [123]
    native_probe.stop_native(123, "different-start")
    assert called == [123]  # A reused PID cannot become a cleanup target.


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
