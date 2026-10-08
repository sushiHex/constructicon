"""The operator provider on the host, assembled from installed facts only (M8 N5).

Every input is a fact the host already holds, read and checked here:
- the launch set (`codex_lane._launcher`) and its runtime;
- the session's sealed startup policy and configuration;
- the operator store and the generation's sealed identity;
- the qualification evidence that generation sealed.

Nothing is minted. The three conformance revisions are the sealed
qualification evidence digest `Q`, read from the store identity: they name which
qualification ran and claim no conformance. The evidence itself records
`vendor_conformance_qualified: false`.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.native_operator import (
    NativeEgressIdentityV1,
    NativeOperatorExecutorProfileV3,
    NativeOperatorGrantPolicyV3,
    NativeOperatorIsolationProfileV3,
    NativeOperatorStoreIdentityV1,
)
from constructicon.core.qualification import QualificationAuthorization
from constructicon.substrate.executors import codex_lane, operator_store
from constructicon.substrate.executors.codex import CodexOperatorProvider, launch_identity
from constructicon.substrate.executors.codex_protocol import ExpectedAccount
from constructicon.substrate.executors.egress import identity_digests
from constructicon.substrate.executors.operator_store import BindingStore
from constructicon.substrate.git.acquisition import AcquisitionClosure
from constructicon.substrate.git.authority import GitAuthority

LAUNCH_ROOT = Path("/var/lib/constructicon-m8-launch")
MAX_EVIDENCE_BYTES = 1048576

READ_PROFILE = NativeOperatorExecutorProfileV3(
    name="codex-operator-read",
    posture=Posture.READ,
    structured_output=True,
    accepted_efforts=(codex_lane.PREPARE_EFFORT,),
    grant_policy=NativeOperatorGrantPolicyV3(
        tool_sets=((),),
        model_ids=(codex_lane.PREPARE_MODEL,),
        environment_names=(),
        workspace_required=False,
        network_modes=("allow",),
        network_access="native_vendor_session_only",
        tool_path="mediated_callbacks_only",
    ),
    isolation=NativeOperatorIsolationProfileV3(
        filesystem="none",
        process_tree_owned=True,
        environment_allowlisted=True,
        network_enforced=True,
        native_workspace="none",
        worker_network="none",
        credential_state="narrow_vendor_store_rw",
        zones="native_and_worker_separate",
    ),
    authentication="vendor_managed_subscription",
    account_assurance="operator_bound_vendor_identity_unverified",
    # The owner's October 1 overage decision (#78); a forbidden profile is
    # forced unavailable.
    subscription_overage="operator_authorized",
)
"""The one production READ profile: the prepared model and effort, no tools."""


READ_GRANTS = EffectiveGrants(
    posture=Posture.READ,
    model_selection=ModelSelection(kind="explicit", model=codex_lane.PREPARE_MODEL),
    effort=codex_lane.PREPARE_EFFORT,
    allowed_tools=(),
    env_allowlist=(),
    network="allow",
    timeout_s=120,
)
"""The READ grants: the profile's one model and effort, and decision 6's 120 s."""


@dataclass(frozen=True)
class HostSession:
    """Where one host session's facts live. Paths only; every read is checked."""

    session: Path
    """The session directory: `config.toml` and `startup-policy.json`, from S1."""
    store_key: str
    sealed: Path
    """The active generation's sealed identity, saved by the session."""
    qualification: Path
    """The qualification evidence that generation sealed (S6a's, or S9's)."""
    state: Path
    """The service-owned `closure.git` (bare) and `acquisitions`."""
    launch_root: Path = LAUNCH_ROOT


def sealed_account(store: NativeOperatorStoreIdentityV1, evidence: Path) -> ExpectedAccount:
    """The account a generation sealed, from its own qualification evidence.

    The file must be exactly the one sealed: its digest is both store
    revisions. It must also be a passing maintenance startup with a completed
    gate naming an approved plan and an account. This is the code twin of the
    runbook's `read_seal`, without trusting that the runbook was followed.
    """
    raw = evidence.read_bytes()
    if not 0 < len(raw) <= MAX_EVIDENCE_BYTES:
        raise ContractViolation("the sealed qualification evidence is unavailable")
    record = json.loads(raw)
    q = digest(codex_lane.EVIDENCE_DOMAIN, 1, json.loads(canonical_json(record)))
    if q != store.subscription_mode_adapter_revision or q != store.store_conformance_revision:
        raise ContractViolation("the evidence is not the qualification this generation sealed")
    gate = record.get("gate") or {}
    if not (
        record.get("completed") is True
        and record.get("schema_version") == codex_lane.LANE_SCHEMA
        and record.get("lane") == "startup"
        and record.get("faults") == []
        and (record.get("custody") or {}).get("kind") == "maintenance"
        and gate.get("completed") is True
        and gate.get("plan") in codex_lane.QUALIFICATION_PLANS
        and isinstance(gate.get("account"), str)
    ):
        raise ContractViolation("the sealed qualification is not a passing startup")
    return ExpectedAccount(plan_type=gate["plan"], identity=Digest(gate["account"]))


def operator_provider(
    host: HostSession, qualification: QualificationAuthorization | None = None,
) -> CodexOperatorProvider:
    """The production provider for this host session.

    It stays unavailable: its published reasons are untouched, and only an
    owner's authorization admits a qualification run.
    """
    if sys.platform != "linux":
        raise ContractViolation("the host assembly requires the Linux host")
    launcher = codex_lane._launcher(host.launch_root)
    configuration = codex_lane.production_configuration()
    if (host.session / "config.toml").read_text(encoding="utf-8") != configuration:
        raise ContractViolation("the session configuration is not the production configuration")
    policy = codex_lane._policy(host.session / "startup-policy.json")
    store = operator_store._sealed_file(host.sealed, os.getuid())
    q = store.subscription_mode_adapter_revision
    executable = codex_lane.vendor_executable(launcher)
    identity = launch_identity(
        launcher=launcher,
        profile=READ_PROFILE,
        egress=NativeEgressIdentityV1(**identity_digests(policy), physical_conformance_revision=q),
        store=store,
        executable_digest=Digest(f"sha256:{executable.sha256}"),
        configuration=configuration,
        catalog=(),
        authenticated_startup_conformance_revision=q,
        subscription_mode_conformance_revision=q,
    )
    return CodexOperatorProvider(
        launcher=launcher,
        profile=READ_PROFILE,
        identity=identity,
        expected_account=sealed_account(store, host.qualification),
        binary=codex_lane.RUNTIME_BINARY,
        configuration=configuration,
        catalog=(),
        acquisition_root=host.state / "acquisitions",
        binding_store=BindingStore(
            host.launch_root / "operator-stores", host.store_key, store,
        ),
        closure=AcquisitionClosure(
            GitAuthority(host.state / "closure.git", host.state / "workspaces"),
        ),
        egress=policy,
        qualification=qualification,
    )
