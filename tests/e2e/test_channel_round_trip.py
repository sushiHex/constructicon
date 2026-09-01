"""One human round trip: ask, park, reply, wake, complete (M7).

The component supplies a payload and nothing else. Where the request went,
under whose authority, on which ports and under which contracts were all
sealed at admission.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, IterationFrame, RunId, ScopePath
from constructicon.core.admission import AdmissionRejected
from constructicon.core.channel import (
    CHANNEL_SEND_EFFECT,
    ChannelEndpoint,
    ChannelSendIntent,
    request_message_id,
)
from constructicon.core.component import CapabilityRequirement
from constructicon.core.control import ADVISE_SCOPE, AuthenticatedActor, ChannelReplyResult
from constructicon.core.effect import EffectRequest, idempotency_key
from constructicon.core.errors import AdmissionError, ContractViolation
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.manifest import manifest_hash_for
from constructicon.core.ports import Port
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.channels.in_process import InProcessChannel
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.effects.channel import ChannelSendEffect
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import FakeClock, atomic

CHANNEL_ID = "channel/review"
ADVISOR = "static:advisor"
ADVISOR_ACTOR = AuthenticatedActor(
    actor_id=ADVISOR,
    auth_method="static",
    scopes=frozenset({ADVISE_SCOPE}),
)
REQUEST = Port(name="request", type_id="test/AdviceRequest", schema_hash="req-v1")
ADVICE = Port(name="advice", type_id="test/AdviceResponse", schema_hash="rep-v1")
INPUTS = {"request": {"question": "does this ship?"}}
ENDPOINT = ChannelEndpoint(lane="review", interaction="advice", recipient_actor_id=ADVISOR)


class _ValueEqualInProcessChannel(InProcessChannel):
    """A distinct transport that defeats equality-based assembly checks."""

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, InProcessChannel)
            and self.channel_id == other.channel_id
            and self.profile == other.profile
        )


async def advisor_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    advice = await ctx.channel("advisor").ask(inputs["request"])
    return {"advice": advice}


async def raw_channel_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    """A hostile component trying to escape the one admitted channel facade."""

    facade = ctx.channel("advisor")
    assert callable(facade.ask)
    for leaked in ("channel", "journal", "effect", "binding", "lease"):
        assert not hasattr(facade, leaked)
    ctx.capability("advisor")
    return {"advice": inputs["request"]}


def _graph(component: str = "test/human-advisor") -> Graph:
    return Graph(
        name="one-advisor",
        nodes=(
            GraphNode(
                id="advisor",
                body=Ref(component=component, bind={"advisor": CHANNEL_ID}),
            ),
        ),
        connections=(),
        inputs=(REQUEST,),
        outputs=(ADVICE,),
    )


_USE_MAILBOX = object()


def _world(
    journal: SqliteJournal,
    *,
    endpoint: ChannelEndpoint | None = ENDPOINT,
    capability: object = _USE_MAILBOX,
) -> tuple[Constructicon, MailboxChannel]:
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    injected = mailbox if capability is _USE_MAILBOX else capability
    system = Constructicon(
        journal=journal,
        capabilities={CHANNEL_ID: injected},
        catalog={
            CHANNEL_ID: CapabilityDescriptor(
                capability_id=CHANNEL_ID,
                kind="channel.mailbox",
                revision="1",
                channel_profile=mailbox.profile,
                endpoint=endpoint,
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

    replied = await ControlPlane(system=system, store=journal).channels_reply(
        ADVISOR_ACTOR,
        message_id=request_id,
        payload={"verdict": "ship it"},
        idempotency_key="advice-1",
    )
    assert isinstance(replied, ChannelReplyResult)
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


async def test_a_channel_effect_refuses_a_non_lossless_intent_before_append(
    journal: SqliteJournal,
) -> None:
    system, mailbox = _world(journal)
    run_id = RunId("run-channel-non-lossless-intent")
    path = ExecutionPath(
        scope=ScopePath(segments=("one-advisor", "advisor")),
        iterations=(
            IterationFrame(
                loop=ScopePath(segments=("one-advisor", "loop")),
                index=1,
            ),
        ),
    )
    intent = ChannelSendIntent(
        message_id=request_message_id(
            run_id=run_id,
            path=path,
            channel_id=CHANNEL_ID,
            channel_revision="1",
            lane=ENDPOINT.lane,
            interaction=ENDPOINT.interaction,
            port=REQUEST.name,
        ),
        channel_id=CHANNEL_ID,
        channel_revision="1",
        lane=ENDPOINT.lane,
        interaction=ENDPOINT.interaction,
        recipient_actor_id=ENDPOINT.recipient_actor_id,
        contract={"type_id": REQUEST.type_id, "schema_hash": REQUEST.schema_hash},
        reply_contract={"type_id": ADVICE.type_id, "schema_hash": ADVICE.schema_hash},
        run_id=run_id,
        path=path,
        port=REQUEST.name,
        reply_port=ADVICE.name,
        payload=INPUTS["request"],
    )
    subject = intent.model_dump(mode="json")
    subject["path"]["iterations"][0]["index"] = True
    manifest_hash = system.validate(_graph(), INPUTS).manifest_hash
    request = EffectRequest(
        run_id=run_id,
        manifest_hash=manifest_hash,
        path=path,
        kind=CHANNEL_SEND_EFFECT,
        subject=subject,
        idempotency_key=idempotency_key(
            manifest_hash,
            path,
            CHANNEL_SEND_EFFECT,
            subject,
        ),
    )
    adapter = ChannelSendEffect(journal=journal, catalog={(CHANNEL_ID, "1"): mailbox})
    before = mailbox.latest_revision(ADVISOR)

    with pytest.raises(ContractViolation, match="not a lossless ChannelSendIntent"):
        await adapter.execute(request)

    assert mailbox.latest_revision(ADVISOR) == before
    assert mailbox.message(intent.message_id) is None


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


def test_admission_refuses_a_bound_channel_without_sealed_routing(
    journal: SqliteJournal,
) -> None:
    system, _mailbox = _world(journal, endpoint=None)

    result = system.admit_graph(_graph(), INPUTS)

    assert isinstance(result, AdmissionRejected)
    assert any("supplied no ChannelEndpoint" in fault.message for fault in result.faults)


def test_assembly_refuses_a_channel_descriptor_backed_by_a_non_channel_object(
    journal: SqliteJournal,
) -> None:
    with pytest.raises(ValueError, match="implementing the Channel contract"):
        _world(journal, capability=object())


def test_assembly_refuses_a_missing_channel_before_recovery_can_activate_it(
    journal: SqliteJournal,
) -> None:
    with pytest.raises(ValueError, match="no object implementing the Channel contract"):
        Constructicon(
            journal=journal,
            catalog={
                CHANNEL_ID: CapabilityDescriptor(
                    capability_id=CHANNEL_ID,
                    kind="channel.mailbox",
                    revision="1",
                    channel_profile=MailboxChannel(
                        journal,
                        channel_id=CHANNEL_ID,
                    ).profile,
                    endpoint=ENDPOINT,
                )
            },
        )


def test_assembly_refuses_a_catalog_key_that_renames_its_descriptor(
    journal: SqliteJournal,
) -> None:
    transport = InProcessChannel(channel_id="channel/internal-name")

    with pytest.raises(ValueError, match="differs from its descriptor identity"):
        Constructicon(
            journal=journal,
            capabilities={"channel/catalog-key": transport},
            catalog={
                "channel/catalog-key": CapabilityDescriptor(
                    capability_id=transport.channel_id,
                    kind="channel.in_process",
                    revision="1",
                    channel_profile=transport.profile,
                    endpoint=ENDPOINT,
                )
            },
        )


def test_assembly_refuses_a_transport_serving_a_different_channel(
    journal: SqliteJournal,
) -> None:
    with pytest.raises(ValueError, match="transport serves 'channel/wrong'"):
        _world(
            journal,
            capability=MailboxChannel(journal, channel_id="channel/wrong"),
        )


def test_assembly_refuses_a_live_profile_weaker_than_the_descriptor(
    journal: SqliteJournal,
) -> None:
    with pytest.raises(ValueError, match="injected profile"):
        _world(
            journal,
            capability=InProcessChannel(channel_id=CHANNEL_ID),
        )


def test_assembly_refuses_distinct_send_and_reply_transports(
    journal: SqliteJournal,
) -> None:
    observed = InProcessChannel(channel_id=CHANNEL_ID)
    sent = InProcessChannel(channel_id=CHANNEL_ID)

    with pytest.raises(ValueError, match="exact channel transports"):
        Constructicon(
            journal=journal,
            capabilities={CHANNEL_ID: observed},
            catalog={
                CHANNEL_ID: CapabilityDescriptor(
                    capability_id=CHANNEL_ID,
                    kind="channel.in_process",
                    revision="1",
                    channel_profile=observed.profile,
                    endpoint=ENDPOINT,
                )
            },
            effects={
                "channel_send": ChannelSendEffect(
                    journal=journal,
                    catalog={(CHANNEL_ID, "1"): sent},
                )
            },
        )


def test_assembly_derives_channel_send_from_the_exact_live_transport(
    journal: SqliteJournal,
) -> None:
    transport = _ValueEqualInProcessChannel(channel_id=CHANNEL_ID)
    system = Constructicon(
        journal=journal,
        capabilities={CHANNEL_ID: transport},
        catalog={
            CHANNEL_ID: CapabilityDescriptor(
                capability_id=CHANNEL_ID,
                kind="channel.in_process",
                revision="1",
                channel_profile=transport.profile,
                endpoint=ENDPOINT,
            )
        },
    )

    effect = system._walker._effects.get(CHANNEL_SEND_EFFECT)
    assert isinstance(effect, ChannelSendEffect)
    assert effect.is_assembled_from(
        journal,
        {(CHANNEL_ID, "1"): transport},
    )
    lookalike = _ValueEqualInProcessChannel(channel_id=CHANNEL_ID)
    assert lookalike == transport and lookalike is not transport
    assert not effect.is_assembled_from(journal, {(CHANNEL_ID, "1"): lookalike})


def test_admission_refuses_a_foreign_exchange_on_the_approval_lane(
    journal: SqliteJournal,
) -> None:
    system, _mailbox = _world(
        journal,
        endpoint=ChannelEndpoint(
            lane="gate",
            interaction="approval",
            recipient_actor_id="static:approver",
        ),
    )

    result = system.admit_graph(_graph(), INPUTS)

    assert isinstance(result, AdmissionRejected)
    assert any("sole consumer" in fault.message for fault in result.faults)


def test_activation_refuses_a_historical_channel_binding_with_no_sealed_exchange(
    journal: SqliteJournal,
) -> None:
    """Recovery cannot expose a pre-fix channel binding as generic authority."""

    system, _mailbox = _world(journal)
    current = system.validate(_graph(), INPUTS)
    provisional = current.model_copy(
        update={
            "schema_version": 2,
            "capability_bindings": tuple(
                binding.model_copy(update={"channel": None})
                for binding in current.capability_bindings
            ),
        }
    )
    historical = provisional.model_copy(update={"manifest_hash": manifest_hash_for(provisional)})

    with pytest.raises(AdmissionError, match="sealed channel shape"):
        system._registry.activate(historical, catalog=system._catalog)


async def test_a_channel_bound_component_never_receives_the_raw_transport(
    journal: SqliteJournal,
) -> None:
    """Actor ids, message ids, and routing remain behind the sealed ask facade."""

    system, _mailbox = _world(journal)
    definition, implementation = atomic(
        "test/raw-channel-escape",
        (REQUEST,),
        (ADVICE,),
        raw_channel_impl,
    )
    definition = definition.model_copy(
        update={
            "capability_requirements": (
                CapabilityRequirement(alias="advisor", kind="channel.mailbox"),
            )
        }
    )
    version = system._register(definition, implementation)
    system._promote_initial(component=definition.name, version=version)
    manifest = system.validate(_graph(definition.name), INPUTS)
    run_id = RunId("run-raw-channel-escape")
    system._prepare_run(manifest, run_id=run_id, inputs=INPUTS)

    result = await system._run_prepared(run_id, cancellation="abandon")

    assert result.status is RunStatus.FAILED
    assert any("holds no capability 'advisor'" in failure for failure in result.failures.values())
