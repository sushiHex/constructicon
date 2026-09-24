"""N3c withdrawal, activation and their crash points over real protected roots.

Run only as the provisioning principal on the disposable CI host, like the N3a
restart proof: fresh roots under ``/var/lib/constructicon-m8-launch``, a fresh
interpreter for every reader, and ``SIGKILL`` for every crash point. Readers
whose verdict is what the service can see run as ``m8-service`` with no
supplementary group, because a root reader would hide an unreadable
descriptor (state review F3). Process death is not power loss.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import canonical_json, digest
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.substrate.executors import operator_store as stores
from tests.substrate.test_native_codex_mediation import write_evidence
from tests.substrate.test_operator_store_restart import protected_root as protected_root

KEY = "n3c-maintenance"
READER = """
import asyncio, sys
from pathlib import Path
from constructicon.core.errors import ContractViolation
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.substrate.executors.operator_store import BindingStore
async def check_closure(): pass
async def main():
    store = BindingStore(Path(sys.argv[1]), sys.argv[2],
        NativeOperatorStoreIdentityV1.model_validate_json(sys.argv[3]))
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
CRASH = """
import sys, time
from pathlib import Path
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.substrate.executors import operator_store as stores
real = stores._replace_metadata
def paused(directory_fd, name, raw):
    if sys.argv[3] == 'after':
        real(directory_fd, name, raw)
    print('paused', flush=True)
    time.sleep(120)
def pause_before_rename(*args, **kwargs):
    # The temporary is written, sealed and synced; the rename never happens.
    print('paused', flush=True)
    time.sleep(120)
if sys.argv[3] == 'temporary':
    stores.os.replace = pause_before_rename
else:
    stores._replace_metadata = paused
root, key = Path(sys.argv[1]), sys.argv[2]
if sys.argv[4] == 'maintain':
    with stores.maintain_offline(root, key, wait_s=0) as maintenance:
        (maintenance.store_path / 'maintenance-marker').write_text('body ran')
else:
    stores.activate_offline(root, key, int(sys.argv[5]), wait_s=0,
        qualified=NativeOperatorStoreIdentityV1.model_validate_json(sys.argv[6]))
"""
WAITER = """
import asyncio, sys
from pathlib import Path
from constructicon.core.errors import ContractViolation
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.substrate.executors.operator_store import BindingStore
async def main():
    store = BindingStore(Path(sys.argv[1]), sys.argv[2],
        NativeOperatorStoreIdentityV1.model_validate_json(sys.argv[3]))
    candidate = store.open_candidate()
    print('candidate', flush=True)
    await asyncio.to_thread(sys.stdin.readline)
    waited = False
    async def check_closure():
        nonlocal waited
        if not waited:
            waited = True
            print('waiting', flush=True)
            await asyncio.to_thread(sys.stdin.readline)
    held = None
    try:
        held = await store.acquire_lock(candidate, lambda: None, check_closure)
        store.check_held(held)
    except ContractViolation:
        print('refused', flush=True)
    else:
        print('accepted', flush=True)
    finally:
        if held is not None: store.close_held(held)
asyncio.run(main())
"""


def service() -> tuple[int, int]:
    import pwd

    entry = pwd.getpwnam("m8-service")
    return entry.pw_uid, entry.pw_gid


def service_root(root: Path) -> tuple[int, int]:
    """Let the service traverse this root, exactly as the CI fixture does."""
    uid, gid = service()
    os.chown(root, 0, gid)
    os.chmod(root, 0o750)
    return uid, gid


def bundle_of(root: Path, key: str = KEY) -> Path:
    return root / stores._bundle_token(key)


def publish(root: Path, generation: int, *, key: str = KEY, runtime_uid: int | None = None):
    return stores.publish_descriptor_offline(
        root, key, generation, runtime_uid=os.getuid() if runtime_uid is None else runtime_uid,
        subscription_mode_adapter_revision=digest("n3c-fixture-only", 1, "mode-unqualified"),
        store_conformance_revision=digest("n3c-fixture-only", 1, "vendor-unqualified"),
    )


def activate_fixture(root: Path, generation: int, *, key: str = KEY) -> None:
    """The first activation of a fresh fixture: explicit test input, as in N3a."""
    bundle = bundle_of(root, key)
    descriptor = stores._descriptor((bundle / "descriptors" / f"{generation}.json").read_bytes())
    path = bundle / "active.json"
    path.write_text(canonical_json({
        "schema_version": 1, "key": key, "generation": generation,
        "binding_digest": str(descriptor.binding_digest),
        "descriptor_digest": str(descriptor.descriptor_digest),
    }), encoding="utf-8")
    path.chmod(0o440)


def fresh_read(root: Path, sealed, *, key: str = KEY, as_service: bool = False) -> str:
    options: dict[str, object] = {}
    if as_service:
        uid, gid = service()
        options = {
            "user": uid, "group": gid, "extra_groups": [],
            "env": {"HOME": "/home/m8-service", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        }
    result = subprocess.run(
        [sys.executable, "-c", READER, str(root), key, sealed.model_dump_json()],
        capture_output=True, text=True, timeout=10, check=False, **options,
    )
    assert result.returncode == 0, "fresh interpreter failed before making its binding observation"
    assert result.stderr == "", "fresh interpreter emitted unexpected diagnostic evidence"
    assert result.stdout.strip() in {"accepted", "refused"}
    return result.stdout.strip()


def expect_line(process: subprocess.Popen, expected: bytes, timeout: float = 30) -> None:
    assert process.stdout is not None
    ready, _, _ = select.select([process.stdout], [], [], timeout)
    assert ready, f"the child never reported {expected!r}"
    assert process.stdout.readline() == expected + b"\n"


def assert_lock_held(root: Path) -> None:
    """Same-run control: the paused helper really holds the retained lock."""
    active = bundle_of(root) / "active.json"
    before = active.read_bytes()
    with (
        pytest.raises(ContractViolation, match="retained lock is held"),
        stores.maintain_offline(root, KEY, wait_s=0),
    ):
        pytest.fail("maintenance ran beside a live helper")
    assert active.read_bytes() == before


def killed_at(root: Path, point: str, helper: str, *extra: str) -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", CRASH, str(root), KEY, point, helper, *extra],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
    )
    try:
        expect_line(child, b"paused")
        assert_lock_held(root)
        child.kill()
        assert child.wait(timeout=10) == -9
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


def pending(path: Path) -> list[str]:
    return [name for name in os.listdir(path) if name.startswith(".pending-")]


def assert_sealed_metadata(path: Path, group: int) -> None:
    info = os.stat(path)
    assert (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (0, group, 0o440), path.name


def test_maintenance_then_activation_is_accepted_by_the_service(protected_root):
    root = protected_root
    uid, gid = service_root(root)
    first = publish(root, 1, runtime_uid=uid)
    activate_fixture(root, 1)
    assert fresh_read(root, first) == "accepted"
    bundle = bundle_of(root)
    marker = bundle / "store" / "maintenance-marker"
    with stores.maintain_offline(root, KEY, wait_s=0) as maintenance:
        assert fresh_read(root, first) == "refused"
        assert maintenance.store_path == bundle / "store"
        marker.write_bytes(b"harmless maintenance\n")
    assert maintenance.closed
    second = publish(root, 2, runtime_uid=uid)
    assert fresh_read(root, second, as_service=True) == "refused", "publication activated"
    stores.activate_offline(root, KEY, 2, qualified=second, wait_s=0)
    assert fresh_read(root, second, as_service=True) == "accepted"
    assert fresh_read(root, first, as_service=True) == "refused"
    for name in ("active.json", "anchor.json", "descriptors/1.json", "descriptors/2.json"):
        assert_sealed_metadata(bundle / name, gid)
    assert marker.read_bytes() == b"harmless maintenance\n"
    assert pending(bundle) == [] and pending(bundle / "descriptors") == []
    write_evidence("n3c-maintenance.json", {
        "schema_version": 1, "credential_free_fixture": True,
        "vendor_conformance_qualified": False,
        "withdrawn_inside_maintenance": True, "publication_did_not_activate": True,
        "service_reader_accepts_activated_generation": True,
        "service_reader_refuses_retired_generation": True,
        "metadata_root_owned_bundle_group_0440": True,
        "store_content_preserved": True,
    })


@pytest.mark.parametrize("point", ["before", "temporary", "after"])
def test_maintenance_killed_at_its_replace(protected_root, point):
    root = protected_root
    first = publish(root, 1)
    activate_fixture(root, 1)
    second = publish(root, 2)
    bundle = bundle_of(root)
    previous = (bundle / "active.json").read_bytes()
    killed_at(root, point, "maintain")
    assert not (bundle / "store" / "maintenance-marker").exists(), "the body ran"
    # Killed between creating and renaming it, the temporary stays behind.
    assert len(pending(bundle)) == (1 if point == "temporary" else 0)
    if point == "after":
        recorded = stores._withdrawal((bundle / "active.json").read_bytes())
        assert recorded == stores._Withdrawal(KEY, 2)
        assert fresh_read(root, first) == "refused"
    else:
        # An orphaned rename temporary is inert: no reader lists the bundle.
        assert (bundle / "active.json").read_bytes() == previous
        assert fresh_read(root, first) == "accepted"
    assert fresh_read(root, second) == "refused"
    # The dead process's lock description is gone with it, and a rerun over
    # any orphan withdraws again.
    with stores.maintain_offline(root, KEY, wait_s=5):
        pass
    assert fresh_read(root, first) == "refused"
    write_evidence(f"n3c-maintenance-killed-{point}.json", {
        "schema_version": 1, "killed_with_sigkill": True, "body_never_ran": True,
        "lock_held_while_paused": True,
        "previous_selection_intact": point != "after",
        "withdrawal_visible": point == "after",
        "orphaned_temporary_inert": point == "temporary",
        "lock_released_by_death": True,
    })


@pytest.mark.parametrize("point", ["before", "after"])
def test_activation_killed_at_its_replace(protected_root, point):
    root = protected_root
    first = publish(root, 1)
    activate_fixture(root, 1)
    with stores.maintain_offline(root, KEY, wait_s=0):
        pass
    second = publish(root, 2)
    bundle = bundle_of(root)
    withdrawn = (bundle / "active.json").read_bytes()
    with pytest.raises(ContractViolation, match="binding is unavailable"):
        stores.activate_offline(root, KEY, 2, qualified=first, wait_s=0)
    assert (bundle / "active.json").read_bytes() == withdrawn
    killed_at(root, point, "activate", "2", second.model_dump_json())
    assert pending(bundle) == []
    if point == "before":
        assert (bundle / "active.json").read_bytes() == withdrawn
        assert fresh_read(root, second) == "refused"
    else:
        assert stores._active((bundle / "active.json").read_bytes()).generation == 2
        assert fresh_read(root, second) == "accepted"
    assert fresh_read(root, first) == "refused"
    write_evidence(f"n3c-activation-killed-{point}.json", {
        "schema_version": 1, "killed_with_sigkill": True, "lock_held_while_paused": True,
        "previous_generation_identity_refused": True,
        "withdrawn_state_intact": point == "before",
        "activated_generation_accepted": point == "after",
    })


def test_a_bind_mount_alias_is_refused_and_unmounting_restores_it(protected_root):
    root = protected_root
    first, second = "n3c-alias-a", "n3c-alias-b"
    sealed = {key: publish(root, 1, key=key) for key in (first, second)}
    for key in sealed:
        activate_fixture(root, 1, key=key)
        assert fresh_read(root, sealed[key], key=key) == "accepted"
    store_a, store_b = bundle_of(root, first) / "store", bundle_of(root, second) / "store"
    subprocess.run(["mount", "--bind", str(store_a), str(store_b)], check=True, timeout=10)
    try:
        assert fresh_read(root, sealed[second], key=second) == "refused"
        assert fresh_read(root, sealed[first], key=first) == "accepted"
    finally:
        subprocess.run(["umount", str(store_b)], check=True, timeout=10)
    assert fresh_read(root, sealed[second], key=second) == "accepted"
    below, source = store_a / "below", root / "bind-source"
    below.mkdir()
    source.mkdir()
    subprocess.run(["mount", "--bind", str(source), str(below)], check=True, timeout=10)
    try:
        assert fresh_read(root, sealed[first], key=first) == "refused"
    finally:
        subprocess.run(["umount", str(below)], check=True, timeout=10)
    below.rmdir()
    assert fresh_read(root, sealed[first], key=first) == "accepted"
    write_evidence("n3c-mount-alias.json", {
        "schema_version": 1, "bind_mounted_store_refused": True,
        "mount_below_store_refused": True, "unmount_restores_binding": True,
    })


def test_a_reader_waiting_through_a_maintenance_cycle_refuses_after_it(protected_root):
    import fcntl

    root = protected_root
    first = publish(root, 1)
    activate_fixture(root, 1)
    waiter = subprocess.Popen(
        [sys.executable, "-c", WAITER, str(root), KEY, first.model_dump_json()],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
    )
    assert waiter.stdin is not None
    holder = -1
    try:
        expect_line(waiter, b"candidate")
        holder = os.open(bundle_of(root) / "retained.lock", os.O_RDWR | os.O_CLOEXEC)
        fcntl.flock(holder, fcntl.LOCK_EX)
        waiter.stdin.write(b"acquire\n")
        expect_line(waiter, b"waiting")
        # The waiter now sits inside its lock wait, holding pre-wait descriptors.
        os.close(holder)
        holder = -1
        with stores.maintain_offline(root, KEY, wait_s=0):
            pass
        second = publish(root, 2)
        stores.activate_offline(root, KEY, 2, qualified=second, wait_s=0)
        waiter.stdin.write(b"go\n")
        expect_line(waiter, b"refused")
        assert waiter.wait(timeout=10) == 0
    finally:
        if holder >= 0:
            os.close(holder)
        if waiter.poll() is None:
            waiter.kill()
            waiter.wait(timeout=10)
    assert fresh_read(root, second) == "accepted"
    write_evidence("n3c-waiting-reader.json", {
        "schema_version": 1, "reader_waited_through_cycle": True,
        "retired_selection_refused_after_wait": True, "new_generation_accepted": True,
    })


LANE_PROBE = r"""
import fcntl, json, os, sys
from pathlib import Path
# First, before anything opens: what this process inherited (plus the listing's own).
fds = sorted(int(name) for name in os.listdir('/proc/self/fd'))
from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors import operator_store as stores
report = Path(sys.argv[1])
options = dict(argument[2:].split('=', 1) for argument in sys.argv[2:])
root, key = Path(options['store-root']), options['key']
lock_fd, floor = int(options['lock-fd']), int(options['floor'])
status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
def verdict(fd, *, floor=floor, parent=os.getppid()):
    try:
        with stores.inherit_maintenance(
            root, key, fd, generation_floor=floor, parent=parent,
        ) as held:
            os.close(held.open_credential())
    except ContractViolation:
        return 'refused'
    return 'accepted'
bundle = root / stores._bundle_token(key)
stranger = os.open(bundle / 'retained.lock', os.O_RDWR | os.O_CLOEXEC)
wrong = os.open(bundle / 'anchor.json', os.O_RDONLY | os.O_CLOEXEC)
facts = {
    'fds': fds, 'lock_fd': lock_fd, 'parent': os.getppid(),
    'uid': status['Uid'].split(), 'gid': status['Gid'].split(), 'groups': status['Groups'].split(),
    'caps': {name: status[name].strip() for name in ('CapInh', 'CapPrm', 'CapEff', 'CapAmb')},
    'environment': dict(os.environ),
    'stranger': verdict(stranger), 'wrong_identity': verdict(wrong),
    'other_floor': verdict(lock_fd, floor=floor + 1),
    'other_parent': verdict(lock_fd, parent=os.getpid()),
    'inherited': verdict(lock_fd),
}
# Last: a description of its own. Held elsewhere is the same-run control that
# the helper holds the lock; taken here, it must still refuse (pid is this one).
own = os.open(bundle / 'retained.lock', os.O_RDWR | os.O_CLOEXEC)
try:
    fcntl.flock(own, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    facts['self_taken'] = 'held-elsewhere'
else:
    facts['self_taken'] = verdict(own)
report.write_text(json.dumps(facts))
"""


def test_the_service_lane_inherits_only_the_held_lock_and_proves_it(protected_root):
    """Host-runtime interface item 4: root withdraws; the service lane proves custody."""
    root = protected_root
    uid, gid = service_root(root)
    first = publish(root, 1, runtime_uid=uid)
    activate_fixture(root, 1)
    credential = bundle_of(root) / "store" / "auth.json"
    credential.write_bytes(b"harmless fixture\n")
    os.chown(credential, uid, gid)
    credential.chmod(0o600)
    reports = Path(tempfile.mkdtemp(prefix="n4-lane-"))
    os.chown(reports, uid, gid)
    try:
        inherited = reports / "inherited.json"
        # The helper's own command line, as the operator runs it.
        code = stores.main([
            "maintain", f"--store-root={root}", f"--key={KEY}", "--",
            sys.executable, "-c", LANE_PROBE, str(inherited),
        ])
        assert code == 0, "the lane probe failed before reporting"
        seen = json.loads(inherited.read_text())
        # The helper returned: the lock is free again, and the withdrawal stays.
        with stores.maintain_offline(root, KEY, wait_s=0):
            pass
        assert fresh_read(root, first, as_service=True) == "refused"
        alone = reports / "alone.json"
        result = subprocess.run(
            [sys.executable, "-c", LANE_PROBE, str(alone), f"--store-root={root}",
             f"--key={KEY}", "--custody=maintenance", "--lock-fd=63", "--floor=1"],
            user=uid, group=gid, extra_groups=[], env=dict(stores.LANE_ENVIRONMENT),
            cwd="/", capture_output=True, text=True, timeout=60, check=False,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        unheld = json.loads(alone.read_text())
    finally:
        shutil.rmtree(reports)
    assert seen["inherited"] == "accepted", "the real inherited custody was refused"
    assert seen["self_taken"] == "held-elsewhere", "the helper did not hold the lock"
    for control in ("stranger", "wrong_identity", "other_floor", "other_parent"):
        assert seen[control] == "refused", control
    assert seen["parent"] == os.getpid()
    # Descriptors 0-2, the lock and the listing's own descriptor; nothing else.
    others = [fd for fd in seen["fds"] if fd not in (0, 1, 2, seen["lock_fd"])]
    assert seen["lock_fd"] in seen["fds"] and len(others) == 1, seen["fds"]
    assert seen["uid"] == [str(uid)] * 4 and seen["gid"] == [str(gid)] * 4
    assert seen["groups"] == []
    assert set(seen["caps"].values()) == {"0000000000000000"}, seen["caps"]
    assert seen["environment"] == stores.LANE_ENVIRONMENT
    assert unheld["inherited"] == "refused", "a lane with no inherited lock was accepted"
    assert unheld["self_taken"] == "refused", "a lock the lane took itself was accepted"
    assert unheld["stranger"] == "refused"
    write_evidence("n4-inherited-maintenance.json", {
        "schema_version": 1, "credential_free_fixture": True,
        "root_withdrew_and_held_the_lock": True, "lane_ran_as_service": True,
        "supplementary_groups_cleared": True, "capabilities_cleared": True,
        "fixed_environment": True, "only_the_lock_inherited": True,
        "inherited_custody_accepted": True, "stranger_description_refused": True,
        "wrong_identity_refused": True, "other_floor_refused": True,
        "other_parent_refused": True, "no_inherited_lock_refused": True,
        "self_taken_lock_refused": True, "withdrawal_outlives_the_helper": True,
    })


REBOOT_ID = "00000000-0000-4000-8000-000000000b07"
REBOOTED = """
import asyncio, json, pathlib, sys
from pathlib import Path
real_read_text = pathlib.Path.read_text
def read_text(self, *args, **kwargs):
    # A simulated reboot: only the boot id the kernel reports changes.
    if str(self) == '/proc/sys/kernel/random/boot_id':
        return 'REBOOT_ID\\n'
    return real_read_text(self, *args, **kwargs)
pathlib.Path.read_text = read_text
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.substrate.executors import operator_store as stores
from constructicon.substrate.executors.operator_store import BindingStore
root, key = Path(sys.argv[1]), sys.argv[2]
retired = NativeOperatorStoreIdentityV1.model_validate_json(sys.argv[3])
async def closure(): pass
def read(sealed):
    async def main():
        store = BindingStore(root, key, sealed)
        held = None
        try:
            held = await store.acquire_lock(store.open_candidate(), lambda: None, closure)
            store.check_held(held)
        except ContractViolation:
            return 'refused'
        finally:
            if held is not None: store.close_held(held)
        return 'accepted'
    return asyncio.run(main())
def publish(generation):
    return stores.publish_descriptor_offline(root, key, generation, runtime_uid=0,
        subscription_mode_adapter_revision=digest('n3c-fixture-only', 1, 'mode-unqualified'),
        store_conformance_revision=digest('n3c-fixture-only', 1, 'vendor-unqualified'))
facts = {'retired_before': read(retired)}
try:
    publish(2)
except ContractViolation as exc:
    facts['publish_before'] = str(exc)
with stores.maintain_offline(root, key, wait_s=0):
    anchor = stores._anchor((root / stores._bundle_token(key) / 'anchor.json').read_bytes())
    facts['anchor_boot'] = anchor.bundle.boot_id
sealed = publish(2)
stores.activate_offline(root, key, 2, qualified=sealed, wait_s=0)
facts.update(current=read(sealed), retired_after=read(retired), sealed=sealed.model_dump_json())
print(json.dumps(facts))
""".replace("REBOOT_ID", REBOOT_ID)


def test_a_reboot_needs_maintenance_before_any_generation_is_accepted(protected_root):
    root = protected_root
    first = publish(root, 1)
    activate_fixture(root, 1)
    assert fresh_read(root, first) == "accepted"
    result = subprocess.run(
        [sys.executable, "-c", REBOOTED, str(root), KEY, first.model_dump_json()],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    facts = json.loads(result.stdout)
    assert facts["retired_before"] == "refused", "a reboot silently reused the binding"
    assert facts["publish_before"] == "native store anchor is unavailable"
    assert facts["anchor_boot"] == REBOOT_ID, "maintenance did not re-anchor"
    assert facts["current"] == "accepted" and facts["retired_after"] == "refused"
    # In the real boot the repaired anchor names the other one: refused again.
    sealed = NativeOperatorStoreIdentityV1.model_validate_json(facts["sealed"])
    assert fresh_read(root, sealed) == "refused"
    write_evidence("n3c-reboot.json", {
        "schema_version": 1, "boot_id_substituted_in_fresh_interpreters": True,
        "retired_generation_refused_after_reboot": True,
        "publication_refused_before_maintenance": True,
        "maintenance_re_anchored": True, "new_generation_accepted": True,
    })


def test_a_publication_temporary_linked_to_the_anchor_disables_until_removed(protected_root):
    root = protected_root
    first = publish(root, 1)
    activate_fixture(root, 1)
    bundle = bundle_of(root)
    # A publication killed between its link and its unlink leaves this state.
    linked = bundle / (".pending-" + "e" * 32)
    os.link(bundle / "anchor.json", linked)
    try:
        assert fresh_read(root, first) == "refused"
        with (
            pytest.raises(ContractViolation, match="metadata is unavailable"),
            stores.maintain_offline(root, KEY, wait_s=0),
        ):
            pytest.fail("maintenance ran over a second name for the anchor")
    finally:
        linked.unlink()
    assert fresh_read(root, first) == "accepted"
    write_evidence("n3c-anchor-link.json", {
        "schema_version": 1, "second_anchor_name_disables": True,
        "removal_restores_binding": True,
    })
