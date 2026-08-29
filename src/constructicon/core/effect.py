"""The effect chain (I2, I13): evidence -> authority -> outcome.

Every externally visible transition crosses one adapter. M6 adds truthful
simulation for counterfactual runs: simulated requests have a distinct identity
namespace and call ``simulate`` only — never ``execute`` or ``reconcile``.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from constructicon.core.address import ExecutionPath, GitSha, RunId
from constructicon.core.channel import ChannelContract, ChannelInteraction
from constructicon.core.control import AuthenticatedActor
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
EffectMode = Literal["live", "simulated"]


class CheckResult(BaseModel):
    """One observed check outcome; ``status`` and ``ok`` stay in lockstep."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: CheckStatus
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
    model_config = ConfigDict(frozen=True)

    kind: Literal["git_merge"] = "git_merge"
    repository: str
    target_ref: str
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


class ChannelSendSubject(BaseModel):
    """Every value a channel adapter could otherwise redirect or substitute.

    Both halves of the exchange are sealed here. An actor able to vary
    ``reply_contract`` after the fact could change what the parked run is
    required to accept, so the reply's admissible type is authority, not
    configuration.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["channel_send"] = "channel_send"
    message_id: Digest
    channel_id: str
    channel_revision: str
    lane: str
    interaction: ChannelInteraction
    recipient_actor_id: str | None
    run_id: RunId
    path: ExecutionPath
    port: str
    contract: ChannelContract
    reply_port: str
    reply_contract: ChannelContract
    payload_digest: Digest


ProofSubject = MergeSubject | ComponentProofSubject | ChannelSendSubject
EffectAction = Literal["merge", "promote", "send"]


class AttestationDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: EffectAction
    subject: ProofSubject
    checks: tuple[CheckResult, ...]
    check_set_hash: Digest
    evidence: tuple[EvidenceRef, ...] = ()
    manifest_hash: Digest
    workspace_id: str | None = None


def attestation_id_for(draft: AttestationDraft) -> str:
    body = digest("attestation", 1, draft.model_dump(mode="json"))
    return f"att-{str(body).removeprefix('sha256:')}"


class Attestation(BaseModel):
    model_config = ConfigDict(frozen=True)

    attestation_id: str
    action: EffectAction
    subject: ProofSubject
    checks: tuple[CheckResult, ...]
    check_set_hash: Digest
    evidence: tuple[EvidenceRef, ...]
    manifest_hash: Digest
    created_by_run: RunId | None
    workspace_id: str | None
    created_at: AwareDatetime

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)


class ApprovalRecord(BaseModel):
    """One authenticated human decision, write-once and exact-subject bound."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str
    subject: ProofSubject
    decision: Literal["approved", "rejected"]
    reason: str | None = None
    actor: AuthenticatedActor
    run_id: RunId
    created_at: AwareDatetime


class EffectProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    recovery: Literal["native_idempotency", "reconcilable"]
    simulation: Literal["supported", "unsupported"] = "unsupported"


class EffectRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: RunId
    manifest_hash: Digest
    path: ExecutionPath
    kind: str
    subject: dict[str, Any]
    idempotency_key: Digest
    attestation_id: str | None = None
    mode: EffectMode = "live"


class EffectReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_hash: Digest
    status: Literal["committed", "rejected", "unknown", "simulated"]
    external_reference: str | None
    observed_state: dict[str, Any] | None


def idempotency_key(
    manifest_hash: Digest,
    path: ExecutionPath,
    kind: str,
    subject: dict[str, Any],
    *,
    mode: EffectMode = "live",
) -> Digest:
    """Compute one request identity without changing historical live keys."""

    payload = {
        "manifest_hash": str(manifest_hash),
        "path": path.model_dump(mode="json"),
        "kind": kind,
        "subject": subject,
    }
    if mode == "live":
        return digest("idempotency", 1, payload)
    return digest("idempotency-simulated", 1, payload)


def request_hash(request: EffectRequest) -> Digest:
    return digest("effect-request", 1, request.model_dump(mode="json"))


class EffectAdapter(Protocol):
    @property
    def profile(self) -> EffectProfile: ...

    async def execute(self, request: EffectRequest) -> EffectReceipt: ...

    async def reconcile(self, request: EffectRequest) -> EffectReceipt | None: ...

    async def simulate(self, request: EffectRequest) -> EffectReceipt: ...
