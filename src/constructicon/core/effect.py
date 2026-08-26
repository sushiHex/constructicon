"""The effect chain (I2, I13): evidence -> authority -> outcome.

ONE mechanism for every externally visible action — merge, open/update PR,
mailbox send, artifact publish, stable-pointer move, approval, CI trigger:

    CheckResult   what a check observed (a Gate is one producer of
                  CheckResults; a promotion evaluator is another — "gate"
                  keeps one meaning)
    Attestation   trusted deterministic policy authorizes THIS action on THIS
                  subject; journal-minted, referenced by id, never
                  caller-supplied
    EffectReceipt what actually happened

Effects are at-least-once, bounded by idempotency. Every effect adapter
declares an ``EffectProfile`` — an effect that is neither natively idempotent
nor reconcilable is not admittable. Recovery law: prepared + no receipt ->
reconcile externally: found -> record committed receipt; absent -> execute;
indeterminate -> PARKED/operator_intervention. NEVER blindly repeat an unknown
external effect — resume recovers the first PR, it never opens a second.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from constructicon.core.address import ExecutionPath, GitSha, RunId
from constructicon.core.envelope import EvidenceRef
from constructicon.core.identity import Digest, digest

CheckStatus = Literal[
    "passed",
    "failed",
    "conflict",
    "timeout",
    "cancelled",
    "infrastructure_error",
]


class CheckResult(BaseModel):
    """One observed check outcome. ``status`` distinguishes a candidate that
    failed from infrastructure that never ran (I4 — a missing executable is
    not a failing test); ``ok`` is its boolean shadow, kept in lockstep so
    M1/M2 attestation JSON (which carried only ``ok``) still loads."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: CheckStatus
    # the validator below always sets this from status (or vice versa); the
    # default only satisfies constructors that pass status alone
    ok: bool = False
    detail: str
    elapsed_s: float

    @model_validator(mode="before")
    @classmethod
    def _sync_status_and_ok(cls, data: Any) -> Any:
        if isinstance(data, dict):
            status, ok = data.get("status"), data.get("ok")
            if status is None and ok is not None:
                data["status"] = "passed" if ok else "failed"
            elif status is not None and ok is None:
                data["ok"] = status == "passed"
            elif status is not None and ok is not None and ok != (status == "passed"):
                raise ValueError(
                    f"check {data.get('name')!r}: ok={ok} contradicts status={status!r}"
                )
        return data


class MergeSubject(BaseModel):
    """The complete identity of one merge: that exact commit into that exact
    ref. One subject everywhere — prepared merge, attestation, effect
    request, idempotency, reconcile, receipt."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["git_merge"] = "git_merge"
    repository: str
    target_ref: str  # always fully qualified ("refs/heads/main"), never shorthand
    candidate: GitSha
    expected_base: GitSha
    merge_commit: GitSha
    tested_tree: GitSha


class ComponentProofSubject(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["component"] = "component"
    component: str
    version: Digest
    baseline_version: Digest | None


ProofSubject = MergeSubject | ComponentProofSubject


class AttestationDraft(BaseModel):
    """What an attesting caller may author. The journal computes identity and
    provenance (id, created_by_run, created_at) — minting is literal (I2)."""

    model_config = ConfigDict(frozen=True)

    action: Literal["merge", "promote"]
    subject: ProofSubject
    checks: tuple[CheckResult, ...]
    check_set_hash: Digest  # exact check/evaluator defs + config revisions
    evidence: tuple[EvidenceRef, ...] = ()
    manifest_hash: Digest  # the attesting run's sealed world (I12)
    workspace_id: str | None = None


def attestation_id_for(draft: AttestationDraft) -> str:
    """Content-derived identity — timestamps excluded, never caller-selected."""
    body = digest("attestation", 1, draft.model_dump(mode="json"))
    return f"att-{str(body).removeprefix('sha256:')}"


class Attestation(BaseModel):
    model_config = ConfigDict(frozen=True)

    attestation_id: str
    action: Literal["merge", "promote"]
    subject: ProofSubject
    checks: tuple[CheckResult, ...]
    check_set_hash: Digest  # exact check/evaluator defs + config revisions
    evidence: tuple[EvidenceRef, ...]
    manifest_hash: Digest  # the attesting run's sealed world (I12)
    created_by_run: RunId | None  # None for run-less deterministic policies
    workspace_id: str | None
    created_at: AwareDatetime

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)


class ApprovalRecord(BaseModel):
    """The discretionary attestation — reserved for authenticated humans."""

    model_config = ConfigDict(frozen=True)

    approval_id: str
    subject: ProofSubject
    actor: str
    run_id: RunId
    created_at: AwareDatetime


class EffectProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    recovery: Literal["native_idempotency", "reconcilable"]


class EffectRequest(BaseModel):
    """Sealed by the effect boundary: ``run_id`` and ``manifest_hash`` are
    supplied by the walker from the active run — never by the node — so an
    adapter can bind authority to the invoking sealed world."""

    model_config = ConfigDict(frozen=True)

    run_id: RunId
    manifest_hash: Digest
    path: ExecutionPath
    kind: str
    subject: dict[str, Any]
    idempotency_key: Digest  # computed only — see idempotency_key()
    attestation_id: str | None = None  # required for authority-bearing kinds


class EffectReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_hash: Digest
    status: Literal["committed", "rejected", "unknown"]
    external_reference: str | None
    observed_state: dict[str, Any] | None


def idempotency_key(
    manifest_hash: Digest, path: ExecutionPath, kind: str, subject: dict[str, Any]
) -> Digest:
    """The idempotency key is computed, never caller-authored."""
    return digest(
        "idempotency",
        1,
        {
            "manifest_hash": str(manifest_hash),
            "path": path.model_dump(mode="json"),
            "kind": kind,
            "subject": subject,
        },
    )


def request_hash(request: EffectRequest) -> Digest:
    return digest("effect-request", 1, request.model_dump(mode="json"))


class EffectAdapter(Protocol):
    """A deterministic boundary for one kind of external transition."""

    @property
    def profile(self) -> EffectProfile: ...

    async def execute(self, request: EffectRequest) -> EffectReceipt: ...

    async def reconcile(self, request: EffectRequest) -> EffectReceipt | None:
        """Find the prior external outcome for this request, if any."""
        ...
