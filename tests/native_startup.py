"""Startup-only investigation over the existing owned byte transport.

No process is created here. Wire owns JSON/RPC validation; this adapter only
frames ProcessIO chunks. It does not qualify model access or native recovery.
"""

import json

from tests.native_codex_probe import RECORD_BYTES, ProbeRefused, Wire

CATALOG = "/opt/native-startup/catalog.json"
BOOTSTRAP = "/opt/native-startup/bootstrap.py"
MODELS = ("gpt-5.5", "gpt-5.6-sol")


class DuplexWire(Wire):
    def __init__(self, io, records=None):
        super().__init__(None, None)
        self.io = io
        self.pending = bytearray()
        self.records = records

    async def read(self):
        value = await super().read()
        if self.records is not None:
            self.records.append({"received": value})
        return value

    async def send(self, value):
        await super().send(value)
        if self.records is not None:
            self.records.append({"sent": value})

    async def _readline(self):
        while b"\n" not in self.pending:
            if len(self.pending) >= RECORD_BYTES:
                raise ProbeRefused("record bound")
            chunk = await self.io.read(min(8192, RECORD_BYTES - len(self.pending)))
            if not chunk:
                raw = bytes(self.pending)
                self.pending.clear()
                return raw
            self.pending.extend(chunk)
        end = self.pending.index(b"\n") + 1
        raw = bytes(self.pending[:end])
        del self.pending[:end]
        return raw

    async def _write(self, raw):
        await self.io.write(raw)


def configuration(model):
    if model not in MODELS:
        raise ValueError("startup probe model is not pinned")
    return f'''
model = {json.dumps(model)}
model_provider = "probe"
model_catalog_json = "{CATALOG}"
check_for_update_on_startup = false
web_search = "disabled"
[model_providers.probe]
name = "Unreachable credential-free fixture"
base_url = "http://127.0.0.1:1/v1"
wire_api = "responses"
requires_openai_auth = false
request_max_retries = 0
stream_max_retries = 0
stream_idle_timeout_ms = 1000
[features]
view_image = false
shell_tool = false
unified_exec = false
apply_patch_freeform = false
multi_agent = false
code_mode = false
js_repl = false
apps = false
'''


async def initialize(wire):
    result = await wire.rpc("initialize", {
        "clientInfo": {"name": "constructicon_startup_probe", "version": "0"},
        "capabilities": {"experimentalApi": True},
    })
    await wire.send({"method": "initialized"})
    return result
