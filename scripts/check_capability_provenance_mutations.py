"""Prove accounting provenance cannot be inferred from absent durable facts."""

from _mutations import run

PROVENANCE = "constructicon.substrate.journal._sqlite_capability_provenance:"
EXECUTION = "constructicon.substrate.journal._sqlite_execution:"
SCHEMA = "constructicon.substrate.journal._sqlite_schema:"
JOURNAL_TESTS = "tests/substrate/journal/test_capability_accounting_provenance.py::"
MIGRATION_TESTS = "tests/migrations/test_sqlite_v7_to_v8.py::"

MUTANTS = (
    (
        "creation co-commits a positive accounting era",
        SCHEMA + "_SqliteSchemaMixin.create_run",
        "mint_creation_accounting_era(connection, created)",
        "pass  # missing creation witness",
        JOURNAL_TESTS + "test_new_runs_co_commit_positive_creation_eras",
    ),
    (
        "idempotent creation validates retained era evidence",
        SCHEMA + "_SqliteSchemaMixin.create_run",
        "require_accounting_era(connection, run)",
        "pass  # existing run is not its own era evidence",
        JOURNAL_TESTS + "test_current_era_damage_is_not_empty_history_or_creation_permission[both]",
    ),
    (
        "worker authority cannot mint lost accounting",
        EXECUTION + "_SqliteExecutionMixin.transition_capability_lease",
        'if target == "lost":',
        "if False:",
        JOURNAL_TESTS + "test_current_workers_cannot_mint_lost_facts",
    ),
    (
        "worker authority cannot reactivate historical lost accounting",
        EXECUTION + "_SqliteExecutionMixin.transition_capability_lease",
        'if stored.state == "lost" and target == "active":',
        "if False:",
        MIGRATION_TESTS + "test_current_worker_cannot_reactivate_historical_lost",
    ),
    (
        "migration inventory commitment detects erased eventless acquisitions",
        PROVENANCE + "validate_accounting_run",
        "if accounting_inventory_hash(histories, era.floor) != era.inventory_hash:",
        "if False:",
        MIGRATION_TESTS + "test_eventless_legacy_erasure_refuses_even_with_valid_event_extent[active-False]",
    ),
    (
        "later acquisitions cannot rewrite a migration inventory",
        PROVENANCE + "accounting_inventory_hash",
        "if acquired.seq > floor:",
        "if False:",
        MIGRATION_TESTS + "test_migration_floor_digest_survives_later_closure_and_new_acquisition",
    ),
    (
        "historical lost transitions require their positive witnesses",
        PROVENANCE + "require_capability_lost_provenance",
        "for event in lost_events:",
        "for event in ():",
        MIGRATION_TESTS + "test_deleted_historical_lost_witness_is_not_reminted_on_open",
    ),
    (
        "initial lost accounting requires its separate historical witness",
        PROVENANCE + "require_capability_lost_provenance",
        "if initial_lost:",
        "if False:",
        MIGRATION_TESTS + "test_deleted_initial_lost_witness_is_not_inferred_from_the_legacy_seal",
    ),
    (
        "current schema cannot mint historical provenance",
        PROVENANCE + "mint_migrated_capability_provenance",
        'connection.execute("PRAGMA user_version").fetchone()[0] != 7',
        "False",
        MIGRATION_TESTS + "test_current_paths_cannot_mint_historical_capability_provenance",
    ),
    (
        "retained accounting evidence makes absent run damage",
        EXECUTION + "_SqliteExecutionMixin.capability_leases",
        "require_accounting_absence(conn, run_id)",
        "pass  # orphan era is not an absent run",
        JOURNAL_TESTS + "test_missing_run_with_retained_accounting_evidence_is_damage",
    ),
    (
        "era rows must agree with their independent seals",
        PROVENANCE + "require_accounting_era",
        "require_durable_fact_seal(",
        "(lambda *args, **kwargs: None)(",
        JOURNAL_TESTS + "test_current_era_damage_is_not_empty_history_or_creation_permission[source]",
    ),
    (
        "accounting cuts cannot precede the proven floor or exceed the extent",
        PROVENANCE + "validate_accounting_run",
        'if cut < era.floor or cut > run["next_event_seq"]:',
        "if False:",
        MIGRATION_TESTS + "test_accounting_cuts_require_positive_era_and_the_recorded_floor",
    ),
    (
        "current legacy events cannot borrow opaque historical provenance",
        PROVENANCE + "require_capability_lost_provenance",
        "if history.legacy is not None and any(",
        "if False and any(",
        MIGRATION_TESTS + "test_current_legacy_event_cannot_downgrade_to_opaque_history",
    ),
    (
        "historical witnesses must lie within the positively recorded floor",
        PROVENANCE + "require_capability_lost_provenance",
        "if event.run_id != history.lease.run_id or event.seq > era.floor:",
        "if False:",
        MIGRATION_TESTS + "test_lost_witness_cannot_lie_above_a_rewritten_migration_floor",
    ),
    (
        "historical minting requires the migration transaction",
        PROVENANCE + "mint_migrated_capability_provenance",
        "or not connection.in_transaction",
        "or False",
        MIGRATION_TESTS + "test_historical_mint_requires_the_migration_write_transaction",
    ),
    (
        "ordinary active point paths cannot skip positive era evidence",
        PROVENANCE + "require_capability_lost_provenance",
        "    era = require_accounting_era(connection, accounting_run_row(connection, history.lease.run_id))\n"
        "    if not lost_events and not initial_lost and history.legacy is None:\n"
        "        return 0",
        "    if not lost_events and not initial_lost and history.legacy is None:\n"
        "        return 0\n"
        "    era = require_accounting_era(connection, accounting_run_row(connection, history.lease.run_id))",
        JOURNAL_TESTS + "test_current_active_capability_paths_require_positive_era[close]",
    ),
    (
        "new acquisitions require their run accounting era",
        EXECUTION + "_SqliteExecutionMixin.record_capability_lease",
        "require_accounting_era(conn, accounting_run_row(conn, lease.run_id))",
        "pass  # new acquisition is not permission to repair missing run evidence",
        JOURNAL_TESTS + "test_current_active_capability_paths_require_positive_era[acquire]",
    ),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
