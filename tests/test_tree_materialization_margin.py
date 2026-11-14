"""This repository is its own maintenance base, and a gate snapshots it whole (#423).

``ContainedGateRunner._snapshot`` has Git write ``git archive --format=tar`` of the
prepared merge commit to a file in its payload, under the ``RLIMIT_FSIZE`` that
``substrate/git/process.py`` sets on every trusted Git child. Past the bound every
full-tree gate refuses with "gate snapshot archive failed". The check lives in the
CI scope script so prose-only changes run it too.

It says this base fits with one tar record to spare. It does not say every candidate
an exam accepts fits, nor that a snapshot finishes in time on a given host.
"""

import math
import re
import shutil
from pathlib import Path

import pytest
from scripts.ci import m8_ci_scope as scope

from constructicon.substrate.git import process

ROOT = Path(__file__).resolve().parents[1]
CHECKOUT = pytest.mark.skipif(
    shutil.which("git") is None or not (ROOT / ".git").exists(),
    reason="needs this repository's Git checkout",
)


def test_the_scope_script_restates_the_gate_snapshot_bound_exactly():
    (factors,) = re.findall(r"\(resource\.RLIMIT_FSIZE, ([\d *]+)\)", process._LIMITED_EXEC)
    assert math.prod(int(factor) for factor in factors.split("*")) == scope.GATE_SNAPSHOT_BOUND
    assert scope.REQUIRED_TREE_MARGIN >= scope.TAR_RECORD


@CHECKOUT
def test_the_committed_tree_leaves_a_record_under_the_gate_snapshot_bound():
    margin = scope.verify_tree_margin(ROOT)
    assert margin >= scope.REQUIRED_TREE_MARGIN
    assert (scope.GATE_SNAPSHOT_BOUND - margin) % scope.TAR_RECORD == 0


@CHECKOUT
def test_ambient_line_ending_configuration_does_not_change_the_measurement(monkeypatch):
    plain = scope.verify_tree_margin(ROOT)
    for name, value in (("COUNT", "1"), ("KEY_0", "core.autocrlf"), ("VALUE_0", "true")):
        monkeypatch.setenv("GIT_CONFIG_" + name, value)
    assert scope.verify_tree_margin(ROOT) == plain


@CHECKOUT
def test_the_docs_command_runs_the_check_and_reports_its_refusal(monkeypatch, capsys):
    assert scope.main(["docs", "--repository", str(ROOT)]) == 0
    assert f"tree margin: {scope.verify_tree_margin(ROOT)} bytes" in capsys.readouterr().out

    def refuse(repository):
        raise scope.ScopeError("tree-materialization-margin: full")

    monkeypatch.setattr(scope, "verify_tree_margin", refuse)
    assert scope.main(["docs", "--repository", str(ROOT)]) == 2
    assert "tree-materialization-margin" in capsys.readouterr().err


@CHECKOUT
def test_a_tree_at_the_bound_is_refused_by_name():
    size = scope.GATE_SNAPSHOT_BOUND - scope.verify_tree_margin(ROOT)
    assert scope.verify_tree_margin(ROOT, size + scope.REQUIRED_TREE_MARGIN) == scope.TAR_RECORD
    with pytest.raises(scope.ScopeError, match="tree-materialization-margin: HEAD archives"):
        scope.verify_tree_margin(ROOT, size + scope.REQUIRED_TREE_MARGIN - 1)
