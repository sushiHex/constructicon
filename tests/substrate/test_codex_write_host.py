from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import digest
from constructicon.substrate.executors import codex_host, codex_lane
from constructicon.substrate.executors.codex_host import WRITE_GRANTS, WRITE_PROFILE
from constructicon.substrate.executors.codex_protocol import CONTAINED_PYTHON_CATALOG
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider


def test_write_profile_permits_only_reviewed_grants() -> None:
    assert WRITE_PROFILE.posture is Posture.WRITE
    assert WRITE_PROFILE.grant_faults(WRITE_GRANTS) == ()
    assert WRITE_GRANTS.timeout_s == 300
    assert WRITE_GRANTS.allowed_tools == CONTAINED_PYTHON_CATALOG
    assert WRITE_PROFILE.grant_policy.workspace_required
    assert WRITE_PROFILE.grant_faults(WRITE_GRANTS.model_copy(update={"allowed_tools": ()}))
    assert WRITE_PROFILE.grant_faults(WRITE_GRANTS.model_copy(update={"network": "none"}))


@pytest.fixture
def host_assembly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    host = codex_host.HostSession(
        session=tmp_path / "session", store_key="fixed-store", sealed=tmp_path / "sealed",
        qualification=tmp_path / "evidence", state=tmp_path / "state",
        launch_root=tmp_path / "launch",
    )
    host.session.mkdir()
    host.state.mkdir()
    (host.state / "closure.git").mkdir()
    configuration = codex_lane.production_configuration()
    (host.session / "config.toml").write_text(configuration)
    launcher = SimpleNamespace(
        revision=digest("launch", 1, "fixed"), limits="fixed-limits",
        expected_runtime=digest("runtime", 1, "fixed"),
    )
    workspace = object.__new__(ContainedWriteWorkspaceProvider)
    workspace.launcher = launcher
    monkeypatch.setattr(codex_host.sys, "platform", "linux")
    monkeypatch.setattr(codex_host.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(codex_lane, "_launcher", lambda root: launcher)
    monkeypatch.setattr(codex_lane, "_policy", lambda path: "sealed-policy")
    monkeypatch.setattr(codex_host.operator_store, "_sealed_file", lambda *args: SimpleNamespace(
        subscription_mode_adapter_revision=digest("qualification", 1, "fixed"),
    ))
    monkeypatch.setattr(
        codex_lane, "vendor_executable", lambda launch: SimpleNamespace(sha256="e" * 64),
    )
    monkeypatch.setattr(codex_host, "identity_digests", lambda policy: {
        "startup_policy_digest": digest("policy", 1, "fixed"),
        "relay_enforcement_revision": digest("relay", 1, "fixed"),
        "policy_compiler_revision": digest("compiler", 1, "fixed"),
    })
    monkeypatch.setattr(codex_host, "NativeEgressIdentityV1", lambda **kwargs: kwargs)
    identities, providers = [], []
    monkeypatch.setattr(codex_host, "launch_identity", lambda **kwargs: identities.append(kwargs))
    monkeypatch.setattr(
        codex_host, "CodexOperatorProvider", lambda **kwargs: providers.append(kwargs),
    )
    monkeypatch.setattr(codex_host, "sealed_account", lambda *args: "sealed-account")
    monkeypatch.setattr(codex_lane, "launch_facts", lambda *args: {})
    monkeypatch.setattr(codex_host, "BindingStore", lambda *args: "binding")
    monkeypatch.setattr(codex_host, "GitAuthority", lambda *args: "authority")
    monkeypatch.setattr(codex_host, "AcquisitionClosure", lambda *args: "closure")
    return host, workspace, identities, providers


def test_write_host_constructs_identity_with_shared_runtime_and_only_catalog(host_assembly) -> None:
    host, workspace, identities, providers = host_assembly
    codex_host.write_operator_provider(host, workspace)
    assert len(identities) == len(providers) == 1
    for kwargs in (identities[0], providers[0]):
        assert kwargs["launcher"] is workspace.launcher
        assert kwargs["profile"] == WRITE_PROFILE
        assert kwargs["catalog"] == CONTAINED_PYTHON_CATALOG
        assert kwargs["configuration"] == codex_lane.production_configuration()
    assert providers[0]["expected_account"] == "sealed-account"


@pytest.mark.parametrize("field", ["revision", "limits", "expected_runtime"])
def test_write_host_refuses_shared_runtime_drift(host_assembly, field: str) -> None:
    host, workspace, identities, providers = host_assembly
    workspace.launcher = SimpleNamespace(**vars(workspace.launcher))
    setattr(workspace.launcher, field, "changed")
    with pytest.raises(ContractViolation, match="different launch runtimes"):
        codex_host.write_operator_provider(host, workspace)
    assert identities == providers == []


def test_write_host_refuses_unreviewed_configuration(host_assembly) -> None:
    host, workspace, identities, providers = host_assembly
    (host.session / "config.toml").write_text("other configuration")
    with pytest.raises(ContractViolation, match="production configuration"):
        codex_host.write_operator_provider(host, workspace)
    assert identities == providers == []
