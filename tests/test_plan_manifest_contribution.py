"""Fixed stdlib consumer for a later, data-only maintenance contribution.

Absence is explicitly skipped, never reported as a passing vector exam. The
application gate separately enforces the complete immutable Git-tree scope.
"""

from __future__ import annotations

import hashlib
import stat
import unittest
from pathlib import Path

from constructicon.substrate.gates.maintenance import VectorRunReport, run_vectors

ROOT = Path(__file__).resolve().parents[1]


def contribution_result(root: Path) -> VectorRunReport | None:
    path = root / "tests/vectors/plan_manifest.json"
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 32768:
        raise ValueError("contribution must be a bounded regular JSON file")
    source = (root / "scripts/regen_plan_manifest.py").read_bytes()
    return run_vectors(path.read_bytes(), source, hashlib.sha256(source).hexdigest())


class PlanManifestContribution(unittest.TestCase):
    def test_retained_vectors_pass_the_fixed_exam(self) -> None:
        report = contribution_result(ROOT)
        if report is None:
            self.skipTest("this revision has no plan-manifest vector contribution")
        self.assertTrue(report.passed, "candidate does not distinguish the fixed mutant set")


if __name__ == "__main__":
    unittest.main()
