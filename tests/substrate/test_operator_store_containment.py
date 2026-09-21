"""Credential-free Linux proofs; portable doubles earn no physical credit."""

import asyncio
import json
import os
import sys
from contextlib import suppress
from pathlib import Path

import pytest

from constructicon.core.grants import Posture
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.executors.linux import NativeStoreMount
from constructicon.substrate.executors.operator_store import BindingStore
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence

KEY = "n3a-fixture"


@pytest.fixture
def binding():
    location = os.environ.get("M8_OPERATOR_STORE_ROOT")
    if not location or sys.platform != "linux":
        if os.environ.get("M8_OPERATOR_STORE_REQUIRED"):
            pytest.fail("required N3a Linux store fixture is absent")
        pytest.skip("N3a physical store custody requires the provisioned Linux lane")
    root = Path(location)
    sealed = NativeOperatorStoreIdentityV1.model_validate_json(
        (root.parent / "operator-store-fixture.json").read_text(),
    )
    return BindingStore(root, KEY, sealed)


async def no_closure():
    """This direct physical-store proof owns no durable graph acquisition."""


async def hold(binding):
    return await binding.acquire_lock(
        binding.open_candidate(), check_control=lambda: None, check_closure=no_closure,
    )


async def collect(io):
    await io.close_stdin()
    while await io.read():
        pass


async def test_only_native_can_read_and_write_the_store_with_no_private_fds(
    binding, launcher, tmp_path,
):
    held = await hold(binding)
    paths = AcquisitionPaths(tmp_path, acquisition_id_for("n3a-mount-proof", 1))
    source = """
import json, os
from pathlib import Path
root = Path('/vendor-store')
marker = root / 'fixture-marker'
facts = {'read': marker.read_text() == 'harmless fixture\\n'}
(root / 'write-probe').write_text('harmless native write')
facts['write'] = (root / 'write-probe').read_text() == 'harmless native write'
(root / 'write-probe').unlink()
# Vendor state may grow directories as well as files. The physical root stays
# the same; its changing link count is not a binding-generation change.
(root / 'session-fixture').mkdir()
(root / 'session-fixture' / 'state').write_text('harmless session')
facts['subdirectory_write'] = (root / 'session-fixture' / 'state').is_file()
facts['metadata_absent'] = not (root / 'anchor.json').exists()
facts['lock_absent'] = not (root / 'retained.lock').exists()
facts['private_parent_absent'] = not Path(PRIVATE_PARENT).exists()
try:
    os.rename(root, '/tmp/rebound-store')
except OSError:
    facts['root_cannot_be_replaced'] = True
else:
    facts['root_cannot_be_replaced'] = False
facts['home_disposable'] = os.environ['HOME'] == '/tmp/home'
facts['workspace_absent'] = not any(Path('/workspace').iterdir())
private_fds = []
for fd in Path('/proc/self/fd').iterdir():
    try:
        target = os.readlink(fd)
    except FileNotFoundError:
        continue
    if 'retained.lock' in target or '/guards/' in target or 'anchor.json' in target:
        private_fds.append(fd.name)
facts['private_fds_absent'] = not private_fds
print(json.dumps(facts), flush=True)
"""
    source = source.replace("PRIVATE_PARENT", repr(str(held.store_path.parent)))
    try:
        async with acquisition_guard(paths) as guard:
            result = await launcher.exchange(
                ("/usr/bin/python3", "-I", "-c", source), workspace=None,
                posture=Posture.READ, guard_fds=(guard, held.lock_fd), timeout_s=10,
                conversation=collect,
                native_store=NativeStoreMount(
                    path=held.store_path, lock_fd=held.lock_fd,
                    before_spawn=lambda: binding.check_held(held),
                ),
            )
            assert result.returncode == result.payload_returncode == 0, result
            facts = json.loads(result.stdout)
            assert set(facts) == {
                'read', 'write', 'subdirectory_write', 'metadata_absent', 'lock_absent',
                'private_parent_absent', 'root_cannot_be_replaced',
                'home_disposable', 'workspace_absent', 'private_fds_absent',
            }, facts
            assert all(value is True for value in facts.values()), facts
            assert binding.check_held(held).binding_digest == binding.sealed.operator_binding_digest
            worker = await launcher.run(
                ("/usr/bin/python3", "-I", "-c",
                 "from pathlib import Path; print(not any(Path('/vendor-store').iterdir()))"),
                workspace=None, posture=Posture.READ, guard_fds=(guard,), timeout_s=10,
            )
            assert worker.returncode == worker.payload_returncode == 0, worker
            assert worker.stdout.strip() == b"True"
            write_evidence("n3a-native-store.json", {
                "schema_version": 1, "credential_free_fixture": True,
                "vendor_conformance_qualified": False,
                "launch_revision": str(launcher.revision),
                "binding_digest": str(binding.sealed.operator_binding_digest),
                "native_facts": facts, "ordinary_worker_store_absent": True,
                "terminal_binding_check_completed": True,
            })
    finally:
        # Fixture data only; retain the directory through the terminal check.
        child = held.store_path / 'session-fixture'
        if child.is_dir():
            (child / 'state').unlink(missing_ok=True)
            child.rmdir()
        binding.close_held(held)


async def test_store_lock_waits_and_hands_off_without_reacquisition(binding):
    held = await hold(binding)
    contender = asyncio.create_task(hold(binding))
    try:
        await asyncio.sleep(0.1)
        assert not contender.done(), "the dedicated store admitted two holders"
        first_fd = held.lock_fd
        assert binding.check_held(held).binding_digest == binding.sealed.operator_binding_digest
        assert held.lock_fd == first_fd
    finally:
        binding.close_held(held)
    successor = await asyncio.wait_for(contender, 5)
    try:
        checked = binding.check_held(successor)
        assert checked.binding_digest == binding.sealed.operator_binding_digest
        write_evidence("n3a-lock-handoff.json", {
            "schema_version": 1, "contender_waited": True,
            "successor_checked_after_release": True,
        })
    finally:
        binding.close_held(successor)


async def test_owner_death_does_not_release_the_supervisors_store_lock(
    binding, launcher, tmp_path,
):
    owner = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.substrate._operator_store_owner", str(tmp_path),
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    contender = None
    successor = None
    try:
        assert owner.stdout is not None
        assert await asyncio.wait_for(owner.stdout.readline(), 30) == b"ready\n"
        contender = asyncio.create_task(hold(binding))
        await asyncio.sleep(0.05)
        assert not contender.done()
        owner.kill()
        # wait() may also wait for inherited stdout/stderr pipe EOF, which is
        # the descendant's death: that would observe too late to prove custody
        # survives the controller. Observe the controller's exit alone here.
        async with asyncio.timeout(5):
            while owner.returncode is None:
                await asyncio.sleep(0.01)
        # Payload ignores TERM. The existing reaper's two-second grace must
        # finish before its copy of the same store OFD can be released.
        await asyncio.sleep(0.2)
        assert not contender.done(), "controller death released a live descendant's store"
        successor = await asyncio.wait_for(asyncio.shield(contender), 8)
        check = binding.check_held(successor)
        assert check.binding_digest == binding.sealed.operator_binding_digest
        write_evidence("n3a-owner-death.json", {
            "schema_version": 1, "controller_died": owner.returncode is not None,
            "store_lock_held_during_reaper_grace": True,
            "successor_checked_after_reaping": True,
        })
    finally:
        if owner.returncode is None:
            owner.kill()
        await asyncio.wait_for(owner.communicate(), 5)
        if successor is not None:
            binding.close_held(successor)
        elif contender is not None:
            contender.cancel()
            with suppress(asyncio.CancelledError):
                remaining = await contender
                binding.close_held(remaining)
