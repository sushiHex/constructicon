"""The effect chain (I2, I13): evidence -> authority -> outcome.

Every externally visible transition crosses one adapter. M6 adds truthful
simulation for counterfactual runs: simulated requests have a distinct identity
namespace and call ``simulate`` only — never ``execute`` or ``reconcile``.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from constructicon.core.address import ExecutionPath, GitSha, RunId
from constructicon.core.channel import (
    ChannelContract,
    ChannelInteraction,
    ChannelMessage,
    ChannelSendIntent,
    message_for_intent,
    same_message,
)
from constructicon.core.control import AuthenticatedActor
from constructicon.core.envelope import EvidenceRef
from constructicon.core.identity import ActorId, Digest, canonical_json, digest, json_value

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


class HistoricalGitProofSubject(BaseModel):
    """Read-only M1/M2 git proof shape retained for journal compatibility.

    It is deliberately excluded from ``ProofSubject`` and therefore cannot be
    minted by any current attestation or approval surface.  Historical rows
    remain truthfully decodable without pretending their weaker subject was a
    current exact-merge-tree proof.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["git"] = "git"
    repository: str
    commit: GitSha
    base: GitSha | None = None
    tested_tree: GitSha | None = None


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
    recipient_actor_id: ActorId | None
    run_id: RunId
    path: ExecutionPath
    port: str
    contract: ChannelContract
    reply_port: str
    reply_contract: ChannelContract
    payload_digest: Digest


def channel_send_subject(intent: ChannelSendIntent) -> ChannelSendSubject:
    """Seal every value a channel adapter could redirect or substitute.

    Trusted runtime code mints an attestation over this; the adapter recomputes
    it from the intent it was handed and refuses any difference. Component code
    can never author one.
    """

    return ChannelSendSubject(
        message_id=intent.message_id,
        channel_id=intent.channel_id,
        channel_revision=intent.channel_revision,
        lane=intent.lane,
        interaction=intent.interaction,
        recipient_actor_id=intent.recipient_actor_id,
        run_id=intent.run_id,
        path=intent.path,
        port=intent.port,
        contract=intent.contract,
        reply_port=intent.reply_port,
        reply_contract=intent.reply_contract,
        payload_digest=digest("channel-payload", 1, intent.payload),
    )


ProofSubject = MergeSubject | ComponentProofSubject | ChannelSendSubject
AttestationSubject = ProofSubject | HistoricalGitProofSubject
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
    subject: AttestationSubject
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


def promotion_attestation_faults(
    attestation: Attestation,
    *,
    component: str,
    version: Digest,
    baseline: Digest | None,
    source_run: RunId | None,
) -> tuple[str, ...]:
    """Explain why one immutable proof cannot authorize one pointer edge.

    Promotion admission and durable registry projection use this same L0 law.
    A receipt may add observational metadata, but its component, baseline, and
    target must be exactly the edge the journal-minted proof evaluated.
    """

    faults: list[str] = []
    if attestation.action != "promote":
        faults.append(
            f"attestation {attestation.attestation_id!r} authorizes "
            f"{attestation.action!r}, not a promotion"
        )
    subject = attestation.subject
    if not isinstance(subject, ComponentProofSubject):
        faults.append("promotion attestation must carry a component subject")
    else:
        if subject.component != component:
            faults.append(
                f"attestation subject names {subject.component!r}, promotion targets {component!r}"
            )
        if subject.version != version:
            faults.append(
                f"attestation binds version {subject.version}, promotion targets "
                f"{version} — identity mismatch is refused, never repaired silently"
            )
        if subject.baseline_version != baseline:
            faults.append(
                f"attestation binds baseline {subject.baseline_version}, "
                f"promotion receipt names {baseline}"
            )
    if not attestation.ok:
        failing = [check.name for check in attestation.checks if not check.ok] or ["<none>"]
        faults.append(f"attestation checks failing: {failing}")
    if attestation.created_by_run != source_run:
        faults.append(
            f"attestation was created by {attestation.created_by_run}, "
            f"promotion receipt names source run {source_run}"
        )
    return tuple(faults)


def validated_channel_send_attestation(
    attestation: Attestation,
    intent: ChannelSendIntent,
    *,
    expected_manifest_hash: Digest,
) -> Attestation:
    """Prove one run-world attestation authorizes one exact send intent."""

    subject = attestation.subject
    if (
        attestation.action != "send"
        or not isinstance(subject, ChannelSendSubject)
        or not attestation.ok
        or attestation.created_by_run != intent.run_id
        or attestation.manifest_hash != expected_manifest_hash
    ):
        raise ValueError("attestation does not authorize this run-world channel send")
    expected = channel_send_subject(intent)
    if canonical_json(json_value(subject.model_dump(mode="json"))) != canonical_json(
        json_value(expected.model_dump(mode="json"))
    ):
        raise ValueError("attestation authorizes a different channel send intent")
    return attestation


def validated_attested_channel_request(
    attestation: Attestation,
    request: ChannelMessage,
    *,
    expected_manifest_hash: Digest,
) -> ChannelMessage:
    """Bind one retained request to the exact send authority that admitted it."""

    subject = attestation.subject
    if request.kind != "request" or not isinstance(subject, ChannelSendSubject):
        raise ValueError("channel send attestation does not govern a request")
    intent = ChannelSendIntent(
        message_id=subject.message_id,
        channel_id=subject.channel_id,
        channel_revision=subject.channel_revision,
        lane=subject.lane,
        interaction=subject.interaction,
        recipient_actor_id=subject.recipient_actor_id,
        contract=subject.contract,
        reply_contract=subject.reply_contract,
        run_id=subject.run_id,
        path=subject.path,
        port=subject.port,
        reply_port=subject.reply_port,
        payload=json_value(request.envelope.payload),
    )
    validated_channel_send_attestation(
        attestation,
        intent,
        expected_manifest_hash=expected_manifest_hash,
    )
    expected = message_for_intent(intent, created_at=request.envelope.created_at)
    if not same_message(request, expected):
        raise ValueError("channel request contradicts its send attestation")
    return request


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
