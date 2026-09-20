"""Real interpreter restarts over protected, harmless Linux configuration.

Run only as the provisioning principal on the disposable CI host. This is not
an operator maintenance workflow, account access, or credential-host deployment.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import canonical_json, digest
from constructicon.substrate.executors import operator_store as stores
from tests.substrate.test_native_codex_mediation import write_evidence

KEY = "restart-fixture"
READER = """
import asyncio, sys
from pathlib import Path
from constructicon.core.errors import ContractViolation
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.substrate.executors.operator_store import BindingStore
async def check_closure(): pass
async def main():
    store = BindingStore(Path(sys.argv[1]), 'restart-fixture',
        NativeOperatorStoreIdentityV1.model_validate_json(sys.argv[2]))
    held = None
    try:
        held = await store.acquire_lock(store.open_candidate(), lambda: None, check_closure)
        check = store.check_held(held)
        assert check.binding_digest == store.sealed.operator_binding_digest
    except ContractViolation:
        print('refused')
    else:
        print('accepted')
    finally:
        if held is not None: store.close_held(held)
asyncio.run(main())
"""


@pytest.fixture
def protected_root():
    required = os.environ.get("M8_STORE_PROVISION_REQUIRED")
    if not required or sys.platform != "linux" or os.geteuid() != 0:
        if required:
            pytest.fail("required N3a provisioning proof needs the disposable Linux root principal")
        pytest.skip("real N3a descriptor/restart proof requires protected Linux provisioning")
    if os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        pytest.fail("N3a provisioning proof is restricted to the disposable hosted runner")
    parent = Path("/var/lib/constructicon-m8-launch")
    assert parent.is_dir() and not parent.is_symlink()
    root = Path(tempfile.mkdtemp(prefix="n3a-restart-", dir=parent))
    try:
        yield root
    finally:
        assert root.resolve().parent == parent and root.name.startswith("n3a-restart-")
        shutil.rmtree(root)


def publish(root, generation):
    return stores.publish_descriptor_offline(
        root, KEY, generation, runtime_uid=os.getuid(),
        subscription_mode_adapter_revision=digest("n3a-fixture-only", 1, "mode-unqualified"),
        store_conformance_revision=digest("n3a-fixture-only", 1, "vendor-unqualified"),
    )


def activate_fixture(root, generation):
    """Explicit test input; intentionally not a production activation API."""
    bundle = root / stores._bundle_token(KEY)
    descriptor = stores._descriptor((bundle / "descriptors" / f"{generation}.json").read_bytes())
    selection = {
        "schema_version": 1, "key": KEY, "generation": generation,
        "binding_digest": str(descriptor.binding_digest),
        "descriptor_digest": str(descriptor.descriptor_digest),
    }
    path = bundle / "active.json"
    path.write_text(canonical_json(selection), encoding="utf-8")
    path.chmod(0o440)


def fresh_read(root, sealed):
    result = subprocess.run(
        [sys.executable, "-c", READER, str(root), sealed.model_dump_json()],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, "fresh interpreter failed before making its binding observation"
    assert result.stderr == "", "fresh interpreter emitted unexpected diagnostic evidence"
    assert result.stdout.strip() in {"accepted", "refused"}
    return result.stdout.strip()


@pytest.mark.parametrize("replaced", ["store", "retained.lock"])
def test_real_restart_accepts_unchanged_root_and_refuses_same_path_replacement(
    protected_root, replaced,
):
    root = protected_root
    sealed = publish(root, 1)
    activate_fixture(root, 1)
    assert fresh_read(root, sealed) == "accepted"
    assert fresh_read(root, sealed) == "accepted"
    bundle = root / stores._bundle_token(KEY)
    retained = (bundle / "descriptors" / "1.json").read_bytes()
    target = bundle / replaced
    if replaced == "store":
        target.rmdir()
        target.mkdir(mode=0o700)
    else:
        target.unlink()
        target.touch(mode=0o600)
    assert fresh_read(root, sealed) == "refused"
    assert (bundle / "descriptors" / "1.json").read_bytes() == retained
    write_evidence(f"n3a-restart-{replaced}.json", {
        "schema_version": 1, "fresh_interpreters_accepted_unchanged": 2,
        "same_path_replacement_refused": True, "descriptor_bytes_preserved": True,
    })


def test_publication_is_no_replace_and_never_an_activation(protected_root):
    root = protected_root
    first = publish(root, 1)
    assert fresh_read(root, first) == "refused"
    activate_fixture(root, 1)
    assert fresh_read(root, first) == "accepted"
    path = root / stores._bundle_token(KEY) / "descriptors" / "1.json"
    original = path.read_bytes()
    refused = False
    try:
        publish(root, 1)
    except ContractViolation:
        refused = True
    assert refused and path.read_bytes() == original
    second = publish(root, 2)
    assert fresh_read(root, first) == "accepted"
    assert fresh_read(root, second) == "refused"
    activate_fixture(root, 2)
    assert fresh_read(root, first) == "refused"
    assert fresh_read(root, second) == "accepted"
    (root / stores._bundle_token(KEY) / "active.json").unlink()
    assert fresh_read(root, second) == "refused"
    write_evidence("n3a-generation-publication.json", {
        "schema_version": 1, "publication_did_not_activate": True,
        "duplicate_generation_refused_without_overwrite": True,
        "explicit_selection_checked_in_fresh_interpreters": True,
        "absent_selection_refused": True,
    })


def test_retained_descriptor_contains_no_credential_observation(protected_root):
    sealed = publish(protected_root, 1)
    bundle = protected_root / stores._bundle_token(KEY)
    raw = json.loads((bundle / "descriptors" / "1.json").read_text())
    assert set(sealed.model_dump()) == {
        "schema_version", "operator_binding_digest", "layout_law_digest",
        "mount_lock_law_digest", "subscription_mode_adapter_revision",
        "store_conformance_revision",
    }
    assert set(raw) == {
        "schema_version", "key", "generation", "store_instance_id", "binding_digest",
        "bundle", "store", "lock", "layout_law_digest", "mount_lock_law_digest",
    }


@pytest.mark.parametrize("alias", ["store-symlink", "lock-hardlink"])
def test_physical_alias_refuses_and_removing_alias_restores_exact_binding(protected_root, alias):
    sealed = publish(protected_root, 1)
    activate_fixture(protected_root, 1)
    assert fresh_read(protected_root, sealed) == "accepted"


    bundle = protected_root / stores._bundle_token(KEY)
    if alias == "store-symlink":
        original = bundle / "store"
        moved = bundle / "moved-store"
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
        try:
            assert fresh_read(protected_root, sealed) == "refused"
        finally:
            original.unlink()
            moved.rename(original)
    else:
        link = bundle / "lock-alias"
        link.hardlink_to(bundle / "retained.lock")
        try:
            assert fresh_read(protected_root, sealed) == "refused"
        finally:
            link.unlink()
    assert fresh_read(protected_root, sealed) == "accepted"


@pytest.mark.parametrize("name", ["anchor.json", "active.json", "descriptors/1.json"])
def test_fifo_metadata_refuses_without_waiting_for_a_writer(protected_root, name):
    sealed = publish(protected_root, 1)
    activate_fixture(protected_root, 1)
    assert fresh_read(protected_root, sealed) == "accepted"
    target = protected_root / stores._bundle_token(KEY) / name
    target.unlink()
    os.mkfifo(target, 0o600)
    try:
        observed = fresh_read(protected_root, sealed)
    except subprocess.TimeoutExpired:
        pytest.fail("metadata FIFO blocked before its nonregular-file refusal")
    assert observed == "refused"
