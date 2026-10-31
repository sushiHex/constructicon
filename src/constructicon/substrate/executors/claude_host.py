"""Bind a Claude READ qualification to installed facts and sealed startup evidence.

The evidence names observed startup controls, not vendor identity, fresh token
validation or broad conformance. Assembly never logs in or activates a store.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from constructicon.core.address import GitSha
from constructicon.core.errors import ContractViolation
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.identity import Digest, digest
from constructicon.core.native_operator import (
    NativeEgressIdentityV1,
    NativeOperatorExecutorProfileV3,
    NativeOperatorGrantPolicyV3,
    NativeOperatorIsolationProfileV3,
    NativeOperatorLaunchIdentityV3,
    NativeOperatorStoreIdentityV1,
)
from constructicon.core.qualification import QualificationAuthorization
from constructicon.substrate.executors import claude_lane
from constructicon.substrate.executors.claude_lane import LaneConfiguration
from constructicon.substrate.executors.claude_maintenance_session import (
    ClaudeMaintenanceSessionPhase,
)
from constructicon.substrate.executors.claude_native import ClaudeNativeRecipe
from constructicon.substrate.executors.claude_protocol import (
    ClaudeAuthMode,
    ClaudeInitializeVerdict,
    initialize_diagnostic_fields_valid,
)
from constructicon.substrate.executors.claude_provider import (
    READ_CATALOG,
    ClaudeOperatorProvider,
    identity_fields,
)
from constructicon.substrate.executors.claude_startup import (
    ClaudeSettingsMismatchReason,
    ClaudeStartupVerdict,
)
from constructicon.substrate.executors.codex_host import _evidence
from constructicon.substrate.executors.egress import identity_digests
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.executors.operator_store import BindingStore, _sealed_file
from constructicon.substrate.git.acquisition import AcquisitionClosure
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
from constructicon.substrate.git.contained import ContainedWorkspaceProvider

READ_SECONDS = 120
_RECORD_FIELDS = frozenset({
    "schema_version", "subscription_qualified", "production_available", "facts",
    "runtime_digest", "vendor_digest", "launch_policy_sha256", "launch_config_sha256",
    "launch_revision", "egress", "completed", "qualification_revision",
})
_FACT_FIELDS = frozenset({
    "phase", "lifecycle", "login", "mode", "relay_closed", "custody_current",
    "credential_closed", "process_clean", "qualification",
})
_QUALIFICATION_FIELDS = frozenset({
    "lifecycle", "initialize_verdict", "settings_verdict", "settings_mismatch_reason",
    "hooks_verdict", "mode_mismatch_reason", "token_source_category", "api_key_source_category",
    "request_writes", "ui_records", "stdin_closed", "eof", "mode", "model", "effort",
})


def sealed_mode(
    store: NativeOperatorStoreIdentityV1, evidence: Path, configuration: LaneConfiguration,
    *, recipe: ClaudeNativeRecipe = ClaudeNativeRecipe.STREAM_JSON,
) -> ClaudeAuthMode:
    """Bind already-validated startup facts to this published store generation."""
    mode, revision = validate_startup_evidence(evidence, configuration, recipe=recipe)
    if (revision != store.subscription_mode_adapter_revision
            or revision != store.store_conformance_revision):
        raise ContractViolation("Claude startup evidence is not sealed by this generation")
    return mode


def checked_startup_evidence(
    evidence: Path, configuration: LaneConfiguration,
    *, recipe: ClaudeNativeRecipe = ClaudeNativeRecipe.STREAM_JSON,
) -> tuple[dict[str, Any], Digest]:
    """Check one closed current snapshot, without claiming qualification."""
    # Reuse the existing bounded regular-file/duplicate-key reader. It does no
    # Codex operation and never reads an operator credential.
    record = _evidence(evidence)
    revision = digest(claude_lane.EVIDENCE_DOMAIN, 1, record)
    facts = record.get("facts")
    qualification = facts.get("qualification") if type(facts) is dict else None
    if (set(record) != _RECORD_FIELDS or type(facts) is not dict
            or set(facts) != _FACT_FIELDS or type(qualification) is not dict
            or set(qualification) != _QUALIFICATION_FIELDS):
        raise ContractViolation("Claude startup evidence is not a closed qualification record")
    checks = (
        type(record["schema_version"]) is int
        and record["schema_version"] == claude_lane.EVIDENCE_SCHEMA,
        record["completed"] is True,
        record["subscription_qualified"] is False,
        record["production_available"] is False,
        record["qualification_revision"] == str(claude_lane.qualification_revision()),
        facts["phase"] == "qualify",
        facts["lifecycle"] in ("joined-clean", "refused", "incomplete"),
        facts["login"] is None, facts["mode"] is None,
        all(facts[name] is True for name in (
            "relay_closed", "custody_current", "credential_closed",
        )),
        type(facts["process_clean"]) is bool,
        qualification["lifecycle"] in ("qualified", "refused", "incomplete"),
        qualification["initialize_verdict"] is None or (
            type(qualification["initialize_verdict"]) is str
            and qualification["initialize_verdict"] in {v.value for v in ClaudeInitializeVerdict}
        ),
        initialize_diagnostic_fields_valid(
            qualification["initialize_verdict"], qualification["mode_mismatch_reason"],
            qualification["token_source_category"], qualification["api_key_source_category"],
        ),
        all(qualification[name] is None or (
            type(qualification[name]) is str
            and qualification[name] in {v.value for v in ClaudeStartupVerdict}
        ) for name in ("settings_verdict", "hooks_verdict")),
        ((qualification["settings_verdict"] == "configuration-mismatch")
         == (qualification["settings_mismatch_reason"] is not None)),
        qualification["settings_mismatch_reason"] is None or (
            type(qualification["settings_mismatch_reason"]) is str
            and qualification["settings_mismatch_reason"] in {
                reason.value for reason in ClaudeSettingsMismatchReason
            }
        ),
        type(qualification["request_writes"]) is int
        and 0 <= qualification["request_writes"] <= 3,
        qualification["initialize_verdict"] is None or (
            type(qualification["request_writes"]) is int and qualification["request_writes"] >= 1
        ),
        qualification["settings_verdict"] is None or (
            type(qualification["request_writes"]) is int and qualification["request_writes"] >= 2
            and qualification["initialize_verdict"] == "mode-match"
        ),
        qualification["hooks_verdict"] is None or (
            qualification["request_writes"] == 3 and qualification["settings_verdict"] == "match"
        ),
        qualification["request_writes"] in (0, 1)
        or qualification["initialize_verdict"] == "mode-match",
        qualification["request_writes"] != 3 or qualification["settings_verdict"] == "match",
        type(qualification["ui_records"]) is int and 0 <= qualification["ui_records"] <= 8,
        type(qualification["stdin_closed"]) is bool, type(qualification["eof"]) is bool,
        qualification["model"] == configuration.model,
        qualification["effort"] == configuration.effort,
    )
    plans = {"subscription": ClaudeAuthMode.SUBSCRIPTION}
    plan = qualification["mode"]
    if not all(checks) or type(plan) is not str or plan not in plans:
        raise ContractViolation("Claude startup evidence has invalid current facts")
    launcher = configuration.launcher(ClaudeMaintenanceSessionPhase.QUALIFY, recipe=recipe)
    expected: dict[str, Any] = {
        "runtime_digest": str(configuration.runtime_digest),
        "vendor_digest": str(configuration.vendor_digest),
        "launch_policy_sha256": configuration.launch_policy_sha256,
        "launch_config_sha256": configuration.configuration_sha256,
        "launch_revision": str(launcher.revision),
        "egress": {name: str(value) for name, value in
                   identity_digests(configuration.egress["observe"]).items()},
    }
    if any(record[name] != value for name, value in expected.items()):
        raise ContractViolation("Claude startup evidence names different installed inputs")
    return record, revision


def validate_startup_evidence(
    evidence: Path, configuration: LaneConfiguration,
    *, recipe: ClaudeNativeRecipe = ClaudeNativeRecipe.STREAM_JSON,
) -> tuple[ClaudeAuthMode, Digest]:
    """Require positive qualification from the same checked current snapshot."""
    record, revision = checked_startup_evidence(evidence, configuration, recipe=recipe)
    facts = record["facts"]
    qualification = facts["qualification"]
    checks = (
        facts["lifecycle"] == "joined-clean", facts["process_clean"] is True,
        qualification["lifecycle"] == "qualified",
        qualification["initialize_verdict"] == "mode-match",
        qualification["settings_verdict"] == "match",
        qualification["settings_mismatch_reason"] is None,
        qualification["hooks_verdict"] == "match",
        qualification["request_writes"] == 3,
        qualification["stdin_closed"] is True, qualification["eof"] is True,
    )
    if not all(checks):
        raise ContractViolation("Claude startup evidence does not affirm complete qualification")
    return {"subscription": ClaudeAuthMode.SUBSCRIPTION}[qualification["mode"]], revision


def read_grants(configuration: LaneConfiguration) -> EffectiveGrants:
    return EffectiveGrants(
        posture=Posture.READ,
        model_selection=ModelSelection(kind="explicit", model=configuration.model),
        effort=configuration.effort, allowed_tools=READ_CATALOG,
        env_allowlist=(), network="allow", timeout_s=READ_SECONDS,
    )


def read_profile(configuration: LaneConfiguration) -> NativeOperatorExecutorProfileV3:
    return NativeOperatorExecutorProfileV3(
        name="claude-operator-read", posture=Posture.READ, structured_output=False,
        accepted_efforts=(configuration.effort,),
        grant_policy=NativeOperatorGrantPolicyV3(
            tool_sets=(READ_CATALOG,), model_ids=(configuration.model,), environment_names=(),
            workspace_required=True, network_modes=("allow",),
            network_access="native_vendor_session_only", tool_path="mediated_callbacks_only",
        ),
        isolation=NativeOperatorIsolationProfileV3(
            filesystem="read_only_snapshot", process_tree_owned=True,
            environment_allowlisted=True, network_enforced=True, native_workspace="none",
            worker_network="none", credential_state="narrow_vendor_store_rw",
            zones="native_and_worker_separate",
        ),
        authentication="vendor_managed_subscription",
        account_assurance="operator_bound_vendor_identity_unverified",
        subscription_overage="operator_authorized",
    )


def write_grants(configuration: LaneConfiguration) -> EffectiveGrants:
    return read_grants(configuration).model_copy(update={
        "posture": Posture.WRITE, "allowed_tools": ("contained_python",), "timeout_s": 300,
    })


def write_profile(configuration: LaneConfiguration) -> NativeOperatorExecutorProfileV3:
    read = read_profile(configuration)
    return read.model_copy(update={
        "name": "claude-operator-write", "posture": Posture.WRITE,
        "grant_policy": read.grant_policy.model_copy(update={
            "tool_sets": (("contained_python",),),
        }),
        "isolation": read.isolation.model_copy(update={"filesystem": "workspace_only"}),
    })


@dataclass(frozen=True)
class ClaudeHostSession:
    configuration: Path
    configuration_sha256: str
    store_root: Path
    store_key: str
    sealed: Path
    qualification: Path
    acquisition_root: Path


def operator_provider(
    host: ClaudeHostSession, *, workspace: ContainedWorkspaceProvider,
    workspace_capability_id: str, workspace_revision: str, expected_base: GitSha,
    worker_launcher: LinuxLauncher,
    authorization: QualificationAuthorization | None = None,
) -> ClaudeOperatorProvider:
    """Assemble only an unavailable provider; exact authorization gates dispatch."""
    if sys.platform != "linux":
        raise ContractViolation("Claude host assembly requires Linux")
    configuration = claude_lane.read_configuration(
        host.configuration, expected_sha256=host.configuration_sha256,
    )
    store = _sealed_file(host.sealed, os.getuid())
    write = type(workspace) is ContainedWriteWorkspaceProvider
    recipe = ClaudeNativeRecipe.STREAM_JSON_WRITE if write else ClaudeNativeRecipe.STREAM_JSON
    if write:
        mode = sealed_mode(store, host.qualification, configuration, recipe=recipe)
        launcher = configuration.launcher(ClaudeMaintenanceSessionPhase.QUALIFY, recipe=recipe)
    else:
        mode = sealed_mode(store, host.qualification, configuration)
        launcher = configuration.launcher(ClaudeMaintenanceSessionPhase.OBSERVE)
    policy = configuration.egress["observe"]
    revision = store.store_conformance_revision
    profile = write_profile(configuration) if write else read_profile(configuration)
    identity = NativeOperatorLaunchIdentityV3(
        **identity_fields(
            launcher, worker_launcher, workspace_provider=workspace,
            workspace_capability_id=workspace_capability_id,
            workspace_revision=workspace_revision, mode=mode,
            expected_base=expected_base,
        ),
        profile=profile, store=store,
        egress=NativeEgressIdentityV1(
            **identity_digests(policy), physical_conformance_revision=revision,
        ),
        authenticated_startup_conformance_revision=revision,
        subscription_mode_conformance_revision=revision,
    )
    return ClaudeOperatorProvider(
        launcher=launcher, worker_launcher=worker_launcher, profile=profile, identity=identity,
        binding_store=BindingStore(host.store_root, host.store_key, store),
        closure=AcquisitionClosure(workspace.authority), workspace_provider=workspace,
        workspace_capability_id=workspace_capability_id, workspace_revision=workspace_revision,
        expected_base=expected_base,
        acquisition_root=host.acquisition_root, egress=policy, mode=mode,
        qualification=authorization,
    )
