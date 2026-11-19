"""Real durable batch -> prepared input -> scripted native window -> checked reply.

The native fixture runs the actual producer, adapter, supervisor, guest shell,
closure and collector. Only external transport/platform primitives are fake.
Private operator custody is trusted; this is no attestation against an operator
rewriting every private record, and it proves no model quality or live host.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from examples import change_review as source
from examples import change_review_batch as batch
from scripts.ops import change_review_batch_prepare as preparation
from scripts.ops import change_review_batch_reply as bridge
from scripts.ops import change_review_input as producer
from scripts.ops import change_review_reply as collector

from constructicon.api import change_review_advice as route
from constructicon.api.control import ControlPlane
from constructicon.core.address import RunId
from constructicon.core.control import ControlCode, ControlRejected, command_id_for
from tests import test_change_review_read as chain
from tests.e2e.test_change_review_batch_example import (
    by_path,
    entry,
    output,
    source_commits,
    submit_arguments,
)
from tests.substrate import test_codex_adapter as adapter
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_adapter import substituted_guard as substituted_guard
from tests.substrate.test_codex_protocol import completed, usage_update
from tests.test_change_review_input import source_world as source_world


def local(state: Path, operation):
    """Use the ordinary durable assembly, and shut down its real workers."""
    async def run():
        system, control = source.assemble(state / "review.db")
        try:
            return await operation(system, control)
        finally:
            await control.shutdown()

    return asyncio.run(run())


@pytest.fixture
def native_world(tmp_path, monkeypatch, portable_binding, substituted_guard, source_world):
    controller_repository, controller, _, _ = source_world
    # On Windows pytest's temp root lacks private-custody ACLs. Replace only
    # that platform primitive, as test_change_review_reply.checked does.
    real_private = collector.private_directory

    def private(path):
        if os.name == "posix":
            real_private(path)

    monkeypatch.setattr(collector, "private_directory", private)
    monkeypatch.setattr(batch, "POLL_SECONDS", 0.01)
    worlds = []

    def create(answer="Opaque advice: test the empty input."):
        root = tmp_path / f"world-{len(worlds)}"
        root.mkdir()
        repository, before, after = source_commits(
            root,
            {"calc.py": b"def calc(values): return 1\n", "sibling.py": b"def sibling(): pass\n"},
            {"calc.py": b"def calc(values): return 2\n",
             "sibling.py": b"def sibling(): return 3\n"},
        )
        state = root / "state"
        submitted = output(entry(state, *submit_arguments(
            repository, before, after, ("calc.py", "sibling.py"),
        )))
        assert submitted["result"]["status"] == "parked"
        selected = by_path(submitted)["calc.py"]
        packet = root / "packet"

        async def prepare(system, control):
            return preparation.prepare_batch_input(
                system, control, run_id=RunId(submitted["run_id"]),
                file_id=selected["file_id"], controller=controller,
                controller_repository=controller_repository, out=packet,
            )

        binding = local(state, prepare)
        raw = (packet / "summary.json").read_bytes()
        monkeypatch.setattr(chain, "DEMO", route.ChangeSummaryV2.model_validate_json(raw))
        monkeypatch.setattr(chain, "SUMMARY", raw)
        native_root = root / "native"
        native_root.mkdir()
        platform = chain.Platform(native_root, monkeypatch, portable_binding, answer=answer)
        platform.native = adapter.clean_native(records=[
            usage_update(input_tokens=37, output_tokens=11), completed(answer=answer),
        ])
        selection, selection_digest = chain.selection(native_root, summary=raw)
        host, result = platform.window(selection, selection_digest)
        collected = collector.collect(platform.custody, result.record, packet)
        world = SimpleNamespace(
            root=root, state=state, submitted=submitted, selected=selected,
            packet=packet, binding=binding,
            binding_sha256=hashlib.sha256((packet / "binding.json").read_bytes()).hexdigest(),
            platform=platform, host=host, result=result, collected=collected,
            counts=platform.counts.copy(), answer=answer,
        )
        worlds.append(world)
        return world

    return create


def handback(world, *, key="native-handback", **changes):
    async def apply(system, control):
        return await bridge.handback(
            system, control, **{
                "binding_file": world.packet / "binding.json",
                "binding_sha256": world.binding_sha256,
                "work": world.platform.custody, "record": world.result.record,
                "key": key, **changes,
            },
        )

    return local(world.state, apply)


def retained(world):
    system, control = source.assemble(world.state / "review.db")
    run_id = RunId(world.submitted["run_id"])
    return system, control, batch.observe(system, control, run_id)


def test_actual_collector_advice_at_batch_bound_replies_once_and_keeps_usage_separate(
    native_world, monkeypatch, capsys,
):
    answer = "\N{SNOWMAN}" * 1365 + "x"
    assert len(answer.encode("utf-8")) == batch.MAX_ADVICE_BYTES
    world = native_world(answer)
    assert (world.result.reason, world.result.cleanup) == ("read-settled", "clean")
    assert world.result.accepted_read_sha256 is not None
    assert world.collected["status"] == "delivered"
    assert world.collected["advice"]["advice"] == answer
    assert world.platform.turns() == 1
    assert world.counts["guest-dispatch"] == 1
    assert world.counts["guest-replay"] == 1
    # The entry's one-run native journal is never the batch journal.
    assert Path(world.platform.local(chain.JOURNAL)) != world.state / "review.db"
    calls = []
    real = collector.collect

    def collect(*args):
        calls.append(args)
        return real(*args)

    monkeypatch.setattr(collector, "collect", collect)
    first = handback(world)
    replay = handback(world)
    assert calls == [(world.platform.custody, world.result.record, world.packet)] * 2
    assert first["reply_command"]["command"]["replayed"] is False
    assert replay["reply_command"]["command"]["replayed"] is True
    assert replay["reply_command"]["message_id"] == first["reply_command"]["message_id"]
    assert first["file_id"] == world.selected["file_id"]
    assert first["request_id"] == world.selected["request"]["message_id"]
    assert first["binding_sha256"] == world.binding_sha256
    assert first["wait_status"] == "settled" and first["partial"] is False
    assert first["usage_relation"] == "separate_not_attributed"
    assert first["native_window"] == {
        name: world.collected[name] for name in (
            "run_id", "window", "accepted_read_sha256", "approval_sha256", "approval_slot",
            "summary_sha256", "instruction_digest", "metering",
        )
    }
    (group,) = first["native_window"]["metering"]["groups"]
    assert (group["known_input_tokens"], group["known_output_tokens"]) == (37, 11)
    assert first["native_window"]["metering"]["confirmed_charge"] is None
    assert first["native_window"]["metering"]["estimate"] is None
    assert "advice" not in first and answer not in json.dumps(first, ensure_ascii=False)
    system, control, observed = retained(world)
    files = by_path(observed)
    assert files["calc.py"]["advice"]["advice"] == answer
    assert files["calc.py"]["advice"]["actor_id"] == source.OPERATOR.actor_id
    assert files["sibling.py"]["request"] == by_path(world.submitted)["sibling.py"]["request"]
    assert files["sibling.py"]["reply"] is None and files["sibling.py"]["status"] == "parked"
    result = source.checked(control.runs_result(source.OPERATOR, RunId(observed["run_id"])))
    assert observed["result"] == result.model_dump(mode="json")
    assert first["batch_root"] == {
        "run_id": observed["run_id"], "status": observed["result"]["status"],
        "metering": observed["result"]["metering"],
    }
    assert replay["batch_root"] == first["batch_root"]
    assert source.checked(control.runs_list(source.OPERATOR)).page.count == 1
    reply = system._journal.channel_reply_for(
        channel_id=source.CHANNEL_ID, request_id=first["request_id"],
    )
    assert reply is not None and str(reply.message_id) == first["reply_command"]["message_id"]
    command_id = command_id_for(source.OPERATOR.actor_id, "channels_reply", "native-handback")
    writer = system._journal.channel_message_writer(message_id=reply.message_id)
    assert writer is not None and writer.command_id == command_id
    assert world.platform.counts == world.counts and world.platform.turns() == 1
    # The actual CLI writes binary UTF-8 JSON, including on Windows. Reuse
    # the original key and real retained evidence, so this spends no turn.
    argv = ["--state", str(world.state), "--binding", str(world.packet / "binding.json"),
            "--binding-sha256", world.binding_sha256,
            "--work", str(world.platform.custody), "--record", str(world.result.record),
            "--key", "native-handback"]
    capsys.readouterr()
    assert bridge.main(argv) == 0
    emitted = capsys.readouterr()
    assert emitted.err == "" and json.loads(emitted.out) == replay
    assert len(emitted.out.encode("utf-8")) <= bridge.MAX_REPLY_BYTES
    argv[argv.index(world.binding_sha256)] = "0" * 64
    assert bridge.main(argv) == 1
    emitted = capsys.readouterr()
    assert emitted.err == ""
    assert json.loads(emitted.out) == {
        "status": "refused", "reason": "batch_binding_pin_mismatch", "partial": False,
    }
    argv[argv.index("0" * 64)] = world.binding_sha256
    # Bind the serialization ceiling against this actual response. The check
    # is after Core's durable replay, so report retained effects as unverified.
    completed_replays = []
    real_reply = ControlPlane.channels_reply
    before_command = system._journal.command(command_id)
    before_events = system._journal.events(RunId(observed["run_id"]))

    async def counted_reply(self, *args, **kwargs):
        result = source.checked(await real_reply(self, *args, **kwargs))
        completed_replays.append(result.model_dump(mode="json"))
        return result

    with monkeypatch.context() as patch:
        patch.setattr(bridge, "MAX_REPLY_BYTES", len(producer._wire(replay)) - 1)
        patch.setattr(ControlPlane, "channels_reply", counted_reply)
        with pytest.raises(bridge.HandbackUnverified,
                           match=r"^batch_bridge_response_unbounded$") as unverified:
            handback(world)
        expected_unverified = {
            "status": "unverified", "reason": "batch_bridge_response_unbounded",
            "partial": True, "root_run_id": world.submitted["run_id"],
            "file_id": first["file_id"], "request_id": first["request_id"],
            "reply_command": replay["reply_command"],
            "next_action": (
                "Inspect retained batch state; replay only the original key and inputs."
            ),
        }
        assert unverified.value.response == expected_unverified
        assert bridge.main(argv) == 1
        emitted = capsys.readouterr()
        assert emitted.err == "" and json.loads(emitted.out) == expected_unverified
    assert completed_replays == [replay["reply_command"]] * 2
    # A lost return after a real committed/replayed command preserves uncertainty
    # about the reply result; the exact original key remains the repair route.
    lost_returns = []

    async def lose_reply(self, *args, **kwargs):
        result = source.checked(await real_reply(self, *args, **kwargs))
        lost_returns.append(result.model_dump(mode="json"))
        raise OSError("fixture lost command return")

    with monkeypatch.context() as patch:
        patch.setattr(ControlPlane, "channels_reply", lose_reply)
        with pytest.raises(bridge.HandbackUnverified,
                           match=r"^batch_reply_outcome_unverified$") as unverified:
            handback(world)
    assert lost_returns == [replay["reply_command"]]
    assert unverified.value.response == {
        **expected_unverified, "reason": "batch_reply_outcome_unverified",
        "reply_command": None,
    }
    assert system._journal.command(command_id) == before_command
    assert system._journal.events(RunId(observed["run_id"])) == before_events
    assert system._journal.channel_reply_for(
        channel_id=source.CHANNEL_ID, request_id=first["request_id"],
    ) == reply
    assert world.platform.counts == world.counts and world.platform.turns() == 1


def test_accepted_native_advice_over_batch_utf8_bound_refuses_without_truncation(
    native_world, monkeypatch,
):
    world = native_world("\N{SNOWMAN}" * 1365 + "xx")
    assert world.collected["status"] == "delivered"
    assert world.collected["advice"]["reply_bytes"] == batch.MAX_ADVICE_BYTES + 1
    refuse_before_command(world, monkeypatch, lambda: handback(world))
    assert world.collected["advice"]["advice"] == world.answer


def refuse_before_command(world, monkeypatch, operation):
    """Static refusal: no command claim, channel mutation, or worker recovery."""
    system, _, before = retained(world)
    events = system._journal.events(RunId(before["run_id"]))
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append(kwargs)
        pytest.fail("refused bridge reached channels_reply")

    with monkeypatch.context() as patch:
        patch.setattr(ControlPlane, "channels_reply", forbidden)
        with pytest.raises((ValueError, RuntimeError)):
            operation()
    assert calls == []
    after_system, _, after = retained(world)
    assert after == before
    assert after_system._journal.events(RunId(before["run_id"])) == events
    command_id = command_id_for(source.OPERATOR.actor_id, "channels_reply", "native-handback")
    assert after_system._journal.command(command_id) is None
    assert world.platform.counts == world.counts and world.platform.turns() <= 1


def test_real_not_delivered_window_refuses_before_batch_mutation(native_world, monkeypatch):
    world = native_world("")
    assert world.collected["status"] == "not-delivered"
    assert world.result.accepted_read_sha256 is None
    assert "advice" not in world.collected
    refuse_before_command(world, monkeypatch, lambda: handback(world))


def test_binding_packet_and_window_tamper_refuse_then_stale_request_uses_core_conflict_rules(
    native_world, monkeypatch, capsys,
):
    world = native_world()
    assert world.collected["status"] == "delivered"
    refuse_before_command(
        world, monkeypatch, lambda: handback(world, binding_sha256="0" * 64),
    )
    instruction = world.packet / "instruction.txt"
    original = instruction.read_bytes()
    instruction.write_bytes(original + b" ")
    refuse_before_command(world, monkeypatch, lambda: handback(world))
    instruction.write_bytes(original)
    # A new caller pin cannot turn another request into the selected member.
    wrong_packet = world.root / "wrong-selection"
    shutil.copytree(world.packet, wrong_packet)
    wrong_binding = {**world.binding, "request_id":
                     by_path(world.submitted)["sibling.py"]["request"]["message_id"]}
    wrong_raw = json.dumps(wrong_binding, sort_keys=True).encode("utf-8")
    (wrong_packet / "binding.json").write_bytes(wrong_raw)
    refuse_before_command(world, monkeypatch, lambda: handback(
        world, binding_file=wrong_packet / "binding.json",
        binding_sha256=hashlib.sha256(wrong_raw).hexdigest(),
    ))
    # Change one retained evidence file in a copy of an actually accepted
    # producer tree; the collector, rather than caller JSON, rejects it.
    copied = world.root / "tampered-custody"
    shutil.copytree(world.platform.custody, copied)
    evidence = next(copied.glob("native-*/captures/read-projection.stdout"))
    evidence.write_bytes(evidence.read_bytes() + b" ")
    refuse_before_command(world, monkeypatch, lambda: handback(
        world, work=copied, record=copied / world.result.record.name,
    ))
    # Answer the exact request through the standard public command first.
    output(entry(
        world.state, "reply", "--run-id", world.submitted["run_id"],
        "--file-id", world.selected["file_id"], "--advice", "Earlier operator reply.",
        "--key", "prior-answer",
    ))
    refuse_before_command(world, monkeypatch, lambda: handback(world))
    # A known caller key must reach Core so its payload comparison, rather
    # than a bridge replay cache, decides the conflict.
    calls = []
    real = ControlPlane.channels_reply

    async def counted(self, *args, **kwargs):
        calls.append(kwargs)
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(ControlPlane, "channels_reply", counted)
    with pytest.raises(bridge.HandbackRefused,
                       match=r"control\.idempotency\.conflict") as refused:
        handback(world, key="prior-answer")
    assert len(calls) == 1
    expected = {
        "status": "refused", "reason": "batch_reply_rejected", "partial": False,
        "fault_codes": ["control.idempotency.conflict"],
    }
    assert refused.value.response == expected
    capsys.readouterr()
    assert bridge.main([
        "--state", str(world.state), "--binding", str(world.packet / "binding.json"),
        "--binding-sha256", world.binding_sha256, "--work", str(world.platform.custody),
        "--record", str(world.result.record), "--key", "prior-answer",
    ]) == 1
    emitted = capsys.readouterr()
    assert emitted.err == "" and json.loads(emitted.out) == expected
    assert world.answer not in emitted.out and "Earlier operator reply." not in emitted.out
    assert str(world.root) not in emitted.out
    assert len(calls) == 2
    _, _, observed = retained(world)
    assert by_path(observed)["calc.py"]["advice"]["advice"] == "Earlier operator reply."
    assert by_path(observed)["sibling.py"]["reply"] is None
    assert world.platform.counts == world.counts and world.platform.turns() == 1


def test_typed_core_refusal_cli_retains_codes_without_private_fault_details(
    tmp_path, monkeypatch, capsys,
):
    outcome = ControlRejected.one_fault(
        ControlCode.IDEMPOTENCY_CONFLICT, "fixture private message", "fixture private repair",
        {"payload": "fixture private details"},
    )
    refused = bridge.HandbackRefused(outcome)
    expected = {
        "status": "refused", "reason": "batch_reply_rejected", "partial": False,
        "fault_codes": ["control.idempotency.conflict"],
    }
    assert refused.response == expected

    async def execute(_args):
        raise refused

    monkeypatch.setattr(bridge, "execute", execute)
    assert bridge.main([
        "--state", str(tmp_path / "state"), "--binding", str(tmp_path / "binding.json"),
        "--binding-sha256", "0" * 64, "--work", str(tmp_path / "work"),
        "--record", str(tmp_path / "record"), "--key", "typed-refusal",
    ]) == 1
    emitted = capsys.readouterr()
    assert emitted.err == "" and json.loads(emitted.out) == expected
    assert "fixture private" not in emitted.out and "fixture private" not in str(refused)
    assert not (tmp_path / "state").exists()
