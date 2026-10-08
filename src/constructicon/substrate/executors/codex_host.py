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
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

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
from constructicon.substrate.executors.codex_protocol import ExpectedAccount, named_method
from constructicon.substrate.executors.egress import identity_digests
from constructicon.substrate.executors.operator_store import BindingStore
from constructicon.substrate.git.acquisition import AcquisitionClosure
from constructicon.substrate.git.authority import GitAuthority

LAUNCH_ROOT = Path("/var/lib/constructicon-m8-launch")
MAX_EVIDENCE_BYTES = 1048576
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)

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


def sealed_account(
    store: NativeOperatorStoreIdentityV1, evidence: Path, installed: Mapping[str, Any],
) -> ExpectedAccount:
    """The account a generation sealed, from its own qualification evidence.

    The code twin of the runbook's `check_evidence` for a passing maintenance
    startup, so it holds without trusting that the runbook was followed:
    - the file is exactly the one sealed (its digest is both store revisions);
    - it is a closed, passing startup by every affirmative fact the lane records;
    - the artifacts it names are `installed`, `codex_lane.launch_facts` of this
      host, so an older qualification cannot vouch for changed artifacts.
    """
    record = _evidence(evidence)
    q = digest(codex_lane.EVIDENCE_DOMAIN, 1, json.loads(canonical_json(record)))
    if q != store.subscription_mode_adapter_revision or q != store.store_conformance_revision:
        raise ContractViolation("the evidence is not the qualification this generation sealed")
    if set(record) != codex_lane.STARTUP_FIELDS | {"completed"}:
        raise ContractViolation("the sealed qualification is not a closed startup record")
    custody, gate, process, relay, credential, readback = (
        record[key] if type(record[key]) is dict else {}
        for key in ("custody", "gate", "process", "relay", "credential", "readback")
    )
    account = gate.get("account")
    passing = (
        record["completed"] is True,
        record["schema_version"] == codex_lane.LANE_SCHEMA and record["lane"] == "startup",
        record["faults"] == [] and record["vendor_conformance_qualified"] is False,
        custody.get("kind") == "maintenance" and set(custody) == {"kind", "generation_floor"},
        record["methods_sent"] == [named_method(item) for item in codex_lane.STARTUP_METHODS],
        record["observation"] == {"malformed_records": 0, "first_error": False},
        gate.get("completed") is True and gate.get("plan") in codex_lane.QUALIFICATION_PLANS,
        _is_digest(account),
        readback.get("spend_control_reached", True) in (False, None),
        process.get("returncode") == 0 and process.get("payload_returncode") == 0,
        not any(
            process.get(key, True) for key in ("timed_out", "bound_exceeded", "exchange_failed")
        ),
        relay.get("closed") is True and relay.get("denied") == {},
        all(credential.get(key) is True for key in ("present", "regular_0600", "checked")),
    )
    if not all(passing):
        raise ContractViolation("the sealed qualification is not a passing startup")
    if any(record[key] != value for key, value in installed.items()):
        raise ContractViolation("the sealed qualification ran other artifacts than are installed")
    return ExpectedAccount(plan_type=gate["plan"], identity=Digest(account))


def _evidence(path: Path) -> dict[str, Any]:
    """One bounded, regular, duplicate-free JSON object; never a FIFO or a link."""
    try:
        fd = os.open(path, os.O_RDONLY | _O_CLOEXEC | _O_NOFOLLOW | _O_NONBLOCK)
    except OSError as exc:
        raise ContractViolation("the sealed qualification evidence is unavailable") from exc
    try:
        info = os.fstat(fd)
        raw = b""
        if stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_EVIDENCE_BYTES:
            raw = os.read(fd, MAX_EVIDENCE_BYTES + 1)
        if not 0 < len(raw) == info.st_size:
            raise ContractViolation("the sealed qualification evidence is unavailable")
        record = json.loads(raw, object_pairs_hook=_unique)
    except (OSError, ValueError) as exc:
        raise ContractViolation("the sealed qualification evidence is unavailable") from exc
    finally:
        os.close(fd)
    if type(record) is not dict:
        raise ContractViolation("the sealed qualification evidence is unavailable")
    return record


def _is_digest(value: object) -> bool:
    try:
        Digest.model_validate(value)
    except ValidationError:
        return False
    return True


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("a duplicated key")
    return dict(pairs)


def operator_provider(
    host: HostSession, qualification: QualificationAuthorization | None = None,
) -> CodexOperatorProvider:
    """The production provider for this host session.

    It stays unavailable: its published reasons are untouched, and only an
    owner's authorization admits a qualification run.
    """
    if sys.platform != "linux":
        raise ContractViolation("the host assembly requires the Linux host")
    # Checked before the closure authority is constructed: constructing it
    # installs hooks, so it must never touch a directory assembly would refuse.
    state = host.state
    if not (state.is_absolute() and state.resolve() == state and (state / "closure.git").is_dir()):
        raise ContractViolation("the state directory is not this host's prepared state")
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
        expected_account=sealed_account(
            store, host.qualification,
            codex_lane.launch_facts(launcher, policy, executable, configuration),
        ),
        binary=codex_lane.RUNTIME_BINARY,
        configuration=configuration,
        catalog=(),
        acquisition_root=state / "acquisitions",
        binding_store=BindingStore(
            host.launch_root / "operator-stores", host.store_key, store,
        ),
        closure=AcquisitionClosure(
            GitAuthority(state / "closure.git", state / "workspaces"),
        ),
        egress=policy,
        qualification=qualification,
    )
