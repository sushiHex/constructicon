"""An isolated installed-shaped runtime has no tests, scripts or pytest dependency."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

from constructicon.api._m9.proposer import source_revision


def test_runtime_only_install_runs_actual_cli_through_owner_and_rollback(tmp_path):
    installed = tmp_path / "controller"
    source = Path(__file__).resolve().parents[2] / "src" / "constructicon"
    shutil.copytree(
        source, installed / "constructicon", ignore=shutil.ignore_patterns("__pycache__"),
    )
    # This is the locked runtime closure, not the editable development environment.
    for name in (
        "pydantic", "pydantic_core", "annotated_types", "typing_extensions", "typing_inspection",
    ):
        spec = importlib.util.find_spec(name)
        assert spec is not None and spec.origin is not None
        origin = Path(spec.origin)
        if spec.submodule_search_locations is not None:
            shutil.copytree(origin.parent, installed / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(origin, installed / origin.name)
    entry = (
        "import importlib.util,sys;sys.path.insert(0,sys.argv.pop(1));"
        "assert all(importlib.util.find_spec(n) is None for n in ('pytest','tests','scripts'));"
        "from constructicon.api._m9.proposer import source_revision;"
        f"assert str(source_revision())=={str(source_revision())!r};"
        "from constructicon.api.m9_trial import main;raise SystemExit(main())"
    )
    store = tmp_path / "trial"
    results = []
    for stage in ("rehearse", "approve", "promote", "promote", "rollback"):
        process = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", entry, str(installed), stage,
             "--trial", "installed", "--store", str(store)],
            cwd=tmp_path, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=45, check=False,
        )
        assert process.returncode == 0, (process.stdout, process.stderr)
        results.append(json.loads(process.stdout))
    assert [result["status"] for result in results] == [
        "awaiting-owner", "approved", "promoted", "promoted", "rolled_back",
    ]
    assert results[3] == {**results[2], "replayed": True}
    assert results[-1]["to"] == results[2]["from"]
