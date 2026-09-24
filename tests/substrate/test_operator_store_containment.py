"""Credential-free Linux proofs; portable doubles earn no physical credit."""

import asyncio
import errno
import json
import os
import sys
from contextlib import contextmanager, suppress
from pathlib import Path

import pytest

from constructicon.core.grants import Posture
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.core.workspace import acquisition_id_for
from constructicon.substrate.executors.linux import NativeStoreMount, sealed_data_fd
from constructicon.substrate.executors.operator_store import BindingStore
from constructicon.substrate.git.acquisition import AcquisitionPaths, acquisition_guard
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence

KEY = "n3a-fixture"
CREDENTIAL = b"harmless fixture\n"
"""The CI fixture's bytes at the store's one file (``build_m8_store_fixture.py``)."""
CONFIGURATION = b'model = "fixture-only"\n'


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


@contextmanager
def native_mount(binding, held, *, before_spawn=None, egress=None, configuration=CONFIGURATION):
    """The production layout's two descriptors for one launch, then closed.

    The same calls the Codex handle makes: the credential opened relative to
    the held store and checked, the configuration as a sealed memfd.
    """

    credential = binding.open_credential(held)
    try:
        sealed = sealed_data_fd(configuration)
    except BaseException:
        os.close(credential)
        raise
    try:
        yield NativeStoreMount(
            lock_fd=held.lock_fd, configuration_fd=sealed, credential_fd=credential,
            before_spawn=before_spawn or (lambda: binding.check_held(held)), egress=egress,
        )
    finally:
        os.close(credential)
        os.close(sealed)


def normalized(argv):
    """A launch's arguments with only the two per-launch descriptor numbers erased."""

    values = list(argv)
    for flag in ("--ro-bind-data", "--bind-fd"):
        values[values.index(flag) + 1] = "<fd>"
    return tuple(values)


async def collect(io):
    await io.close_stdin()
    while await io.read():
        pass


LAYOUT = r"""
import errno, json, os
from pathlib import Path
home = Path('/tmp/home/.codex')
credential, config = home / 'auth.json', home / 'config.toml'

def errno_of(action):
    try:
        action()
    except OSError as exc:
        return exc.errno
    return 0

facts = {'read': credential.read_bytes() == CREDENTIAL}
# The pinned client's own save pattern: truncate and rewrite the same inode.
with open(credential, 'r+b') as stream:
    stream.truncate(0)
    stream.write(b'native rewrite\n')
    stream.flush()
    os.fsync(stream.fileno())
facts['write'] = credential.read_bytes() == b'native rewrite\n'
staged = home / 'auth.json.pending'
staged.write_bytes(b'replacement\n')
facts['rename_errno'] = errno_of(lambda: os.replace(staged, credential))
facts['unlink_errno'] = errno_of(lambda: credential.unlink())
staged.unlink()
facts['config'] = config.read_bytes() == CONFIGURATION
facts['config_write_errno'] = errno_of(lambda: config.write_bytes(b'model = "decoy"\n'))
facts['home_entries'] = sorted(os.listdir(home))
facts['codex_home'] = os.environ.get('CODEX_HOME')
facts['home'] = os.environ.get('HOME')
facts['store_absent'] = not Path('/vendor-store').exists()
facts['private_parent_absent'] = not Path(PRIVATE_PARENT).exists()
facts['workspace_absent'] = not any(Path('/workspace').iterdir())
private_fds = []
for fd in Path('/proc/self/fd').iterdir():
    try:
        target = os.readlink(fd)
    except FileNotFoundError:
        continue
    if any(name in target for name in (
        'retained.lock', '/guards/', 'anchor.json', 'auth.json', 'memfd:',
    )):
        private_fds.append(fd.name)
facts['private_fds'] = private_fds
print(json.dumps(facts), flush=True)
"""


async def test_the_native_layout_binds_only_the_credential_and_the_sealed_configuration(
    binding, launcher, tmp_path,
):
    """L1 (M8-N4-state-review.md): two host objects in a disposable home."""

    held = await hold(binding)
    paths = AcquisitionPaths(tmp_path, acquisition_id_for("n4-layout-proof", 1))
    source = (
        LAYOUT.replace("PRIVATE_PARENT", repr(str(held.store_path.parent)))
        .replace("CREDENTIAL", repr(CREDENTIAL)).replace("CONFIGURATION", repr(CONFIGURATION))
    )
    host_credential = held.store_path / "auth.json"
    inode = host_credential.stat().st_ino
    try:
        async with acquisition_guard(paths) as guard:
            with native_mount(binding, held) as mount:
                result = await launcher.exchange(
                    ("/usr/bin/python3", "-I", "-c", source), workspace=None,
                    posture=Posture.READ, guard_fds=(guard, held.lock_fd), timeout_s=10,
                    conversation=collect, native_store=mount,
                )
            assert result.returncode == result.payload_returncode == 0, result
            facts = json.loads(result.stdout)
            denied = {errno.EROFS, errno.EACCES, errno.EPERM}
            assert facts["read"] is True and facts["write"] is True, facts
            assert facts["rename_errno"] == errno.EBUSY, facts
            assert facts["unlink_errno"] == errno.EBUSY, facts
            assert facts["config"] is True and facts["config_write_errno"] in denied, facts
            assert facts["home_entries"] == ["auth.json", "config.toml"], facts
            assert facts["codex_home"] == "/tmp/home/.codex" and facts["home"] == "/tmp/home"
            assert facts["store_absent"] and facts["private_parent_absent"], facts
            assert facts["workspace_absent"] and facts["private_fds"] == [], facts
            # The zone's write reached the store's own inode, through the bind.
            assert host_credential.read_bytes() == b"native rewrite\n"
            assert host_credential.stat().st_ino == inode
            assert sorted(os.listdir(held.store_path)) == ["auth.json"]
            assert binding.check_held(held).binding_digest == binding.sealed.operator_binding_digest
            worker = await launcher.run(
                ("/usr/bin/python3", "-I", "-c",
                 "from pathlib import Path; print(not Path('/vendor-store').exists() "
                 "and not Path('/tmp/home/.codex').exists())"),
                workspace=None, posture=Posture.READ, guard_fds=(guard,), timeout_s=10,
            )
            assert worker.returncode == worker.payload_returncode == 0, worker
            assert worker.stdout.strip() == b"True"
            write_evidence("n3a-native-layout.json", {
                "schema_version": 1, "credential_free_fixture": True,
                "vendor_conformance_qualified": False,
                "launch_revision": str(launcher.revision),
                "binding_digest": str(binding.sealed.operator_binding_digest),
                "native_facts": facts, "in_place_write_kept_the_store_inode": True,
                "ordinary_worker_layout_absent": True,
            })
    finally:
        host_credential.write_bytes(CREDENTIAL)
        binding.close_held(held)


async def test_the_zone_receives_the_checked_object_not_whatever_the_path_names(
    binding, launcher, tmp_path,
):
    """Descriptor binding: a path swapped after the check never reaches the zone."""

    held = await hold(binding)
    paths = AcquisitionPaths(tmp_path, acquisition_id_for("n4-layout-swap", 1))
    store = held.store_path
    original, substitute = store / "auth.json.checked", store / "auth.json.substitute"
    swapped: list[bool] = []

    def swap_then_check():
        substitute.write_bytes(b"substituted\n")
        substitute.chmod(0o600)
        os.rename(store / "auth.json", original)
        os.rename(substitute, store / "auth.json")
        swapped.append(True)
        return binding.check_held(held)

    try:
        async with acquisition_guard(paths) as guard:
            with native_mount(binding, held, before_spawn=swap_then_check) as mount:
                result = await launcher.exchange(
                    ("/usr/bin/python3", "-I", "-c",
                     "print(open('/tmp/home/.codex/auth.json', 'rb').read().decode(), end='')"),
                    workspace=None, posture=Posture.READ, guard_fds=(guard, held.lock_fd),
                    timeout_s=10, conversation=collect, native_store=mount,
                )
        assert swapped == [True]
        assert result.returncode == result.payload_returncode == 0, result
        assert result.stdout == CREDENTIAL, "the zone saw the path's object, not the checked one"
        write_evidence("n3a-native-layout-descriptor.json", {
            "schema_version": 1, "path_swapped_after_check": True,
            "zone_saw_the_checked_object": True,
        })
    finally:
        if original.exists():
            os.replace(original, store / "auth.json")
        substitute.unlink(missing_ok=True)
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
