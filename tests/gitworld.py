"""Shared git-authority fixtures: a seeded bare authority, the build graph
(propose -> gate -> merge), and its module-level component implementations."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from constructicon.api.system import Constructicon, GitWorld, git_world
from constructicon.core.address import GitSha
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.graph import Connection, Graph, GraphNode, Ref
from constructicon.core.ports import Port
from constructicon.runtime.context import NodeContext
from constructicon.substrate.gates.runner import BoundGateRunner, CheckSpec
from constructicon.substrate.git.authority import StagedWriteWorkspace
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import LEASE_TTL_S, atomic

GOAL = Port(name="goal", type_id="git/Goal", schema_hash="s1")
CANDIDATE = Port(name="candidate", type_id="git/Candidate", schema_hash="s1")
EVALUATION = Port(name="evaluation", type_id="git/Evaluation", schema_hash="s1")
MERGED = Port(name="merged", type_id="git/Merged", schema_hash="s1")

WRITE_GRANTS = EffectiveGrants(
    posture=Posture.WRITE,
    model_selection=ModelSelection(kind="backend_default"),
    effort=None,
    allowed_tools=(),
    env_allowlist=(),
    network="none",
    timeout_s=600,
)

SEED_CALC = "def add(a: int, b: int) -> int:\n    return a + b\n"
SEED_TEST = (
    "from calc import add\n\n\ndef test_add() -> None:\n    assert add(1, 2) == 3\n"
)
GOOD_FIX = (
    "def add(a: int, b: int) -> int:\n    return a + b\n\n\n"
    "def double(value: int) -> int:\n    return add(value, value)\n"
)
BROKEN_FIX = "def add(a: int, b: int) -> int:\n    return a - b\n"  # tests go red

# fast checks for the tiny fixture package (full defaults probe tool versions)
FAST_CHECKS = (
    CheckSpec("ruff", (sys.executable, "-m", "ruff", "check", "--no-cache", "."), 60.0),
    CheckSpec(
        "pytest", (sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"), 120.0
    ),
)


def _host_git(args: list[str], cwd: Path) -> None:
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="seed",
        GIT_AUTHOR_EMAIL="seed@test.invalid",
        GIT_COMMITTER_NAME="seed",
        GIT_COMMITTER_EMAIL="seed@test.invalid",
    )
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


def seed_authority(root: Path, files: dict[str, str] | None = None) -> Path:
    """A bare authority repo whose main holds a minuscule python package."""
    repo = root / "authority.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
    )
    push_to_main(repo, files or {"calc.py": SEED_CALC, "test_calc.py": SEED_TEST}, "seed")
    return repo


def push_to_main(repo: Path, files: dict[str, str], message: str) -> GitSha:
    """Test-side base movement: commit files onto main via a throwaway clone.
    (The deny-push hook guards the authority against agent workspaces; the
    seeding path bypasses it deliberately via a plain fetch into main.)"""
    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "clone"
        clone.mkdir()
        _host_git(["init", "-q", "-b", "main"], clone)
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", "refs/heads/main"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if head:
            _host_git(["fetch", "-q", str(repo), head], clone)
            _host_git(["reset", "-q", "--hard", head], clone)
        for name, content in files.items():
            (clone / name).write_text(content)
        _host_git(["add", "-A"], clone)
        _host_git(["commit", "-q", "-m", message], clone)
        new_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True
        ).stdout.strip()
        # authority-side fetch + ref update (hooks only guard pushes)
        _host_git(["fetch", "-q", str(clone), new_head], repo)
        _host_git(["update-ref", "refs/heads/main", new_head], repo)
        return GitSha(new_head)


async def propose_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    workspace = ctx.capability("workspace")
    assert isinstance(workspace, StagedWriteWorkspace)
    Path(workspace.path, "calc.py").write_text(inputs["goal"]["content"])
    sha = workspace.commit_all(f"propose: {inputs['goal']['title']}")
    return {"candidate": {"commit": str(sha), "base": str(workspace.base)}}


async def failing_propose_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Commits a candidate, then dies — uncheckpointed work must be discarded."""
    workspace = ctx.capability("workspace")
    assert isinstance(workspace, StagedWriteWorkspace)
    Path(workspace.path, "calc.py").write_text(inputs["goal"]["content"])
    workspace.commit_all("propose: doomed")
    raise RuntimeError("proposer died after committing")


async def gate_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    gates = ctx.capability("gates")
    assert isinstance(gates, BoundGateRunner)
    evaluation = gates.verify(GitSha(inputs["candidate"]["commit"]))
    return {
        "evaluation": {
            "ok": evaluation.ok,
            "attestation_id": evaluation.attestation_id,
            "subject": (
                evaluation.subject.model_dump(mode="json")
                if evaluation.subject
                else None
            ),
            "checks": [check.model_dump(mode="json") for check in evaluation.checks],
        }
    }


async def merge_impl(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    evaluation = inputs["evaluation"]
    if evaluation["subject"] is None:
        checks = evaluation["checks"]
        if any(c["name"] == "already-integrated" and c["ok"] for c in checks):
            # a reproduced run over an installed world: truthful, no effect
            return {"merged": {"status": "already_integrated", "reference": None,
                               "observed": None}}
        red = [c["name"] for c in checks if c["status"] != "passed"]
        raise RuntimeError(f"gates produced no merge subject: {red}")
    receipt = await ctx.effect(
        "merge_verified",
        evaluation["subject"],
        attestation_id=evaluation["attestation_id"],
    )
    return {
        "merged": {
            "status": receipt.status,
            "reference": receipt.external_reference,
            "observed": receipt.observed_state,
        }
    }


def build_graph() -> Graph:
    return Graph(
        name="build-fix",
        nodes=(
            GraphNode(
                id="propose",
                body=Ref(component="git/propose", bind={"workspace": "git-workspace"}),
            ),
            GraphNode(
                id="gate", body=Ref(component="git/gate", bind={"gates": "git-gates"})
            ),
            GraphNode(id="merge", body=Ref(component="git/merge")),
        ),
        connections=(
            Connection(src="propose", dst="gate"),
            Connection(src="gate", dst="merge"),
        ),
        inputs=(GOAL,),
        outputs=(MERGED,),
    )


def build_git_system(
    tmp_path: Path,
    journal: SqliteJournal,
    *,
    owner_id: str = "worker-one",
    propose: Any = propose_impl,
) -> tuple[Constructicon, GitWorld]:
    repo = tmp_path / "authority.git"
    if not repo.exists():
        seed_authority(tmp_path)
    world = git_world(
        journal=journal,
        repo_path=repo,
        workspaces_root=tmp_path / "workspaces",
        checks=FAST_CHECKS,
    )
    system = Constructicon(
        journal=journal,
        capabilities=world.capabilities,
        catalog=world.catalog,
        effects=world.effects,
        root_grants=WRITE_GRANTS,
        owner_id=owner_id,
        lease_ttl_s=LEASE_TTL_S,
    )
    for definition, impl in (
        atomic("git/propose", (GOAL,), (CANDIDATE,), propose),
        atomic("git/gate", (CANDIDATE,), (EVALUATION,), gate_impl),
        atomic("git/merge", (EVALUATION,), (MERGED,), merge_impl),
    ):
        version = system._register(definition, impl)
        system._promote_initial(component=definition.name, version=version)
    return system, world
