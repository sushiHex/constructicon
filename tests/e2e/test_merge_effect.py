"""merge_verified under attack and under crashes (M3 §4, §7).

Forgery never poisons an idempotency key (verification failures raise and
leave no receipt); crash recovery reconciles from the marker ref — exactly
one install ever, at every seam."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.effect import (
    AttestationDraft,
    CheckResult,
    EffectRequest,
    MergeSubject,
    idempotency_key,
)
from constructicon.core.errors import AdmissionError, ContractViolation
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import Digest, digest
from constructicon.core.ports import Port
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.substrate.effects.git import MergeVerifiedEffect
from constructicon.substrate.git.authority import GitAuthority, PreparedMerge
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import LEASE_TTL_S, FakeClock, InjectedCrash, atomic
from tests.gitworld import GOOD_FIX, build_git_system, build_graph, seed_authority
from tests.run_attestations import mint_run_attestation
from tests.run_worlds import sealed_test_manifest

GOAL_INPUT = {"goal": {"title": "add double()", "content": GOOD_FIX}}
MANIFEST_HASH = sealed_test_manifest().manifest_hash
PATH = ExecutionPath(scope=ScopePath(segments=("build", "merge")))


def prepared_world(
    tmp_path: Path, journal: SqliteJournal
) -> tuple[GitAuthority, MergeVerifiedEffect, MergeSubject, str]:
    repo = seed_authority(tmp_path)
    authority = GitAuthority(repo, tmp_path / "workspaces")
    workspace = authority.acquire_write(
        acquisition_id="acq-forge",
        target_ref="refs/heads/main",
        candidate_ref="refs/candidates/run-forge/acq-forge",
    )
    Path(workspace.path, "calc.py").write_text(GOOD_FIX)
    candidate = workspace.commit_all("candidate")
    prepared = authority.prepare_merge(candidate, "refs/heads/main")
    assert isinstance(prepared, PreparedMerge)
    subject = prepared.subject
    draft = AttestationDraft(
        action="merge",
        subject=subject,
        checks=(CheckResult(name="gate", status="passed", detail="", elapsed_s=0.0),),
        check_set_hash=digest("check-set", 1, {"t": 1}),
        manifest_hash=MANIFEST_HASH,
    )
    attestation = mint_run_attestation(journal, RunId("run-forge"), draft)
    effect = MergeVerifiedEffect(journal=journal, authority=authority)
    return authority, effect, subject, attestation.attestation_id


def request_for(
    subject: MergeSubject,
    attestation_id: str | None,
    *,
    manifest_hash: Digest = MANIFEST_HASH,
) -> EffectRequest:
    subject_dict = subject.model_dump(mode="json")
    return EffectRequest(
        run_id=RunId("run-forge"),
        manifest_hash=manifest_hash,
        path=PATH,
        kind="merge_verified",
        subject=subject_dict,
        idempotency_key=idempotency_key(
            manifest_hash, PATH, "merge_verified", subject_dict
        ),
        attestation_id=attestation_id,
    )


@pytest.mark.parametrize("operation", ["execute", "reconcile"])
async def test_the_forgery_matrix_leaves_no_receipt_and_moves_nothing(
    tmp_path: Path, journal: SqliteJournal, operation: str
) -> None:
    authority, effect, subject, attestation_id = prepared_world(tmp_path, journal)
    if operation == "reconcile":
        assert (await effect.execute(request_for(subject, attestation_id))).status == "committed"
    before = authority.resolve_ref("refs/heads/main")

    async def refused(request: EffectRequest, match: str) -> None:
        marker_before = authority.read_ref(authority.marker_ref(request.idempotency_key))
        with pytest.raises(AdmissionError, match=match):
            await getattr(effect, operation)(request)
        assert journal.receipt_for(request.idempotency_key) is None  # not poisoned
        assert authority.read_ref(authority.marker_ref(request.idempotency_key)) == marker_before
        assert authority.resolve_ref("refs/heads/main") == before

    # fabricated attestation id
    await refused(request_for(subject, "att-i-made-this-up"), "not journal-minted")
    # a failing attestation cannot authorize
    failing = mint_run_attestation(
        journal,
        RunId("run-forge"),
        AttestationDraft(
            action="merge",
            subject=subject,
            checks=(CheckResult(name="gate", status="failed", detail="", elapsed_s=0.0),),
            check_set_hash=digest("check-set", 1, {"t": 1}),
            manifest_hash=MANIFEST_HASH,
        )
    )
    await refused(
        request_for(subject, failing.attestation_id), "checks failing"
    )
    # subject mismatch, field by field
    for field, value in (
        ("candidate", str(subject.expected_base)),
        ("expected_base", str(subject.candidate)),
        ("merge_commit", str(subject.candidate)),
        ("tested_tree", str(subject.expected_base)),
        ("target_ref", "refs/heads/other"),
    ):
        mutated = subject.model_copy(update={field: value})
        await refused(
            request_for(mutated, attestation_id), "does not authorize this exact"
        )
    # world mismatch: an attestation from an unrelated manifest
    await refused(
        request_for(
            subject, attestation_id, manifest_hash=digest("manifest", 1, {"other": 1})
        ),
        "differs from the invoking manifest",
    )
    # wrong merge object: attested subject naming a commit whose parents differ
    doctored = subject.model_copy(update={"merge_commit": str(subject.candidate)})
    doctored_attestation = mint_run_attestation(
        journal,
        RunId("run-forge"),
        AttestationDraft(
            action="merge",
            subject=doctored,
            checks=(CheckResult(name="gate", status="passed", detail="", elapsed_s=0.0),),
            check_set_hash=digest("check-set", 1, {"t": 1}),
            manifest_hash=MANIFEST_HASH,
        )
    )
    await refused(
        request_for(doctored, doctored_attestation.attestation_id),
        "parents|tested tree",
    )
    # after all of that, the legitimate request still commits cleanly
    receipt = await effect.execute(request_for(subject, attestation_id))
    assert receipt.status == "committed"
    assert authority.resolve_ref("refs/heads/main") == subject.merge_commit


async def unproved_merge_impl(
    ctx: NodeContext, inputs: Mapping[str, Any]
) -> Mapping[str, Any]:
    receipt = await ctx.effect("merge_verified", inputs["subject"])
    return {"receipt": receipt.model_dump(mode="json")}


async def test_walker_refuses_unproved_reconciliation_of_an_installed_merge(
    tmp_path: Path, journal: SqliteJournal
) -> None:
    authority, effect, subject, attestation_id = prepared_world(tmp_path, journal)
    assert (await effect.execute(request_for(subject, attestation_id))).status == "committed"
    system = Constructicon(journal=journal, capabilities={}, catalog={},
                          effects={"merge_verified": effect}, owner_id="unproved-worker")
    incoming = Port(name="subject", type_id="test/MergeSubject", schema_hash="s1")
    outgoing = Port(name="receipt", type_id="test/Receipt", schema_hash="s1")
    definition, impl = atomic("test/unproved-merge", (incoming,), (outgoing,), unproved_merge_impl)
    version = system._register(definition, impl)
    system._promote_initial(component=definition.name, version=version)
    graph = Graph(name="unproved-merge", nodes=(
        GraphNode(id="merge", body=Ref(component=definition.name)),
    ), connections=(), inputs=(incoming,), outputs=(outgoing,))
    run_id = RunId("run-unproved-reconciliation")
    result = await system._start_direct(
        graph, {"subject": subject.model_dump(mode="json")}, run_id=run_id,
    )
    assert result.status is RunStatus.FAILED
    assert any("requires an attestation id" in failure for failure in result.failures.values())
    events = journal.events(run_id, limit=100)
    assert any(event.kind == "NodeFailed" for event in events)
    assert not any(event.kind in {"EffectCommitted", "EffectReconciled"} for event in events)
    manifest_hash = journal.run_manifest_hash(run_id)
    assert manifest_hash is not None
    path = ExecutionPath(scope=ScopePath(segments=(graph.name, "merge")))
    key = idempotency_key(manifest_hash, path, "merge_verified", subject.model_dump(mode="json"))
    assert journal.receipt_for(key) is None
    assert authority.read_ref(authority.marker_ref(key)) is None
    assert authority.resolve_ref(subject.target_ref) == subject.merge_commit


async def test_reconciliation_keeps_valid_install_proof_after_target_moves(
    tmp_path: Path, journal: SqliteJournal
) -> None:
    authority, effect, subject, attestation_id = prepared_world(tmp_path, journal)
    request = request_for(subject, attestation_id)
    assert await effect.reconcile(request) is None
    committed = await effect.execute(request)
    authority._run("update-ref", subject.target_ref, subject.expected_base)
    assert await effect.reconcile(request) == committed
    assert authority.resolve_ref(subject.target_ref) == subject.expected_base
    assert authority.read_ref(authority.marker_ref(request.idempotency_key)) == subject.merge_commit


@pytest.mark.parametrize("operation", ["execute", "reconcile", "simulate"])
async def test_mirrored_objects_never_authorize_another_repository(
    tmp_path, journal, operation,
):
    authority, _, subject, attestation = prepared_world(tmp_path, journal)
    mirror = tmp_path / "mirror.git"
    shutil.copytree(Path(authority.repository_id), mirror)
    other = GitAuthority(mirror, tmp_path / "mirror-workspaces")
    # All Git facts match: only the governing authority differs.
    assert other.tree_of(subject.merge_commit) == subject.tested_tree
    assert other.parents_of(subject.merge_commit) == (subject.expected_base, subject.candidate)
    effect = MergeVerifiedEffect(journal=journal, authority=other)
    request = request_for(subject, attestation)
    before = other.resolve_ref(subject.target_ref)
    with pytest.raises(ContractViolation, match="another Git authority"):
        await getattr(effect, operation)(request)
    assert other.resolve_ref(subject.target_ref) == before
    assert not other.reconcile_install(subject, request.idempotency_key)
    assert journal.receipt_for(request.idempotency_key) is None


@pytest.mark.parametrize(
    ("probe", "expected_event"),
    [
        # died after the prepared row committed, before the adapter executed:
        # reconcile finds nothing external -> execute exactly once
        ("effect.after_prepared_commit", "EffectCommitted"),
        # died after the git transaction, before the SQLite receipt: the
        # marker ref is the durable proof -> reconcile, never re-install
        ("effect.before_receipt_txn", "EffectReconciled"),
    ],
)
async def test_crash_seams_install_exactly_once(
    tmp_path: Path,
    journal: SqliteJournal,
    clock: FakeClock,
    probe: str,
    expected_event: str,
) -> None:
    system, world = build_git_system(tmp_path, journal)
    authority = world.authority
    run_id = RunId(f"run-{probe.replace('.', '-')}")

    def armed(name: str) -> None:
        if name == probe:
            raise InjectedCrash(name)

    journal.fault_probe = armed
    with pytest.raises(InjectedCrash):
        await system._start_direct(build_graph(), GOAL_INPUT, run_id=run_id)
    journal.fault_probe = lambda name: None
    clock.advance(LEASE_TTL_S + 1)

    result = await system._resume_direct(run_id)
    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["merged"]["status"] == "committed"
    kinds = [event.kind for event in system._journal.events(run_id, limit=200)]
    assert expected_event in kinds

    # exactly one install ever: main is one merge commit above the seed base
    installed = authority.resolve_ref("refs/heads/main")
    assert str(installed) == result.outputs["merged"]["observed"]["merge_commit"]
    parents = authority.parents_of(installed)
    assert len(parents) == 2
    grandparents = authority.parents_of(parents[0])
    assert grandparents == ()  # the seed commit directly — no second merge


async def test_stale_owner_workspace_is_never_the_new_owners(
    tmp_path: Path, journal: SqliteJournal, clock: FakeClock
) -> None:
    """Acquisition epochs fence the filesystem: the reclaimed run acquires a
    fresh physical path, and the crashed epoch's leftovers are reaped."""
    system, _world = build_git_system(tmp_path, journal)
    run_id = RunId("run-fenced-ws")
    staging_root = tmp_path / "workspaces" / "staging"

    seen_dirs: list[str] = []

    def armed(name: str) -> None:
        if name == "lease.after_record_commit" and not seen_dirs:
            seen_dirs.extend(p.name for p in staging_root.iterdir())
            raise InjectedCrash(name)

    journal.fault_probe = armed
    with pytest.raises(InjectedCrash):
        await system._start_direct(build_graph(), GOAL_INPUT, run_id=run_id)
    journal.fault_probe = lambda name: None
    assert seen_dirs  # the crashed epoch left its staging repo behind
    clock.advance(LEASE_TTL_S + 1)

    result = await system._resume_direct(run_id)
    assert result.status is RunStatus.SUCCEEDED
    rows = system._journal.capability_leases(run_id)
    epochs = {row.acquisition_epoch for row in rows}
    assert len(epochs) == 2  # one acquisition per ownership epoch
    stale = [row for row in rows if row.acquisition_epoch == min(epochs)]
    assert all(
        row.state == "closed" and row.disposition == "discarded" for row in stale
    )
    # nothing physical survived either epoch
    assert not staging_root.exists() or not any(staging_root.iterdir())
