# mypy: disable-error-code="attr-defined"
"""Internal SQLite v5 bounded run/event read projection."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.control import RunOrigin, RunRecord
from constructicon.core.identity import Digest
from constructicon.core.journal import JournalEvent
from constructicon.core.run import RunStatus


class _M6ReadMixin:
    def run_record(self, run_id: RunId) -> RunRecord | None:
        with self._read() as connection:
            row = connection.execute(
                "SELECT r.*, o.origin_json FROM runs r LEFT JOIN run_origins o"
                " ON o.run_id = r.run_id WHERE r.run_id = ?",
                (run_id,),
            ).fetchone()
        return self._run_record_from_row(row) if row else None

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
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        arguments.append(limit)
        with self._read() as connection:
            rows = connection.execute(
                "SELECT r.*, o.origin_json FROM runs r LEFT JOIN run_origins o"
                " ON o.run_id = r.run_id"
                + where
                + " ORDER BY r.created_at ASC, r.run_id ASC LIMIT ?",
                tuple(arguments),
            ).fetchall()
        return [self._run_record_from_row(row) for row in rows]

    def recoverable_runs(self, *, limit: int = 100) -> list[RunId]:
        now = self._now_iso()
        with self._read() as connection:
            rows = connection.execute(
                "SELECT run_id FROM runs WHERE status = ? OR"
                " (status = ? AND (owner_id IS NULL OR lease_expires_at IS NULL"
                " OR lease_expires_at <= ?)) ORDER BY created_at, run_id LIMIT ?",
                (RunStatus.PENDING.value, RunStatus.RUNNING.value, now, limit),
            ).fetchall()
        return [RunId(row["run_id"]) for row in rows]

    def run_origin(self, run_id: RunId) -> RunOrigin | None:
        with self._read() as connection:
            row = connection.execute(
                "SELECT origin_json FROM run_origins WHERE run_id = ?", (run_id,)
            ).fetchone()
        return RunOrigin.model_validate_json(row["origin_json"]) if row else None

    def event(self, run_id: RunId, seq: int) -> JournalEvent | None:
        with self._read() as connection:
            row = connection.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq = ?", (run_id, seq)
            ).fetchone()
        return self._event_from_row(row) if row else None

    def max_event_seq(self, run_id: RunId) -> int:
        with self._read() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(seq), 0) AS seq FROM events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row["seq"])

    def _run_record_from_row(self, row: sqlite3.Row) -> RunRecord:
        status = RunStatus(row["status"])
        if status is not RunStatus.RUNNING:
            liveness = "not_applicable"
        elif (
            row["owner_id"] is not None
            and row["lease_expires_at"] is not None
            and row["lease_expires_at"] > self._now_iso()
        ):
            liveness = "live"
        else:
            liveness = "lost"
        origin_json = row["origin_json"]
        return RunRecord(
            run_id=RunId(row["run_id"]),
            manifest_hash=Digest(row["manifest_hash"]),
            input_hash=Digest(row["input_hash"]),
            status=status,
            liveness=liveness,
            created_at=row["created_at"],
            owner_id=row["owner_id"],
            lease_expires_at=row["lease_expires_at"],
            cancel_requested=bool(row["cancel_requested"]),
            origin=RunOrigin.model_validate_json(origin_json) if origin_json else None,
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> JournalEvent:
        return JournalEvent(
            run_id=RunId(row["run_id"]),
            seq=row["seq"],
            kind=row["kind"],
            path=(
                ExecutionPath.model_validate_json(row["path_json"])
                if row["path_json"]
                else None
            ),
            created_at=row["created_at"],
            payload=json.loads(row["payload"]) if row["payload"] else None,
        )
