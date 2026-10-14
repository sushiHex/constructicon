"""Command crash seams converge in a fresh process without physical cleanup."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.e2e.disposal_crash_worker import CRASH_EXIT_CODE, RUN
from tests.migrations.test_sqlite_v7_to_v8 import historical_database


def process(directory, seam):
    return subprocess.run(
        [sys.executable, "-m", "tests.e2e.disposal_crash_worker", str(directory), seam],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=60, check=False,
    )


@pytest.mark.parametrize(
    "seam", ("after_plan", "after_domain_mutation", "after_command_completion",
             "after_domain_comparison"),
)
def test_real_process_disposal_restart_keeps_one_receipt_and_physical_guard(tmp_path, seam):
    historical_database(tmp_path / "journal.db", "schema8-disposal-baseline.sql")
    with sqlite3.connect(tmp_path / "journal.db") as journal:
        baseline_epoch = journal.execute(
            "SELECT owner_epoch FROM runs WHERE run_id=?", (RUN,),
        ).fetchone()[0]
        pairs = journal.execute(
            "SELECT lease_id, acquisition_epoch, resource_ref FROM capability_leases"
            " WHERE run_id = ? ORDER BY lease_id", (RUN,),
        ).fetchall()
    with sqlite3.connect(tmp_path / "fake-physical.db") as physical:
        physical.execute("CREATE TABLE physical_resources (lease_id TEXT, epoch INTEGER,"
                         " resource_ref TEXT, guard_held INTEGER, provider_calls INTEGER)")
        physical.executemany("INSERT INTO physical_resources VALUES (?, ?, ?, 1, 0)", pairs)
        before = physical.execute("SELECT * FROM physical_resources ORDER BY lease_id").fetchall()
    crashed = process(tmp_path, seam)
    assert crashed.returncode == CRASH_EXIT_CODE, (
        crashed.returncode, crashed.stdout, crashed.stderr,
    )
    recovered = process(tmp_path, "recover")
    assert recovered.returncode == 0, (recovered.stdout, recovered.stderr)
    response = json.loads(recovered.stdout)
    superseded = seam == "after_domain_comparison"
    if superseded:
        assert response["status"] == "rejected" and response["faults"]
    else:
        assert response["status"] == "disposed" and response["count"] == 2
        assert response["physical_cleanup"] == "unverified"
    replay = process(tmp_path, "recover")
    assert replay.returncode == 0, replay.stderr
    replayed = json.loads(replay.stdout)
    if superseded:
        assert replayed == response
    else:
        assert replayed["command"]["replayed"] is True
        first_metadata = response.pop("command")
        replay_metadata = replayed.pop("command")
        assert first_metadata["command_id"] == replay_metadata["command_id"]
        assert replayed == response
    journal = SqliteJournal(tmp_path / "journal.db")
    events = journal.events(RUN)
    audits = [event for event in events if event.kind == "CapabilityDisposalRecorded"]
    assert len(audits) == int(not superseded)
    assert sum(event.kind == "LeaseTransition" for event in events) == (0 if superseded else 2)
    assert all(row.state == ("active" if superseded else "lost")
               for row in journal.capability_leases(RUN))
    assert journal.run_head(RUN).record.status.value == "running"
    assert journal.run_head(RUN).record.owner_id is None
    operation = "runs_dispose_capabilities"
    through = journal.latest_command_key(operation=operation)
    assert through is not None
    commands = journal.command_records(operation=operation, after=None, through=through, limit=10)
    assert len(commands) == 1
    assert commands[0].state == ("rejected" if superseded else "committed")
    with sqlite3.connect(tmp_path / "journal.db") as connection:
        assert connection.execute(
            "SELECT owner_epoch FROM runs WHERE run_id=?", (RUN,),
        ).fetchone()[0] == baseline_epoch + int(superseded)
    with sqlite3.connect(tmp_path / "fake-physical.db") as physical:
        after = physical.execute("SELECT * FROM physical_resources ORDER BY lease_id").fetchall()
        assert after == before
