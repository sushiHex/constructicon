"""Phase separation, real Linux checks, and owned gate failure boundaries."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.errors import Cancelled, ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import digest
from constructicon.core.run import OwnershipLost
from constructicon.substrate.executors.linux import ProcessLimits, ProcessResult
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
