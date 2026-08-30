"""One human round trip: ask, park, reply, wake, complete (M7).

The component supplies a payload and nothing else. Where the request went,
under whose authority, on which ports and under which contracts were all
sealed at admission.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.channel import ChannelEndpoint, ChannelSendIntent
from constructicon.core.effect import EffectRequest, idempotency_key
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.ports import Port
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.effects.channel import ChannelSendEffect
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import FakeClock, atomic

CHANNEL_ID = "channel/review"
ADVISOR = "static:advisor"
REQUEST = Port(name="request", type_id="test/AdviceRequest", schema_hash="req-v1")
ADVICE = Port(name="advice", type_id="test/AdviceResponse", schema_hash="rep-v1")
INPUTS = {"request": {"question": "does this ship?"}}
ENDPOINT = ChannelEndpoint(lane="review", interaction="advice", recipient_actor_id=ADVISOR)


async def advisor_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    advice = await ctx.channel("advisor").ask(inputs["request"])
    return {"advice": advice}


def _graph() -> Graph:
    return Graph(
        name="one-advisor",
        nodes=(
            GraphNode(
                id="advisor",
                body=Ref(component="test/human-advisor", bind={"advisor": CHANNEL_ID}),
            ),
        ),
        connections=(),
        inputs=(REQUEST,),
        outputs=(ADVICE,),
    )


def _world(journal: SqliteJournal) -> tuple[Constructicon, MailboxChannel]:
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    system = Constructicon(
        journal=journal,
        capabilities={CHANNEL_ID: mailbox},
        catalog={
            CHANNEL_ID: CapabilityDescriptor(
                capability_id=CHANNEL_ID,
                kind="channel.mailbox",
                revision="1",
                channel_profile=mailbox.profile,
                endpoint=ENDPOINT,
            )
        },
        effects={
            "channel_send": ChannelSendEffect(
                journal=journal,
                catalog={(CHANNEL_ID, "1"): mailbox},
            )
        },
        owner_id="channel-round-trip",
    )
    definition, implementation = atomic("test/human-advisor", (REQUEST,), (ADVICE,), advisor_impl)
    version = system._register(definition, implementation)
    system._promote_initial(component=definition.name, version=version)
    return system, mailbox


async def _park(system: Constructicon, run_id: RunId) -> None:
    manifest = system.validate(_graph(), INPUTS)
    assert manifest.schema_version == 3  # it binds a channel, so it says so
    system._prepare_run(manifest, run_id=run_id, inputs=INPUTS)
    result = await system._run_prepared(run_id, cancellation="abandon")
    assert result.status is RunStatus.PARKED


async def test_an_advisor_asks_parks_and_completes_after_one_reply(
    journal: SqliteJournal,
) -> None:
    system, mailbox = _world(journal)
    run_id = RunId("run-advice-round-trip")
    await _park(system, run_id)

    waits = journal.parked_waits()
    assert [wait.run_id for wait in waits] == [run_id]
    request_id = waits[0].requests[0]

    stored = mailbox.message(request_id)
    assert stored is not None
    assert stored.recipient_actor_id == ADVISOR  # sealed routing, not a payload field
    assert stored.lane == "review"
    assert stored.envelope.port == "request"  # the component's one declared input
    assert stored.reply_port == "advice"  # and its one declared output
    assert stored.envelope.payload == INPUTS["request"]

    mailbox.reply(
        request_id=request_id,
        actor_id=ADVISOR,
        payload={"verdict": "ship it"},
        command_id="cmd-advice-1",
    )
    resumed = await system._run_prepared(run_id, cancellation="abandon")
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.outputs == {"advice": {"verdict": "ship it"}}


async def test_a_reconstructed_send_appends_no_second_message(
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    """The run parks twice before a reply; one request exists, with one time."""

    system, mailbox = _world(journal)
    run_id = RunId("run-advice-retry")
    await _park(system, run_id)
    request_id = journal.parked_waits()[0].requests[0]
    original = mailbox.message(request_id)
    assert original is not None

    clock.advance(3600)
    again = await system._run_prepared(run_id, cancellation="abandon")
    assert again.status is RunStatus.PARKED
    assert mailbox.message(request_id) == original  # same fact, same observation time
    assert mailbox.latest_revision(ADVISOR).message_seq == 1


async def test_a_counterfactual_send_writes_no_live_message(
    journal: SqliteJournal,
) -> None:
    """Simulation records evidence, never a message a human could answer."""

    system, mailbox = _world(journal)
    run_id = RunId("run-advice-simulated")
    await _park(system, run_id)
    stored = mailbox.message(journal.parked_waits()[0].requests[0])
    assert stored is not None
    before = mailbox.latest_revision(ADVISOR)

    intent = ChannelSendIntent(
        message_id=stored.message_id,
        channel_id=CHANNEL_ID,
        channel_revision="1",
        lane=stored.lane,
        interaction=stored.interaction,
        recipient_actor_id=stored.recipient_actor_id,
        contract=stored.contract,
        reply_contract=stored.reply_contract,
        run_id=stored.envelope.run_id,
        path=stored.envelope.path,
        port=stored.envelope.port,
        reply_port=stored.reply_port,
        payload=stored.envelope.payload,
    )
    subject = intent.model_dump(mode="json")
    manifest_hash = system.validate(_graph(), INPUTS).manifest_hash
    request = EffectRequest(
        run_id=run_id,
        manifest_hash=manifest_hash,
        path=stored.envelope.path,
        kind="channel_send",
        subject=subject,
        idempotency_key=idempotency_key(
            manifest_hash,
            stored.envelope.path,
            "channel_send",
            subject,
            mode="simulated",
        ),
        mode="simulated",
    )
    adapter = ChannelSendEffect(journal=journal, catalog={(CHANNEL_ID, "1"): mailbox})
    receipt = await adapter.simulate(request)

    assert receipt.status == "simulated"  # never a false "committed"
    assert receipt.external_reference == str(stored.message_id)
    assert mailbox.latest_revision(ADVISOR) == before  # and nothing was appended


async def test_admission_compiles_the_exchange_the_component_never_names(
    journal: SqliteJournal,
) -> None:
    system, _mailbox = _world(journal)
    manifest = system.validate(_graph(), INPUTS)
    binding = next(item for item in manifest.capability_bindings if item.binding == "advisor")

    assert binding.channel is not None
    assert binding.channel.endpoint == ENDPOINT  # assembly's routing, sealed
    assert binding.channel.port == "request"  # the one declared input
    assert binding.channel.reply_port == "advice"  # the one declared output
    assert binding.channel.contract.type_id == "test/AdviceRequest"
    assert binding.channel.reply_contract.type_id == "test/AdviceResponse"
