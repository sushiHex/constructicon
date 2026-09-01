# mypy: disable-error-code="attr-defined"
"""Durable command-law and approval ledgers."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Literal

from constructicon.core.channel import ChannelMessage
from constructicon.core.control import (
    AuthenticatedActor,
    CommandClaim,
    CommandClaimResult,
    CommandRecord,
    HistoricalResumePlanEvidence,
    command_id_for,
    command_request_hash,
    validate_idempotency_key,
)
from constructicon.core.effect import ApprovalRecord
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.human import (
    ApprovalPlan,
    ChannelAckPlan,
    ChannelApprovalPlan,
    ChannelReplyPlan,
    decoded_human_command_plan,
    validated_channel_approval_exchange,
    validated_channel_command_approval,
    validated_command_approval_plan,
    validated_standalone_command_approval,
)
from constructicon.core.identity import Digest, JsonValue, canonical_json
from constructicon.core.run import OwnershipLost
from constructicon.substrate.journal._sqlite_approvals import (
    approval_fact,
    approval_from_row,
    seal_approval,
    stored_approval_fact_from_row,
)
from constructicon.substrate.journal._sqlite_channels import (
    _ack_row,
    _request_in_transaction,
    _stored_ack_record,
    _stored_message_fact,
    reply_in_transaction,
    stored_reply_in_transaction,
)
from constructicon.substrate.journal._sqlite_commands import (
    command_for_id,
    historical_resume_plan_evidence_for_id,
    seal_command_claim,
    seal_command_phases,
    seal_current_command_plan,
    sealed_command_from_row,
    validate_command_claim_inventory,
)
from constructicon.substrate.journal._sqlite_execution_facts import (
    resume_attempt_owned_by,
)

_COMMAND_RECOVERY_ANOMALY = """
(
    constructicon_utc_microseconds(created_at) IS NULL
    OR command_id IS NOT constructicon_command_id(
        actor_id,
        operation,
        idempotency_key
    )
)
"""


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
        validate_idempotency_key(idempotency_key)
        if request_hash != command_request_hash(request):
            raise ValueError("request_hash does not match the canonical command request")
        command_id = command_id_for(actor.actor_id, operation, idempotency_key)
        request_json = canonical_json(request)
        with self._txn() as connection:
            record = command_for_id(connection, command_id)
            if record is None:
                now = self._now()
                expires = now + timedelta(seconds=ttl_s)
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
                row = connection.execute(
                    "SELECT * FROM commands WHERE command_id = ?",
                    (command_id,),
                ).fetchone()
                assert row is not None
                seal_command_claim(connection, row)
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
            now = self._now()
            expires = now + timedelta(seconds=ttl_s)
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
        if plan is None:
            # `None` is a legal `JsonValue`, so the port's type admits the one
            # value that is not a plan: it stores as the four SQL-non-NULL bytes
            # `null` and decodes back to nothing. Refusing it here is what lets
            # every later reading of the column mean the same thing.
            raise ValueError(
                f"command {claim.command_id!r} cannot be planned with no plan"
            )
        plan_json = canonical_json(plan)
        with self._txn() as connection:
            record = self._command_fenced(connection, claim)
            if record.plan is not None:
                if canonical_json(record.plan) == plan_json:
                    return
                raise JournalDamaged(
                    f"command {claim.command_id!r} already carries a different plan"
                )
            connection.execute(
                "UPDATE commands SET plan_json = ?, updated_at = ? WHERE command_id = ?",
                (plan_json, self._now_iso(), claim.command_id),
            )
            planned = connection.execute(
                "SELECT * FROM commands WHERE command_id = ?",
                (claim.command_id,),
            ).fetchone()
            assert planned is not None
            seal_current_command_plan(connection, planned)
        self.fault_probe("command.after_plan_commit")

    def complete_command(self, claim: CommandClaim, response: JsonValue) -> CommandRecord:
        return self._terminal_command(claim, response, "committed")

    def reject_command(self, claim: CommandClaim, response: JsonValue) -> CommandRecord:
        return self._terminal_command(claim, response, "rejected")

    def command(self, command_id: str) -> CommandRecord | None:
        with self._read() as connection:
            return command_for_id(connection, command_id)

    def historical_resume_plan_evidence(
        self,
        command_id: str,
    ) -> HistoricalResumePlanEvidence | None:
        with self._read() as connection:
            return historical_resume_plan_evidence_for_id(connection, command_id)

    def latest_command_key(self, *, operation: str) -> tuple[str, str] | None:
        with self._read() as connection:
            validate_command_claim_inventory(connection)
            row = connection.execute(
                "SELECT * FROM commands WHERE "
                + _COMMAND_RECOVERY_ANOMALY
                + " OR (operation = ?"
                " AND constructicon_utc_microseconds(created_at) IS NOT NULL)"
                " ORDER BY CASE WHEN "
                + _COMMAND_RECOVERY_ANOMALY
                + " THEN 0 ELSE 1 END, created_at DESC, command_id DESC LIMIT 1",
                (operation,),
            ).fetchone()
            if row is None:
                return None
            record = sealed_command_from_row(connection, row)
            return (record.created_at.isoformat(), record.command_id)

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
            validate_command_claim_inventory(connection)
            rows = connection.execute(
                "SELECT * FROM commands WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at, command_id LIMIT ?",
                tuple(params),
            ).fetchall()
            return tuple(sealed_command_from_row(connection, row) for row in rows)

    def command_records(
        self,
        *,
        operation: str,
        after: tuple[str, str] | None,
        through: tuple[str, str],
        limit: int,
    ) -> tuple[CommandRecord, ...]:
        """Decode every row in a bounded cut before interpreting lifecycle state."""

        if limit <= 0:
            raise ValueError("limit must be positive")
        clauses = [
            "operation = ?",
            "constructicon_utc_microseconds(created_at) IS NOT NULL",
            "(created_at < ? OR (created_at = ? AND command_id <= ?))",
        ]
        params: list[object] = [operation, through[0], through[0], through[1]]
        if after is not None:
            clauses.append("(created_at > ? OR (created_at = ? AND command_id > ?))")
            params.extend((after[0], after[0], after[1]))
        params.append(limit)
        with self._read() as connection:
            validate_command_claim_inventory(connection)
            rows = connection.execute(
                "SELECT * FROM commands WHERE "
                + _COMMAND_RECOVERY_ANOMALY
                + " OR ("
                + " AND ".join(clauses)
                + ") ORDER BY CASE WHEN "
                + _COMMAND_RECOVERY_ANOMALY
                + " THEN 0 ELSE 1 END, created_at, command_id LIMIT ?",
                tuple(params),
            ).fetchall()
            return tuple(sealed_command_from_row(connection, row) for row in rows)

    def store_approval(self, claim: CommandClaim, approval: ApprovalRecord) -> ApprovalRecord:
        with self._txn() as connection:
            command = self._approval_command_fenced(connection, claim, approval)
            self._write_approval(connection, command, approval)
        return approval

    def store_approval_exchange(
        self,
        claim: CommandClaim,
        approval: ApprovalRecord,
        *,
        channel_id: str,
        request_id: Digest,
        payload: JsonValue,
    ) -> ChannelMessage:
        """One human decision: its approval record, reply, and delivery fact.

        A new acknowledgement joins the approval and reply in this commit. An
        equal earlier acknowledgement is preserved under its original command;
        this commit then adds the approval and reply together. Composing
        `store_approval` with `channel_reply` would still commit twice, so a
        death between them could leave an approval authorizing an exchange
        nobody answered, or a reply with no governance fact behind it.

        The deciding actor is read off the approval rather than passed again, so
        the authenticated command, reply sender, and acknowledgement actor
        cannot disagree with the record that authorizes them.
        """

        actor_id = approval.actor.actor_id
        with self._txn() as connection:
            command = self._command_fenced(connection, claim)
            request, _reply_port = _request_in_transaction(
                connection,
                channel_id=channel_id,
                request_id=request_id,
            )
            plan = validated_channel_command_approval(command, approval, request)
            if (
                plan.channel_id != channel_id
                or plan.request_id != request_id
                or canonical_json(plan.payload) != canonical_json(payload)
            ):
                raise JournalDamaged(
                    f"approval {approval.approval_id!r} write contradicts its channel plan"
                )
            approval_row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval.approval_id,),
            ).fetchone()
            stored_reply = stored_reply_in_transaction(
                connection,
                channel_id=channel_id,
                request_id=request_id,
            )
            if stored_reply is None:
                if approval_row is not None:
                    raise JournalDamaged(
                        f"approval {approval.approval_id!r} exists without its channel reply"
                    )
            else:
                _reply, writer = stored_reply
                if writer == claim.command_id:
                    if approval_row is None:
                        raise JournalDamaged(
                            f"channel reply for approval {approval.approval_id!r} exists "
                            "without its approval record"
                        )
                elif approval_row is not None:
                    raise JournalDamaged(
                        f"approval {approval.approval_id!r} exists beside another "
                        "command's channel reply"
                    )
                # Otherwise another complete exchange won the race.  Do not
                # write this command's approval; `reply_in_transaction` below
                # reports the typed reply conflict from the immutable winner.
            reply = reply_in_transaction(
                connection,
                channel_id=channel_id,
                request_id=request_id,
                actor_id=actor_id,
                payload=payload,
                command_id=claim.command_id,
                observe=self._now,
            )
            validated_channel_approval_exchange(command, approval, request, reply)
            self._write_approval(connection, command, approval)
        self.fault_probe("channel.after_reply_insert")
        return reply

    def _write_approval(
        self,
        connection: sqlite3.Connection,
        command: CommandRecord,
        approval: ApprovalRecord,
    ) -> ApprovalRecord:
        existing_fact = approval_fact(
            connection,
            approval_id=approval.approval_id,
            command_id=command.command_id,
        )
        if existing_fact is not None:
            existing_command, existing = existing_fact
            if existing_command.command_id != command.command_id:
                raise JournalDamaged(
                    f"approval {approval.approval_id!r} belongs to another command"
                )
            if existing == approval:
                return existing
            raise JournalDamaged(f"approval {approval.approval_id!r} was rewritten contradictorily")
        owner = connection.execute(
            "SELECT approval_id FROM approvals WHERE command_id = ?",
            (command.command_id,),
        ).fetchone()
        if owner is not None:
            raise JournalDamaged(
                f"command {command.command_id!r} already wrote a different approval"
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
                command.command_id,
                approval.created_at.isoformat(),
            ),
        )
        stored = connection.execute(
            "SELECT * FROM approvals WHERE approval_id = ?",
            (approval.approval_id,),
        ).fetchone()
        assert stored is not None
        seal_approval(connection, stored)
        return approval

    def _approval_command_fenced(
        self,
        connection: sqlite3.Connection,
        claim: CommandClaim,
        approval: ApprovalRecord,
    ) -> CommandRecord:
        """Fence one approval under the exact actor its command authenticated."""

        command = self._command_fenced(connection, claim)
        validated_standalone_command_approval(command, approval)
        return command

    def approval_for_command(self, command_id: str) -> ApprovalRecord | None:
        """The approval one command wrote, if it wrote one."""

        with self._read() as connection:
            fact = approval_fact(connection, command_id=command_id)
            if fact is None:
                return None
            _command, approval = fact
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval.approval_id,),
            ).fetchone()
            assert row is not None
            return self._stored_approval(connection, row)

    def approval(self, approval_id: str) -> ApprovalRecord | None:
        with self._read() as connection:
            fact = approval_fact(connection, approval_id=approval_id)
            if fact is None:
                return None
            _command, approval = fact
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval.approval_id,),
            ).fetchone()
            assert row is not None
            return self._stored_approval(connection, row)

    def _stored_approval(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> ApprovalRecord:
        """Project one approval, including its channel exchange when bound."""

        command, approval = stored_approval_fact_from_row(connection, row)
        plan = validated_command_approval_plan(command, approval)
        if not isinstance(plan, ChannelApprovalPlan):
            return approval
        try:
            stored_reply = stored_reply_in_transaction(
                connection,
                channel_id=plan.channel_id,
                request_id=plan.request_id,
            )
        except ContractViolation as exc:
            raise JournalDamaged(
                f"request-bound approval {approval.approval_id!r} names no sealed request"
            ) from exc
        if stored_reply is None or stored_reply[1] != command.command_id:
            raise JournalDamaged(
                f"request-bound approval {approval.approval_id!r} has no reply "
                "written by its command"
            )
        return approval

    def _terminal_command(
        self,
        claim: CommandClaim,
        response: JsonValue,
        state: Literal["committed", "rejected"],
    ) -> CommandRecord:
        if response is None:
            # The same law as `store_command_plan`: a terminal command must
            # carry a response some later replay can hand back, and `null` is
            # bytes that are present to SQL and absent to every reader.
            raise ValueError(
                f"command {claim.command_id!r} cannot become {state} with no response"
            )
        response_json = canonical_json(response)
        with self._txn() as connection:
            existing = command_for_id(connection, claim.command_id)
            if existing is None:
                raise JournalDamaged(f"unknown command {claim.command_id!r}")
            written = (
                self._domain_fact_owned_by(connection, existing)
                if state == "rejected"
                else None
            )
            if written is not None:
                raise JournalDamaged(
                    f"command {claim.command_id!r} cannot be rejected after writing "
                    f"{written}"
                )
            if existing.state in ("committed", "rejected"):
                if existing.state == state and canonical_json(existing.response) == response_json:
                    return existing
                raise JournalDamaged(
                    f"command {claim.command_id!r} already has a different terminal response"
                )
            fenced = self._command_fenced(connection, claim)
            if fenced.plan is None:
                raise JournalDamaged(
                    f"command {claim.command_id!r} cannot become terminal without an immutable plan"
                )
            now = self._now()
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
            seal_command_phases(connection, raw_updated)
            updated = sealed_command_from_row(connection, raw_updated)
        self.fault_probe("command.after_terminal_commit")
        return updated

    @staticmethod
    def _domain_fact_owned_by(
        connection: sqlite3.Connection,
        command: CommandRecord,
    ) -> str | None:
        """Project facts by immutable plan identity before permitting rejection.

        A rejection says the planned mutation did not happen. Once any
        co-located fact says otherwise, changing only the command lifecycle
        would manufacture an impossible history that every exact projection
        must then reject. Relational ``command_id`` is only a redundant link:
        the typed plan independently names each human fact, so moving that link
        cannot make the mutation disappear and invite a fabricated rejection.
        """

        facts: list[str] = []
        plan = decoded_human_command_plan(command)
        if isinstance(plan, (ApprovalPlan, ChannelApprovalPlan)):
            approval_rows = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ? OR command_id = ? LIMIT 2",
                (plan.approval.approval_id, command.command_id),
            ).fetchall()
            if len(approval_rows) > 1:
                raise JournalDamaged(
                    f"command {command.command_id!r} has contradictory approval facts"
                )
            if approval_rows:
                approval_from_row(approval_rows[0], command=command)
                facts.append("an approval")

        channel_plan = (
            plan
            if isinstance(plan, (ChannelApprovalPlan, ChannelReplyPlan, ChannelAckPlan))
            else None
        )
        if channel_plan is not None:
            if isinstance(channel_plan, ChannelAckPlan):
                request_id = channel_plan.message_id
                channel_id = channel_plan.channel_id
                actor_id = channel_plan.actor_id
                reply_id: Digest | None = None
            else:
                request_id = channel_plan.request_id
                channel_id = channel_plan.channel_id
                actor_id = (
                    channel_plan.ack_actor_id
                    if isinstance(channel_plan, ChannelApprovalPlan)
                    else channel_plan.actor_id
                )
                reply_id = channel_plan.reply_id

            reply_candidate = (
                connection.execute(
                    "SELECT 1 FROM channel_messages"
                    " WHERE message_id = ? OR command_id = ? LIMIT 1",
                    (str(reply_id), command.command_id),
                ).fetchone()
                if reply_id is not None
                else None
            )
            if reply_candidate is not None:
                stored_reply = stored_reply_in_transaction(
                    connection,
                    channel_id=channel_id,
                    request_id=request_id,
                )
                if stored_reply is None:
                    raise JournalDamaged(
                        f"command {command.command_id!r} owns a non-projectable channel reply"
                    )
                _reply, writer_command_id = stored_reply
                if writer_command_id == command.command_id:
                    facts.append("a channel reply")

            ack_row = _ack_row(connection, request_id, actor_id)
            if ack_row is not None:
                request, _reply_port = _request_in_transaction(
                    connection,
                    channel_id=channel_id,
                    request_id=request_id,
                )
                acknowledgement = _stored_ack_record(
                    connection,
                    ack_row,
                    request=request,
                )
                if acknowledgement.command_id == command.command_id:
                    facts.append("a channel acknowledgement")

        # A fact linked to an operation whose plan does not name it is damage,
        # not an excuse to ignore the old redundant owner column.
        approval_row = connection.execute(
            "SELECT * FROM approvals WHERE command_id = ?",
            (command.command_id,),
        ).fetchone()
        if approval_row is not None and "an approval" not in facts:
            stored_approval_fact_from_row(connection, approval_row)
            facts.append("an approval")
        reply_row = connection.execute(
            "SELECT * FROM channel_messages WHERE command_id = ?",
            (command.command_id,),
        ).fetchone()
        if reply_row is not None and "a channel reply" not in facts:
            _stored_message_fact(connection, reply_row)
            facts.append("a channel reply")
        ack_row = connection.execute(
            "SELECT * FROM channel_acks WHERE command_id = ?",
            (command.command_id,),
        ).fetchone()
        if ack_row is not None and "a channel acknowledgement" not in facts:
            _stored_ack_record(connection, ack_row)
            facts.append("a channel acknowledgement")

        if resume_attempt_owned_by(connection, command):
            facts.append("a resume attempt")

        for fact in (
            "an approval",
            "a channel reply",
            "a channel acknowledgement",
            "a resume attempt",
        ):
            if fact in facts:
                return fact
        return None

    @staticmethod
    def _command_fenced(
        connection: sqlite3.Connection,
        claim: CommandClaim,
    ) -> CommandRecord:
        record = command_for_id(connection, claim.command_id)
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
                f"command {claim.command_id!r} is no longer owned by"
                f" {claim.owner_id!r} epoch {claim.epoch}"
            )
        return record
