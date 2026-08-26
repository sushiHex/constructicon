"""Projections: regenerable views over one journal read snapshot.

SQLite is authoritative; ``events.jsonl`` and ``summary.json`` are disposable
projections derived from a single read transaction, canonical under the
identity law — identical durable state produces identical bytes (no wall
clock, no derived liveness; the stored lease expiry is included and callers
derive liveness themselves).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import RunId
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.substrate.journal.sqlite import SqliteJournal

PROJECTION_SCHEMA_VERSION = 1


class ProjectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: RunId
    through_seq: int
    events_digest: Digest
    summary_digest: Digest


def project_run(journal: SqliteJournal, run_id: RunId, out_dir: Path) -> ProjectionResult:
    with journal._read() as conn:  # projection is a journal-family module
        conn.execute("BEGIN")  # one WAL read snapshot for run + events
        run = conn.execute(
            "SELECT status, manifest_hash, input_hash, lease_expires_at"
            " FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if run is None:
            raise ContractViolation(f"unknown run {run_id!r}")
        rows = conn.execute(
            "SELECT seq, kind, path_json, payload, created_at FROM events"
            " WHERE run_id = ? ORDER BY seq ASC",
            (run_id,),
        ).fetchall()
        conn.execute("COMMIT")

    lines: list[str] = []
    through_seq = 0
    for row in rows:
        through_seq = int(row["seq"])
        event: dict[str, Any] = {
            "schema_version": PROJECTION_SCHEMA_VERSION,
            "run_id": run_id,
            "seq": through_seq,
            "kind": row["kind"],
            "path": json.loads(row["path_json"]) if row["path_json"] else None,
            "payload": json.loads(row["payload"]) if row["payload"] else None,
            "created_at": row["created_at"],
        }
        lines.append(canonical_json(event))
    events_text = "".join(line + "\n" for line in lines)

    summary = {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "run_id": run_id,
        "projected_through_seq": through_seq,
        "status": run["status"],
        "manifest_hash": run["manifest_hash"],
        "input_hash": run["input_hash"],
        "event_count": len(lines),
        "lease_expires_at": run["lease_expires_at"],
    }
    summary_text = canonical_json(summary) + "\n"

    out_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(out_dir / "events.jsonl", events_text)
    _atomic_write(out_dir / "summary.json", summary_text)

    return ProjectionResult(
        run_id=run_id,
        through_seq=through_seq,
        events_digest=digest("projection-events", 1, events_text),
        summary_digest=digest("projection-summary", 1, summary_text),
    )


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
