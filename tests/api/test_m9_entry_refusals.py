"""Actual installed entry boundaries retain typed causes without private text."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest

from constructicon.api import m9_trial
from constructicon.api._m9.evaluator import wait_deadline
from constructicon.api._m9.evidence import TrialIdentity
from constructicon.api._m9.trial import _open
from constructicon.api.control import ControlPlane
from constructicon.core.address import RunId
from constructicon.core.control import ControlCode, ControlRejected
from constructicon.core.run import RunState, RunStatus


def failure(stderr):
    prefix = "M9 trial stopped: "
    assert stderr.startswith(prefix) and "Traceback" not in stderr and "PRIVATE" not in stderr
    return json.loads(stderr.removeprefix(prefix))


@pytest.mark.parametrize("damage,expected", [
    ("future-schema", "M9_JOURNAL_DAMAGED"), ("sqlite-bytes", "M9_JOURNAL_UNAVAILABLE"),
])
def test_cli_journal_corruption_is_a_closed_staged_refusal(tmp_path, damage, expected):
    root, trial = tmp_path / "PRIVATE-store", TrialIdentity("damage")
    _open(root, trial, initialize=True)
    database = root / "journal.sqlite"
    if damage == "future-schema":
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA user_version = 999")
            connection.commit()
    else:
        database.write_bytes(b"not a sqlite database")
    process = subprocess.run(
        [sys.executable, "-m", "constructicon.api.m9_trial", "seed", "--trial", trial.trial_id,
         "--store", str(root)], stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=20, check=False,
    )
    assert process.returncode == 1 and process.stdout == ""
    assert failure(process.stderr) == {
        "status": "refused", "stage": "seed", "operation": "seed", "code": expected,
    }
    assert str(root) not in process.stderr


def test_main_preserves_typed_control_refusals_at_each_approval_and_move_boundary(
    tmp_path, monkeypatch, capsys,
):
    root = tmp_path / "trial"

    def invoke(stage, *, rejected=False):
        args = [stage, "--trial", "control", "--store", str(root)]
        if rejected:
            with pytest.raises(SystemExit) as stopped:
                m9_trial.main(args)
            assert stopped.value.code == 1
            output = capsys.readouterr()
            assert output.out == ""
            result = failure(output.err)
            assert result == {
                "status": "refused", "code": "M9_CONTROL_REJECTED",
                "stage": "prepare" if stage == "rehearse" else stage,
                "operation": stage, "control_codes": [ControlCode.COMMAND_IN_PROGRESS.value],
                "partial": False,
            }
        else:
            assert m9_trial.main(args) == 0
            output = capsys.readouterr()
            assert output.err == "" and json.loads(output.out)["status"]

    rejection = ControlRejected.one_fault(
        ControlCode.COMMAND_IN_PROGRESS, "PRIVATE backend value", "PRIVATE repair",
    )
    original_start = ControlPlane.runs_start

    async def refuse_issuance(control, *args, **kwargs):
        if kwargs["proposal"].name == "m9-operator-issue":
            return rejection
        return await original_start(control, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(ControlPlane, "runs_start", refuse_issuance)
        invoke("rehearse", rejected=True)
    invoke("rehearse")
    for stage, method in (
        ("approve", "runs_approve"), ("promote", "registry_promote"),
        ("rollback", "registry_rollback"),
    ):
        async def refuse(*args, **kwargs):
            return rejection

        with monkeypatch.context() as patch:
            patch.setattr(ControlPlane, method, refuse)
            invoke(stage, rejected=True)
        invoke(stage)


def test_main_wait_timeout_keeps_named_read_time_diagnostics(tmp_path, monkeypatch, capsys):
    journal = _open(tmp_path / "trial", TrialIdentity("wait"), initialize=True)
    monkeypatch.setattr(journal, "run_state", lambda run: RunState(
        status=RunStatus.RUNNING, liveness="lost",
    ))

    async def wait(options):
        async with wait_deadline(journal, RunId("run-lost-owner"), "select", timeout_s=0.001):
            await asyncio.sleep(1)

    monkeypatch.setattr(m9_trial, "dispatch", wait)
    with pytest.raises(SystemExit) as stopped:
        m9_trial.main(["propose", "--trial", "wait", "--store", str(tmp_path / "trial")])
    assert stopped.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert failure(output.err) == {
        "status": "refused", "code": "M9_WAIT_TIMEOUT", "stage": "select",
        "operation": "propose", "run": "run-lost-owner", "run_status": "running",
        "liveness": "lost",
    }
