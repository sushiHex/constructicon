"""FakeExternalLedger — the independently durable "outside" (I7).

One SQLite file (``fake-external.db``) records every externally visible
transition the fakes perform: announce executions and executor calls. It is a
separate database from the journal on purpose — recovery tests prove that
crash and resume consult an external world the journal cannot retroactively
edit, and the parent process of a killed worker asserts exactly which
uncheckpointed work replayed.

The default path is ``:memory:`` (per-instance, connection-held), so unit
tests get the identical code path with no files; crash tests pass a real path
and reopen it from a fresh process.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS announce_executions (
    execution_seq   INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json    TEXT NOT NULL,
    receipt_json    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS executor_calls (
    call_seq  INTEGER PRIMARY KEY AUTOINCREMENT,
    executor  TEXT NOT NULL,
    task_json TEXT NOT NULL
);
"""


class FakeExternalLedger:
    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self._conn = sqlite3.connect(str(db_path), timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- announce (native idempotency, like a well-behaved external API) -----

    def announce_receipt(self, idempotency_key: str) -> str | None:
        row = self._conn.execute(
            "SELECT receipt_json FROM announce_executions WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return row["receipt_json"] if row else None

    def record_announce(
        self, idempotency_key: str, request_json: str, receipt_json: str
    ) -> None:
        self._conn.execute(
            "INSERT INTO announce_executions"
            " (idempotency_key, request_json, receipt_json) VALUES (?, ?, ?)",
            (idempotency_key, request_json, receipt_json),
        )
        self._conn.commit()

    def announce_requests(self) -> list[str]:
        """request_json per REAL external transition, in execution order."""
        rows = self._conn.execute(
            "SELECT request_json FROM announce_executions ORDER BY execution_seq ASC"
        ).fetchall()
        return [row["request_json"] for row in rows]

    def announce_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM announce_executions"
        ).fetchone()
        return int(row["n"])

    # -- executor calls (append-only; every invocation, replayed or not) -----

    def record_executor_call(self, executor: str, task_json: str) -> None:
        self._conn.execute(
            "INSERT INTO executor_calls (executor, task_json) VALUES (?, ?)",
            (executor, task_json),
        )
        self._conn.commit()

    def executor_calls(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT task_json FROM executor_calls ORDER BY call_seq ASC"
        ).fetchall()
        return [row["task_json"] for row in rows]

    def close(self) -> None:
        self._conn.close()
