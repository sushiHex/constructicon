"""Prove both registry-store duplicate guards use canonical definitions."""

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
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
