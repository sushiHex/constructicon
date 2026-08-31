"""Contracts and interaction are not independent facts (M7 PR C).

An admitted channel binding carries two decisions from two places: the component
declares what crosses, and assembly's endpoint declares under whose authority.
Admission is the only place that sees both, and for the two canonical human
exchanges they must agree.

They must agree because the authority that *answers* an exchange is chosen by
its interaction, while what the answer is *believed to be* is chosen by its
contracts. Let those diverge and a human holding advise alone authors the whole
`ApprovalRecord` a run returns as a governance fact.
"""

from __future__ import annotations

import pytest

from constructicon.core.channel import ChannelContract, ChannelInteraction
from constructicon.core.human import (
    ADVICE_REPLY_CONTRACT,
    ADVICE_REQUEST_CONTRACT,
    APPROVAL_REPLY_CONTRACT,
    APPROVAL_REQUEST_CONTRACT,
    canonical_exchange_fault,
)

FOREIGN_REQUEST = ChannelContract(type_id="other/Ask", schema_hash="ask-1")
FOREIGN_REPLY = ChannelContract(type_id="other/Answer", schema_hash="answer-1")


@pytest.mark.parametrize(
    ("request_contract", "reply_contract", "interaction"),
    [
        (ADVICE_REQUEST_CONTRACT, ADVICE_REPLY_CONTRACT, "advice"),
        (APPROVAL_REQUEST_CONTRACT, APPROVAL_REPLY_CONTRACT, "approval"),
        (FOREIGN_REQUEST, FOREIGN_REPLY, "advice"),
        (FOREIGN_REQUEST, FOREIGN_REPLY, "approval"),
    ],
)
def test_a_coherent_exchange_is_admitted(
    request_contract: ChannelContract,
    reply_contract: ChannelContract,
    interaction: ChannelInteraction,
) -> None:
    """Both canonical pairs under their own interaction, and any foreign pair."""

    assert canonical_exchange_fault(request_contract, reply_contract, interaction) is None


def test_an_approval_exchange_sealed_as_advice_is_refused() -> None:
    """The escalation this check exists for.

    `channels_reply` consumes advice and stamps only advice replies, so an
    approval exchange sealed as advice would be answered by an advise-scoped
    human whose payload is stored verbatim — the whole record, actor and
    decision included, arriving at the component as a trusted fact.
    """

    fault = canonical_exchange_fault(
        APPROVAL_REQUEST_CONTRACT,
        APPROVAL_REPLY_CONTRACT,
        "advice",
    )
    assert fault is not None
    assert "interaction='approval'" in fault


def test_an_advice_exchange_sealed_as_approval_is_refused() -> None:
    """The mirror: no operation consumes it, so the run parks forever."""

    fault = canonical_exchange_fault(
        ADVICE_REQUEST_CONTRACT,
        ADVICE_REPLY_CONTRACT,
        "approval",
    )
    assert fault is not None
    assert "interaction='advice'" in fault


@pytest.mark.parametrize(
    ("request_contract", "reply_contract"),
    [
        (APPROVAL_REQUEST_CONTRACT, ADVICE_REPLY_CONTRACT),
        (ADVICE_REQUEST_CONTRACT, APPROVAL_REPLY_CONTRACT),
        (APPROVAL_REQUEST_CONTRACT, FOREIGN_REPLY),
        (FOREIGN_REQUEST, APPROVAL_REPLY_CONTRACT),
    ],
)
def test_half_a_canonical_exchange_is_refused(
    request_contract: ChannelContract,
    reply_contract: ChannelContract,
) -> None:
    """A pair naming one canonical contract and not its partner is a mismatch.

    Recognized by either half, so neither can be used to dress a foreign
    exchange in a canonical one's authority.
    """

    for interaction in ("advice", "approval"):
        fault = canonical_exchange_fault(
            request_contract,
            reply_contract,
            interaction,  # type: ignore[arg-type]
        )
        assert fault is not None
        assert "pairs" in fault
