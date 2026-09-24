"""Private physical custody for one ADR 0021 operator-store binding.

This module is deliberately not a provider, account database, runtime
maintenance API, or public identity surface.  It reads an operator-provisioned
static bundle and holds its retained lock.  The Codex provider owns
lease/materialization and uses the positive :class:`BindingCheck` returned here
at its two boundaries.  Three synchronous offline helpers are the only writers:
publication, maintenance (a durable withdrawal) and activation.
"""

from __future__ import annotations

import asyncio
import ctypes
import inspect
import math
import os
import re
import secrets
import stat
import sys
import time
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from constructicon.core.errors import ContractViolation
from constructicon.core.identity import Digest, canonical_json, digest, parse_json_value
from constructicon.core.native_operator import (
    NativeOperatorStoreIdentityV1,
    operator_binding_digest,
)

MAX_METADATA_BYTES = 64 * 1024
MAX_HANDLE_BYTES = 128
MAX_DESCRIPTOR_COUNT = 1024
MAX_MOUNTINFO_BYTES = 1024 * 1024
_BUNDLE_MODE = 0o750
_DESCRIPTORS_MODE = 0o750
_STORE_MODE = 0o700
_LOCK_MODE = 0o600
_METADATA_MODE = 0o440
_WAIT_POLL_S = 0.01
_GENERATION = re.compile(r"[1-9][0-9]*\.json\Z")
_AT_EMPTY_PATH = 0x1000
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


@dataclass(frozen=True)
class FileHandleV1:
    """Private observed object identity; it never crosses a public contract."""

    boot_id: str
    mount_id: int
    handle_type: int
    handle_hex: str
    dev: int
    ino: int
    mode: int
    uid: int
    nlink: int

    def model_dump(self) -> dict[str, object]:
        return {
            "boot_id": self.boot_id,
            "mount_id": self.mount_id,
            "handle_type": self.handle_type,
            "handle_hex": self.handle_hex,
            "dev": self.dev,
            "ino": self.ino,
            "mode": self.mode,
            "uid": self.uid,
            "nlink": self.nlink,
        }


@dataclass(frozen=True)
class BindingCheck:
    """One positive, in-memory selection check.  No absent check is success."""

    binding_digest: Digest


@dataclass
class OpenedBundle:
    bundle_path: Path
    store_path: Path
    root_fd: int
    bundle_fd: int
    descriptors_fd: int
    store_fd: int
    lock_fd: int
    bundle_identity: FileHandleV1
    store_identity: FileHandleV1
    lock_identity: FileHandleV1
    closed: bool = False


@dataclass
class HeldStoreLock:
    """The one lock description retained through the invocation lifetime."""

    lock_fd: int
    store_path: Path
    _opened: OpenedBundle
    closed: bool = False


@dataclass(frozen=True)
class _Anchor:
    key: str
    bundle: FileHandleV1


@dataclass(frozen=True)
class _Descriptor:
    key: str
    generation: int
    store_instance_id: str
    binding_digest: Digest
    bundle: FileHandleV1
    store: FileHandleV1
    lock: FileHandleV1
    layout_law_digest: Digest
    mount_lock_law_digest: Digest

    def body(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "key": self.key,
            "generation": self.generation,
            "store_instance_id": self.store_instance_id,
            "binding_digest": str(self.binding_digest),
            "bundle": self.bundle.model_dump(),
            "store": self.store.model_dump(),
            "lock": self.lock.model_dump(),
            "layout_law_digest": str(self.layout_law_digest),
            "mount_lock_law_digest": str(self.mount_lock_law_digest),
        }

    @property
    def descriptor_digest(self) -> Digest:
        return digest("native-operator-store-descriptor", 1, self.body())


@dataclass(frozen=True)
class _Active:
    key: str
    generation: int
    binding_digest: Digest
    descriptor_digest: Digest


@dataclass(frozen=True)
class _Withdrawal:
    """The third ``active.json`` state; every provider reads it as unavailable."""

    key: str
    generation_floor: int


@dataclass
class StoreMaintenance:
    """Exists only after the withdrawal is durable; the operator's one locator."""

    store_path: Path
    generation_floor: int
    closed: bool = False


def _require_token(value: object, *, field: str) -> str:
    if type(value) is not str or not value or value.strip() != value or "\x00" in value:
        raise ValueError(f"{field} is invalid")
    return value


def _require_int(value: object, *, field: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{field} is invalid")
    return value


def _file_handle(value: object) -> FileHandleV1:
    if not isinstance(value, Mapping) or set(value) != {
        "boot_id", "mount_id", "handle_type", "handle_hex", "dev", "ino", "mode", "uid", "nlink",
    }:
        raise ValueError("file identity is invalid")
    handle_hex = _require_token(value["handle_hex"], field="handle_hex")
    if len(handle_hex) > MAX_HANDLE_BYTES * 2 or len(handle_hex) % 2 or any(
        char not in "0123456789abcdef" for char in handle_hex
    ):
        raise ValueError("file identity handle is invalid")
    return FileHandleV1(
        boot_id=_require_token(value["boot_id"], field="boot_id"),
        mount_id=_require_int(value["mount_id"], field="mount_id", minimum=1),
        handle_type=_require_int(value["handle_type"], field="handle_type"),
        handle_hex=handle_hex,
        dev=_require_int(value["dev"], field="dev"),
        ino=_require_int(value["ino"], field="ino", minimum=1),
        mode=_require_int(value["mode"], field="mode"),
        uid=_require_int(value["uid"], field="uid"),
        nlink=_require_int(value["nlink"], field="nlink", minimum=1),
    )


def _metadata(raw: bytes) -> Mapping[str, Any]:
    if not raw or len(raw) > MAX_METADATA_BYTES:
        raise ContractViolation("native store metadata is unavailable")
    try:
        text = raw.decode("utf-8")
        parsed = parse_json_value(text)
        if not isinstance(parsed, dict) or canonical_json(parsed).encode() != raw:
            raise ValueError("metadata is not a canonical object")
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ContractViolation("native store metadata is unavailable") from exc
    return parsed


def _anchor(raw: bytes) -> _Anchor:
    try:
        body = _metadata(raw)
        if (
            set(body) != {"schema_version", "key", "bundle"}
            or type(body["schema_version"]) is not int
            or body["schema_version"] != 1
        ):
            raise ValueError("shape")
        return _Anchor(_require_token(body["key"], field="key"), _file_handle(body["bundle"]))
    except ValueError as exc:
        raise ContractViolation("native store anchor is unavailable") from exc


def _descriptor(raw: bytes) -> _Descriptor:
    try:
        body = _metadata(raw)
        expected = {
            "schema_version", "key", "generation", "store_instance_id", "binding_digest", "bundle",
            "store", "lock", "layout_law_digest", "mount_lock_law_digest",
        }
        if (
            set(body) != expected
            or type(body["schema_version"]) is not int
            or body["schema_version"] != 1
        ):
            raise ValueError("shape")
        return _Descriptor(
            key=_require_token(body["key"], field="key"),
            generation=_require_int(body["generation"], field="generation", minimum=1),
            store_instance_id=_require_token(body["store_instance_id"], field="store_instance_id"),
            binding_digest=Digest.model_validate(body["binding_digest"]),
            bundle=_file_handle(body["bundle"]), store=_file_handle(body["store"]),
            lock=_file_handle(body["lock"]),
            layout_law_digest=Digest.model_validate(body["layout_law_digest"]),
            mount_lock_law_digest=Digest.model_validate(body["mount_lock_law_digest"]),
        )
    except (TypeError, ValueError) as exc:
        raise ContractViolation("native store descriptor is unavailable") from exc


def _active(raw: bytes) -> _Active:
    try:
        body = _metadata(raw)
        if set(body) != {
            "schema_version", "key", "generation", "binding_digest", "descriptor_digest",
        }:
            raise ValueError("shape")
        if type(body["schema_version"]) is not int or body["schema_version"] != 1:
            raise ValueError("version")
        return _Active(
            key=_require_token(body["key"], field="key"),
            generation=_require_int(body["generation"], field="generation", minimum=1),
            binding_digest=Digest.model_validate(body["binding_digest"]),
            descriptor_digest=Digest.model_validate(body["descriptor_digest"]),
        )
    except (TypeError, ValueError) as exc:
        raise ContractViolation("native store active selection is unavailable") from exc


def _withdrawal(raw: bytes) -> _Withdrawal:
    try:
        body = _metadata(raw)
        if (
            set(body) != {"schema_version", "key", "generation_floor"}
            or type(body["schema_version"]) is not int
            or body["schema_version"] != 1
        ):
            raise ValueError("shape")
        return _Withdrawal(
            key=_require_token(body["key"], field="key"),
            generation_floor=_require_int(body["generation_floor"], field="generation_floor"),
        )
    except ValueError as exc:
        raise ContractViolation("native store withdrawal is unavailable") from exc


def _bundle_token(key: str) -> str:
    return str(digest("native-operator-store-key-path", 1, key)).removeprefix("sha256:")


def _trusted_directory(fd: int) -> None:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ContractViolation("native store trusted parent is unavailable")


def _open_trusted_directory(path: Path) -> int:
    """Open every ancestor without following a symlink or writable parent."""

    if not path.is_absolute():
        raise ContractViolation("native store trusted parent is unavailable")
    current = os.open("/", os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC | _O_NOFOLLOW)
    try:
        _trusted_directory(current)
        for part in path.parts[1:]:
            next_fd = os.open(
                part, os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC | _O_NOFOLLOW,
                dir_fd=current,
            )
            os.close(current)
            current = next_fd
            _trusted_directory(current)
        return current
    except BaseException:
        os.close(current)
        raise


class _CFileHandle(ctypes.Structure):
    _fields_ = [
        ("handle_bytes", ctypes.c_uint),
        ("handle_type", ctypes.c_int),
        ("f_handle", ctypes.c_ubyte * MAX_HANDLE_BYTES),
    ]


def _identity(fd: int) -> FileHandleV1:
    """Read one Linux opaque object identity from an already verified descriptor."""

    if sys.platform != "linux":
        raise ContractViolation("native store physical identity requires Linux")
    handle = _CFileHandle()
    handle.handle_bytes = MAX_HANDLE_BYTES
    mount_id = ctypes.c_int()
    function = ctypes.CDLL(None, use_errno=True).name_to_handle_at
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(_CFileHandle),
                         ctypes.POINTER(ctypes.c_int), ctypes.c_int]
    function.restype = ctypes.c_int
    if function(fd, b"", ctypes.byref(handle), ctypes.byref(mount_id), _AT_EMPTY_PATH) != 0:
        raise ContractViolation("native store physical identity is unavailable")
    if not 0 < handle.handle_bytes <= MAX_HANDLE_BYTES or mount_id.value <= 0:
        raise ContractViolation("native store physical identity is unavailable")
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError as exc:
        raise ContractViolation("native store physical identity is unavailable") from exc
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", boot_id):
        raise ContractViolation("native store physical identity is unavailable")
    info = os.fstat(fd)
    return FileHandleV1(
        boot_id=boot_id, mount_id=mount_id.value, handle_type=handle.handle_type,
        handle_hex=bytes(handle.f_handle[:handle.handle_bytes]).hex(), dev=info.st_dev,
        ino=info.st_ino, mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, nlink=info.st_nlink,
    )


def _read_mountinfo() -> bytes:
    """The one platform read behind the mount-topology check, bounded plus one."""

    try:
        with Path("/proc/self/mountinfo").open("rb") as stream:
            return stream.read(MAX_MOUNTINFO_BYTES + 1)
    except OSError as exc:
        raise ContractViolation("native store mount topology is unavailable") from exc


def _mounts_below(path: Path, mount_id: int) -> None:
    """Refuse a mount at, or below, the writable store root."""

    raw = _read_mountinfo()
    if len(raw) > MAX_MOUNTINFO_BYTES:
        raise ContractViolation("native store mount topology is unavailable")
    prefix = str(path)
    for line in raw.decode("utf-8", errors="strict").splitlines():
        fields = line.split()
        if len(fields) < 5 or not fields[0].isdigit():
            raise ContractViolation("native store mount topology is unavailable")
        point = (
            fields[4].replace(r"\040", " ").replace(r"\011", "\t")
            .replace(r"\012", "\n").replace(r"\134", "\\")
        )
        if point == prefix and int(fields[0]) != mount_id:
            raise ContractViolation("native store mount topology is unavailable")
        if point.startswith(prefix.rstrip("/") + "/"):
            raise ContractViolation("native store mount topology is unavailable")


def _open_bundle(root: Path, token: str) -> OpenedBundle:
    """Open the fixed bundle and children without any symlink traversal."""

    if sys.platform != "linux":
        raise ContractViolation("native store custody requires Linux")
    if (
        not root.is_absolute()
        or any(part in {".", ".."} for part in root.parts)
        or not re.fullmatch(r"[0-9a-f]{64}", token)
    ):
        raise ContractViolation("native store bundle is unavailable")
    root_fd = bundle_fd = descriptors_fd = store_fd = lock_fd = -1
    try:
        root_fd = _open_trusted_directory(root)
        bundle = root / token
        bundle_fd = os.open(
            token, os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC | _O_NOFOLLOW, dir_fd=root_fd,
        )
        _trusted_directory(bundle_fd)
        descriptors_fd = os.open(
            "descriptors", os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC | _O_NOFOLLOW,
            dir_fd=bundle_fd,
        )
        _trusted_directory(descriptors_fd)
        store_fd = os.open(
            "store", os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC | _O_NOFOLLOW, dir_fd=bundle_fd,
        )
        lock_fd = os.open(
            "retained.lock", os.O_RDWR | _O_CLOEXEC | _O_NOFOLLOW, dir_fd=bundle_fd,
        )
        root_identity, bundle_identity, descriptors_identity, store_identity, lock_identity = (
            _identity(root_fd), _identity(bundle_fd), _identity(descriptors_fd),
            _identity(store_fd),
            _identity(lock_fd),
        )
        if (
            bundle_identity.mode != _BUNDLE_MODE
            or descriptors_identity.mode != _DESCRIPTORS_MODE
            or store_identity.mode != _STORE_MODE
            or lock_identity.mode != _LOCK_MODE
            or store_identity.uid != lock_identity.uid
        ):
            raise ContractViolation("native store fixed layout is unavailable")
        if (
            bundle_identity.mount_id != root_identity.mount_id
            or descriptors_identity.mount_id != root_identity.mount_id
            or store_identity.mount_id != root_identity.mount_id
            or lock_identity.mount_id != root_identity.mount_id
        ):
            raise ContractViolation("native store mount topology is unavailable")
        lock_info = os.fstat(lock_fd)
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1:
            raise ContractViolation("native store retained lock is unavailable")
        _mounts_below(bundle / "store", store_identity.mount_id)
        return OpenedBundle(
            bundle, bundle / "store", root_fd, bundle_fd, descriptors_fd, store_fd, lock_fd,
            bundle_identity, store_identity, lock_identity,
        )
    except BaseException as exc:
        cleanup = _close_fds(lock_fd, store_fd, descriptors_fd, bundle_fd, root_fd)
        if cleanup is not None:
            exc.add_note("native store partial-open cleanup failed")
        raise


def _read_metadata(opened: OpenedBundle, name: str) -> bytes:
    """Read one fixed relative metadata file through its trusted directory."""

    if name == "anchor.json" or name == "active.json":
        directory, target = opened.bundle_fd, name
    elif _GENERATION.fullmatch(name):
        directory, target = opened.descriptors_fd, name
    else:
        raise ContractViolation("native store metadata is unavailable")
    # A malformed FIFO must not block this event loop before fstat can refuse
    # it. O_NONBLOCK does not change regular-file reads.
    fd = os.open(
        target, os.O_RDONLY | _O_CLOEXEC | _O_NOFOLLOW | _O_NONBLOCK,
        dir_fd=directory,
    )
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_size > MAX_METADATA_BYTES
            or info.st_uid != 0 or info.st_mode & 0o022
        ):
            raise ContractViolation("native store metadata is unavailable")
        chunks = bytearray()
        while len(chunks) <= MAX_METADATA_BYTES:
            chunk = os.read(fd, min(8192, MAX_METADATA_BYTES + 1 - len(chunks)))
            if not chunk:
                return bytes(chunks)
            chunks.extend(chunk)
        raise ContractViolation("native store metadata is unavailable")
    finally:
        os.close(fd)


def _descriptor_names(opened: OpenedBundle) -> tuple[str, ...]:
    names: list[str] = []
    with os.scandir(opened.descriptors_fd) as entries:
        for entry in entries:
            if len(names) >= MAX_DESCRIPTOR_COUNT or _GENERATION.fullmatch(entry.name) is None:
                raise ContractViolation("native store descriptor inventory is unavailable")
            names.append(entry.name)
    return tuple(sorted(names, key=lambda value: int(value.removesuffix(".json"))))


def _flock(fd: int) -> bool:
    if sys.platform != "linux":
        raise ContractViolation("native store locking requires Linux")
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _close(fd: int) -> None:
    os.close(fd)


def _fchown(fd: int, uid: int, gid: int) -> None:
    function = cast(
        Callable[[int, int, int], None] | None,
        getattr(os, "fchown", None),
    )
    if function is None:
        raise ContractViolation("native store provisioning requires Linux fd ownership")
    function(fd, uid, gid)


def _fchmod(fd: int, mode: int) -> None:
    function = cast(Callable[[int, int], None] | None, getattr(os, "fchmod", None))
    if function is None:
        raise ContractViolation("native store provisioning requires Linux fd modes")
    function(fd, mode)


def _close_fds(*fds: int) -> OSError | None:
    """Attempt every independent close and retain the first failure."""

    failure: OSError | None = None
    for fd in fds:
        if fd >= 0:
            try:
                _close(fd)
            except OSError as exc:
                failure = failure or exc
    return failure


def _close_opened(candidate: OpenedBundle) -> None:
    if candidate.closed:
        return
    candidate.closed = True
    failure = _close_fds(
        candidate.lock_fd, candidate.store_fd, candidate.descriptors_fd,
        candidate.bundle_fd, candidate.root_fd,
    )
    if failure is not None:
        raise failure


def _seal_metadata_fd(fd: int, directory_fd: int) -> None:
    """One ownership law for every metadata writer: the directory's group, 0440.

    The owner stays the writing process (root in production, which every reader
    requires), so an unprivileged test exercises this exact primitive.
    """

    _fchown(fd, -1, os.fstat(directory_fd).st_gid)
    _fchmod(fd, _METADATA_MODE)


def _publish_new(directory_fd: int, name: str, raw: bytes) -> None:
    """Publish one immutable metadata file; an existing name is always refusal."""

    temporary = ".pending-" + secrets.token_hex(16)
    created = False
    try:
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_CLOEXEC, 0o600,
            dir_fd=directory_fd,
        )
        created = True
        try:
            written = 0
            while written < len(raw):
                count = os.write(fd, raw[written:])
                if count <= 0:
                    raise OSError("short write while publishing native store metadata")
                written += count
            _seal_metadata_fd(fd, directory_fd)
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(
                temporary,
                name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise ContractViolation(
                "native store descriptor publication is unavailable"
            ) from exc
    finally:
        if created:
            os.unlink(temporary, dir_fd=directory_fd)
            os.fsync(directory_fd)


def _replace_metadata(directory_fd: int, name: str, raw: bytes) -> None:
    """Atomically replace one mutable metadata file, then persist the directory.

    Any failure before the replace leaves the previous file intact and removes
    the temporary. A failure of the directory ``fsync`` after it raises with the
    new file visible, so a caller never treats that state as durable.
    """

    temporary = ".pending-" + secrets.token_hex(16)
    fd = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_CLOEXEC | _O_NOFOLLOW, 0o600,
        dir_fd=directory_fd,
    )
    replaced = False
    try:
        try:
            written = 0
            while written < len(raw):
                count = os.write(fd, raw[written:])
                if count <= 0:
                    raise OSError("short write while replacing native store metadata")
                written += count
            _seal_metadata_fd(fd, directory_fd)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        replaced = True
    finally:
        if not replaced:
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=directory_fd)
    os.fsync(directory_fd)


def _provision_directory(
    parent_fd: int,
    name: str,
    *,
    mode: int,
    owner_uid: int,
    owner_gid: int | None,
) -> int:
    """Create or verify one fixed child before applying any ownership mutation."""

    created = False
    try:
        os.mkdir(name, mode=mode, dir_fd=parent_fd)
        created = True
    except FileExistsError:
        pass
    descriptor = os.open(
        name, os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC | _O_NOFOLLOW,
        dir_fd=parent_fd,
    )
    try:
        if created:
            _fchown(descriptor, owner_uid, -1 if owner_gid is None else owner_gid)
            _fchmod(descriptor, mode)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != owner_uid
            or (owner_gid is not None and info.st_gid != owner_gid)
            or stat.S_IMODE(info.st_mode) != mode
        ):
            raise ContractViolation("native store provisioned directory is unavailable")
        return descriptor
    except BaseException:
        _close(descriptor)
        raise


def _provision_lock(bundle_fd: int, *, runtime_uid: int) -> int:
    """Create or verify the retained lock through its already verified parent."""

    created = False
    try:
        descriptor = os.open(
            "retained.lock",
            os.O_RDWR | os.O_CREAT | os.O_EXCL | _O_CLOEXEC | _O_NOFOLLOW,
            _LOCK_MODE,
            dir_fd=bundle_fd,
        )
        created = True
    except FileExistsError:
        descriptor = os.open(
            "retained.lock", os.O_RDWR | _O_CLOEXEC | _O_NOFOLLOW,
            dir_fd=bundle_fd,
        )
    try:
        if created:
            _fchown(descriptor, runtime_uid, -1)
            _fchmod(descriptor, _LOCK_MODE)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != runtime_uid
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != _LOCK_MODE
        ):
            raise ContractViolation("native store retained lock is unavailable")
        return descriptor
    except BaseException:
        _close(descriptor)
        raise


def _require_wait(wait_s: object) -> None:
    if (
        type(wait_s) not in (int, float)
        or not math.isfinite(cast(float, wait_s))
        or cast(float, wait_s) < 0
    ):
        raise ContractViolation("native store maintenance wait is invalid")


def _require_same_objects(current: OpenedBundle, original: OpenedBundle) -> None:
    if (
        current.bundle_identity != original.bundle_identity
        or not _same_store_identity(current.store_identity, original.store_identity)
        or current.lock_identity != original.lock_identity
    ):
        raise ContractViolation("native store binding is unavailable")


def _hold_offline(opened: OpenedBundle, root: Path, token: str, wait_s: float) -> None:
    """Take the retained lock, then re-prove the objects it guards under it.

    Holding this description is the affirmative "no materialized acquisition"
    fact: every handle and supervisor retains its own until it is reaped. Zero
    means exactly one attempt. The identities compared are the ones reopened
    after the wait, never ones observed before it.
    """

    deadline = time.monotonic() + wait_s
    while not _flock(opened.lock_fd):
        if time.monotonic() >= deadline:
            raise ContractViolation("native store retained lock is held")
        time.sleep(_WAIT_POLL_S)
    current = _open_bundle(root, token)
    try:
        _require_same_objects(current, opened)
    finally:
        _close_opened(current)


def publish_descriptor_offline(
    root: Path,
    key: str,
    generation: int,
    *,
    runtime_uid: int,
    subscription_mode_adapter_revision: Digest,
    store_conformance_revision: Digest,
    wait_s: float = 0,
) -> NativeOperatorStoreIdentityV1:
    """Create one immutable descriptor under a pre-protected operator root.

    This is an offline provisioning helper.  It cannot write ``active.json``;
    withdrawal and activation are :func:`maintain_offline` and
    :func:`activate_offline`.  It holds the retained lock from before it reads
    the anchor and inventory until its descriptor is published, so no lock
    holder ever sees the inventory change.  The caller supplies no
    store-instance label or child paths.
    """

    _require_wait(wait_s)
    if not root.is_absolute() or type(generation) is not int or generation < 1:
        raise ContractViolation("native store descriptor publication is unavailable")
    try:
        key = _require_token(key, field="key")
    except ValueError as exc:
        raise ContractViolation("native store descriptor publication is unavailable") from exc
    if type(runtime_uid) is not int or runtime_uid < 0:
        raise ContractViolation("native store descriptor publication is unavailable")
    if sys.platform != "linux":
        raise ContractViolation("native store custody requires Linux")
    token = _bundle_token(key)
    try:
        root_fd = _open_trusted_directory(root)
        bundle_fd = descriptors_fd = store_fd = lock_fd = -1
        try:
            _trusted_directory(root_fd)
            root_group = os.fstat(root_fd).st_gid
            bundle_fd = _provision_directory(
                root_fd, token, mode=_BUNDLE_MODE, owner_uid=0, owner_gid=root_group,
            )
            descriptors_fd = _provision_directory(
                bundle_fd, "descriptors", mode=_DESCRIPTORS_MODE, owner_uid=0,
                owner_gid=root_group,
            )
            store_fd = _provision_directory(
                bundle_fd, "store", mode=_STORE_MODE, owner_uid=runtime_uid,
                owner_gid=None,
            )
            lock_fd = _provision_lock(bundle_fd, runtime_uid=runtime_uid)
            # Persist the fixed topology before any immutable metadata can be
            # acknowledged. Metadata publication fsyncs its own file/directory.
            for retained_fd in (lock_fd, store_fd, descriptors_fd, bundle_fd, root_fd):
                os.fsync(retained_fd)
        finally:
            close_failure = _close_fds(
                lock_fd, store_fd, descriptors_fd, bundle_fd, root_fd,
            )
            if close_failure is not None:
                raise close_failure
        opened = _open_bundle(root, token)
        try:
            _hold_offline(opened, root, token, wait_s)
            instance = _identity_instance(opened.store_identity)
            sealed = store_identity_for(
                key, generation, instance,
                subscription_mode_adapter_revision=subscription_mode_adapter_revision,
                store_conformance_revision=store_conformance_revision,
            )
            anchor_body = {
                "schema_version": 1, "key": key, "bundle": opened.bundle_identity.model_dump(),
            }
            descriptor = _Descriptor(
                key=key, generation=generation, store_instance_id=instance,
                binding_digest=sealed.operator_binding_digest, bundle=opened.bundle_identity,
                store=opened.store_identity, lock=opened.lock_identity,
                layout_law_digest=sealed.layout_law_digest,
                mount_lock_law_digest=sealed.mount_lock_law_digest,
            )
            anchor_raw = canonical_json(anchor_body).encode()
            descriptor_raw = canonical_json(descriptor.body()).encode()
            # Prove that both exact byte strings satisfy the strict reader and
            # its size bound before creating either immutable metadata file.
            _anchor(anchor_raw)
            _descriptor(descriptor_raw)
            anchor_name = "anchor.json"
            try:
                current_anchor = _anchor(_read_metadata(opened, anchor_name))
            except FileNotFoundError:
                _publish_new(opened.bundle_fd, anchor_name, anchor_raw)
            else:
                if current_anchor != _Anchor(key, opened.bundle_identity):
                    raise ContractViolation("native store anchor is unavailable")
            for name in _descriptor_names(opened):
                old = _descriptor(_read_metadata(opened, name))
                if old.store_instance_id == instance and (
                    not _same_store_identity(old.store, descriptor.store)
                    or old.lock != descriptor.lock
                ):
                    raise ContractViolation("native store instance history is unavailable")
                if _same_object_across_boots(old.store, descriptor.store) and (
                    not _same_object_across_boots(old.lock, descriptor.lock)
                ):
                    raise ContractViolation("native store instance history is unavailable")
            _publish_new(
                opened.descriptors_fd, f"{generation}.json",
                descriptor_raw,
            )
            return sealed
        finally:
            _close_opened(opened)
    except ContractViolation:
        raise
    except (OSError, ValueError) as exc:
        raise ContractViolation("native store descriptor publication is unavailable") from exc


def _check_descriptor(
    opened: OpenedBundle,
    descriptor: _Descriptor,
    *,
    key: str,
    generation: int,
    sealed: NativeOperatorStoreIdentityV1,
) -> None:
    """One descriptor law for both callers: a provider's selection and activation."""

    if descriptor.key != key or descriptor.generation != generation:
        raise ContractViolation("native store active selection is unavailable")
    expected_binding = operator_binding_digest(
        descriptor.key, descriptor.generation, descriptor.store_instance_id,
    )
    if (
        descriptor.binding_digest != expected_binding
        or descriptor.binding_digest != sealed.operator_binding_digest
        or descriptor.layout_law_digest != BINDING_LAYOUT_LAW
        or descriptor.mount_lock_law_digest != BINDING_MOUNT_LOCK_LAW
        or descriptor.layout_law_digest != sealed.layout_law_digest
        or descriptor.mount_lock_law_digest != sealed.mount_lock_law_digest
        or descriptor.store_instance_id != _identity_instance(opened.store_identity)
        or descriptor.bundle != opened.bundle_identity
        or not _same_store_identity(descriptor.store, opened.store_identity)
        or descriptor.lock != opened.lock_identity
    ):
        raise ContractViolation("native store binding is unavailable")
    for name in _descriptor_names(opened):
        old = _descriptor(_read_metadata(opened, name))
        if old.store_instance_id == descriptor.store_instance_id and (
            not _same_store_identity(old.store, descriptor.store)
            or old.lock != descriptor.lock
        ):
            raise ContractViolation("native store instance history is unavailable")
        # The instance changes with the boot; the physical store does not, and
        # its retained lock is never replaced while the binding exists.
        if _same_object_across_boots(old.store, descriptor.store) and (
            not _same_object_across_boots(old.lock, descriptor.lock)
        ):
            raise ContractViolation("native store instance history is unavailable")


class BindingStore:
    """One statically provisioned, active operator-store selection."""

    def __init__(self, root: Path, key: str, sealed: NativeOperatorStoreIdentityV1) -> None:
        if (
            not root.is_absolute()
            or any(part in {".", ".."} for part in root.parts)
            or any(ord(char) < 32 for char in str(root))
            or not key.strip()
        ):
            raise ContractViolation("native store binding is unavailable")
        self.root = root
        self.key = key
        self.sealed = sealed
        self._token = _bundle_token(key)

    def open_candidate(self) -> OpenedBundle:
        try:
            opened = _open_bundle(self.root, self._token)
        except (OSError, ValueError) as exc:
            raise ContractViolation("native store binding is unavailable") from exc
        try:
            anchor = _anchor(_read_metadata(opened, "anchor.json"))
            if anchor.key != self.key or anchor.bundle != opened.bundle_identity:
                raise ContractViolation("native store anchor is unavailable")
            self._check_selection(opened)
            return opened
        except FileNotFoundError as exc:
            self.close_candidate(opened)
            raise ContractViolation("native store active selection is unavailable") from exc
        except OSError as exc:
            self.close_candidate(opened)
            raise ContractViolation("native store binding is unavailable") from exc
        except BaseException:
            self.close_candidate(opened)
            raise

    def _check_selection(self, opened: OpenedBundle) -> _Descriptor:
        active = _active(_read_metadata(opened, "active.json"))
        if active.key != self.key:
            raise ContractViolation("native store active selection is unavailable")
        descriptor = _descriptor(_read_metadata(opened, f"{active.generation}.json"))
        if (
            descriptor.descriptor_digest != active.descriptor_digest
            or descriptor.binding_digest != active.binding_digest
        ):
            raise ContractViolation("native store active selection is unavailable")
        _check_descriptor(
            opened, descriptor, key=self.key, generation=active.generation, sealed=self.sealed,
        )
        return descriptor

    async def acquire_lock(
        self,
        candidate: OpenedBundle,
        check_control: Callable[[], None],
        check_closure: Callable[[], Awaitable[None]],
    ) -> HeldStoreLock:
        if candidate.closed:
            raise ContractViolation("native store candidate is unavailable")
        try:
            while not _flock(candidate.lock_fd):
                check_control()
                await check_closure()
                await asyncio.sleep(0.01)
            check_control()
            await check_closure()
            self._check_selection(candidate)
            check_control()
            await check_closure()
            held = HeldStoreLock(candidate.lock_fd, candidate.store_path, candidate)
            self.check_held(held)
            return held
        except (OSError, ValueError) as exc:
            self.close_candidate(candidate)
            raise ContractViolation("native store binding is unavailable") from exc
        except BaseException:
            self.close_candidate(candidate)
            raise

    def check_held(self, held: HeldStoreLock) -> BindingCheck:
        if held.closed or held._opened.closed:
            raise ContractViolation("native store lock is unavailable")
        try:
            current = _open_bundle(self.root, self._token)
            anchor = _anchor(_read_metadata(current, "anchor.json"))
            if anchor.key != self.key or anchor.bundle != current.bundle_identity:
                raise ContractViolation("native store anchor is unavailable")
            descriptor = self._check_selection(current)
            _require_same_objects(current, held._opened)
            return BindingCheck(descriptor.binding_digest)
        except (OSError, ValueError) as exc:
            raise ContractViolation("native store binding is unavailable") from exc
        finally:
            if "current" in locals():
                _close_opened(current)

    def close_candidate(self, candidate: OpenedBundle) -> None:
        _close_opened(candidate)

    def close_held(self, held: HeldStoreLock) -> None:
        if held.closed:
            return
        held.closed = True
        try:
            self.close_candidate(held._opened)
        except OSError as exc:
            raise ContractViolation("native store closure is unavailable") from exc


def _across_reboot(anchored: FileHandleV1, live: FileHandleV1) -> bool:
    """The same physical bundle after a reboot: only boot-scoped fields differ.

    A handle, device, inode, mode, owner or link count that differs is another
    object, and a mount id that differs within one boot is another mount; both
    stay refused. The boot must actually have changed.
    """

    return (
        anchored.boot_id != live.boot_id
        and anchored.handle_type == live.handle_type
        and anchored.handle_hex == live.handle_hex
        and anchored.dev == live.dev
        and anchored.ino == live.ino
        and anchored.mode == live.mode
        and anchored.uid == live.uid
        and anchored.nlink == live.nlink
    )


def _anchor_is_current(opened: OpenedBundle, key: str, *, after_reboot: bool) -> bool:
    """Whether the anchor names this bundle now; ``False`` is a reboot to repair.

    Only maintenance passes ``after_reboot``. Publication, activation and every
    provider require the anchor exactly, so a reboot needs maintenance rather
    than silent reuse.
    """

    anchor = _anchor(_read_metadata(opened, "anchor.json"))
    if anchor.key != key:
        raise ContractViolation("native store anchor is unavailable")
    if anchor.bundle == opened.bundle_identity:
        return True
    if after_reboot and _across_reboot(anchor.bundle, opened.bundle_identity):
        return False
    raise ContractViolation("native store anchor is unavailable")


def _open_offline(
    root: Path, key: str, wait_s: float, refusal: str, *, after_reboot: bool = False,
) -> OpenedBundle:
    """Open the bundle, check its anchor and hold the lock; the caller closes."""

    _require_wait(wait_s)
    if not root.is_absolute():
        raise ContractViolation(refusal)
    try:
        key = _require_token(key, field="key")
    except ValueError as exc:
        raise ContractViolation(refusal) from exc
    token = _bundle_token(key)
    try:
        opened = _open_bundle(root, token)
    except (OSError, ValueError) as exc:
        raise ContractViolation(refusal) from exc
    try:
        _anchor_is_current(opened, key, after_reboot=after_reboot)
        _hold_offline(opened, root, token, wait_s)
        return opened
    except (OSError, ValueError) as exc:
        _close_opened(opened)
        raise ContractViolation(refusal) from exc
    except BaseException:
        _close_opened(opened)
        raise


@contextmanager
def maintain_offline(root: Path, key: str, *, wait_s: float) -> Iterator[StoreMaintenance]:
    """Withdraw the selection durably, then expose the store under the lock.

    An offline operator helper, like publication. The floor is the highest
    descriptor generation present under the lock, read from the inventory and
    never from the previous record, so this runs whatever that state was:
    withdrawal only disables. The receipt is built only after the directory
    ``fsync`` returns. Exit closes every descriptor, which releases the lock;
    it writes nothing and never activates.

    After a reboot the anchor still names the previous boot, so every provider
    and the other two helpers refuse. Maintenance alone repairs it, under the
    lock and after the withdrawal is durable, and only for the same physical
    bundle (``_across_reboot``). Every descriptor also names the previous boot,
    so no earlier generation can be accepted again: the next is published and
    activated as after any maintenance.
    """

    opened = _open_offline(
        root, key, wait_s, "native store maintenance is unavailable", after_reboot=True,
    )
    try:
        try:
            # Decided again under the lock, never from the pre-lock reading.
            anchored = _anchor_is_current(opened, key, after_reboot=True)
            names = _descriptor_names(opened)
            floor = int(names[-1].removesuffix(".json")) if names else 0
            raw = canonical_json({
                "schema_version": 1, "key": key, "generation_floor": floor,
            }).encode()
            _withdrawal(raw)
            _replace_metadata(opened.bundle_fd, "active.json", raw)
            if not anchored:
                anchor_raw = canonical_json({
                    "schema_version": 1, "key": key,
                    "bundle": opened.bundle_identity.model_dump(),
                }).encode()
                _anchor(anchor_raw)
                _replace_metadata(opened.bundle_fd, "anchor.json", anchor_raw)
        except (OSError, ValueError) as exc:
            raise ContractViolation("native store maintenance is unavailable") from exc
        maintenance = StoreMaintenance(opened.store_path, floor)
        try:
            yield maintenance
        finally:
            maintenance.closed = True
    finally:
        _close_opened(opened)


def _current_withdrawal(opened: OpenedBundle, key: str) -> _Withdrawal:
    """Every activation follows a durable maintenance record for this key."""

    try:
        raw = _read_metadata(opened, "active.json")
    except FileNotFoundError as exc:
        raise ContractViolation("native store withdrawal is unavailable") from exc
    withdrawal = _withdrawal(raw)
    if withdrawal.key != key:
        raise ContractViolation("native store withdrawal names another binding")
    return withdrawal


def activate_offline(
    root: Path,
    key: str,
    generation: int,
    *,
    qualified: NativeOperatorStoreIdentityV1,
    wait_s: float,
) -> None:
    """Select one generation published after the durable withdrawal.

    Publication takes the lock that maintenance held from its inventory read
    through its replace, so a generation above the floor was published after
    the withdrawal was durable. ``qualified`` is the sealed identity that
    qualification produced. It is trusted operator input, like every
    conformance revision: this bounds which generation it may name and checks
    it against the provider's own descriptor law and the live objects; it does
    not prove that qualification ran.
    """

    if (
        type(generation) is not int or generation < 1
        or not isinstance(qualified, NativeOperatorStoreIdentityV1)
    ):
        raise ContractViolation("native store activation is unavailable")
    opened = _open_offline(root, key, wait_s, "native store activation is unavailable")
    try:
        withdrawal = _current_withdrawal(opened, key)
        if generation <= withdrawal.generation_floor:
            raise ContractViolation("native store activation is unavailable")
        descriptor = _descriptor(_read_metadata(opened, f"{generation}.json"))
        _check_descriptor(opened, descriptor, key=key, generation=generation, sealed=qualified)
        raw = canonical_json({
            "schema_version": 1, "key": key, "generation": generation,
            "binding_digest": str(descriptor.binding_digest),
            "descriptor_digest": str(descriptor.descriptor_digest),
        }).encode()
        _active(raw)
        _replace_metadata(opened.bundle_fd, "active.json", raw)
    except (OSError, ValueError) as exc:
        raise ContractViolation("native store activation is unavailable") from exc
    finally:
        _close_opened(opened)


def _identity_instance(identity: FileHandleV1) -> str:
    return str(digest("native-operator-store-instance", 1, {
        "boot_id": identity.boot_id, "dev": identity.dev, "mount_id": identity.mount_id,
        "handle_type": identity.handle_type,
        "handle_hex": identity.handle_hex,
    }))


def _same_object_across_boots(left: FileHandleV1, right: FileHandleV1) -> bool:
    """One physical object in any boot: never the boot id, mount id or link count."""

    return (
        left.handle_type == right.handle_type
        and left.handle_hex == right.handle_hex
        and left.dev == right.dev
        and left.ino == right.ino
    )


def _same_store_identity(left: FileHandleV1, right: FileHandleV1) -> bool:
    """Compare the pinned store identity without its mutable directory link count."""

    return (
        left.boot_id == right.boot_id
        and left.mount_id == right.mount_id
        and left.handle_type == right.handle_type
        and left.handle_hex == right.handle_hex
        and left.dev == right.dev
        and left.ino == right.ino
        and left.mode == right.mode
        and left.uid == right.uid
    )


def store_identity_for(
    key: str,
    generation: int,
    instance: str,
    *,
    subscription_mode_adapter_revision: Digest,
    store_conformance_revision: Digest,
) -> NativeOperatorStoreIdentityV1:
    """Build the sealed L0 store identity from already observed offline facts."""

    return NativeOperatorStoreIdentityV1(
        operator_binding_digest=operator_binding_digest(key, generation, instance),
        layout_law_digest=BINDING_LAYOUT_LAW,
        mount_lock_law_digest=BINDING_MOUNT_LOCK_LAW,
        subscription_mode_adapter_revision=subscription_mode_adapter_revision,
        store_conformance_revision=store_conformance_revision,
    )


_MODULE_SOURCE = inspect.getsource(sys.modules[__name__])
BINDING_LAYOUT_LAW = digest("native-operator-store-layout", 1, {"source": _MODULE_SOURCE})
BINDING_MOUNT_LOCK_LAW = digest("native-operator-store-mount-lock", 1, {"source": _MODULE_SOURCE})
