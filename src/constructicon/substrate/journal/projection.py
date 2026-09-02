"""Projections: regenerable views over one journal read snapshot.

SQLite is authoritative; ``events.jsonl`` and ``summary.json`` are disposable
projections derived from a single read transaction, canonical under the
identity law — identical durable state produces identical bytes (no wall
clock, no derived liveness; the stored lease expiry is included and callers
derive liveness themselves).
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import RunId
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.substrate.journal._sqlite_base import (
    _durable_digest,
    _durable_run_fields,
)
from constructicon.substrate.journal._sqlite_execution_facts import stored_event_from_row
from constructicon.substrate.journal._sqlite_runs import (
    RUN_PROJECTION_COLUMNS,
    RUN_PROJECTION_JOINS,
    register_run_origin_guard,
    validated_run_fence,
)
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
        # The same row and the same proof every other run projector uses. The
        # immutable world is the run's positive seal; the status and the lease
        # it also prints are mutable, and only the lifecycle law can say they
        # are true — a status names the latest sealed event, and the event
        # extent must agree with the allocation fence. A projection that proved
        # less than that could print a `succeeded` no event ever recorded, or
        # a history with an interior event quietly missing, and still be
        # byte-stable: canonical, and wrong.
        register_run_origin_guard(conn)
        run = conn.execute(
            "SELECT " + RUN_PROJECTION_COLUMNS + RUN_PROJECTION_JOINS + " WHERE r.run_id = ?",
            (run_id,),
        ).fetchone()
        if run is None:
            raise ContractViolation(f"unknown run {run_id!r}")
        validated_run_fence(conn, run)
        rows = conn.execute(
            "SELECT * FROM events WHERE run_id = ? ORDER BY seq ASC",
            (run_id,),
        ).fetchall()
        stored_events = [stored_event_from_row(conn, row) for row in rows]

    run_fields = _durable_run_fields(run)
    manifest_hash = _durable_digest(
        run["manifest_hash"],
        fact=f"run {run_id!r} manifest identity",
    )
    input_hash = _durable_digest(
        run["input_hash"],
        fact=f"run {run_id!r} input identity",
    )
    lines: list[str] = []
    through_seq = 0
    for stored in stored_events:
        through_seq = stored.seq
        event: dict[str, Any] = {
            "schema_version": PROJECTION_SCHEMA_VERSION,
            "run_id": stored.run_id,
            "seq": through_seq,
            "kind": stored.kind,
            "path": (stored.path.model_dump(mode="json") if stored.path is not None else None),
            "payload": stored.payload,
            "created_at": stored.created_at.isoformat(),
        }
        lines.append(canonical_json(event))
    events_text = "".join(line + "\n" for line in lines)

    summary = {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "run_id": run_id,
        "projected_through_seq": through_seq,
        "status": run_fields.status.value,
        "manifest_hash": manifest_hash,
        "input_hash": input_hash,
        "event_count": len(lines),
        "lease_expires_at": (
            run_fields.lease_expires_at.isoformat()
            if run_fields.lease_expires_at is not None
            else None
        ),
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
