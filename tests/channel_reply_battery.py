"""Differential fault battery for one in-process channel source, in a fresh interpreter.

Run as ``python -I tests/channel_reply_battery.py <src root> <module source>``.
It loads the given source bytes as the module under test, drives a fixed
scenario list and prints one JSON report: results, exact exception type and
text, acknowledgement and revision state, and every retained-index lookup with
the lock depth it ran under. Calibration evidence only, never gate authority.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from importlib.machinery import SourceFileLoader
from pathlib import Path

sys.path.insert(0, sys.argv[1])

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.channel import (
    ChannelContract,
    ChannelSendIntent,
    request_message_id,
)

NOW = datetime(2026, 11, 8, tzinfo=UTC)
CHANNEL = "channel/battery"
ADVISOR = "static:advisor"
OTHER = "static:other"


def _load(path: str):
    loader = SourceFileLoader("channel_under_test", path)
    spec = importlib.util.spec_from_loader("channel_under_test", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


MODULE = _load(sys.argv[2])
LOOKUPS: list[int] = []


class CountingLock:
    """Non-reentrant like ``threading.Lock``; records entries and nesting."""

    def __init__(self) -> None:
        self.depth = 0
        self.entries = 0

    def __enter__(self) -> None:
        if self.depth:
            raise RuntimeError("lock re-entered")
        self.depth += 1
        self.entries += 1

    def __exit__(self, *exc: object) -> None:
        self.depth -= 1


class ObservedIndex(dict):
    lock: CountingLock

    def get(self, key, default=None):  # type: ignore[override]
        LOOKUPS.append(self.lock.depth)
        return super().get(key, default)


def channel():
    built = MODULE.InProcessChannel(channel_id=CHANNEL, now_fn=lambda: NOW)
    lock = CountingLock()
    index = ObservedIndex()
    index.lock = lock
    built._lock = lock
    built._by_id = index
    return built


def intent(port: str = "request") -> ChannelSendIntent:
    path = ExecutionPath(scope=ScopePath(segments=("battery",)))
    run = RunId("run-channel-battery")
    return ChannelSendIntent(
        message_id=request_message_id(run_id=run, path=path, channel_id=CHANNEL,
            channel_revision="1", lane="review", interaction="advice", port=port),
        channel_id=CHANNEL, channel_revision="1", lane="review", interaction="advice",
        recipient_actor_id=ADVISOR,
        contract=ChannelContract(type_id="test/Request", schema_hash="request-v1"),
        reply_contract=ChannelContract(type_id="test/Reply", schema_hash="reply-v1"),
        run_id=run, path=path, port=port, reply_port="reply",
        payload={"question": "ship it?"},
    )


def answered(c):
    request = c.append_request(intent(), "att-battery")
    reply = c.reply(request_id=request.message_id, actor_id=ADVISOR,
                    payload={"answer": "yes"}, command_id="reply-1")
    return request, reply


def tear(c, request) -> None:
    """Remove the reply's atomic acknowledgement from every ack index."""
    key = (str(request.message_id), ADVISOR)
    ack = c._ack_by_key.pop(key)
    c._acks.remove(ack)
    command = next(name for name, owned in c._ack_commands.items() if owned == key)
    del c._ack_commands[command]


def damage_history(c) -> None:
    c._seq_by_id[next(iter(c._seq_by_id))] = 99


def drop_port(c, request, *, proof: bool) -> None:
    object.__setattr__(c._by_id[str(request.message_id)], "reply_port", None)
    if proof:
        object.__setattr__(c._request_intent_by_message[str(request.message_id)],
                           "reply_port", None)


def scenarios():
    def absent(c):
        missing = intent("absent").message_id
        return [lambda: c.reply_for(missing),
                lambda: c.acknowledge(message_id=missing, actor_id=ADVISOR, command_id="a")]

    def no_reply(c):
        request = c.append_request(intent(), "att-battery")
        return [lambda: c.reply_for(request.message_id)]

    def valid_detach(c):
        request, _ = answered(c)

        def mutate_returned():
            first = c.reply_for(request.message_id)
            first.envelope.payload["answer"] = "mutated"
            return c.reply_for(request.message_id)

        return [lambda: c.reply_for(request.message_id), mutate_returned]

    def ack_cycle(c):
        request = c.append_request(intent(), "att-battery")
        ack = lambda command: c.acknowledge(  # noqa: E731
            message_id=request.message_id, actor_id=OTHER, command_id=command)
        return [lambda: ack("ack-1"), lambda: ack("ack-1"), lambda: ack("ack-2")]

    def answered_ack(c):
        request, _ = answered(c)
        return [lambda: c.acknowledge(message_id=request.message_id, actor_id=ADVISOR,
                                      command_id="reply-1"),
                lambda: c.acknowledge(message_id=request.message_id, actor_id=ADVISOR,
                                      command_id="other")]

    def reply_id_input(c):
        _, reply = answered(c)
        return [lambda: c.reply_for(reply.message_id),
                lambda: c.acknowledge(message_id=reply.message_id, actor_id=OTHER,
                                      command_id="ack-reply")]

    def forged_pointer(c):
        request, reply = answered(c)
        other = c.append_request(intent("other"), "att-other")
        forged = reply.model_copy(update={"reply_to": other.message_id})
        index = c._messages.index(c._by_id[str(reply.message_id)])
        c._messages[index] = forged
        dict.__setitem__(c._by_id, str(reply.message_id), forged)
        return [lambda: c.reply_for(request.message_id),
                lambda: c.acknowledge(message_id=request.message_id, actor_id=OTHER,
                                      command_id="ack-forged")]

    def torn(c):
        request, _ = answered(c)
        tear(c, request)
        return [lambda: c.reply_for(request.message_id),
                lambda: c.acknowledge(message_id=request.message_id, actor_id=ADVISOR,
                                      command_id="after-tear")]

    def history_and_bad_request(c):
        c.append_request(intent(), "att-battery")
        damage_history(c)
        missing = intent("absent").message_id
        return [lambda: c.reply_for(missing),
                lambda: c.acknowledge(message_id=missing, actor_id=ADVISOR, command_id="a")]

    def proof_and_missing_port(c):
        request = c.append_request(intent(), "att-battery")
        drop_port(c, request, proof=False)
        return [lambda: c.reply_for(request.message_id),
                lambda: c.acknowledge(message_id=request.message_id, actor_id=ADVISOR,
                                      command_id="a")]

    def consistent_missing_port(c):
        request = c.append_request(intent(), "att-battery")
        drop_port(c, request, proof=True)
        return [lambda: c.reply_for(request.message_id),
                lambda: c.acknowledge(message_id=request.message_id, actor_id=ADVISOR,
                                      command_id="a")]

    def torn_and_conflicting_ack(c):
        request, _ = answered(c)
        tear(c, request)
        # Another command already holds this actor's acknowledgement.
        key = (str(request.message_id), OTHER)
        held = MODULE.ChannelAck(message_id=request.message_id, actor_id=OTHER, acked_at=NOW)
        c._append_ack(key, held, "holder")
        return [lambda: c.acknowledge(message_id=request.message_id, actor_id=OTHER,
                                      command_id="loser"),
                lambda: c.reply_for(request.message_id)]

    return {name: build for name, build in locals().items() if callable(build)}


def observe(c, operation):
    LOOKUPS.clear()
    entries = c._lock.entries
    try:
        value = operation()
        outcome = {"result": None if value is None else value.model_dump(mode="json")}
    except Exception as error:
        outcome = {"error": type(error).__name__, "text": str(error)}
    outcome.update(
        lock_entries=c._lock.entries - entries, lock_held_after=c._lock.depth,
        lookup_depths=list(LOOKUPS), message_seq=len(c._messages), ack_seq=len(c._acks),
        acks=sorted([key[0], key[1], command] for command, key in c._ack_commands.items()),
    )
    return outcome


def main() -> None:
    report = {}
    for name, build in scenarios().items():
        c = channel()
        operations = build(c)
        report[name] = [observe(c, operation) for operation in operations]
    print(json.dumps({"source": Path(sys.argv[2]).name, "report": report}, sort_keys=True))


if __name__ == "__main__":
    main()
