"""ADR 0021 operator-mode contracts (schema 3) and the two boundary decoders.

This is a second, explicitly versioned executor law standing beside the frozen
gateway v1 closure in :mod:`constructicon.core.executor`. Nothing here reads,
rewrites or relaxes v1: the decoders dispatch on the raw object's declared
``schema_version`` outside both closures — absence selects the historical
unversioned profile, exact 3 selects these records, and every other value
refuses. Schema 2 stays reserved for ADR 0020's principal-attested mode, which
this module deliberately does not implement.

Account assurance here is ``operator_bound_vendor_identity_unverified``: the
binding names an operator key, a maintenance generation and a store instance,
never a verified vendor principal. No field carries a path, PID, nonce, raw
key, principal, email, tenant, workspace id or store content hash.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, TypeAdapter, field_validator

from constructicon.core.executor import (
    ExecutorLaunchIdentity,
    ExecutorProfile,
    _names,
)
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.identity import Digest, digest, parse_json_value

NATIVE_OPERATOR_SCHEMA_VERSION = 3
"""ADR 0021's version for the native operator policy, profile and launch identity.

Version 2 is reserved for ADR 0020's proposed principal-attested mode so two
incompatible proposals can never share one serialized meaning.
"""


def operator_binding_digest(
    operator_key: str,
    maintenance_generation: int,
    store_instance_id: str,
) -> Digest:
    """The secret-free label of one prepared operator store binding.

    Not a credential, an account tuple or a store content hash: the stable
    identity of *which* binding a store instance was prepared under, so a
    maintenance generation cannot silently move beneath a published identity.
    """

    if not operator_key.strip():
        raise ValueError("an operator binding requires a non-blank operator key")
    if not store_instance_id.strip():
        raise ValueError("an operator binding requires a non-blank store instance id")
    if maintenance_generation < 1:
        raise ValueError("a maintenance generation starts at 1")
    return digest(
        "native-operator-binding",
        1,
        {
            "key": operator_key,
            "generation": maintenance_generation,
            "store_instance": store_instance_id,
        },
    )


class NativeOperatorGrantPolicyV3(BaseModel):
    """A complete finite native-mode inventory; every fixed literal is stated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[3] = 3
    tool_sets: tuple[tuple[str, ...], ...]
    model_ids: tuple[str, ...]
    environment_names: tuple[str, ...]
    workspace_required: bool
    network_modes: tuple[Literal["allow"], ...]
    network_access: Literal["native_vendor_session_only"]
    tool_path: Literal["mediated_callbacks_only"]

    @field_validator("tool_sets")
    @classmethod
    def _tool_inventory(cls, values: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
        if not values:
            raise ValueError("declare at least one supported tool set, including () if supported")
        return tuple(sorted({_names(value) for value in values}))

    @field_validator("model_ids")
    @classmethod
    def _inventory(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("declare the finite explicit model inventory; there is no default")
        return _names(values)

    @field_validator("environment_names")
    @classmethod
    def _environment(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _names(values)

    @field_validator("network_modes")
    @classmethod
    def _networks(cls, values: tuple[Literal["allow"], ...]) -> tuple[Literal["allow"], ...]:
        if values != ("allow",):
            raise ValueError("native vendor sessions offer exactly the ('allow',) network mode")
        return values


class NativeOperatorIsolationProfileV3(BaseModel):
    """What the native zone and the worker zone each mechanically enforce."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[3] = 3
    filesystem: Literal["none", "workspace_only", "read_only_snapshot"]
    process_tree_owned: bool
    environment_allowlisted: bool
    network_enforced: bool
    native_workspace: Literal["none"]
    worker_network: Literal["none"]
    credential_state: Literal["narrow_vendor_store_rw"]
    zones: Literal["native_and_worker_separate"]

    def satisfies(self, posture: Posture) -> bool:
        """The v1 posture rule restated: the v1 body is frozen law, not a base."""

        if not (self.process_tree_owned and self.environment_allowlisted):
            return False
        if posture is Posture.READ:
            return self.filesystem in ("none", "read_only_snapshot")
        return self.filesystem == "workspace_only"


class NativeOperatorExecutorProfileV3(BaseModel):
    """One posture, one finite inventory, one stated account assurance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[3] = 3
    name: str
    posture: Posture
    structured_output: bool
    accepted_efforts: tuple[str, ...]
    grant_policy: NativeOperatorGrantPolicyV3
    isolation: NativeOperatorIsolationProfileV3
    authentication: Literal["vendor_managed_subscription"]
    account_assurance: Literal["operator_bound_vendor_identity_unverified"]
    subscription_overage: Literal["forbidden", "operator_authorized"]

    @field_validator("name")
    @classmethod
    def _named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a native operator profile requires a non-blank name")
        return value

    @field_validator("accepted_efforts")
    @classmethod
    def _efforts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("declare the finite accepted efforts; an absent effort is refused")
        return _names(values)

    def grant_faults(self, grants: EffectiveGrants) -> tuple[str, ...]:
        """The one pure predicate; admission and adapters call exactly this.

        There is no closest match, no narrowing and no boolean bypass. Workspace
        presence is a task-time fact and stays in the adapter's ``execute``.
        """

        policy = self.grant_policy
        faults: list[str] = []
        if grants.posture is not self.posture:
            faults.append(
                f"executor offers only posture {self.posture.value!r}, "
                f"not {grants.posture.value!r}"
            )
        elif not self.isolation.satisfies(grants.posture):
            faults.append(f"executor cannot mechanically enforce posture {grants.posture.value!r}")
        if tuple(sorted(set(grants.allowed_tools))) not in policy.tool_sets:
            faults.append(f"executor does not offer exact tool set {grants.allowed_tools!r}")
        if grants.network != "allow":
            faults.append(
                "network 'none' excludes model networking; this profile requires 'allow'"
            )
        if not self.isolation.network_enforced:
            faults.append("executor cannot mechanically enforce network grants")
        unsupported = sorted(set(grants.env_allowlist) - set(policy.environment_names))
        if unsupported:
            faults.append(f"executor cannot inherit environment names {unsupported!r}")
        if grants.effort is None or grants.effort not in self.accepted_efforts:
            # The native adapter fixes effort from the sealed manifest, so an
            # absent effort is a backend default and is refused, never inferred.
            faults.append(
                "executor requires an explicit listed effort; offered: "
                f"{list(self.accepted_efforts)!r}"
            )
        selection = grants.model_selection
        if selection.kind != "explicit" or not (selection.model or "").strip():
            faults.append("executor requires an explicit model from its finite inventory")
        elif selection.model not in policy.model_ids:
            faults.append(
                f"executor does not offer model {selection.model!r}; "
                f"inventory: {list(policy.model_ids)!r}"
            )
        return tuple(faults)


class NativeEgressIdentityV1(BaseModel):
    """The fixed enforcement facts of one egress boundary; no endpoint locator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    enforcement_build_digest: Digest
    destination_policy_digest: Digest
    resolver_policy_digest: Digest
    tls_assumptions_digest: Digest
    configuration_digest: Digest
    physical_conformance_revision: Digest


class NativeOperatorStoreIdentityV1(BaseModel):
    """Which prepared store law a launch is bound to; never its content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    operator_binding_digest: Digest
    layout_law_digest: Digest
    mount_lock_law_digest: Digest
    subscription_mode_adapter_revision: Digest
    store_conformance_revision: Digest


class NativeOperatorLaunchIdentityV3(BaseModel):
    """Content facts supplied by a trusted factory, never installation locators.

    Constructing this contract is not an OS, vendor-session or store
    availability proof; a factory must obtain each fact from its actual
    artifacts and refuse drift.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[3] = 3
    executable_digest: Digest
    runtime_digest: Digest
    adapter_revision: Digest
    decoder_revision: Digest
    isolation_revision: Digest
    configuration_digest: Digest
    limits_digest: Digest
    callback_protocol_revision: Digest
    callback_catalog_digest: Digest
    profile: NativeOperatorExecutorProfileV3
    egress: NativeEgressIdentityV1
    store: NativeOperatorStoreIdentityV1
    authenticated_startup_conformance_revision: Digest
    subscription_mode_conformance_revision: Digest

    @property
    def revision(self) -> str:
        return str(digest("executor-native-operator-launch", 3, {
            "law": NATIVE_OPERATOR_LAW_REVISION,
            "identity": self.model_dump(mode="json"),
        }))


NATIVE_OPERATOR_LAW_REVISION = digest("executor-native-operator-law", 3, {
    member.__name__: inspect.getsource(member)
    for member in (
        _names, Posture, ModelSelection, EffectiveGrants,
        NativeOperatorGrantPolicyV3, NativeOperatorIsolationProfileV3,
        NativeOperatorExecutorProfileV3, NativeEgressIdentityV1,
        NativeOperatorStoreIdentityV1, NativeOperatorLaunchIdentityV3,
    )
})
"""Derived from the shared grant bodies and every v3 record, not a manual version.

Reading the v1 sources does not modify the v1 closure: ``EXECUTOR_LAW_REVISION``
keeps its exact base value, and this revision is a separate identity law.
"""


def offered_postures(
    profile: ExecutorProfile | NativeOperatorExecutorProfileV3,
) -> frozenset[Posture]:
    """Every posture a profile offers, whichever version declares it.

    A v3 profile states exactly one posture; READ and WRITE are separate
    profiles with separate identities, never one widened record.
    """

    if isinstance(profile, NativeOperatorExecutorProfileV3):
        return frozenset({profile.posture})
    return profile.postures


def _select_profile(value: Any) -> Any:
    if isinstance(value, (ExecutorProfile, NativeOperatorExecutorProfileV3)):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("an executor profile must be a JSON object")
    if "schema_version" not in value:
        return ExecutorProfile.model_validate(value)
    version = value["schema_version"]
    if type(version) is int and version == 3:
        return NativeOperatorExecutorProfileV3.model_validate(value)
    refusal = (
        f"executor profile schema_version {version!r} is unsupported: absent selects "
        "the unversioned profile, 3 selects the native operator profile, 2 is reserved"
    )
    raise ValueError(refusal)


def _select_launch_identity(value: Any) -> Any:
    if isinstance(value, (ExecutorLaunchIdentity, NativeOperatorLaunchIdentityV3)):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("a launch identity must be a JSON object")
    version = value.get("schema_version")
    if type(version) is int and version == 1:
        # ExecutorProfile ignores extra keys, so a hybrid nested profile would
        # otherwise parse as v1 and silently drop its native markers.
        raw_profile = value.get("profile")
        if isinstance(raw_profile, Mapping) and "schema_version" in raw_profile:
            raise ValueError("a schema-1 launch identity requires the unversioned profile")
        return ExecutorLaunchIdentity.model_validate(value)
    if type(version) is int and version == 3:
        return NativeOperatorLaunchIdentityV3.model_validate(value)
    refusal = (
        f"launch identity schema_version {version!r} is unsupported: 1 selects the v1 "
        "identity, 3 selects the native operator identity, 2 is reserved"
    )
    raise ValueError(refusal)


ExecutorProfileUnion = Annotated[
    ExecutorProfile | NativeOperatorExecutorProfileV3, BeforeValidator(_select_profile)
]
ExecutorLaunchIdentityUnion = Annotated[
    ExecutorLaunchIdentity | NativeOperatorLaunchIdentityV3,
    BeforeValidator(_select_launch_identity),
]

_PROFILE_ADAPTER: TypeAdapter[Any] = TypeAdapter(ExecutorProfileUnion)
_LAUNCH_ADAPTER: TypeAdapter[Any] = TypeAdapter(ExecutorLaunchIdentityUnion)


def _one_object(raw: str | Mapping[str, Any]) -> Any:
    return parse_json_value(raw) if isinstance(raw, str) else raw


def parse_executor_profile(
    raw: str | Mapping[str, Any],
) -> ExecutorProfile | NativeOperatorExecutorProfileV3:
    """Decode one executor profile by its declared version, never by trial.

    A failed native decode raises; it never retries with the permissive
    unversioned profile.
    """

    parsed = _PROFILE_ADAPTER.validate_python(_one_object(raw))
    assert isinstance(parsed, (ExecutorProfile, NativeOperatorExecutorProfileV3))
    return parsed


def parse_executor_launch_identity(
    raw: str | Mapping[str, Any],
) -> ExecutorLaunchIdentity | NativeOperatorLaunchIdentityV3:
    """Decode one launch identity by its declared version, never by trial."""

    parsed = _LAUNCH_ADAPTER.validate_python(_one_object(raw))
    assert isinstance(parsed, (ExecutorLaunchIdentity, NativeOperatorLaunchIdentityV3))
    return parsed
