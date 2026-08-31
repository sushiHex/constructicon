"""The channel read surface serves an actor, never a query (M7 PR C).

An inbox is derived from who you are: there is no parameter that names another
recipient, and no parameter that widens which interactions you may see. A
cursor carries both halves of that authority, so a page cannot be resumed under
another identity or under scopes the actor no longer holds.
"""

from __future__ import annotations

from pathlib import Path

from constructicon.api.control import ControlPlane
from constructicon.api.cursor import CursorCodec
from constructicon.api.detail import DetailAddress
from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.channel import (
    ChannelContract,
    ChannelInteraction,
    ChannelSendIntent,
    request_message_id,
)
from constructicon.core.control import (
    ADVISE_SCOPE,
    APPROVE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    ChannelMessagePage,
    ControlCode,
    ControlRejected,
)
from constructicon.core.identity import canonical_json, json_value
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import FakeClock

CHANNEL_ID = "channel/review"
ALICE_ID = "static:alice"
BOB_ID = "static:bob"
RUN = RunId("run-channel-reads")
PATH = ExecutionPath(scope=ScopePath(segments=("review",)))
REQUEST_CONTRACT = ChannelContract(type_id="test/Ask", schema_hash="ask-v1")
REPLY_CONTRACT = ChannelContract(type_id="test/Answer", schema_hash="answer-v1")
ATTESTATION = "att-channel-reads"


def _actor(actor_id: str, *scopes: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=actor_id,
        auth_method="static",
        scopes=frozenset({READ_SCOPE, *scopes}),
    )


ALICE = _actor(ALICE_ID, ADVISE_SCOPE, APPROVE_SCOPE)
ALICE_ADVISE_ONLY = _actor(ALICE_ID, ADVISE_SCOPE)
BOB = _actor(BOB_ID, ADVISE_SCOPE, APPROVE_SCOPE)
READER = _actor("static:reader")
# An advisor is its own role, not an observer with extra rights (I9).
ADVISOR_ONLY = AuthenticatedActor(
    actor_id=ALICE_ID,
    auth_method="static",
    scopes=frozenset({ADVISE_SCOPE}),
)


def _intent(
    *,
    port: str,
    recipient: str | None = ALICE_ID,
    interaction: ChannelInteraction = "advice",
) -> ChannelSendIntent:
    return ChannelSendIntent(
        message_id=request_message_id(
            run_id=RUN,
            path=PATH,
            channel_id=CHANNEL_ID,
            channel_revision="1",
            lane="review",
            interaction=interaction,
            port=port,
        ),
        channel_id=CHANNEL_ID,
        channel_revision="1",
        lane="review",
        interaction=interaction,
        recipient_actor_id=recipient,
        contract=REQUEST_CONTRACT,
        reply_contract=REPLY_CONTRACT,
        run_id=RUN,
        path=PATH,
        port=port,
        reply_port=f"{port}-answer",
        payload={"question": port},
    )


def _panel(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> tuple[ControlPlane, MailboxChannel]:
    """One control plane over one journal that already carries a channel."""

    journal = SqliteJournal(tmp_path / "channel-reads.db", now_fn=clock.now)
    return (
        ControlPlane(system=system, store=journal),
        MailboxChannel(journal, channel_id=CHANNEL_ID),
    )


def _ids(page: ChannelMessagePage | ControlRejected) -> list[str]:
    assert not isinstance(page, ControlRejected)
    return [str(item.message_id) for item in page.items]


def test_an_inbox_is_derived_from_the_authenticated_actor(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """No parameter names a recipient, so no caller can read another's queue."""

    control, review = _panel(tmp_path, clock, system)
    mine = review.append_request(_intent(port="mine"), ATTESTATION)
    theirs = review.append_request(_intent(port="theirs", recipient=BOB_ID), ATTESTATION)

    assert _ids(control.channels_inbox(ALICE)) == [str(mine.message_id)]
    assert _ids(control.channels_inbox(BOB)) == [str(theirs.message_id)]


def test_a_page_holds_only_the_interactions_the_actor_may_answer(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """Advising is not approving, and the request seals which this is."""

    control, review = _panel(tmp_path, clock, system)
    advice = review.append_request(_intent(port="advice"), ATTESTATION)
    approval = review.append_request(
        _intent(port="approval", interaction="approval"),
        ATTESTATION,
    )

    assert _ids(control.channels_inbox(ALICE_ADVISE_ONLY)) == [str(advice.message_id)]
    assert _ids(control.channels_inbox(ALICE)) == [
        str(advice.message_id),
        str(approval.message_id),
    ]


def test_an_actor_holding_no_channel_scope_is_refused_not_served_an_empty_page(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """An empty page would say "nothing is waiting", which is a different claim."""

    control, review = _panel(tmp_path, clock, system)
    review.append_request(_intent(port="advice"), ATTESTATION)

    refused = control.channels_inbox(READER)
    assert isinstance(refused, ControlRejected)
    assert refused.faults[0].code is ControlCode.AUTH_REQUIRED_SCOPE


def test_an_open_request_is_discoverable_under_its_own_interaction_scope(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """A request sealed to no one is work whoever holds the scope may take.

    Discovery still follows the sealed interaction, so an open approval is not
    an advisor's to find — and an addressed request stays private to its
    recipient even though an open one beside it is public.
    """

    control, review = _panel(tmp_path, clock, system)
    open_advice = review.append_request(_intent(port="open", recipient=None), ATTESTATION)
    open_approval = review.append_request(
        _intent(port="gate", recipient=None, interaction="approval"),
        ATTESTATION,
    )
    addressed = review.append_request(_intent(port="mine"), ATTESTATION)

    # Alice, holding advise alone: the open advice and her own, never the open
    # approval — an unsealed recipient widens who may find it, not what.
    assert _ids(control.channels_inbox(ADVISOR_ONLY)) == [
        str(open_advice.message_id),
        str(addressed.message_id),
    ]
    assert _ids(control.channels_inbox(ALICE)) == [
        str(open_advice.message_id),
        str(open_approval.message_id),
        str(addressed.message_id),
    ]
    # Bob is named by nothing here, so he finds the open pair and not Alice's.
    assert _ids(control.channels_inbox(BOB)) == [
        str(open_advice.message_id),
        str(open_approval.message_id),
    ]
    assert not isinstance(
        control.channels_message(BOB, open_advice.message_id),
        ControlRejected,
    )


def test_an_advisor_reads_its_own_work_and_nothing_else(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """The whole point of a distinct advise scope (I9).

    An advisor holding `constructicon:advise` alone reads its inbox and the
    detail that inbox handed it. Relaxing the detail door for that must not
    hand the same actor a run, an event, or a component — every other family
    still answers to read, now checked where it resolves.
    """

    control, review = _panel(tmp_path, clock, system)
    request = review.append_request(_intent(port="ask"), ATTESTATION)

    page = control.channels_inbox(ADVISOR_ONLY)
    assert _ids(page) == [str(request.message_id)]
    assert not isinstance(page, ControlRejected)
    assert not isinstance(control.details_read(ADVISOR_ONLY, page.items[0].detail), ControlRejected)

    for refused in (
        control.runs_list(ADVISOR_ONLY),
        control.runs_status(ADVISOR_ONLY, RUN),
        control.registry_rdeps(ADVISOR_ONLY, "test/triage"),
        control.resource_read(ADVISOR_ONLY, DetailAddress.manifest(RUN)),
        control.resource_read(ADVISOR_ONLY, DetailAddress.command("cmd-anything")),
        # The result alias is pinned to its terminal attempt before it resolves,
        # and pinning reads the journal. An unauthorized caller must be refused
        # before that read, or the refusal itself reports whether a run exists.
        control.resource_read(ADVISOR_ONLY, DetailAddress.result(RUN)),
    ):
        assert isinstance(refused, ControlRejected)
        assert refused.faults[0].code is ControlCode.AUTH_REQUIRED_SCOPE
        assert refused.faults[0].details == {"required_scope": READ_SCOPE}


def test_an_inbox_cursor_cannot_be_replayed_by_another_actor(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    control, review = _panel(tmp_path, clock, system)
    review.append_request(_intent(port="one"), ATTESTATION)
    review.append_request(_intent(port="two"), ATTESTATION)

    first = control.channels_inbox(ALICE, limit=1)
    assert not isinstance(first, ControlRejected)
    assert first.page.next_cursor is not None

    stolen = control.channels_inbox(BOB, limit=1, cursor=first.page.next_cursor)
    assert isinstance(stolen, ControlRejected)
    assert stolen.faults[0].code is ControlCode.CURSOR_QUERY_MISMATCH


def test_an_inbox_cursor_cannot_be_replayed_under_a_changed_scope_shape(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """The normalized authorized-interaction set is bound into the cursor.

    The same person paging with advise+approve and then re-presenting that
    cursor holding advise alone is asking a different question. Continuing it
    would silently narrow the page mid-stream and skip rows the first bound
    promised, so the honest answer is a refusal, not a shorter page.
    """

    control, review = _panel(tmp_path, clock, system)
    review.append_request(_intent(port="one", interaction="approval"), ATTESTATION)
    review.append_request(_intent(port="two"), ATTESTATION)

    first = control.channels_inbox(ALICE, limit=1)
    assert not isinstance(first, ControlRejected)
    assert first.page.next_cursor is not None

    narrowed = control.channels_inbox(
        ALICE_ADVISE_ONLY,
        limit=1,
        cursor=first.page.next_cursor,
    )
    assert isinstance(narrowed, ControlRejected)
    assert narrowed.faults[0].code is ControlCode.CURSOR_QUERY_MISMATCH


def test_a_forged_continuation_is_refused_rather_than_trusted(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """A cursor's checksum detects corruption, never forgery.

    Anyone can mint a structurally valid cursor, so every field it carries is
    re-validated: a continuation beyond the bound it claims to continue, and a
    cut ahead of retained history, are both refused instead of queried.
    """

    control, review = _panel(tmp_path, clock, system)
    request = review.append_request(_intent(port="one"), ATTESTATION)
    codec = CursorCodec()
    query = {"actor_id": ALICE_ID, "interactions": ["advice", "approval"]}

    beyond_its_own_bound = codec.encode(
        actor_id=ALICE_ID,
        kind="channel-inbox",
        query=query,
        upper_bound={"message_seq": 1, "ack_seq": 0},
        last_key=[99, str(request.message_id)],
    )
    ahead_of_history = codec.encode(
        actor_id=ALICE_ID,
        kind="channel-inbox",
        query=query,
        upper_bound={"message_seq": 9_000, "ack_seq": 0},
        last_key=[0, str(request.message_id)],
    )
    not_a_revision = codec.encode(
        actor_id=ALICE_ID,
        kind="channel-inbox",
        query=query,
        upper_bound=[1, 0],
        last_key=[0, str(request.message_id)],
    )

    for forged in (beyond_its_own_bound, ahead_of_history, not_a_revision):
        refused = control.channels_inbox(ALICE, cursor=forged)
        assert isinstance(refused, ControlRejected)
        assert refused.faults[0].code is ControlCode.CURSOR_INVALID


def test_a_sparse_inbox_pages_exactly_once_at_one_stable_cut(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """An actor's messages are sparse in a shared history, so position is durable.

    Counting page rows instead would redeliver, and a message appended after
    the first page must not appear beneath a reader already walking the cut.
    """

    control, review = _panel(tmp_path, clock, system)
    expected: list[str] = []
    for index in range(4):
        review.append_request(_intent(port=f"other-{index}", recipient=BOB_ID), ATTESTATION)
        expected.append(
            str(review.append_request(_intent(port=f"mine-{index}"), ATTESTATION).message_id)
        )

    seen: list[str] = []
    cursor: str | None = None
    while True:
        page = control.channels_inbox(ALICE, limit=1, cursor=cursor)
        assert not isinstance(page, ControlRejected)
        seen.extend(str(item.message_id) for item in page.items)
        cursor = page.page.next_cursor
        if cursor is None:
            break
        # Appended mid-walk: the cut this page fixed must not admit it.
        review.append_request(_intent(port=f"late-{len(seen)}"), ATTESTATION)

    assert seen == expected
    assert len(seen) == len(set(seen))


def test_a_reply_is_read_under_the_request_that_governs_it(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """A reply carries no recipient, so its authority is its request's seal."""

    control, review = _panel(tmp_path, clock, system)
    request = review.append_request(_intent(port="ask"), ATTESTATION)
    reply = review.reply(
        request_id=request.message_id,
        actor_id=ALICE_ID,
        payload={"verdict": "ship"},
        command_id="cmd-reply",
    )
    assert reply.recipient_actor_id is None

    served = control.channels_message(ALICE, reply.message_id)
    assert not isinstance(served, ControlRejected)
    assert served.kind == "reply"
    assert served.reply_to == request.message_id

    # A reply never lands in an inbox: it is addressed to the run, not a person.
    assert _ids(control.channels_inbox(ALICE)) == [str(request.message_id)]

    stranger = control.channels_message(BOB, reply.message_id)
    assert isinstance(stranger, ControlRejected)
    assert stranger.faults[0].code is ControlCode.AUTH_REQUIRED_SCOPE


def test_an_approval_message_is_not_readable_under_advise_scope(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    control, review = _panel(tmp_path, clock, system)
    approval = review.append_request(
        _intent(port="gate", interaction="approval"),
        ATTESTATION,
    )

    refused = control.channels_message(ALICE_ADVISE_ONLY, approval.message_id)
    assert isinstance(refused, ControlRejected)
    assert refused.faults[0].code is ControlCode.AUTH_REQUIRED_SCOPE
    assert refused.faults[0].details == {"required_scope": APPROVE_SCOPE}

    assert not isinstance(control.channels_message(ALICE, approval.message_id), ControlRejected)


def test_an_unknown_message_is_a_typed_refusal(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    control, _review = _panel(tmp_path, clock, system)
    absent = _intent(port="never-sent").message_id

    refused = control.channels_message(ALICE, absent)
    assert isinstance(refused, ControlRejected)
    assert refused.faults[0].code is ControlCode.CHANNEL_MESSAGE_UNKNOWN


def test_the_detail_resource_answers_to_the_same_authority_as_the_page(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """One law: a page's reference reads back, and a stranger's URI does not."""

    control, review = _panel(tmp_path, clock, system)
    request = review.append_request(_intent(port="ask"), ATTESTATION)
    page = control.channels_inbox(ALICE)
    assert not isinstance(page, ControlRejected)
    summary = page.items[0]

    chunk = control.details_read(ALICE, summary.detail)
    assert not isinstance(chunk, ControlRejected)
    assert chunk.text == canonical_json(json_value(request.model_dump(mode="json")))

    uri = DetailAddress.channel_message(request.message_id)
    assert summary.detail.uri == uri
    stranger = control.resource_read(BOB, uri)
    assert isinstance(stranger, ControlRejected)
    assert stranger.faults[0].code is ControlCode.AUTH_REQUIRED_SCOPE


def test_an_actor_with_no_channel_authority_is_refused_before_any_read(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """The addressed read gets the same door as the page.

    Deriving authority from the message means reading the message first, so an
    actor holding no channel authority at all would learn whether an id exists
    before being told the surface is not its to read. The door comes first.
    """

    control, review = _panel(tmp_path, clock, system)
    request = review.append_request(_intent(port="ask"), ATTESTATION)
    absent = _intent(port="never-sent").message_id

    for message_id in (request.message_id, absent):
        refused = control.channels_message(READER, message_id)
        assert isinstance(refused, ControlRejected)
        # Identical either way: a scopeless caller learns nothing about which.
        assert refused.faults[0].code is ControlCode.AUTH_REQUIRED_SCOPE
        assert refused.faults[0].details == {
            "required_scopes": [ADVISE_SCOPE, APPROVE_SCOPE]
        }
