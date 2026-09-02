"""The migration witnesses domain plans older than their exact proofs.

Two shapes are older than the laws that now judge them: a registry promotion
plan with no `terminal_rejection_policy`, and a cancellation that found its run
already terminal with no `observed_event_seq`. Neither field exists on `main`,
so genuine schema-6 history holds exactly these shapes.

The same bytes are also what a downgrade after the fact looks like, and the
repo's anti-forgery tests are right to refuse those. What tells the two apart
is a witness only the migration can write: legacy shape with a witness is
history and replays; legacy shape without one is a forgery and stays damage.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from tests.durable_seals import reseal_primary_fact
from tests.migrations.test_sqlite_v6_to_v7 import _downgrade_v7_schema_to_v6

from constructicon.core.control import (
    OPERATE_SCOPE,
    AuthenticatedActor,
    CommandClaim,
    HistoricalDomainPlanEvidence,
    command_request_hash,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import JsonValue, canonical_json
from constructicon.substrate.journal._sqlite_commands import (
    DOMAIN_PLAN_ERA_FACT_FAMILY,
    command_plan_fact_hash,
    command_terminal_fact_hash,
    domain_plan_era_fact_hash,
)
from constructicon.substrate.journal._sqlite_fact_seals import sealed_fact_hash
from constructicon.substrate.journal.sqlite import SqliteJournal

_NO_WITNESS = "'domain_plan_pre_v7' fact .* has no positive seal"

ACTOR = AuthenticatedActor(
    actor_id="static:domain-plan-era",
    auth_method="static",
    scopes=frozenset({OPERATE_SCOPE}),
)

# The current shape of each family, and the one key whose absence is the era.
SHAPES: dict[str, tuple[str, dict[str, JsonValue], str]] = {
    "promotion": (
        "registry_promote",
        {
            "kind": "promotion",
            "component": "test/component",
            "baseline": None,
            "target": "sha256:" + "a" * 64,
            "attestation_id": "att-domain-plan-era",
            "terminal_rejection_policy": "exact-v1",
        },
        "terminal_rejection_policy",
    ),
    "cancel": (
        "runs_cancel",
        {
            "kind": "cancel",
            "run_id": "run-domain-plan-era",
            "observed_status": "failed",
            "outcome": "already_terminal",
            "response_status": "failed",
            "observed_event_seq": 1,
        },
        "observed_event_seq",
    ),
}


def _claimed(journal: SqliteJournal, operation: str, key: str) -> CommandClaim:
    request: JsonValue = {"key": key}
    result = journal.claim_command(
        actor=ACTOR,
        operation=operation,
        idempotency_key=key,
        request_hash=command_request_hash(request),
        request=request,
        owner_id="test:domain-plan-era",
        ttl_s=30,
    )
    assert result.claim is not None
    return result.claim


def _current_plan(shape: str) -> JsonValue:
    return {"schema_version": 1, "plan": dict(SHAPES[shape][1])}


def _legacy_plan(shape: str) -> JsonValue:
    inner = dict(SHAPES[shape][1])
    del inner[SHAPES[shape][2]]
    return {"schema_version": 1, "plan": inner}


def _rewrite_plan(database: Path, command_id: str, plan: JsonValue) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (canonical_json(plan), command_id),
        )
        connection.commit()


@pytest.mark.parametrize("shape", sorted(SHAPES))
@pytest.mark.parametrize("phase", ("prepared", "terminal"))
def test_v6_migration_witnesses_each_pre_exact_proof_domain_plan(
    shape: str,
    phase: str,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"domain-era-{shape}-{phase}.db"
    journal = SqliteJournal(database)
    operation = SHAPES[shape][0]
    claim = _claimed(journal, operation, f"domain-era-{shape}-{phase}")
    journal.store_command_plan(claim, _current_plan(shape))
    if phase == "terminal":
        journal.reject_command(claim, {"status": "rejected", "faults": []})
    _downgrade_v7_schema_to_v6(database)
    _rewrite_plan(database, claim.command_id, _legacy_plan(shape))

    migrated = SqliteJournal(database)
    witness = migrated.historical_domain_plan_evidence(claim.command_id)
    assert witness == HistoricalDomainPlanEvidence(
        command_id=claim.command_id,
        phase_at_migration=phase,  # type: ignore[arg-type]
    )
    # And the resume family did not claim it: the witness is one family's.
    assert migrated.historical_resume_plan_evidence(claim.command_id) is None


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_a_current_plan_downgraded_without_a_witness_is_a_forgery(
    shape: str,
    tmp_path: Path,
) -> None:
    """The bytes match history; nothing witnessed them, so they are not."""

    database = tmp_path / f"domain-era-forged-{shape}.db"
    journal = SqliteJournal(database)
    claim = _claimed(journal, SHAPES[shape][0], f"domain-era-forged-{shape}")
    journal.store_command_plan(claim, _current_plan(shape))

    with journal._txn() as connection:
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (canonical_json(_legacy_plan(shape)), claim.command_id),
        )
        row = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?",
            (claim.command_id,),
        ).fetchone()
        reseal_primary_fact(
            connection,
            family="command_plan",
            fact_key=claim.command_id,
            fact=command_plan_fact_hash(row),
        )

    with pytest.raises(JournalDamaged, match=_NO_WITNESS):
        journal.command(claim.command_id)


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_a_witness_on_a_current_plan_is_refused(shape: str, tmp_path: Path) -> None:
    """A witness cannot be smuggled onto bytes that do not call for one."""

    database = tmp_path / f"domain-era-smuggled-{shape}.db"
    journal = SqliteJournal(database)
    claim = _claimed(journal, SHAPES[shape][0], f"domain-era-smuggled-{shape}")
    journal.store_command_plan(claim, _current_plan(shape))
    witness = HistoricalDomainPlanEvidence(
        command_id=claim.command_id,
        phase_at_migration="prepared",
    )
    selector = canonical_json(witness.model_dump(mode="json"))
    with journal._txn() as connection:
        row = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?",
            (claim.command_id,),
        ).fetchone()
        connection.execute(
            "INSERT INTO durable_fact_seals (family, fact_key, selector, fact_hash)"
            " VALUES (?, ?, ?, ?)",
            (
                DOMAIN_PLAN_ERA_FACT_FAMILY,
                claim.command_id,
                selector,
                str(
                    sealed_fact_hash(
                        family=DOMAIN_PLAN_ERA_FACT_FAMILY,
                        fact_key=claim.command_id,
                        selector=selector,
                        fact=domain_plan_era_fact_hash(row, evidence=witness),
                    )
                ),
            ),
        )

    with pytest.raises(JournalDamaged, match="carries historical era evidence"):
        journal.command(claim.command_id)


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_a_terminal_witness_binds_the_exact_retained_response(
    shape: str,
    tmp_path: Path,
) -> None:
    """The witness is what lets a stored refusal replay, so it must own its bytes."""

    database = tmp_path / f"domain-era-response-{shape}.db"
    journal = SqliteJournal(database)
    claim = _claimed(journal, SHAPES[shape][0], f"domain-era-response-{shape}")
    journal.store_command_plan(claim, _current_plan(shape))
    journal.reject_command(claim, {"status": "rejected", "faults": []})
    _downgrade_v7_schema_to_v6(database)
    _rewrite_plan(database, claim.command_id, _legacy_plan(shape))
    migrated = SqliteJournal(database)
    assert migrated.historical_domain_plan_evidence(claim.command_id) is not None

    # Rewrite the response and reconcile only the terminal-phase seal, as a
    # forger who did not know about the witness would.
    with migrated._txn() as connection:
        connection.execute(
            "UPDATE commands SET response_json = ? WHERE command_id = ?",
            (
                canonical_json({"status": "rejected", "faults": [{"forged": True}]}),
                claim.command_id,
            ),
        )
        row = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?",
            (claim.command_id,),
        ).fetchone()
        reseal_primary_fact(
            connection,
            family="command_terminal",
            fact_key=claim.command_id,
            fact=command_terminal_fact_hash(row),
        )

    with pytest.raises(JournalDamaged, match="positive seal"):
        migrated.command(claim.command_id)


def test_an_orphan_witness_is_refused_at_open(tmp_path: Path) -> None:
    database = tmp_path / "domain-era-orphan.db"
    SqliteJournal(database)
    witness = HistoricalDomainPlanEvidence(
        command_id="cmd-domain-era-orphan",
        phase_at_migration="prepared",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO durable_fact_seals (family, fact_key, selector, fact_hash)"
            " VALUES (?, ?, ?, ?)",
            (
                DOMAIN_PLAN_ERA_FACT_FAMILY,
                witness.command_id,
                canonical_json(witness.model_dump(mode="json")),
                "sha256:" + "0" * 64,
            ),
        )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match="domain-plan era seal inventory has an orphan or missing fact",
    ):
        SqliteJournal(database)


def test_a_command_unplanned_at_migration_receives_no_witness(tmp_path: Path) -> None:
    """The witness binds a plan, so a command with none to bind gets none.

    That is what stops a plan stored *after* the migration inheriting a
    witness it was never observed under — and the current writer's guard then
    refuses the legacy shape outright.
    """

    database = tmp_path / "domain-era-unplanned.db"
    journal = SqliteJournal(database)
    claim = _claimed(journal, "registry_promote", "domain-era-unplanned")
    _downgrade_v7_schema_to_v6(database)

    migrated = SqliteJournal(database)
    assert migrated.historical_domain_plan_evidence(claim.command_id) is None

    with pytest.raises(JournalDamaged, match="cannot mint a historical domain plan era"):
        migrated.store_command_plan(claim, _legacy_plan("promotion"))
    migrated.store_command_plan(claim, _current_plan("promotion"))
    stored = migrated.command(claim.command_id)
    assert stored is not None and stored.plan is not None
    planned = json.loads(canonical_json(stored.plan))["plan"]
    assert planned["terminal_rejection_policy"] == "exact-v1"
