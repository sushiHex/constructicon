"""Hosted fake provider composition; never vendor/subscription qualification."""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.executor import ExecutorFailure, ExecutorSuccess, TaskSpec
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.native_operator import (
    NativeEgressIdentityV1,
    NativeOperatorExecutorProfileV3,
    NativeOperatorGrantPolicyV3,
    NativeOperatorIsolationProfileV3,
    NativeOperatorLaunchIdentityV3,
    NativeOperatorStoreIdentityV1,
)
from constructicon.core.qualification import QualificationAuthorization
from constructicon.substrate.executors import claude_provider as native
from constructicon.substrate.executors.claude_protocol import ClaudeAuthMode
from constructicon.substrate.executors.claude_read_worker import READ_WORKER_LIMITS
from constructicon.substrate.executors.egress import (
    EgressDestination,
    EgressPolicy,
    identity_digests,
)
from constructicon.substrate.executors.operator_store import BindingCheck
from tests.gitworld import SEED_CALC
from tests.substrate.test_claude_native_containment import claude_launcher as claude_launcher
from tests.substrate.test_claude_provider import mark
from tests.substrate.test_contained_workspace import context
from tests.substrate.test_contained_workspace import provider as provider
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence


@pytest.mark.parametrize("model", ["fixture-read", "fixture-zero"])
async def test_owned_provider_uses_real_native_worker_relay_and_guard_lifetimes(
    claude_launcher, launcher, provider, tmp_path, model,
):
    """All processes are the qualified harmless fixture, with no upstream dial."""
    import fcntl

    launch = replace(claude_launcher, claude=replace(claude_launcher.claude, model=model))
    worker = replace(launcher, limits=READ_WORKER_LIMITS)
    provider.launcher = launcher
    expected_base = provider.authority.resolve_ref(provider.target_ref)
    policy = EgressPolicy((EgressDestination("api.anthropic.com", 443, "1.1.1.1"),), 4)
    store_identity = NativeOperatorStoreIdentityV1(
        operator_binding_digest=mark("physical-fixture-binding"), layout_law_digest=mark("layout"),
        mount_lock_law_digest=mark("lock"), subscription_mode_adapter_revision=mark("mode"),
        store_conformance_revision=mark("fake-store-only"),
    )
    profile = NativeOperatorExecutorProfileV3(
        name="fake-claude-read-physical", posture=Posture.READ, structured_output=False,
        accepted_efforts=("low",), grant_policy=NativeOperatorGrantPolicyV3(
            tool_sets=(native.READ_CATALOG,), model_ids=(model,), environment_names=(),
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
        **native.identity_fields(launch, worker, workspace_provider=provider,
                                 workspace_capability_id="owned-workspace",
                                 workspace_revision="test", mode=ClaudeAuthMode.SUBSCRIPTION,
                                 expected_base=expected_base),
        profile=profile, store=store_identity,
        egress=NativeEgressIdentityV1(**identity_digests(policy),
                                     physical_conformance_revision=mark("fixture-relay")),
        authenticated_startup_conformance_revision=mark("fake-startup-only"),
        subscription_mode_conformance_revision=mark("fake-mode-only"),
    )
    grants = EffectiveGrants(
        posture=Posture.READ, model_selection=ModelSelection(kind="explicit", model=model),
        effort="low", allowed_tools=native.READ_CATALOG, env_allowlist=(),
        network="allow", timeout_s=120,
    )
    base = context(binding="executor")
    authorization = QualificationAuthorization(
        authorization_id="fake-physical-provider", stage="qualification-read",
        actor_id="static:fake", idempotency_key="physical-provider", scope=base.path.scope,
        binding="executor", source_graph_hash=mark("physical-graph"), capability_id="claude",
        revision=identity.revision, operator_binding_digest=store_identity.operator_binding_digest,
        journal=str(tmp_path / "unused-journal"), max_epoch=1,
        not_after=datetime.now(UTC) + timedelta(minutes=5), grants=grants,
        attempt_record=str(tmp_path / "attempt.json"),
    )
    ctx = replace(
        base, run_lease=base.run_lease.model_copy(update={"run_id": authorization.run_id}),
        binding=base.binding.model_copy(update={"capability_id": "claude",
                                               "revision": identity.revision,
                                               "effective_grants": grants}),
        check_control=lambda: None, source_graph_hash=authorization.source_graph_hash,
    )
    store_root = tmp_path / "harmless-store"
    store_root.mkdir()
    credential = store_root / ".credentials.json"
    credential.write_bytes(b"fake-initial\n")
    credential.chmod(0o600)
    lock = store_root / "retained.lock"
    lock.touch(mode=0o600)
    store_objects = [(path.stat().st_dev, path.stat().st_ino)
                     for path in (store_root, credential, lock)]
    held_fds = set()

    class HarmlessLockedStore:
        root = store_root
        sealed = store_identity

        def open_candidate(self):
            return os.open(lock, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)

        async def acquire_lock(self, fd, check_control, check_closure):
            try:
                while True:
                    check_control()
                    await check_closure()
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        held_fds.add(fd)
                        return SimpleNamespace(lock_fd=fd)
                    except BlockingIOError:
                        await asyncio.sleep(.01)
            except BaseException:
                os.close(fd)
                raise

        def check_held(self, held):
            assert held.lock_fd in held_fds
            assert [(path.stat().st_dev, path.stat().st_ino)
                    for path in (store_root, credential, lock)] == store_objects
            return BindingCheck(store_identity.operator_binding_digest)

        def open_credential(self, held):
            return os.open(credential, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)

        def close_held(self, held):
            held_fds.remove(held.lock_fd)
            os.close(held.lock_fd)

    workspace = await provider.acquire(replace(ctx, binding=context().binding))
    await workspace.materialize()
    # sun_path needs a short root independently of pytest's diagnostic path.
    with tempfile.TemporaryDirectory(prefix="m8-crp-") as directory:
        executor = native.ClaudeOperatorProvider(
            launcher=launch, worker_launcher=worker, profile=profile, identity=identity,
            binding_store=HarmlessLockedStore(), closure=provider.closure,
            workspace_provider=provider, workspace_capability_id="owned-workspace",
            workspace_revision="test", acquisition_root=Path(directory), egress=policy,
            mode=ClaudeAuthMode.SUBSCRIPTION, expected_base=expected_base,
            qualification=authorization,
        )
        acquired = await executor.acquire(ctx)
        try:
            await acquired.materialize()
            result = await acquired.resource.execute(
                TaskSpec(instruction="Read calc.py literally."),
                workspace=workspace.resource, grants=grants,
            )
            expected = ExecutorSuccess if model == "fixture-read" else ExecutorFailure
            assert isinstance(result, expected)
            if model == "fixture-read":
                assert result.raw_reply == SEED_CALC
            assert acquired.resource.initial_check == acquired.resource.terminal_check
            assert acquired.resource.initial_check is not None
            assert acquired.resource.relay_closed and acquired.resource.relay_denied == {}
            assert acquired.resource.relay_destinations == {}
        finally:
            await executor.close(acquired, "discard")
            await provider.close(workspace, "discard")
        assert not held_fds and not acquired.resource.paths.payload.exists()
    assert credential.read_bytes() == b"fake-initial\n"
    write_evidence(f"n6-claude-provider-{model}.json", {
        "schema_version": 1, "scope": "fake_physical_leased_read_provider",
        "production_available": False, "claude_qualified": False,
        "native_launch_revision": str(launch.revision),
        "worker_launch_revision": str(worker.revision),
        "outcome": result.status, "initial_terminal_binding_checked": True,
        "relay_joined": True, "relay_connections": 0,
        "callback_started": acquired.resource._callback_started,
        "callback_completed": acquired.resource._callback_completed,
        "scratch_disposed": True,
    })
