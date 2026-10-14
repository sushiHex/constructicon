"""Phase separation, real Linux checks, and owned gate failure boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import threading
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.address import GitSha
from constructicon.core.errors import Cancelled, ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import digest
from constructicon.core.run import OwnershipLost
from constructicon.substrate.executors.linux import LinuxLauncher, ProcessLimits, ProcessResult
from constructicon.substrate.gates.contained import ContainedGateRunner
from constructicon.substrate.gates.runner import CheckSpec
from constructicon.substrate.git.authority import GitAuthority
from tests.gitworld import push_to_main, seed_authority
from tests.substrate.test_contained_workspace import context, stale_row
from tests.substrate.test_linux_containment import launcher as launcher

LINUX = pytest.mark.skipif(sys.platform != "linux", reason="physical acquisition guard needs Linux")
PYTHON = "/usr/bin/python3"
PASS = CheckSpec("python", (PYTHON, "-c", "print('passed')"), 20)


class ObservedLauncher:
    """Only a call/phase double. Native cases explicitly replace it."""

    revision = digest("fake-launch", 1, "gates")
    limits = ProcessLimits()

    def __init__(self):
        self.calls = []
        self.result = ProcessResult(0, b"python fixture\n", b"", 0, payload_returncode=0)

    async def run(self, command, **kwargs):
        self.calls.append((command, kwargs))
        assert kwargs["guard_fds"]
        for fd in kwargs["guard_fds"]:
            os.fstat(fd)
        return self.result


class RecordingJournal:
    """Attestation timing double; public lifecycle tests use real SQLite."""

    def __init__(self):
        self.drafts = []

    def mint_attestation(self, lease, draft):
        self.drafts.append((lease, draft))
        return SimpleNamespace(attestation_id="test-minted-authority")


def unqualified(tmp_path, launch=None, checks=(PASS,), journal=None):
    repo = seed_authority(tmp_path)
    authority = GitAuthority(repo, tmp_path / "legacy")
    return ContainedGateRunner(
        journal=journal or RecordingJournal(), authority=authority, root=tmp_path / "gates",
        target_ref="refs/heads/main", provider_id="test-contained-gates",
        launcher=launch or ObservedLauncher(), checks=checks,
    )


async def qualify(runner):
    return await ContainedGateRunner.create(
        journal=runner._journal, authority=runner.authority, root=runner.root,
        target_ref=runner.target_ref, provider_id=runner.provider_id,
        launcher=runner.launcher, checks=runner.checks,
    )


def gate_context(runner, *, epoch=1, control=lambda: None):
    ctx = context(epoch=epoch, binding="gates")
    return replace(ctx, binding=ctx.binding.model_copy(update={"revision": runner.revision}),
                   check_control=control)


def candidate(runner, files=None):
    old = runner.authority.resolve_ref(runner.target_ref)
    new = push_to_main(Path(runner.authority.repository_id), files or {"extra": "candidate"}, "new")
    runner.authority._run("update-ref", runner.target_ref, old)
    return new


async def started(runner):
    ctx = gate_context(runner)
    acquired = await runner.acquire(ctx)
    await acquired.materialize()
    return acquired


async def test_identification_is_mount_free_and_inert_even_without_a_target(tmp_path):
    runner = unqualified(tmp_path)
    runner.authority._run("update-ref", "-d", runner.target_ref)
    with pytest.raises(ContractViolation, match="not identified"):
        _ = runner.revision
    runner = await qualify(runner)
    assert runner.revision and not runner.root.exists()
    assert len(runner.launcher.calls) == 1
    command, call = runner.launcher.calls[0]
    assert command[-1] == "--version"
    assert call["workspace"] is None and call["posture"] is Posture.READ
    acquired = await runner.acquire(gate_context(runner))
    assert not runner.root.exists()
    assert "base" not in acquired.resource_ref and "candidate" not in acquired.resource_ref
    await runner.close(acquired, "discard")
    assert not runner.root.exists()
    assert not runner.closure.is_closed(acquired.resource.paths)
    with pytest.raises(ContractViolation, match="inert open"):
        await acquired.materialize()


@pytest.mark.parametrize("failure", ["exit", "timeout", "bound", "drift"])
async def test_failed_runtime_identification_never_qualifies(tmp_path, failure):
    runner = unqualified(tmp_path)
    if failure == "drift":
        original = runner.launcher.run

        async def changed(*args, **kwargs):
            result = await original(*args, **kwargs)
            runner.launcher.revision = digest("changed", 1, True)
            return result

        runner.launcher.run = changed
    else:
        runner.launcher.result = ProcessResult(
            1 if failure == "exit" else 0, b"", b"", 0,
            timed_out=failure == "timeout", bound_exceeded="stdout" if failure == "bound" else None,
        )
    with pytest.raises(ContractViolation, match="identification"):
        await qualify(runner)
    with pytest.raises(ContractViolation, match="not identified"):
        _ = runner.check_set_hash
    assert not runner.root.exists()


@pytest.mark.parametrize("drift", ["launcher", "checks", "target"])
async def test_live_revision_is_not_a_cached_label(tmp_path, drift):
    runner = await qualify(unqualified(tmp_path))
    ctx = gate_context(runner)
    if drift == "launcher":
        runner.launcher.revision = digest("new", 1, "runtime")
    elif drift == "checks":
        runner.checks = (replace(PASS, timeout_s=4),)
    else:
        runner.target_ref = "refs/heads/other"
    with pytest.raises(ContractViolation, match=r"drifted|sealed revision"):
        await runner.acquire(ctx)
    assert not runner.root.exists()


@pytest.mark.parametrize("bad", [(), (PASS, PASS), (replace(PASS, timeout_s=0),),
                                 (replace(PASS, argv=("python",)),)])
def test_invalid_check_configuration_is_refused(tmp_path, bad):
    with pytest.raises(ContractViolation):
        unqualified(tmp_path, checks=bad)


async def test_relative_authorities_cannot_alias_across_service_working_directories(
    tmp_path, monkeypatch,
):
    identifiers = []
    for name in ("service-a", "service-b"):
        service = tmp_path / name
        runner = unqualified(service)
        with monkeypatch.context() as local:
            local.chdir(service)
            relative = GitAuthority(Path("authority.git"), service / "relative-legacy")
            identifiers.append(relative.repository_id)
            # Legacy authority still accepts this locator; only the new
            # contained assembly refuses the ambiguous recovery route.
            assert relative.resolve_ref(runner.target_ref)
            with pytest.raises(ContractViolation, match="canonical absolute Git authority"):
                await ContainedGateRunner.create(
                    journal=runner._journal, authority=relative, root=runner.root,
                    target_ref=runner.target_ref, provider_id=runner.provider_id,
                    launcher=runner.launcher, checks=runner.checks,
                )
            assert not runner.root.exists() and not runner.launcher.calls
    assert identifiers == ["authority.git", "authority.git"]


@LINUX
async def test_absolute_repository_alias_is_not_a_canonical_recovery_route(tmp_path):
    runner = unqualified(tmp_path)
    alias = tmp_path / "repo-alias"
    alias.symlink_to(Path(runner.authority.repository_id), target_is_directory=True)
    runner.authority = GitAuthority(alias, tmp_path / "alias-legacy")
    with pytest.raises(ContractViolation, match="canonical absolute Git authority"):
        await qualify(runner)
    assert not runner.root.exists() and not runner.launcher.calls


@LINUX
@pytest.mark.parametrize("materialize", [False, True])
async def test_recovery_before_verify_has_no_subject_or_current_base_dependency(
    tmp_path, materialize,
):
    runner = await qualify(unqualified(tmp_path))
    ctx = gate_context(runner)
    acquired = await runner.acquire(ctx)
    reference, sentinel = acquired.resource_ref, runner.closure.sentinel
    if materialize:
        await acquired.materialize()
    runner.authority._run("update-ref", "-d", runner.target_ref)
    await runner.reconcile(gate_context(runner, epoch=2), (stale_row(acquired, ctx),))
    assert runner.closure.is_closed(acquired.resource.paths)
    assert runner.closure.sentinel == sentinel and acquired.resource_ref == reference
    assert not acquired.resource.paths.payload.exists()
    with pytest.raises(ContractViolation, match=r"closed|materialized"):
        await acquired.resource.verify("a" * 40)


@LINUX
@pytest.mark.parametrize("route", ["root", "repository"])
async def test_recovery_never_reports_the_wrong_storage_root_reaped(tmp_path, route, monkeypatch):
    from constructicon.substrate.gates import contained
    from constructicon.substrate.git.acquisition import acquisition_guard

    runner = await qualify(unqualified(tmp_path))
    acquired = await started(runner)
    ctx = acquired.resource.context
    old = acquired.resource.paths
    old.payload.mkdir(parents=True)
    sentinel = old.payload / "owned"
    sentinel.write_bytes(b"still owned by the old guard")
    authority, root = runner.authority, runner.root
    if route == "root":
        root = tmp_path / "different-root"
    else:
        authority = GitAuthority(seed_authority(tmp_path / "other"), tmp_path / "other-legacy")
    successor = await ContainedGateRunner.create(
        journal=runner._journal, authority=authority, root=root,
        target_ref=runner.target_ref, provider_id=runner.provider_id,
        launcher=runner.launcher, checks=runner.checks,
    )
    assert successor.revision == runner.revision  # Host locators never enter this digest.

    async def forbidden_disposal(*args, **kwargs):
        pytest.fail("a foreign recovery route reached physical disposal")

    async with acquisition_guard(old):
        with monkeypatch.context() as refusal:
            # Observe the forbidden boundary directly: an omitted repository
            # fence would otherwise wait forever on the guard held above.
            refusal.setattr(contained, "dispose_acquisition", forbidden_disposal)
            with pytest.raises(ContractViolation, match="recovery reference"):
                await successor.reconcile(
                    gate_context(successor, epoch=2), (stale_row(acquired, ctx),),
                )
            assert sentinel.read_bytes() == b"still owned by the old guard"
            assert not runner.closure.is_closed(old) and not successor.closure.is_closed(old)
            if route == "root":
                assert not successor.root.exists()
    # The genuine successor uses the recorded root and the same guard.
    same = await qualify(runner)
    result = await same.reconcile(gate_context(same, epoch=2), (stale_row(acquired, ctx),))
    assert result.reaped == (acquired.resource_ref,)
    assert runner.closure.is_closed(old) and not old.payload.exists()


@LINUX
async def test_recovery_validates_the_whole_batch_before_closing_any_row(tmp_path):
    import json

    runner = await qualify(unqualified(tmp_path))
    first = await runner.acquire(gate_context(runner))
    second = await runner.acquire(gate_context(runner, epoch=2))
    raw = json.loads(second.resource_ref)
    raw["storage_root"] = str(tmp_path / "foreign")
    foreign = stale_row(
        replace(second, resource_ref=json.dumps(raw)), gate_context(runner, epoch=2),
    )
    with pytest.raises(ContractViolation, match="recovery reference"):
        await runner.reconcile(gate_context(runner, epoch=3), (
            stale_row(first, gate_context(runner)), foreign,
        ))
    assert not runner.closure.is_closed(first.resource.paths)
    assert not runner.closure.is_closed(second.resource.paths)
    assert not runner.root.exists()


async def test_native_checks_use_exact_prepared_snapshot_and_fixed_runtime(launcher, tmp_path):
    runner = await qualify(unqualified(tmp_path, launcher))
    sha = candidate(runner)
    revision = runner.revision
    acquired = await started(runner)
    reference, sentinel = acquired.resource_ref, runner.closure.sentinel
    new_base = push_to_main(Path(runner.authority.repository_id), {"base-new": "new"}, "base moves")
    result = await acquired.resource.verify(sha)
    assert result.ok
    assert result.subject == runner.authority.prepare_merge(sha, runner.target_ref).subject
    assert result.subject.expected_base == new_base
    assert result.subject.tested_tree == runner.authority.tree_of(result.subject.merge_commit)
    assert runner.revision == revision and acquired.resource_ref == reference
    assert runner.closure.sentinel == sentinel
    assert not acquired.resource.paths.payload.exists()
    # A second candidate is not a second installed runtime or check-set identity.
    other = candidate(runner, {"other": "second"})
    assert (await acquired.resource.verify(other)).ok
    assert runner.revision == revision
    assert len(runner._journal.drafts) == 2
    await runner.close(acquired, "release")
    assert runner.closure.is_closed(acquired.resource.paths)


def maintenance_commits(runner, target_source, vectors, *, extra=False):
    """Git plumbing builds the fixed nested paths without executing repository code."""
    authority = runner.authority

    def blob(value):
        return authority._run("hash-object", "-w", "--stdin",
                              input_text=value.decode("utf-8")).stdout.strip()

    def tree(entries):
        return authority._run("mktree", input_text=entries).stdout.strip()

    old = authority.resolve_ref(runner.target_ref)
    original = authority._run("ls-tree", old).stdout
    scripts = tree(f"100644 blob {blob(target_source)}\tregen_plan_manifest.py\n")
    baseline_entries = original + f"040000 tree {scripts}\tscripts\n"
    baseline_tree = tree(baseline_entries)
    base = GitSha(authority._run("commit-tree", baseline_tree, "-p", old,
                                 input_text="maintenance base\n").stdout.strip())
    authority._run("update-ref", runner.target_ref, base, old)
    vectors_tree = tree(f"100644 blob {blob(vectors)}\tplan_manifest.json\n")
    tests_tree = tree(f"040000 tree {vectors_tree}\tvectors\n")
    candidate_entries = baseline_entries + f"040000 tree {tests_tree}\ttests\n"
    if extra:
        candidate_entries += f"100644 blob {blob(b'unrelated change')}\tunrelated.py\n"
    candidate_tree = tree(candidate_entries)
    proposed = GitSha(authority._run("commit-tree", candidate_tree, "-p", base,
                                     input_text="data vector contribution\n").stdout.strip())
    return base, proposed


@pytest.mark.parametrize("case", ["accept", "extra", "weak"])
async def test_native_maintenance_recipe_runs_its_fixed_exam_and_refuses_scope(
    launcher, tmp_path, case,
):
    from constructicon.api.plan_manifest_application import maintenance_checks
    from constructicon.substrate.gates.maintenance import parse_vectors, render_unittest
    from tests.substrate.test_maintenance_vectors import (
        SOURCE,
        entries,
        path,
        permitting_vectors,
        wire,
    )

    vectors = permitting_vectors()
    if case == "weak":
        vectors = wire([path("a.md"), path(".md"), entries(b"a" * 64 + b"  a.md\n"),
                        entries(b"bad"), entries(b"\xff")])
    journal = RecordingJournal()
    runner = unqualified(tmp_path, launcher, journal=journal)
    base, proposed = maintenance_commits(runner, SOURCE, vectors, extra=case == "extra")
    inventory = runner.authority._run("ls-tree", "-r", "-z", base).stdout.encode()
    pin = hashlib.sha256(SOURCE).hexdigest()
    runner.checks = maintenance_checks(SOURCE, pin, inventory,
                                       runner.authority.environment.object_format)
    runner = await qualify(runner)
    acquired = await started(runner)
    try:
        result = await acquired.resource.verify(proposed)
        assert result.subject is not None
        assert result.subject.candidate == proposed and result.subject.expected_base == base
        assert result.subject.tested_tree == runner.authority.tree_of(proposed)
        assert len(result.checks) == 1
        assert result.checks[0].name == "plan-manifest-trusted-vectors"
        assert result.checks[0].status == ("passed" if case == "accept" else "failed")
        assert result.ok is (case == "accept")
        assert len(journal.drafts) == 1
        lease, draft = journal.drafts[0]
        assert lease == acquired.resource.context.run_lease
        assert draft.subject == result.subject and draft.checks == result.checks
        assert draft.check_set_hash == runner.check_set_hash
        assert result.attestation_id == "test-minted-authority"
        if case == "accept":
            # These facts came from the real contained driver, rather than inferred exit success.
            report = json.loads(result.checks[0].detail)
            assert report["passed"] is True
            assert report["baseline"] == {"tests_run": 24, "failures": 0, "errors": 0, "skips": 0}
            assert tuple(mutant["name"] for mutant in report["mutants"]) == (
                "path_absolute", "path_noncanonical", "path_parent", "path_unsafe_characters",
                "path_any_suffix", "digest_relaxed", "entries_duplicate_overwrite",
                "entries_conflict_skip",
            )
            for mutant in report["mutants"]:
                assert mutant["distinguished"] is True
                assert mutant["counts"]["tests_run"] == 24
                assert mutant["counts"]["failures"] > 0
                assert mutant["counts"]["errors"] == mutant["counts"]["skips"] == 0
            assert report["input_sha256"] == hashlib.sha256(vectors).hexdigest()
            assert report["target_sha256"] == pin
            rendered = render_unittest(parse_vectors(vectors), SOURCE, trusted_target_sha256=pin)
            assert report["render_sha256"] == hashlib.sha256(rendered).hexdigest()
        assert not acquired.resource.paths.payload.exists()
        assert runner.authority.resolve_ref(runner.target_ref) == base
    finally:
        await runner.close(acquired, "discard")
    assert runner.closure.is_closed(acquired.resource.paths)
    assert not acquired.resource.paths.payload.exists()
    assert runner.authority.resolve_ref(runner.target_ref) == base


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
async def test_native_output_overflow_cannot_pass(launcher, tmp_path, stream):
    launch = replace(launcher, limits=replace(launcher.limits, stdout_bytes=2048))
    script = f"import sys; sys.{stream}.write('x'*100000)"
    specs = (CheckSpec("noisy", (PYTHON, "-c", script)),)
    runner = await qualify(unqualified(tmp_path, launch, specs))
    acquired = await started(runner)
    result = await acquired.resource.verify(candidate(runner))
    assert not result.ok and result.checks[0].status == "infrastructure_error"
    assert "output bound" in result.checks[0].detail
    assert not acquired.resource.paths.payload.exists()
    await runner.close(acquired, "discard")


@pytest.mark.parametrize("case", ["red", "timeout", "missing", "exit125", "exit126", "exit127"])
async def test_native_nonpassing_checks_remain_typed_data(launcher, tmp_path, case):
    runner = unqualified(tmp_path, launcher)
    if case == "red" or case.startswith("exit"):
        code = int(case.removeprefix("exit")) if case.startswith("exit") else 2
        runner.checks = (CheckSpec("red", (PYTHON, "-c", f"raise SystemExit({code})")),)
    elif case == "timeout":
        runner.checks = (CheckSpec("hang", (PYTHON, "-c", "import time; time.sleep(60)"), 1),)
    else:
        # The interpreter exists at assembly; candidate script absence is a check failure.
        runner.checks = (CheckSpec("missing", (PYTHON, "/workspace/missing.py")),)
    runner = await qualify(runner)
    acquired = await started(runner)
    result = await acquired.resource.verify(candidate(runner))
    assert not result.ok
    assert result.checks[0].status == ("timeout" if case == "timeout" else "failed")
    assert not acquired.resource.paths.payload.exists()
    await runner.close(acquired, "discard")


@pytest.mark.parametrize("report", [None, 1])
async def test_missing_or_contradictory_private_exit_is_not_a_pass(tmp_path, report):
    runner = await qualify(unqualified(tmp_path))
    runner.launcher.result = ProcessResult(0, b"passed", b"", 0, payload_returncode=report)
    with open(__file__, "rb") as guard:
        result = await runner._check(PASS, tmp_path, guard.fileno())
    assert result.status == "infrastructure_error" and not result.ok


async def test_hostile_repository_check_is_physically_confined(launcher, tmp_path, monkeypatch):
    sentinel = tmp_path / "host-secret"
    sentinel.write_text("credential-sentinel")
    monkeypatch.setenv("GATE_SECRET", "credential-sentinel")
    program = f"""
import os, socket, sys
from pathlib import Path
assert 'GATE_SECRET' not in os.environ
assert not Path({str(sentinel)!r}).exists()
assert not Path({str(tmp_path / 'authority.git')!r}).exists()
assert not Path({str(tmp_path / 'gates')!r}).exists()
assert not Path('/sys').exists()
for path in ('/workspace/new-file', {str(sentinel)!r}):
    try:
        Path(path).write_text('escaped')
    except OSError:
        pass
    else:
        raise AssertionError('host or snapshot write succeeded')
sock = socket.socket()
sock.settimeout(0.1)
assert sock.connect_ex(('1.1.1.1', 443)) != 0
sock.close()
pid = os.fork()
if pid == 0:
    os.setsid()
    import time
    time.sleep(120)
else:
    print('confined', flush=True)
"""
    runner = await qualify(unqualified(tmp_path, launcher, (
        CheckSpec("hostile", (PYTHON, "/workspace/hostile.py"), 15),
    )))
    acquired = await started(runner)
    result = await acquired.resource.verify(candidate(runner, {"hostile.py": program}))
    assert result.ok, result
    assert "confined" in result.checks[0].detail
    assert sentinel.read_text() == "credential-sentinel"
    assert not acquired.resource.paths.payload.exists()
    await runner.close(acquired, "discard")


@LINUX
@pytest.mark.parametrize("loss", [Cancelled, OwnershipLost, asyncio.CancelledError])
async def test_control_loss_quiesces_preparation_without_minting(tmp_path, monkeypatch, loss):
    runner = await qualify(unqualified(tmp_path))
    acquired = await started(runner)
    sha = candidate(runner)
    entered, released = threading.Event(), threading.Event()
    original = runner.authority.prepare_merge

    def prepare(*args):
        entered.set()
        assert released.wait(5)
        return original(*args)

    monkeypatch.setattr(runner.authority, "prepare_merge", prepare)
    state = [False]

    def control():
        if state[0]:
            raise loss("lost")

    # The handle is immutable; the originally supplied callback can observe control.
    acquired = await runner.acquire(gate_context(runner, control=control))
    await acquired.materialize()
    task = asyncio.create_task(acquired.resource.verify(sha))
    try:
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(0.01)
        state[0] = True
        # Wait for the gate's control observer to cancel its owned preparation task.
        await asyncio.sleep(0.1)
        assert not task.done()  # cancellation joins the still-running trusted worker
    finally:
        released.set()
    with pytest.raises(loss):
        await task
    assert not runner._journal.drafts and not acquired.resource.paths.payload.exists()
    await runner.close(acquired, "discard")


@LINUX
async def test_integrity_failure_is_checked_after_launch_and_before_mint(tmp_path):
    runner = await qualify(unqualified(tmp_path))
    original = runner.launcher.run

    async def mutate(*args, **kwargs):
        result = await original(*args, **kwargs)
        (kwargs["workspace"] / "extra").write_text("changed by test double")
        return result

    runner.launcher.run = mutate
    acquired = await started(runner)
    result = await acquired.resource.verify(candidate(runner))
    assert not result.ok and result.checks[-1].name == "snapshot-integrity"
    assert not acquired.resource.paths.payload.exists()
    await runner.close(acquired, "discard")


@LINUX
@pytest.mark.parametrize("failure", ["launch", "cleanup"])
async def test_teardown_failures_never_mint(tmp_path, monkeypatch, failure):
    runner = await qualify(unqualified(tmp_path))
    acquired = await started(runner)
    sha = candidate(runner)

    if failure == "launch":
        async def fail(*args, **kwargs):
            raise ContractViolation("teardown failed")

        monkeypatch.setattr(runner.launcher, "run", fail)
    else:
        def fail(*args, **kwargs):
            raise OSError("cleanup failed")

        monkeypatch.setattr("constructicon.substrate.gates.contained.shutil.rmtree", fail)
    with pytest.raises((ContractViolation, OSError), match="failed"):
        await acquired.resource.verify(sha)
    assert not runner._journal.drafts
    monkeypatch.undo()
    await runner.close(acquired, "discard")


@LINUX
@pytest.mark.parametrize("attribute", ["export-ignore", "export-subst"])
async def test_lossy_archive_cannot_claim_the_original_tree(tmp_path, attribute):
    runner = await qualify(unqualified(tmp_path))
    acquired = await started(runner)
    sha = candidate(runner, {
        ".gitattributes": f"extra {attribute}\n", "extra": "$Format:%H$\n",
    })
    with pytest.raises(ContractViolation, match="exact prepared Git tree"):
        await acquired.resource.verify(sha)
    assert not runner._journal.drafts
    assert not acquired.resource.paths.payload.exists()
    # No candidate-executing call: the only launch was the mount-free probe.
    assert all(call[1]["workspace"] is None for call in runner.launcher.calls)
    await runner.close(acquired, "discard")


@LINUX
async def test_explicit_control_check_immediately_before_mint_is_load_bearing(
    tmp_path, monkeypatch,
):
    runner = await qualify(unqualified(tmp_path))
    calls = []
    lost = [False]

    def control():
        calls.append(lost[0])
        if lost[0]:
            raise OwnershipLost("before mint")

    acquired = await runner.acquire(gate_context(runner, control=control))
    await acquired.materialize()
    original = runner._require_open

    async def last_check(handle):
        await original(handle)
        if any(kwargs["workspace"] is not None for _, kwargs in runner.launcher.calls):
            lost[0] = True

    monkeypatch.setattr(runner, "_require_open", last_check)
    with pytest.raises(OwnershipLost):
        await runner._verify(acquired.resource, candidate(runner))
    assert True in calls and not runner._journal.drafts
    await runner.close(acquired, "discard")


@LINUX
async def test_closed_marker_prevents_late_verify_even_on_a_ready_local_handle(tmp_path):
    runner = await qualify(unqualified(tmp_path))
    acquired = await started(runner)
    runner.closure.commit(acquired.resource.paths)
    with pytest.raises(ContractViolation, match="permanently closed"):
        await acquired.resource.verify(candidate(runner))
    assert not runner._journal.drafts and not acquired.resource.paths.payload.exists()
    await runner.close(acquired, "discard")


@LINUX
async def test_local_close_observed_at_mint_boundary_prevents_authority(tmp_path, monkeypatch):
    runner = await qualify(unqualified(tmp_path))
    acquired = await started(runner)
    original = runner._require_open

    async def close_after_last_open(handle):
        await original(handle)
        if any(kwargs["workspace"] is not None for _, kwargs in runner.launcher.calls):
            # Model close() entering while the joined identity worker is pending.
            handle._phase.closed = True

    monkeypatch.setattr(runner, "_require_open", close_after_last_open)
    with pytest.raises(ContractViolation, match="locally closed"):
        await runner._verify(acquired.resource, candidate(runner))
    assert not runner._journal.drafts and not acquired.resource.paths.payload.exists()
    await runner.close(acquired, "discard")


@pytest.mark.parametrize("change", ["kind", "revision", "leased", "journal", "absent"])
async def test_contained_gate_assembly_requires_exact_facts(tmp_path, change):
    from constructicon.api.system import Constructicon
    from constructicon.runtime.registry import CapabilityDescriptor
    from constructicon.substrate.journal.sqlite import SqliteJournal

    journal = SqliteJournal(tmp_path / "run.sqlite")
    runner = await qualify(unqualified(tmp_path, journal=journal))
    descriptor = CapabilityDescriptor(
        capability_id="gates", kind=runner.kind, revision=runner.revision, leased=True,
    )
    if change == "journal":
        journal = SqliteJournal(tmp_path / "other.sqlite")
    elif change != "absent":
        descriptor = replace(descriptor, **{
            change: {"kind": "gates", "revision": "different", "leased": False}[change],
        })
    with pytest.raises(ValueError, match="exact descriptor and journal"):
        Constructicon(journal=journal, capabilities={"gates": runner},
                      catalog={} if change == "absent" else {"gates": descriptor})


@pytest.mark.parametrize("world", ["same", "journal", "authority", "same-path", "adapter"])
async def test_gate_and_merge_effect_share_one_exact_world(tmp_path, world):
    from constructicon.substrate.effects.git import MergeVerifiedEffect
    from constructicon.substrate.journal.sqlite import SqliteJournal
    from tests.runtime.test_async_gates import gate_system

    journal = SqliteJournal(tmp_path / "run.sqlite")
    runner = await qualify(unqualified(tmp_path, journal=journal))
    effect_journal, authority = journal, runner.authority
    if world == "journal":
        effect_journal = SqliteJournal(tmp_path / "other.sqlite")
    elif world == "authority":
        authority = GitAuthority(seed_authority(tmp_path / "other"), tmp_path / "other-legacy")
    elif world == "same-path":
        authority = GitAuthority(Path(authority.repository_id), tmp_path / "other-legacy")
    effect = MergeVerifiedEffect(journal=effect_journal, authority=authority)
    if world == "adapter":
        effect = SimpleNamespace(profile=effect.profile)
    if world == "same":
        gate_system(journal, runner, effects={"merge_verified": effect})
    else:
        with pytest.raises(ValueError, match="same authority/journal"):
            gate_system(journal, runner, effects={"merge_verified": effect})


@LINUX
@pytest.mark.parametrize("field", ["provider", "acquisition", "epoch", "path"])
async def test_recovery_refuses_a_foreign_reference_without_closing_it(tmp_path, field):
    import json

    runner = await qualify(unqualified(tmp_path))
    ctx = gate_context(runner)
    acquired = await runner.acquire(ctx)
    stale = stale_row(acquired, ctx)
    if field in {"provider", "acquisition"}:
        raw = json.loads(acquired.resource_ref)
        raw[field] = "foreign"
        row = stale.lease.model_copy(update={"resource_ref": json.dumps(raw)})
    elif field == "epoch":
        row = stale.lease.model_copy(update={"acquisition_epoch": 2})
    else:
        row = stale.lease.model_copy(update={"path": context(binding="other").path.model_copy(
            update={"scope": context().path.scope.child("other")},
        )})
    with pytest.raises(ContractViolation, match="recovery"):
        await runner.reconcile(gate_context(runner, epoch=2), (replace(stale, lease=row),))
    assert not runner.closure.is_closed(acquired.resource.paths)
    assert not acquired.resource.paths.payload.exists()


async def test_bound_legacy_gate_cannot_hide_behind_an_unrelated_label(tmp_path):
    from constructicon.api.system import Constructicon
    from constructicon.substrate.gates.runner import BoundGateRunner
    from constructicon.substrate.journal.sqlite import SqliteJournal
    from tests.executorworld import FakeExecutorProvider, launch_identity

    executor = FakeExecutorProvider()
    executor._identity = launch_identity(executor.identity.profile.model_copy(update={
        "postures": frozenset({Posture.WRITE}),
    }))
    assert Posture.WRITE in executor.identity.profile.postures
    with pytest.raises(ValueError, match="require contained workspace and gate bindings"):
        Constructicon(
            journal=SqliteJournal(tmp_path / "run.sqlite"),
            capabilities={"executor": executor, "alias": object.__new__(BoundGateRunner)},
            catalog={"executor": executor.descriptor("executor")},
        )


@dataclass(frozen=True, kw_only=True)
class MaintenanceNativeLauncher(LinuxLauncher):
    """Observe the production boundary; every recorded call really launches."""

    calls: list = field(default_factory=list)

    async def run(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return await LinuxLauncher.run(self, command, **kwargs)


class MaintenanceNativeWriter:
    """A contained Python task double, never a vendor or subscription proof."""

    def __init__(self, launcher, vectors, *, extra=False):
        from constructicon.core.executor import ExecutorGrantPolicy, ExecutorProfile
        from constructicon.core.grants import IsolationProfile

        self.launcher, self.vectors, self.extra = launcher, vectors, extra
        self.calls = []
        self.profile = ExecutorProfile(
            name="maintenance-contained-scripted-model", structured_output=False,
            postures=frozenset({Posture.WRITE}), accepted_efforts=frozenset({"test"}),
            isolation=IsolationProfile(filesystem="workspace_only", process_tree_owned=True,
                environment_allowlisted=True, network_enforced=True),
            # The scripted model needs no connection. Even the authorized allow
            # posture remains physically networkless in this narrower double.
            grant_policy=ExecutorGrantPolicy(tool_sets=(("contained_python",),),
                network_modes=("allow",), network_access="none", environment_names=(),
                workspace_required=True),
        )

    def validate_grants(self, grants):
        return self.profile.grant_faults(grants)

    async def execute(self, task, *, workspace, grants):
        from constructicon.api.plan_manifest_application import WRITE_INSTRUCTION
        from constructicon.core.executor import ExecutorSuccess

        assert task.instruction == WRITE_INSTRUCTION and task.context == ()
        assert task.response_schema is None and not self.validate_grants(grants)
        self.calls.append(task)
        program = (
            "from pathlib import Path\n"
            "assert Path('/proc/net/route').read_text().splitlines()[1:] == []\n"
            "p=Path('tests/vectors/plan_manifest.json')\n"
            "p.parent.mkdir(parents=True,exist_ok=True)\n"
            f"p.write_bytes({self.vectors!r})\n"
            + ("Path('unrelated.py').write_bytes(b'unrelated change')\n" if self.extra else "")
            + "print('scripted vector contribution',flush=True)\n"
        )
        async with workspace.use() as guard:
            result = await self.launcher.run(
                (PYTHON, "-I", "-c", program), workspace=Path(workspace.path),
                posture=Posture.WRITE, guard_fds=(guard,), timeout_s=grants.timeout_s,
            )
        assert result.returncode == result.payload_returncode == 0, result.stderr.decode()
        assert not result.timed_out and result.bound_exceeded is None
        assert result.stdout == b"scripted vector contribution\n"
        return ExecutorSuccess(raw_reply="scripted vector contribution")


@pytest.mark.parametrize("case", ["accept", "extra", "weak"])
async def test_native_maintenance_operational_entry_captures_checks_closes_and_replays(
    launcher, tmp_path, monkeypatch, case,
):
    from constructicon.api.maintenance_entry import (
        inspect_result,
        maintenance_application_revision,
        run_maintenance,
    )
    from constructicon.api.plan_manifest_application import (
        GRAPH_NAME,
        MaintenanceResources,
        maintenance_checks,
        maintenance_graph,
    )
    from constructicon.core.address import ExecutionPath, ScopePath
    from constructicon.core.envelope import GitRef
    from constructicon.core.grants import EffectiveGrants, ModelSelection
    from constructicon.core.maintenance import (
        MaintenanceAttemptAuthorization,
        MaintenanceCapabilityPin,
        PlanManifestRequest,
    )
    from constructicon.core.manifest import parse_manifest_json, source_graph_hash_for
    from constructicon.core.run import RunStatus
    from constructicon.substrate.git.acquisition import AcquisitionPaths
    from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
    from constructicon.substrate.journal.sqlite import SqliteJournal
    from tests.executorworld import FakeExecutorProvider, launch_identity
    from tests.substrate.test_maintenance_vectors import (
        SOURCE,
        entries,
        path,
        permitting_vectors,
        wire,
    )

    vectors = permitting_vectors() if case != "weak" else wire([
        path("a.md"), path(".md"), entries(b"a" * 64 + b"  a.md\n"),
        entries(b"bad"), entries(b"\xff"),
    ])
    physical = MaintenanceNativeLauncher(
        **{item.name: getattr(launcher, item.name) for item in fields(LinuxLauncher)},
    )
    journal = SqliteJournal(tmp_path / "maintenance.sqlite")
    minted = []
    actual_mint = journal.mint_attestation

    def observe_mint(lease, draft):
        attestation = actual_mint(lease, draft)
        minted.append(attestation)
        return attestation

    monkeypatch.setattr(journal, "mint_attestation", observe_mint)
    runner = unqualified(tmp_path, physical, journal=journal)
    base, expected_candidate = maintenance_commits(runner, SOURCE, vectors, extra=case == "extra")
    pin = hashlib.sha256(SOURCE).hexdigest()
    inventory = runner.authority._run("ls-tree", "-r", "-z", base).stdout.encode()
    runner.checks = maintenance_checks(SOURCE, pin, inventory,
                                       runner.authority.environment.object_format)
    gate = await qualify(runner)
    workspace = ContainedWriteWorkspaceProvider(
        runner.authority, root=tmp_path / "writer-acquisitions", target_ref=runner.target_ref,
        provider_id="maintenance-workspace", posture=Posture.WRITE, launcher=physical,
    )
    request = PlanManifestRequest(
        repository=runner.authority.repository_id, target_ref=runner.target_ref,
        base_commit=base, target_sha256=pin, check_set_hash=gate.check_set_hash,
    )
    resources = MaintenanceResources(journal, runner.authority, workspace, gate, request, SOURCE)
    executor = FakeExecutorProvider()
    executor.executor = MaintenanceNativeWriter(physical, vectors, extra=case == "extra")
    executor._identity = launch_identity(executor.executor.profile)
    grants = EffectiveGrants(
        posture=Posture.WRITE, model_selection=ModelSelection(kind="explicit", model="scripted"),
        effort="test", allowed_tools=("contained_python",), env_allowlist=(), network="allow",
        timeout_s=300,
    )
    graph = maintenance_graph(
        executor_id="maintenance-executor", workspace_id=workspace.provider_id,
        gate_id=gate.provider_id, writer_grants=grants,
    )
    authorization = MaintenanceAttemptAuthorization(
        authorization_id="native-maintenance-entry", actor_id="static:native-maintenance",
        idempotency_key="native-maintenance-once", scope=ScopePath(segments=(GRAPH_NAME, "writer")),
        binding="executor", source_graph_hash=source_graph_hash_for(graph),
        capability_id="maintenance-executor", revision=executor.identity.revision,
        operator_binding_digest=digest("scripted-maintenance-binding", 1, "no-vendor"),
        journal=str((tmp_path / "maintenance.sqlite").resolve()), max_epoch=1,
        not_after=datetime.now(UTC) + timedelta(hours=1),
        grants=grants, attempt_record=str(tmp_path / "maintenance.attempt"), request=request,
        application_revision=maintenance_application_revision(),
        workspace=MaintenanceCapabilityPin(capability_id=workspace.provider_id,
                                           revision=workspace.revision),
        gate=MaintenanceCapabilityPin(capability_id=gate.provider_id, revision=gate.revision),
    )
    executor.maintenance = authorization
    arguments = dict(resources=resources, executor=executor,
                     executor_descriptor=executor.descriptor(authorization.capability_id),
                     authorization=authorization)
    result = await run_maintenance(**arguments)
    run_id = authorization.run_id
    state = journal.run_state(run_id)
    assert state.status is (RunStatus.SUCCEEDED if case == "accept" else RunStatus.FAILED), \
        journal.events(run_id, limit=100)
    assert state.owner_id is None and not journal.cancel_requested(run_id)
    assert len(executor.executor.calls) == 1
    manifest = parse_manifest_json(journal.load_manifest_json(journal.run_manifest_hash(run_id)))
    assert manifest.source_graph == graph
    assert manifest.source_graph_hash == authorization.source_graph_hash
    assert journal.run_inputs(run_id) == {"request": request.model_dump(mode="json")}
    assert {row.component for row in manifest.resolved_components} == {
        "constructicon.maintenance/plan-manifest-writer",
        "constructicon.maintenance/plan-manifest-checker",
    }
    checkpoint = journal.checkpoint(run_id, ExecutionPath(scope=authorization.scope))
    assert checkpoint is not None
    candidate_ref = GitRef.model_validate(checkpoint.outputs["candidate"].payload)
    assert candidate_ref.diff_against == base and candidate_ref.repository == request.repository
    assert runner.authority.parents_of(candidate_ref.commit) == (base,)
    assert runner.authority.tree_of(candidate_ref.commit) \
        == runner.authority.tree_of(expected_candidate)
    rows = journal.capability_leases(run_id)
    assert len(rows) == 3 and all(row.state == "closed" for row in rows)
    assert {row.binding_id: row.disposition for row in rows} == {
        "executor": "released", "workspace": "released",
        "gate": "released" if case == "accept" else "discarded",
    }
    for row in rows:
        if row.binding_id not in {"workspace", "gate"}:
            continue
        ref = json.loads(row.resource_ref)
        provider = workspace if row.binding_id == "workspace" else gate
        paths = AcquisitionPaths(provider.root, ref["acquisition"])
        assert provider.closure.is_closed(paths) and not paths.payload.exists()
    assert all(handle.closed for handle in executor.handles)
    assert not executor.ledger.resources
    assert not list(workspace.root.glob("payloads/*")) and not list(gate.root.glob("payloads/*"))
    assert runner.authority.resolve_ref(request.target_ref) == base
    assert any("git('add', '--all'" in arg for command, _ in physical.calls for arg in command)
    assert any(command[:2] == ("/usr/bin/git", "pack-objects") for command, _ in physical.calls)
    assert sum(gate.checks[0].argv[-1] in command for command, _ in physical.calls) == 1
    assert len(minted) == 1
    proof = journal.load_attestation(minted[0].attestation_id)
    assert proof == minted[0] and proof.created_by_run == run_id
    assert proof.manifest_hash == manifest.manifest_hash
    assert proof.check_set_hash == request.check_set_hash
    assert proof.subject.candidate == candidate_ref.commit and proof.subject.expected_base == base
    assert len(proof.checks) == 1 and proof.checks[0].name == "plan-manifest-trusted-vectors"
    assert proof.checks[0].status == ("passed" if case == "accept" else "failed")
    assert proof.ok is (case == "accept")
    if case == "accept":
        assert result is not None and result.run_id == run_id and result.candidate == candidate_ref
        proof = journal.load_attestation(result.evaluation.attestation_id)
        assert proof.ok and proof.created_by_run == run_id
        assert proof.manifest_hash == manifest.manifest_hash
        assert proof.subject == result.evaluation.subject
        assert proof.subject.candidate == candidate_ref.commit
        report = json.loads(result.evaluation.checks[0].detail)
        assert report["passed"] is True
        assert report["baseline"] == {"tests_run": 24, "failures": 0, "errors": 0, "skips": 0}
        assert tuple(item["name"] for item in report["mutants"]) == (
            "path_absolute", "path_noncanonical", "path_parent", "path_unsafe_characters",
            "path_any_suffix", "digest_relaxed", "entries_duplicate_overwrite",
            "entries_conflict_skip",
        )
        assert all(item["distinguished"] and item["counts"]["tests_run"] == 24
                   and item["counts"]["failures"] > 0
                   and item["counts"]["errors"] == item["counts"]["skips"] == 0
                   for item in report["mutants"])
        assert report["input_sha256"] == result.input_sha256 == hashlib.sha256(vectors).hexdigest()
        assert report["render_sha256"] == result.render_sha256 and report["target_sha256"] == pin
        published = tmp_path / "maintenance-result.json"
        assert published.is_file() and published.stat().st_size <= 65536
        assert inspect_result(published) == {
            "schema_version": 1, "meaning": "historical-application-acceptance",
            "run_id": str(run_id), "input_sha256": result.input_sha256,
            "render_sha256": result.render_sha256, "candidate_commit": str(candidate_ref.commit),
        }
    else:
        assert result is None
        assert journal.checkpoint(run_id, ExecutionPath(scope=ScopePath(
            segments=(GRAPH_NAME, "checker"),
        ))) is None
        assert not (tmp_path / "maintenance-result.json").exists()
    calls, event_seq = len(physical.calls), journal.max_event_seq(run_id)
    replay = await run_maintenance(**arguments)
    assert replay == result and len(executor.executor.calls) == 1 and len(physical.calls) == calls
    assert journal.max_event_seq(run_id) == event_seq
    assert runner.authority.resolve_ref(request.target_ref) == base
    # Reopen the actual store and reconstruct providers. No in-memory result or
    # executor handle may supply replay evidence; this is object reconstruction,
    # not a claim of a separate-process crash measurement.
    reopened = SqliteJournal(tmp_path / "maintenance.sqlite")
    reconstructed_gate = await ContainedGateRunner.create(
        journal=reopened, authority=runner.authority, root=gate.root,
        target_ref=gate.target_ref, provider_id=gate.provider_id,
        launcher=physical, checks=gate.checks,
    )
    reconstructed_workspace = ContainedWriteWorkspaceProvider(
        runner.authority, root=workspace.root, target_ref=workspace.target_ref,
        provider_id=workspace.provider_id, posture=Posture.WRITE, launcher=physical,
    )
    reconstructed_executor = FakeExecutorProvider()
    reconstructed_executor.executor = MaintenanceNativeWriter(
        physical, vectors, extra=case == "extra",
    )
    reconstructed_executor._identity = launch_identity(reconstructed_executor.executor.profile)
    reconstructed_executor.maintenance = authorization
    reconstructed = replace(resources, journal=reopened, workspace=reconstructed_workspace,
                            gate=reconstructed_gate)
    calls = len(physical.calls)  # Reassembly's mount-free runtime probe is observed separately.
    assert await run_maintenance(
        resources=reconstructed, executor=reconstructed_executor,
        executor_descriptor=reconstructed_executor.descriptor(authorization.capability_id),
        authorization=authorization,
    ) == result
    assert not reconstructed_executor.executor.calls and not reconstructed_executor.handles
    assert len(physical.calls) == calls and reopened.max_event_seq(run_id) == event_seq
    assert reopened.capability_leases(run_id) == rows
