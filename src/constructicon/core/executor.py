"""The executor seam — task-shaped, harness-level (decision 2).

All models, subscription or API, fit the same data model schema and are
interchangeable as plugs — substitutable where their declared capability
profile satisfies the node's contract. There is no completion-level provider
layer, ever.

Outcomes share one observation (I4: salvage applies to every status; fields a
backend does not emit stay ``None``, never inferred), extended per-status with
only the status-specific field.
"""

from __future__ import annotations

import inspect
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from constructicon.core.envelope import ArtifactRef, GitRef, TextContext
from constructicon.core.grants import EffectiveGrants, IsolationProfile, ModelSelection, Posture
from constructicon.core.identity import Digest, digest
from constructicon.core.workspace import LeasedCapability, WorkspaceView


class TaskSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    instruction: str
    context: tuple[ArtifactRef | GitRef | TextContext, ...] = ()
    response_schema: dict[str, Any] | None = None


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int | None = None
    output_tokens: int | None = None


class RateLimitInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_using_overage: bool | None = None
    detail: dict[str, Any] | None = None


class TransportDamage(BaseModel):
    model_config = ConfigDict(frozen=True)

    malformed_records: int
    first_error: str | None
    evidence_excerpt: str | None  # bounded head+tail, never the full stream


class ExecutorError(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["spawn", "timeout", "exit", "unavailable"]
    detail: str
    exit_code: int | None = None
    timed_out_after_s: float | None = None
    produced_output: bool | None = None


class ExecutorObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_reply: str | None = None
    output: Any = None  # extracted structured output, pre-validation
    requested_model: str | None = None
    served_model: str | None = None  # None when the backend does not emit it
    usage: Usage | None = None
    rate_limit: RateLimitInfo | None = None
    elapsed_s: float = 0.0


class ExecutorSuccess(ExecutorObservation):
    status: Literal["success"] = "success"


class ExecutorPartial(ExecutorObservation):
    status: Literal["partial"] = "partial"
    damage: TransportDamage


class ExecutorFailure(ExecutorObservation):
    status: Literal["failure"] = "failure"
    error: ExecutorError


ExecutorOutcome = ExecutorSuccess | ExecutorPartial | ExecutorFailure


def _names(values: tuple[str, ...]) -> tuple[str, ...]:
    if any(not value.strip() for value in values):
        raise ValueError("inventory names must be non-empty")
    return tuple(sorted(set(values)))


class ExecutorGrantPolicy(BaseModel):
    """A complete finite enforcement inventory, not another grant language."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    tool_sets: tuple[tuple[str, ...], ...]
    network_modes: tuple[Literal["none", "allow"], ...]
    network_access: Literal["none", "provider_route_only"]
    environment_names: tuple[str, ...]
    workspace_required: bool

    @field_validator("tool_sets")
    @classmethod
    def _tool_inventory(cls, values: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
        if not values:
            raise ValueError("declare at least one supported tool set, including () if supported")
        return tuple(sorted({_names(value) for value in values}))

    @field_validator("network_modes")
    @classmethod
    def _networks(
        cls, values: tuple[Literal["none", "allow"], ...]
    ) -> tuple[Literal["none", "allow"], ...]:
        if not values:
            raise ValueError("declare at least one supported network mode")
        return tuple(sorted(set(values)))

    @field_validator("environment_names")
    @classmethod
    def _environment(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _names(values)


class ExecutorProfile(BaseModel):
    """Capability profile: what makes executors honestly substitutable."""

    model_config = ConfigDict(frozen=True)

    name: str
    structured_output: bool
    postures: frozenset[Posture]
    isolation: IsolationProfile
    accepted_efforts: frozenset[str] = frozenset()
    grant_policy: ExecutorGrantPolicy | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        value: dict[str, Any] = handler(self)
        if self.grant_policy is None:
            # Historical profiles keep their exact absence and set serialization.
            value.pop("grant_policy", None)
        else:
            # The live identity cannot depend on process-local set iteration.
            if "postures" in value:
                value["postures"] = sorted(posture.value for posture in self.postures)
            if "accepted_efforts" in value:
                value["accepted_efforts"] = sorted(self.accepted_efforts)
        return value

    def grant_faults(self, grants: EffectiveGrants) -> tuple[str, ...]:
        """The one pure complete-policy predicate used by admission and adapters.

        Legacy consumers retain their historical checks; an incomplete profile
        cannot itself provide a complete grant proof through this new method.
        """
        policy = self.grant_policy
        if policy is None:
            return ("executor profile has no complete grant policy",)
        faults: list[str] = []
        if grants.posture not in self.postures:
            faults.append(f"executor does not offer posture {grants.posture.value!r}")
        elif not self.isolation.satisfies(grants.posture):
            faults.append(f"executor cannot mechanically enforce posture {grants.posture.value!r}")
        if tuple(sorted(set(grants.allowed_tools))) not in policy.tool_sets:
            faults.append(f"executor does not offer exact tool set {grants.allowed_tools!r}")
        if grants.network not in policy.network_modes:
            faults.append(f"executor does not offer network mode {grants.network!r}")
        if not self.isolation.network_enforced:
            faults.append("executor cannot mechanically enforce network grants")
        unsupported = sorted(set(grants.env_allowlist) - set(policy.environment_names))
        if unsupported:
            faults.append(f"executor cannot inherit environment names {unsupported!r}")
        if grants.effort is not None and grants.effort not in self.accepted_efforts:
            faults.append(f"executor does not offer explicit effort {grants.effort!r}")
        selection = grants.model_selection
        if selection.kind == "explicit" and (
            selection.model is None or not selection.model.strip()
        ):
            faults.append("an explicit model selection requires a non-empty model id")
        return tuple(faults)


class ProviderRouteIdentity(BaseModel):
    """Secret-free identity of the selected deployment and its conformance law."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    build_digest: Digest
    configuration_digest: Digest
    policy_digest: Digest
    conformance_revision: Digest


class ExecutorLaunchIdentity(BaseModel):
    """Content facts supplied by a trusted factory, never installation locators.

    A factory must obtain these from its actual artifacts and refuse drift.
    Constructing this data contract is not an OS or gateway availability proof.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    executable_digest: Digest
    runtime_digest: Digest
    adapter_revision: Digest
    decoder_revision: Digest
    isolation_revision: Digest
    configuration_digest: Digest
    limits_digest: Digest
    profile: ExecutorProfile
    provider_route: ProviderRouteIdentity | None

    @model_validator(mode="after")
    def _complete(self) -> ExecutorLaunchIdentity:
        policy = self.profile.grant_policy
        if policy is None or len(self.profile.postures) != 1:
            raise ValueError("a launch identity requires a complete, single-posture profile")
        if (policy.network_access == "provider_route_only") != (self.provider_route is not None):
            raise ValueError("provider-route access requires exactly one provider-route identity")
        return self

    @property
    def revision(self) -> str:
        return str(digest("executor-launch", 1, {
            "law": EXECUTOR_LAW_REVISION,
            "identity": self.model_dump(mode="json"),
        }))


EXECUTOR_LAW_REVISION = digest("executor-law", 1, {
    member.__name__: inspect.getsource(member)
    for member in (
        _names, Posture, ModelSelection, EffectiveGrants, IsolationProfile,
        ExecutorGrantPolicy, ExecutorProfile, ProviderRouteIdentity, ExecutorLaunchIdentity,
    )
})
"""Derived from the complete shared policy/identity bodies, not a manual version.

The backend factory still binds its own adapter, decoder, recipe and artifacts.
Legacy profile bytes/revisions do not participate in this new identity law.
"""


@runtime_checkable
class ExecutorProvider(LeasedCapability, Protocol):
    """A leased factory whose published facts describe its actual implementation.

    Availability is the result of substrate checks, read without I/O by L2;
    the substrate must additionally recheck physical prerequisites before use.
    A genuine fake may prove its own behavior, never a real launcher's safety.
    """

    @property
    def identity(self) -> ExecutorLaunchIdentity: ...

    @property
    def unavailable_reasons(self) -> tuple[str, ...]: ...


class Executor(Protocol):
    @property
    def profile(self) -> ExecutorProfile: ...

    def validate_grants(self, grants: EffectiveGrants) -> tuple[str, ...]:
        """Itemized reasons this executor cannot honor the grants; empty = ok."""
        ...

    async def execute(
        self,
        task: TaskSpec,
        *,
        workspace: WorkspaceView | None,
        grants: EffectiveGrants,
    ) -> ExecutorOutcome: ...
