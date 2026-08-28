"""Registry reads reconstruct one coherent registration/promotion vector cut."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from constructicon.core.component import PromotionRecord
from constructicon.core.registry import (
    InvalidRegistryRevision,
    RegistryRevision,
    RegistryStore,
    StoredVersion,
    registry_snapshot_digest,
)
from constructicon.runtime.registry import InMemoryRegistryStore
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import ISSUE, REVIEW, atomic, review_impl


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
    component: str,
    before: StoredVersion | None,
    target: StoredVersion,
    offset: int,
) -> PromotionRecord:
    return PromotionRecord(
        component=component,
        channel="stable",
        from_version=before.content_hash if before else None,
        to_version=target.content_hash,
        attestation_id=f"att-revision-{offset}",
        actor="static:test",
        source_run=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=offset),
    )


def test_registry_vector_cut_is_reconstructable_and_digest_complete(
    revision_store: RegistryStore,
) -> None:
    first = _version("revision/component", 0)
    second = _version("revision/component", 1)
    revision_store.store_version(first)
    revision_store.store_promotion(_promotion(first.definition.name, None, first, 1))
    cut = revision_store.snapshot().revision
    digest_at_cut = registry_snapshot_digest(revision_store.snapshot(cut))

    revision_store.store_version(second)
    revision_store.store_promotion(_promotion(first.definition.name, first, second, 2))

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
    revision_store.store_promotion(_promotion(version.definition.name, None, version, 1))
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

    promotion = _promotion(stored.definition.name, None, stored, 1)
    revision_store.store_promotion(promotion)
    after_promotion = revision_store.snapshot().revision
    assert after_promotion == RegistryRevision(registration_seq=1, promotion_seq=1)
    revision_store.store_promotion(promotion)
    assert revision_store.snapshot().revision == after_promotion


def test_nonstable_promotion_fact_never_moves_the_stable_pointer(
    revision_store: RegistryStore,
) -> None:
    """The in-memory and SQLite stores reconstruct the same channel semantics."""

    first = _version("revision/channel-parity", 0)
    second = _version("revision/channel-parity", 1)
    revision_store.store_version(first)
    revision_store.store_version(second)
    revision_store.store_promotion(_promotion(first.definition.name, None, first, 1))
    revision_store.store_promotion(
        _promotion(first.definition.name, first, second, 2).model_copy(
            update={"channel": "candidate"}
        )
    )

    snapshot = revision_store.snapshot()
    assert snapshot.revision == RegistryRevision(registration_seq=2, promotion_seq=2)
    assert snapshot.stable_version(first.definition.name) == first.content_hash
    assert snapshot.history[first.definition.name] == ((None, str(first.content_hash)),)


def test_sqlite_registry_revision_cuts_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "registry-reopen.db"
    first_store = SqliteJournal(path)
    first = _version("revision/reopen", 0)
    second = _version("revision/reopen", 1)
    first_store.store_version(first)
    first_store.store_promotion(_promotion(first.definition.name, None, first, 1))
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
