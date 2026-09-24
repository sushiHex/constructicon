"""Portable OS-boundary double for the real N3a descriptor reader.

It deliberately replaces only the Linux descriptor/identity/flock primitives.
All strict metadata parsing, active selection, sealed-law comparison and held
check behaviour remains the production ``BindingStore`` implementation.
"""

from __future__ import annotations

import os
import stat
from dataclasses import replace
from pathlib import Path

from constructicon.core.identity import digest
from constructicon.substrate.executors import operator_store


def _identity(name: str, *, handle: str | None = None) -> operator_store.FileHandleV1:
    return operator_store.FileHandleV1(
        boot_id="00000000-0000-0000-0000-000000000001", mount_id=1,
        handle_type=1, handle_hex=handle or (name.encode().hex()), dev=1,
        ino=abs(hash(name)) + 1, mode=0o700, uid=1000, nlink=1,
    )


class StoreWorld:
    def __init__(self, tmp_path: Path, *, key: str = "operator-test", generation: int = 1) -> None:
        self.root = tmp_path / "trusted"
        self.root.mkdir(parents=True)
        self.key, self.generation = key, generation
        self.bundle = _identity("bundle")
        self.store = _identity("store")
        self.lock = _identity("lock")
        self.instance = operator_store._identity_instance(self.store)
        self.mode = digest("operator-store-test", 1, "mode")
        self.conformance = digest("operator-store-test", 1, "conformance")
        self.sealed = operator_store.store_identity_for(
            key, generation, self.instance,
            subscription_mode_adapter_revision=self.mode,
            store_conformance_revision=self.conformance,
        )
        self.metadata: dict[str, bytes] = {}
        self.names: list[str] = []
        self.lock_attempts = 0
        self.lock_after = 0
        # Opt-in flock semantics: one holding descriptor, released by its close.
        self.exclusive = False
        self.holder: int | None = None
        self.closed: list[int] = []
        # The credential file's metadata as the substituted fstat reports it.
        self.credential: tuple[int, int, int] | None = (stat.S_IFREG | 0o600, 1, 1000)
        self.credential_opens: list[int] = []
        # Bytes each substituted sealed configuration descriptor carried.
        self.configurations: list[bytes] = []
        # What the offline helpers did, in order; nothing here infers it.
        self.events: list[str] = []
        self._write_anchor()
        self.write_descriptor(generation)
        self.activate(generation)

    def _opened(self) -> operator_store.OpenedBundle:
        self.events.append("open")
        fds = tuple(os.open(os.devnull, os.O_RDONLY) for _ in range(5))
        return operator_store.OpenedBundle(
            self.root / "bundle", self.root / "bundle" / "store", *fds,
            self.bundle, self.store, self.lock,
        )

    def _write_anchor(self) -> None:
        self.metadata["anchor.json"] = operator_store.canonical_json({
            "schema_version": 1, "key": self.key, "bundle": self.bundle.model_dump(),
        }).encode()

    def descriptor(self, generation: int, *, instance: str | None = None,
                   store: operator_store.FileHandleV1 | None = None,
                   lock: operator_store.FileHandleV1 | None = None) -> operator_store._Descriptor:
        instance = self.instance if instance is None else instance
        sealed = operator_store.store_identity_for(
            self.key, generation, instance,
            subscription_mode_adapter_revision=self.mode,
            store_conformance_revision=self.conformance,
        )
        return operator_store._Descriptor(
            self.key, generation, instance, sealed.operator_binding_digest, self.bundle,
            self.store if store is None else store, self.lock if lock is None else lock,
            sealed.layout_law_digest, sealed.mount_lock_law_digest,
        )

    def write_descriptor(self, generation: int, **changes: object) -> operator_store._Descriptor:
        descriptor = self.descriptor(generation)
        descriptor = replace(descriptor, **changes)
        name = f"{generation}.json"
        self.metadata[name] = operator_store.canonical_json(descriptor.body()).encode()
        if name not in self.names:
            self.names.append(name)
        return descriptor

    def activate(self, generation: int) -> None:
        descriptor = operator_store._descriptor(self.metadata[f"{generation}.json"])
        self.metadata["active.json"] = operator_store.canonical_json({
            "schema_version": 1, "key": self.key, "generation": generation,
            "binding_digest": str(descriptor.binding_digest),
            "descriptor_digest": str(descriptor.descriptor_digest),
        }).encode()

    def sealed_for(self, generation: int) -> operator_store.NativeOperatorStoreIdentityV1:
        return operator_store.store_identity_for(
            self.key, generation, self.instance,
            subscription_mode_adapter_revision=self.mode,
            store_conformance_revision=self.conformance,
        )

    def install(self, monkeypatch) -> None:
        monkeypatch.setattr(operator_store, "_open_bundle", lambda root, token: self._opened())
        def metadata(opened, name):
            try:
                return self.metadata[name]
            except KeyError as exc:
                raise FileNotFoundError(name) from exc

        monkeypatch.setattr(operator_store, "_read_metadata", metadata)

        def names(opened) -> tuple[str, ...]:
            self.events.append("inventory")
            # Production order: numeric, never insertion or lexicographic.
            return tuple(sorted(self.names, key=lambda name: int(name.removesuffix(".json"))))

        monkeypatch.setattr(operator_store, "_descriptor_names", names)

        def flock(fd: int) -> bool:
            self.lock_attempts += 1
            if self.lock_attempts <= self.lock_after:
                return False
            if self.exclusive and self.holder not in (None, fd):
                return False
            self.holder = fd
            self.events.append("lock")
            return True

        monkeypatch.setattr(operator_store, "_flock", flock)
        def close(fd: int) -> None:
            self.closed.append(fd)
            if fd == self.holder:
                self.holder = None
            os.close(fd)

        monkeypatch.setattr(operator_store, "_close", close)

        def replace_metadata(directory_fd: int, name: str, raw: bytes) -> None:
            self.events.append("replace")
            self.metadata[name] = raw

        monkeypatch.setattr(operator_store, "_replace_metadata", replace_metadata)
        self.install_mounts(monkeypatch)

    def install_mounts(self, monkeypatch) -> None:
        """The two descriptors a native launch binds, with only syscalls replaced.

        ``check_credential``'s rule and the handle's ownership of both
        descriptors stay real. The sealed configuration becomes an ordinary
        readable descriptor holding the same bytes, so a test can read what the
        zone would receive.
        """

        def open_credential_fd(store_fd: int) -> int:
            if self.credential is None:
                raise FileNotFoundError(2, "No such file or directory", "auth.json")
            fd = os.open(os.devnull, os.O_RDONLY)
            self.credential_opens.append(fd)
            return fd

        def credential_facts(fd: int) -> tuple[int, int, int]:
            assert self.credential is not None
            return self.credential

        def create_credential_fd(store_fd: int) -> int:
            if self.credential is not None:
                raise FileExistsError(17, "File exists", "auth.json")
            self.credential = (stat.S_IFREG | 0o600, 1, 1000)
            self.events.append("create-credential")
            return os.open(self.root / "created-credential", os.O_WRONLY | os.O_CREAT, 0o600)

        monkeypatch.setattr(operator_store, "_open_credential_fd", open_credential_fd)
        monkeypatch.setattr(operator_store, "_credential_facts", credential_facts)
        monkeypatch.setattr(operator_store, "_create_credential_fd", create_credential_fd)

        from constructicon.substrate.executors import codex

        def sealed(data: bytes) -> int:
            self.configurations.append(data)
            path = self.root / f"sealed-{len(self.configurations)}"
            path.write_bytes(data)
            return os.open(path, os.O_RDONLY)

        monkeypatch.setattr(codex, "sealed_data_fd", sealed)

    def fdinfo(self, *locks: str, ino: int | None = None) -> bytes:
        """``/proc/self/fdinfo/<fd>`` as ``fs/proc/fd.c`` and ``fs/locks.c`` print it."""

        ino = self.lock.ino if ino is None else ino
        head = f"pos:\t0\nflags:\t02100002\nmnt_id:\t29\nino:\t{ino}\n"
        return (head + "".join(f"lock:\t{n}: {lock}\n" for n, lock in enumerate(locks, 1))).encode()

    def flock_line(
        self, pid: int, *, ino: int | None = None, kind: str = "FLOCK  ADVISORY  WRITE",
    ) -> str:
        return f"{kind} {pid} 08:01:{self.lock.ino if ino is None else ino} 0 EOF"

    def install_inheritance(self, monkeypatch, *, parent: int) -> int:
        """One descriptor the root helper passed, holding the lock ``parent`` took.

        Only the identity read and the fdinfo read are substituted; tests change
        ``inherited`` and ``fdinfos`` to describe another descriptor.
        """

        fd = os.open(os.devnull, os.O_RDONLY)
        self.inherited = {fd: self.lock}
        self.fdinfos = {fd: self.fdinfo(self.flock_line(parent))}

        def identity(descriptor: int) -> operator_store.FileHandleV1:
            if descriptor not in self.inherited:
                raise operator_store.ContractViolation(
                    "native store physical identity is unavailable"
                )
            return self.inherited[descriptor]

        def read_fdinfo(descriptor: int) -> bytes:
            if descriptor not in self.fdinfos:
                raise operator_store.ContractViolation("native store maintenance is unavailable")
            return self.fdinfos[descriptor]

        monkeypatch.setattr(operator_store, "_identity", identity)
        monkeypatch.setattr(operator_store, "_read_fdinfo", read_fdinfo)
        return fd

    def install_publisher(self, monkeypatch) -> list[int]:
        """Substitute only publication's provisioning primitives; returns fsyncs."""

        synced: list[int] = []
        devnull = lambda *args, **kwargs: os.open(os.devnull, os.O_RDONLY)  # noqa: E731
        monkeypatch.setattr(operator_store, "_open_trusted_directory", devnull)
        monkeypatch.setattr(operator_store, "_trusted_directory", lambda fd: None)
        monkeypatch.setattr(operator_store, "_provision_directory", devnull)
        monkeypatch.setattr(operator_store, "_provision_lock", devnull)
        monkeypatch.setattr(operator_store.os, "fsync", synced.append)

        def publish_new(directory_fd: int, name: str, raw: bytes) -> None:
            if name in self.metadata:
                raise operator_store.ContractViolation(
                    "native store descriptor publication is unavailable"
                )
            self.events.append("publish")
            self.metadata[name] = raw
            if name != "anchor.json":
                self.names.append(name)

        monkeypatch.setattr(operator_store, "_publish_new", publish_new)
        return synced

    def reboot(self, *, boot_id: str = "00000000-0000-0000-0000-000000000002",
               mount_id: int = 2) -> None:
        """Change only the boot-scoped identity fields, as a real reboot does."""

        for name in ("bundle", "store", "lock"):
            setattr(self, name, replace(getattr(self, name), boot_id=boot_id, mount_id=mount_id))
        self.instance = operator_store._identity_instance(self.store)

    def withdraw(self, floor: int) -> None:
        self.metadata["active.json"] = operator_store.canonical_json({
            "generation_floor": floor, "key": self.key, "schema_version": 1,
        }).encode()

    def binding(self, sealed=None) -> operator_store.BindingStore:
        return operator_store.BindingStore(
            self.root, self.key, self.sealed if sealed is None else sealed,
        )
