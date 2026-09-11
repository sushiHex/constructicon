"""Opt-in native evidence. No account or remote provider can be reached.

The CI process lives in a fresh, loopback-only network namespace, with its own
PID namespace and an empty environment. The fake Responses endpoint speaks the
documented custom-provider protocol; it does not emulate authentication.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from constructicon.core.executor import TaskSpec
from constructicon.core.grants import Posture
from constructicon.core.identity import parse_json_value
from tests.containedworld import RecordedExecutorProvider
from tests.native_codex_probe import CANARY_PNG, RECORD_BYTES, run_probe
from tests.substrate.test_contained_workspace import context
from tests.substrate.test_contained_workspace import provider as provider
from tests.substrate.test_linux_containment import launcher as launcher

WORKER = "import sys; exec(sys.stdin.read())"
PROGRAM = (
    "import json, pathlib\n"
    "assert not pathlib.Path('/etc/shadow').exists()\n"
    "try:\n"
    "    pathlib.Path('/workspace/forbidden-write').write_text('must refuse')\n"
    "except OSError as exc:\n"
    "    assert exc.errno == 30\n"
    "else:\n"
    "    raise AssertionError('READ mount was writable')\n"
    "print(json.dumps({'type':'result','output':{'contained':True}}))\n"
)


def events(items, *, model="probe-model"):
    response = {"id": "resp_probe", "object": "response", "model": model,
                "status": "in_progress", "output": []}
    yield {"type": "response.created", "response": response}
    for index, item in enumerate(items):
        yield {"type": "response.output_item.added", "output_index": index, "item": item}
        if item["type"] == "message":
            yield {"type": "response.output_text.delta", "output_index": index,
                   "content_index": 0, "item_id": item["id"], "delta": "fixture complete"}
        yield {"type": "response.output_item.done", "output_index": index, "item": item}
    yield {"type": "response.completed", "response": {
        **response, "status": "completed", "output": items,
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }}


@asynccontextmanager
async def fake_provider(tool, arguments, *, model="probe-model"):
    requests, failures = [], []
    handlers = set()

    async def respond(reader, writer):
        task = asyncio.current_task()
        handlers.add(task)
        try:
            async with asyncio.timeout(10):
                headers = await reader.readuntil(b"\r\n\r\n")
                lines = headers.decode("ascii").split("\r\n")
                assert lines[0] == "POST /v1/responses HTTP/1.1", lines[0]
                fields = dict(line.lower().split(":", 1) for line in lines[1:] if line)
                assert "authorization" not in fields  # No placeholder or token needed.
                size = int(fields["content-length"])
                assert 0 < size <= 1024 * 1024
                request = parse_json_value((await reader.readexactly(size)).decode())
                requests.append(request)
                assert len(requests) <= 2, "unexpected retry or extra turn"
                assert request["model"] == model
                if len(requests) == 1:
                    item = {"id": "fc_probe", "call_id": "call_probe", "name": tool}
                    if tool == "apply_patch":
                        items = [{**item, "type": "custom_tool_call", "input": arguments["patch"]}]
                    else:
                        items = [{**item, "type": "function_call",
                                  "arguments": json.dumps(arguments)}]
                else:
                    items = [{"id": "msg_probe", "type": "message", "role": "assistant",
                              "status": "completed", "content": [
                                  {"type": "output_text", "text": "fixture complete"}]}]
                payload = b"".join(
                    ("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode()
                    for event in events(items, model=model)
                )
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n"
                    + f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload,
                )
                await writer.drain()
        except Exception as exc:
            failures.append(repr(exc))
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            finally:
                handlers.discard(task)

    server = await asyncio.start_server(respond, "127.0.0.1", 0, limit=RECORD_BYTES)
    try:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1", requests, failures
    finally:
        server.close()
        await server.wait_closed()
        pending = tuple(handlers)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.fixture
def native(tmp_path):
    binary = os.environ.get("M8_CODEX_BINARY")
    if sys.platform != "linux" or not binary:
        if os.environ.get("M8_NATIVE_CODEX_REQUIRED"):
            pytest.fail("required credential-free native CLI environment missing")
        pytest.skip("pinned Linux CLI probe not exercised; dedicated lane required")
    # An env flag is insufficient. Prove this namespace has no external interface
    # or route before executing the native harness (which is not yet trusted).
    interfaces = {line.split(":")[0].strip() for line in Path("/proc/net/dev").read_text()
                  .splitlines()[2:]}
    assert interfaces == {"lo"}, interfaces
    assert len(Path("/proc/net/route").read_text().splitlines()) == 1
    assert os.getuid() != 0
    assert not {key for key in os.environ if "TOKEN" in key or "API_KEY" in key}
    home = tmp_path / "empty-home"
    (home / ".codex").mkdir(parents=True)
    env = {"HOME": str(home), "CODEX_HOME": str(home / ".codex"),
           "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    version = subprocess.check_output([binary, "--version"], env=env, cwd=tmp_path, timeout=15)
    assert version.strip() == b"codex-cli 0.153.4"
    return Path(binary), env


def write_evidence(name, value):
    directory = os.environ.get("M8_EVIDENCE_DIRECTORY")
    if directory:
        (Path(directory) / name).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def catalog_for(source: bytes, *, restricted: bool) -> bytes:
    """Change only three tool selectors, never model identity or instructions."""
    catalog = json.loads(source)
    selected = {"gpt-5.5", "gpt-5.6-sol"}
    assert {entry["slug"] for entry in catalog["models"]} >= selected
    if restricted:
        for entry in catalog["models"]:
            if entry["slug"] in selected:
                entry.update(apply_patch_tool_type=None, tool_mode="direct",
                             multi_agent_version=None)
    return (json.dumps(catalog, sort_keys=True) + "\n").encode()


def argv_for(native, cwd, endpoint, *, images, model="probe-model", catalog=None):
    binary, env = native
    configuration = f'''
model = "{model}"
model_provider = "probe"
model_context_window = 32768
model_auto_compact_token_limit = 30000
check_for_update_on_startup = false
web_search = "disabled"
{f'model_catalog_json = {json.dumps(str(catalog))}' if catalog else ''}
[model_providers.probe]
name = "Credential-free loopback fixture"
base_url = "{endpoint}"
wire_api = "responses"
requires_openai_auth = false
request_max_retries = 0
stream_max_retries = 0
stream_idle_timeout_ms = 10000
[features]
view_image = {str(images).lower()}
shell_tool = false
unified_exec = false
apply_patch_freeform = false
multi_agent = false
code_mode = false
js_repl = false
apps = false
'''
    config = Path(env["CODEX_HOME"])
    (config / "config.toml").write_text(configuration)
    return [str(binary), "app-server", "--strict-config", "--stdio"]


def test_pinned_native_schema_inventory(native, tmp_path):
    binary, env = native
    output = tmp_path / "schema"
    subprocess.run([str(binary), "app-server", "generate-json-schema", "--experimental",
                    "--out", str(output)], check=True, env=env, cwd=tmp_path, timeout=30,
                   capture_output=True)
    schemas = {path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in output.rglob("*.json")}
    params = json.loads((output / "DynamicToolCallParams.json").read_text())
    assert set(params["required"]) == {"arguments", "callId", "threadId", "tool", "turnId"}
    client = json.loads((output / "ClientRequest.json").read_text())
    methods = sorted({variant["properties"]["method"]["enum"][0]
                      for variant in client["oneOf"]})
    features = subprocess.check_output(
        [str(binary), "features", "list"], env=env, cwd=tmp_path, timeout=15,
    ).decode()
    flags = {line.split()[0]: line.split()[-1] for line in features.splitlines()}
    assert flags["view_image"] == "true"
    write_evidence("codex-schema.json", {"schemas": schemas, "client_methods": methods,
                                        "default_features": features,
                                        "binary_sha256": hashlib.sha256(binary.read_bytes())
                                        .hexdigest()})
    assert "thread/start" in methods and "turn/start" in methods


@pytest.mark.parametrize("model,operation,catalog_mode", [
    *(("probe-model", operation, "bundled") for operation in (
        "contained_python", "exec_command", "view_image",
    )),
    *((model, operation, mode) for model in ("gpt-5.5", "gpt-5.6-sol")
      for mode in ("bundled", "restricted") for operation in (
        "contained_python", "exec_command", "view_image", "apply_patch",
        "fs/readFile", "process/spawn", "config/value/write",
    )),
    *((model, operation, "unchanged") for model in ("gpt-5.5", "gpt-5.6-sol")
      for operation in ("contained_python", "apply_patch")),
])
@pytest.mark.parametrize("images", [True, False], ids=["image-control", "image-disabled"])
async def test_native_dynamic_dispatch_and_builtin_probe(
    native, tmp_path, provider, launcher, model, operation, images, catalog_mode,
):
    catalog_path = None
    catalog_evidence = None
    restricted = catalog_mode == "restricted"
    if catalog_mode != "bundled":
        source = Path(os.environ["M8_CODEX_CATALOG"]).read_bytes()
        assert hashlib.sha256(source).hexdigest() == (
            "d7136a413cfac1b5b1686d9e0dcc5c80ca05bebed5e9fc3911376561d0ef6ee8"
        )
        content = catalog_for(source, restricted=restricted)
        catalog_path = Path(native[1]["CODEX_HOME"]) / "catalog.json"
        catalog_path.write_bytes(content)
        catalog_evidence = {"source_sha256": hashlib.sha256(source).hexdigest(),
                            "effective_sha256": hashlib.sha256(content).hexdigest(),
                            "mode": catalog_mode}
    provider.launcher = launcher
    executor = RecordedExecutorProvider(launcher, provider, WORKER)
    await executor.qualify()
    workspace = await provider.acquire(context())
    acquired = await executor.acquire(context(binding="executor"))
    await workspace.materialize()
    await acquired.materialize()
    observed = []

    async def worker(program):
        result = await acquired.resource.execute(
            TaskSpec(instruction=program), workspace=workspace.resource,
            grants=acquired.resource.context.binding.effective_grants,
        )
        assert result.status == "success", result
        observed.append(result.output)
        return json.dumps(result.output)

    # A canary in the harness home is NOT a credential. A disabled built-in
    # reaching it would refute exclusive mediation despite a successful callback.
    canary = Path(native[1]["HOME"]) / "builtin-bypass"
    patch_canary = Path(native[1]["HOME"]) / "native-patch-fixture.txt"
    image_canary = Path(native[1]["HOME"]) / "private.png"
    image_canary.write_bytes(CANARY_PNG)
    arguments = {
        "contained_python": {"program": PROGRAM +
                             f"assert not pathlib.Path({str(image_canary)!r}).exists()\n"},
        "exec_command": {"cmd": f"printf bypass > {canary}", "max_output_tokens": 100},
        "view_image": {"path": str(image_canary)},
        "apply_patch": {"patch": f"*** Begin Patch\n*** Add File: {patch_canary}\n"
                                 "+fixture only\n*** End Patch\n"},
        # Client RPC names are sent as model tool calls, never as client RPCs.
        # Exact unsupported-call output proves name dispatch, not argument validation.
        "fs/readFile": {"path": str(image_canary)},
        "process/spawn": {"command": ["/usr/bin/true"]},
        "config/value/write": {"keyPath": "model", "value": "not-selected",
                               "mergeStrategy": "replace"},
    }[operation]
    try:
        async with fake_provider(operation, arguments, model=model) as exchange:
            endpoint, requests, failures = exchange
            argv = argv_for(native, tmp_path, endpoint, images=images, model=model,
                            catalog=catalog_path)
            result = await run_probe(argv, cwd=tmp_path, env=native[1], worker=worker, model=model)
            evidence = {"probe": operation, "model": model, "images_enabled": images,
                        "protocol": result, "requests": requests,
                        "server_failures": failures, "worker_outputs": observed,
                        "builtin_canary_written": canary.exists(),
                        "native_patch_written": patch_canary.exists(),
                        "catalog": catalog_evidence}
            write_evidence(f"codex-{model}-{operation.replace('/', '-')}-images-"
                           f"{str(images).lower()}-{catalog_mode}.json", evidence)
            assert not failures, failures
            assert len(requests) == 2
            expected_tools = {"request_user_input", "contained_python"}
            if images:
                expected_tools.add("view_image")
            if model != "probe-model":
                if not restricted:
                    expected_tools.add("apply_patch")
                assert "missing model metadata" not in result["stderr_observed"].lower()
            if model == "gpt-5.6-sol" and not restricted:
                # This pinned model publishes CodeMode namespaces despite the
                # requested false flags. Preserve that distinct wire surface;
                # do not flatten it into a claim of the fallback inventory.
                assert "tools" not in requests[0]
                declarations = [item for item in requests[0]["input"]
                                if item.get("type") == "additional_tools"]
                assert len(declarations) == 1
                namespaces = {tool["name"]: tool for tool in declarations[0]["tools"]}
                assert set(namespaces) == {"functions", "collaboration"}
                functions = {tool["name"]: tool for tool in namespaces["functions"]["tools"]}
                assert set(functions) == {"exec", "wait", "request_user_input"}
                assert {tool["name"] for tool in namespaces["collaboration"]["tools"]} == {
                    "followup_task", "interrupt_agent", "list_agents", "send_message",
                    "spawn_agent", "wait_agent",
                }
                description = functions["exec"]["description"]
                assert set(re.findall(r"^### `([^`]+)`$", description, re.MULTILINE)) == (
                    expected_tools - {"request_user_input"}
                )
            else:
                assert {tool["name"] for tool in requests[0]["tools"]} == expected_tools
                assert not any(item.get("type") == "additional_tools"
                               for item in requests[0]["input"])
            outputs = [item for item in requests[1]["input"]
                       if item.get("type") in {"function_call_output", "custom_tool_call_output"}]
            assert len(outputs) == 1
            if operation == "contained_python":
                assert result["calls"] == ["call_probe"]
                assert observed == [{"contained": True}]
            else:
                assert not observed
                assert not result["calls"]
                if operation == "apply_patch" and not restricted:
                    assert patch_canary.read_text() == "fixture only\n"
                elif operation != "view_image" or not images:
                    assert outputs[0]["output"] == f"unsupported call: {operation}"
                    assert not canary.exists()
                    assert not patch_canary.exists()
                else:
                    # A PASS reproduces the negative result: this native reader
                    # bypasses the worker and exports an unmounted harness file.
                    image = outputs[0]["output"][0]
                    assert image["type"] == "input_image"
                    assert image["image_url"].startswith("data:image/png;base64,")
                    assert base64.b64decode(image["image_url"].split(",", 1)[1],
                                            validate=True) == CANARY_PNG
    finally:
        await executor.close(acquired, "discard")
        await provider.close(workspace, "discard")
    assert acquired.resource.active is None
    assert provider.closure.is_closed(acquired.resource.paths)
    assert not workspace.resource.paths.payload.exists()


@pytest.mark.parametrize("trust", ["untrusted", "trusted"])
async def test_project_extension_startup_has_a_positive_control(native, tmp_path, trust):
    """Observe one project MCP startup path, not all hooks/plugins/config sources."""
    marker = tmp_path / "extension-started"
    project_config = tmp_path / ".codex"
    project_config.mkdir()
    (tmp_path / ".git").mkdir()
    # A tiny, inert MCP peer records startup and advertises no tools. It neither
    # executes model input nor loads any external module or account state.
    peer = (
        "import json, sys; from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('started')\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    if 'id' not in request: continue\n"
        "    result = {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {}},\n"
        "              'serverInfo': {'name': 'inert-fixture', 'version': '0'}}\n"
        "    if request['method'] == 'tools/list': result = {'tools': []}\n"
        "    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}),\n"
        "          flush=True)\n"
    )
    (project_config / "config.toml").write_text(
        '[mcp_servers.fixture]\ncommand = "/usr/bin/python3"\n'
        f"args = {json.dumps(['-I', '-u', '-c', peer])}\nstartup_timeout_sec = 5\n",
    )

    async def worker(_program):
        raise AssertionError("a refused model call must not dispatch")

    async with fake_provider("exec_command", {"cmd": "true"}, model="gpt-5.5") as exchange:
        endpoint, requests, failures = exchange
        argv = argv_for(native, tmp_path, endpoint, images=False, model="gpt-5.5")
        config = Path(native[1]["CODEX_HOME"]) / "config.toml"
        config.write_text(config.read_text() +
                          f'\n[projects.{json.dumps(str(tmp_path))}]\ntrust_level = "{trust}"\n')
        result = await run_probe(argv, cwd=tmp_path, env=native[1], worker=worker, model="gpt-5.5")
        write_evidence(f"codex-project-{trust}.json", {
            "trust": trust, "extension_started": marker.exists(), "protocol": result,
            "requests": requests, "server_failures": failures,
        })
        assert not failures and len(requests) == 2
        assert not result["calls"]
        assert marker.exists() == (trust == "trusted")
        if marker.exists():
            assert marker.read_text() == "started"


@pytest.mark.parametrize("ending", ["cancel", "native-death"])
async def test_native_turn_ending_joins_an_active_contained_worker(
    native, tmp_path, provider, launcher, monkeypatch, ending,
):
    provider.posture = Posture.WRITE
    provider.launcher = launcher
    executor = RecordedExecutorProvider(launcher, provider, WORKER)
    await executor.qualify()
    workspace = await provider.acquire(context(posture=Posture.WRITE))
    acquired = await executor.acquire(context(posture=Posture.WRITE, binding="executor"))
    await workspace.materialize()
    await acquired.materialize()
    heartbeat = Path(workspace.resource.path) / "worker-live"
    program = (
        "import time\n"
        "with open('/workspace/worker-live', 'ab', buffering=0) as beat:\n"
        "    while True:\n"
        "        beat.write(b'.'); time.sleep(.02)\n"
    )
    native_processes = []
    create = asyncio.create_subprocess_exec

    async def observe_process(*argv, **kwargs):
        process = await create(*argv, **kwargs)
        if argv[0] == str(native[0]):
            native_processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", observe_process)
    calls = []

    def acquisition_state():
        return {
            "executor_closed": provider.closure.is_closed(acquired.resource.paths),
            "workspace_closed": provider.closure.is_closed(workspace.resource.paths),
            "workspace_removed": not workspace.resource.paths.payload.exists(),
        }

    async def worker(source):
        calls.append(source)
        await acquired.resource.execute(
            TaskSpec(instruction=source), workspace=workspace.resource,
            grants=acquired.resource.context.binding.effective_grants,
        )
        raise AssertionError("the active worker must be cancelled, not return an answer")

    pending = None
    try:
        async with fake_provider("contained_python", {"program": program},
                                 model="gpt-5.5") as exchange:
            endpoint, requests, failures = exchange
            argv = argv_for(native, tmp_path, endpoint, images=False, model="gpt-5.5")
            pending = asyncio.create_task(run_probe(
                argv, cwd=tmp_path, env=native[1], worker=worker, timeout=12, model="gpt-5.5",
            ))
            async with asyncio.timeout(10):
                while not heartbeat.exists():
                    await asyncio.sleep(.01)
            assert len(native_processes) == 1 and calls == [program]
            assert acquired.resource.active is not None
            if ending == "cancel":
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                native_processes[0].kill()
                # The driver is awaiting its worker: native death does not
                # interrupt that await. The existing overall deadline owns it.
                with pytest.raises(TimeoutError):
                    await pending
            assert native_processes[0].returncode is not None
            assert acquired.resource.active is None
            stopped = heartbeat.read_bytes()
            assert stopped
            await asyncio.sleep(.1)
            assert heartbeat.read_bytes() == stopped
            assert not failures and len(requests) == 1
            # The driver owns its process and joins the supplied callback. It
            # does NOT own these fixture acquisitions. Prove that distinction
            # before the test's unconditional cleanup can conceal it.
            before_cleanup = acquisition_state()
            assert not any(before_cleanup.values())
            on_driver_return = {
                "native_returncode": native_processes[0].returncode,
                "worker_joined": acquired.resource.active is None,
                "worker_heartbeat_stopped": heartbeat.read_bytes() == stopped,
                "acquisitions": before_cleanup,
            }
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await executor.close(acquired, "discard")
        await provider.close(workspace, "discard")
    assert acquired.resource.active is None
    after_cleanup = acquisition_state()
    assert all(after_cleanup.values())
    write_evidence(f"codex-lifetime-{ending}.json", {
        "ending": ending, "worker_calls": len(calls), "driver_deadline_s": 12,
        "on_driver_return": on_driver_return,
        "after_explicit_test_cleanup": after_cleanup,
    })
