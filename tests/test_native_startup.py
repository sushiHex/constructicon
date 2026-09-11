"""Portable framing proofs; these tests make no native-isolation claim."""

import inspect
import json
from types import SimpleNamespace

import pytest

from tests.native_codex_probe import RECORD_BYTES, TOTAL_BYTES, ProbeRefused
from tests.native_startup import MODELS, DuplexWire, configuration


class BytePeer:
    def __init__(self, source, *, fragment=8192):
        self.source = bytearray(source)
        self.fragment = fragment
        self.written = bytearray()

    async def read(self, maximum=8192):
        assert 0 < maximum <= 8192
        count = min(maximum, self.fragment)
        value = bytes(self.source[:count])
        del self.source[:count]
        return value

    async def write(self, value):
        self.written.extend(value)


@pytest.mark.parametrize("fragment", [1, 3, 8192])
async def test_duplex_framing_preserves_short_reads_and_coalesced_suffix(fragment):
    peer = BytePeer(b'{"id":1,"result":{"ok":true}}\n{"method":"warning"}\n', fragment=fragment)
    wire = DuplexWire(peer)
    try:
        result = await wire.rpc("fixture/read", {})
    except ProbeRefused as exc:
        pytest.fail(f"valid fragmented response refused: {exc}")
    assert result == {"ok": True}
    assert json.loads(peer.written) == {"id": 1, "method": "fixture/read", "params": {}}
    assert await wire.read() == {"method": "warning"}
    assert wire.warnings == [{"method": "warning"}]


@pytest.mark.parametrize("payload", [
    b'{"id":1,"id":2}\n', b'{"ok":NaN}\n', b'[]\n', b'{"ok":true}', b'\xff\n',
    b'x' * RECORD_BYTES, b'x' * RECORD_BYTES + b'\n',
], ids=["duplicate", "nonfinite", "array", "truncated", "unicode", "full", "oversized"])
async def test_duplex_uses_existing_strict_record_law(payload):
    try:
        await DuplexWire(BytePeer(payload)).read()
    except ProbeRefused:
        return
    pytest.fail("damaged or oversized record was accepted")


async def test_duplex_retains_cumulative_receive_and_send_bounds():
    peer = BytePeer(b'{}\n')
    wire = DuplexWire(peer)
    wire.received = TOTAL_BYTES
    try:
        await wire.read()
    except ProbeRefused:
        pass
    else:
        pytest.fail("cumulative receive bound was discarded")
    wire.sent = TOTAL_BYTES
    try:
        await wire.send({})
    except ProbeRefused:
        pass
    else:
        pytest.fail("cumulative send bound was discarded")
    assert not peer.written


@pytest.mark.parametrize("result", [b'{"id":2,"result":{}}\n', b'{"id":true,"result":{}}\n',
                                   b'{"id":1,"method":"process/spawn","params":{}}\n'])
async def test_duplex_cannot_turn_foreign_reply_or_request_into_success(result):
    try:
        await DuplexWire(BytePeer(result)).rpc("config/read", {})
    except ProbeRefused:
        return
    pytest.fail("foreign response or operation was accepted")


def test_startup_configuration_keeps_pins_and_has_no_authentication():
    import tomllib

    for model in MODELS:
        value = tomllib.loads(configuration(model))
        assert value["model"] == model
        provider = value["model_providers"]["probe"]
        assert provider["requires_openai_auth"] is False
        assert provider["base_url"] == "http://127.0.0.1:1/v1"
        assert not any(value["features"].values())
    with pytest.raises(ValueError, match="not pinned"):
        configuration("unqualified-model")


async def test_startup_uses_the_exact_owned_launch_interface():
    from constructicon.core.grants import Posture
    from constructicon.substrate.executors.linux import LinuxLauncher
    from tests.native_startup import BOOTSTRAP
    from tests.substrate.test_native_startup import observe

    invoked = []

    async def exchange(*args, **kwargs):
        inspect.signature(LinuxLauncher.exchange).bind(None, *args, **kwargs)
        assert args == (("/usr/bin/python3", "-I", BOOTSTRAP),)
        assert kwargs["workspace"] is None and kwargs["posture"] is Posture.READ
        assert kwargs["guard_fds"] == () and kwargs["timeout_s"] == 20
        assert callable(kwargs["conversation"])
        invoked.append(True)
        return "instrument-only"

    assert await observe(SimpleNamespace(exchange=exchange), MODELS[0]) == ({}, "instrument-only")
    assert invoked == [True]
