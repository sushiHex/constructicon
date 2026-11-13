"""The model's seat: the one place a test chooses who answers the writer's turn.

Below the seat everything is the system under test: the adapter mediating each
callback, the worker, capture and the gate. The seat itself is the scripted
native peer, and an occupant is only where its programs come from.

- ``ideal``: the one program a rehearsal knows is right.
- ``hostile``: what a model plausibly sends instead. A step may be a function of
  the outputs seen so far, as a model's next call is.
- ``replay``: a recorded ``Turn``. Each output is compared with the record before
  the next program is sent; a divergence ends the turn, and ``settle`` raises.
- ``live``: a real model behind the vendor binary. It sits only on the private
  host inside an owner-approved window, so it is named here and never seated.

No occupant here is a vendor binary or a model. ``Realness`` says what stood in
every other place of a world, and tests assert it whole.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from tests.substrate.test_codex_protocol import completed
from tests.substrate.test_codex_write import WriteNative

Occupant = Literal["ideal", "hostile", "replay", "live"]
Step = str | Callable[[tuple[str, ...]], str]
RECORD_VERSION = 1


class ReplayDiverged(AssertionError):
    """The system no longer does what the recorded turn saw it do."""


@dataclass(frozen=True)
class Seen:
    """One callback output as the model saw it: a digest and a length, never text."""

    sha256: str
    bytes: int

    @classmethod
    def of(cls, text: str) -> Seen:
        raw = text.encode()
        return cls(hashlib.sha256(raw).hexdigest(), len(raw))


@dataclass(frozen=True)
class Call:
    """One program the model sent; ``seen`` is None when no output came back."""

    program: str
    seen: Seen | None


@dataclass(frozen=True)
class Turn:
    """One recorded turn: its calls in order, whether it completed, and its last message.

    Only the last call may lack an output: a model cannot send another call until
    the previous one answers. ``reply`` is the completion's message; a turn may
    complete without one, and a turn that never completed has none.
    """

    calls: tuple[Call, ...]
    completed: bool
    reply: str | None

    def __post_init__(self) -> None:
        if any(call.seen is None for call in self.calls[:-1]):
            raise ValueError("only a turn's last call may lack an output")
        if self.reply is not None and not self.completed:
            raise ValueError("a turn that never completed has no reply")

    def to_json(self) -> str:
        return json.dumps({
            "version": RECORD_VERSION, "completed": self.completed, "reply": self.reply,
            "calls": [{"program": call.program,
                       "seen": None if call.seen is None else vars(call.seen)}
                      for call in self.calls],
        }, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> Turn:
        record = json.loads(raw)
        if set(record) != {"version", "calls", "completed", "reply"}:
            raise ValueError(f"a turn record has exactly four keys, not {sorted(record)}")
        if record["version"] != RECORD_VERSION or type(record["completed"]) is not bool:
            raise ValueError("an unknown turn record version or completion")
        calls = []
        for item in record["calls"]:
            if set(item) != {"program", "seen"}:
                raise ValueError(f"a recorded call has exactly two keys, not {sorted(item)}")
            calls.append(Call(item["program"],
                              None if item["seen"] is None else Seen(**item["seen"])))
        return cls(tuple(calls), record["completed"], record["reply"])


@dataclass(frozen=True)
class Realness:
    """What stood in each place of one scripted world; the classes themselves."""

    model: Occupant
    worker: type  # The class that launched the worker, capture and gate.
    contained: bool  # Whether that class is the provisioned Linux boundary.
    store_world: type  # The world under the real operator store (its syscalls).
    identity: str  # "fixture": the launch identity is minted from test digests.


class Seated(WriteNative):
    """The scripted peer with a named occupant; the next step waits for each output."""

    def __init__(self, occupant: Occupant, steps: Sequence[Step], *,
                 reply: str | None = "done", expected: Turn | None = None) -> None:
        self.occupant, self.steps, self.reply = occupant, list(steps), reply
        self.expected = expected
        self.seen: list[str] = []
        self.divergence: str | None = None
        super().__init__(self._program(0) if self.steps else "never sent")
        if not self.steps:
            self.callbacks.clear()
            self.records[:] = [completed(answer=reply)]

    def _program(self, index: int) -> str:
        step = self.steps[index]
        return step if isinstance(step, str) else step(tuple(self.seen))

    def _respond(self, raw: bytes) -> None:
        request = json.loads(raw)
        index = self.callback_index
        if (index >= len(self.callbacks) or request.get("method") is not None
                or request.get("id") != self.callbacks[index]["id"]):
            super()._respond(raw)
            return
        self.received.append(request)
        self.callback_responses.append(request)
        item, = request["result"]["contentItems"]
        self.seen.append(item["text"])
        self.callback_index += 1
        recorded = None if self.expected is None else self.expected.calls[index].seen
        if self.expected is not None and Seen.of(item["text"]) != recorded:
            # Closed loop: nothing recorded after a divergence is ever sent.
            self.divergence = (f"call {index + 1}: recorded {recorded}, "
                               f"produced {Seen.of(item['text'])}")
            self._emit(completed(answer=self.reply))
        elif self.callback_index < len(self.steps):
            self.callbacks.append(self._callback_for(
                f"server-{index + 2}", f"call-{index + 2}", self._program(index + 1)))
            self._emit(self.callbacks[-1])
        else:
            if self.expected is not None and not self.expected.completed:
                self.divergence = "every recorded call was answered, yet the turn never completed"
            self._emit(completed(answer=self.reply))

    def _wire(self, method: str) -> list[dict]:
        """What this peer actually emitted, read back from its own bytes."""
        records = (json.loads(raw) for raw in self.emitted)
        return [record["params"] for record in records
                if isinstance(record, dict) and record.get("method") == method]

    @property
    def sent(self) -> list[str]:
        return [call["arguments"]["program"] for call in self._wire("item/tool/call")]

    def recording(self) -> Turn:
        """What this seat sent and saw, in the record's own form."""
        calls = tuple(
            Call(program, Seen.of(self.seen[index]) if index < len(self.seen) else None)
            for index, program in enumerate(self.sent))
        completions = self._wire("turn/completed")
        items = completions[0]["turn"]["items"] if completions else []
        return Turn(calls, bool(completions), items[-1]["text"] if items else None)

    def settle(self) -> None:
        """Raise unless the turn ran exactly as it was recorded."""
        assert self.expected is not None, "only a replayed turn has a record to settle"
        if self.divergence is not None:
            raise ReplayDiverged(self.divergence)
        if len(self.seen) < sum(call.seen is not None for call in self.expected.calls):
            raise ReplayDiverged(
                f"call {len(self.seen) + 1}: recorded an output, none was returned")
        if self.recording() != self.expected:
            raise ReplayDiverged(f"recorded {self.expected}, ran {self.recording()}")


def ideal(program: str) -> Seated:
    return Seated("ideal", [program])


def hostile(steps: Sequence[Step], *, reply: str | None = "done") -> Seated:
    return Seated("hostile", steps, reply=reply)


def replay(turn: Turn) -> Seated:
    if not turn.calls and not turn.completed:
        raise ValueError("a turn with no call and no completion sent nothing to replay")
    return Seated("replay", [call.program for call in turn.calls], reply=turn.reply,
                  expected=turn)


def live() -> Seated:
    raise NotImplementedError(
        "the live occupant is a real model behind the vendor binary; it sits only on the "
        "private host inside an owner-approved window")
