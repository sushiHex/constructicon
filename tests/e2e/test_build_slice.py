"""The M3 acceptance slice: Stage -> Import -> Prepare -> Verify -> Attest ->
Transact -> Receipt, through the ordinary graph machinery with real Ruff and
real Pytest as the gates."""

from __future__ import annotations

from pathlib import Path

from constructicon.api.system import Constructicon, GitWorld
from constructicon.core.address import RunId
from constructicon.core.run import RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.gitworld import (
    BROKEN_FIX,
    GOOD_FIX,
    build_git_system,
    build_graph,
    failing_propose_impl,
    push_to_main,
)

GOAL_INPUT = {"goal": {"title": "add double()", "content": GOOD_FIX}}


def git_system(
    tmp_path: Path, journal: SqliteJournal, **kwargs: object
) -> tuple[Constructicon, GitWorld]:
    return build_git_system(tmp_path, journal, **kwargs)  # type: ignore[arg-type]


async def test_the_gated_merge_slice(
    tmp_path: Path, journal: SqliteJournal
) -> None:
    system, world = git_system(tmp_path, journal)
    authority = world.authority
    base_before = authority.resolve_ref("refs/heads/main")

    result = await system.start(build_graph(), GOAL_INPUT, run_id=RunId("run-slice"))

    assert result.status is RunStatus.SUCCEEDED
    merged = result.outputs["merged"]
    assert merged["status"] == "committed"
    installed = authority.resolve_ref("refs/heads/main")
    assert str(installed) == merged["observed"]["merge_commit"]
    # the exact commit: parents are (old base, candidate); tree is the tested tree
    parents = authority.parents_of(installed)
    assert parents[0] == base_before
    attestation_events = [
        event.kind for event in system.journal.events(RunId("run-slice"), limit=200)
    ]
    assert "EffectCommitted" in attestation_events
    assert "LeaseAcquired" in attestation_events
    # every acquisition closed cleanly
    leases = system.journal.capability_leases(RunId("run-slice"))
    assert leases and all(lease.state == "closed" for lease in leases)
    assert {lease.disposition for lease in leases} == {"released"}
    # the staging workspaces are gone; only durable git state remains
    staging_root = tmp_path / "workspaces" / "staging"
    assert not staging_root.exists() or not any(staging_root.iterdir())


async def test_failing_gates_refuse_the_merge_via_evidence(
    tmp_path: Path, journal: SqliteJournal
) -> None:
    system, world = git_system(tmp_path, journal)
    authority = world.authority
    before = authority.resolve_ref("refs/heads/main")

    result = await system.start(
        build_graph(),
        {"goal": {"title": "break the tests", "content": BROKEN_FIX}},
        run_id=RunId("run-red"),
    )
    assert result.status is RunStatus.FAILED
    assert any("checks failing" in error for error in result.failures.values())
    assert authority.resolve_ref("refs/heads/main") == before  # nothing installed
    # the failing attestation exists as evidence; it authorizes nothing
    kinds = [event.kind for event in system.journal.events(RunId("run-red"), limit=200)]
    assert "NodeFailed" in kinds and "EffectCommitted" not in kinds


async def test_merge_conflict_flows_as_data(
    tmp_path: Path, journal: SqliteJournal
) -> None:
    system, world = git_system(tmp_path, journal)
    authority = world.authority

    def probe(name: str) -> None:
        # after propose's completion committed, move main so the merge conflicts
        if name == "completion.after_commit" and not getattr(probe, "fired", False):
            probe.fired = True  # type: ignore[attr-defined]
            push_to_main(
                Path(authority.repository_id),
                {"calc.py": "def add(a, b):\n    return b + a\n"},
                "collide",
            )

    journal.fault_probe = probe
    result = await system.start(build_graph(), GOAL_INPUT, run_id=RunId("run-conflict"))
    journal.fault_probe = lambda name: None
    assert result.status is RunStatus.FAILED
    assert any("no merge subject" in error for error in result.failures.values())


async def test_base_moved_after_gates_is_a_truthful_rejection(
    tmp_path: Path, journal: SqliteJournal
) -> None:
    """The gate passes on base B0; before the merge node runs, main moves to
    B1 (a non-conflicting file). The effect refuses with a rejected receipt —
    data the loop can revalidate on — and installs nothing."""
    system, world = git_system(tmp_path, journal)
    authority = world.authority
    completions = 0

    def probe(name: str) -> None:
        nonlocal completions
        if name == "completion.after_commit":
            completions += 1
            if completions == 2:  # propose done, gate done -> move the base
                push_to_main(
                    Path(authority.repository_id), {"extra.py": "X = 1\n"}, "base moves"
                )

    journal.fault_probe = probe
    result = await system.start(build_graph(), GOAL_INPUT, run_id=RunId("run-moved"))
    journal.fault_probe = lambda name: None

    assert result.status is RunStatus.SUCCEEDED  # rejection is data, not a crash
    merged = result.outputs["merged"]
    assert merged["status"] == "rejected"
    observed = merged["observed"]
    assert observed["expected_base"] != observed["found_base"]
    kinds = [event.kind for event in system.journal.events(RunId("run-moved"), limit=200)]
    assert "EffectRejected" in kinds
    # nothing installed: main is the moved base, not a merge commit
    assert str(authority.resolve_ref("refs/heads/main")) == observed["found_base"]


async def test_rejected_is_final_and_reproduce_never_reinstalls(
    tmp_path: Path, journal: SqliteJournal
) -> None:
    system, world = git_system(tmp_path, journal)
    authority = world.authority

    first = await system.start(build_graph(), GOAL_INPUT, run_id=RunId("run-one"))
    assert first.outputs["merged"]["status"] == "committed"
    installed = authority.resolve_ref("refs/heads/main")

    # reproduce re-walks against the moved world: the candidate is already
    # reachable from the target, so it reports already-integrated and never
    # double-installs (same-subject dedup is pinned in the crash lanes)
    reproduced = await system.reproduce(RunId("run-one"), new_run_id=RunId("run-two"))
    assert reproduced.status is RunStatus.SUCCEEDED
    assert reproduced.outputs["merged"]["status"] == "already_integrated"
    assert authority.resolve_ref("refs/heads/main") == installed
    kinds = [event.kind for event in system.journal.events(RunId("run-two"), limit=200)]
    assert "EffectCommitted" not in kinds and "EffectRejected" not in kinds


async def test_discard_on_failure_removes_staging_and_candidate_ref(
    tmp_path: Path, journal: SqliteJournal
) -> None:
    system, world = git_system(tmp_path, journal, propose=failing_propose_impl)
    authority = world.authority

    result = await system.start(
        build_graph(),
        {"goal": {"title": "doomed", "content": GOOD_FIX}},
        run_id=RunId("run-doomed"),
    )
    assert result.status is RunStatus.FAILED
    assert "proposer died" in str(result.failures)
    leases = system.journal.capability_leases(RunId("run-doomed"))
    workspace_leases = [lease for lease in leases if lease.binding_id == "workspace"]
    assert workspace_leases and all(
        lease.state == "closed" and lease.disposition == "discarded"
        for lease in workspace_leases
    )
    # the uncheckpointed candidate is gone: no candidate refs survive
    refs = authority._run("for-each-ref", "refs/candidates/").stdout.strip()
    assert refs == ""
    staging_root = tmp_path / "workspaces" / "staging"
    assert not staging_root.exists() or not any(staging_root.iterdir())
