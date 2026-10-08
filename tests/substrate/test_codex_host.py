"""The production host assembly of the operator provider (M8 N5).

Portable: the sealed-account loader and the READ profile. On the provisioned
Linux lane: the provider assembled from the real launch set and vendor, as the
service, plus the `mint` command over it. Neither starts a vendor process; the
host session runs the assembly against the real generation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import canonical_json, digest
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.substrate.executors import codex_host, codex_lane
from constructicon.substrate.executors.codex import (
    UNQUALIFIED_PREREQUISITES,
    configured_effort,
    configured_model,
)
from tests.substrate.test_codex_adapter import native_store

ACCOUNT = digest("test-account", 1, "operator")


def evidence(**changes) -> dict:
    record = {
        "completed": True,
        "schema_version": codex_lane.LANE_SCHEMA,
        "lane": "startup",
        "faults": [],
        "custody": {"kind": "maintenance", "generation_floor": 3},
        "gate": {"completed": True, "plan": "pro", "account": str(ACCOUNT)},
    }
    record.update(changes)
    return record


def sealed_by(record: dict, store: NativeOperatorStoreIdentityV1) -> NativeOperatorStoreIdentityV1:
    q = digest(codex_lane.EVIDENCE_DOMAIN, 1, json.loads(canonical_json(record)))
    return store.model_copy(
        update={"subscription_mode_adapter_revision": q, "store_conformance_revision": q},
    )


def test_the_sealed_account_is_the_one_the_generation_sealed(tmp_path):
    record = evidence()
    path = tmp_path / "s6a-qualification.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    account = codex_host.sealed_account(sealed_by(record, native_store()), path)
    assert (account.plan_type, account.identity) == ("pro", ACCOUNT)


def test_evidence_the_generation_did_not_seal_is_refused(tmp_path):
    path = tmp_path / "s6a-qualification.json"
    path.write_text(json.dumps(evidence()), encoding="utf-8")
    other = sealed_by(evidence(faults=["a different record"]), native_store())
    with pytest.raises(ContractViolation, match="not the qualification this generation sealed"):
        codex_host.sealed_account(other, path)


@pytest.mark.parametrize(
    "change",
    [
        {"completed": False},
        {"schema_version": codex_lane.LANE_SCHEMA - 1},
        {"lane": "login"},
        {"faults": ["a fault"]},
        {"custody": {"kind": "active", "binding_digest": str(ACCOUNT)}},
        {"gate": {"completed": False, "plan": "pro", "account": str(ACCOUNT)}},
        {"gate": {"completed": True, "plan": "plus", "account": str(ACCOUNT)}},
        {"gate": {"completed": True, "plan": "pro", "account": None}},
    ],
    ids=["incomplete", "schema", "lane", "faults", "custody", "gate", "plan", "account"],
)
def test_a_sealed_record_that_is_not_a_passing_startup_is_refused(tmp_path, change):
    """Sealed exactly, yet not a passing maintenance startup: the digest alone is
    not trusted to mean the runbook's checks were run."""
    record = evidence(**change)
    path = tmp_path / "qualification.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ContractViolation, match="not a passing startup"):
        codex_host.sealed_account(sealed_by(record, native_store()), path)


def test_the_read_profile_admits_the_read_grants_and_the_production_configuration():
    profile = codex_host.READ_PROFILE
    assert profile.grant_faults(codex_host.READ_GRANTS) == ()
    configuration = codex_lane.production_configuration()
    assert configured_model(configuration) in profile.grant_policy.model_ids
    assert configured_effort(configuration) in profile.accepted_efforts
    assert codex_host.READ_GRANTS.timeout_s == 120
    assert profile.subscription_overage == "operator_authorized"


@pytest.fixture
def host(tmp_path) -> codex_host.HostSession:
    """A host session over the real launch set, with a synthetic generation:
    construction reads no store, so the sealed identity needs only be sealed."""
    location = os.environ.get("M8_OPERATOR_STORE_ROOT")
    if not location or sys.platform != "linux":
        if os.environ.get("M8_HOST_ASSEMBLY_REQUIRED"):
            pytest.fail("required host assembly lane is unprovisioned")
        pytest.skip("the host assembly proof needs the provisioned Linux lane")
    session = tmp_path / "session"
    session.mkdir(mode=0o700)
    (session / "config.toml").write_text(codex_lane.production_configuration())
    (session / "startup-policy.json").write_text(json.dumps({
        "destinations": [["auth.openai.com", 443, "192.0.2.1"], ["chatgpt.com", 443, "192.0.2.2"]],
        "connections": 8,
    }))
    fixture = NativeOperatorStoreIdentityV1.model_validate_json(
        (Path(location).parent / "operator-store-fixture.json").read_text(),
    )
    record = evidence()
    (session / "s6a-qualification.json").write_text(json.dumps(record))
    sealed = session / "g4.sealed.json"
    fd = os.open(sealed, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(sealed_by(record, fixture).model_dump_json())
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    subprocess.run(
        ["git", "init", "--bare", "-q", str(state / "closure.git")],
        stdin=subprocess.DEVNULL, check=True, capture_output=True,
    )
    return codex_host.HostSession(
        session=session, store_key="n3a-fixture", sealed=sealed,
        qualification=session / "s6a-qualification.json", state=state,
        launch_root=Path(location).parent,
    )


def test_the_production_provider_assembles_from_host_facts_and_stays_unavailable(host):
    provider = codex_host.operator_provider(host)
    assert provider.unavailable_reasons == UNQUALIFIED_PREREQUISITES
    assert provider.identity.profile == codex_host.READ_PROFILE
    assert provider.expected_account.identity == ACCOUNT
    q = provider.identity.store.subscription_mode_adapter_revision
    assert provider.identity.egress.physical_conformance_revision == q
    assert provider.identity.authenticated_startup_conformance_revision == q
    assert provider.qualification is None


def test_a_session_configuration_other_than_production_is_refused(host):
    (host.session / "config.toml").write_text(codex_lane.production_configuration(control=True))
    with pytest.raises(ContractViolation, match="not the production configuration"):
        codex_host.operator_provider(host)


def test_mint_prints_the_pins_of_this_host(host, capsys):
    from constructicon.api import qualification

    flags = [
        "--session", str(host.session), "--store-key", host.store_key,
        "--sealed", str(host.sealed), "--qualification", str(host.qualification),
        "--state", str(host.state),
    ]
    assert qualification.main([
        "mint", *flags, "--authorization-id", "twin", "--actor", "operator:twin",
        "--key", "stage1", "--journal", str(host.state / "journal.sqlite"),
    ]) == 0
    printed = json.loads(capsys.readouterr().out)
    provider = codex_host.operator_provider(host)
    assert printed["revision"] == provider.identity.revision
    store = provider.identity.store
    assert printed["operator_binding_digest"] == str(store.operator_binding_digest)
    assert printed["stage"] == "qualification-no-dispatch" and printed["max_epoch"] == 1
