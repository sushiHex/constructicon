"""One scripted Responses peer for TCP baseline and Unix placement tests.

It observes invocation bytes, never authenticates their process of origin.
All limits apply at this endpoint even if a caller bypasses the byte bridge.
"""

import asyncio
import json
import socket
from contextlib import asynccontextmanager, suppress

from constructicon.core.identity import parse_json_value
from constructicon.substrate._lifetime import finish_owned
from tests.native_codex_probe import PROBE_PROMPT
from tests.substrate._provider_transport import (
    BODY,
    CASE_SECONDS,
    HANDLER_SECONDS,
    HEADERS,
    Budget,
    read,
    write,
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


async def request_from(sock, budget):
    data = bytearray()
    while b"\r\n\r\n" not in data:
        raw = await read(sock, budget, HEADERS + 1 - len(data))
        if not raw:
            raise ValueError("incomplete headers")
        data.extend(raw)
        end = data.find(b"\r\n\r\n")
        if (end + 4 if end >= 0 else len(data)) > HEADERS:
            raise ValueError("header bound")
    header, body = bytes(data).split(b"\r\n\r\n", 1)
    lines = header.decode("ascii").split("\r\n")
    if lines[0] != "POST /v1/responses HTTP/1.1":
        raise ValueError("unexpected request target")
    fields = {}
    for line in lines[1:]:
        name, value = line.split(":", 1)
        name = name.lower()
        if not name or name.strip() != name or name in fields:
            raise ValueError("ambiguous header")
        fields[name] = value.strip()
    if {"authorization", "proxy-authorization", "transfer-encoding"} & fields.keys():
        raise ValueError("authentication or transfer encoding refused")
    length = fields["content-length"]
    if not length or any(character not in "0123456789" for character in length):
        raise ValueError("malformed content length")
    size = int(length)
    if not 0 < size <= BODY:
        raise ValueError("body bound")
    data = bytearray(body)
    while len(data) < size:
        raw = await read(sock, budget, size - len(data))
        if not raw:
            raise ValueError("incomplete body")
        data.extend(raw)
    if len(data) != size:
        raise ValueError("trailing request bytes")
    request = parse_json_value(data.decode())
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    return request


def response_for(tool, arguments, model, namespace, ordinal):
    if tool is not None and ordinal == 1:
        item = {"id": "fc_probe", "call_id": "call_probe", "name": tool}
        if namespace is not None:
            item["namespace"] = namespace
        if tool in {"apply_patch", "exec"}:
            source = arguments["patch" if tool == "apply_patch" else "code"]
            items = [{**item, "type": "custom_tool_call", "input": source}]
        else:
            items = [{**item, "type": "function_call", "arguments": json.dumps(arguments)}]
    else:
        items = [{"id": "msg_probe", "type": "message", "role": "assistant",
                  "status": "completed", "content": [
                      {"type": "output_text", "text": "fixture complete"}]}]
    payload = b"".join(
        ("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode()
        for event in events(items, model=model)
    )
    return (b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n"
            + f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)


class Peer:
    def __init__(self, listener, deadline, tool, arguments, model, namespace, scenario):
        self.listener, self.deadline = listener, deadline
        self.tool, self.arguments, self.model, self.namespace = tool, arguments, model, namespace
        self.budget = Budget()
        self.requests, self.failures = [], []
        self.handlers, self.active = set(), set()
        self.stopped = asyncio.Event()
        self.acceptor = None
        self.scenario = scenario

    def check_scenario(self, request):
        # The controlled user turn is a scenario assertion, not process identity
        # or proof of upstream instructions. Startup-origin qualification is separate.
        inputs = request.get("input", [])
        if not isinstance(inputs, list):
            raise ValueError("unexpected scenario input")
        users = [item for item in inputs if isinstance(item, dict) and item.get("role") == "user"]
        if self.scenario is None:
            if inputs:
                raise ValueError("unexpected scenario input")
        elif not users or users[-1].get("content") != [
            {"type": "input_text", "text": self.scenario},
        ]:
            raise ValueError("unexpected scenario prompt")

    def stop(self):
        self.stopped.set()
        if self.acceptor is not None and self.acceptor is not asyncio.current_task():
            self.acceptor.cancel()
        self.listener.close()
        for sock in self.active:
            # Wake reads without invalidating their registered descriptor.
            with suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    async def respond(self, sock):
        try:
            async with asyncio.timeout_at(min(
                self.deadline, asyncio.get_running_loop().time() + HANDLER_SECONDS,
            )):
                request = await request_from(sock, self.budget)
                self.requests.append(request)
                if request.get("model") != self.model:
                    raise ValueError("unexpected model")
                self.check_scenario(request)
                await write(sock, self.budget, response_for(
                    self.tool, self.arguments, self.model, self.namespace, len(self.requests),
                ))
                sock.shutdown(socket.SHUT_WR)
                if await read(sock, self.budget):
                    raise ValueError("trailing request bytes")
        except Exception as exc:
            self.failures.append(repr(exc))
            self.stop()
        except asyncio.CancelledError:
            self.failures.append("incomplete handler at teardown")
            raise
        finally:
            self.active.remove(sock)
            sock.close()

    async def serve(self):
        try:
            async with asyncio.timeout_at(self.deadline):
                while not self.stopped.is_set():
                    sock, _ = await asyncio.get_running_loop().sock_accept(self.listener)
                    sock.setblocking(False)
                    try:
                        self.budget.admit()  # Incomplete connections spend admission too.
                        if self.active:
                            raise ValueError("concurrent connection")
                    except ValueError:
                        sock.close()
                        raise
                    self.active.add(sock)
                    task = asyncio.create_task(self.respond(sock))
                    self.handlers.add(task)
        except TimeoutError:
            if self.active:
                self.failures.append("peer deadline with active connection")
            self.stop()
        except Exception as exc:
            if not self.stopped.is_set():
                self.failures.append(repr(exc))
                self.stop()


@asynccontextmanager
async def provider_peer(tool=None, arguments=None, *, model="probe-model", namespace=None,
                        path=None, deadline=None, scenario=None):
    if deadline is None:
        deadline = asyncio.get_running_loop().time() + CASE_SECONDS
    listener = socket.socket(socket.AF_UNIX if path is not None else socket.AF_INET)
    listener.setblocking(False)
    bound = None
    peer = None
    try:
        listener.bind(str(path) if path is not None else ("127.0.0.1", 0))
        if path is not None:
            observed = path.lstat()
            bound = (observed.st_dev, observed.st_ino)
        listener.listen(2)
        peer = Peer(listener, deadline, tool, arguments, model, namespace, scenario)
        task = asyncio.create_task(peer.serve())
        peer.acceptor = task
        try:
            yield peer
        finally:
            async def join():
                peer.stop()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                # Drain already-completing handlers; a live partial request is an error.
                await asyncio.sleep(0)
                for handler in peer.handlers:
                    if not handler.done():
                        handler.cancel()
                await asyncio.gather(*peer.handlers, return_exceptions=True)

            await finish_owned(asyncio.create_task(join()))
    finally:
        listener.close()
        if path is not None and bound is not None:
            try:
                observed = path.lstat()
            except FileNotFoundError:
                if peer is not None:
                    peer.failures.append("endpoint removed before teardown")
            else:
                if (observed.st_dev, observed.st_ino) == bound:
                    path.unlink()
                elif peer is not None:
                    peer.failures.append("endpoint replaced before teardown")


@asynccontextmanager
async def fake_provider(tool, arguments, *, model="probe-model", namespace=None):
    async with provider_peer(tool, arguments, model=model, namespace=namespace,
                             scenario=PROBE_PROMPT) as peer:
        port = peer.listener.getsockname()[1]
        yield f"http://127.0.0.1:{port}/v1", peer.requests, peer.failures
