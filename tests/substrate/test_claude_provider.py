"""Portable leased lifecycle proof; no credential, vendor binary or network."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import (
    ExecutorError,
    ExecutorFailure,
    ExecutorSuccess,
    RateLimitInfo,
    TaskSpec,
    Usage,
)
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.identity import digest
from constructicon.core.native_operator import (
    NativeEgressIdentityV1,
    NativeOperatorExecutorProfileV3,
    NativeOperatorGrantPolicyV3,
    NativeOperatorIsolationProfileV3,
    NativeOperatorLaunchIdentityV3,
    NativeOperatorStoreIdentityV1,
)
from constructicon.core.qualification import QualificationAuthorization
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors import claude_provider as native
from constructicon.substrate.executors.claude_native import ClaudeNativeVendor
from constructicon.substrate.executors.claude_protocol import ClaudePlan
from constructicon.substrate.executors.claude_read_worker import READ_WORKER_LIMITS
from constructicon.substrate.executors.egress import (
    EgressDestination,
    EgressPolicy,
    identity_digests,
)
from constructicon.substrate.executors.linux import LinuxLauncher, ProcessLimits, ProcessResult
from constructicon.substrate.executors.operator_store import BindingCheck
from constructicon.substrate.git import contained
from constructicon.substrate.git.authority import _remove_tree
from tests.gitworld import push_to_main
from tests.substrate.test_claude_read import NATIVE_UUID, SESSION, Peer, lifecycle
from tests.substrate.test_contained_workspace import context, stale_row
from tests.substrate.test_contained_workspace import provider as provider


def mark(name):
    return digest("claude-provider-test", 1, name)


async def portable_dispose(closure, paths, *, disposition="discard", candidate_ref=None):
    """Only Linux directory/flock custody is substituted; closure stays real."""
    await finish_owned(asyncio.create_task(asyncio.to_thread(
        closure.commit, paths, disposition=disposition, candidate_ref=candidate_ref,
    )))
    async with native.acquisition_guard(paths):
        if not paths.payload.exists():
            return False
        await finish_owned(asyncio.create_task(asyncio.to_thread(_remove_tree, paths.payload)))
        return True


@pytest.fixture
async def assembled(provider, monkeypatch, tmp_path):
    expected_base = provider.authority.resolve_ref("refs/heads/main")
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "claude").write_bytes(b"harmless fixture, never executed")
    launcher = LinuxLauncher(
        runtime_root=tmp_path / "runtime", expected_runtime=mark("runtime"),
        bubblewrap=tmp_path / "bwrap", policy=tmp_path / "policy",
        expected_policy_sha256="0" * 64,
        claude=ClaudeNativeVendor(vendor, "model", "high", mark("vendor")),
    )
    worker = replace(launcher, claude=None, limits=READ_WORKER_LIMITS)
    provider.launcher = replace(worker, limits=ProcessLimits())
    policy = EgressPolicy((EgressDestination("api.anthropic.com", 443, "1.1.1.1"),), 4)
    store_identity = NativeOperatorStoreIdentityV1(
        operator_binding_digest=mark("binding"), layout_law_digest=mark("layout"),
        mount_lock_law_digest=mark("mount-lock"),
        subscription_mode_adapter_revision=mark("mode"), store_conformance_revision=mark("store"),
    )
    profile = NativeOperatorExecutorProfileV3(
        name="claude-read-test", posture=Posture.READ, structured_output=False,
        accepted_efforts=("high",), grant_policy=NativeOperatorGrantPolicyV3(
            tool_sets=(native.READ_CATALOG,), model_ids=("model",), environment_names=(),
            workspace_required=True, network_modes=("allow",),
            network_access="native_vendor_session_only", tool_path="mediated_callbacks_only",
        ), isolation=NativeOperatorIsolationProfileV3(
            filesystem="read_only_snapshot", process_tree_owned=True,
            environment_allowlisted=True, network_enforced=True, native_workspace="none",
            worker_network="none", credential_state="narrow_vendor_store_rw",
            zones="native_and_worker_separate",
        ), authentication="vendor_managed_subscription",
        account_assurance="operator_bound_vendor_identity_unverified",
        subscription_overage="operator_authorized",
    )
    identity = NativeOperatorLaunchIdentityV3(
        **native.identity_fields(launcher, worker, workspace_provider=provider,
                                 workspace_capability_id="owned-workspace",
                                 workspace_revision="test", selected_plan=ClaudePlan.PRO,
                                 expected_base=expected_base),
        profile=profile, store=store_identity,
        egress=NativeEgressIdentityV1(**identity_digests(policy),
                                     physical_conformance_revision=mark("egress")),
        authenticated_startup_conformance_revision=mark("startup"),
        subscription_mode_conformance_revision=mark("subscription"),
    )
    grants = EffectiveGrants(
        posture=Posture.READ, model_selection=ModelSelection(kind="explicit", model="model"),
        effort="high", allowed_tools=native.READ_CATALOG, env_allowlist=(),
        network="allow", timeout_s=30,
    )
    base = context(binding="executor")
    authorization = QualificationAuthorization(
        authorization_id="claude-read-one", stage="qualification-read",
        actor_id="static:test", idempotency_key="claude-read-one", scope=base.path.scope,
        binding="executor", source_graph_hash=mark("graph"), capability_id="claude",
        revision=identity.revision, operator_binding_digest=store_identity.operator_binding_digest,
        journal=str(tmp_path / "journal"), max_epoch=1,
        not_after=datetime.now(UTC) + timedelta(minutes=5), grants=grants,
        attempt_record=str(tmp_path / "attempt.json"),
    )
    state = SimpleNamespace(guards=0, locks=0, probes=[], workers=[], exchanges=[],
                            binding=True, denied={}, closed=False, block=None,
                            native_joined=False, peer=Peer(), probe_hook=None,
                            break_terminal_binding=False)

    @asynccontextmanager
    async def guard(paths):
        state.guards += 1
        try:
            yield 77
        finally:
            state.guards -= 1

    class Store:
        root = tmp_path / "binding"
        sealed = store_identity

        def open_candidate(self):
            state.locks += 1
            return object()

        async def acquire_lock(self, candidate, check_control, check_closure):
            check_control()
            await check_closure()
            return SimpleNamespace(lock_fd=88)

        def check_held(self, held):
            return BindingCheck(mark("binding")) if state.binding else None

        def open_credential(self, held):
            return os.open(os.devnull, os.O_RDONLY)

        def close_held(self, held):
            state.locks -= 1

    class Relay:
        def __init__(self, policy, directory, deadline, check_control):
            self.closed = False
            self.denied = state.denied
            self.destinations = {}

        async def __aenter__(self):
            return None

        async def __aexit__(self, *args):
            self.closed = True
            state.closed = True

    async def probe(self, *, deadline=None):
        state.probes.append(self)
        if state.probe_hook is not None:
            state.probe_hook()
        await asyncio.sleep(0)

    async def run(self, command, **kwargs):
        assert self is worker and state.locks == 1 and state.guards == 2
        assert kwargs["posture"] is Posture.READ and kwargs["input_kind"] == "task"
        assert kwargs["stdin"] == b""
        state.workers.append((command, kwargs))
        if state.block is not None:
            state.block.set()
            await asyncio.Event().wait()
        return ProcessResult(0, b"file text", b"", .01, payload_returncode=0)

    async def exchange(self, command, **kwargs):
        assert self is launcher and kwargs["workspace"] is None
        assert state.locks == 1 and state.guards == 1
        assert kwargs["guard_fds"] == (77, 88)
        assert kwargs["native_store"].lock_fd == 88
        state.exchanges.append(kwargs)
        kwargs["native_store"].before_spawn()
        try:
            await kwargs["conversation"](state.peer)
            return ProcessResult(0, b"", b"", .01, payload_returncode=0)
        finally:
            state.native_joined = True
            if state.break_terminal_binding:
                state.binding = False

    monkeypatch.setattr(native, "acquisition_guard", guard)
    monkeypatch.setattr(contained, "acquisition_guard", guard)
    monkeypatch.setattr(native, "EgressRelay", Relay)
    monkeypatch.setattr(native, "dispose_acquisition", portable_dispose)
    monkeypatch.setattr(contained, "dispose_acquisition", portable_dispose)
    # This portable double binds no UNIX socket. The production path bound is
    # independently retained; platform temp paths can exceed Linux sun_path.
    monkeypatch.setattr(native, "MAX_SOCKET_PATH_BYTES", 4096)
    monkeypatch.setattr(LinuxLauncher, "probe", probe)
    monkeypatch.setattr(LinuxLauncher, "run", run)
    monkeypatch.setattr(LinuxLauncher, "exchange", exchange)
    kwargs = dict(launcher=launcher, worker_launcher=worker, profile=profile, identity=identity,
                  binding_store=Store(), closure=provider.closure, workspace_provider=provider,
                  workspace_capability_id="owned-workspace", workspace_revision="test",
                  acquisition_root=tmp_path / "native", egress=policy,
                  selected_plan=ClaudePlan.PRO, expected_base=expected_base,
                  qualification=authorization)
    executor = native.ClaudeOperatorProvider(**kwargs)
    lease = base.run_lease.model_copy(update={"run_id": authorization.run_id})
    ctx = replace(base, run_lease=lease,
                  binding=base.binding.model_copy(update={"capability_id": "claude",
                                                         "revision": identity.revision,
                                                         "effective_grants": grants}),
                  check_control=lambda: None, source_graph_hash=authorization.source_graph_hash)
    wsctx = replace(ctx, binding=context().binding)
    workspace = await provider.acquire(wsctx)
    await workspace.materialize()
    return SimpleNamespace(executor=executor, context=ctx, grants=grants, workspace=workspace,
                           state=state, kwargs=kwargs)


async def acquire_ready(assembled):
    acquired = await assembled.executor.acquire(assembled.context)
    await acquired.materialize()
    return acquired


async def execute(assembled, acquired):
    return await acquired.resource.execute(TaskSpec(instruction="read the file"),
                                           workspace=assembled.workspace.resource,
                                           grants=assembled.grants)


def record(assembled):
    return json.loads(assembled.executor.qualification.attempt_record and
                      native.Path(assembled.executor.qualification.attempt_record).read_text())


async def test_accepting_leased_path_is_inert_then_runs_one_native_and_one_owned_read(assembled):
    a = assembled
    assert a.executor.unavailable_reasons
    assert a.executor.authorizes_admission(source_graph_hash=a.context.source_graph_hash,
                                           capability_id="claude")
    acquired = await a.executor.acquire(a.context)
    assert not a.state.exchanges and not a.state.probes and a.state.locks == 0
    assert record(a)["phase"] == "acquired"
    await acquired.materialize()
    assert len(a.state.probes) == 2 and a.state.guards == a.state.locks == 1
    result = await execute(a, acquired)
    assert isinstance(result, ExecutorSuccess) and result.raw_reply == "task output"
    assert result.served_model is None
    assert len(a.state.workers) == len(a.state.exchanges) == 1
    assert a.state.native_joined and a.state.closed
    saved = record(a)
    assert saved["dispatch"] == "completed"
    assert saved["facts"]["callback_started"] == saved["facts"]["callback_completed"] == 1
    assert saved["facts"]["initial_binding_checked"] is True
    assert saved["facts"]["terminal_binding_checked"] is True
    acquired.resource.paths.payload.mkdir(parents=True)
    (acquired.resource.paths.payload / "transient").write_text("fixture scratch")
    await a.executor.close(acquired, "release")
    assert a.state.guards == a.state.locks == 0
    assert a.executor.closure.is_closed(acquired.resource.paths)
    assert not acquired.resource.paths.payload.exists()
    with pytest.raises(ContractViolation):
        await a.executor.acquire(a.context)


async def test_default_unavailability_has_no_admission_or_acquisition_exception(assembled):
    a = assembled
    executor = native.ClaudeOperatorProvider(**{**a.kwargs, "qualification": None})
    assert executor.unavailable_reasons
    assert not executor.authorizes_admission(source_graph_hash=a.context.source_graph_hash,
                                             capability_id="claude")
    with pytest.raises(ContractViolation):
        await executor.acquire(a.context)
    assert not a.state.probes and not a.state.exchanges and a.state.locks == 0


@pytest.mark.parametrize("change", ["run", "epoch", "graph", "capability", "grants", "revision"])
async def test_authorization_refuses_other_invocations_before_reservation(assembled, change):
    a = assembled
    ctx = a.context
    if change == "run":
        ctx = replace(ctx, run_lease=ctx.run_lease.model_copy(update={"run_id": "other"}))
    elif change == "epoch":
        ctx = replace(ctx, run_lease=ctx.run_lease.model_copy(update={"epoch": 2}))
    elif change == "graph":
        ctx = replace(ctx, source_graph_hash=mark("other"))
    else:
        field = {"capability": "capability_id", "grants": "effective_grants",
                 "revision": "revision"}[change]
        value = a.grants.model_copy(update={"timeout_s": 1}) if change == "grants" else "other"
        ctx = replace(ctx, binding=ctx.binding.model_copy(update={field: value}))
    with pytest.raises(ContractViolation):
        await a.executor.acquire(ctx)
    assert not native.Path(a.executor.qualification.attempt_record).exists()


@pytest.mark.parametrize("defect", ["binding", "closure", "control"])
async def test_materialization_resume_rechecks_before_readiness(assembled, defect):
    a = assembled
    acquired = await a.executor.acquire(a.context)

    def hook():
        if defect == "binding":
            a.state.binding = False
        elif defect == "closure":
            a.executor.closure.commit(acquired.resource.paths)
        else:
            acquired.resource.closed = True

    a.state.probe_hook = hook
    with pytest.raises((ContractViolation, BaseExceptionGroup)):
        await acquired.materialize()
    assert acquired.resource.ready is False
    assert not a.state.exchanges and record(a)["dispatch"] == "not dispatched"
    a.state.binding = True
    await a.executor.close(acquired, "discard")
    assert a.state.guards == a.state.locks == 0


@pytest.mark.parametrize("defect", ["no-callback", "relay-denial", "terminal-error",
                                   "user-write", "post-mode"])
async def test_native_success_cannot_replace_callback_relay_or_protocol_proof(assembled, defect):
    a = assembled
    if defect == "no-callback":
        a.state.peer.callback = False
    elif defect == "relay-denial":
        a.state.denied["denied:fixture"] = 1
    else:
        a.state.peer.defect = defect
    acquired = await acquire_ready(a)
    result = await execute(a, acquired)
    assert isinstance(result, ExecutorFailure)
    assert a.state.native_joined and a.state.closed
    assert record(a)["dispatch"] == "possibly dispatched"
    await a.executor.close(acquired, "discard")
    assert a.state.guards == a.state.locks == 0


async def test_completed_lifecycle_and_result_cannot_replace_provider_callback_proof(assembled):
    class CompletedPeer(Peer):
        def terminal(self):
            self.emit(lifecycle(self))
            super().terminal()

    a = assembled
    a.state.peer = CompletedPeer(callback=False)
    acquired = await acquire_ready(a)
    result = await execute(a, acquired)
    assert isinstance(result, ExecutorFailure)
    assert a.state.native_joined and a.state.closed
    assert a.state.peer.callback_replies == 0 and a.state.workers == []
    assert record(a)["dispatch"] == "possibly dispatched"
    await a.executor.close(acquired, "discard")
    assert a.state.guards == a.state.locks == 0


async def test_terminal_refusal_retains_emitted_telemetry_without_native_text(assembled):
    a = assembled

    class RatePeer(Peer):
        def terminal(self):
            self.emit({"type": "rate_limit_event", "uuid": NATIVE_UUID, "session_id": SESSION,
                       "rate_limit_info": {"status": "allowed", "isUsingOverage": False}})
            super().terminal()

    a.state.peer = RatePeer(callback=False)
    acquired = await acquire_ready(a)
    result = await execute(a, acquired)
    assert isinstance(result, ExecutorFailure)
    assert result.usage == Usage(input_tokens=1, output_tokens=1)
    assert result.rate_limit == RateLimitInfo(is_using_overage=False, detail={"status": "allowed"})
    assert result.elapsed_s > 0 and result.requested_model == "model"
    assert result.served_model is None and result.raw_reply is None and result.output is None
    await a.executor.close(acquired, "discard")


@pytest.mark.parametrize("detail", ["PRIVATE-ACCOUNT-CANARY",
                                    "Claude READ refused [known_refusal=PRIVATE-CANARY]"])
async def test_provider_does_not_forward_unknown_driver_detail(assembled, monkeypatch, detail):
    async def failed(*args, **kwargs):
        return ExecutorFailure(error=ExecutorError(kind="exit", detail=detail))

    monkeypatch.setattr(native.claude_read, "run_read_transaction", failed)
    acquired = await acquire_ready(assembled)
    outcome = await execute(assembled, acquired)
    assert isinstance(outcome, ExecutorFailure)
    assert outcome.error.detail == "Claude READ refused"
    assert "PRIVATE" not in outcome.model_dump_json()
    await assembled.executor.close(acquired, "discard")
    assert assembled.state.guards == assembled.state.locks == 0


@pytest.mark.parametrize("change", ["control", "expiry"])
async def test_intent_is_durable_before_user_write_and_expiry_rechecked_after_durability(
    assembled, monkeypatch, change,
):
    a = assembled
    acquired = await acquire_ready(a)
    original = acquired.resource.attempt.intend
    current = [a.executor.qualification.not_after - timedelta(seconds=1)]
    if change == "expiry":
        monkeypatch.setattr(native, "datetime", SimpleNamespace(now=lambda tz: current[0]))

    def intend():
        assert not a.state.peer.users
        result = original()
        assert record(a)["phase"] == "intent"
        if change == "control":
            acquired.resource.closed = True  # ownership changes while fsync blocks
        else:
            current[0] = a.executor.qualification.not_after
        return result

    monkeypatch.setattr(acquired.resource.attempt, "intend", intend)
    with pytest.raises(ContractViolation):
        await execute(a, acquired)
    assert not a.state.peer.users and not a.state.workers
    assert record(a)["dispatch"] == "not dispatched"
    await a.executor.close(acquired, "discard")


async def test_cancellation_joins_worker_native_and_relay_before_releasing_guards(assembled):
    a = assembled
    acquired = await acquire_ready(a)
    a.state.block = asyncio.Event()
    task = asyncio.create_task(execute(a, acquired))
    await a.state.block.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert a.state.native_joined and a.state.closed and a.state.guards == 1
    assert record(a)["dispatch"] == "possibly dispatched"
    await a.executor.close(acquired, "discard")
    assert a.state.guards == a.state.locks == 0


async def test_inert_close_settles_attempt_without_physical_work(assembled):
    a = assembled
    acquired = await a.executor.acquire(a.context)
    await a.executor.close(acquired, "discard")
    assert not a.state.probes and not a.state.exchanges and a.state.locks == 0
    assert record(a)["dispatch"] == "not dispatched"


async def test_recovery_validates_all_rows_before_fencing_then_never_dispatches(
    assembled, monkeypatch,
):
    a = assembled
    acquired = await a.executor.acquire(a.context)
    stale = stale_row(acquired, a.context)
    recovered = replace(a.context, run_lease=a.context.run_lease.model_copy(update={"epoch": 2}))
    calls = []

    async def dispose(closure, paths, *, disposition):
        calls.append(paths)

    monkeypatch.setattr(native, "dispose_acquisition", dispose)
    bad = replace(stale, lease=stale.lease.model_copy(update={"resource_ref": "{}"}))
    with pytest.raises(ContractViolation):
        await a.executor.reconcile(recovered, (stale, bad))
    assert calls == []
    result = await a.executor.reconcile(recovered, (stale,))
    assert result.reaped == (acquired.resource_ref,) and len(calls) == 1
    assert not a.state.exchanges


async def test_workspace_must_own_same_invocation_and_exact_admitted_binding(assembled):
    a = assembled
    acquired = await acquire_ready(a)
    original = a.workspace.resource.context
    object.__setattr__(a.workspace.resource, "context", replace(
        original, binding=original.binding.model_copy(update={"revision": "other"}),
    ))
    with pytest.raises(ContractViolation):
        await execute(a, acquired)
    assert not a.state.exchanges and not a.state.workers
    await a.executor.close(acquired, "discard")


async def test_terminal_binding_failure_preserves_primary_cancellation(assembled):
    a = assembled
    acquired = await acquire_ready(a)
    a.state.block = asyncio.Event()
    a.state.break_terminal_binding = True
    task = asyncio.create_task(execute(a, acquired))
    await a.state.block.wait()
    task.cancel()
    with pytest.raises(BaseExceptionGroup) as caught:
        await task
    cancellation, remainder = caught.value.split(asyncio.CancelledError)
    assert cancellation is not None and remainder is not None
    assert a.state.native_joined and a.state.closed
    assert record(a)["dispatch"] == "possibly dispatched"
    a.state.binding = True
    await a.executor.close(acquired, "discard")
    assert a.state.guards == a.state.locks == 0


async def test_completed_outcome_must_be_durable_before_success_is_published(
    assembled, monkeypatch,
):
    a = assembled
    acquired = await acquire_ready(a)

    def complete(dispatch, facts):
        assert dispatch == "completed" and facts["terminal_binding_checked"]
        raise OSError("private directory fsync failure")

    monkeypatch.setattr(acquired.resource.attempt, "complete", complete)
    with pytest.raises(ContractViolation, match="retain its outcome"):
        await execute(a, acquired)
    assert record(a)["phase"] == "intent"
    assert a.state.native_joined and a.state.closed
    await a.executor.close(acquired, "discard")


async def test_expected_fixture_commit_is_bound_and_ref_move_refuses_before_attempt(assembled):
    a = assembled
    push_to_main(a.executor.workspace_provider.authority._repo, {"moved": "fixture"}, "move")
    with pytest.raises(ContractViolation, match="target moved"):
        await a.executor.acquire(a.context)
    assert not native.Path(a.executor.qualification.attempt_record).exists()
    assert not a.state.exchanges


async def test_close_during_callback_joins_owned_work_before_releasing_custody(assembled):
    a = assembled
    acquired = await acquire_ready(a)
    a.state.block = asyncio.Event()
    task = asyncio.create_task(execute(a, acquired))
    await a.state.block.wait()
    await a.executor.close(acquired, "discard")
    with pytest.raises(asyncio.CancelledError):
        await task
    assert a.state.native_joined and a.state.closed
    assert a.state.guards == a.state.locks == 0
    assert record(a)["dispatch"] == "possibly dispatched"
    await a.executor.close(acquired, "discard")


async def test_post_exchange_resume_rechecks_closure_before_outcome_and_attempt_success(
    assembled, monkeypatch,
):
    a = assembled
    acquired = await acquire_ready(a)
    original = acquired.resource._run

    async def close_after_exchange(task, worker):
        result = await original(task, worker)
        assert isinstance(result, ExecutorSuccess)
        a.executor.closure.commit(acquired.resource.paths)
        return result

    monkeypatch.setattr(acquired.resource, "_run", close_after_exchange)
    with pytest.raises(ContractViolation):
        await execute(a, acquired)
    assert record(a)["dispatch"] == "possibly dispatched"
    await a.executor.close(acquired, "discard")
