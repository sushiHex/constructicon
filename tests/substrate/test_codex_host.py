"""The production host assembly of the operator provider (M8 N5).

Portable: the sealed-account loader, the READ profile, and the module entry.
On the provisioned Linux lane: the provider assembled from the real launch set
and vendor, as the service, plus the `mint` command over it, in-process and as
the documented `python -m` entry. Neither starts a vendor process; the host
session runs the assembly against the real generation.
"""

from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
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
from constructicon.substrate.executors.codex_protocol import named_method
from tests.substrate.test_codex_adapter import native_store

ACCOUNT = digest("test-account", 1, "operator")
INSTALLED = {
    "adapter_revision": "adapter", "protocol_revision": "protocol", "launch_revision": "launch",
    "runtime_digest": "runtime",
    "executable": {
        "path": "/codex", "sha256": "e", "catalog_sha256": "c", "sealed_catalog_sha256": "s",
    },
    "configuration_digest": "configuration", "egress": {"policy": "p"},
}
"""Synthetic launch facts; the Linux lane uses `codex_lane.launch_facts` of the host."""


def evidence(installed=INSTALLED, **changes) -> dict:
    """A closed, passing maintenance startup record, as the lane writes one."""
    record = {
        "completed": True,
        "schema_version": codex_lane.LANE_SCHEMA,
        "lane": "startup",
        "custody": {"kind": "maintenance", "generation_floor": 3},
        **installed,
        "relay": {"destinations": {"accepted:chatgpt.com:443": 2}, "denied": {}, "closed": True},
        "credential": {
            "present": True, "regular_0600": True, "mtime_changed": False, "checked": True,
        },
        "process": {
            "returncode": 0, "payload_returncode": 0, "timed_out": False,
            "bound_exceeded": False, "exchange_failed": False, "elapsed_s": 1.5,
            "stderr_bytes": 0,
        },
        "vendor_identity": "unverified",
        "vendor_conformance_qualified": False,
        "faults": [],
        "methods_sent": [named_method(item) for item in codex_lane.STARTUP_METHODS],
        "withheld_methods": [],
        "gate": {"completed": True, "plan": "pro", "account": str(ACCOUNT)},
        "readback": {"spend_control_reached": False},
        "observation": {"malformed_records": 0, "first_error": False},
        "refresh": "unmeasured",
        "hold_s": 0,
    }
    record.update(changes)
    return record


def sealed_by(record: dict, store: NativeOperatorStoreIdentityV1) -> NativeOperatorStoreIdentityV1:
    q = digest(codex_lane.EVIDENCE_DOMAIN, 1, json.loads(canonical_json(record)))
    return store.model_copy(
        update={"subscription_mode_adapter_revision": q, "store_conformance_revision": q},
    )


def written(tmp_path: Path, record: dict) -> Path:
    path = tmp_path / "s6a-qualification.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_the_sealed_account_is_the_one_the_generation_sealed(tmp_path):
    record = evidence()
    assert set(record) == codex_lane.STARTUP_FIELDS | {"completed"}
    path = written(tmp_path, record)
    account = codex_host.sealed_account(sealed_by(record, native_store()), path, INSTALLED)
    assert (account.plan_type, account.identity) == ("pro", ACCOUNT)


def test_evidence_the_generation_did_not_seal_is_refused(tmp_path):
    path = written(tmp_path, evidence())
    other = sealed_by(evidence(faults=["a different record"]), native_store())
    with pytest.raises(ContractViolation, match="not the qualification this generation sealed"):
        codex_host.sealed_account(other, path, INSTALLED)


def test_a_sealed_record_that_is_not_closed_is_refused(tmp_path):
    for record in (evidence(extra=True), {k: v for k, v in evidence().items() if k != "refresh"}):
        path = written(tmp_path, record)
        with pytest.raises(ContractViolation, match="not a closed startup record"):
            codex_host.sealed_account(sealed_by(record, native_store()), path, INSTALLED)


PASSING = evidence()


@pytest.mark.parametrize(
    "change",
    [
        {"completed": False},
        {"schema_version": codex_lane.LANE_SCHEMA - 1},
        {"lane": "login"},
        {"faults": ["a fault"]},
        {"vendor_conformance_qualified": True},
        {"custody": {"kind": "active", "binding_digest": str(ACCOUNT)}},
        {"methods_sent": []},
        {"observation": {"malformed_records": 1, "first_error": True}},
        {"gate": {"completed": False, "plan": "pro", "account": str(ACCOUNT)}},
        {"gate": {"completed": True, "plan": "plus", "account": str(ACCOUNT)}},
        {"gate": {"completed": True, "plan": "pro", "account": None}},
        {"gate": {"completed": True, "plan": "pro", "account": "not-a-digest"}},
        {"readback": {"spend_control_reached": True}},
        {"readback": None},
        {"process": {**PASSING["process"], "timed_out": True}},
        {"process": {**PASSING["process"], "returncode": 1}},
        {"relay": {**PASSING["relay"], "closed": False}},
        {"relay": {**PASSING["relay"], "denied": {"denied:destination": 1}}},
        {"credential": {**PASSING["credential"], "checked": False}},
    ],
    ids=[
        "incomplete", "schema", "lane", "faults", "conformance", "custody", "methods",
        "observation", "gate", "plan", "account", "malformed-account", "spend", "no-readback",
        "timed-out",
        "returncode", "relay-open", "relay-denied", "credential",
    ],
)
def test_a_sealed_record_that_is_not_a_passing_startup_is_refused(tmp_path, change):
    """Sealed exactly, yet not a passing maintenance startup: the digest alone is
    not trusted to mean the runbook's checks were run."""
    record = evidence(**change)
    path = written(tmp_path, record)
    with pytest.raises(ContractViolation, match="not a passing startup"):
        codex_host.sealed_account(sealed_by(record, native_store()), path, INSTALLED)


@pytest.mark.parametrize("key", sorted(INSTALLED))
def test_a_qualification_of_other_artifacts_is_refused(tmp_path, key):
    record = evidence()
    path = written(tmp_path, record)
    changed = {**INSTALLED, key: "changed since"}
    with pytest.raises(ContractViolation, match="other artifacts than are installed"):
        codex_host.sealed_account(sealed_by(record, native_store()), path, changed)


@pytest.mark.parametrize(
    "content",
    [
        json.dumps(evidence())[:-1] + ', "faults": ["hidden"]}',
        "[]",
        "",
        " " * (codex_host.MAX_EVIDENCE_BYTES + 1),
    ],
    ids=["duplicate-key", "not-an-object", "empty", "oversized"],
)
def test_evidence_that_is_not_one_bounded_unique_object_is_unavailable(tmp_path, content):
    path = tmp_path / "s6a-qualification.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ContractViolation, match="evidence is unavailable"):
        codex_host.sealed_account(native_store(), path, INSTALLED)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="a FIFO needs POSIX")
def test_a_fifo_is_refused_without_blocking(tmp_path):
    path = tmp_path / "s6a-qualification.json"
    os.mkfifo(path)
    with pytest.raises(ContractViolation, match="evidence is unavailable"):
        codex_host.sealed_account(native_store(), path, INSTALLED)


def test_the_read_profile_admits_the_read_grants_and_the_production_configuration():
    profile = codex_host.READ_PROFILE
    assert profile.grant_faults(codex_host.READ_GRANTS) == ()
    configuration = codex_lane.production_configuration()
    assert configured_model(configuration) in profile.grant_policy.model_ids
    assert configured_effort(configuration) in profile.accepted_efforts
    assert codex_host.READ_GRANTS.timeout_s == 120
    assert profile.subscription_overage == "operator_authorized"


@pytest.mark.filterwarnings("ignore:.*found in sys.modules:RuntimeWarning")
def test_the_module_entry_runs_the_importable_module_not_main(monkeypatch):
    """`python -m` executes the module as `__main__`, whose nodes the registry
    cannot import cold; the entry must hand over to the imported module."""
    from constructicon.api import qualification

    calls = []
    monkeypatch.setattr(qualification, "main", lambda: calls.append(1) or 0)
    with pytest.raises(SystemExit) as stopped:
        runpy.run_module("constructicon.api.qualification", run_name="__main__")
    assert stopped.value.code == 0 and calls == [1]


@pytest.fixture
def host(tmp_path):
    """A host session over the real launch set, with a synthetic generation:
    construction reads no store, so the sealed identity needs only be sealed."""
    location = os.environ.get("M8_OPERATOR_STORE_ROOT")
    if not location or sys.platform != "linux":
        if os.environ.get("M8_HOST_ASSEMBLY_REQUIRED"):
            pytest.fail("required host assembly lane is unprovisioned")
        pytest.skip("the host assembly proof needs the provisioned Linux lane")
    root = Path(location).parent
    session = tmp_path / "session"
    session.mkdir(mode=0o700)
    configuration = codex_lane.production_configuration()
    (session / "config.toml").write_text(configuration)
    (session / "startup-policy.json").write_text(json.dumps({
        "destinations": [["auth.openai.com", 443, "8.8.8.8"], ["chatgpt.com", 443, "8.8.4.4"]],
        "connections": 8,
    }))
    fixture = NativeOperatorStoreIdentityV1.model_validate_json(
        (root / "operator-store-fixture.json").read_text(),
    )
    launcher = codex_lane._launcher(root)
    record = evidence(codex_lane.launch_facts(
        launcher, codex_lane._policy(session / "startup-policy.json"),
        codex_lane.vendor_executable(launcher), configuration,
    ))
    (session / "s6a-qualification.json").write_text(json.dumps(record))
    sealed = session / "g4.sealed.json"
    fd = os.open(sealed, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(sealed_by(record, fixture).model_dump_json())
    # Short and its own: the native egress socket path is bounded to 107 bytes.
    state = Path(tempfile.mkdtemp(prefix="h", dir="/tmp"))
    try:
        subprocess.run(
            ["git", "init", "--bare", "-q", str(state / "closure.git")],
            stdin=subprocess.DEVNULL, check=True, capture_output=True,
        )
        yield codex_host.HostSession(
            session=session, store_key="n3a-fixture", sealed=sealed,
            qualification=session / "s6a-qualification.json", state=state,
            launch_root=root,
        )
    finally:
        shutil.rmtree(state)


def flags(host) -> list[str]:
    return [
        "--session", str(host.session), "--store-key", host.store_key,
        "--sealed", str(host.sealed), "--qualification", str(host.qualification),
        "--state", str(host.state),
    ]


MINT = [
    "--authorization-id", "twin", "--actor", "operator:twin", "--key", "stage1",
]


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


def test_an_unprepared_state_directory_is_refused_before_it_is_touched(host, tmp_path):
    bare = tmp_path / "unprepared"
    bare.mkdir()
    with pytest.raises(ContractViolation, match="not this host's prepared state"):
        codex_host.operator_provider(
            codex_host.HostSession(**{**host.__dict__, "state": bare}),
        )
    assert list(bare.iterdir()) == []


def test_mint_prints_the_pins_of_this_host(host, capsys):
    from constructicon.api import qualification

    journal = ["--journal", str(host.state / "journal.sqlite")]
    assert qualification.main(["mint", *flags(host), *MINT, *journal]) == 0
    printed = json.loads(capsys.readouterr().out)
    provider = codex_host.operator_provider(host)
    assert printed["revision"] == provider.identity.revision
    store = provider.identity.store
    assert printed["operator_binding_digest"] == str(store.operator_binding_digest)
    assert printed["stage"] == "qualification-no-dispatch" and printed["max_epoch"] == 1


def test_the_documented_module_entry_mints_the_importable_graph(host, capsys):
    """The runbook runs `python -m`; its graph must be the one `run` registers."""
    from constructicon.api import qualification

    journal = ["--journal", str(host.state / "journal.sqlite")]
    qualification.main(["mint", *flags(host), *MINT, *journal])
    in_process = json.loads(capsys.readouterr().out)
    completed = subprocess.run(
        [sys.executable, "-m", "constructicon.api.qualification", "mint", *flags(host), *MINT,
         *journal],
        stdin=subprocess.DEVNULL, check=True, capture_output=True, text=True,
    )
    entry = json.loads(completed.stdout)
    assert entry["source_graph_hash"] == in_process["source_graph_hash"]
