"""Every mutation inventory runs in CI, and every mutant still names live code.

An inventory is only evidence when it runs, and a mutant only when its target
still exists. Both used to be learned at run time, from CI or never: six
inventories ran nowhere, and refactors orphaned targets more than once. Here
both are checked statically, by the harness's own resolution, so the suite
fails instead.
"""

from __future__ import annotations

import re
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
WORKFLOWS = ROOT / ".github" / "workflows"
INVENTORIES = sorted(path.name for path in SCRIPTS.glob("check_*_mutations.py"))


@pytest.fixture(scope="module")
def harness():
    sys.path.insert(0, str(SCRIPTS))
    try:
        import _mutations

        yield _mutations
    finally:
        sys.path.remove(str(SCRIPTS))


def mutants(name: str) -> list[tuple]:
    loaded = runpy.run_path(str(SCRIPTS / name))
    return list(loaded["MUTANTS"])


def test_every_inventory_runs_in_exactly_one_ci_place():
    found = [
        script
        for workflow in sorted(WORKFLOWS.glob("*.yml"))
        for script in re.findall(r"\b(check_\w+_mutations\.py)\b", workflow.read_text("utf-8"))
    ]
    assert sorted(found) == INVENTORIES


@pytest.mark.parametrize("name", INVENTORIES)
def test_every_mutant_names_live_code(harness, name):
    """The harness's own resolution: the target imports, its text occurs exactly
    once, and the mutated source still parses."""
    entries = mutants(name)
    assert entries, name
    for entry in entries:
        assert isinstance(entry, tuple) and len(entry) == 5, (name, entry)
        label, target, before, after, _test = entry
        try:
            harness.mutated(target, before, after)
        except Exception as exc:  # name the mutant, whatever failed
            pytest.fail(f"{name}: {label}: {exc!r}")


def test_every_killing_test_is_collected(tmp_path):
    """A renamed test or parameter id is a run-time NOT PROVEN; collect them all now."""
    nodes = sorted({entry[4] for name in INVENTORIES for entry in mutants(name)})
    arguments = tmp_path / "nodes.txt"
    arguments.write_text("\n".join(nodes) + "\n", encoding="utf-8")
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         f"@{arguments}"],
        cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600,
        check=False,
    )
    assert collected.returncode == 0, collected.stdout[-4000:] + collected.stderr[-2000:]
