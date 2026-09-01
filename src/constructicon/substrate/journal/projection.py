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
from constructicon.substrate.journal._sqlite_runs import require_run_world_seal
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
        # The whole row, joined to its origin, because that is what the run's
        # positive seal is about. A projection that selected only the columns it
        # prints could not ask for that proof, and a rewrite from one valid
        # value to another would leave the store readable and the projected
        # bytes quietly wrong — which is the one thing a canonical projection
        # must never be.
        run = conn.execute(
            "SELECT r.*, o.origin_json FROM runs AS r"
            " LEFT JOIN run_origins AS o ON o.run_id = r.run_id"
            " WHERE r.run_id = ?",
            (run_id,),
        ).fetchone()
        if run is None:
            raise ContractViolation(f"unknown run {run_id!r}")
        require_run_world_seal(conn, run)
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
