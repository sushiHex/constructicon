"""Portable OS-boundary double for the real N3a descriptor reader.

It deliberately replaces only the Linux descriptor/identity/flock primitives.
All strict metadata parsing, active selection, sealed-law comparison and held
check behaviour remains the production ``BindingStore`` implementation.
"""

from __future__ import annotations

import os
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
        self.closed: list[int] = []
        self._write_anchor()
        self.write_descriptor(generation)
        self.activate(generation)

    def _opened(self) -> operator_store.OpenedBundle:
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

    def install(self, monkeypatch) -> None:
        monkeypatch.setattr(operator_store, "_open_bundle", lambda root, token: self._opened())
        def metadata(opened, name):
            try:
                return self.metadata[name]
            except KeyError as exc:
                raise FileNotFoundError(name) from exc

        monkeypatch.setattr(operator_store, "_read_metadata", metadata)
        monkeypatch.setattr(operator_store, "_descriptor_names", lambda opened: tuple(self.names))

        def flock(fd: int) -> bool:
            self.lock_attempts += 1
            return self.lock_attempts > self.lock_after

        monkeypatch.setattr(operator_store, "_flock", flock)
        def close(fd: int) -> None:
            self.closed.append(fd)
            os.close(fd)

        monkeypatch.setattr(operator_store, "_close", close)

    def binding(self) -> operator_store.BindingStore:
        return operator_store.BindingStore(self.root, self.key, self.sealed)
