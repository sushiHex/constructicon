# mypy: disable-error-code="attr-defined"
"""Durable command-law and approval ledgers."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Literal, cast

from pydantic import TypeAdapter

from constructicon.core.address import RunId
from constructicon.core.control import (
    AuthenticatedActor,
    CommandClaim,
    CommandClaimResult,
    CommandRecord,
    command_id_for,
)
from constructicon.core.effect import ApprovalRecord, ProofSubject
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, JsonValue, canonical_json
from constructicon.core.run import OwnershipLost


class _SqliteControlMixin:
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
        expires = now + timedelta(seconds=ttl_s)
        command_id = command_id_for(actor.actor_id, operation, idempotency_key)
        request_json = canonical_json(request)
        with self._txn() as connection:
            row = connection.execute(
                "SELECT * FROM commands WHERE command_id = ?", (command_id,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO commands (command_id, actor_id, actor_json, operation,"
                    " idempotency_key, request_hash, request_json, state, owner_id,"
                    " owner_epoch, lease_expires_at, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, 'prepared', ?, 1, ?, ?, ?)",
                    (
                        command_id,
                        actor.actor_id,
                        actor.model_dump_json(),
                        operation,
                        idempotency_key,
                        str(request_hash),
                        request_json,
                        owner_id,
                        expires.isoformat(),
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                return CommandClaimResult(
                    status="claimed",
                    claim=CommandClaim(
                        command_id=command_id,
                        actor_id=actor.actor_id,
                        operation=operation,
                        owner_id=owner_id,
                        epoch=1,
                        expires_at=expires,
                    ),
                )
            record = self._command_from_row(row)
            if (
                record.actor.actor_id != actor.actor_id
                or record.operation != operation
                or record.idempotency_key != idempotency_key
                or record.request_hash != request_hash
                or canonical_json(record.request) != request_json
            ):
                return CommandClaimResult(status="conflict", record=record)
            if record.state in ("committed", "rejected"):
                return CommandClaimResult(status="replayed", record=record)
            if record.lease_expires_at is not None and record.lease_expires_at > now:
                return CommandClaimResult(status="in_progress", record=record)
            epoch = record.owner_epoch + 1
            connection.execute(
                "UPDATE commands SET owner_id = ?, owner_epoch = ?, lease_expires_at = ?,"
                " updated_at = ? WHERE command_id = ? AND state = 'prepared'",
                (owner_id, epoch, expires.isoformat(), now.isoformat(), command_id),
            )
            return CommandClaimResult(
                status="claimed",
                claim=CommandClaim(
                    command_id=command_id,
                    actor_id=actor.actor_id,
                    operation=operation,
                    owner_id=owner_id,
                    epoch=epoch,
                    expires_at=expires,
                ),
                record=record,
            )

    def store_command_plan(self, claim: CommandClaim, plan: JsonValue) -> None:
        plan_json = canonical_json(plan)
        with self._txn() as connection:
            row = self._command_fenced(connection, claim)
            if row["plan_json"] is not None:
                if row["plan_json"] == plan_json:
                    return
                raise JournalDamaged(
                    f"command {claim.command_id!r} already carries a different plan"
                )
            connection.execute(
                "UPDATE commands SET plan_json = ?, updated_at = ? WHERE command_id = ?",
                (plan_json, self._now_iso(), claim.command_id),
            )
        self.fault_probe("command.after_plan_commit")

    def complete_command(self, claim: CommandClaim, response: JsonValue) -> CommandRecord:
        return self._terminal_command(claim, response, "committed")

    def reject_command(self, claim: CommandClaim, response: JsonValue) -> CommandRecord:
        return self._terminal_command(claim, response, "rejected")

    def command(self, command_id: str) -> CommandRecord | None:
        with self._read() as connection:
            row = connection.execute(
                "SELECT * FROM commands WHERE command_id = ?", (command_id,)
            ).fetchone()
        return self._command_from_row(row) if row else None

    def latest_command_key(self, *, operation: str) -> tuple[str, str] | None:
        with self._read() as connection:
            row = connection.execute(
                "SELECT created_at, command_id FROM commands WHERE operation = ?"
                " ORDER BY created_at DESC, command_id DESC LIMIT 1",
                (operation,),
            ).fetchone()
        if row is None:
            return None
        return (str(row["created_at"]), str(row["command_id"]))

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
        clauses = [
            "operation = ?",
            "state = 'committed'",
            "completed_at IS NOT NULL",
            "(created_at < ? OR (created_at = ? AND command_id <= ?))",
        ]
        params: list[object] = [operation, through[0], through[0], through[1]]
        if after is not None:
            clauses.append("(created_at > ? OR (created_at = ? AND command_id > ?))")
            params.extend((after[0], after[0], after[1]))
        params.append(limit)
        with self._read() as connection:
            rows = connection.execute(
                "SELECT * FROM commands WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at, command_id LIMIT ?",
                tuple(params),
            ).fetchall()
        return tuple(self._command_from_row(row) for row in rows)

    def store_approval(self, claim: CommandClaim, approval: ApprovalRecord) -> ApprovalRecord:
        with self._txn() as connection:
            self._command_fenced(connection, claim)
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?", (approval.approval_id,)
            ).fetchone()
            if row is not None:
                existing = self._approval_from_row(row)
                if existing == approval and row["command_id"] == claim.command_id:
                    return existing
                raise JournalDamaged(
                    f"approval {approval.approval_id!r} was rewritten contradictorily"
                )
            connection.execute(
                "INSERT INTO approvals (approval_id, run_id, subject_json, decision,"
                " reason, actor_json, command_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    approval.approval_id,
                    approval.run_id,
                    canonical_json(approval.subject.model_dump(mode="json")),
                    approval.decision,
                    approval.reason,
                    approval.actor.model_dump_json(),
                    claim.command_id,
                    approval.created_at.isoformat(),
                ),
            )
        return approval

    def approval(self, approval_id: str) -> ApprovalRecord | None:
        with self._read() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
        return self._approval_from_row(row) if row else None

    def _terminal_command(
        self,
        claim: CommandClaim,
        response: JsonValue,
        state: Literal["committed", "rejected"],
    ) -> CommandRecord:
        response_json = canonical_json(response)
        now = self._now()
        with self._txn() as connection:
            row = connection.execute(
                "SELECT * FROM commands WHERE command_id = ?", (claim.command_id,)
            ).fetchone()
            if row is None:
                raise JournalDamaged(f"unknown command {claim.command_id!r}")
            existing = self._command_from_row(row)
            if existing.state in ("committed", "rejected"):
                if existing.state == state and canonical_json(existing.response) == response_json:
                    return existing
                raise JournalDamaged(
                    f"command {claim.command_id!r} already has a different terminal response"
                )
            self._command_fenced(connection, claim)
            connection.execute(
                "UPDATE commands SET state = ?, response_json = ?, owner_id = NULL,"
                " lease_expires_at = NULL, updated_at = ?, completed_at = ?"
                " WHERE command_id = ?",
                (
                    state,
                    response_json,
                    now.isoformat(),
                    now.isoformat(),
                    claim.command_id,
                ),
            )
            raw_updated = connection.execute(
                "SELECT * FROM commands WHERE command_id = ?", (claim.command_id,)
            ).fetchone()
            assert raw_updated is not None
            updated = cast(sqlite3.Row, raw_updated)
        self.fault_probe("command.after_terminal_commit")
        return self._command_from_row(updated)

    @staticmethod
    def _command_fenced(connection: sqlite3.Connection, claim: CommandClaim) -> sqlite3.Row:
        raw = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?", (claim.command_id,)
        ).fetchone()
        if raw is None:
            raise JournalDamaged(f"unknown command {claim.command_id!r}")
        row = cast(sqlite3.Row, raw)
        if (
            row["state"] != "prepared"
            or row["owner_id"] != claim.owner_id
            or int(row["owner_epoch"]) != claim.epoch
        ):
            raise OwnershipLost(
                f"command {claim.command_id!r} is no longer owned by"
                f" {claim.owner_id!r} epoch {claim.epoch}"
            )
        return row

    @staticmethod
    def _command_from_row(row: sqlite3.Row) -> CommandRecord:
        state = cast(Literal["prepared", "committed", "rejected"], row["state"])
        return CommandRecord(
            command_id=row["command_id"],
            actor=AuthenticatedActor.model_validate_json(row["actor_json"]),
            operation=row["operation"],
            idempotency_key=row["idempotency_key"],
            request_hash=Digest(row["request_hash"]),
            request=json.loads(row["request_json"]),
            state=state,
            plan=json.loads(row["plan_json"]) if row["plan_json"] else None,
            response=json.loads(row["response_json"]) if row["response_json"] else None,
            owner_id=row["owner_id"],
            owner_epoch=row["owner_epoch"],
            lease_expires_at=(
                datetime.fromisoformat(row["lease_expires_at"]) if row["lease_expires_at"] else None
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            completed_at=(
                datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
            ),
        )

    @staticmethod
    def _approval_from_row(row: sqlite3.Row) -> ApprovalRecord:
        adapter: TypeAdapter[ProofSubject] = TypeAdapter(ProofSubject)
        subject: ProofSubject = adapter.validate_python(json.loads(row["subject_json"]))
        return ApprovalRecord(
            approval_id=row["approval_id"],
            subject=subject,
            decision=row["decision"],
            reason=row["reason"],
            actor=AuthenticatedActor.model_validate_json(row["actor_json"]),
            run_id=RunId(row["run_id"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
