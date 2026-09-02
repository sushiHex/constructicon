"""Registry reads reconstruct one coherent registration/promotion vector cut."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from constructicon.core.component import (
    CapabilityRequirement,
    ComponentMetadata,
    LearningProfile,
    PromotionRecord,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.graph import Ref
from constructicon.core.identity import canonical_json, digest
from constructicon.core.registry import (
    InvalidRegistryRevision,
    RegistryRevision,
    RegistryStore,
    StoredVersion,
    registry_snapshot_digest,
)
from constructicon.runtime.registry import InMemoryRegistryStore
from constructicon.substrate.journal._sqlite_registry import (
    seal_component_registration,
)
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import ISSUE, REVIEW, atomic, review_impl
from tests.run_attestations import mint_promotion_attestation


@pytest.fixture(params=("memory", "sqlite"))
def revision_store(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> RegistryStore:
    if request.param == "memory":
        return InMemoryRegistryStore()
    return SqliteJournal(tmp_path / "registry-revisions.db")


def _version(name: str, offset: int) -> StoredVersion:
    definition, _ = atomic(name, (ISSUE,), (REVIEW,), review_impl)
    if offset:
        definition = definition.model_copy(
            update={
                "outputs": (
                    definition.outputs[0].model_copy(update={"schema_hash": f"s{offset + 1}"}),
                )
            }
        )
    return StoredVersion(
        definition=definition,
        content_hash=definition.content_hash(),
        registered_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=offset),
    )


def _promotion(
    store: RegistryStore,
    component: str,
    before: StoredVersion | None,
    target: StoredVersion,
    offset: int,
) -> PromotionRecord:
    record = PromotionRecord(
        component=component,
        channel="stable",
        from_version=before.content_hash if before else None,
        to_version=target.content_hash,
        attestation_id=f"att-revision-{offset}",
        actor="static:test",
        source_run=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=offset),
    )
    if isinstance(store, SqliteJournal):
        attestation = mint_promotion_attestation(
            store,
            component=component,
            version=target.content_hash,
            baseline=before.content_hash if before else None,
            proof=f"registry-revision-{offset}",
        )
        return record.model_copy(update={"attestation_id": attestation.attestation_id})
    return record


def test_registry_vector_cut_is_reconstructable_and_digest_complete(
    revision_store: RegistryStore,
) -> None:
    first = _version("revision/component", 0)
    second = _version("revision/component", 1)
    revision_store.store_version(first)
    revision_store.store_promotion(
        _promotion(revision_store, first.definition.name, None, first, 1)
    )
    cut = revision_store.snapshot().revision
    digest_at_cut = registry_snapshot_digest(revision_store.snapshot(cut))

    revision_store.store_version(second)
    revision_store.store_promotion(
        _promotion(revision_store, first.definition.name, first, second, 2)
    )

    historical = revision_store.snapshot(cut)
    current = revision_store.snapshot()
    assert historical.revision == cut == RegistryRevision(registration_seq=1, promotion_seq=1)
    assert historical.stable_version(first.definition.name) == first.content_hash
    assert historical.get(first.definition.name, second.content_hash) is None
    assert registry_snapshot_digest(historical) == digest_at_cut
    assert current.stable_version(first.definition.name) == second.content_hash
    assert registry_snapshot_digest(current) != digest_at_cut


def test_registry_rejects_future_and_incoherent_cuts(
    revision_store: RegistryStore,
) -> None:
    version = _version("revision/incoherent", 0)
    revision_store.store_version(version)
    revision_store.store_promotion(
        _promotion(revision_store, version.definition.name, None, version, 1)
    )
    with pytest.raises(InvalidRegistryRevision):
        revision_store.snapshot(RegistryRevision(registration_seq=2, promotion_seq=1))
    with pytest.raises(InvalidRegistryRevision):
        revision_store.snapshot(RegistryRevision(registration_seq=0, promotion_seq=1))


def test_registry_revision_advances_only_for_new_durable_facts(
    revision_store: RegistryStore,
) -> None:
    assert revision_store.snapshot().revision == RegistryRevision(
        registration_seq=0,
        promotion_seq=0,
    )
    stored = _version("revision/idempotent", 0)
    revision_store.store_version(stored)
    after_registration = revision_store.snapshot().revision
    assert after_registration == RegistryRevision(registration_seq=1, promotion_seq=0)
    revision_store.store_version(stored)
    assert revision_store.snapshot().revision == after_registration

    promotion = _promotion(revision_store, stored.definition.name, None, stored, 1)
    revision_store.store_promotion(promotion)
    after_promotion = revision_store.snapshot().revision
    assert after_promotion == RegistryRevision(registration_seq=1, promotion_seq=1)
    revision_store.store_promotion(promotion)
    assert revision_store.snapshot().revision == after_promotion


def test_nonstable_promotion_fact_is_refused_before_it_can_move_a_pointer(
    revision_store: RegistryStore,
) -> None:
    """The in-memory and SQLite stores enforce the typed stable-only contract."""

    first = _version("revision/channel-parity", 0)
    second = _version("revision/channel-parity", 1)
    revision_store.store_version(first)
    revision_store.store_version(second)
    revision_store.store_promotion(
        _promotion(revision_store, first.definition.name, None, first, 1)
    )
    with pytest.raises(JournalDamaged, match="unsupported channel"):
        revision_store.store_promotion(
            _promotion(revision_store, first.definition.name, first, second, 2).model_copy(
                update={"channel": "candidate"}
            )
        )

    snapshot = revision_store.snapshot()
    assert snapshot.revision == RegistryRevision(registration_seq=2, promotion_seq=1)
    assert snapshot.stable_version(first.definition.name) == first.content_hash
    assert snapshot.history[first.definition.name] == ((None, str(first.content_hash)),)


def test_sqlite_registry_revision_cuts_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "registry-reopen.db"
    first_store = SqliteJournal(path)
    first = _version("revision/reopen", 0)
    second = _version("revision/reopen", 1)
    first_store.store_version(first)
    first_store.store_promotion(_promotion(first_store, first.definition.name, None, first, 1))
    cut = first_store.snapshot().revision
    first_store.store_version(second)

    reopened = SqliteJournal(path)
    historical = reopened.snapshot(cut)
    current = reopened.snapshot()
    assert historical.revision == cut
    assert historical.get(first.definition.name, first.content_hash) == first
    assert historical.get(first.definition.name, second.content_hash) is None
    assert current.get(first.definition.name, second.content_hash) == second
    assert current.revision == RegistryRevision(registration_seq=2, promotion_seq=1)


@pytest.mark.parametrize("field", ("to_version", "source_run"))
def test_sqlite_promotion_projection_is_bound_to_its_exact_attestation_edge(
    field: str,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"promotion-authority-{field}.db"
    journal = SqliteJournal(database)
    first = _version("revision/authority", 0)
    second = _version("revision/authority", 1)
    journal.store_version(first)
    journal.store_version(second)
    promotion = _promotion(journal, first.definition.name, None, first, 1)
    journal.store_promotion(promotion)

    forged = str(second.content_hash) if field == "to_version" else "run-foreign-evaluator"
    with sqlite3.connect(database) as connection:
        connection.execute(f"UPDATE promotions SET {field} = ?", (forged,))

    with pytest.raises(JournalDamaged, match=r"authority fact|positive seal"):
        journal.snapshot()
    with pytest.raises(JournalDamaged, match=r"authority fact|positive seal"):
        journal.promotion_for_attestation(promotion.attestation_id)


def test_sqlite_promotion_cannot_move_between_equivalent_authority_facts(
    tmp_path: Path,
) -> None:
    """A valid replacement attestation is still not the receipt's authority."""

    database = tmp_path / "promotion-selector.db"
    journal = SqliteJournal(database)
    version = _version("revision/sealed-authority", 0)
    journal.store_version(version)
    first = _promotion(journal, version.definition.name, None, version, 1)
    replacement = _promotion(journal, version.definition.name, None, version, 2)
    assert first.attestation_id != replacement.attestation_id
    journal.store_promotion(first)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE promotions SET attestation_id = ? WHERE attestation_id = ?",
            (replacement.attestation_id, first.attestation_id),
        )

    for attestation_id in (first.attestation_id, replacement.attestation_id):
        with pytest.raises(JournalDamaged, match=r"seal|selector"):
            journal.promotion_for_attestation(attestation_id)
    with pytest.raises(JournalDamaged, match=r"seal|selector"):
        journal.snapshot()


def test_sqlite_promotion_requires_its_independent_positive_seal(
    tmp_path: Path,
) -> None:
    database = tmp_path / "promotion-missing-seal.db"
    journal = SqliteJournal(database)
    version = _version("revision/missing-seal", 0)
    journal.store_version(version)
    promotion = _promotion(journal, version.definition.name, None, version, 1)
    journal.store_promotion(promotion)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM durable_fact_seals WHERE family = 'promotion'"
        )

    with pytest.raises(JournalDamaged, match="positive seal"):
        journal.snapshot()
    with pytest.raises(JournalDamaged, match="positive seal"):
        journal.store_promotion(promotion)


@pytest.mark.parametrize("deleted_sequence", (1, 2))
def test_sqlite_registry_never_treats_a_deleted_promotion_as_rollback(
    deleted_sequence: int,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"promotion-deleted-{deleted_sequence}.db"
    journal = SqliteJournal(database)
    first = _version("revision/append-only", 0)
    second = _version("revision/append-only", 1)
    journal.store_version(first)
    journal.store_version(second)
    journal.store_promotion(_promotion(journal, first.definition.name, None, first, 1))
    second_promotion = _promotion(journal, first.definition.name, first, second, 2)
    journal.store_promotion(second_promotion)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM promotions WHERE promotion_seq = ?",
            (deleted_sequence,),
        )

    with pytest.raises(JournalDamaged, match="append-only sequence history is incomplete"):
        journal.snapshot()
    with pytest.raises(JournalDamaged, match="append-only sequence history is incomplete"):
        journal.store_promotion(second_promotion)


def test_sqlite_registry_never_recreates_a_deleted_candidate(tmp_path: Path) -> None:
    database = tmp_path / "candidate-deleted.db"
    journal = SqliteJournal(database)
    first = _version("revision/deleted-candidate", 0)
    second = _version("revision/deleted-candidate", 1)
    journal.store_version(first)
    journal.store_version(second)
    journal.store_promotion(_promotion(journal, first.definition.name, None, first, 1))

    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM components WHERE content_hash = ?",
            (str(second.content_hash),),
        )

    with pytest.raises(JournalDamaged, match="append-only sequence history is incomplete"):
        journal.snapshot()
    with pytest.raises(JournalDamaged, match="append-only sequence history is incomplete"):
        journal.store_version(second)


def test_sqlite_component_registration_cannot_move_to_another_valid_identity(
    tmp_path: Path,
) -> None:
    database = tmp_path / "component-selector.db"
    journal = SqliteJournal(database)
    original = _version("revision/original", 0)
    replacement = _version("revision/replacement", 1)
    journal.store_version(original)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE components SET name = ?, content_hash = ?, definition_json = ?,"
            " registered_at = ? WHERE registration_seq = 1",
            (
                replacement.definition.name,
                str(replacement.content_hash),
                replacement.definition.model_dump_json(),
                replacement.registered_at.isoformat(),
            ),
        )

    with pytest.raises(JournalDamaged, match=r"seal|selector"):
        journal.snapshot()
    for version in (original, replacement):
        with pytest.raises(JournalDamaged, match=r"seal|selector"):
            journal.store_version(version)


def test_sqlite_component_registration_requires_its_positive_seal(
    tmp_path: Path,
) -> None:
    database = tmp_path / "component-missing-seal.db"
    journal = SqliteJournal(database)
    version = _version("revision/component-seal", 0)
    journal.store_version(version)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM durable_fact_seals WHERE family = 'component_registration'"
        )

    with pytest.raises(JournalDamaged, match="positive seal"):
        journal.snapshot()
    with pytest.raises(JournalDamaged, match="positive seal"):
        journal.store_version(version)


@pytest.mark.parametrize("with_capabilities", (False, True))
def test_sqlite_component_projection_retains_the_exact_historical_set_order_law(
    with_capabilities: bool,
    tmp_path: Path,
) -> None:
    """Old frozenset order is accepted exactly, never re-versioned today."""

    database = tmp_path / f"component-historical-order-{with_capabilities}.db"
    journal = SqliteJournal(database)
    source = _version("revision/historical-order", 0)
    update: dict[str, object] = {
            "metadata": ComponentMetadata(
                labels=frozenset({"alpha", "zeta"}),
                learning=LearningProfile(
                    change_surfaces=frozenset({"code", "prompt"}),
                    experience_policy=Ref(component="policy/experience"),
                    evaluator=Ref(component="policy/evaluator"),
                    promotion_policy=Ref(component="policy/promotion"),
                ),
            ),
    }
    if with_capabilities:
        update["capability_requirements"] = (
            CapabilityRequirement(alias="alpha", kind="executor.fake"),
            CapabilityRequirement(alias="zeta", kind="workspace.fake"),
        )
    definition = source.definition.model_copy(update=update)
    raw = json.loads(definition.model_dump_json())
    raw["metadata"]["labels"] = ["zeta", "alpha"]
    raw["metadata"]["learning"]["change_surfaces"] = ["prompt", "code"]
    if with_capabilities:
        raw["capability_requirements"] = list(
            reversed(raw["capability_requirements"])
        )
    identity_payload = {
        "role": raw["role"],
        "body": raw["body"],
        "inputs": raw["inputs"],
        "outputs": raw["outputs"],
        "learning": raw["metadata"]["learning"],
    }
    identity_version = 1
    if with_capabilities:
        identity_version = 2
        identity_payload["capability_requirements"] = sorted(
            raw["capability_requirements"],
            key=lambda item: (item["alias"], item["kind"]),
        )
    historical_hash = digest(
        "component",
        identity_version,
        identity_payload,
    )
    assert historical_hash != definition.content_hash()

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "INSERT INTO components"
            " (name, content_hash, definition_json, registered_at) VALUES (?, ?, ?, ?)",
            (
                definition.name,
                str(historical_hash),
                canonical_json(raw),
                source.registered_at.isoformat(),
            ),
        )
        row = connection.execute("SELECT * FROM components").fetchone()
        assert row is not None
        seal_component_registration(connection, row)

    snapshot = journal.snapshot()
    retained = snapshot.get(definition.name, historical_hash)
    assert retained is not None
    assert retained.content_hash == historical_hash
    assert retained.definition == definition
