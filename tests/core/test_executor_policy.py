"""M8's complete policy and content identity; no real backend proof is implied."""

from __future__ import annotations

import inspect
import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

import constructicon.core.executor as executor_contract
from constructicon.api.system import DEFAULT_ROOT_GRANTS
from constructicon.core.executor import (
    EXECUTOR_LAW_REVISION,
    ExecutorGrantPolicy,
    ExecutorLaunchIdentity,
    ExecutorProfile,
    ProviderRouteIdentity,
    TaskSpec,
)
from constructicon.core.grants import ModelSelection, Posture
from constructicon.core.identity import canonical_json, digest
from constructicon.substrate.executors.fake import FakeExecutor
from tests.executorworld import FakeExecutorProvider, launch_identity, policy

LEGACY_PROFILE = (
    '{"name":"fake","structured_output":true,"postures":["read"],'
    '"isolation":{"filesystem":"none","process_tree_owned":true,'
    '"environment_allowlisted":true,"network_enforced":true},"accepted_efforts":[]}'
)


def test_legacy_profile_keeps_its_exact_bytes_and_incompleteness() -> None:
    executor = FakeExecutor({})
    assert executor.profile.model_dump_json() == LEGACY_PROFILE
    assert ExecutorProfile.model_validate_json(LEGACY_PROFILE).model_dump_json() == LEGACY_PROFILE
    assert "grant_policy" not in executor.profile.model_dump()
    assert executor.profile.grant_faults(DEFAULT_ROOT_GRANTS) == (
        "executor profile has no complete grant policy",
    )
    unusual = DEFAULT_ROOT_GRANTS.model_copy(
        update={
            "allowed_tools": ("anything",),
            "network": "allow",
            "effort": "unrecorded",
        }
    )
    assert executor.validate_grants(unusual) == ()  # Explicit legacy scope, not new completeness.
    assert executor.validate_grants(unusual.model_copy(update={"posture": Posture.WRITE})) == (
        "fake executor offers no 'write' posture",
    )


def test_policy_inventory_is_an_exact_normalized_set() -> None:
    raw = policy().model_dump(mode="json")
    raw.update(
        tool_sets=[["search", "read", "read"], [], ["read", "search"]],
        network_modes=["none", "none"],
        environment_names=["B", "A", "A"],
    )
    normalized = ExecutorGrantPolicy.model_validate(raw)
    assert normalized.tool_sets == ((), ("read", "search"))
    assert normalized.environment_names == ("A", "B")
    assert normalized.network_modes == ("none",)
    assert ExecutorGrantPolicy.model_validate_json(normalized.model_dump_json()) == normalized
    for field, value in (
        ("tool_sets", []),
        ("tool_sets", [[""]]),
        ("network_modes", []),
        ("network_modes", ["inherit"]),
        ("environment_names", [""]),
    ):
        with pytest.raises(ValidationError):
            ExecutorGrantPolicy.model_validate({**raw, field: value})
    with pytest.raises(ValidationError):
        ExecutorGrantPolicy.model_validate({**raw, "new_hidden_policy": True})


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"posture": Posture.WRITE}, "does not offer posture"),
        ({"allowed_tools": ("search",)}, "exact tool set"),
        ({"allowed_tools": ("Bash(git *)",)}, "exact tool set"),
        ({"allowed_tools": ("*",)}, "exact tool set"),
        ({"network": "allow"}, "network mode"),
        ({"env_allowlist": ("UNDECLARED",)}, "environment"),
        ({"effort": "unknown"}, "effort"),
        ({"model_selection": ModelSelection(kind="explicit")}, "non-empty model"),
        ({"model_selection": ModelSelection(kind="explicit", model=" ")}, "non-empty model"),
    ],
)
def test_adapter_and_profile_share_every_grant_refusal(change: dict, message: str) -> None:
    executor = FakeExecutor({}, grant_policy=policy())
    grants = DEFAULT_ROOT_GRANTS.model_copy(update=change)
    faults = executor.validate_grants(grants)
    assert faults == executor.profile.grant_faults(grants)
    assert any(message in fault for fault in faults)


@pytest.mark.parametrize(
    "field", ["process_tree_owned", "environment_allowlisted", "network_enforced", "filesystem"]
)
def test_complete_policy_requires_every_physical_declaration(field: str) -> None:
    profile = FakeExecutorProvider().identity.profile
    changed = profile.model_copy(
        update={
            "isolation": profile.isolation.model_copy(
                update={
                    field: "workspace_only" if field == "filesystem" else False,
                }
            )
        }
    )
    assert changed.grant_faults(DEFAULT_ROOT_GRANTS)


def test_narrowing_does_not_invent_an_unsupported_empty_set() -> None:
    profile = FakeExecutorProvider().identity.profile
    nonempty = profile.model_copy(
        update={"grant_policy": policy().model_copy(update={"tool_sets": (("read", "search"),)})}
    )
    assert nonempty.grant_faults(DEFAULT_ROOT_GRANTS)
    grants = DEFAULT_ROOT_GRANTS.model_copy(update={"allowed_tools": ("search", "read", "read")})
    assert nonempty.grant_faults(grants) == ()
    profile = profile.model_copy(update={"accepted_efforts": frozenset({"low", "high"})})
    assert (
        profile.grant_faults(
            DEFAULT_ROOT_GRANTS.model_copy(
                update={
                    "effort": "high",
                    "model_selection": ModelSelection(kind="explicit", model="exact-id"),
                    "env_allowlist": ("SAFE_TEST",),
                }
            )
        )
        == ()
    )


@pytest.mark.parametrize(
    "field",
    [
        "executable_digest",
        "runtime_digest",
        "adapter_revision",
        "decoder_revision",
        "isolation_revision",
        "configuration_digest",
        "limits_digest",
    ],
)
def test_each_launch_fact_changes_revision(field: str) -> None:
    identity = FakeExecutorProvider().identity
    changed = identity.model_copy(update={field: digest("changed", 1, field)})
    assert changed.revision != identity.revision


def test_profile_and_gateway_conformance_are_identity_not_aliases() -> None:
    identity = FakeExecutorProvider().identity
    route = ProviderRouteIdentity(
        **{
            key: digest("fake-route", 1, key)
            for key in (
                "build_digest",
                "configuration_digest",
                "policy_digest",
                "conformance_revision",
            )
        }
    )
    profile = identity.profile.model_copy(
        update={
            "grant_policy": policy().model_copy(update={"network_access": "provider_route_only"})
        }
    )
    routed = ExecutorLaunchIdentity.model_validate(
        {
            **identity.model_dump(mode="json"),
            "profile": profile,
            "provider_route": route,
        }
    )
    for field in type(route).model_fields:
        changed = routed.model_copy(
            update={"provider_route": route.model_copy(update={field: digest("changed", 1, field)})}
        )
        assert changed.revision != routed.revision
    assert routed.revision != identity.revision
    with pytest.raises(ValidationError):
        ExecutorLaunchIdentity.model_validate({**identity.model_dump(), "profile": profile})
    with pytest.raises(ValidationError):
        launch_identity(FakeExecutor({}).profile)
    with pytest.raises(ValidationError):
        launch_identity(identity.profile.model_copy(update={"postures": frozenset(Posture)}))
    with pytest.raises(ValidationError):
        ExecutorLaunchIdentity.model_validate(
            {
                **identity.model_dump(),
                "host_path": "not-identity",
            }
        )
    with pytest.raises(ValueError, match="no provider route"):
        FakeExecutor({}, grant_policy=profile.grant_policy)


def test_complete_identity_is_stable_across_process_hash_seeds() -> None:
    script = (
        "from tests.executorworld import FakeExecutorProvider, launch_identity; "
        "p=FakeExecutorProvider().identity.profile.model_copy(update={"
        "'accepted_efforts':frozenset({'high','low','medium'})}); "
        "print(launch_identity(p).revision)"
    )
    revisions = [
        subprocess.run(
            [sys.executable, "-c", script],
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()
        for seed in ("1", "2", "3")
    ]
    assert len(set(revisions)) == 1
    assert revisions[0].startswith("sha256:")


def test_shared_law_is_bound_without_a_factory_remembering_to_stamp_it(monkeypatch) -> None:
    identity = FakeExecutorProvider().identity
    original = identity.revision
    assert original == str(
        digest(
            "executor-launch",
            1,
            {
                "law": EXECUTOR_LAW_REVISION,
                "identity": identity.model_dump(mode="json"),
            },
        )
    )
    monkeypatch.setattr("constructicon.core.executor.EXECUTOR_LAW_REVISION", digest("other", 1, {}))
    assert identity.revision != original


def test_shared_law_inventory_is_complete() -> None:
    names = (
        "_names",
        "Posture",
        "ModelSelection",
        "EffectiveGrants",
        "IsolationProfile",
        "ExecutorGrantPolicy",
        "ExecutorProfile",
        "ProviderRouteIdentity",
        "ExecutorLaunchIdentity",
    )
    assert (
        digest(
            "executor-law",
            1,
            {name: inspect.getsource(getattr(executor_contract, name)) for name in names},
        )
        == EXECUTOR_LAW_REVISION
    )


@pytest.mark.parametrize(
    "field",
    [
        "name",
        "structured_output",
        "postures",
        "isolation",
        "accepted_efforts",
        "grant_policy",
    ],
)
def test_every_profile_field_participates_in_launch_identity(field: str) -> None:
    original = FakeExecutorProvider().identity
    values = {
        "name": "other-fake",
        "structured_output": False,
        "postures": frozenset({Posture.WRITE}),
        "isolation": original.profile.isolation.model_copy(update={"network_enforced": False}),
        "accepted_efforts": frozenset({"low"}),
        "grant_policy": policy().model_copy(update={"workspace_required": True}),
    }
    changed = original.model_copy(
        update={
            "profile": original.profile.model_copy(update={field: values[field]}),
        }
    )
    assert changed.revision != original.revision


async def test_complete_fake_enforces_workspace_presence_and_salvages_legacy() -> None:
    required = policy().model_copy(update={"workspace_required": True})
    executor = FakeExecutor({"test": "ok"}, grant_policy=required)
    result = await executor.execute(
        TaskSpec(instruction="test"), workspace=None, grants=DEFAULT_ROOT_GRANTS
    )
    assert result.status == "failure" and "WorkspaceView" in result.error.detail
    legacy = FakeExecutor({"test": "ok"})
    assert (
        await legacy.execute(
            TaskSpec(instruction="test"), workspace=None, grants=DEFAULT_ROOT_GRANTS
        )
    ).status == "success"
    assert "grant_policy" not in canonical_json(legacy.profile)
