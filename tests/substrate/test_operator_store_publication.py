"""Publisher refuses hostile pre-existing children before mutating them."""

from __future__ import annotations

import os
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.substrate.executors import operator_store
from tests.operator_store_world import _identity
from tests.substrate.test_operator_store_restart import protected_root as protected_root


def _publish(root, key="publication-fixture"):
    return operator_store.publish_descriptor_offline(
        root,
        key,
        1,
        runtime_uid=os.getuid(),
        subscription_mode_adapter_revision=digest("publication-test", 1, "mode"),
        store_conformance_revision=digest("publication-test", 1, "conformance"),
    )


@pytest.mark.parametrize("key", [" publication-fixture ", "publication\x00fixture"])
def test_invalid_key_refuses_before_filesystem_entry(tmp_path, monkeypatch, key):
    monkeypatch.setattr(operator_store.sys, "platform", "linux")
    monkeypatch.setattr(
        operator_store,
        "_open_trusted_directory",
        lambda root: pytest.fail("an invalid key must refuse before filesystem entry"),
    )
    with pytest.raises(ContractViolation, match="publication is unavailable"):
        operator_store.publish_descriptor_offline(
            tmp_path.resolve(),
            key,
            1,
            runtime_uid=1000,
            subscription_mode_adapter_revision=digest("publication-test", 1, "mode"),
            store_conformance_revision=digest("publication-test", 1, "conformance"),
        )


def test_existing_unopenable_child_gets_no_ownership_mutation(tmp_path, monkeypatch):
    """Portable proof of ordering; the Linux lane supplies the real symlink."""

    mutations: list[tuple[int, int, int]] = []

    def exists(*args, **kwargs):
        raise FileExistsError

    def refuses(*args, **kwargs):
        raise OSError("nofollow refusal")

    monkeypatch.setattr(operator_store.os, "mkdir", exists)
    monkeypatch.setattr(operator_store.os, "open", refuses)
    monkeypatch.setattr(
        operator_store,
        "_fchown",
        lambda fd, uid, gid: mutations.append((fd, uid, gid)),
    )
    with pytest.raises(OSError, match="nofollow refusal"):
        operator_store._provision_directory(
            7,
            "existing",
            mode=0o750,
            owner_uid=0,
            owner_gid=0,
        )
    assert mutations == []


@pytest.mark.parametrize(
    ("requested", "existing"),
    [(0o750, 0o700), (0o700, 0o500)],
)
def test_existing_directory_requires_its_exact_fixed_mode(
    monkeypatch, requested, existing,
):
    monkeypatch.setattr(
        operator_store.os,
        "mkdir",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileExistsError()),
    )
    monkeypatch.setattr(operator_store.os, "open", lambda *args, **kwargs: 17)
    monkeypatch.setattr(
        operator_store.os,
        "fstat",
        lambda fd: SimpleNamespace(
            st_mode=stat.S_IFDIR | existing,
            st_uid=1000,
            st_gid=1000,
        ),
    )
    closed: list[int] = []
    monkeypatch.setattr(operator_store, "_close", closed.append)

    with pytest.raises(ContractViolation, match="provisioned directory"):
        operator_store._provision_directory(
            7,
            "existing",
            mode=requested,
            owner_uid=1000,
            owner_gid=1000,
        )
    assert closed == [17]


def test_existing_lock_requires_its_exact_fixed_mode(monkeypatch):
    attempts = 0

    def open_lock(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise FileExistsError
        return 19

    monkeypatch.setattr(operator_store.os, "open", open_lock)
    monkeypatch.setattr(
        operator_store.os,
        "fstat",
        lambda fd: SimpleNamespace(
            st_mode=stat.S_IFREG | 0o400,
            st_uid=1000,
            st_nlink=1,
        ),
    )
    closed: list[int] = []
    monkeypatch.setattr(operator_store, "_close", closed.append)

    with pytest.raises(ContractViolation, match="retained lock"):
        operator_store._provision_lock(7, runtime_uid=1000)
    assert closed == [19]


@pytest.mark.parametrize("fault", ["mode", "uid"])
def test_reader_refuses_a_wrong_fixed_child_mode_or_store_lock_owner(monkeypatch, fault):
    identities = [
        _identity("root"),
        replace(_identity("bundle"), mode=0o700 if fault == "mode" else 0o750),
        replace(_identity("descriptors"), mode=0o750),
        replace(_identity("store"), mode=0o700),
        replace(_identity("lock"), mode=0o600, uid=1001 if fault == "uid" else 1000),
    ]
    descriptors = iter((11, 12, 13, 14))
    monkeypatch.setattr(operator_store.sys, "platform", "linux")
    monkeypatch.setattr(operator_store, "_open_trusted_directory", lambda root: 10)
    monkeypatch.setattr(operator_store, "_trusted_directory", lambda fd: None)
    monkeypatch.setattr(operator_store.os, "open", lambda *args, **kwargs: next(descriptors))
    monkeypatch.setattr(operator_store, "_identity", lambda fd: identities[fd - 10])
    monkeypatch.setattr(operator_store, "_mounts_below", lambda *args: None)
    monkeypatch.setattr(
        operator_store.os,
        "fstat",
        lambda fd: SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=1),
    )
    closed: list[int] = []
    monkeypatch.setattr(operator_store, "_close", closed.append)

    with pytest.raises(ContractViolation, match="fixed layout"):
        operator_store._open_bundle(Path("C:/trusted"), "a" * 64)
    assert closed == [14, 13, 12, 11, 10]


def test_oversized_publisher_metadata_refuses_before_any_immutable_write(monkeypatch):
    root = Path("C:/trusted")
    identities = [
        replace(_identity("bundle"), mode=0o750),
        replace(_identity("store"), mode=0o700),
        replace(_identity("lock"), mode=0o600),
    ]
    opened = operator_store.OpenedBundle(
        root / "bundle",
        root / "bundle" / "store",
        10,
        11,
        12,
        13,
        14,
        identities[0],
        identities[1],
        identities[2],
    )
    provisioned = iter((11, 12, 13))
    monkeypatch.setattr(operator_store.sys, "platform", "linux")
    monkeypatch.setattr(operator_store, "_open_trusted_directory", lambda path: 10)
    monkeypatch.setattr(operator_store, "_trusted_directory", lambda fd: None)
    monkeypatch.setattr(
        operator_store,
        "_provision_directory",
        lambda *args, **kwargs: next(provisioned),
    )
    monkeypatch.setattr(operator_store, "_provision_lock", lambda *args, **kwargs: 14)
    monkeypatch.setattr(operator_store.os, "fstat", lambda fd: SimpleNamespace(st_gid=1000))
    monkeypatch.setattr(operator_store.os, "fsync", lambda fd: None)
    monkeypatch.setattr(operator_store, "_close_fds", lambda *fds: None)
    monkeypatch.setattr(operator_store, "_open_bundle", lambda path, token: opened)
    monkeypatch.setattr(operator_store, "_close_opened", lambda candidate: None)
    monkeypatch.setattr(
        operator_store,
        "_read_metadata",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    monkeypatch.setattr(
        operator_store,
        "_publish_new",
        lambda *args, **kwargs: pytest.fail("oversized bytes must not reach publication"),
    )

    with pytest.raises(ContractViolation, match="metadata is unavailable"):
        operator_store.publish_descriptor_offline(
            root,
            "x" * (operator_store.MAX_METADATA_BYTES + 1),
            1,
            runtime_uid=1000,
            subscription_mode_adapter_revision=digest("publication-test", 1, "mode"),
            store_conformance_revision=digest("publication-test", 1, "conformance"),
        )


def test_short_metadata_write_refuses_and_removes_its_private_temporary(monkeypatch):
    closed: list[int] = []
    unlinked: list[tuple[str, int]] = []
    synced: list[int] = []
    monkeypatch.setattr(operator_store.secrets, "token_hex", lambda size: "a" * (size * 2))
    monkeypatch.setattr(operator_store.os, "open", lambda *args, **kwargs: 11)
    monkeypatch.setattr(operator_store.os, "write", lambda fd, raw: 0)
    monkeypatch.setattr(operator_store.os, "close", closed.append)
    monkeypatch.setattr(operator_store.os, "fsync", synced.append)
    monkeypatch.setattr(
        operator_store.os,
        "unlink",
        lambda name, *, dir_fd: unlinked.append((name, dir_fd)),
    )
    monkeypatch.setattr(
        operator_store.os,
        "link",
        lambda *args, **kwargs: pytest.fail("a short write must not publish"),
    )

    with pytest.raises(OSError, match="short write"):
        operator_store._publish_new(7, "1.json", b"metadata")
    assert closed == [11]
    assert unlinked == [(".pending-" + "a" * 32, 7)]
    assert synced == [7]


def test_existing_bundle_symlink_refuses_without_mutating_its_victim(protected_root):
    victim = protected_root / "unrelated-victim"
    victim.mkdir(mode=0o711)
    victim.chmod(0o711)
    os.chown(victim, 65534, 65534)
    marker = victim / "evidence"
    marker.write_text("unchanged", encoding="utf-8")
    before = victim.stat()

    bundle = protected_root / operator_store._bundle_token("publication-fixture")
    bundle.symlink_to(victim, target_is_directory=True)
    with pytest.raises(ContractViolation, match="publication is unavailable"):
        _publish(protected_root)

    after = victim.stat()
    assert (after.st_uid, after.st_gid, after.st_mode) == (
        before.st_uid, before.st_gid, before.st_mode,
    )
    assert marker.read_text(encoding="utf-8") == "unchanged"
