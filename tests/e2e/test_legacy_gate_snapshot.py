"""Legacy composed gate -> merge path must not attest a tree it did not test.

Regression for issue #369: ``.gitattributes`` ``export-ignore`` once let the
legacy ``GitAuthority.read_snapshot`` drop a failing test from the gated tree
while the merge commit still contained it."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from constructicon.core.address import RunId
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.substrate.git.authority import StagedWriteWorkspace
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.gitworld import GOOD_FIX, build_git_system, build_graph


async def _propose_files(
    ctx: NodeContext, inputs: Mapping[str, Any], files: Mapping[str, str]
) -> Mapping[str, Any]:
    workspace = ctx.capability("workspace")
    assert isinstance(workspace, StagedWriteWorkspace)
    Path(workspace.path, "calc.py").write_text(inputs["goal"]["content"])
    for name, content in files.items():
        Path(workspace.path, name).write_text(content, newline="\n")
    sha = workspace.commit_all("propose")
    return {"candidate": {"commit": str(sha), "base": str(workspace.base)}}


# Registered implementations must be module-level (cold-importable).
async def propose_export_ignored_failure(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    return await _propose_files(ctx, inputs, {
        "test_bad.py": "def test_bad() -> None:\n    assert False\n",
        ".gitattributes": "test_bad.py export-ignore\n",
    })


async def propose_ordinary_attributes(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    return await _propose_files(ctx, inputs, {".gitattributes": "*.py text eol=lf\n"})


GOAL = {"goal": {"title": "t", "content": GOOD_FIX}}


async def test_export_ignored_failing_test_cannot_pass_gates_or_merge(
    tmp_path: Path, journal: SqliteJournal
) -> None:
    system, world = build_git_system(
        tmp_path, journal, propose=propose_export_ignored_failure
    )
    base = world.authority.resolve_ref("refs/heads/main")

    result = await system._start_direct(build_graph(), GOAL, run_id=RunId("run-ignore"))

    assert result.status is not RunStatus.SUCCEEDED
    assert world.authority.resolve_ref("refs/heads/main") == base  # nothing merged
    kinds = [e.kind for e in journal.events(RunId("run-ignore"), limit=400)]
    assert "EffectCommitted" not in kinds
    snapshots = tmp_path / "workspaces" / "snapshots"
    assert not snapshots.exists() or list(snapshots.iterdir()) == []


async def test_ordinary_attributes_still_gate_and_merge(
    tmp_path: Path, journal: SqliteJournal
) -> None:
    system, _world = build_git_system(
        tmp_path, journal, propose=propose_ordinary_attributes
    )

    result = await system._start_direct(build_graph(), GOAL, run_id=RunId("run-ok"))

    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["merged"]["status"] == "committed"
