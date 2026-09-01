"""Truthful run-world attestations for direct substrate tests."""

from __future__ import annotations

from constructicon.core.address import RunId
from constructicon.core.effect import (
    Attestation,
    AttestationDraft,
    CheckResult,
    ComponentProofSubject,
)
from constructicon.core.identity import Digest, digest
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.run_worlds import create_test_run, sealed_test_manifest

_TEST_MANIFEST = sealed_test_manifest()
_TEST_MANIFEST_HASH = _TEST_MANIFEST.manifest_hash


def ensure_test_run(
    journal: SqliteJournal,
    run_id: RunId,
    *,
    manifest_hash: Digest = _TEST_MANIFEST_HASH,
) -> Digest:
    """Return the run's real manifest, creating one minimal test world if absent."""

    stored = journal.run_manifest_hash(run_id)
    if stored is not None:
        if stored != manifest_hash:
            raise ValueError("test run already belongs to a different manifest")
        return stored
    created = create_test_run(journal, run_id)
    if created.manifest_hash != manifest_hash:
        raise ValueError("requested test manifest is not the sealed fixture world")
    return manifest_hash


def mint_run_attestation(
    journal: SqliteJournal,
    run_id: RunId,
    draft: AttestationDraft,
) -> Attestation:
    """Mint under a real lease and release it for the next direct test action."""

    ensure_test_run(journal, run_id, manifest_hash=draft.manifest_hash)
    lease = journal.claim_run(
        run_id,
        owner_id="test:attestation-mint",
        ttl_s=30,
    )
    try:
        return journal.mint_attestation(lease, draft)
    finally:
        journal.release_run(lease)


def mint_promotion_attestation(
    journal: SqliteJournal,
    *,
    component: str,
    version: Digest,
    baseline: Digest | None,
    proof: str,
) -> Attestation:
    """Mint one exact policy proof for a direct SQLite registry receipt."""

    return journal.mint_policy_attestation(
        AttestationDraft(
            action="promote",
            subject=ComponentProofSubject(
                component=component,
                version=version,
                baseline_version=baseline,
            ),
            checks=(
                CheckResult(
                    name=proof,
                    status="passed",
                    detail="direct registry test",
                    elapsed_s=0.0,
                ),
            ),
            check_set_hash=digest("check-set", 1, {"test": proof}),
            evidence=(),
            manifest_hash=digest("manifest", 1, {"policy": proof}),
            workspace_id=None,
        )
    )
