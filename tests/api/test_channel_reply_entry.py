"""The channel stored-reply task through the real entry, Graph, capture, gate and journal.

Fake-first: a genuine L0 writer double or the real adapter with a scripted native
peer writes the hand-written candidate. No credentials, no live model.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.api import maintenance_entry as entry
from constructicon.api.plan_manifest_application import (
    CHANNEL_STORED_REPLY,
    INVENTORY_CHECK_NAME,
    PLAN_MANIFEST,
    maintenance_graph,
)
from constructicon.core.address import ExecutionPath, ScopePath
from constructicon.core.envelope import utc_now
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorGrantPolicy
from constructicon.core.identity import Digest, digest
from constructicon.core.maintenance import (
    CHANNEL_TARGET_PATH,
    ChannelReplyAttemptAuthorization,
    ChannelReplyResult,
    MaintenanceAttemptAuthorization,
    MaintenanceCapabilityPin,
)
from constructicon.core.manifest import source_graph_hash_for
from constructicon.core.refusal import RefusalCode
from constructicon.core.run import RunStatus
from constructicon.substrate.executors.codex_host import WRITE_GRANTS
from constructicon.substrate.gates.channel_reply import CHECK_NAME as CHANNEL_CHECK
from constructicon.substrate.git.pack import PackLimits
from constructicon.substrate.git.process import GitProcess
from tests.api import test_plan_manifest_application as application_tests
from tests.api.test_maintenance_entry import change_authorization_law
from tests.api.test_maintenance_report import layout as layout
from tests.executorworld import launch_identity
from tests.maintenance_instructions import CHANNEL_PURPOSE, fast_import_entry
from tests.substrate.test_channel_reply_oracle import BASE, CANDIDATE
from tests.substrate.test_codex_adapter import bare_launcher
from tests.substrate.test_codex_adapter import portable_binding as portable_binding

concrete_application = application_tests.concrete_application
# Captured at import, before any world substitutes its guarded remover.
_RMTREE = shutil.rmtree
CHANNEL = pytest.mark.parametrize("concrete_application", ["channel-stored-reply"],
                                  indirect=True)
# This branch's base (b0d2c0b) application revision: an old pin, never current.
OLD_APPLICATION_REVISION = (
    "sha256:06be0dbbdcfd7af834ec255826ca26ff9e952f04f03d84719b08ad461ba6a9f1"
)


def authorize(resources, executor, task, model=None):
    profile = executor.executor.profile.model_copy(update={
        "accepted_efforts": frozenset({WRITE_GRANTS.effort}),
        "grant_policy": ExecutorGrantPolicy(tool_sets=(("contained_python",),),
            network_modes=("allow",), network_access="none", environment_names=(),
            workspace_required=True),
    })
    executor.executor.profile = profile
    executor._identity = launch_identity(profile)
    graph = maintenance_graph(executor_id="executor", workspace_id=resources.workspace.provider_id,
        gate_id=resources.gate.provider_id, writer_grants=WRITE_GRANTS, task=task)
    model = task.authorization_model if model is None else model
    root = Path(resources.journal._db_path).resolve().parent
    fields = {
        "authorization_id": "channel-entry-double", "actor_id": "operator:test",
        "idempotency_key": "maintenance", "scope": task.writer_scope, "binding": "executor",
        "source_graph_hash": source_graph_hash_for(graph), "capability_id": "executor",
        "revision": str(executor.identity.revision),
        "operator_binding_digest": digest("fake-binding", 1, 0),
        "journal": str(root / Path(resources.journal._db_path).name), "max_epoch": 1,
        "not_after": utc_now() + timedelta(hours=1), "grants": WRITE_GRANTS,
        "attempt_record": str(root / "attempt.json"),
        "application_revision": entry.maintenance_application_revision(),
        "workspace": MaintenanceCapabilityPin(capability_id=resources.workspace.provider_id,
                                              revision=resources.workspace.revision),
        "gate": MaintenanceCapabilityPin(capability_id=resources.gate.provider_id,
                                         revision=resources.gate.revision),
    }
    # Construct without the task's own request validation only for a crossed
    # model: the crossed authorization must be refused by the entry, by name.
    if model is task.authorization_model:
        auth = model(request=resources.request, **fields)
    else:
        auth = model.model_construct(request=resources.request, purpose=model.model_fields[
            "purpose"].default, **fields)
    executor.maintenance = auth
    return auth


def forbid_startup(monkeypatch, entered):
    async def forbidden(*args, **kwargs):
        entered.append(True)
        pytest.fail("a refused authority reached RunHost startup or acquisition")

    monkeypatch.setattr(entry.ControlPlane, "startup", forbidden)


async def git(resources, *args):
    return await GitProcess(resources.authority.git_executable,
                            application_tests.ProcessLimits()).run(
        *args, cwd=Path(resources.authority.repository_id))


@CHANNEL
async def test_hand_written_candidate_is_accepted_published_and_replayed(
    concrete_application,
):
    resources, executor, _system, control, _launch = concrete_application
    await control.shutdown()
    auth = authorize(resources, executor, CHANNEL_STORED_REPLY)
    first = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth)
    assert isinstance(first, ChannelReplyResult) and first.evaluation.ok
    assert resources.journal.run_state(auth.run_id).status is RunStatus.SUCCEEDED
    assert all(row.state == "closed" for row in resources.journal.capability_leases(auth.run_id))
    request = resources.request
    assert first.base_sha256 == request.target_sha256 == hashlib.sha256(BASE).hexdigest()
    assert first.candidate_sha256 == hashlib.sha256(CANDIDATE).hexdigest()
    assert resources.authority.parents_of(first.candidate.commit) == (request.base_commit,)
    assert resources.authority.resolve_ref(request.target_ref) == request.base_commit
    delta = await git(resources, "diff-tree", "--no-commit-id", "--raw", "-r", "-z",
                      "--no-renames", request.base_commit, first.candidate.commit)
    fields = delta.split(b"\0")
    assert fields[1:] == [CHANNEL_TARGET_PATH.encode(), b""]
    assert fields[0].split()[0:2] == [b":100644", b"100644"] and fields[0].split()[4] == b"M"
    attestation = resources.journal.load_attestation(first.evaluation.attestation_id)
    assert attestation.ok and attestation.check_set_hash == request.check_set_hash
    names = [check.name for check in attestation.checks]
    assert "channel-stored-reply-exact-extraction" in names
    report = json.loads(next(check.detail for check in first.evaluation.checks
                             if check.name == "channel-stored-reply-exact-extraction"))
    assert report["passed"] is True and report["candidate_sha256"] == first.candidate_sha256
    assert report["python"]  # the worker's own interpreter, recorded by the worker
    published = Path(auth.journal).parent / "maintenance-result.json"
    stored = json.loads(published.read_bytes())
    assert stored["purpose"] == "channel-stored-reply" and "input_sha256" not in stored["result"]
    before = published.read_bytes()
    second = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth)
    assert second == first and len(executor.executor.calls) == 1
    assert published.read_bytes() == before
    observed = entry.inspect_result(published)
    assert observed["meaning"] == "historical-application-acceptance"
    assert observed["purpose"] == "channel-stored-reply"
    assert "repository" not in json.dumps(observed)


@CHANNEL
@pytest.mark.parametrize("candidate", ["accepted", "noop", "extra-edit"])
async def test_the_shipped_packet_reads_a_real_channel_run_from_a_private_copy(
    concrete_application, layout, capsys, monkeypatch, candidate,
):
    """A real entry run, its durable files laid out as the report reads them."""
    import sqlite3

    from constructicon.api import maintenance_report
    from tests.api.test_maintenance_report import assert_closed_refusal, tree

    resources, executor, _system, control, _launch = concrete_application
    await control.shutdown()
    if candidate != "accepted":
        executor.executor.candidate = (BASE if candidate == "noop" else CANDIDATE.replace(
            b"if max_batch <= 0:", b"if max_batch < 0:"))
    auth = authorize(resources, executor, CHANNEL_STORED_REPLY)
    result = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth)
    assert (result is not None) is (candidate == "accepted")
    root, out = layout
    root.mkdir(mode=0o700)
    source = sqlite3.connect(resources.journal._db_path)
    copy = sqlite3.connect(root / "maintenance.sqlite")
    try:
        source.backup(copy)
    finally:
        copy.close()
        source.close()
    # The L0 writer double keeps no adapter attempt record; the packet says missing.
    assert not Path(auth.attempt_record).exists()
    published = Path(auth.journal).parent / "maintenance-result.json"
    if published.exists():
        shutil.copyfile(published, root / "maintenance-result.json")
    (root / "application-run.json").write_text(json.dumps(
        {"accepted": candidate == "accepted", "run_id": auth.run_id}), encoding="utf-8")
    before = tree(root)
    # The world's guarded remover accepts only its own root; the report's own
    # scratch and this layout are elsewhere, so restore the genuine primitive.
    monkeypatch.setattr(shutil, "rmtree", _RMTREE)
    code = maintenance_report.main(["--root", str(root), "--out", str(out),
        "--command-report", str(root / "application-run.json"), "--run-id", auth.run_id,
        "--authorization-id", auth.authorization_id])
    text = capsys.readouterr().out
    packet = json.loads(text)
    assert code == 0 and packet["complete"] is True, packet
    assert len(text.encode()) <= maintenance_report.MAX_PACKET_BYTES
    assert packet["purpose"] == "channel-stored-reply"
    assert packet["leases"]["summary"] == "recorded-closed"
    # The copy is not the request's authority: the target is not guessed.
    assert packet["target"]["reason"] == "request-names-another-repository"
    assert tree(root) == before
    for marker in (str(root), str(Path(resources.authority.repository_id))):
        assert marker not in text
    if candidate == "accepted":
        assert packet["status"] == "succeeded"
        assert packet["outcome"] == "succeeded-with-acceptance-record"
        assert packet["attestation"]["observation"] == "recorded"
        assert packet["attestation"]["ok"] is True
        assert packet["result"] == {"observation": "historical-acceptance-observed",
            "candidate_commit": str(result.candidate.commit),
            "base_sha256": result.base_sha256, "candidate_sha256": result.candidate_sha256}
        return
    assert packet["status"] == "failed" and packet["outcome"] == "refused"
    assert packet["result"] == {"observation": "missing"}
    assert packet["refusal"]["node"] == ("writer" if candidate == "noop" else "checker")
    # A crossed copy: this task's run beside a same-run plan-manifest stored result.
    from constructicon.core.envelope import GitRef
    from constructicon.core.gates import MergeEvaluation
    from constructicon.core.maintenance import PlanManifestResult

    crossed = PlanManifestResult(run_id=auth.run_id,
        candidate=GitRef(repository=resources.request.repository,
                         commit=resources.request.base_commit),
        evaluation=MergeEvaluation(subject=None, attestation_id=None, checks=()),
        input_sha256="a" * 64, render_sha256="b" * 64)
    (root / "maintenance-result.json").write_text(json.dumps({"schema_version": 1,
        "meaning": "historical-application-acceptance",
        "authorization_digest": "sha256:" + "c" * 64,
        "result": crossed.model_dump(mode="json")}), encoding="utf-8")
    code = maintenance_report.main(["--root", str(root), "--out", str(out.parent / "again"),
        "--command-report", str(root / "application-run.json"), "--run-id", auth.run_id,
        "--authorization-id", auth.authorization_id])
    text = capsys.readouterr().out
    refused = json.loads(text)
    assert code == 1 and refused["diagnostic_stage"] == "task"
    assert_closed_refusal(refused, text, "diagnostic")


def attested_checks(resources, run_id):
    """Each attestation the run minted, as (check name, status) pairs."""
    with closing(sqlite3.connect(resources.journal._db_path)) as connection:
        ids = [row[0] for row in connection.execute("SELECT attestation_id FROM attestations")]
    found = [resources.journal.load_attestation(value) for value in ids]
    return [(attestation.ok, [(check.name, check.status) for check in attestation.checks])
            for attestation in found if attestation.created_by_run == run_id]


@CHANNEL
@pytest.mark.parametrize(("candidate", "code", "failed"), [
    ("noop", RefusalCode.CAPTURE_UNCHANGED, None),
    ("extra-edit", RefusalCode.GATE_NOT_POSITIVE, CHANNEL_CHECK),
    ("extra-file", RefusalCode.GATE_NOT_POSITIVE, INVENTORY_CHECK_NAME),
], ids=["noop", "extra-edit", "extra-file"])
async def test_a_refused_candidate_publishes_nothing(concrete_application, candidate, code,
                                                     failed):
    resources, executor, _system, control, _launch = concrete_application
    await control.shutdown()
    executor.executor.candidate = {"noop": BASE, "extra-file": CANDIDATE}.get(
        candidate, CANDIDATE.replace(b"if max_batch <= 0:", b"if max_batch < 0:"))
    executor.executor.extra = candidate == "extra-file"
    auth = authorize(resources, executor, CHANNEL_STORED_REPLY)
    result = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth)
    assert result is None and len(executor.executor.calls) == 1
    assert resources.journal.run_state(auth.run_id).status is RunStatus.FAILED
    assert not (Path(auth.journal).parent / "maintenance-result.json").exists()
    failures = [event.payload for event in resources.journal.events(auth.run_id, limit=100)
                if event.kind == "NodeFailed"]
    expected = ("maintenance captured candidate equals the pinned base" if candidate == "noop"
                else "maintenance candidate failed its exact gate")
    assert failures == [{"error_type": "ContractViolation", "error": expected,
                         "refusal": [code.value]}]
    # An extra file and a wrong edit fail different named checks of one exam.
    checks = [(name, "failed" if name == failed else "passed")
              for name in (INVENTORY_CHECK_NAME, CHANNEL_CHECK)]
    assert attested_checks(resources, auth.run_id) == ([(False, checks)] if failed else [])


async def refused_world(tmp_path, monkeypatch):
    """The concrete_application world, assembled here so one test can pair two of them."""
    resources, _launch = await application_tests.concrete_resources(
        tmp_path, monkeypatch, committed_tree=False, channel=True)
    executor = application_tests.FakeExecutorProvider()
    executor.executor = application_tests.PortableChannelWriter(CANDIDATE.replace(
        b"if max_batch <= 0:", b"if max_batch < 0:"))
    executor._identity = launch_identity(executor.executor.profile)
    await application_tests.maintenance_system(resources, executor_id="executor",
        executor=executor, executor_descriptor=executor.descriptor("executor"),
        writer_grants=WRITE_GRANTS)
    return resources, executor


async def test_a_code_changes_no_status_checkpoint_or_attestation(
    tmp_path, portable_binding, portable_acquisition_namespace,
):
    """Paired runs differ only in whether the failing guard is coded (REFUSAL_CODE.md)."""
    from constructicon.api import plan_manifest_application as application

    def uncoded(*args, refusal=()):
        return ContractViolation(*args)

    observed = []
    for coded in (True, False):
        # Each world substitutes its own primitives, scoped to its own directory.
        with pytest.MonkeyPatch.context() as monkeypatch:
            if not coded:
                monkeypatch.setattr(application, "ContractViolation", uncoded)
            resources, executor = await refused_world(tmp_path / str(coded), monkeypatch)
            auth = authorize(resources, executor, CHANNEL_STORED_REPLY)
            assert await entry.run_maintenance(resources=resources, executor=executor,
                executor_descriptor=executor.descriptor("executor"), authorization=auth) is None
        events = resources.journal.events(auth.run_id, limit=100)
        failure, = (event.payload for event in events if event.kind == "NodeFailed")
        refusal = failure.pop("refusal", None)
        assert refusal == ([RefusalCode.GATE_NOT_POSITIVE.value] if coded else None)
        observed.append((
            resources.journal.run_state(auth.run_id).status, failure,
            [event.kind for event in events],
            [resources.journal.checkpoint(auth.run_id, ExecutionPath(scope=ScopePath(
                segments=(CHANNEL_STORED_REPLY.graph_name, node)))) is not None
             for node in ("writer", "checker")],
            attested_checks(resources, auth.run_id),
        ))
    assert observed[0] == observed[1]
    assert observed[0][0] is RunStatus.FAILED and observed[0][3] == [True, False]


@pytest.mark.parametrize(("concrete_application", "assembled", "crossed"), [
    ("channel-stored-reply", CHANNEL_STORED_REPLY, MaintenanceAttemptAuthorization),
    (None, PLAN_MANIFEST, ChannelReplyAttemptAuthorization),
], indirect=["concrete_application"], ids=["plan-for-channel", "channel-for-plan"])
async def test_a_crossed_task_authority_is_refused_by_name_before_startup(
    concrete_application, monkeypatch, assembled, crossed,
):
    resources, executor, _system, control, _launch = concrete_application
    await control.shutdown()
    auth = authorize(resources, executor, assembled, model=crossed)
    entered = []
    forbid_startup(monkeypatch, entered)
    with pytest.raises(ContractViolation) as refused:
        await entry.run_maintenance(resources=resources, executor=executor,
            executor_descriptor=executor.descriptor("executor"), authorization=auth)
    assert str(refused.value) == (
        "maintenance authorization purpose differs from the assembled task")
    assert entered == [] and executor.executor.calls == []
    assert resources.journal.run_state(auth.run_id) is None
    assert not Path(auth.attempt_record).exists()
    # The unavailable-assembly boundary refuses the crossed type as well.
    executor._unavailable_reasons = ("not generally available",)
    executor.qualified_graph = auth.source_graph_hash
    with pytest.raises(ContractViolation, match="available, exact leased executor"):
        await entry.maintenance_system(resources, executor_id="executor", executor=executor,
            executor_descriptor=executor.descriptor("executor"), writer_grants=WRITE_GRANTS)


async def test_no_old_application_pin_authorizes_the_new_revision(
    concrete_application, monkeypatch,
):
    resources, executor, _system, control, _launch = concrete_application
    await control.shutdown()
    assert str(entry.maintenance_application_revision()) != OLD_APPLICATION_REVISION
    auth = authorize(resources, executor, PLAN_MANIFEST).model_copy(update={
        "application_revision": Digest(OLD_APPLICATION_REVISION)})
    executor.maintenance = auth
    entered = []
    forbid_startup(monkeypatch, entered)
    with pytest.raises(ContractViolation, match="assembled resources"):
        await entry.run_maintenance(resources=resources, executor=executor,
            executor_descriptor=executor.descriptor("executor"), authorization=auth)
    assert entered == [] and executor.executor.calls == []


@CHANNEL
async def test_a_retained_run_resumes_only_under_its_exact_application_revision(
    concrete_application, monkeypatch,
):
    resources, executor, _system, control, _launch = concrete_application
    await control.shutdown()
    auth = authorize(resources, executor, CHANNEL_STORED_REPLY)
    assert await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth) is not None
    descriptor = executor.descriptor("executor")
    # A new controller: the application module's bytes, hence its revision, change.
    change_authorization_law(monkeypatch, "api/plan_manifest_application.py",
        b'capture_message="constructicon channel stored-reply extraction"',
        b'capture_message="constructicon channel stored-reply extraction v2"')
    entered = []
    forbid_startup(monkeypatch, entered)
    with pytest.raises(ContractViolation, match="assembled resources"):
        await entry.require_maintenance_attempt(resources, executor, descriptor, auth)
    renewed_graph = maintenance_graph(executor_id="executor",
        workspace_id=resources.workspace.provider_id, gate_id=resources.gate.provider_id,
        writer_grants=WRITE_GRANTS, task=CHANNEL_STORED_REPLY)
    assert source_graph_hash_for(renewed_graph) != auth.source_graph_hash
    renewed = auth.model_copy(update={
        "application_revision": entry.maintenance_application_revision(),
        "source_graph_hash": source_graph_hash_for(renewed_graph)})
    executor.maintenance = renewed
    # Even a renewed authorization cannot recover the older revision's retained run.
    with pytest.raises(ContractViolation, match="journal retains another component"):
        await entry.require_maintenance_attempt(resources, executor, descriptor, renewed)
    assert entered == [] and len(executor.executor.calls) == 1


@CHANNEL
async def test_a_committed_writer_checkpoint_never_redispatches(
    concrete_application, monkeypatch,
):
    resources, executor, _system, control, launcher = concrete_application
    await control.shutdown()
    auth = authorize(resources, executor, CHANNEL_STORED_REPLY)
    started, allowed = asyncio.Event(), asyncio.Event()
    original_run = launcher.run

    async def run(command, **kwargs):
        if "trusted_channel_stored_reply" in " ".join(command):
            started.set()
            await allowed.wait()
        return await original_run(command, **kwargs)

    monkeypatch.setattr(launcher, "run", run)
    first = asyncio.create_task(entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth))
    try:
        async with asyncio.timeout(60):
            await started.wait()
    except BaseException:
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        raise
    assert len(executor.executor.calls) == 1
    assert resources.journal.run_state(auth.run_id).status is RunStatus.RUNNING
    first.cancel()
    outcome = await asyncio.gather(first, return_exceptions=True)
    assert isinstance(outcome[0], asyncio.CancelledError)
    assert not (Path(auth.journal).parent / "maintenance-result.json").exists()
    allowed.set()

    async def no_second_acquire(context):
        pytest.fail("checker-only recovery attempted another writer acquisition")

    monkeypatch.setattr(executor, "acquire", no_second_acquire)
    result = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth)
    assert isinstance(result, ChannelReplyResult) and result.evaluation.ok
    assert len(executor.executor.calls) == 1


@CHANNEL
async def test_scripted_callback_candidate_is_accepted_through_the_real_adapter(
    concrete_application, portable_binding, tmp_path, monkeypatch,
):
    from tests.maintenance_task_world import configure_executor_guard, scripted_task_executor
    from tests.model_seat import ideal

    resources, _executor, _system, control, launch = concrete_application
    await control.shutdown()
    program = (
        "from pathlib import Path\n"
        f"p=Path({CHANNEL_TARGET_PATH!r})\n"
        f"assert p.read_bytes()=={BASE!r}\n"
        f"p.write_bytes({CANDIDATE!r})\n"
        "print('task callback completed')\n"
    )
    assert len(program.encode()) <= launch.limits.input_bytes
    resources, executor, scripted, _configuration, authorization = await scripted_task_executor(
        resources, launch, portable_binding, tmp_path, ideal(program), task=CHANNEL_STORED_REPLY)
    assert scripted.realness.model == "ideal" and not scripted.realness.contained
    assert type(authorization) is ChannelReplyAttemptAuthorization
    configure_executor_guard(monkeypatch)
    result = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=application_tests_descriptor(executor), authorization=authorization)
    assert isinstance(result, ChannelReplyResult) and result.evaluation.ok
    assert result.candidate_sha256 == hashlib.sha256(CANDIDATE).hexdigest()
    assert scripted.native.methods.count("turn/start") == 1
    assert scripted.native.callback_responses[0]["result"]["success"] is True
    record = json.loads(Path(authorization.attempt_record).read_bytes())
    assert record["purpose"] == "channel-stored-reply"
    assert record["phase"] == "outcome" and record["dispatch"] == "completed"
    published = Path(authorization.journal).parent / "maintenance-result.json"
    assert entry.inspect_result(published)["purpose"] == "channel-stored-reply"


def application_tests_descriptor(executor):
    from tests.substrate.test_codex_adapter import descriptor_of

    return descriptor_of(executor, "executor")


async def _bundle(tmp_path, target: bytes):
    import shutil

    from constructicon.api import _maintenance_source as source_module
    from constructicon.substrate.executors.linux import ProcessLimits

    seed = tmp_path / "reviewed-source.git"
    seed.mkdir()
    await source_module.git(seed, "init", "--bare", "--template=", ".")
    commit = (b"commit refs/heads/reviewed\n"
              b"committer test <test@example.invalid> 1767225600 +0000\ndata 1\nx\n"
              + f"M 100644 inline {CHANNEL_TARGET_PATH}\ndata {len(target)}\n".encode()
              + target + b"\n" + fast_import_entry(CHANNEL_PURPOSE) + b"\ndone\n")
    await GitProcess(str(Path(shutil.which("git")).resolve()), ProcessLimits()).run(
        "fast-import", "--quiet", cwd=seed, stdin=commit)
    bundle = tmp_path / "reviewed.bundle"
    await source_module.git(seed, "bundle", "create", str(bundle), "refs/heads/reviewed")
    base = (await source_module.git(seed, "rev-parse", "refs/heads/reviewed")).strip().decode()
    return bundle, base


@pytest.mark.parametrize(("target", "refusal"), [
    (BASE, None),
    (CANDIDATE, "maintenance channel base refused: base-has-helper"),
    (BASE.replace(b"{message_id} pins no reply port", b"{message_id} has no reply port"),
     "maintenance channel base refused: base-block-missing"),
], ids=["unrefactored", "already-refactored", "no-exact-block"])
async def test_preparation_pins_the_target_and_refuses_a_finished_extraction(
    tmp_path, monkeypatch, target, refusal,
):
    from constructicon.api import _maintenance_source as source_module

    bundle, base = await _bundle(tmp_path, target)
    root = tmp_path / "maintenance"

    def portable_custody(path):
        assert path.is_absolute() and path.resolve() == path and path.is_dir()
        assert path.resolve().is_relative_to(tmp_path.resolve())

    monkeypatch.setattr(source_module, "private_root", portable_custody)
    prepare = source_module.prepare_source(root, bundle,
        bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
        base_commit=base, target_ref="refs/heads/maintenance", purpose="channel-stored-reply")
    if refusal is not None:
        with pytest.raises(ContractViolation) as refused:
            await prepare
        assert str(refused.value) == refusal
        assert not (root / "source-pin.json").exists()
        return
    pin = await prepare
    assert pin.sources == {CHANNEL_TARGET_PATH: hashlib.sha256(BASE).hexdigest()}
    assert source_module.pinned_purpose(pin) == "channel-stored-reply"
    assert await source_module.inspect_source(root) == pin
    with pytest.raises(ContractViolation, match="names no fixed task"):
        await source_module.prepare_source(tmp_path / "other", bundle,
            bundle_sha256=pin.bundle_sha256, base_commit=base,
            target_ref="refs/heads/maintenance", purpose="caller-selected")
    # A pin naming neither fixed source set is refused by name.
    foreign = pin.model_copy(update={"sources": {"scripts/other.py": "0" * 64}})
    with pytest.raises(ContractViolation, match="omits the ordinary consumer"):
        source_module.pinned_purpose(foreign)


async def test_assembly_refuses_base_over_pack_budget_before_executor(tmp_path, monkeypatch):
    from constructicon.api import _maintenance_source as source_module

    bundle, base = await _bundle(tmp_path, BASE)
    root = tmp_path / "maintenance"
    monkeypatch.setattr(source_module, "private_root", lambda path: None)
    await source_module.prepare_source(root, bundle,
        bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
        base_commit=base, target_ref="refs/heads/maintenance", purpose="channel-stored-reply")
    monkeypatch.setattr(entry.codex_lane, "_launcher", lambda path: bare_launcher())
    monkeypatch.setattr(entry, "MAINTENANCE_PACK_LIMITS", PackLimits(expanded_bytes=1))

    async def forbidden_source_read(*args, **kwargs):
        raise AssertionError("an impossible capture reached gate or executor preparation")

    monkeypatch.setattr(entry, "git", forbidden_source_read)
    with pytest.raises(ContractViolation, match="expanded capture headroom"):
        await entry.assemble_maintenance(host=SimpleNamespace(launch_root=tmp_path),
                                         root=root, journal=None)


@pytest.mark.parametrize("prepared", ["channel-stored-reply", "plan-manifest-maintenance"])
async def test_assembly_refuses_authority_for_the_other_prepared_task_before_constructors(
    monkeypatch, tmp_path, prepared,
):
    from constructicon.api import _maintenance_source as source_module
    from tests.core.test_maintenance_authorization import authorization
    from tests.core.test_maintenance_channel_authorization import channel_authorization

    sources = ({CHANNEL_TARGET_PATH: "0" * 64} if prepared == "channel-stored-reply"
               else dict(source_module.SOURCE_HASHES))
    pin = source_module.SourcePin(bundle_sha256="0" * 64, base_commit="a" * 40,
        target_ref="refs/heads/maintenance", config_sha256="0" * 64, sources=sources)

    async def inspect(root):
        return pin

    def forbidden(*args, **kwargs):
        pytest.fail("a crossed authority reached an authority or workspace constructor")

    monkeypatch.setattr(entry, "inspect_source", inspect)
    monkeypatch.setattr(entry, "GitAuthority", forbidden)
    crossed = (authorization() if prepared == "channel-stored-reply"
               else channel_authorization())
    with pytest.raises(ContractViolation) as refused:
        await entry.assemble_maintenance(host=None, root=tmp_path, journal=None,
                                         authorization=crossed)
    assert str(refused.value) == (
        "maintenance authorization purpose differs from the prepared task")
