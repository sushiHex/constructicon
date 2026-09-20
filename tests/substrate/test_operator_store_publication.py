"""Publisher refuses hostile pre-existing children before mutating them."""

from __future__ import annotations

import os

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.substrate.executors import operator_store
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
            private=False,
        )
    assert mutations == []


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
