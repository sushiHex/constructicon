"""Prove canonical registry storage and closed run-attestation authority."""

from _mutations import run

TEST = (
    "tests/runtime/test_registry_revision.py::"
    "test_registry_store_refuses_canonical_duplicate_definitions_without_mutation"
)

MUTANTS = (
    (
        "memory duplicate definition comparison is canonical",
        "constructicon.runtime.registry:InMemoryRegistryStore.store_version",
        "if same_definition(existing.definition, version.definition):",
        "if existing.definition == version.definition:",
        TEST,
    ),
    (
        "sqlite duplicate definition comparison is canonical",
        "constructicon.substrate.journal._sqlite_registry:_SqliteRegistryMixin.store_version",
        "if same_definition(retained.definition, version.definition):",
        "if retained.definition == version.definition:",
        TEST,
    ),
    (
        "ordinary attestation identity includes its creator run",
        "constructicon.core.effect:attestation_id_for_run",
        '"created_by_run": str(run_id)',
        '"created_by_run": "ignored"',
        "tests/substrate/journal/test_run_attestation_identity.py::"
        "test_equal_drafts_from_independent_runs_have_distinct_run_bound_proofs[promote]",
    ),
    (
        "current run-v1 proof requires exact migration witness",
        "constructicon.substrate.journal._sqlite_attestations:require_attestation_seal",
        "require_durable_fact_seal(\n"
        "            connection, family=RUN_V1_ATTESTATION_WITNESS_FAMILY,\n"
        "            fact_key=attestation_id, selector=attestation_id,\n"
        "            fact_hash=attestation_fact_hash(row, family=RUN_V1_ATTESTATION_WITNESS_FAMILY),\n"
        "        )",
        "pass",
        "tests/migrations/test_sqlite_v9_to_v10.py::"
        "test_historical_witness_damage_refuses_current_point_run_and_open[missing]",
    ),
    (
        "both run identity eras prove their creator world",
        "constructicon.substrate.journal._sqlite_attestations:require_attestation_seal",
        "_require_current_creator(connection, stored)",
        "pass",
        "tests/substrate/journal/test_run_attestation_identity.py::"
        "test_exact_v2_id_and_primary_seal_cannot_replace_creator_world_validation",
    ),
    (
        "inbox selector includes unwitnessed history despite actor filtering",
        "constructicon.substrate.journal._sqlite_attestations:_attestation_seals_match",
        "return int(witness == expected(RUN_V1_ATTESTATION_WITNESS_FAMILY))",
        "return 1",
        "tests/migrations/test_sqlite_v9_to_v10.py::"
        "test_inbox_sql_cannot_hide_unproven_history_behind_another_actor[missing]",
    ),
    (
        "SQL joins retain misplaced opposite-family seals for refusal",
        "constructicon.substrate.journal._sqlite_attestations:attestation_seal_joins",
        'f" OR {prefix}_{suffix}.selector = {alias}.attestation_id)"',
        'f" AND {prefix}_{suffix}.selector = {alias}.attestation_id)"',
        "tests/migrations/test_sqlite_v9_to_v10.py::"
        "test_inbox_sql_cannot_hide_unproven_history_behind_another_actor[dual-family-selector]",
    ),
    (
        "SQL relation binds proof manifest to its canonical creator world",
        "constructicon.substrate.journal._sqlite_attestations:_attestation_creator_matches",
        "str(proof.created_by_run) == run_id and str(proof.manifest_hash) == manifest_hash",
        "str(proof.created_by_run) == run_id",
        "tests/substrate/journal/test_run_attestation_identity.py::"
        "test_exact_v2_id_and_primary_seal_cannot_replace_creator_world_validation",
    ),
    (
        "canonical creator command authority precedes actor and cursor filters",
        "constructicon.substrate.journal._sqlite_attestations:_validate_attestation_creator_worlds",
        "for row in rows:",
        "for row in ():",
        "tests/migrations/test_sqlite_v9_to_v10.py::"
        "test_creator_command_and_clone_authority_cannot_hide_behind_filters[command-plan-seal]",
    ),
    (
        "fresh rollback cannot reuse a consumed policy proof",
        "constructicon.runtime.registry:ComponentRegistry.plan_rollback",
        "if prior is not None:",
        "if False:",
        "tests/api/test_control_response_loss.py::"
        "test_recurring_rollback_refuses_used_proof_and_replays_history",
    ),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
