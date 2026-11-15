"""One admission and acquisition law for the closed live-run permits.

The models retain their own fields and validators: declaration order is wire
format. Imports in their delegating methods keep this closed union acyclic.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.control import command_id_for, run_id_for_command
from constructicon.core.grants import EffectiveGrants, Posture
from constructicon.core.identity import Digest, canonical_json
from constructicon.core.maintenance import (
    ChannelReplyAttemptAuthorization,
    MaintenanceAttemptAuthorization,
    MaintenanceAuthorization,
)
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.refusal import RefusalCode

Permit = QualificationAuthorization | MaintenanceAuthorization
_PERMIT_TYPES = (
    QualificationAuthorization, MaintenanceAttemptAuthorization, ChannelReplyAttemptAuthorization,
)


class PermitFault(StrEnum):
    """The ten acquisition checks, in their established refusal order."""

    RUN = "run"
    INVOCATION = "invocation"
    BINDING = "binding"
    SOURCE_GRAPH = "source_graph"
    CAPABILITY = "capability"
    REVISION = "revision"
    OPERATOR_BINDING = "operator_binding"
    GRANTS = "grants"
    EPOCH = "epoch"
    EXPIRED = "expired"

    @property
    def refusal(self) -> RefusalCode:
        """The code for this actual failed check, without inspecting its sentence."""
        return {
            PermitFault.RUN: RefusalCode.PERMIT_RUN,
            PermitFault.INVOCATION: RefusalCode.PERMIT_INVOCATION,
            PermitFault.BINDING: RefusalCode.PERMIT_BINDING,
            PermitFault.SOURCE_GRAPH: RefusalCode.PERMIT_SOURCE_GRAPH,
            PermitFault.CAPABILITY: RefusalCode.PERMIT_CAPABILITY,
            PermitFault.REVISION: RefusalCode.PERMIT_REVISION,
            PermitFault.OPERATOR_BINDING: RefusalCode.PERMIT_OPERATOR_BINDING,
            PermitFault.GRANTS: RefusalCode.PERMIT_GRANTS,
            PermitFault.EPOCH: RefusalCode.PERMIT_EPOCH,
            PermitFault.EXPIRED: RefusalCode.PERMIT_EXPIRED,
        }[self]

    def sentence(self, *, epoch: str) -> str:
        """Render the retained wording, including the model's epoch sentence."""
        return {
            PermitFault.RUN: "a different run",
            PermitFault.INVOCATION: "a different invocation",
            PermitFault.BINDING: "a different binding",
            PermitFault.SOURCE_GRAPH: "a different source graph",
            PermitFault.CAPABILITY: "a different capability",
            PermitFault.REVISION: "a different adapter revision",
            PermitFault.OPERATOR_BINDING: "a different operator binding",
            PermitFault.GRANTS: "other grants",
            PermitFault.EPOCH: epoch,
            PermitFault.EXPIRED: "an expired authorization",
        }[self]


def _require_permit(permit: Permit) -> None:
    if type(permit) not in _PERMIT_TYPES:
        raise TypeError("the permit law requires a closed authorization type")


def fault_sentences(permit: Permit, found: tuple[PermitFault, ...]) -> tuple[str, ...]:
    """Render once-evaluated faults in the permit's retained vocabulary."""
    _require_permit(permit)
    if type(permit) is QualificationAuthorization:
        prefix, epoch = "qualification", "an acquisition beyond the authorized epochs"
    else:
        prefix, epoch = "maintenance", "an acquisition outside the authorized epoch"
    return tuple(f"{prefix} refuses {fault.sentence(epoch=epoch)}" for fault in found)


def run_id(permit: Permit) -> RunId:
    """The one runs_start identity fixed by the trusted actor and key."""
    _require_permit(permit)
    return run_id_for_command(command_id_for(permit.actor_id, "runs_start", permit.idempotency_key))


def admits(
    permit: Permit, *, source_graph_hash: Digest, capability_id: str, revision: str,
) -> bool:
    """Timeless exact admission; acquisition owns the attempt and window."""
    _require_permit(permit)
    return (
        source_graph_hash == permit.source_graph_hash
        and capability_id == permit.capability_id
        and revision == permit.revision
    )


def faults(
    permit: Permit, *, run_id: RunId, path: ExecutionPath, binding: str,
    source_graph_hash: Digest | None, capability_id: str, revision: str,
    operator_binding_digest: Digest, grants: EffectiveGrants, epoch: int, now: datetime,
) -> tuple[PermitFault, ...]:
    """Every failed acquisition check; absent no-dispatch grant pins match."""
    _require_permit(permit)
    pinned = permit.grants is None or canonical_json(grants) == canonical_json(permit.grants)
    checks = (
        (run_id == permit.run_id, PermitFault.RUN),
        (path == ExecutionPath(scope=permit.scope), PermitFault.INVOCATION),
        (binding == permit.binding, PermitFault.BINDING),
        (source_graph_hash == permit.source_graph_hash, PermitFault.SOURCE_GRAPH),
        (capability_id == permit.capability_id, PermitFault.CAPABILITY),
        (revision == permit.revision, PermitFault.REVISION),
        (operator_binding_digest == permit.operator_binding_digest, PermitFault.OPERATOR_BINDING),
        (pinned, PermitFault.GRANTS),
        # Producer: substrate/journal/_sqlite_execution.py:259-264,321
        # validates a nonnegative integer owner epoch, then returns it plus one.
        (type(epoch) is int and 1 <= epoch <= permit.max_epoch, PermitFault.EPOCH),
        (now < permit.not_after, PermitFault.EXPIRED),
    )
    return tuple(fault for held, fault in checks if not held)


def fixed_write_grants(grants: EffectiveGrants) -> bool:
    """The bounded WRITE grant shape shared by qualification and maintenance."""
    return not (
        grants.posture is not Posture.WRITE
        or grants.model_selection.kind != "explicit"
        or not (grants.model_selection.model or "").strip()
        or not (grants.effort or "").strip()
        or grants.allowed_tools != ("contained_python",)
        or grants.env_allowlist != ()
        or grants.network != "allow"
        or grants.timeout_s != 300
    )
