"""In-memory ControlStore test double (I6).

It exercises the same claim/plan/fence/replay law as the SQLite implementation;
no MCP-specific state lives here.
"""

from __future__ import annotations

from datetime import timedelta
from threading import Lock
from typing import Callable

from constructicon.core.control import (
    AuthenticatedActor,
    CommandClaim,
    CommandClaimResult,
    CommandRecord,
    command_id_for,
)
from constructicon.core.effect import ApprovalRecord
from constructicon.core.envelope import utc_now
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, JsonValue


class InMemoryControlStore:
    def __init__(self, *, now_fn: Callable = utc_now) -> None:
        self._now = now_fn
        self._commands: dict[str, CommandRecord] = {}
        self._approvals: dict[str, ApprovalRecord] = {}
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
        now = self._now()
        command_id = command_id_for(actor.actor_id, operation, idempotency_key)
        with self._lock:
            existing = self._commands.get(command_id)
            if existing is not None:
                if (
                    existing.actor.actor_id != actor.actor_id
                    or existing.operation != operation
                    or existing.idempotency_key != idempotency_key
                    or existing.request_hash != request_hash
                    or existing.request != request
                ):
                    return CommandClaimResult(status="conflict", record=existing)
                if existing.state in ("committed", "rejected"):
                    return CommandClaimResult(status="replayed", record=existing)
                if (
                    existing.lease_expires_at is not None
                    and existing.lease_expires_at > now
                    and existing.owner_id != owner_id
                ):
                    return CommandClaimResult(status="in_progress", record=existing)
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
                    record=updated,
                )

            expires_at = now + timedelta(seconds=ttl_s)
            record = CommandRecord(
                command_id=command_id,
                actor=actor,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                request=request,
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
                record=record,
            )

    def store_command_plan(self, claim: CommandClaim, plan: JsonValue) -> None:
        with self._lock:
            record = self._fenced(claim)
            if record.plan is None:
                self._commands[claim.command_id] = record.model_copy(
                    update={"plan": plan, "updated_at": self._now()}
                )
                return
            if record.plan != plan:
                raise JournalDamaged(
                    f"command {claim.command_id!r} already carries a different plan"
                )

    def complete_command(self, claim: CommandClaim, response: JsonValue) -> CommandRecord:
        return self._terminal(claim, response, "committed")

    def reject_command(self, claim: CommandClaim, response: JsonValue) -> CommandRecord:
        return self._terminal(claim, response, "rejected")

    def command(self, command_id: str) -> CommandRecord | None:
        with self._lock:
            return self._commands.get(command_id)

    def store_approval(self, claim: CommandClaim, approval: ApprovalRecord) -> ApprovalRecord:
        with self._lock:
            self._fenced(claim)
            existing = self._approvals.get(approval.approval_id)
            if existing is None:
                self._approvals[approval.approval_id] = approval
                return approval
            if existing != approval:
                raise JournalDamaged(
                    f"approval {approval.approval_id!r} was rewritten contradictorily"
                )
            return existing

    def approval(self, approval_id: str) -> ApprovalRecord | None:
        with self._lock:
            return self._approvals.get(approval_id)

    def _fenced(self, claim: CommandClaim) -> CommandRecord:
        record = self._commands.get(claim.command_id)
        if record is None:
            raise JournalDamaged(f"unknown command {claim.command_id!r}")
        if (
            record.state != "prepared"
            or record.owner_id != claim.owner_id
            or record.owner_epoch != claim.epoch
        ):
            raise JournalDamaged(
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
        with self._lock:
            record = self._commands.get(claim.command_id)
            if record is None:
                raise JournalDamaged(f"unknown command {claim.command_id!r}")
            if record.state in ("committed", "rejected"):
                if record.state == state and record.response == response:
                    return record
                raise JournalDamaged(
                    f"command {claim.command_id!r} already has a contradictory terminal response"
                )
            record = self._fenced(claim)
            now = self._now()
            updated = record.model_copy(
                update={
                    "state": state,
                    "response": response,
                    "owner_id": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                    "completed_at": now,
                }
            )
            self._commands[claim.command_id] = updated
            return updated
