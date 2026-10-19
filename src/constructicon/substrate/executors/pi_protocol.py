"""Finite source-shaped Pi READ codec, exercised only by scripted peers.

No vendor availability, authentication or startup authority is proved here.
The owned byte transport and task adapter remain separate from this decoder.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from constructicon.core.executor import (
    ExecutorError,
    ExecutorFailure,
    ExecutorOutcome,
    ExecutorPartial,
    ExecutorSuccess,
    TransportDamage,
    Usage,
)
from constructicon.core.identity import canonical_json, parse_json_value
from constructicon.substrate.executors.linux import ProcessResult

RECORD_BYTES = 65536
STDOUT_BYTES = 1048576
RECORD_COUNT = 128
JSON_DEPTH = 32
REPLY_BYTES = 16384
OUTCOME_BYTES = 65536
MAX_INTEGER = 2**63 - 1


def encoded(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def same(left: Any, right: Any) -> bool:
    return encoded(left) == encoded(right)


def text_blocks(value: Any) -> None:
    """The small fixture reads text only; image/native semantics remain unqualified."""
    if type(value) is not list or any(
        type(block) is not dict or block.get("type") != "text"
        or type(block.get("text")) is not str for block in value
    ):
        raise ValueError("unsupported READ content")


def tool_call(value: Any) -> None:
    if (type(value) is not dict or value.get("type") != "toolCall"
            or type(value.get("id")) is not str or not value["id"]
            or len(encoded(value["id"])) > 256 or value.get("name") != "read"
            or type(value.get("arguments")) is not dict):
        raise ValueError("unsupported READ declaration")


def assistant_update(update: Any) -> None:
    if type(update) is not dict:
        raise ValueError("assistant update is not an object")
    kind = update.get("type")
    indexed = ("text_start", "text_delta", "text_end", "thinking_start", "thinking_delta",
               "thinking_end", "toolcall_start", "toolcall_delta", "toolcall_end")
    if kind not in (*indexed, "start", "done", "error"):
        raise ValueError("unsupported assistant update")
    if kind in indexed and (
        type(update.get("contentIndex")) is not int
        or not 0 <= update["contentIndex"] <= MAX_INTEGER
    ):
        raise ValueError("invalid assistant block index")
    if kind in ("text_delta", "thinking_delta", "toolcall_delta"):
        if type(update.get("delta")) is not str:
            raise ValueError("invalid assistant delta")
    elif kind in ("text_end", "thinking_end"):
        if type(update.get("content")) is not str:
            raise ValueError("invalid assistant block completion")
    elif kind == "toolcall_start":
        if (type(update.get("id")) is not str or not update["id"]
                or len(encoded(update["id"])) > 256 or update.get("toolName") != "read"):
            raise ValueError("unsupported tool update")
    elif kind == "toolcall_end":
        tool_call(update.get("toolCall"))
    elif kind in ("done", "error"):
        message = update.get("message" if kind == "done" else "error")
        if (update.get("reason") not in ("stop", "length", "toolUse", "error", "aborted")
                or type(message) is not dict or message.get("role") != "assistant"
                or type(message.get("content")) is not list):
            raise ValueError("invalid provider completion update")


def bounded(value: str, limit: int) -> str:
    """Bound the encoded JSON string, including quotes and escaping."""
    if len(encoded(value)) <= limit:
        return value
    left, right = 0, len(value)
    while left < right:
        middle = (left + right + 1) // 2
        if len(encoded(value[:middle])) <= limit:
            left = middle
        else:
            right = middle - 1
    return value[:left]


def parse_record(raw: bytes) -> dict[str, Any]:
    """Check depth before recursive JSON parsing; shared parsing rejects ambiguity."""
    depth = 0
    quoted = escaped = False
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > JSON_DEPTH:
                raise ValueError("JSON depth exceeded")
        elif byte in (93, 125):
            depth -= 1
    value = parse_json_value(raw.decode("utf-8", errors="strict"))
    if type(value) is not dict:
        raise ValueError("record is not an object")
    return value


@dataclass
class ReadCall:
    arguments: dict[str, Any]
    started: bool = False
    ended: bool = False
    content: Any = None
    result: dict[str, Any] | None = None


class PiDecoder:
    """One fresh get_state and one prompt, with irreversible damage/refusal."""

    def __init__(self, instruction: str) -> None:
        self.instruction = instruction
        self.buffer = bytearray()
        self.total = self.count = 0
        self.generation = self.frame_generation = 0
        self.expected: tuple[str, str, int] | None = None
        self.state_observed = self.accepted = self.eof = False
        self.started = self.ended = self.settled = self.turn = False
        self.active_role: str | None = None
        self.messages: list[dict[str, Any]] = []
        self.turn_assistant: dict[str, Any] | None = None
        self.provider_completion: dict[str, Any] | None = None
        self.turn_results: list[dict[str, Any]] = []
        self.calls: dict[str, ReadCall] = {}
        self.final: str | None = None
        self.usage_complete = self.models_complete = True
        self.input_tokens = self.output_tokens = 0
        self.models: set[str] = set()
        self.damage_count = 0
        self.error: str | None = None
        self.excerpt: str | None = None
        self.refused = False

    def damage(self, detail: str, raw: bytes = b"") -> None:
        self.damage_count = min(RECORD_COUNT + 1, self.damage_count + 1)
        if self.error is None:
            self.error = bounded(detail, 256)
            self.excerpt = bounded(raw[:1024].decode("utf-8", errors="replace"), 1024)

    def request(self, command: str, identifier: str) -> None:
        if self.expected is not None or self.buffer or self.eof:
            self.damage("request crossed buffered or closed input")
        self.generation += 1
        self.expected = command, identifier, self.generation

    @property
    def stopped(self) -> bool:
        return bool(self.damage_count or self.refused or self.eof)

    def feed(self, chunk: bytes) -> None:
        self.total += len(chunk)
        if self.total > STDOUT_BYTES:
            self.damage("stdout byte limit exceeded")
            return
        while chunk:
            if not self.buffer:
                self.frame_generation = self.generation
            newline = chunk.find(b"\n")
            amount = len(chunk) if newline < 0 else newline + 1
            if len(self.buffer) + amount > RECORD_BYTES:
                self.damage("record byte limit exceeded")
                self.buffer.clear()
                return
            self.buffer.extend(chunk[:amount])
            chunk = chunk[amount:]
            if newline < 0:
                return
            raw = bytes(self.buffer)
            self.buffer.clear()
            self.count += 1
            if self.count > RECORD_COUNT:
                self.damage("record count exceeded")
                return
            try:
                self.observe(parse_record(raw), self.frame_generation)
            except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
                self.damage("malformed or incoherent Pi record", raw)

    def finish(self) -> None:
        self.eof = True
        if self.buffer:
            self.damage("unterminated record", bytes(self.buffer))
            self.buffer.clear()

    def observe(self, record: dict[str, Any], generation: int) -> None:
        if self.damage_count or self.refused:
            return
        kind = record.get("type")
        if kind == "response":
            if self.expected is None:
                raise ValueError("unsolicited response")
            command, identifier, expected_generation = self.expected
            if (record.get("id") != identifier or record.get("command") != command
                    or generation != expected_generation):
                raise ValueError("response does not match fresh request")
            self.expected = None
            if record.get("success") is not True:
                self.refused = True
                return
            data = record.get("data")
            if type(data) is not dict:
                raise ValueError("missing response data")
            if command == "get_state":
                required = {"thinkingLevel": "off", "isStreaming": False,
                            "isCompacting": False, "autoCompactionEnabled": False,
                            "messageCount": 0, "pendingMessageCount": 0}
                if (any(type(data.get(key)) is not type(value) or data[key] != value
                        for key, value in required.items())
                        or data.get("model", {}).get("provider") != "fixture"
                        or data.get("model", {}).get("id") != "pi-read"):
                    self.refused = True
                    return
                self.state_observed = True
            elif command == "prompt":
                self.accepted = data.get("disposition") == "started"
                self.refused = not self.accepted
            return
        if not self.state_observed or self.generation != 2 or self.settled:
            raise ValueError("event outside sole dispatch")
        if kind == "agent_start":
            if self.started:
                raise ValueError("duplicate agent")
            self.started = True
        elif kind == "turn_start":
            if not self.started or self.turn or self.ended or self.final is not None:
                raise ValueError("unexpected turn")
            self.turn = True
            self.turn_assistant = None
            self.turn_results = []
        elif kind in ("message_start", "message_end"):
            message = record["message"]
            role = message["role"]
            if not self.turn or role not in ("user", "assistant", "toolResult"):
                raise ValueError("unsupported message")
            if kind == "message_start":
                if self.active_role is not None:
                    raise ValueError("overlapping message")
                self.active_role = role
            else:
                if self.active_role != role:
                    raise ValueError("message was not started")
                self.active_role = None
                self.message_end(message)
                self.messages.append(message)
        elif kind == "message_update":
            update = record["assistantMessageEvent"]
            assistant_update(update)
            if self.active_role != "assistant":
                raise ValueError("unsupported assistant update")
            if update["type"] == "error":
                self.refused = True
            elif update["type"] == "done":
                if (self.provider_completion is not None
                        or update["message"].get("stopReason") != update["reason"]):
                    raise ValueError("contradictory provider completion")
                self.provider_completion = update["message"]
                if update["reason"] not in ("stop", "toolUse"):
                    self.refused = True
        elif kind in ("tool_execution_start", "tool_execution_update", "tool_execution_end"):
            identifier = record["toolCallId"]
            call = self.calls[identifier]
            if record["toolName"] != "read" or not self.turn:
                raise ValueError("unsupported tool")
            if kind == "tool_execution_start":
                if call.started or not same(record.get("args"), call.arguments):
                    raise ValueError("duplicate or changed read")
                call.started = True
            elif not call.started or call.ended:
                raise ValueError("read lifecycle mismatch")
            elif kind == "tool_execution_update":
                if not same(record.get("args"), call.arguments):
                    raise ValueError("read arguments changed")
                text_blocks(record["partialResult"]["content"])
            else:
                if record.get("isError") is not False:
                    self.refused = True
                call.ended = True
                call.content = record["result"]["content"]
                text_blocks(call.content)
        elif kind == "turn_end":
            if (not self.turn or self.active_role is not None or self.turn_assistant is None
                    or not same(record.get("message"), self.turn_assistant)
                    or not same(record.get("toolResults"), self.turn_results)
                    or any(call.result is None for call in self.calls.values())):
                raise ValueError("incomplete or contradictory turn copy")
            self.turn = False
        elif kind == "agent_end":
            if (not self.started or self.ended or self.turn or self.final is None
                    or not same(record.get("messages"), self.messages)
                    or record.get("willRetry") is not False):
                raise ValueError("incomplete or contradictory agent copy")
            self.ended = True
        elif kind == "agent_settled":
            if not self.ended or record.get("aborted") is not False:
                self.refused = True
            self.settled = True
        else:
            raise ValueError("unsupported Pi event")

    def message_end(self, message: dict[str, Any]) -> None:
        role = message["role"]
        if role == "user":
            if self.messages or message.get("content") != self.instruction:
                raise ValueError("unexpected user message")
            return
        if role == "toolResult":
            text_blocks(message.get("content"))
            call = self.calls[message["toolCallId"]]
            if (not call.ended or call.result is not None or message.get("toolName") != "read"
                    or message.get("isError") is not False
                    or not same(message.get("content"), call.content)):
                raise ValueError("unmatched or failed read result")
            call.result = message
            self.turn_results.append(message)
            return
        if not self.messages or self.turn_assistant is not None or self.final is not None:
            raise ValueError("unexpected assistant response")
        if self.provider_completion is not None:
            if not same(self.provider_completion, message):
                raise ValueError("provider completion differs from message completion")
            self.provider_completion = None
        blocks = message["content"]
        if type(blocks) is not list:
            raise ValueError("assistant content is not a list")
        reason = message.get("stopReason")
        text: list[str] = []
        tools = 0
        for block in blocks:
            if block.get("type") == "text" and type(block.get("text")) is str:
                text.append(block["text"])
            elif block.get("type") == "thinking" and type(block.get("thinking")) is str:
                pass
            elif block.get("type") == "toolCall" and reason == "toolUse":
                tool_call(block)
                identifier = block.get("id")
                if (type(identifier) is not str or not identifier or identifier in self.calls
                        or len(encoded(identifier)) > 256 or block.get("name") != "read"
                        or type(block.get("arguments")) is not dict):
                    raise ValueError("unsupported read declaration")
                self.calls[identifier] = ReadCall(block["arguments"])
                tools += 1
            else:
                raise ValueError("unsupported content block")
        if reason == "stop":
            if (not text or not self.calls
                    or any(call.result is None for call in self.calls.values())):
                raise ValueError("final analysis lacks completed read")
            reply = "".join(text)
            if not reply.strip():
                raise ValueError("final analysis has no nonblank text")
            self.final = bounded(reply, REPLY_BYTES)
            if self.final != reply:
                self.damage("analysis publication limit exceeded")
        elif reason != "toolUse" or not tools:
            self.refused = True
        self.turn_assistant = message
        usage = message.get("usage")
        if type(usage) is not dict or any(
            type(usage.get(key)) is not int or not 0 <= usage[key] <= MAX_INTEGER
            for key in ("input", "output", "cacheRead", "cacheWrite", "totalTokens")
        ) or usage["totalTokens"] != sum(
            usage[key] for key in ("input", "output", "cacheRead", "cacheWrite")
        ):
            self.usage_complete = False
        else:
            self.input_tokens += usage["input"]
            self.output_tokens += usage["output"]
            if max(self.input_tokens, self.output_tokens) > MAX_INTEGER:
                self.usage_complete = False
        model = message.get("responseModel")
        if type(model) is str and model.strip() and len(encoded(model)) <= 256:
            self.models.add(model)
        else:
            self.models_complete = False

    def outcome(self, result: ProcessResult) -> ExecutorOutcome:
        observation: dict[str, Any] = {
            "output": self.final, "raw_reply": self.final, "requested_model": "fixture/pi-read",
            "served_model": next(iter(self.models)) if (
                self.models_complete and len(self.models) == 1
            ) else None,
            "usage": Usage(input_tokens=self.input_tokens, output_tokens=self.output_tokens)
            if self.usage_complete and self.final is not None else None,
            "elapsed_s": result.elapsed_s if (
                math.isfinite(result.elapsed_s) and result.elapsed_s >= 0
            ) else 0,
        }
        if result.timed_out:
            outcome: ExecutorOutcome = ExecutorFailure(**observation, error=ExecutorError(
                kind="timeout", detail="Pi fixture deadline expired",
                produced_output=self.final is not None,
            ))
        elif self.damage_count:
            outcome = ExecutorPartial(**observation, damage=TransportDamage(
                malformed_records=self.damage_count, first_error=self.error,
                evidence_excerpt=self.excerpt,
            ))
        elif (self.refused or not self.accepted or not self.eof or not self.settled
              or self.final is None or type(result.returncode) is not int or result.returncode != 0
              or type(result.payload_returncode) is not int or result.payload_returncode != 0
              or result.timed_out is not False
              or result.bound_exceeded is not None or type(result.stderr) is not bytes
              or result.stderr):
            outcome = ExecutorFailure(**observation, error=ExecutorError(
                kind="exit", detail="Pi fixture did not complete cleanly",
                produced_output=self.final is not None,
            ))
        else:
            outcome = ExecutorSuccess(**observation)
        if not publication_fits(outcome):
            return ExecutorFailure(error=ExecutorError(
                kind="exit", detail="Pi outcome publication refused",
            ))
        return outcome


def publication_fits(outcome: ExecutorOutcome) -> bool:
    """Walk every published field, so additions inherit the conservative ceiling."""
    value = outcome.model_dump(mode="json")
    if len(encoded(value)) > OUTCOME_BYTES:
        return False
    pending: list[tuple[tuple[str, ...], Any]] = [((), value)]
    while pending:
        path, item = pending.pop()
        if type(item) is dict:
            pending.extend(((*path, key), child) for key, child in item.items())
        elif type(item) is list:
            pending.extend((path, child) for child in item)
        elif type(item) is str:
            limit = REPLY_BYTES if path in (("output",), ("raw_reply",)) else (
                1024 if path == ("damage", "evidence_excerpt") else 256
            )
            if len(encoded(item)) > limit:
                return False
        elif type(item) is int and not 0 <= item <= MAX_INTEGER:
            return False
    return True
