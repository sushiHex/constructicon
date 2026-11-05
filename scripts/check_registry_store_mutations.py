"""Prove canonical registry definitions and fresh rollback proof custody."""

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
