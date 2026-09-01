"""In-memory ControlStore ledger test double (I6).

It exercises the same claim/plan/fence/replay and standalone-approval laws as
SQLite.  It deliberately is not a ``ControlPlaneStore``: channel history lives
in another object, so claiming their writes are one transaction would be false.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from threading import Lock
from typing import cast

from constructicon.core.control import (
    AuthenticatedActor,
    CommandClaim,
    CommandClaimResult,
    CommandRecord,
    HistoricalResumePlanEvidence,
    command_id_for,
    command_request_hash,
    validate_idempotency_key,
    validated_new_resume_command_plan,
)
from constructicon.core.effect import ApprovalRecord
from constructicon.core.envelope import utc_now
from constructicon.core.errors import JournalDamaged
from constructicon.core.human import (
    validated_command_approval,
    validated_standalone_command_approval,
)
from constructicon.core.identity import Digest, JsonValue, canonical_json
from constructicon.core.run import OwnershipLost


class InMemoryControlStore:
    def __init__(self, *, now_fn: Callable[[], datetime] = utc_now) -> None:
        self._now = now_fn
        self._commands: dict[str, CommandRecord] = {}
        self._approvals: dict[str, ApprovalRecord] = {}
        self._approval_command_by_id: dict[str, str] = {}
        self._approval_id_by_command: dict[str, str] = {}
        self._lock = Lock()

    def claim_command(
        self,
        *,
        actor: AuthenticatedActor,
        operation: str,
        idempotency_key: str,
        request_hash: Digest,
        request: JsonValue,
        owner_id: str,
        ttl_s: float,
    ) -> CommandClaimResult:
        validate_idempotency_key(idempotency_key)
        if request_hash != command_request_hash(request):
            raise ValueError("request_hash does not match the canonical command request")
        durable_request, request_json = _durable_json(request)
        command_id = command_id_for(actor.actor_id, operation, idempotency_key)
        with self._lock:
            existing = self._commands.get(command_id)
            if existing is not None:
                if (
                    existing.actor.actor_id != actor.actor_id
                    or existing.operation != operation
                    or existing.idempotency_key != idempotency_key
                    or existing.request_hash != request_hash
                    or canonical_json(existing.request) != request_json
                ):
                    return CommandClaimResult(
                        status="conflict",
                        record=_detached_command(existing),
                    )
                if existing.state in ("committed", "rejected"):
                    return CommandClaimResult(
                        status="replayed",
                        record=_detached_command(existing),
                    )
                now = self._now()
                if existing.lease_expires_at is not None and existing.lease_expires_at > now:
                    return CommandClaimResult(
                        status="in_progress",
                        record=_detached_command(existing),
                    )
                epoch = existing.owner_epoch + 1
                expires_at = now + timedelta(seconds=ttl_s)
                updated = existing.model_copy(
                    update={
                        "owner_id": owner_id,
                        "owner_epoch": epoch,
                        "lease_expires_at": expires_at,
                        "updated_at": now,
                    }
                )
                self._commands[command_id] = updated
                return CommandClaimResult(
                    status="claimed",
                    claim=CommandClaim(
                        command_id=command_id,
                        actor_id=actor.actor_id,
                        operation=operation,
                        owner_id=owner_id,
                        epoch=epoch,
                        expires_at=expires_at,
                    ),
                    record=_detached_command(updated),
                )

            now = self._now()
            expires_at = now + timedelta(seconds=ttl_s)
            record = CommandRecord(
                command_id=command_id,
                actor=actor,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                request=durable_request,
                state="prepared",
                plan=None,
                response=None,
                owner_id=owner_id,
                owner_epoch=1,
                lease_expires_at=expires_at,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )
            self._commands[command_id] = record
            return CommandClaimResult(
                status="claimed",
                claim=CommandClaim(
                    command_id=command_id,
                    actor_id=actor.actor_id,
                    operation=operation,
                    owner_id=owner_id,
                    epoch=1,
                    expires_at=expires_at,
                ),
                record=_detached_command(record),
            )

    def store_command_plan(self, claim: CommandClaim, plan: JsonValue) -> None:
        durable_plan, plan_json = _durable_json(plan)
        with self._lock:
            record = self._fenced(claim)
            if record.plan is None:
                planned = record.model_copy(
                    update={"plan": durable_plan, "updated_at": self._now()}
                )
                validated_new_resume_command_plan(planned)
                self._commands[claim.command_id] = planned
                return
            if canonical_json(record.plan) != plan_json:
                raise JournalDamaged(
                    f"command {claim.command_id!r} already carries a different plan"
                )

    def complete_command(self, claim: CommandClaim, response: JsonValue) -> CommandRecord:
        return self._terminal(claim, response, "committed")

    def reject_command(self, claim: CommandClaim, response: JsonValue) -> CommandRecord:
        return self._terminal(claim, response, "rejected")

    def command(self, command_id: str) -> CommandRecord | None:
        with self._lock:
            record = self._commands.get(command_id)
            return _detached_command(record) if record is not None else None

    def historical_resume_plan_evidence(
        self,
        command_id: str,
    ) -> HistoricalResumePlanEvidence | None:
        """The current-only in-memory store never contains migrated plans."""

        return None

    def latest_command_key(self, *, operation: str) -> tuple[str, str] | None:
        with self._lock:
            keys = [
                (record.created_at.isoformat(), record.command_id)
                for record in self._commands.values()
                if record.operation == operation
            ]
        return max(keys) if keys else None

    def committed_commands(
        self,
        *,
        operation: str,
        after: tuple[str, str] | None,
        through: tuple[str, str],
        limit: int,
    ) -> tuple[CommandRecord, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        with self._lock:
            records = tuple(
                sorted(
                    (
                        record
                        for record in self._commands.values()
                        if record.operation == operation
                        and record.state == "committed"
                        and record.completed_at is not None
                        and (record.created_at.isoformat(), record.command_id) <= through
                        and (
                            after is None
                            or (record.created_at.isoformat(), record.command_id) > after
                        )
                    ),
                    # Order by the SAME key the bounds compare on, or a mixed
                    # UTC offset would sort differently from the durable store.
                    key=lambda record: (record.created_at.isoformat(), record.command_id),
                )
            )
        return tuple(_detached_command(record) for record in records[:limit])

    def command_records(
        self,
        *,
        operation: str,
        after: tuple[str, str] | None,
        through: tuple[str, str],
        limit: int,
    ) -> tuple[CommandRecord, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        with self._lock:
            records = tuple(
                sorted(
                    (
                        record
                        for record in self._commands.values()
                        if record.operation == operation
                        and (record.created_at.isoformat(), record.command_id) <= through
                        and (
                            after is None
                            or (record.created_at.isoformat(), record.command_id) > after
                        )
                    ),
                    key=lambda record: (record.created_at.isoformat(), record.command_id),
                )
            )
        return tuple(_detached_command(record) for record in records[:limit])

    def store_approval(self, claim: CommandClaim, approval: ApprovalRecord) -> ApprovalRecord:
        with self._lock:
            self._approval_fenced(claim, approval)
            existing = self._approvals.get(approval.approval_id)
            if existing is None:
                owned = self._approval_id_by_command.get(claim.command_id)
                if owned is not None:
                    raise JournalDamaged(
                        f"command {claim.command_id!r} already wrote a different approval"
                    )
                self._approvals[approval.approval_id] = approval
                self._approval_command_by_id[approval.approval_id] = claim.command_id
                self._approval_id_by_command[claim.command_id] = approval.approval_id
                return approval
            if (
                existing != approval
                or self._approval_command_by_id.get(approval.approval_id) != claim.command_id
            ):
                raise JournalDamaged(
                    f"approval {approval.approval_id!r} was rewritten contradictorily"
                )
            return existing

    def _approval_fenced(
        self,
        claim: CommandClaim,
        approval: ApprovalRecord,
    ) -> CommandRecord:
        """Fence one approval under the exact actor its command authenticated."""

        record = self._fenced(claim)
        validated_standalone_command_approval(record, approval)
        return record

    def approval_for_command(self, command_id: str) -> ApprovalRecord | None:
        with self._lock:
            approval_id = self._approval_id_by_command.get(command_id)
            if approval_id is None:
                if command_id in self._approval_command_by_id.values():
                    raise JournalDamaged(
                        f"approval indexes disagree for command {command_id!r}"
                    )
                return None
            return self._project_approval(
                approval_id,
                expected_command_id=command_id,
            )

    def approval(self, approval_id: str) -> ApprovalRecord | None:
        with self._lock:
            if approval_id not in self._approvals:
                if approval_id in self._approval_command_by_id:
                    raise JournalDamaged(
                        f"approval {approval_id!r} has provenance but no record"
                    )
                return None
            return self._project_approval(approval_id)

    def _project_approval(
        self,
        approval_id: str,
        *,
        expected_command_id: str | None = None,
    ) -> ApprovalRecord:
        """Project one approval only beside its exact owning command."""

        approval = self._approvals.get(approval_id)
        command_id = self._approval_command_by_id.get(approval_id)
        if approval is None or command_id is None:
            raise JournalDamaged(f"approval {approval_id!r} has incomplete provenance")
        if expected_command_id is not None and command_id != expected_command_id:
            raise JournalDamaged(
                f"approval {approval_id!r} belongs to command {command_id!r}, "
                f"not {expected_command_id!r}"
            )
        if self._approval_id_by_command.get(command_id) != approval_id:
            raise JournalDamaged(f"approval indexes disagree for command {command_id!r}")
        command = self._commands.get(command_id)
        if command is None:
            raise JournalDamaged(
                f"approval {approval_id!r} names missing command {command_id!r}"
            )
        return validated_command_approval(command, approval)

    def _fenced(self, claim: CommandClaim) -> CommandRecord:
        record = self._commands.get(claim.command_id)
        if record is None:
            raise JournalDamaged(f"unknown command {claim.command_id!r}")
        if record.actor.actor_id != claim.actor_id or record.operation != claim.operation:
            raise JournalDamaged(
                f"command claim {claim.command_id!r} contradicts its durable identity"
            )
        if (
            record.state != "prepared"
            or record.owner_id != claim.owner_id
            or record.owner_epoch != claim.epoch
        ):
            raise OwnershipLost(
                f"command {claim.command_id!r} is no longer owned by "
                f"{claim.owner_id!r} epoch {claim.epoch}"
            )
        return record

    def _terminal(
        self,
        claim: CommandClaim,
        response: JsonValue,
        state: str,
    ) -> CommandRecord:
        durable_response, response_json = _durable_json(response)
        with self._lock:
            record = self._commands.get(claim.command_id)
            if record is None:
                raise JournalDamaged(f"unknown command {claim.command_id!r}")
            if state == "rejected" and claim.command_id in self._approval_id_by_command:
                raise JournalDamaged(
                    f"command {claim.command_id!r} cannot be rejected after writing an approval"
                )
            if record.state in ("committed", "rejected"):
                if (
                    record.state == state
                    and canonical_json(record.response) == response_json
                ):
                    return _detached_command(record)
                raise JournalDamaged(
                    f"command {claim.command_id!r} already has a contradictory terminal response"
                )
            record = self._fenced(claim)
            if record.plan is None:
                raise JournalDamaged(
                    f"command {claim.command_id!r} cannot become terminal without an immutable plan"
                )
            now = self._now()
            updated = record.model_copy(
                update={
                    "state": state,
                    "response": durable_response,
                    "owner_id": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                    "completed_at": now,
                }
            )
            self._commands[claim.command_id] = updated
            return _detached_command(updated)


def _durable_json(value: JsonValue) -> tuple[JsonValue, str]:
    """Detach one JSON value and retain the bytes that define exact equality."""

    encoded = canonical_json(value)
    return cast(JsonValue, json.loads(encoded)), encoded


def _detached_command(record: CommandRecord) -> CommandRecord:
    """Return a snapshot whose mutable JSON cannot rewrite the in-memory ledger."""

    if record.state in {"committed", "rejected"} and record.plan is None:
        raise JournalDamaged(
            f"terminal command {record.command_id!r} has no immutable plan"
        )
    return record.model_copy(deep=True)
