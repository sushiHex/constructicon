"""Operator commands wrap the physical N3a/N3c store lifecycle."""

from __future__ import annotations

import errno
import os
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.substrate.executors import operator_store as stores
from tests.operator_store_world import StoreWorld


def _operator(world: StoreWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stores.sys, "platform", "linux")
    monkeypatch.setattr(stores, "_service", lambda name: (1000, 1000))
    monkeypatch.setattr(stores, "_operator_root", lambda root, service: 1000)
    world.install(monkeypatch)
    world.install_publisher(monkeypatch)


def _publish(world: StoreWorld, revision: str) -> list[str]:
    return [
        "publish", "--store-root", str(world.root), "--key", world.key,
        "--generation", "2", "--qualification-evidence-digest", revision,
    ]


def _operator_with_real_root(
    world: StoreWorld, monkeypatch: pytest.MonkeyPatch, facts: list[int], roots: list[Path],
) -> None:
    real_guard = stores._operator_root
    _operator(world, monkeypatch)
    primitive = stores._open_trusted_directory

    def open_root(root: Path) -> int:
        roots.append(root)
        return primitive(root)

    monkeypatch.setattr(stores, "_open_trusted_directory", open_root)
    monkeypatch.setattr(stores, "_operator_root", real_guard)
    monkeypatch.setattr(stores.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(stores.os, "fstat", lambda fd: SimpleNamespace(
        st_uid=facts[0], st_gid=facts[1], st_mode=stat.S_IFDIR | facts[2],
    ))


def _main_with_bound_runtime_uid(command: list[str]) -> int:
    try:
        return stores.main(command)
    except NameError as exc:
        if exc.name != "runtime_uid":
            raise
        pytest.fail("operator command must bind runtime_uid through root validation")


def test_provision_cli_validates_the_installed_root_and_named_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    world = StoreWorld(tmp_path)
    facts = [0, 2000, 0o750]
    roots: list[Path] = []
    _operator_with_real_root(world, monkeypatch, facts, roots)
    services: list[str] = []
    monkeypatch.setattr(stores, "_service", lambda name: (
        services.append(name) or 1000, 2000,
    ))
    publications: list[tuple[Path, str, int, dict[str, object]]] = []

    def publish(root: Path, key: str, generation: int, **kwargs: object
                ) -> NativeOperatorStoreIdentityV1:
        publications.append((root, key, generation, kwargs))
        return world.sealed

    monkeypatch.setattr(stores, "publish_descriptor_offline", publish)
    command = [
        "provision", "--store-root", str(world.root), "--key", world.key,
        "--service", "test-service",
    ]
    assert _main_with_bound_runtime_uid(command) == 0
    printed = NativeOperatorStoreIdentityV1.model_validate_json(capsys.readouterr().out)
    assert printed == world.sealed
    assert services == ["test-service"] and roots == [world.root]
    assert publications == [(
        world.root, world.key, 1,
        {
            "runtime_uid": 1000,
            "subscription_mode_adapter_revision": stores.UNQUALIFIED_REVISION,
            "store_conformance_revision": stores.UNQUALIFIED_REVISION,
            "bundle_presence": "fresh", "require_next_generation": True, "wait_s": 0.0,
        },
    )]
    facts[0] = 1001
    opened_before = len(roots)
    with pytest.raises(SystemExit) as refused:
        stores.main(command)
    assert refused.value.code == 1 and len(publications) == 1
    assert services == ["test-service", "test-service"]
    assert roots[opened_before:] == [world.root]


@pytest.mark.parametrize("helper", ["publish", "activate"])
def test_qualified_cli_validates_the_installed_root_and_named_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], helper: str,
) -> None:
    world = StoreWorld(tmp_path)
    facts = [0, 2000, 0o750]
    roots: list[Path] = []
    _operator_with_real_root(world, monkeypatch, facts, roots)
    services: list[str] = []
    monkeypatch.setattr(stores, "_service", lambda name: (
        services.append(name) or 1000, 2000,
    ))
    world.withdraw(1)
    revision = digest("qualification-test", 1, "cli-root-evidence")
    if helper == "activate":
        sealed = stores.publish_descriptor_offline(
            world.root, world.key, 2, runtime_uid=1000,
            subscription_mode_adapter_revision=revision,
            store_conformance_revision=revision, bundle_presence="existing",
            require_next_generation=True,
        )
        monkeypatch.setattr(stores, "_sealed_file", lambda path, runtime_uid: sealed)
        command = [
            "activate", "--store-root", str(world.root), "--key", world.key,
            "--generation", "2", "--qualification-evidence-digest", str(revision),
            "--sealed", str(tmp_path / "sealed.json"),
        ]
    else:
        command = _publish(world, str(revision))
    command.extend(("--service", "test-service"))
    assert _main_with_bound_runtime_uid(command) == 0
    assert world.root in roots and all(root == world.root for root in roots)
    capsys.readouterr()
    if helper == "activate":
        assert stores._active(world.metadata["active.json"]).generation == 2
        world.withdraw(1)
    else:
        assert "2.json" in world.metadata
        command[command.index("--generation") + 1] = "3"
    before = dict(world.metadata)
    facts[0] = 1001
    opened_before = len(roots)
    with pytest.raises(SystemExit) as refused:
        stores.main(command)
    assert refused.value.code == 1 and world.metadata == before
    assert services == ["test-service", "test-service"]
    assert roots[opened_before:] == [world.root]


def test_publish_then_activate_wrap_the_existing_lock_and_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    world = StoreWorld(tmp_path)
    _operator(world, monkeypatch)
    world.withdraw(1)
    presences: list[str] = []
    original_directory = stores._provision_directory

    def record_directory(*args: object, **kwargs: object) -> int:
        presences.append(str(kwargs.get("presence", "either")))
        return original_directory(*args, **kwargs)

    monkeypatch.setattr(stores, "_provision_directory", record_directory)
    revision = str(digest("qualified-startup-test", 1, "clean-evidence"))
    assert stores.main(_publish(world, revision)) == 0
    sealed = NativeOperatorStoreIdentityV1.model_validate_json(capsys.readouterr().out)
    assert sealed.subscription_mode_adapter_revision == sealed.store_conformance_revision
    assert str(sealed.store_conformance_revision) == revision
    assert stores._withdrawal(world.metadata["active.json"]).generation_floor == 1
    assert "2.json" in world.metadata and "publish" in world.events
    assert presences[0] == "existing"

    identity_file = tmp_path / "sealed.json"
    identity_file.write_text(sealed.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        stores, "_sealed_file",
        lambda path, runtime_uid: NativeOperatorStoreIdentityV1.model_validate_json(
            path.read_bytes()
        ),
    )
    assert stores.main([
        "activate", "--store-root", str(world.root), "--key", world.key,
        "--generation", "2", "--sealed", str(identity_file),
        "--qualification-evidence-digest", revision,
    ]) == 0
    assert stores._active(world.metadata["active.json"]).generation == 2
    binding = world.binding(sealed)
    candidate = binding.open_candidate()
    assert not candidate.closed
    binding.close_candidate(candidate)


def test_activation_refuses_wrong_or_missing_evidence_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = StoreWorld(tmp_path)
    _operator(world, monkeypatch)
    world.withdraw(1)
    revision = digest("qualified-startup-test", 1, "clean-evidence")
    sealed = stores.publish_descriptor_offline(
        world.root, world.key, 2, runtime_uid=1000,
        subscription_mode_adapter_revision=revision,
        store_conformance_revision=revision, bundle_presence="existing",
        require_next_generation=True,
    )
    monkeypatch.setattr(stores, "_sealed_file", lambda path, runtime_uid: sealed)
    before = bytes(world.metadata["active.json"])
    with pytest.raises(SystemExit) as refused:
        stores.main([
            "activate", "--store-root", str(world.root), "--key", world.key,
            "--generation", "2", "--sealed", str(tmp_path / "sealed.json"),
            "--qualification-evidence-digest",
            str(digest("qualified-startup-test", 1, "other-evidence")),
        ])
    assert refused.value.code == 1 and world.metadata["active.json"] == before
    with pytest.raises(SystemExit) as missing:
        stores.main([
            "activate", "--store-root", str(world.root), "--key", world.key,
            "--generation", "2", "--sealed", str(tmp_path / "sealed.json"),
        ])
    assert missing.value.code == 2 and world.metadata["active.json"] == before


@pytest.mark.parametrize("field", [
    "subscription_mode_adapter_revision", "store_conformance_revision",
])
def test_activation_checks_each_evidence_revision_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str,
) -> None:
    world = StoreWorld(tmp_path)
    _operator(world, monkeypatch)
    world.withdraw(1)
    revision = digest("qualified-startup-test", 1, "clean-evidence")
    sealed = stores.publish_descriptor_offline(
        world.root, world.key, 2, runtime_uid=1000,
        subscription_mode_adapter_revision=revision,
        store_conformance_revision=revision, bundle_presence="existing",
        require_next_generation=True,
    )
    bad = sealed.model_copy(update={field: digest("qualified-startup-test", 1, "wrong")})
    monkeypatch.setattr(stores, "_sealed_file", lambda path, runtime_uid: bad)
    before = bytes(world.metadata["active.json"])
    with pytest.raises(SystemExit) as refused:
        stores.main([
            "activate", "--store-root", str(world.root), "--key", world.key,
            "--generation", "2", "--sealed", str(tmp_path / "sealed.json"),
            "--qualification-evidence-digest", str(revision),
        ])
    assert refused.value.code == 1 and world.metadata["active.json"] == before


@pytest.mark.parametrize("target", ["store", "lock"])
def test_publish_refuses_another_service_owner_before_a_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str,
) -> None:
    world = StoreWorld(tmp_path)
    _operator(world, monkeypatch)
    setattr(world, target, replace(getattr(world, target), uid=1001))
    before = dict(world.metadata)
    with pytest.raises(ContractViolation, match="bundle owner"):
        stores._operator_bundle(world.root, world.key, 1000)
    with pytest.raises(SystemExit) as refused:
        stores.main(_publish(world, str(digest("qualification-test", 1, "evidence"))))
    assert refused.value.code == 1 and world.metadata == before
    assert "publish" not in world.events


def test_publish_refuses_a_partial_bundle_without_repairing_its_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = StoreWorld(tmp_path)
    _operator(world, monkeypatch)
    world.metadata.pop("anchor.json")
    before = dict(world.metadata)
    with pytest.raises(SystemExit) as refused:
        stores.main(_publish(world, str(digest("qualification-test", 1, "evidence"))))
    assert refused.value.code == 1 and world.metadata == before
    assert "publish" not in world.events


@pytest.mark.parametrize(("uid", "gid", "mode"), [
    (0, 1000, 0o750), (1001, 1000, 0o750), (0, 1001, 0o750),
    (0, 1000, 0o700), (0, 1000, 0o770),
])
def test_operator_requires_the_installed_root_owner_group_and_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uid: int, gid: int, mode: int,
) -> None:
    descriptor = os.open(os.devnull, os.O_RDONLY)
    monkeypatch.setattr(stores.sys, "platform", "linux")
    monkeypatch.setattr(stores.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(stores, "_open_trusted_directory", lambda root: descriptor)
    monkeypatch.setattr(stores.os, "fstat", lambda fd: SimpleNamespace(
        st_uid=uid, st_gid=gid, st_mode=stat.S_IFDIR | mode,
    ))
    if (uid, gid, mode) == (0, 1000, 0o750):
        assert stores._operator_root(tmp_path.resolve(), (1000, 1000)) == 1000
    else:
        with pytest.raises(ContractViolation, match="operator root"):
            stores._operator_root(tmp_path.resolve(), (1000, 1000))


def test_fresh_bundle_refuses_an_existing_target_before_open_or_chown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stores.os, "mkdir", lambda *args, **kwargs: (_ for _ in ()).throw(
        FileExistsError()
    ))
    monkeypatch.setattr(stores.os, "open", lambda *args, **kwargs: pytest.fail(
        "an existing fresh target must not be opened"
    ))
    monkeypatch.setattr(stores, "_fchown", lambda *args: pytest.fail(
        "an existing fresh target must not be chowned"
    ))
    with pytest.raises(ContractViolation, match="must be fresh"):
        stores._provision_directory(
            7, "bundle", mode=0o750, owner_uid=0, owner_gid=1000, presence="fresh",
        )


def test_existing_bundle_mode_never_creates_a_missing_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stores.os, "mkdir", lambda *args, **kwargs: pytest.fail(
        "publish must not create an absent bundle"
    ))
    monkeypatch.setattr(stores.os, "open", lambda *args, **kwargs: (_ for _ in ()).throw(
        FileNotFoundError()
    ))
    with pytest.raises(FileNotFoundError):
        stores._provision_directory(
            7, "bundle", mode=0o750, owner_uid=0, owner_gid=1000,
            presence="existing",
        )


def test_provision_delegates_g1_with_a_fresh_bundle_and_unqualified_revisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    marker = object()
    monkeypatch.setattr(stores, "_operator_root", lambda root, service: 1000)

    def publish(root: Path, key: str, generation: int, **kwargs: object) -> object:
        seen.update(root=root, key=key, generation=generation, **kwargs)
        return marker

    monkeypatch.setattr(stores, "publish_descriptor_offline", publish)
    assert stores.provision_offline(tmp_path, "store", service=(1000, 1000)) is marker
    assert seen["bundle_presence"] == "fresh"
    assert seen["require_next_generation"] is True
    assert seen["generation"] == 1
    assert seen["subscription_mode_adapter_revision"] == stores.UNQUALIFIED_REVISION
    assert seen["store_conformance_revision"] == stores.UNQUALIFIED_REVISION


def test_publish_requires_the_next_generation_under_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = StoreWorld(tmp_path)
    _operator(world, monkeypatch)
    world.withdraw(1)
    with pytest.raises(ContractViolation, match="generation is not next"):
        stores.publish_descriptor_offline(
            world.root, world.key, 3, runtime_uid=1000,
            subscription_mode_adapter_revision=world.mode,
            store_conformance_revision=world.conformance,
            bundle_presence="existing", require_next_generation=True,
        )
    assert "3.json" not in world.metadata and "publish" not in world.events


def test_publish_cli_refuses_to_skip_a_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = StoreWorld(tmp_path)
    _operator(world, monkeypatch)
    world.withdraw(1)
    command = _publish(world, str(digest("qualification-test", 1, "evidence")))
    command[command.index("--generation") + 1] = "3"
    before = dict(world.metadata)
    with pytest.raises(SystemExit) as refused:
        stores.main(command)
    assert refused.value.code == 1 and world.metadata == before
    assert "3.json" not in world.metadata and "publish" not in world.events


@pytest.mark.parametrize("failure", ["platform", "root", "service_uid", "service_gid"])
def test_operator_requires_linux_root_and_an_unprivileged_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    monkeypatch.setattr(stores.sys, "platform", "win32" if failure == "platform" else "linux")
    monkeypatch.setattr(stores.os, "geteuid", lambda: 1000 if failure == "root" else 0,
                        raising=False)
    monkeypatch.setattr(stores, "_open_trusted_directory", lambda root: pytest.fail(
        "a wrong principal must refuse before opening the store root"
    ))
    service = (0 if failure == "service_uid" else 1000,
               0 if failure == "service_gid" else 1000)
    with pytest.raises(ContractViolation, match="requires root"):
        stores._operator_root(tmp_path.resolve(), service)




def test_qualified_identity_file_is_bounded_owned_and_exact_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = stores.store_identity_for(
        "operator-test", 2, "instance",
        subscription_mode_adapter_revision=digest("qualification-test", 1, "evidence"),
        store_conformance_revision=digest("qualification-test", 1, "evidence"),
    )
    path = tmp_path / "sealed.json"
    path.write_text(identity.model_dump_json(), encoding="utf-8")
    owner = 1000
    mode = [0o600]
    real_fstat = os.fstat

    def metadata(fd: int) -> SimpleNamespace:
        info = real_fstat(fd)
        return SimpleNamespace(
            st_mode=stat.S_IFREG | mode[0], st_nlink=1, st_uid=owner,
            st_size=info.st_size,
        )

    monkeypatch.setattr(stores.os, "fstat", metadata)
    assert stores._sealed_file(path, owner) == identity
    mode[0] = 0o644
    with pytest.raises(ContractViolation, match="identity is unavailable"):
        stores._sealed_file(path, owner)
    mode[0] = 0o600
    path.write_bytes(b"x" * (stores.MAX_METADATA_BYTES + 1))
    with pytest.raises(ContractViolation, match="identity is unavailable"):
        stores._sealed_file(path, owner)


def test_qualified_identity_file_refuses_another_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "sealed.json"
    identity = stores.store_identity_for(
        "operator-test", 2, "instance",
        subscription_mode_adapter_revision=digest("qualification-test", 1, "evidence"),
        store_conformance_revision=digest("qualification-test", 1, "evidence"),
    )
    path.write_text(identity.model_dump_json(), encoding="utf-8")
    real_fstat = os.fstat
    monkeypatch.setattr(stores.os, "fstat", lambda fd: SimpleNamespace(
        st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_uid=2000,
        st_size=real_fstat(fd).st_size,
    ))
    with pytest.raises(ContractViolation, match="identity is unavailable"):
        stores._sealed_file(path, 1000)


@pytest.mark.parametrize("failure", ["not-regular", "hard-link", "too-large"])
def test_qualified_identity_file_refuses_invalid_physical_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    path = tmp_path / "sealed.json"
    identity = stores.store_identity_for(
        "operator-test", 2, "instance",
        subscription_mode_adapter_revision=digest("qualification-test", 1, "evidence"),
        store_conformance_revision=digest("qualification-test", 1, "evidence"),
    )
    path.write_text(identity.model_dump_json(), encoding="utf-8")
    real_fstat = os.fstat
    monkeypatch.setattr(stores.os, "fstat", lambda fd: SimpleNamespace(
        st_mode=(stat.S_IFDIR if failure == "not-regular" else stat.S_IFREG) | 0o600,
        st_nlink=2 if failure == "hard-link" else 1, st_uid=1000,
        st_size=(stores.MAX_METADATA_BYTES + 1 if failure == "too-large"
                 else real_fstat(fd).st_size),
    ))
    with pytest.raises(ContractViolation, match="identity is unavailable"):
        stores._sealed_file(path, 1000)


def test_qualified_identity_file_refuses_growth_beyond_the_read_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "sealed.json"
    identity = stores.store_identity_for(
        "operator-test", 2, "instance",
        subscription_mode_adapter_revision=digest("qualification-test", 1, "evidence"),
        store_conformance_revision=digest("qualification-test", 1, "evidence"),
    )
    padded = identity.model_dump_json().encode() + b" " * stores.MAX_METADATA_BYTES
    path.write_bytes(identity.model_dump_json().encode())
    cursor = [0]

    def growing_read(fd: int, size: int) -> bytes:
        start = cursor[0]
        cursor[0] += size
        return padded[start:cursor[0]]

    monkeypatch.setattr(stores.os, "fstat", lambda fd: SimpleNamespace(
        st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_uid=1000, st_size=2,
    ))
    monkeypatch.setattr(stores.os, "read", growing_read)
    with pytest.raises(ContractViolation, match="identity is unavailable"):
        stores._sealed_file(path, 1000)


def test_qualified_identity_file_refuses_symlink_at_open_portably(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = stores.store_identity_for(
        "operator-test", 2, "instance",
        subscription_mode_adapter_revision=digest("qualification-test", 1, "evidence"),
        store_conformance_revision=digest("qualification-test", 1, "evidence"),
    )
    target = tmp_path / "sealed.json"
    target.write_text(identity.model_dump_json(), encoding="utf-8")
    alias = tmp_path / "sealed.link"
    nofollow = 1 << 27
    real_open, real_fstat = os.open, os.fstat
    monkeypatch.setattr(stores, "_O_NOFOLLOW", nofollow)

    def open_file(path: Path, flags: int) -> int:
        if path == alias:
            if flags & nofollow:
                raise OSError(errno.ELOOP, "symbolic link refused")
            return real_open(target, flags & ~nofollow)
        return real_open(path, flags & ~nofollow)

    def file_facts(fd: int) -> SimpleNamespace:
        info = real_fstat(fd)
        return SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_uid=1000,
            st_size=info.st_size,
        )

    monkeypatch.setattr(stores.os, "open", open_file)
    monkeypatch.setattr(stores.os, "fstat", file_facts)
    assert stores._sealed_file(target, 1000) == identity
    with pytest.raises(OSError) as refused:
        stores._sealed_file(alias, 1000)
    assert refused.value.errno == errno.ELOOP


def test_linux_sealed_identity_open_refuses_a_real_symlink(tmp_path: Path) -> None:
    if stores.sys.platform != "linux":
        pytest.skip("real O_NOFOLLOW symlink behaviour requires Linux")
    target = tmp_path / "sealed.json"
    target.write_text("{}", encoding="utf-8")
    alias = tmp_path / "sealed.link"
    alias.symlink_to(target)
    with pytest.raises(OSError) as refused:
        stores._sealed_file(alias, os.getuid())
    assert refused.value.errno == errno.ELOOP


def test_activate_cli_never_bypasses_the_physical_sealed_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = StoreWorld(tmp_path)
    _operator(world, monkeypatch)
    world.withdraw(1)
    revision = digest("qualification-test", 1, "evidence")
    sealed = stores.publish_descriptor_offline(
        world.root, world.key, 2, runtime_uid=1000,
        subscription_mode_adapter_revision=revision,
        store_conformance_revision=revision, bundle_presence="existing",
        require_next_generation=True,
    )
    path = tmp_path / "sealed.json"
    path.write_text(sealed.model_dump_json(), encoding="utf-8")
    mode = [0o600]
    real_fstat = os.fstat

    def file_facts(fd: int) -> SimpleNamespace:
        info = real_fstat(fd)
        return SimpleNamespace(
            st_mode=stat.S_IFREG | mode[0], st_nlink=1, st_uid=1000,
            st_size=info.st_size,
        )

    monkeypatch.setattr(stores.os, "fstat", file_facts)
    command = [
        "activate", "--store-root", str(world.root), "--key", world.key,
        "--generation", "2", "--sealed", str(path),
        "--qualification-evidence-digest", str(revision),
    ]
    assert stores.main(command) == 0
    assert stores._active(world.metadata["active.json"]).generation == 2
    world.withdraw(1)
    before = bytes(world.metadata["active.json"])
    mode[0] = 0o644
    with pytest.raises(SystemExit) as refused:
        stores.main(command)
    assert refused.value.code == 1 and world.metadata["active.json"] == before


@pytest.mark.parametrize("raw", ["sha256:" + "A" * 64, "sha256:abc", "not-a-digest"])
def test_malformed_evidence_revision_is_refused(raw: str) -> None:
    with pytest.raises(ContractViolation, match="digest is invalid"):
        stores._operator_digest(raw)


def test_unqualified_placeholder_cannot_be_reused_as_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = StoreWorld(tmp_path)
    _operator(world, monkeypatch)
    world.withdraw(1)
    with pytest.raises(SystemExit) as refused:
        stores.main(_publish(world, str(stores.UNQUALIFIED_REVISION)))
    assert refused.value.code == 1 and "2.json" not in world.metadata


def test_help_lists_all_four_operator_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as help_result:
        stores.main(["--help"])
    assert help_result.value.code == 0
    output = capsys.readouterr().out
    assert all(name in output for name in ("provision", "maintain", "publish", "activate"))


@pytest.mark.parametrize("helper", ["publish", "activate"])
def test_qualified_commands_require_a_digest_at_parse_time(helper: str) -> None:
    arguments = [helper, "--store-root", "/protected", "--key", "store", "--generation", "2"]
    if helper == "activate":
        arguments.extend(("--sealed", "/protected/sealed.json"))
    with pytest.raises(SystemExit) as refused:
        stores.main(arguments)
    assert refused.value.code == 2


@pytest.mark.parametrize("helper", ["publish", "activate"])
def test_qualified_commands_refuse_generation_one(helper: str) -> None:
    arguments = [
        helper, "--store-root", "/protected", "--key", "store", "--generation", "1",
        "--qualification-evidence-digest", str(digest("qualification-test", 1, "evidence")),
    ]
    if helper == "activate":
        arguments.extend(("--sealed", "/protected/sealed.json"))
    with pytest.raises(SystemExit) as refused:
        stores.main(arguments)
    assert refused.value.code == 2


@pytest.mark.parametrize("option", ["--generation", "--sealed", "--qualification-evidence-digest"])
def test_provision_rejects_qualified_overrides(option: str) -> None:
    value = "2" if option == "--generation" else "value"
    with pytest.raises(SystemExit) as refused:
        stores.main(["provision", "--store-root", "/protected", "--key", "store", option, value])
    assert refused.value.code == 2


@pytest.mark.parametrize("option", ["--generation", "--qualification-evidence-digest"])
def test_publish_requires_both_qualification_inputs(option: str) -> None:
    args = ["publish", "--store-root", "/protected", "--key", "store"]
    if option == "--generation":
        args.extend(("--qualification-evidence-digest", str(digest("test", 1, "evidence"))))
    else:
        args.extend(("--generation", "2"))
    with pytest.raises(SystemExit) as refused:
        stores.main(args)
    assert refused.value.code == 2


def test_publish_rejects_a_sealed_input() -> None:
    with pytest.raises(SystemExit) as refused:
        stores.main([
            "publish", "--store-root", "/protected", "--key", "store",
            "--generation", "2", "--qualification-evidence-digest",
            str(digest("test", 1, "evidence")), "--sealed", "/protected/sealed.json",
        ])
    assert refused.value.code == 2


def test_activate_requires_a_sealed_input() -> None:
    with pytest.raises(SystemExit) as refused:
        stores.main([
            "activate", "--store-root", "/protected", "--key", "store",
            "--generation", "2", "--qualification-evidence-digest",
            str(digest("test", 1, "evidence")),
        ])
    assert refused.value.code == 2
