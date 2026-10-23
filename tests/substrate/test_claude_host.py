"""Sealed startup evidence is an affirmative, exact-artifact predicate."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import canonical_json, digest
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.substrate.executors import claude_host, claude_lane
from constructicon.substrate.executors.claude_maintenance_session import (
    ClaudeMaintenanceSessionPhase,
)
from constructicon.substrate.executors.claude_protocol import ClaudePlan
from constructicon.substrate.executors.egress import identity_digests
from tests.substrate.test_claude_lane import configuration


@pytest.fixture
def case(tmp_path):
    path = configuration(tmp_path)
    config = claude_lane.read_configuration(
        path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    launcher = config.launcher(ClaudeMaintenanceSessionPhase.OBSERVE)
    record = {
        "schema_version": claude_lane.EVIDENCE_SCHEMA, "completed": True,
        "subscription_qualified": False, "production_available": False,
        "qualification_revision": str(claude_lane.qualification_revision()),
        "facts": {
            "phase": "qualify", "lifecycle": "joined-clean", "login": None, "mode": None,
            "relay_closed": True, "custody_current": True,
            "credential_closed": True, "process_clean": True,
            "qualification": {
                "lifecycle": "qualified", "initialize_verdict": "mode-match",
                "settings_verdict": "match", "hooks_verdict": "match",
                "request_writes": 3, "ui_records": 0, "stdin_closed": True, "eof": True,
                "selected_plan": "max", "model": config.model, "effort": config.effort,
            },
        },
        "runtime_digest": str(config.runtime_digest), "vendor_digest": str(config.vendor_digest),
        "launch_policy_sha256": config.launch_policy_sha256,
        "launch_config_sha256": config.configuration_sha256,
        "launch_revision": str(launcher.revision),
        "egress": {name: str(value) for name, value in
                   identity_digests(config.egress["observe"]).items()},
    }
    return config, record, tmp_path / "evidence.json"


def seal(record, path):
    path.write_text(canonical_json(record), encoding="utf-8")
    revision = digest(claude_lane.EVIDENCE_DOMAIN, 1, record)
    other = digest("test", 1, "non-secret")
    return NativeOperatorStoreIdentityV1(
        operator_binding_digest=other, layout_law_digest=other, mount_lock_law_digest=other,
        subscription_mode_adapter_revision=revision, store_conformance_revision=revision,
    )


@pytest.mark.parametrize("name,expected", [("pro", ClaudePlan.PRO), ("max", ClaudePlan.MAX)])
def test_complete_sealed_startup_permits_compatible_subscription(case, name, expected):
    config, record, path = case
    record["facts"]["qualification"]["selected_plan"] = name
    path.write_text(canonical_json(record), encoding="utf-8")
    assert claude_host.validate_startup_evidence(path, config) == (
        expected, digest(claude_lane.EVIDENCE_DOMAIN, 1, record),
    )
    assert claude_host.sealed_plan(seal(record, path), path, config) is expected
    profile, grants = claude_host.read_profile(config), claude_host.read_grants(config)
    assert profile.grant_faults(grants) == ()
    assert grants.allowed_tools == ("read_file",)
    assert grants.timeout_s == 120
    assert profile.account_assurance == "operator_bound_vendor_identity_unverified"


@pytest.mark.parametrize("scope,field,value", [
    ("record", "schema_version", True), ("record", "completed", False),
    ("record", "subscription_qualified", True), ("record", "production_available", True),
    ("facts", "phase", "observe"), ("facts", "lifecycle", "incomplete"),
    ("facts", "login", {}), ("facts", "mode", {}),
    *(('facts', field, value) for field in (
        "relay_closed", "custody_current", "credential_closed", "process_clean",
    ) for value in (False, None, 1)),
    ("qualification", "lifecycle", "incomplete"),
    ("qualification", "initialize_verdict", "mode-mismatch"),
    ("qualification", "settings_verdict", "configuration-mismatch"),
    ("qualification", "hooks_verdict", "configuration-mismatch"),
    *(('qualification', 'request_writes', value) for value in (0, 2, 4, 3.0, True)),
    *(('qualification', 'ui_records', value) for value in (-1, 9, False, 0.0)),
    ("qualification", "stdin_closed", False), ("qualification", "eof", False),
    ("qualification", "selected_plan", "api"), ("qualification", "selected_plan", None),
    ("qualification", "model", "other-model"), ("qualification", "effort", "high"),
    *(('record', field, 'changed') for field in (
        "runtime_digest", "vendor_digest", "launch_policy_sha256", "launch_config_sha256",
        "launch_revision", "egress", "qualification_revision",
    )),
])
def test_each_affirmative_fact_is_required_even_when_record_is_sealed(case, scope, field, value):
    config, record, path = case
    target = record if scope == "record" else record["facts"]
    if scope == "qualification":
        target = target["qualification"]
    target[field] = value
    path.write_text(canonical_json(record), encoding="utf-8")
    with pytest.raises(ContractViolation):
        claude_host.validate_startup_evidence(path, config)
    with pytest.raises(ContractViolation):
        claude_host.sealed_plan(seal(record, path), path, config)


def test_sealed_validation_reads_one_snapshot_and_reuses_its_digest(case, monkeypatch):
    config, record, path = case
    store = seal(record, path)
    original = claude_host._evidence
    reads = []

    def read(candidate):
        reads.append(candidate)
        assert reads == [path]
        return original(candidate)

    monkeypatch.setattr(claude_host, "_evidence", read)
    assert claude_host.sealed_plan(store, path, config) is ClaudePlan.MAX
    assert reads == [path]


@pytest.mark.parametrize("scope", ["record", "facts", "qualification"])
def test_new_or_missing_evidence_fields_refuse(case, scope):
    config, record, path = case
    target = record if scope == "record" else record["facts"]
    if scope == "qualification":
        target = target["qualification"]
    target["unreviewed"] = True
    with pytest.raises(ContractViolation):
        claude_host.sealed_plan(seal(record, path), path, config)
    del target["unreviewed"]
    del target[next(iter(target))]
    with pytest.raises(ContractViolation):
        claude_host.sealed_plan(seal(record, path), path, config)


@pytest.mark.parametrize("field", [
    "subscription_mode_adapter_revision", "store_conformance_revision",
])
def test_both_sealed_revisions_name_exact_evidence(case, field):
    config, record, path = case
    store = seal(record, path).model_copy(update={field: digest("other", 1, {})})
    with pytest.raises(ContractViolation, match="sealed"):
        claude_host.sealed_plan(store, path, config)


def test_duplicate_json_does_not_become_a_passing_record(case):
    config, record, path = case
    store = seal(record, path)
    raw = path.read_text(encoding="utf-8")
    path.write_text('{"completed":false,' + raw[1:], encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))["completed"] is True
    with pytest.raises(ContractViolation):
        claude_host.sealed_plan(store, path, config)


def test_operator_provider_orders_exact_config_store_and_evidence_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = configuration(tmp_path)
    config_sha = hashlib.sha256(config_path.read_bytes()).hexdigest()
    host = claude_host.ClaudeHostSession(
        configuration=config_path, configuration_sha256=config_sha,
        store_root=tmp_path / "store", store_key="reviewed-key",
        sealed=tmp_path / "sealed.json", qualification=tmp_path / "qualification.json",
        acquisition_root=tmp_path / "acquisitions",
    )
    trace: list[tuple[object, ...]] = []
    store = SimpleNamespace(store_conformance_revision=digest("test-store", 1, "sealed"))
    real_read = claude_lane.read_configuration
    config = real_read(config_path, expected_sha256=config_sha)
    monkeypatch.setattr(claude_host, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(claude_host, "os", SimpleNamespace(getuid=lambda: 1001))

    def read(path: Path, *, expected_sha256: str):
        trace.append(("config", path, expected_sha256))
        return real_read(path, expected_sha256=expected_sha256)

    def sealed(path: Path, uid: int):
        trace.append(("sealed", path, uid))
        return store

    def evidence(actual_store: object, path: Path, actual_config: object):
        trace.append(("evidence", actual_store, path, actual_config))
        return ClaudePlan.MAX

    def provider(**kwargs: object):
        trace.append(("provider", kwargs))
        return kwargs

    monkeypatch.setattr(claude_lane, "read_configuration", read)
    monkeypatch.setattr(claude_host, "_sealed_file", sealed)
    monkeypatch.setattr(claude_host, "sealed_plan", evidence)
    monkeypatch.setattr(claude_host, "identity_fields", lambda *args, **kwargs: {})
    monkeypatch.setattr(claude_host, "NativeOperatorLaunchIdentityV3", lambda **kwargs: kwargs)
    monkeypatch.setattr(claude_host, "BindingStore", lambda *args: args)
    monkeypatch.setattr(claude_host, "AcquisitionClosure", lambda authority: authority)
    monkeypatch.setattr(claude_host, "ClaudeOperatorProvider", provider)
    workspace = SimpleNamespace(authority=object())
    worker = object()
    authorization = object()
    result = claude_host.operator_provider(
        host, workspace=workspace, workspace_capability_id="claude-read-workspace",
        workspace_revision="reviewed-revision", expected_base="a" * 40,
        worker_launcher=worker, authorization=authorization,
    )
    assert trace[:3] == [
        ("config", config_path, config_sha),
        ("sealed", host.sealed, 1001),
        ("evidence", store, host.qualification, config),
    ]
    assert trace[3][0] == "provider"
    assert result["worker_launcher"] is worker
    assert result["workspace_provider"] is workspace
    assert result["binding_store"] == (host.store_root, host.store_key, store)
    assert result["closure"] is workspace.authority
    assert result["selected_plan"] is ClaudePlan.MAX
    assert result["qualification"] is authorization
    assert result["launcher"] == config.launcher(ClaudeMaintenanceSessionPhase.OBSERVE)
    assert result["egress"] == config.egress["observe"]


def test_operator_provider_refuses_before_downstream_reads_or_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = configuration(tmp_path)
    host = claude_host.ClaudeHostSession(
        configuration=config_path,
        configuration_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
        store_root=tmp_path / "store", store_key="reviewed-key",
        sealed=tmp_path / "sealed.json", qualification=tmp_path / "qualification.json",
        acquisition_root=tmp_path / "acquisitions",
    )
    calls: list[str] = []
    real_read = claude_lane.read_configuration

    def read(path: Path, *, expected_sha256: str):
        calls.append("config")
        return real_read(path, expected_sha256=expected_sha256)

    def sealed(*args: object) -> object:
        calls.append("sealed")
        return object()

    monkeypatch.setattr(claude_lane, "read_configuration", read)
    monkeypatch.setattr(claude_host, "_sealed_file", sealed)
    monkeypatch.setattr(claude_host, "sealed_plan", lambda *args: calls.append("evidence"))
    monkeypatch.setattr(claude_host, "ClaudeOperatorProvider",
                        lambda **kwargs: calls.append("provider"))
    arguments = dict(workspace=SimpleNamespace(authority=object()),
                     workspace_capability_id="claude-read-workspace",
                     workspace_revision="reviewed-revision", expected_base="a" * 40,
                     worker_launcher=object())
    monkeypatch.setattr(claude_host, "sys", SimpleNamespace(platform="win32"))
    with pytest.raises(ContractViolation, match="requires Linux"):
        claude_host.operator_provider(host, **arguments)
    assert calls == []
    monkeypatch.setattr(claude_host, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(claude_host, "os", SimpleNamespace(getuid=lambda: 1001))
    wrong_sha = claude_host.ClaudeHostSession(**{
        **host.__dict__, "configuration_sha256": "0" * 64,
    })
    with pytest.raises(ValueError, match="reviewed bytes"):
        claude_host.operator_provider(wrong_sha, **arguments)
    assert calls == ["config"]
    calls.clear()
    def bad_sealed(*args: object) -> None:
        calls.append("sealed")
        raise ContractViolation("unsealed")

    monkeypatch.setattr(claude_host, "_sealed_file", bad_sealed)
    with pytest.raises(ContractViolation, match="unsealed"):
        claude_host.operator_provider(host, **arguments)
    assert calls == ["config", "sealed"]
    calls.clear()

    def bad_evidence(*args: object) -> None:
        calls.append("evidence")
        raise ContractViolation("not qualified")

    monkeypatch.setattr(claude_host, "_sealed_file", sealed)
    monkeypatch.setattr(claude_host, "sealed_plan", bad_evidence)
    with pytest.raises(ContractViolation, match="not qualified"):
        claude_host.operator_provider(host, **arguments)
    assert calls == ["config", "sealed", "evidence"]
