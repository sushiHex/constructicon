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
from constructicon.substrate.executors import claude_lane
from constructicon.substrate.executors.claude_lane import LaneConfiguration
from constructicon.substrate.executors.claude_maintenance_session import (
    ClaudeMaintenanceSessionPhase,
)
from constructicon.substrate.executors.claude_protocol import ClaudePlan
from constructicon.substrate.executors.claude_provider import (
    READ_CATALOG,
    ClaudeOperatorProvider,
    identity_fields,
)
from constructicon.substrate.executors.codex_host import _evidence
from constructicon.substrate.executors.egress import identity_digests
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.executors.operator_store import BindingStore, _sealed_file
from constructicon.substrate.git.acquisition import AcquisitionClosure
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
    "lifecycle", "initialize_verdict", "settings_verdict", "hooks_verdict",
    "request_writes", "ui_records", "stdin_closed", "eof", "selected_plan", "model", "effort",
})


def sealed_plan(
    store: NativeOperatorStoreIdentityV1, evidence: Path, configuration: LaneConfiguration,
) -> ClaudePlan:
    """Require affirmative joined startup facts for exactly these installed inputs."""
    # Reuse the existing bounded regular-file/duplicate-key reader. It does no
    # Codex operation and never reads an operator credential.
    record = _evidence(evidence)
    revision = digest(claude_lane.EVIDENCE_DOMAIN, 1, record)
    if (revision != store.subscription_mode_adapter_revision
            or revision != store.store_conformance_revision):
        raise ContractViolation("Claude startup evidence is not sealed by this generation")
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
        facts["phase"] == "qualify", facts["lifecycle"] == "joined-clean",
        facts["login"] is None, facts["mode"] is None,
        all(facts[name] is True for name in (
            "relay_closed", "custody_current", "credential_closed", "process_clean",
        )),
        qualification["lifecycle"] == "qualified",
        qualification["initialize_verdict"] == "mode-match",
        qualification["settings_verdict"] == "match",
        qualification["hooks_verdict"] == "match",
        type(qualification["request_writes"]) is int and qualification["request_writes"] == 3,
        type(qualification["ui_records"]) is int and 0 <= qualification["ui_records"] <= 8,
        qualification["stdin_closed"] is True, qualification["eof"] is True,
        qualification["model"] == configuration.model,
        qualification["effort"] == configuration.effort,
    )
    plans = {"pro": ClaudePlan.PRO, "max": ClaudePlan.MAX}
    plan = qualification["selected_plan"]
    if not all(checks) or type(plan) is not str or plan not in plans:
        raise ContractViolation("Claude startup evidence does not affirm complete qualification")
    launcher = configuration.launcher(ClaudeMaintenanceSessionPhase.OBSERVE)
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
    return plans[plan]


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
    selected_plan = sealed_plan(store, host.qualification, configuration)
    launcher = configuration.launcher(ClaudeMaintenanceSessionPhase.OBSERVE)
    policy = configuration.egress["observe"]
    revision = store.store_conformance_revision
    profile = read_profile(configuration)
    identity = NativeOperatorLaunchIdentityV3(
        **identity_fields(
            launcher, worker_launcher, workspace_provider=workspace,
            workspace_capability_id=workspace_capability_id,
            workspace_revision=workspace_revision, selected_plan=selected_plan,
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
        acquisition_root=host.acquisition_root, egress=policy, selected_plan=selected_plan,
        qualification=authorization,
    )
