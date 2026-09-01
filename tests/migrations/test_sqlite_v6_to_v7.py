"""M7 persistence: SQLite v6 gains explicit reply and ack provenance.

A v6 reply is not ownerless. The reply path *claimed* its request's
acknowledgement then, so that row already names the command that wrote the
reply. v7 records the same fact on the reply itself together with provenance
version 1. The read law falls back to the acknowledgement only when both new
columns are NULL and its message lies at or below the migration cutoff —
otherwise erasing a current writer would masquerade as history.
Acknowledgements are stamped as legacy below their own independently retained
cutoff; current facts are above it. An in-flight command
that crashed under v6 can still retry without losing a race it never entered.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.channel import (
    ChannelContract,
    ChannelMessageWriter,
    ChannelReplyConflict,
    ChannelSendIntent,
    message_for_reply,
    request_message_id,
)
from constructicon.core.control import (
    APPROVE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    CommandClaim,
    LegacyRunCreationPlan,
    RunCreationPlan,
    RunOrigin,
    StoredRunCreationPlan,
    approval_id_for_command,
    command_request_hash,
    run_id_for_command,
)
from constructicon.core.effect import (
    ApprovalRecord,
    AttestationDraft,
    CheckResult,
    ComponentProofSubject,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.human import (
    APPROVAL_REPLY_CONTRACT,
    APPROVAL_REQUEST_CONTRACT,
    ApprovalDecisionPayload,
    ApprovalRequestPayload,
    ChannelApprovalPlan,
    StoredApprovalPlan,
    approval_decision_payload,
)
from constructicon.core.identity import Digest, canonical_json, digest, json_value
from constructicon.substrate.journal._sqlite_attestations import seal_attestation
from constructicon.substrate.journal._sqlite_channels import (
    _insert_message,
    channel_message_fact_hash,
)
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal
from tests.channel_commands import (
    ack_command_id,
    ack_with_command,
    prepare_ack_command,
    reply_command_id,
    reply_with_command,
)
from tests.channel_requests import AttestedMailboxChannel as MailboxChannel
from tests.conftest import FakeClock
from tests.durable_seals import reseal_primary_fact
from tests.run_attestations import mint_promotion_attestation, mint_run_attestation
from tests.run_worlds import sealed_test_manifest

CHANNEL_ID = "channel/legacy"
ADVISOR = "static:legacy-advisor"
RUN = RunId("run-v6-legacy")
PATH = ExecutionPath(scope=ScopePath(segments=("review",)))
CONTRACT = ChannelContract(type_id="test/Ask", schema_hash="ask-v1")
REPLY_CONTRACT = ChannelContract(type_id="test/Answer", schema_hash="answer-v1")
WRITER = "cmd-v6-writer"
APPROVER = AuthenticatedActor(
    actor_id="static:legacy-approver",
    auth_method="static",
    scopes=frozenset({APPROVE_SCOPE, READ_SCOPE}),
)
SUBJECT = ComponentProofSubject(
    component="test/legacy-triage",
    version=Digest("sha256:" + "a" * 64),
    baseline_version=None,
)


def _intent() -> ChannelSendIntent:
    return ChannelSendIntent(
        message_id=request_message_id(
            run_id=RUN,
            path=PATH,
            channel_id=CHANNEL_ID,
            channel_revision="1",
            lane="review",
            interaction="advice",
            port="request",
        ),
        channel_id=CHANNEL_ID,
        channel_revision="1",
        lane="review",
        interaction="advice",
        recipient_actor_id=ADVISOR,
        contract=CONTRACT,
        reply_contract=REPLY_CONTRACT,
        run_id=RUN,
        path=PATH,
        port="request",
        reply_port="reply",
        payload={"question": "ship?"},
    )


def _approval_intent() -> ChannelSendIntent:
    path = ExecutionPath(scope=ScopePath(segments=("approval",)))
    return ChannelSendIntent(
        message_id=request_message_id(
            run_id=RUN,
            path=path,
            channel_id=CHANNEL_ID,
            channel_revision="1",
            lane="approval",
            interaction="approval",
            port="request",
        ),
        channel_id=CHANNEL_ID,
        channel_revision="1",
        lane="approval",
        interaction="approval",
        recipient_actor_id=APPROVER.actor_id,
        contract=APPROVAL_REQUEST_CONTRACT,
        reply_contract=APPROVAL_REPLY_CONTRACT,
        run_id=RUN,
        path=path,
        port="request",
        reply_port="decision",
        payload=ApprovalRequestPayload(
            subject=json_value(SUBJECT.model_dump(mode="json")),
        ).model_dump(mode="json"),
    )


def _dump(database: Path) -> dict[str, list[tuple[object, ...]]]:
    with sqlite3.connect(database) as connection:
        tables = sorted(
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        )
        return {
            table: sorted(
                tuple(row) for row in connection.execute(f"SELECT * FROM {table}").fetchall()
            )
            for table in tables
        }


def _downgrade_v7_schema_to_v6(database: Path) -> None:
    """Restore the exact pre-v7 relational shape used by the branch writer.

    The schema-6 developer-branch command law already stored the same schema-1
    plan envelope used here. Keeping those bytes while removing only v7
    relational provenance models that exact branch-SHA history; a bare inner
    plan was never the durable command record.  The v7 effect pointers and
    migration seals are absent too: leaving them behind would only test a
    partially rewound current database, not the migration source.
    """

    with sqlite3.connect(database) as connection:
        connection.execute("DROP INDEX channel_reply_command_unique")
        connection.execute("ALTER TABLE channel_messages DROP COLUMN reply_provenance_version")
        connection.execute("ALTER TABLE channel_messages DROP COLUMN command_id")
        connection.execute("ALTER TABLE channel_acks DROP COLUMN ack_provenance_version")
        connection.execute("DROP TABLE channel_provenance")
        connection.execute("ALTER TABLE effects DROP COLUMN outcome_run_id")
        connection.execute("ALTER TABLE effects DROP COLUMN outcome_event_seq")
        connection.execute("DROP TABLE legacy_effect_seals")
        connection.execute("DROP TABLE legacy_capability_lease_seals")
        connection.execute("ALTER TABLE runs DROP COLUMN creation_command_id")
        connection.execute("DROP TABLE durable_fact_seals")
        connection.execute("PRAGMA user_version = 6")
        connection.commit()


def _rebuild_v6_ack_sequence(database: Path, *, storage_type: str) -> None:
    """Model a damaged schema-6 table whose sequence has lost integer storage."""

    with sqlite3.connect(database) as connection:
        columns = [str(row[1]) for row in connection.execute("PRAGMA table_info(channel_acks)")]
        connection.execute("ALTER TABLE channel_acks RENAME TO exact_channel_acks")
        connection.execute(f"CREATE TABLE channel_acks ({', '.join(columns)})")
        projected = [
            f"CAST(ack_seq AS {storage_type})" if column == "ack_seq" else column
            for column in columns
        ]
        connection.execute(
            f"INSERT INTO channel_acks ({', '.join(columns)}) "
            f"SELECT {', '.join(projected)} FROM exact_channel_acks"
        )
        connection.execute("DROP TABLE exact_channel_acks")


@pytest.mark.parametrize(
    ("family", "message"),
    (
        ("unknown_migration_family", "family .* is unknown"),
        ("approval", "orphan or missing primary fact"),
    ),
)
def test_v6_migration_refuses_unmapped_durable_fact_seals_atomically(
    family: str,
    message: str,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"orphan-{family}.db"
    SqliteJournal(database)
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE durable_fact_seals ("
            " family TEXT NOT NULL, fact_key TEXT NOT NULL,"
            " selector TEXT NOT NULL, fact_hash TEXT NOT NULL,"
            " PRIMARY KEY (family, fact_key), UNIQUE (family, selector))"
        )
        connection.execute(
            "INSERT INTO durable_fact_seals VALUES (?, ?, ?, ?)",
            (
                family,
                "orphan-fact",
                "orphan-selector",
                str(digest("orphan-durable-fact-seal", 1, {"family": family})),
            ),
        )

    with pytest.raises(JournalDamaged, match=message):
        SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert connection.execute("SELECT family, fact_key FROM durable_fact_seals").fetchall() == [
            (family, "orphan-fact")
        ]


def test_v6_migration_reconciles_a_valid_partial_fact_seal_inventory(
    tmp_path: Path,
) -> None:
    database = tmp_path / "partial-fact-seal.db"
    journal = SqliteJournal(database)
    attestation = mint_promotion_attestation(
        journal,
        component="migration/partial-seal",
        version=Digest("sha256:" + "b" * 64),
        baseline=None,
        proof="partial-seal",
    )
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE durable_fact_seals ("
            " family TEXT NOT NULL, fact_key TEXT NOT NULL,"
            " selector TEXT NOT NULL, fact_hash TEXT NOT NULL,"
            " PRIMARY KEY (family, fact_key), UNIQUE (family, selector))"
        )
        row = connection.execute(
            "SELECT * FROM attestations WHERE attestation_id = ?",
            (attestation.attestation_id,),
        ).fetchone()
        assert row is not None
        seal_attestation(connection, row)

    migrated = SqliteJournal(database)
    assert migrated.load_attestation(attestation.attestation_id) == attestation
    with sqlite3.connect(database) as connection:
        assert set(
            connection.execute("SELECT family, fact_key FROM durable_fact_seals").fetchall()
        ) == {
            ("attestation", attestation.attestation_id),
            ("channel_provenance", "1"),
        }


def test_v6_migration_seals_a_content_derived_creator_after_its_run_world(
    tmp_path: Path,
) -> None:
    database = tmp_path / "content-derived-creator.db"
    journal = SqliteJournal(database)
    manifest = sealed_test_manifest()
    creator = RunId("run-v6-content-derived-creator")
    version = digest("component", 1, {"migration": "creator-order"})
    attestation = mint_run_attestation(
        journal,
        creator,
        AttestationDraft(
            action="promote",
            subject=ComponentProofSubject(
                component="migration/creator-order",
                version=version,
                baseline_version=None,
            ),
            checks=(
                CheckResult(
                    name="creator-order",
                    status="passed",
                    detail="creator run world predates its proof",
                    elapsed_s=0.0,
                ),
            ),
            check_set_hash=digest("check-set", 1, {"migration": "creator-order"}),
            manifest_hash=manifest.manifest_hash,
        ),
    )
    assert attestation.created_by_run == creator
    _downgrade_v7_schema_to_v6(database)

    migrated = SqliteJournal(database)

    assert migrated.load_attestation(attestation.attestation_id) == attestation
    assert migrated.run_manifest_hash(creator) == attestation.manifest_hash
    with sqlite3.connect(database) as connection:
        families = {
            row[0]
            for row in connection.execute(
                "SELECT family FROM durable_fact_seals WHERE fact_key IN (?, ?, ?)",
                (
                    str(manifest.manifest_hash),
                    str(creator),
                    attestation.attestation_id,
                ),
            )
        }
    assert {"manifest", "run_world", "attestation"} <= families


def _seed_genuine_v6(database: Path, clock: FakeClock) -> tuple[str, str]:
    """One request and its reply, stored exactly as v6 stored them.

    The v7 columns are dropped after the write, so the reply carries no writer
    of its own — only the acknowledgement does, which is the v6 arrangement.
    """

    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), "att-v6")
    # Seed the exact historical bytes directly. Schema 6 had no reply command
    # column or acknowledgement provenance marker and did not require a command
    # row; its ack was the only durable writer identity. A migration fixture
    # must not invent current provenance merely to pass through today's writer.
    reply = message_for_reply(
        request,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        created_at=clock.now(),
    )
    with journal._txn() as connection:
        _insert_message(connection, reply, None, WRITER)
        connection.execute(
            "INSERT INTO channel_acks (message_id, actor_id, command_id, acked_at,"
            " ack_provenance_version) VALUES (?, ?, ?, ?, NULL)",
            (
                str(request.message_id),
                ADVISOR,
                WRITER,
                clock.now().isoformat(),
            ),
        )
    _downgrade_v7_schema_to_v6(database)
    return str(request.message_id), str(reply.message_id)


def test_v6_to_v7_adds_exact_provenance_without_rewriting_historical_content(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    database = tmp_path / "v6.db"
    _seed_genuine_v6(database, clock)
    before = _dump(database)

    SqliteJournal(database, now_fn=clock.now)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        columns = {row[1] for row in connection.execute("PRAGMA table_info(channel_messages)")}
        acknowledgement_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(channel_acks)")
        }
        reply_command_index = next(
            row
            for row in connection.execute("PRAGMA index_list(channel_messages)")
            if row[1] == "channel_reply_command_unique"
        )
        reply_command_index_columns = [
            row[2] for row in connection.execute("PRAGMA index_info(channel_reply_command_unique)")
        ]
        reply_command_index_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index'"
            " AND name = 'channel_reply_command_unique'"
        ).fetchone()
    assert "command_id" in columns
    assert "reply_provenance_version" in columns
    assert "ack_provenance_version" in acknowledgement_columns
    assert reply_command_index[2] == 1  # unique
    assert reply_command_index[4] == 1  # partial: historical NULLs remain unconstrained
    assert reply_command_index_columns == ["command_id"]
    assert reply_command_index_sql is not None
    assert str(reply_command_index_sql[0]).endswith("WHERE command_id IS NOT NULL")

    after = _dump(database)
    assert set(after) == set(before) | {
        "channel_provenance",
        "durable_fact_seals",
        "legacy_capability_lease_seals",
        "legacy_effect_seals",
    }
    for table, rows in before.items():
        if table == "channel_messages":
            # Every historical value survives; only two NULLs are appended.
            assert [row[:-2] for row in after[table]] == rows
            assert all(row[-2:] == (None, None) for row in after[table])
        elif table == "channel_acks":
            assert [row[:-1] for row in after[table]] == rows
            assert all(row[-1] == 0 for row in after[table])
        elif table == "effects":
            assert [row[:-2] for row in after[table]] == rows
            assert all(row[-2:] == (None, None) for row in after[table])
        elif table == "runs":
            # The positive creation-command marker is additive. This
            # originless historical run therefore receives one NULL.
            assert [row[:-1] for row in after[table]] == rows
            assert all(row[-1] is None for row in after[table])
        else:
            assert after[table] == rows
    assert after["channel_provenance"] == [(1, 1, 2)]
    assert after["legacy_capability_lease_seals"] == []


def test_a_current_reply_cannot_downgrade_through_a_migrated_opaque_preack(
    tmp_path: Path,
) -> None:
    """The message-era cutoff distinguishes history from erased current proof."""

    clock = FakeClock()
    database = tmp_path / "v6-preack-current-reply.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), "att-v6-preack")
    with journal._txn() as connection:
        connection.execute(
            "INSERT INTO channel_acks (message_id, actor_id, command_id, acked_at,"
            " ack_provenance_version) VALUES (?, ?, ?, ?, NULL)",
            (
                str(request.message_id),
                ADVISOR,
                "opaque-v6-preack",
                clock.now().isoformat(),
            ),
        )
    _downgrade_v7_schema_to_v6(database)

    migrated = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(migrated, channel_id=CHANNEL_ID)
    reply = reply_with_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="current-over-v6-preack",
    )
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        cutoff = connection.execute(
            "SELECT legacy_ack_through, legacy_message_through"
            " FROM channel_provenance WHERE singleton = 1"
        ).fetchone()
        reply_seq = connection.execute(
            "SELECT message_seq FROM channel_messages WHERE message_id = ?",
            (str(reply.message_id),),
        ).fetchone()
        assert tuple(cutoff) == (1, 1)
        assert tuple(reply_seq) == (2,)
        connection.execute(
            "UPDATE channel_messages SET command_id = NULL,"
            " reply_provenance_version = NULL WHERE message_id = ?",
            (str(reply.message_id),),
        )
        row = connection.execute(
            "SELECT * FROM channel_messages WHERE message_id = ?",
            (str(reply.message_id),),
        ).fetchone()
        assert row is not None
        reseal_primary_fact(
            connection,
            family="channel_message",
            fact_key=str(reply.message_id),
            fact=channel_message_fact_hash(row),
        )
        connection.commit()

    for read in (
        lambda: mailbox.reply_for(request.message_id),
        lambda: migrated.answered_requests((request.message_id,)),
    ):
        with pytest.raises(JournalDamaged, match="invalid provenance era"):
            read()


def test_current_open_reproves_a_reply_writer_over_a_migrated_opaque_preack(
    tmp_path: Path,
) -> None:
    """A v0 ack cannot make a current reply's own command reference optional."""

    clock = FakeClock()
    database = tmp_path / "v6-preack-current-writer.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), "att-v6-preack-writer")
    with journal._txn() as connection:
        connection.execute(
            "INSERT INTO channel_acks (message_id, actor_id, command_id, acked_at,"
            " ack_provenance_version) VALUES (?, ?, ?, ?, NULL)",
            (
                str(request.message_id),
                ADVISOR,
                "opaque-v6-preack-writer",
                clock.now().isoformat(),
            ),
        )
    _downgrade_v7_schema_to_v6(database)

    migrated = SqliteJournal(database, now_fn=clock.now)
    current = MailboxChannel(migrated, channel_id=CHANNEL_ID)
    key = "current-writer-over-v6-preack"
    reply_with_command(
        current,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key=key,
    )
    writer = reply_command_id(ADVISOR, key)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM durable_fact_seals WHERE fact_key = ?"
            " AND family IN ('command_claim', 'command_plan', 'command_terminal')",
            (writer,),
        )
        connection.execute("DELETE FROM commands WHERE command_id = ?", (writer,))

    with pytest.raises(
        JournalDamaged,
        match=r"missing command|missing behind a dependent durable fact",
    ):
        SqliteJournal(database, now_fn=clock.now)


def test_a_v6_reply_that_merely_looks_like_a_decision_is_not_one(
    tmp_path: Path,
) -> None:
    """What settles a legacy reply is the ledger, not the shape of its bytes.

    A payload test would classify this row as an approval and then demand the
    decision record its era never wrote — the same permanent migration abort,
    surviving in whatever subset of history happens to match today's model. It
    would also move: change the model that reads these bytes and the same
    history is classified differently on the next release.
    """

    clock = FakeClock()
    database = tmp_path / "v6-lookalike-decision.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_approval_intent(), "att-v6-lookalike")
    lookalike = ApprovalDecisionPayload(
        approval=ApprovalRecord(
            approval_id="apv-v6-lookalike",
            subject=SUBJECT,
            decision="approved",
            reason=None,
            actor=APPROVER,
            run_id=RUN,
            created_at=clock.now(),
        )
    ).model_dump(mode="json")
    reply = message_for_reply(
        request,
        actor_id=APPROVER.actor_id,
        payload=json_value(lookalike),
        created_at=clock.now(),
    )
    with journal._txn() as connection:
        _insert_message(connection, reply, None, WRITER)
        connection.execute(
            "INSERT INTO channel_acks (message_id, actor_id, command_id, acked_at,"
            " ack_provenance_version) VALUES (?, ?, ?, ?, NULL)",
            (
                str(request.message_id),
                APPROVER.actor_id,
                WRITER,
                clock.now().isoformat(),
            ),
        )
    _downgrade_v7_schema_to_v6(database)

    migrated = SqliteJournal(database, now_fn=clock.now)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

    projected = MailboxChannel(migrated, channel_id=CHANNEL_ID).reply_for(request.message_id)
    assert projected is not None
    assert projected.message_id == reply.message_id
    # No approval was minted, so none is claimed for it.
    assert migrated.approval("apv-v6-lookalike") is None


def test_a_v6_approval_interaction_reply_predates_the_decision_law(
    tmp_path: Path,
) -> None:
    """A reply older than the approval ledger is not a broken approval.

    Schema 6 sealed `interaction='approval'` long before a decision could be
    recorded against it, so its replies carry whatever their answerer wrote.
    Holding one to a law younger than itself is not a discovery of damage: the
    migration aborts, `user_version` stays at 6, and — since ADR 0016 forbids
    healing on open — the store can never be opened again.
    """

    clock = FakeClock()
    database = tmp_path / "v6-approval-interaction.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_approval_intent(), "att-v6-approval-era")
    reply = message_for_reply(
        request,
        actor_id=APPROVER.actor_id,
        payload={"decision": "approved"},
        created_at=clock.now(),
    )
    with journal._txn() as connection:
        _insert_message(connection, reply, None, WRITER)
        connection.execute(
            "INSERT INTO channel_acks (message_id, actor_id, command_id, acked_at,"
            " ack_provenance_version) VALUES (?, ?, ?, ?, NULL)",
            (
                str(request.message_id),
                APPROVER.actor_id,
                WRITER,
                clock.now().isoformat(),
            ),
        )
    _downgrade_v7_schema_to_v6(database)

    migrated = SqliteJournal(database, now_fn=clock.now)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

    # And it reads back as what it is: an ordinary reply from before the law.
    projected = MailboxChannel(migrated, channel_id=CHANNEL_ID).reply_for(request.message_id)
    assert projected is not None
    assert projected.message_id == reply.message_id
    assert projected.envelope.payload == {"decision": "approved"}


@pytest.mark.parametrize("storage_type", ("TEXT", "REAL"))
def test_v6_to_v7_never_normalizes_a_damaged_ack_sequence(
    storage_type: str,
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    database = tmp_path / f"v6-ack-sequence-{storage_type.lower()}.db"
    _seed_genuine_v6(database, clock)
    _rebuild_v6_ack_sequence(database, storage_type=storage_type)

    with pytest.raises(JournalDamaged, match="sequence history is damaged"):
        SqliteJournal(database, now_fn=clock.now)


def test_a_partly_climbed_v7_migration_adds_only_the_missing_provenance_column(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    database = tmp_path / "partial-v7.db"
    _seed_genuine_v6(database, clock)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE channel_messages ADD COLUMN command_id TEXT")
        connection.commit()

    SqliteJournal(database, now_fn=clock.now)
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(channel_messages)")}
        acknowledgement_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(channel_acks)")
        }
        rows = connection.execute(
            "SELECT command_id, reply_provenance_version FROM channel_messages"
        ).fetchall()
    assert {"command_id", "reply_provenance_version"} <= columns
    assert "ack_provenance_version" in acknowledgement_columns
    assert rows and all(tuple(row) == (None, None) for row in rows)


def test_a_current_v7_database_never_repairs_a_missing_run_provenance_column(
    tmp_path: Path,
) -> None:
    database = tmp_path / "erased-run-provenance.db"
    SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE runs DROP COLUMN creation_command_id")

    with pytest.raises(
        JournalDamaged,
        match="creation-command provenance column",
    ):
        SqliteJournal(database)


@pytest.mark.parametrize(
    "statements",
    (
        ("DROP TABLE channel_provenance",),
        ("ALTER TABLE channel_messages DROP COLUMN reply_provenance_version",),
        ("ALTER TABLE channel_acks DROP COLUMN ack_provenance_version",),
        (
            "DROP INDEX channel_reply_command_unique",
            "ALTER TABLE channel_messages DROP COLUMN command_id",
        ),
        ("DROP INDEX channel_reply_command_unique",),
    ),
)
def test_current_v7_never_repairs_missing_channel_provenance(
    statements: tuple[str, ...],
    tmp_path: Path,
) -> None:
    database = tmp_path / f"missing-channel-provenance-{len(statements)}.db"
    SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        for statement in statements:
            connection.execute(statement)

    with pytest.raises(
        JournalDamaged,
        match=r"channel (?:reply )?provenance|durable tables",
    ):
        SqliteJournal(database)


@pytest.mark.parametrize(
    ("column", "declaration", "value"),
    (
        ("command_id", "TEXT", "cmd-impossible-v6-writer"),
        ("reply_provenance_version", "INTEGER", 1),
    ),
)
def test_v6_to_v7_refuses_current_reply_provenance_atomically(
    column: str,
    declaration: str,
    value: object,
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    database = tmp_path / f"v6-current-{column}.db"
    _seed_genuine_v6(database, clock)
    with sqlite3.connect(database) as connection:
        connection.execute(f"ALTER TABLE channel_messages ADD COLUMN {column} {declaration}")
        connection.execute(
            f"UPDATE channel_messages SET {column} = ? WHERE reply_to IS NOT NULL",
            (value,),
        )
    before = _dump(database)

    with pytest.raises(JournalDamaged, match="schema 6 channel reply"):
        SqliteJournal(database, now_fn=clock.now)
    assert _dump(database) == before


def test_an_origin_bearing_historical_run_keeps_its_exact_bare_creation_plan(
    tmp_path: Path,
) -> None:
    """The pre-envelope `{run_id, manifest, inputs, origin}` bytes remain readable."""

    database = tmp_path / "legacy-run-creation-plan.db"
    journal = SqliteJournal(database)
    actor = AuthenticatedActor(
        actor_id="static:legacy-run-creator",
        auth_method="static",
        scopes=frozenset(),
    )
    manifest = sealed_test_manifest()
    request = {
        "proposal": manifest.source_graph.model_dump(mode="json"),
        "inputs": {},
    }
    claimed = journal.claim_command(
        actor=actor,
        operation="runs_start",
        idempotency_key="legacy-run-creation-plan",
        request_hash=command_request_hash(request),
        request=request,
        owner_id="test:legacy-run-creator",
        ttl_s=30,
    )
    assert claimed.claim is not None
    run_id = run_id_for_command(claimed.claim.command_id)
    origin = RunOrigin(
        kind="start",
        actor_id=actor.actor_id,
        command_id=claimed.claim.command_id,
    )
    plan = RunCreationPlan(
        run_id=run_id,
        manifest=manifest,
        inputs={},
        origin=origin,
    )
    journal.store_command_plan(
        claimed.claim,
        StoredRunCreationPlan(plan=plan).model_dump(mode="json"),
    )
    journal.create_run(
        run_id,
        manifest_json=manifest.model_dump_json(),
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs={},
        origin=origin,
    )
    _downgrade_v7_schema_to_v6(database)
    legacy = LegacyRunCreationPlan(
        run_id=run_id,
        manifest=manifest,
        inputs={},
        origin=origin,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (
                canonical_json(legacy.model_dump(mode="json")),
                claimed.claim.command_id,
            ),
        )

    migrated = SqliteJournal(database)
    assert migrated.run_origin(run_id) == origin
    assert migrated.run_manifest_hash(run_id) == manifest.manifest_hash


def test_a_command_backed_v6_ack_keeps_its_exact_command_provenance(
    tmp_path: Path,
) -> None:
    """Migration-era commands remain evidence; v0 does not mean ownerless."""

    clock = FakeClock()
    database = tmp_path / "command-backed-ack.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), "att-v6-command")
    ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key="v6-command-backed-ack",
    )
    expected_command_id = ack_command_id(ADVISOR, "v6-command-backed-ack")
    before_migration = journal.channel_ack(
        message_id=request.message_id,
        actor_id=ADVISOR,
    )
    assert before_migration is not None
    assert before_migration.command_id == expected_command_id

    _downgrade_v7_schema_to_v6(database)

    migrated = SqliteJournal(database, now_fn=clock.now)
    stored = migrated.channel_ack(message_id=request.message_id, actor_id=ADVISOR)
    assert stored is not None
    assert stored.command_id == expected_command_id
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT ack_seq, ack_provenance_version FROM channel_acks"
            " WHERE message_id = ? AND actor_id = ?",
            (str(request.message_id), ADVISOR),
        ).fetchone()
        cutoff = connection.execute(
            "SELECT legacy_ack_through FROM channel_provenance WHERE singleton = 1"
        ).fetchone()
    assert row is not None
    assert cutoff is not None
    assert tuple(row) == (1, 0)
    assert tuple(cutoff) == (1,)

    # Migration changes the provenance era, not authorship. A surviving v6
    # command still cannot claim rejection after its positive-v0 delivery fact
    # says the mutation happened.
    command = migrated.command(expected_command_id)
    assert command is not None
    assert command.owner_id is not None
    assert command.lease_expires_at is not None
    claim = CommandClaim(
        command_id=command.command_id,
        actor_id=command.actor.actor_id,
        operation=command.operation,
        owner_id=command.owner_id,
        epoch=command.owner_epoch,
        expires_at=command.lease_expires_at,
    )
    with pytest.raises(
        JournalDamaged,
        match="cannot be rejected after writing a channel acknowledgement",
    ):
        migrated.reject_command(claim, {"status": "rejected"})
    assert migrated.command(expected_command_id) == command
    assert migrated.channel_ack(message_id=request.message_id, actor_id=ADVISOR) == stored


def test_a_v0_ack_never_attaches_to_a_later_command_with_the_same_id(
    tmp_path: Path,
) -> None:
    """Its writer string is historical data, not a current command relation."""

    clock = FakeClock()
    database = tmp_path / "opaque-ack-command-collision.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), "att-v6-opaque-ack")
    key = "v6-opaque-ack-collision"
    historical_writer = ack_command_id(ADVISOR, key)
    with journal._txn() as connection:
        connection.execute(
            "INSERT INTO channel_acks (message_id, actor_id, command_id, acked_at,"
            " ack_provenance_version) VALUES (?, ?, ?, ?, NULL)",
            (
                str(request.message_id),
                ADVISOR,
                historical_writer,
                clock.now().isoformat(),
            ),
        )
    _downgrade_v7_schema_to_v6(database)

    migrated = SqliteJournal(database, now_fn=clock.now)
    reopened = MailboxChannel(migrated, channel_id=CHANNEL_ID)
    other_intent = _intent().model_copy(
        update={
            "message_id": request_message_id(
                run_id=RUN,
                path=PATH,
                channel_id=CHANNEL_ID,
                channel_revision="1",
                lane="review",
                interaction="advice",
                port="other-request",
            ),
            "port": "other-request",
        }
    )
    other = reopened.append_request(other_intent, "att-current-other-request")
    assert (
        prepare_ack_command(
            reopened,
            message_id=other.message_id,
            actor_id=ADVISOR,
            idempotency_key=key,
        )
        == historical_writer
    )

    stored = migrated.channel_ack(
        message_id=request.message_id,
        actor_id=ADVISOR,
    )
    assert stored is not None
    assert stored.command_id == historical_writer
    assert stored.provenance_version == 0


def test_a_command_backed_v6_reply_keeps_its_two_historical_observations(
    tmp_path: Path,
) -> None:
    """Schema 6 observed reply and ack separately; migration must not invent equality."""

    clock = FakeClock()
    database = tmp_path / "command-backed-reply.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_intent(), "att-v6-command-reply")
    key = "v6-command-backed-reply"
    reply = reply_with_command(
        channel,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key=key,
    )
    clock.advance(1)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE channel_acks SET acked_at = ? WHERE message_id = ? AND actor_id = ?",
            (clock.now().isoformat(), str(request.message_id), ADVISOR),
        )

    _downgrade_v7_schema_to_v6(database)

    migrated = SqliteJournal(database, now_fn=clock.now)
    reopened = MailboxChannel(migrated, channel_id=CHANNEL_ID)
    assert reopened.reply_for(request.message_id) == reply
    assert migrated.answered_requests([request.message_id]) == {
        request.message_id: reply.message_id
    }
    acknowledgement = migrated.channel_ack(
        message_id=request.message_id,
        actor_id=ADVISOR,
    )
    assert acknowledgement is not None
    assert acknowledgement.command_id == reply_command_id(ADVISOR, key)
    assert acknowledgement.provenance_version == 0
    assert acknowledgement.ack.acked_at != reply.envelope.created_at


def test_a_request_bound_v6_approval_keeps_its_exact_three_fact_exchange(
    tmp_path: Path,
) -> None:
    """The schema-6 PR-C history already admitted transactional approvals."""

    clock = FakeClock()
    database = tmp_path / "request-bound-approval.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(_approval_intent(), "att-v6-approval")
    command_request = {
        "run_id": str(RUN),
        "subject": json_value(SUBJECT.model_dump(mode="json")),
        "decision": "approved",
        "reason": None,
        "request_message_id": str(request.message_id),
    }
    claimed = journal.claim_command(
        actor=APPROVER,
        operation="runs_approve",
        idempotency_key="v6-request-bound-approval",
        request_hash=command_request_hash(command_request),
        request=command_request,
        owner_id="test:v6-request-bound-approval",
        ttl_s=30,
    )
    assert claimed.claim is not None
    approval = ApprovalRecord(
        approval_id=approval_id_for_command(
            claimed.claim.command_id,
            json_value(SUBJECT.model_dump(mode="json")),
        ),
        subject=SUBJECT,
        decision="approved",
        reason=None,
        actor=APPROVER,
        run_id=RUN,
        created_at=clock.now(),
    )
    assert request.reply_port is not None
    plan = ChannelApprovalPlan(
        approval=approval,
        channel_id=request.channel_id,
        request_id=request.message_id,
        reply_id=message_for_reply(
            request,
            actor_id=APPROVER.actor_id,
            payload=approval_decision_payload(approval),
            created_at=clock.now(),
        ).message_id,
        reply_port=request.reply_port,
        payload=approval_decision_payload(approval),
        ack_actor_id=APPROVER.actor_id,
        run_id=RUN,
        parked_event_seq=journal.max_event_seq(RUN),
    )
    journal.store_command_plan(
        claimed.claim,
        StoredApprovalPlan(plan=plan).model_dump(mode="json"),
    )
    reply = journal.store_approval_exchange(
        claimed.claim,
        approval,
        channel_id=CHANNEL_ID,
        request_id=request.message_id,
        payload=approval_decision_payload(approval),
    )
    clock.advance(1)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE channel_acks SET acked_at = ? WHERE message_id = ? AND actor_id = ?",
            (clock.now().isoformat(), str(request.message_id), APPROVER.actor_id),
        )
        # The schema-6 writer serialized frozenset iteration order.  Retain one
        # genuine unsorted multi-scope command and approval actor exactly as an
        # older process could have emitted it.
        for table in ("commands", "approvals"):
            raw_actor = connection.execute(
                f"SELECT actor_json FROM {table} WHERE command_id = ?",
                (claimed.claim.command_id,),
            ).fetchone()
            assert raw_actor is not None
            actor_json = json.loads(raw_actor[0])
            actor_json["scopes"] = list(reversed(actor_json["scopes"]))
            assert actor_json["scopes"] != sorted(actor_json["scopes"])
            connection.execute(
                f"UPDATE {table} SET actor_json = ? WHERE command_id = ?",
                (
                    json.dumps(actor_json, separators=(",", ":")),
                    claimed.claim.command_id,
                ),
            )

    _downgrade_v7_schema_to_v6(database)

    migrated = SqliteJournal(database, now_fn=clock.now)
    reopened = MailboxChannel(migrated, channel_id=CHANNEL_ID)
    assert migrated.approval(approval.approval_id) == approval
    with sqlite3.connect(database) as connection:
        assert {
            row[0]
            for row in connection.execute(
                "SELECT family FROM durable_fact_seals"
                " WHERE (family = 'command_claim' AND fact_key = ?)"
                " OR (family = 'approval' AND fact_key = ?)",
                (claimed.claim.command_id, approval.approval_id),
            )
        } == {"command_claim", "approval"}
    assert reopened.reply_for(request.message_id) == reply
    assert migrated.answered_requests([request.message_id]) == {
        request.message_id: reply.message_id
    }
    acknowledgement = migrated.channel_ack(
        message_id=request.message_id,
        actor_id=APPROVER.actor_id,
    )
    assert acknowledgement is not None
    assert acknowledgement.provenance_version == 0
    assert acknowledgement.ack.acked_at != reply.envelope.created_at


def test_a_v6_reply_still_reconciles_for_the_command_that_wrote_it(tmp_path: Path) -> None:
    """Its writer lives in the acknowledgement, so an exact retry is not a race."""

    clock = FakeClock()
    database = tmp_path / "retry.db"
    request_id, reply_id = _seed_genuine_v6(database, clock)

    journal = SqliteJournal(database, now_fn=clock.now)
    assert journal.channel_message_writer(  # type: ignore[arg-type]
        message_id=reply_id
    ) == ChannelMessageWriter(command_id=WRITER, era="legacy")

    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    clock.advance(600)
    replayed = channel.reply(
        request_id=request_id,  # type: ignore[arg-type]
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        command_id=WRITER,
    )
    assert str(replayed.message_id) == reply_id
    assert journal.channel_actor_revision(actor_id=ADVISOR).message_seq == 2  # no third message


def test_a_v6_reply_still_refuses_a_different_command(tmp_path: Path) -> None:
    clock = FakeClock()
    database = tmp_path / "loser.db"
    request_id, _reply_id = _seed_genuine_v6(database, clock)

    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    with pytest.raises(ChannelReplyConflict, match="already answered by another command"):
        channel.reply(
            request_id=request_id,  # type: ignore[arg-type]
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            command_id="cmd-someone-else",
        )
