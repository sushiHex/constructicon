"""merge_verified — the one path from proposed code to a protected ref.

Live execution verifies a journal-minted attestation and installs one exact Git
subject. Counterfactual simulation performs the same proof checks but never calls
Git install/reconcile and returns a truthful ``simulated`` receipt.
"""

from __future__ import annotations

from constructicon.core.effect import (
    EffectProfile,
    EffectReceipt,
    EffectRequest,
    MergeSubject,
    request_hash,
)
from constructicon.core.errors import AdmissionError, ContractViolation
from constructicon.core.journal import Journal
from constructicon.substrate.git.authority import GitAuthority


class MergeVerifiedEffect:
    def __init__(self, *, journal: Journal, authority: GitAuthority) -> None:
        self._journal = journal
        self._authority = authority

    @property
    def profile(self) -> EffectProfile:
        return EffectProfile(
            kind="merge_verified",
            recovery="reconcilable",
            simulation="supported",
        )

    async def execute(self, request: EffectRequest) -> EffectReceipt:
        subject = self._verified_subject(request)
        outcome = self._authority.install(subject, request.idempotency_key)
        if outcome.installed:
            return EffectReceipt(
                request_hash=request_hash(request),
                status="committed",
                external_reference=str(subject.merge_commit),
                observed_state={
                    "target_ref": subject.target_ref,
                    "merge_commit": str(subject.merge_commit),
                },
            )
        return EffectReceipt(
            request_hash=request_hash(request),
            status="rejected",
            external_reference=None,
            observed_state={
                "target_ref": subject.target_ref,
                "expected_base": str(subject.expected_base),
                "found_base": str(outcome.found_base),
            },
        )

    async def reconcile(self, request: EffectRequest) -> EffectReceipt | None:
        subject = MergeSubject.model_validate(request.subject)
        committed = self._authority.reconcile_install(subject, request.idempotency_key)
        if committed:
            return EffectReceipt(
                request_hash=request_hash(request),
                status="committed",
                external_reference=str(subject.merge_commit),
                observed_state={
                    "target_ref": subject.target_ref,
                    "merge_commit": str(subject.merge_commit),
                },
            )
        return None

    async def simulate(self, request: EffectRequest) -> EffectReceipt:
        subject = self._verified_subject(request)
        return EffectReceipt(
            request_hash=request_hash(request),
            status="simulated",
            external_reference=str(subject.merge_commit),
            observed_state={
                "target_ref": subject.target_ref,
                "merge_commit": str(subject.merge_commit),
                "external_transition": False,
            },
        )

    def _verified_subject(self, request: EffectRequest) -> MergeSubject:
        subject = MergeSubject.model_validate(request.subject)
        if request.attestation_id is None:
            raise ContractViolation(
                "merge_verified requires an attestation id — authority is never implicit"
            )
        attestation = self._journal.load_attestation(request.attestation_id)
        if attestation is None:
            raise AdmissionError(
                [
                    f"merge refused: attestation {request.attestation_id!r} is not "
                    "journal-minted — a caller-authored claim cannot authorize a merge"
                ]
            )
        faults: list[str] = []
        if attestation.action != "merge":
            faults.append(
                f"attestation {attestation.attestation_id!r} authorizes "
                f"{attestation.action!r}, not a merge"
            )
        if attestation.subject != subject:
            faults.append(
                "attestation does not authorize this exact merge subject — "
                "identity mismatch is refused, never repaired silently"
            )
        if attestation.manifest_hash != request.manifest_hash:
            faults.append(
                f"attested world {attestation.manifest_hash} differs from the "
                f"invoking manifest {request.manifest_hash} — an unrelated world "
                "cannot authorize this subject"
            )
        if not attestation.ok:
            failing = [check.name for check in attestation.checks if not check.ok] or ["<none>"]
            faults.append(f"attestation checks failing: {failing}")
        if not faults:
            authority = self._authority
            if authority.tree_of(subject.merge_commit) != subject.tested_tree:
                faults.append(
                    f"merge commit {subject.merge_commit} does not carry the "
                    f"tested tree {subject.tested_tree}"
                )
            parents = authority.parents_of(subject.merge_commit)
            if parents != (subject.expected_base, subject.candidate):
                faults.append(
                    f"merge commit parents {parents} are not "
                    f"(expected_base, candidate)"
                )
        if faults:
            raise AdmissionError(faults)
        return subject
