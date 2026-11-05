"""The M9 operator trial's reviewed mailbox and leased issuer assembly."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.channel import ChannelEndpoint
from constructicon.core.graph import Graph
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.effects.channel import ChannelSendEffect
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.e2e.m9_issuer import (
    ISSUER_CAP,
    OPERATOR_CHANNEL,
    Issuer,
    issue_from_operator_decision,
    operator_approval_bundle,
    operator_issuer_definition,
    operator_issuer_graph,
)


def assemble_operator_approval(
    journal: SqliteJournal,
    issuer: Issuer,
    *,
    seed: bool = False,
    fault_probe: Callable[[str], None] | None = None,
) -> tuple[ControlPlane, MailboxChannel, Graph]:
    """Assemble the pinned approval graph; seed components only on initial startup."""
    if (
        issuer.journal is not journal
        or issuer.approvals is not journal
        or issuer.registry is not journal
    ):
        raise ValueError("M9 operator issuance requires one journal for all durable facts")
    mailbox = MailboxChannel(journal, channel_id=OPERATOR_CHANNEL)
    world = Constructicon(
        journal=journal,
        capabilities={
            OPERATOR_CHANNEL: mailbox,
            ISSUER_CAP: replace(issuer, operator_mailbox=True),
        },
        catalog={
            OPERATOR_CHANNEL: CapabilityDescriptor(
                capability_id=OPERATOR_CHANNEL,
                kind="channel.mailbox",
                revision="1",
                channel_profile=mailbox.profile,
                endpoint=ChannelEndpoint(
                    lane="gate", interaction="approval", recipient_actor_id=issuer.owner
                ),
            ),
            ISSUER_CAP: CapabilityDescriptor(
                capability_id=ISSUER_CAP, kind=ISSUER_CAP, revision="1", leased=True
            ),
        },
        effects={
            "channel_send": ChannelSendEffect(
                journal=journal, catalog={(OPERATOR_CHANNEL, "1"): mailbox}
            )
        },
    )
    gate = operator_approval_bundle()
    for component, implementation in (
        (gate.definition, gate.implementation),
        (operator_issuer_definition(), issue_from_operator_decision),
    ):
        if seed:
            world._register(component, implementation)
        retained = journal.snapshot().get(component.name, component.content_hash())
        if retained is None or retained.definition != component:
            raise ValueError(f"M9 approval assembly lacks the pinned definition: {component.name}")
    return (
        ControlPlane(system=world, store=journal, fault_probe=fault_probe),
        mailbox,
        operator_issuer_graph(),
    )
