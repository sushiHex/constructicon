import subprocess
import sys
from types import SimpleNamespace

import pytest
from scripts import _mutations


@pytest.mark.parametrize("flag", [None, 0x08000000])
def test_inventory_children_do_not_create_windows(monkeypatch, flag):
    if flag is None:
        monkeypatch.delattr(subprocess, "CREATE_NO_WINDOW", raising=False)
    else:
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", flag, raising=False)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "git":
            return SimpleNamespace(stdout=b"")
        baseline = "--baseline" in args
        marker = "MUTATION_BASELINE_PASSED" if baseline else "MUTATION_ASSERTION_FAILURE"
        output = f'MUTATION_COLLECTION ["test_node"]\n{marker} ["test_node"]\n'
        return SimpleNamespace(stdout=output, stderr="", returncode=0 if baseline else 1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["inventory.py"])
    assert _mutations.run([("case", "module:function", "before", "after", "test_node")]) == 0
    assert len(calls) == 4  # two snapshots, baseline, and mutant
    assert [args[0] == "git" for args, _ in calls] == [True, False, False, True]
    for _, kwargs in calls:
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["creationflags"] == (flag or 0)
