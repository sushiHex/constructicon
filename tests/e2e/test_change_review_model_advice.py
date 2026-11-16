"""The example's explicit model-advice opt-in refuses by name, never by traceback.

Credential-free and off-host: each stage stops at its named refusal before any
host assembly, permit read or model call. The permitted run itself is driven in
tests/api/test_change_review_advice.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from examples.change_review import demo_commits

ROOT = Path(__file__).parents[2]


def opt_in(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess:
    repository, before, after = demo_commits(tmp_path / "sample")
    return subprocess.run(
        [sys.executable, "-m", "examples.change_review", "--state", str(tmp_path / "state"),
         "model-advice", "--repository", str(repository), "--before-commit", before,
         "--after-commit", after, "--path", "calc.py", *arguments],
        cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
        timeout=60, check=False,
    )


def refused(process: subprocess.CompletedProcess) -> dict:
    assert process.returncode == 1, (process.stdout, process.stderr)
    assert "Traceback" not in process.stderr and process.stdout == ""
    return json.loads(process.stderr)


def test_a_run_without_its_permit_is_a_named_refusal(tmp_path: Path) -> None:
    report = refused(opt_in(tmp_path, "--stage", "run"))
    assert report["refusal"] == ["advice.permit"]
    journal = (tmp_path / "advice.sqlite").resolve()
    report = refused(opt_in(tmp_path, "--stage", "run", "--journal", str(journal)))
    assert report["refusal"] == ["advice.permit"] and not journal.exists()
    assert not (tmp_path / "state").exists()


def test_pins_without_the_host_is_a_named_refusal(tmp_path: Path) -> None:
    report = refused(opt_in(tmp_path, "--stage", "pins"))
    assert report["refusal"] == ["advice.provider"]


def test_the_installed_entry_refuses_a_summary_outside_the_closed_list(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"scope": "x", "before_ref": {"repository": "/r"}}),
                       encoding="utf-8")
    process = subprocess.run(
        [sys.executable, "-m", "constructicon.api.change_review_advice",
         "--summary", str(summary), "--stage", "run"],
        cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
        timeout=60, check=False,
    )
    assert process.returncode == 1 and "Traceback" not in process.stderr
    assert json.loads(process.stdout)["refusal"] == ["advice.summary"]
