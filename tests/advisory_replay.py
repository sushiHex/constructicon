"""The advisory occupant: a real model behind a public API, asked for each next call.

ADVISORY ONLY. A run through this module is never acceptance, never evidence for
a live criterion and never a qualification. It uses no vendor binary, no
subscription store, no operator window and no Constructicon authority. It
answers one question before an owner spends a live window: shown the request a
real maintenance turn sends, does a model call the tool and write the file?

Everything below the seat is the system under test, exactly as in the scripted
cases: the adapter mediates each call with its own ceilings, the worker runs the
program, capture commits the tree and the gate runs its exam. Nothing here
restates a ceiling; the adapter enforces them, and this module only asks the
model what it sends next.

RISK. The worker of the portable world is a plain subprocess of this
interpreter. A program the model writes runs UNCONTAINED on this machine with
this user's rights, and whatever it prints is sent to the configured endpoint.
The portable worker collects a program's whole output before any bound is
checked and does not reap what a program starts. Run it inside WSL2 or a
disposable virtual machine, never on a machine that holds anything you would
not hand to the model's provider. Do not run it with ``--showlocals``: a
failure would print this process's locals, the key among them.

What cannot be made identical to a live turn is listed in ``LIMITS``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from constructicon.substrate.executors.codex_protocol import (
    CONTAINED_PYTHON,
    CONTAINED_PYTHON_TOOL,
    MAX_TOOL_CALLS,
)
from tests.model_seat import Reply, Seated

NETWORK = "CONSTRUCTICON_ADVISORY_NETWORK"
ENDPOINT = "CONSTRUCTICON_ADVISORY_ENDPOINT"
API_KEY = "CONSTRUCTICON_ADVISORY_API_KEY"
REQUEST = "CONSTRUCTICON_ADVISORY_REQUEST"
MODEL = "CONSTRUCTICON_ADVISORY_MODEL"
OUTPUT = "CONSTRUCTICON_ADVISORY_OUTPUT"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
SOCKET_TIMEOUT_S = 120.0
# One request's whole elapsed time, however slowly its bytes arrive.
REQUEST_DEADLINE_S = 600.0
NAMESPACE = "functions"
INVENTORY = Path(__file__).with_name("fixtures") / "native_production_inventory.json"
# The keys the placement lane's capture carries. Another key is another request.
CAPTURE_KEYS = frozenset({
    "client_metadata", "include", "input", "model", "parallel_tool_calls", "prompt_cache_key",
    "reasoning", "store", "stream", "text", "tool_choice",
})
USAGE_KEYS = ("input_tokens", "output_tokens", "total_tokens")
_WORD = re.compile(r"[a-z][a-z0-9_.]{0,39}")

LIMITS = (
    "The request is translated: the vendor's additional_tools item becomes a public "
    "function tool without its namespace, so the model sees the name contained_python and "
    "not functions.contained_python. Item ids, client metadata, the prompt cache key and "
    "the reasoning context are dropped. The messages are sent as captured.",
    "The capture comes from the placement lane, which swaps the provider and the catalog "
    "path. Vendor-authored text under subscription authentication may differ.",
    "Authentication is an API key, not the subscription store; the endpoint may serve a "
    "different model build under the same name.",
    "The reply is read whole, not streamed, and the vendor binary's own handling of the "
    "stream, of an unknown tool and of malformed arguments is not exercised.",
    "The portable worker is not the contained one: no /workspace, no isolation, this "
    "interpreter's packages are importable, and the base holds the target and one other "
    "file, not the full tree.",
    "On Windows a text pipe hands the model CRLF line endings.",
)

Send = Callable[[dict[str, Any]], dict[str, Any]]


class AdvisoryRefused(RuntimeError):
    """A closed refusal name; the run did not start or could not continue."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def _refuse(code: str, detail: str = "") -> AdvisoryRefused:
    return AdvisoryRefused(code, detail)


def _tool() -> dict[str, Any]:
    """The adapter's declaration in the public function-tool form."""
    return {"type": "function", "name": CONTAINED_PYTHON_TOOL["name"],
            "description": CONTAINED_PYTHON_TOOL["description"],
            "parameters": CONTAINED_PYTHON_TOOL["inputSchema"]}


def _is_text_message(item: Any) -> bool:
    return (isinstance(item, dict) and set(item) <= {"id", "type", "role", "content"}
            and item.get("role") in ("developer", "user")
            and isinstance(item.get("content"), list) and bool(item["content"])
            and all(isinstance(part, dict) and set(part) == {"type", "text"}
                    and part["type"] == "input_text" and isinstance(part["text"], str)
                    for part in item["content"]))


def _is_the_one_tool(item: Any) -> bool:
    """The vendor's sealed WRITE offer as measured, carrying the adapter's declaration.

    Producer: the pinned vendor binary, which sends its tools in one
    ``additional_tools`` input item (vendor source ``core/src/client.rs:902-933``,
    cited at ``tests/native_inventory.py:64-65``). The exact offer is not assumed
    here: it is the one measured on that binary and retained in
    ``tests/fixtures/native_production_inventory.json`` (``sealed.write``; record
    ``docs/plans/handoffs/M8-N5-native-tool-inventory.md``), which the placement
    lane holds every real capture to. A capture that differs is a new vendor
    shape to measure, not one to translate by guess.
    """
    measured = json.loads(INVENTORY.read_bytes())["sealed"]["write"]
    if measured != [{"type": "namespace", "name": NAMESPACE, "description": "",
                     "tools": [{**_tool(), "strict": False}]}]:
        # The measured offer no longer carries the adapter's declaration.
        return False
    return (isinstance(item, dict) and not set(item) - {"id", "role", "type", "tools"}
            and item.get("tools") == measured)


def first_request(raw: bytes, *, instruction: str) -> dict[str, Any]:
    """The captured first request, admitted only if it is this base's maintenance turn.

    It may hold nothing but text messages and one offer of the adapter's own
    tool, and its last message must be the committed instruction and nothing
    else. A key or an item this module would drop or not understand is refused,
    so what is sent is what was captured, less the plumbing ``LIMITS`` names.
    """
    try:
        captured = json.loads(raw)
    except ValueError:
        raise _refuse("advisory-request-unreadable") from None
    if isinstance(captured, dict) and "peer" in captured:
        # The placement lane's evidence record: its one request is the capture.
        requests = (captured.get("peer") or {}).get("requests")
        if not isinstance(requests, list) or len(requests) != 1:
            raise _refuse("advisory-request-shape")
        captured, = requests
    if (not isinstance(captured, dict) or not isinstance(captured.get("input"), list)
            or not isinstance(captured.get("model"), str)):
        raise _refuse("advisory-request-shape")
    if set(captured) - CAPTURE_KEYS:
        raise _refuse("advisory-request-unknown-key")
    items = captured["input"]
    offers = [item for item in items
              if isinstance(item, dict) and item.get("type") == "additional_tools"]
    messages = [item for item in items
                if isinstance(item, dict) and item.get("type") == "message"]
    if len(offers) + len(messages) != len(items) or not all(map(_is_text_message, messages)):
        raise _refuse("advisory-request-item")
    if len(offers) != 1 or not _is_the_one_tool(offers[0]):
        raise _refuse("advisory-request-tool-differs")
    last = messages[-1] if messages else {}
    if last.get("role") != "user" or last.get("content") != [
            {"type": "input_text", "text": instruction}]:
        raise _refuse("advisory-request-instruction-differs")
    return captured


def public_body(captured: Mapping[str, Any], *, model: str | None = None) -> dict[str, Any]:
    """An admitted capture as a public Responses-style body. ``LIMITS`` names the changes."""
    body: dict[str, Any] = {
        "model": model or captured["model"],
        "input": [{"type": "message", "role": item["role"], "content": item["content"]}
                  for item in captured["input"] if item.get("type") == "message"],
        "tools": [_tool()],
        "tool_choice": captured.get("tool_choice", "auto"),
        "parallel_tool_calls": False,
        "store": False,
        "stream": False,
    }
    effort = (captured.get("reasoning") or {}).get("effort")
    if effort is not None:
        body["reasoning"] = {"effort": effort}
    for key in ("text", "include"):
        if key in captured:
            body[key] = captured[key]
    return body


def _word(value: Any) -> str | None:
    """A short identifier as the producer spelled it, or None; never free text."""
    return value if isinstance(value, str) and _WORD.fullmatch(value) else None


def _shape(response: Any) -> dict[str, Any]:
    """What a response looked like, in field names and closed words only."""
    if not isinstance(response, dict):
        return {"type": type(response).__name__}
    output = response.get("output")
    return {
        "keys": sorted(key for key in response if _word(key))[:32],
        "status": _word(response.get("status")),
        "error": response.get("error") is not None,
        "output": [_word(item.get("type")) if isinstance(item, dict) else None
                   for item in output][:32] if isinstance(output, list) else None,
    }


class Conversation:
    """One advisory turn with the endpoint; every later request extends the first."""

    def __init__(self, body: dict[str, Any], send: Send, *,
                 deadline_s: float = REQUEST_DEADLINE_S) -> None:
        self.body, self.send, self.deadline_s = body, send, deadline_s
        self.items: list[Any] = []
        self.awaiting: str | None = None
        self.requests = 0
        self.usage: list[dict[str, int]] = []
        # A closed name when the turn was ended here and not by the model.
        self.refusal: str | None = None
        # Once closed, nothing an outstanding request returns is used.
        self.closed = False
        # The last response's field names, status and item types; never its text.
        self.shape: dict[str, Any] | None = None

    def step(self, seen: tuple[str, ...]) -> str | Reply:
        try:
            return self._step(seen)
        except AdvisoryRefused as refused:
            self.refusal = str(refused)  # The closed name, and an HTTP status if it has one.
        except Exception as error:  # A transport or decoding fault; its text may be private.
            self.refusal = f"advisory-transport-failed ({type(error).__name__})"
        return Reply(None)

    def _ask(self, body: dict[str, Any]) -> Any:
        """One request under one elapsed deadline; an answer after it is never read."""
        answer: list[Any] = []

        def work() -> None:
            try:
                answer.append((True, self.send(body)))
            except BaseException as error:
                answer.append((False, error))

        worker = threading.Thread(target=work, name="advisory-request", daemon=True)
        worker.start()
        worker.join(self.deadline_s)
        if not answer:
            raise _refuse("advisory-request-deadline")
        succeeded, value = answer[0]
        if not succeeded:
            raise value
        return value

    def _step(self, seen: tuple[str, ...]) -> str | Reply:
        if self.closed:
            raise _refuse("advisory-answer-after-the-run-ended")
        if self.awaiting is not None:
            self.items.append({"type": "function_call_output", "call_id": self.awaiting,
                               "output": seen[-1]})
            self.awaiting = None
        self.requests += 1
        response = self._ask({**self.body, "input": [*self.body["input"], *self.items]})
        if self.closed:
            raise _refuse("advisory-answer-after-the-run-ended")
        # Producer: whatever endpoint the operator names. None is pinned and none
        # was ever called from here, so every check from here to the end of this
        # method is an ASSUMPTION about a public Responses-style reply (a
        # ``status`` of "completed", a null ``error``, an ``output`` list whose
        # ``function_call`` items carry ``name``, ``arguments`` and ``call_id``
        # and whose ``message`` items carry ``output_text`` parts), not a fact
        # verified at a producer. They fail closed: a wrong assumption costs a refused advisory
        # run with a name, never a result. ``shape`` keeps what the producer
        # really sent, as field names only, so the assumption can be corrected
        # against its bytes instead of loosened by guess.
        self.shape = _shape(response)
        if not isinstance(response, dict) or response.get("error") is not None:
            raise _refuse("advisory-response-error")
        if response.get("status") != "completed":
            raise _refuse("advisory-response-incomplete")
        output = response.get("output")
        if not isinstance(output, list) or not all(isinstance(item, dict) for item in output):
            raise _refuse("advisory-response-shape")
        usage = response.get("usage")
        self.usage.append({key: usage[key] for key in USAGE_KEYS
                           if isinstance(usage, dict) and type(usage.get(key)) is int})
        self.items.extend(output)
        calls = [item for item in output if item.get("type") == "function_call"]
        if not calls:
            said = [part.get("text") for item in output if item.get("type") == "message"
                    for part in item.get("content") or []
                    if isinstance(part, dict) and part.get("type") == "output_text"
                    and isinstance(part.get("text"), str)]
            return Reply("".join(said) if said else None)
        if len(calls) != 1:
            raise _refuse("advisory-parallel-tool-calls")
        call, = calls
        if call.get("name") != CONTAINED_PYTHON:
            raise _refuse("advisory-unknown-tool")
        try:
            arguments = json.loads(call.get("arguments"))
        except (TypeError, ValueError):
            arguments = None
        if (not isinstance(arguments, dict) or set(arguments) != {"program"}
                or not isinstance(arguments["program"], str)
                or not isinstance(call.get("call_id"), str)):
            raise _refuse("advisory-tool-arguments")
        self.awaiting = call["call_id"]
        return arguments["program"]


class Advised(Seated):
    """The seat with the advisory occupant.

    The first request is made as the seat is built, before any run exists. Each
    later one is made off the event loop, so the run's own heartbeat keeps its
    lease while the endpoint thinks; the answer is delivered back on the loop,
    and only while the adapter still holds the peer open.
    """

    def __init__(self, conversation: Conversation) -> None:
        self.conversation = conversation
        self.asking: threading.Thread | None = None
        # One more step than the adapter admits: a ninth call is sent, and refused there.
        super().__init__("advisory", [conversation.step] * (MAX_TOOL_CALLS + 1), reply=None)

    def _continue(self, index: int) -> None:
        loop = asyncio.get_running_loop()

        def ask() -> None:
            program = self._program(index + 1)
            try:
                loop.call_soon_threadsafe(self._deliver, index, program)
            except RuntimeError:  # The loop itself is gone.
                self.conversation.refusal = "advisory-answer-after-the-run-ended"

        self.asking = threading.Thread(target=ask, name="advisory-model", daemon=True)
        self.asking.start()

    def _deliver(self, index: int, program: str | None) -> None:
        if self.conversation.closed or self.stdin_closed or self.eof:
            # The adapter ended the turn (a deadline, a refusal) while the endpoint
            # was thinking. Nothing more is emitted, so the record stays what ran.
            self.conversation.refusal = "advisory-answer-after-the-run-ended"
            return
        self._send(index, program)

    def close(self) -> None:
        """Freeze the record: nothing an outstanding request returns is used after this."""
        self.conversation.closed = True


def advisory(captured: Mapping[str, Any], send: Send, *, model: str | None = None,
             deadline_s: float = REQUEST_DEADLINE_S) -> Advised:
    return Advised(Conversation(public_body(captured, model=model), send, deadline_s=deadline_s))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the key to another place; it is refused, never followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise _refuse("advisory-endpoint-redirected", f"HTTP {code}")


def _open(request: urllib.request.Request, timeout: float):
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


def network_transport(environ: Mapping[str, str]) -> Send:
    """The only path to the network: explicit, https, keyed from the environment."""
    if environ.get(NETWORK) != "1":
        raise _refuse("advisory-network-off", f"set {NETWORK}=1 to send the request")
    endpoint, key = environ.get(ENDPOINT, ""), environ.get(API_KEY, "")
    if not key:
        raise _refuse("advisory-no-key", f"set {API_KEY}")
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        usable = parsed.scheme == "https" and bool(parsed.hostname)
    except ValueError:
        usable = False
    if not usable:
        raise _refuse("advisory-endpoint-not-https", f"set {ENDPOINT} to an https URL")

    def send(body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            endpoint, data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with _open(request, SOCKET_TIMEOUT_S) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            # The status alone: a response body may echo the request.
            raise _refuse("advisory-endpoint-refused", f"HTTP {error.code}") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise _refuse("advisory-response-too-large")
        return json.loads(raw)

    return send


def commitment(text: str) -> dict[str, object]:
    """What may be posted about a private record: its digest and length."""
    raw = text.encode()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
