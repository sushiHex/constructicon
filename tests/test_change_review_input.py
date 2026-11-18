"""The offline packet uses committed source as data and claims fresh output."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from examples import change_review
from scripts.ops.change_review_input import main, prepare

from constructicon.api import change_review_advice as advice
from constructicon.core import control, identity


@pytest.fixture
def source_world(tmp_path):
    repository, before, after = change_review.demo_commits(tmp_path / "sample")
    change_review.git(repository, "config", "user.name", "Packet fixture")
    change_review.git(repository, "config", "user.email", "fixture@example.invalid")
    for name, module in (
        ("examples/change_review.py", change_review),
        ("src/constructicon/api/change_review_advice.py", advice),
        ("src/constructicon/core/control.py", control),
        ("src/constructicon/core/identity.py", identity),
    ):
        target = repository / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(module.__file__).read_bytes())
    change_review.git(repository, "add", "examples", "src")
    change_review.git(repository, "commit", "-qm", "pin preparation sources")
    controller = change_review.git(repository, "rev-parse", "HEAD").decode().strip()
    return repository, controller, before, after


def test_packet_uses_the_actual_summary_and_instruction_producers(source_world, tmp_path):
    repository, controller, before, after = source_world
    out = tmp_path / "packet"
    record = prepare(repository, controller, before, after, "calc.py", out)
    raw = (out / "summary.json").read_bytes()
    summary = advice.ChangeSummaryV2.model_validate_json(raw)
    bound = advice.bound_values(summary)
    assert record["summary_sha256"] == hashlib.sha256(raw).hexdigest()
    assert record["offline_pins"] == bound.projection()
    assert record["offline_pins_are_provisional"] is True
    assert record["execution_authorized"] is False
    assert record["change"] == {"before": before, "after": after, "path": "calc.py"}
    instruction = (out / "instruction.txt").read_bytes()
    assert instruction == bound.instruction.encode("utf-8")
    assert str(repository).encode() not in instruction and b"return sum" not in instruction
    assert b"\r" not in raw + instruction
    assert json.loads((out / "packet.json").read_bytes()) == record
    assert set(p.name for p in out.iterdir()) == {"summary.json", "instruction.txt", "packet.json"}


def test_an_occupied_output_is_never_replaced(source_world, tmp_path):
    out = tmp_path / "occupied"
    out.mkdir()
    (out / "keep").write_bytes(b"neighbor")
    with pytest.raises(FileExistsError):
        prepare(*source_world, "calc.py", out)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == {"keep": b"neighbor"}


def test_selected_source_drift_refuses_before_claim(source_world, tmp_path):
    repository, _, before, after = source_world
    changed = repository / "src/constructicon/core/identity.py"
    changed.write_bytes(changed.read_bytes() + b"\n# different selected source\n")
    change_review.git(repository, "add", str(changed))
    change_review.git(repository, "commit", "-qm", "different identity source")
    controller = change_review.git(repository, "rev-parse", "HEAD").decode().strip()
    out = tmp_path / "refused"
    with pytest.raises(ValueError, match="imported source differs"):
        prepare(repository, controller, before, after, "calc.py", out)
    assert not out.exists()


def test_real_isolated_entry_prepares_and_refuses_reuse(source_world, tmp_path):
    repository, controller, before, after = source_world
    root = Path(__file__).resolve().parents[1]
    argv = [sys.executable, "-I", "-B", str(root / "scripts/ops/change_review_input.py"),
            "--repository", str(repository), "--controller", controller,
            "--before", before, "--after", after, "--path", "calc.py",
            "--out", str(tmp_path / "cli-packet")]
    runs = [subprocess.run(argv, cwd=tmp_path, stdin=subprocess.DEVNULL,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                           capture_output=True, timeout=30) for _ in range(2)]
    assert [(p.returncode, p.stderr) for p in runs] == [(0, b""), (1, b"")]
    assert json.loads(runs[0].stdout)["status"] == "prepared"
    assert json.loads(runs[1].stdout) == {
        "status": "refused", "reason": "consumer-input-unproved",
    }


def test_a_valid_wide_summary_is_an_opaque_instruction_bound_refusal(
    source_world, tmp_path, capsys,
):
    repository, controller, _, _ = source_world

    def functions(prefix, returned):
        return "\n".join(
            f"def {prefix}{'一' * 74}_{index:02}(): return {returned}"
            for index in range(25)
        )

    for label, source in (
        ("before", functions("共有", 1) + "\n" + functions("削除", 1)),
        ("after", functions("共有", 2) + "\n" + functions("追加", 2)),
    ):
        (repository / "calc.py").write_text(source, encoding="utf-8", newline="\n")
        change_review.git(repository, "add", "calc.py")
        change_review.git(repository, "commit", "-qm", label)
        commit = change_review.git(repository, "rev-parse", "HEAD").decode().strip()
        if label == "before":
            before = commit
        else:
            after = commit
    out = tmp_path / "too-wide"
    assert main(["--repository", str(repository), "--controller", controller,
                 "--before", before, "--after", after, "--path", "calc.py",
                 "--out", str(out)]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "refused", "reason": "consumer-input-unproved",
    }
    assert not out.exists()
