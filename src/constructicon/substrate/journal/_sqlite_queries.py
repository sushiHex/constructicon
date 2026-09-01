# mypy: disable-error-code="attr-defined"
"""Bounded durable run and event query projection."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Any, cast

from pydantic import ValidationError

from constructicon.core.address import RunId
from constructicon.core.channel import reply_message_id
from constructicon.core.control import (
    CommandRecord,
    RunHead,
    RunOrigin,
    RunRecord,
)
from constructicon.core.effect import ApprovalRecord
from constructicon.core.errors import JournalDamaged
from constructicon.core.human import (
    claims_approval_exchange,
    validated_channel_ack_provenance,
)
from constructicon.core.identity import (
    Digest,
    canonical_json,
    json_value,
    parse_json_value,
)
from constructicon.core.journal import JournalEvent
from constructicon.core.run import (
    TERMINAL_STATUS_EVENTS,
    ParkedUnit,
    ParkedWait,
    RunStatus,
)
from constructicon.substrate.journal._sqlite_approvals import (
    stored_approval_fact_from_row,
)
from constructicon.substrate.journal._sqlite_base import (
    _durable_sequence,
    _durable_text,
    _utc_microseconds,
)
from constructicon.substrate.journal._sqlite_channels import (
    _channel_message_rows_for_ids,
    _channel_provenance_cutoffs,
    _snapshot,
    _stored_ack_record_from_values,
    _stored_channel_message_from_row,
    _stored_reply_writer,
    _stored_request_facts,
    _validate_channel_message_absences,
    _validate_reply_provenance_era,
    _validated_stored_reply_fact,
)
from constructicon.substrate.journal._sqlite_commands import sealed_command_from_row
from constructicon.substrate.journal._sqlite_execution_facts import stored_event_from_row
from constructicon.substrate.journal._sqlite_runs import (
    RUN_CHILD_ORPHAN_ANOMALY,
    RUN_IMMUTABLE_ANOMALY,
    RUN_LIFECYCLE_ANOMALY,
    RUN_PROJECTION_COLUMNS,
    RUN_PROJECTION_JOINS,
    ValidatedRunWorld,
    register_run_origin_guard,
    run_record_from_row,
    validate_no_orphan_run_facts,
    validated_run_facts,
    validated_run_projection,
)

# Comfortably under every SQLite build's SQLITE_MAX_VARIABLE_NUMBER, old and new.
_MAX_SQL_VARIABLES = 900

_RECOVERABLE_RUN_SCALAR_ANOMALY = (
    "r.status IS NULL OR typeof(r.status) != 'text'"
    " OR r.status NOT IN ('pending', 'running', 'parked', 'failed',"
    " 'succeeded', 'cancelled')"
    " OR (r.status IN ('pending', 'running') AND ("
    " typeof(r.run_id) != 'text'"
    " OR constructicon_utc_microseconds(r.created_at) IS NULL"
    " OR (r.owner_id IS NOT NULL AND typeof(r.owner_id) != 'text')"
    " OR typeof(r.cancel_requested) != 'integer'"
    " OR r.cancel_requested NOT IN (0, 1)"
    " OR (r.lease_expires_at IS NOT NULL"
    " AND constructicon_utc_microseconds(r.lease_expires_at) IS NULL)))"
)


def _lifecycle_event_row(
    row: sqlite3.Row,
    *,
    run_id: RunId,
    seq: int,
    kind: str,
) -> sqlite3.Row:
    """Present one already-joined lifecycle event to the shared event decoder."""

    return cast(
        sqlite3.Row,
        {
            "run_id": str(run_id),
            "seq": seq,
            "kind": kind,
            "path_json": row["lifecycle_event_path_json"],
            "payload": row["lifecycle_event_payload"],
            "created_at": row["lifecycle_event_created_at"],
        },
    )


class _SqliteQueriesMixin:
    def run_record(self, run_id: RunId) -> RunRecord | None:
        with self._read() as connection, _snapshot(connection):
            register_run_origin_guard(connection)
            row = connection.execute(
                "SELECT " + RUN_PROJECTION_COLUMNS + RUN_PROJECTION_JOINS + " WHERE r.run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                validate_no_orphan_run_facts(connection)
                return None
            record, _world, _event_seq, _event_kind = self._validated_run_projection(
                connection,
                row,
            )
            return record

    def run_head(self, run_id: RunId) -> RunHead | None:
        with self._read() as connection, _snapshot(connection):
            projection = self._run_projection_for_id(connection, run_id)
            if projection is None:
                return None
            record, _world, event_seq, event_kind = projection
            return RunHead(
                record=record,
                event_seq=event_seq or 0,
                event_kind=event_kind,
            )

    def run_records(
        self,
        *,
        statuses: tuple[RunStatus, ...] | None = None,
        after: tuple[str, str] | None = None,
        through: tuple[str, str] | None = None,
        limit: int = 100,
    ) -> list[RunRecord]:
        clauses: list[str] = []
        arguments: list[Any] = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            clauses.append(f"r.status IN ({placeholders})")
            arguments.extend(status.value for status in statuses)
        if after is not None:
            clauses.append("(r.created_at > ? OR (r.created_at = ? AND r.run_id > ?))")
            arguments.extend((after[0], after[0], after[1]))
        if through is not None:
            clauses.append("(r.created_at < ? OR (r.created_at = ? AND r.run_id <= ?))")
            arguments.extend((through[0], through[0], through[1]))
        requested = " AND ".join(clauses) if clauses else "1"
        arguments.append(limit)
        with self._read() as connection, _snapshot(connection):
            register_run_origin_guard(connection)
            rows = connection.execute(
                "SELECT "
                + RUN_PROJECTION_COLUMNS
                + RUN_PROJECTION_JOINS
                + f" WHERE ({requested}) OR ({RUN_LIFECYCLE_ANOMALY})"
                f" OR ({RUN_IMMUTABLE_ANOMALY}) OR ({RUN_CHILD_ORPHAN_ANOMALY})"
                f" ORDER BY ({RUN_CHILD_ORPHAN_ANOMALY}) DESC,"
                f" ({RUN_IMMUTABLE_ANOMALY}) DESC,"
                f" ({RUN_LIFECYCLE_ANOMALY}) DESC,"
                " r.created_at ASC, r.run_id ASC LIMIT ?",
                tuple(arguments),
            ).fetchall()
            if not rows:
                validate_no_orphan_run_facts(connection)
            return [self._validated_run_projection(connection, row)[0] for row in rows]

    def latest_run_key(
        self, *, statuses: tuple[RunStatus, ...] | None = None
    ) -> tuple[str, str] | None:
        requested = "1"
        arguments: list[Any] = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            requested = f"r.status IN ({placeholders})"
            arguments.extend(status.value for status in statuses)
        with self._read() as connection, _snapshot(connection):
            register_run_origin_guard(connection)
            row = connection.execute(
                "SELECT "
                + RUN_PROJECTION_COLUMNS
                + RUN_PROJECTION_JOINS
                + f" WHERE ({requested}) OR ({RUN_LIFECYCLE_ANOMALY})"
                f" OR ({RUN_IMMUTABLE_ANOMALY}) OR ({RUN_CHILD_ORPHAN_ANOMALY})"
                f" ORDER BY ({RUN_CHILD_ORPHAN_ANOMALY}) DESC,"
                f" ({RUN_IMMUTABLE_ANOMALY}) DESC,"
                f" ({RUN_LIFECYCLE_ANOMALY}) DESC," + " r.created_at DESC, r.run_id DESC LIMIT 1",
                tuple(arguments),
            ).fetchone()
            if row is None:
                validate_no_orphan_run_facts(connection)
                return None
            record, _world, _event_seq, _event_kind = self._validated_run_projection(
                connection,
                row,
            )
            return (record.created_at.isoformat(), str(record.run_id))

    def recoverable_runs(self, *, limit: int = 100) -> list[RunId]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        observed_at = self._now()
        with self._read() as connection, _snapshot(connection):
            register_run_origin_guard(connection)
            rows = connection.execute(
                "SELECT " + RUN_PROJECTION_COLUMNS + RUN_PROJECTION_JOINS + " WHERE r.status = ?"
                " OR (r.status = ? AND (r.owner_id IS NULL"
                " OR r.lease_expires_at IS NULL"
                " OR constructicon_utc_microseconds(r.lease_expires_at) <= ?))"
                f" OR ({_RECOVERABLE_RUN_SCALAR_ANOMALY})"
                f" OR ({RUN_LIFECYCLE_ANOMALY})"
                f" OR ({RUN_IMMUTABLE_ANOMALY}) OR ({RUN_CHILD_ORPHAN_ANOMALY})"
                f" ORDER BY ({RUN_CHILD_ORPHAN_ANOMALY}) DESC,"
                f" ({RUN_IMMUTABLE_ANOMALY}) DESC,"
                f" ({RUN_LIFECYCLE_ANOMALY}) DESC,"
                f" ({_RECOVERABLE_RUN_SCALAR_ANOMALY}) DESC,"
                " constructicon_utc_microseconds(r.created_at), r.run_id LIMIT ?",
                (
                    RunStatus.PENDING.value,
                    RunStatus.RUNNING.value,
                    _utc_microseconds(observed_at),
                    limit,
                ),
            ).fetchall()
            if not rows:
                validate_no_orphan_run_facts(connection)
            records = [
                self._validated_run_projection(
                    connection,
                    row,
                )[0]
                for row in rows
            ]
            return [
                record.run_id
                for record in records
                if record.status is RunStatus.PENDING
                or (record.status is RunStatus.RUNNING and record.liveness == "lost")
            ]

    def run_origin(self, run_id: RunId) -> RunOrigin | None:
        with self._read() as connection, _snapshot(connection):
            register_run_origin_guard(connection)
            row = connection.execute(
                "SELECT " + RUN_PROJECTION_COLUMNS + RUN_PROJECTION_JOINS + " WHERE r.run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                validate_no_orphan_run_facts(connection)
                return None
            record, _world, _event_seq, _event_kind = self._validated_run_projection(
                connection,
                row,
            )
            return record.origin

    def event(self, run_id: RunId, seq: int) -> JournalEvent | None:
        with self._read() as connection, _snapshot(connection):
            projection = self._run_facts_for_id(connection, run_id)
            if projection is None:
                return None
            row = connection.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq = ?", (run_id, seq)
            ).fetchone()
            if row is None:
                return None
            event = stored_event_from_row(connection, row)
            if event.run_id != run_id or event.seq != seq:
                raise JournalDamaged(f"event {run_id!r}/{seq!r} contradicts its requested identity")
            return event

    def latest_terminal_event(self, run_id: RunId) -> JournalEvent | None:
        with self._read() as connection, _snapshot(connection):
            register_run_origin_guard(connection)
            row = connection.execute(
                "SELECT " + RUN_PROJECTION_COLUMNS + RUN_PROJECTION_JOINS + " WHERE r.run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                validate_no_orphan_run_facts(connection)
                return None
            record, _world, event_seq, event_kind = self._validated_run_projection(
                connection,
                row,
            )
            if record.status not in TERMINAL_STATUS_EVENTS:
                return None
            assert event_seq is not None and event_kind is not None
            return stored_event_from_row(
                connection,
                _lifecycle_event_row(
                    row,
                    run_id=record.run_id,
                    seq=event_seq,
                    kind=event_kind,
                ),
            )

    def parked_waits(
        self,
        *,
        after: tuple[str, str] | None = None,
        through: tuple[str, str] | None = None,
        limit: int = 100,
    ) -> list[ParkedWait]:
        """Every PARKED run and the exact requests a reply would wake it at.

        A projection over rows that already exist — the PARKED run and its
        latest parking event — never a table, an outbox, or a second authority.
        Recovery derives wake eligibility from these domain facts rather than
        command completion, so a wake survives death after the reply's domain
        transaction but before its command completes. Immutable writer command
        rows may still prove reply provenance. A PARKED row without one
        well-formed latest parking event is damage and fails closed rather than
        silently waking nothing.
        """

        if limit <= 0:
            raise ValueError("limit must be positive")
        clauses = [
            f"(r.status = ? OR ({RUN_LIFECYCLE_ANOMALY})"
            f" OR ({RUN_IMMUTABLE_ANOMALY}) OR ({RUN_CHILD_ORPHAN_ANOMALY}))"
        ]
        arguments: list[Any] = [RunStatus.PARKED.value]
        if after is not None:
            clauses.append("(r.created_at > ? OR (r.created_at = ? AND r.run_id > ?))")
            arguments.extend((after[0], after[0], after[1]))
        if through is not None:
            clauses.append("(r.created_at < ? OR (r.created_at = ? AND r.run_id <= ?))")
            arguments.extend((through[0], through[0], through[1]))
        arguments.append(limit)

        # Status and fence are one SQLite statement, hence one WAL snapshot.
        # Reading PARKED rows first and terminal events later lets another host
        # complete a run between those observations; the newer terminal event
        # would then make an entirely valid transition look like journal damage.
        with self._read() as connection, _snapshot(connection):
            register_run_origin_guard(connection)
            rows = connection.execute(
                "SELECT "
                + RUN_PROJECTION_COLUMNS
                + RUN_PROJECTION_JOINS
                + " WHERE "
                + " AND ".join(clauses)
                + f" ORDER BY ({RUN_CHILD_ORPHAN_ANOMALY}) DESC,"
                + f" ({RUN_IMMUTABLE_ANOMALY}) DESC,"
                + f" ({RUN_LIFECYCLE_ANOMALY}) DESC,"
                + " r.created_at, r.run_id LIMIT ?",
                tuple(arguments),
            ).fetchall()
            if not rows:
                validate_no_orphan_run_facts(connection)

            projections = [(row, *self._validated_run_projection(connection, row)) for row in rows]

        waits: list[ParkedWait] = []
        for row, record, _world, event_seq, event_kind in projections:
            if record.status is not RunStatus.PARKED or event_kind != "RunParked":
                raise JournalDamaged(f"run {record.run_id!r} contradicts its durable lifecycle")
            assert event_seq is not None
            try:
                payload = (
                    parse_json_value(row["lifecycle_event_payload"])
                    if row["lifecycle_event_payload"] is not None
                    else None
                )
            except (TypeError, ValueError) as exc:
                raise JournalDamaged(
                    f"RunParked event for {record.run_id!r} has invalid payload bytes"
                ) from exc
            if not isinstance(payload, dict):
                raise JournalDamaged(f"RunParked event for {record.run_id!r} has no object payload")
            units = payload.get("parked")
            if not isinstance(units, list):
                raise JournalDamaged(
                    f"RunParked event for {record.run_id!r} carries no parked units"
                )
            try:
                parsed = [ParkedUnit.model_validate(unit) for unit in units]
            except ValidationError as exc:
                raise JournalDamaged(
                    f"RunParked event for {record.run_id!r} has invalid parked units: {exc}"
                ) from exc
            if canonical_json(units) != canonical_json(
                [json_value(unit.model_dump(mode="json")) for unit in parsed]
            ):
                raise JournalDamaged(
                    f"RunParked event for {record.run_id!r} has non-lossless parked units"
                )
            waits.append(
                ParkedWait(
                    run_id=record.run_id,
                    created_at=record.created_at,
                    event_seq=event_seq,
                    requests=tuple(
                        unit.waiting_on for unit in parsed if unit.waiting_on is not None
                    ),
                )
            )

        if not waits:
            return []

        # The first statement proved each candidate was a coherent PARKED fact.
        # This current fence only drops a candidate another host advanced after
        # that snapshot; it never converts ordinary progress into damage. The
        # RunHost repeats the same event fence at claim, closing the unavoidable
        # final race after this read returns.
        current: dict[str, tuple[RunStatus, int]] = {}
        with self._read() as connection:
            for start in range(0, len(waits), _MAX_SQL_VARIABLES):
                chunk = waits[start : start + _MAX_SQL_VARIABLES]
                placeholders = ",".join("?" for _ in chunk)
                for row in connection.execute(
                    "SELECT run_id, status, next_event_seq FROM runs"
                    f" WHERE run_id IN ({placeholders})",
                    tuple(str(wait.run_id) for wait in chunk),
                ).fetchall():
                    run_key = _durable_text(
                        row["run_id"],
                        fact="PARKED current-fence run identity",
                    )
                    try:
                        status = RunStatus(
                            _durable_text(
                                row["status"],
                                fact=f"PARKED run {run_key!r} current status",
                            )
                        )
                    except ValueError as exc:
                        raise JournalDamaged(
                            f"PARKED run {run_key!r} current status is invalid"
                        ) from exc
                    current[run_key] = (
                        status,
                        _durable_sequence(
                            row["next_event_seq"],
                            fact=f"PARKED run {run_key!r} current event sequence",
                            allow_zero=True,
                            kind="event sequence",
                        ),
                    )
        missing = [wait.run_id for wait in waits if str(wait.run_id) not in current]
        if missing:
            raise JournalDamaged(f"PARKED runs disappeared during projection: {missing}")
        return [
            wait
            for wait in waits
            if current[str(wait.run_id)] == (RunStatus.PARKED, wait.event_seq)
        ]

    def answered_requests(self, requests: Sequence[Digest]) -> dict[Digest, Digest]:
        """Map each request that already has a stored reply to that reply's id.

        One bounded read over immutable rows. The reply is the durable fact a
        wake observes; command completion never gates it. Immutable writer
        command and plan rows are consulted only to prove that fact's
        provenance.

        Requests are deduplicated and chunked: one placeholder per request would
        exceed SQLite's bind-variable ceiling on a page of runs that each park
        many units, and that exception would escape into the recovery pump.
        """

        unique = list(dict.fromkeys(str(request) for request in requests))
        if not unique:
            return {}
        answered: dict[Digest, Digest] = {}
        with self._read() as connection, _snapshot(connection):
            legacy_ack_through, legacy_message_through = _channel_provenance_cutoffs(connection)
            request_batch = max(
                1,
                min(
                    connection.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER),
                    _MAX_SQL_VARIABLES,
                )
                // 2,
            )
            for start in range(0, len(unique), request_batch):
                chunk = unique[start : start + request_batch]
                placeholders = ",".join("?" for _ in chunk)
                request_rows = _channel_message_rows_for_ids(connection, chunk)
                request_messages = _stored_request_facts(connection, request_rows)
                request_by_id = {str(message.message_id): message for message in request_messages}
                missing = sorted(set(chunk) - request_by_id.keys())
                if missing:
                    raise JournalDamaged(
                        f"parked waits name channel requests that are not stored: {missing}"
                    )
                non_requests = sorted(
                    message_id
                    for message_id, message in request_by_id.items()
                    if message.kind != "request"
                )
                if non_requests:
                    raise JournalDamaged(
                        f"parked waits name channel messages that are not requests: {non_requests}"
                    )
                request_by_reply_id = {}
                for request in request_messages:
                    if request.reply_port is None:
                        raise JournalDamaged(
                            f"channel request {request.message_id} pins no reply port"
                        )
                    expected_reply_id = str(
                        reply_message_id(
                            request_id=request.message_id,
                            reply_port=request.reply_port,
                        )
                    )
                    if expected_reply_id in request_by_reply_id:
                        raise JournalDamaged("multiple channel requests derive one reply identity")
                    request_by_reply_id[expected_reply_id] = request
                expected_reply_ids = tuple(request_by_reply_id)
                reply_placeholders = ",".join("?" for _ in expected_reply_ids)
                reply_rows = connection.execute(
                    "SELECT reply.*,"
                    " ack.ack_seq AS acknowledgement_seq,"
                    " ack.message_id AS acknowledgement_message_id,"
                    " ack.actor_id AS acknowledgement_actor_id,"
                    " ack.command_id AS acknowledgement_command,"
                    " ack.acked_at AS acknowledgement_acked_at,"
                    " ack.ack_provenance_version AS acknowledgement_provenance_version"
                    " FROM channel_messages AS reply"
                    " LEFT JOIN channel_acks AS ack"
                    " ON ack.message_id = reply.reply_to"
                    " AND ack.actor_id = reply.sender_actor_id"
                    f" WHERE reply.message_id IN ({reply_placeholders})"
                    f" OR reply.reply_to IN ({placeholders})",
                    (*expected_reply_ids, *chunk),
                ).fetchall()
                _validate_channel_message_absences(
                    connection,
                    requested=expected_reply_ids,
                    located={
                        _durable_text(
                            row["message_id"],
                            fact="answered-request reply identity",
                        )
                        for row in reply_rows
                    },
                )
                stored_replies = []
                for row in reply_rows:
                    stored_reply = _stored_channel_message_from_row(connection, row)
                    acknowledgement_writer = (
                        _durable_text(
                            row["acknowledgement_command"],
                            fact=(
                                f"channel reply {stored_reply.message.message_id} "
                                "acknowledgement command"
                            ),
                        )
                        if row["acknowledgement_command"] is not None
                        else None
                    )
                    stored_replies.append((row, stored_reply, acknowledgement_writer))
                approval_writers: set[str] = set()
                reply_writers: set[str] = set()
                acknowledgement_writers: set[str] = set()
                for _row, stored_reply, acknowledgement_writer in stored_replies:
                    reply = stored_reply.message
                    if reply.kind != "reply" or reply.reply_to is None:
                        raise JournalDamaged(
                            f"answered-request projection selected non-reply {reply.message_id}"
                        )
                    if stored_reply.command_id is not None:
                        reply_writers.add(stored_reply.command_id)
                    if acknowledgement_writer is not None:
                        acknowledgement_writers.add(acknowledgement_writer)
                    writer = _stored_reply_writer(
                        stored_reply.command_id,
                        acknowledgement_writer,
                    )
                    candidate_request = request_by_reply_id.get(str(reply.message_id))
                    if candidate_request is None:
                        candidate_request = request_by_id.get(str(reply.reply_to))
                    if (
                        candidate_request is not None
                        and claims_approval_exchange(candidate_request)
                        and writer is not None
                    ):
                        approval_writers.add(writer)
                approvals_by_writer: dict[str, ApprovalRecord] = {}
                commands_by_id: dict[str, CommandRecord] = {}
                writer_ids = approval_writers | reply_writers | acknowledgement_writers
                if writer_ids:
                    ordered_writers = tuple(sorted(writer_ids))
                    command_rows: list[sqlite3.Row] = []
                    command_batch = min(
                        connection.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER),
                        _MAX_SQL_VARIABLES,
                    )
                    for command_start in range(0, len(ordered_writers), command_batch):
                        command_chunk = ordered_writers[
                            command_start : command_start + command_batch
                        ]
                        command_placeholders = ",".join("?" for _ in command_chunk)
                        command_rows.extend(
                            connection.execute(
                                "SELECT * FROM commands WHERE command_id IN "
                                f"({command_placeholders})",
                                command_chunk,
                            ).fetchall()
                        )
                    for command_row in command_rows:
                        command = sealed_command_from_row(connection, command_row)
                        if command.command_id in commands_by_id:
                            raise JournalDamaged(
                                f"channel writer command {command.command_id!r} is stored twice"
                            )
                        commands_by_id[command.command_id] = command
                if approval_writers:
                    approval_placeholders = ",".join("?" for _ in approval_writers)
                    approval_rows = connection.execute(
                        f"SELECT * FROM approvals WHERE command_id IN ({approval_placeholders})",
                        tuple(sorted(approval_writers)),
                    ).fetchall()
                    for approval_row in approval_rows:
                        approval_command_id = _durable_text(
                            approval_row["command_id"],
                            fact="channel approval command identity",
                        )
                        if approval_command_id in approvals_by_writer:
                            raise JournalDamaged(
                                f"channel writer command {approval_command_id!r} "
                                "owns more than one approval"
                            )
                        approval_command_record = commands_by_id.get(approval_command_id)
                        if approval_command_record is None:
                            raise JournalDamaged(
                                f"approval {approval_row['approval_id']!r} names missing "
                                f"command {approval_command_id!r}"
                            )
                        sealed_command, approval = stored_approval_fact_from_row(
                            connection,
                            approval_row,
                        )
                        if sealed_command.command_id != approval_command_record.command_id:
                            raise JournalDamaged(
                                f"approval {approval.approval_id!r} contradicts its "
                                "batched writer command"
                            )
                        approvals_by_writer[approval_command_id] = approval
                for row, stored_reply, exact_acknowledgement_writer in stored_replies:
                    reply = stored_reply.message
                    assert reply.reply_to is not None
                    candidate_request = request_by_reply_id.get(str(reply.message_id))
                    if candidate_request is None:
                        candidate_request = request_by_id.get(str(reply.reply_to))
                    if candidate_request is None:
                        raise JournalDamaged(
                            f"reply {reply.message_id} neither derives from nor names "
                            "a requested channel message"
                        )
                    request = candidate_request
                    acknowledgement_record = (
                        _stored_ack_record_from_values(
                            connection,
                            message_id=row["acknowledgement_message_id"],
                            actor_id=row["acknowledgement_actor_id"],
                            command_id=row["acknowledgement_command"],
                            acked_at=row["acknowledgement_acked_at"],
                            ack_seq=row["acknowledgement_seq"],
                            provenance_version=row["acknowledgement_provenance_version"],
                            legacy_ack_through=legacy_ack_through,
                            command=(
                                commands_by_id.get(exact_acknowledgement_writer)
                                if exact_acknowledgement_writer is not None
                                else None
                            ),
                        )
                        if row["acknowledgement_message_id"] is not None
                        else None
                    )
                    acknowledgement_command = (
                        acknowledgement_record.command_id
                        if acknowledgement_record is not None
                        else None
                    )
                    _validate_reply_provenance_era(
                        stored_reply,
                        acknowledgement_record,
                        legacy_message_through=legacy_message_through,
                    )
                    writer = _stored_reply_writer(
                        stored_reply.command_id,
                        acknowledgement_command,
                    )
                    reply, _writer = _validated_stored_reply_fact(
                        request,
                        reply,
                        stored_reply.command_id,
                        acknowledgement_command=acknowledgement_command,
                        stored_approval=(
                            approvals_by_writer.get(writer) if writer is not None else None
                        ),
                        approval_command=(
                            commands_by_id.get(writer) if writer is not None else None
                        ),
                        writer_command=(commands_by_id.get(writer) if writer is not None else None),
                    )
                    if acknowledgement_record is not None:
                        acknowledgement_writer_command = commands_by_id.get(
                            acknowledgement_record.command_id
                        )
                        if acknowledgement_writer_command is not None:
                            validated_channel_ack_provenance(
                                acknowledgement_writer_command,
                                acknowledgement_record,
                                request,
                                reply=reply,
                                reply_command_id=writer,
                                approval=approvals_by_writer.get(
                                    acknowledgement_writer_command.command_id
                                ),
                            )
                    if request.message_id in answered:
                        raise JournalDamaged(
                            f"channel request {request.message_id} has more than one stored reply"
                        )
                    answered[request.message_id] = reply.message_id
        return answered

    def max_event_seq(self, run_id: RunId) -> int:
        with self._read() as connection, _snapshot(connection):
            projection = self._run_facts_for_id(connection, run_id)
            if projection is None:
                return 0
            _world, event_seq, _event_kind = projection
            return event_seq or 0

    def _run_facts_for_id(
        self,
        connection: sqlite3.Connection,
        run_id: RunId,
    ) -> tuple[ValidatedRunWorld, int | None, str | None] | None:
        register_run_origin_guard(connection)
        row = connection.execute(
            "SELECT " + RUN_PROJECTION_COLUMNS + RUN_PROJECTION_JOINS + " WHERE r.run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            validate_no_orphan_run_facts(connection)
            return None
        return validated_run_facts(connection, row)

    def _run_projection_for_id(
        self,
        connection: sqlite3.Connection,
        run_id: RunId,
    ) -> tuple[RunRecord, ValidatedRunWorld, int | None, str | None] | None:
        register_run_origin_guard(connection)
        row = connection.execute(
            "SELECT " + RUN_PROJECTION_COLUMNS + RUN_PROJECTION_JOINS + " WHERE r.run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            validate_no_orphan_run_facts(connection)
            return None
        return self._validated_run_projection(connection, row)

    def _run_record_from_row(self, row: sqlite3.Row) -> RunRecord:
        """Compatibility hook over the shared exact run-row decoder."""

        return run_record_from_row(row, observe=self._now)

    def _validated_run_projection(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> tuple[RunRecord, ValidatedRunWorld, int | None, str | None]:
        """Keep the testable row hook while sharing every proof law."""

        return validated_run_projection(
            connection,
            row,
            observe=self._now,
            decode_record=self._run_record_from_row,
        )
