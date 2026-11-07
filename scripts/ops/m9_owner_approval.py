"""Authenticate an actual-pin approval using the owner's separately held SSH key."""

from __future__ import annotations

import base64
import os
import stat
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from scripts.ops.claude_read_commands import parsed, sha
from scripts.ops.claude_read_session import SSH, retain
from scripts.ops.m9_read_window import OwnerDecision

NAMESPACE = "constructicon-m9-read"
_PRINCIPAL = "m9-owner"
_SIGNATURE_LIMIT = 8192
_KEY_PREFIX = b"\0\0\0\x0bssh-ed25519\0\0\0\x20"
KEYGEN = Path(SSH).with_name("ssh-keygen.exe" if os.name == "nt" else "ssh-keygen")


def private_directory(path: Path) -> None:
    """Refuse writable custody ancestry; system administrators are trusted."""
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("M9_OWNER_UNSAFE_CUSTODY")
    for ancestor in (path, *path.parents):
        info = ancestor.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("M9_OWNER_UNSAFE_CUSTODY")
        if os.name == "nt":
            _check_windows_acl(ancestor, leaf=ancestor == path)
        else:
            sticky_system_parent = (
                ancestor != path and info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            )
            if (
                info.st_uid not in (0, os.geteuid())
                or (ancestor == path and (info.st_uid != os.geteuid() or info.st_mode & 0o077))
                or (info.st_mode & 0o022 and not sticky_system_parent)
            ):
                raise ValueError("M9_OWNER_UNSAFE_CUSTODY")


def _check_windows_acl(path: Path, *, leaf: bool) -> None:
    import ntsecuritycon as rights
    import win32api
    import win32security as security

    token = security.OpenProcessToken(win32api.GetCurrentProcess(), rights.TOKEN_QUERY)
    try:
        user, _ = security.GetTokenInformation(token, security.TokenUser)
    finally:
        token.Close()
    trusted = {
        security.ConvertSidToStringSid(user),
        "S-1-5-18",
        "S-1-5-32-544",
        # OWNER RIGHTS applies only to the independently checked current owner.
        "S-1-3-4",
        # Windows Modules Installer can own the system-volume root.
        "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",
    }
    sd = security.GetNamedSecurityInfo(
        str(path),
        security.SE_FILE_OBJECT,
        security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION,
    )
    acl = sd.GetSecurityDescriptorDacl()
    owner = security.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner())
    if acl is None or owner not in trusted:
        raise ValueError("M9_OWNER_UNSAFE_CUSTODY")
    unsafe = (
        rights.DELETE
        | rights.FILE_DELETE_CHILD
        | rights.WRITE_DAC
        | rights.WRITE_OWNER
        | rights.GENERIC_ALL
        | rights.GENERIC_WRITE
        | rights.FILE_WRITE_ATTRIBUTES
        | rights.FILE_WRITE_EA
    )
    if leaf:
        unsafe |= rights.FILE_ADD_FILE | rights.FILE_ADD_SUBDIRECTORY
    for i in range(acl.GetAceCount()):
        (kind, flags), mask, *rest = acl.GetAce(i)
        if kind == security.ACCESS_DENIED_ACE_TYPE or (
            flags & security.INHERIT_ONLY_ACE and not leaf
        ):
            continue
        if kind != security.ACCESS_ALLOWED_ACE_TYPE:
            raise ValueError("M9_OWNER_UNSAFE_CUSTODY")
        if mask & unsafe and security.ConvertSidToStringSid(rest[-1]) not in trusted:
            raise ValueError("M9_OWNER_UNSAFE_CUSTODY")


class SignedApproval:
    """Exchange public challenge/signature bytes; never read or store the signing key.

    The selected launch must pin the owner's key digest independently of the
    operator account. The operator needs no signing agent or GitHub credential.
    """

    def __init__(self, exchange: Path, public_key: bytes, pinned_sha256: str):
        key = public_key.split(b" ")
        if len(key) != 2 or key[0] != b"ssh-ed25519" or sha(public_key) != pinned_sha256:
            raise ValueError("M9_OWNER_KEY_NOT_PINNED")
        decoded = base64.b64decode(key[1], validate=True)
        if (
            len(decoded) != len(_KEY_PREFIX) + 32
            or not decoded.startswith(_KEY_PREFIX)
            or base64.b64encode(decoded) != key[1]
        ):
            raise ValueError("M9_OWNER_BAD_PUBLIC_KEY")
        if not exchange.is_absolute() or exchange.resolve(strict=True) != exchange:
            raise ValueError("M9_OWNER_UNSAFE_EXCHANGE")
        if not exchange.is_dir():
            raise ValueError("M9_OWNER_UNSAFE_EXCHANGE")
        self.exchange = exchange
        self.allowed = f'{_PRINCIPAL} namespaces="{NAMESPACE}" '.encode() + public_key + b"\n"

    def await_signature(self, challenge: bytes, pins: bytes, cutoff: float) -> bytes | None:
        if parsed(challenge)["pins_sha256"] != sha(pins) or time.monotonic() >= cutoff:
            raise ValueError("M9_OWNER_PINS_UNPROVED")
        packet = self.exchange / sha(challenge)
        packet.mkdir(mode=0o700)
        retain(packet / "pins.json", pins)
        retain(packet / "challenge.json", challenge)
        print(f"M9 owner approval requested: {packet}", flush=True)
        flags = os.O_RDONLY | (os.O_BINARY if os.name == "nt" else os.O_NOFOLLOW | os.O_NONBLOCK)
        while (remaining := cutoff - time.monotonic()) > 0:
            if os.path.lexists(self.exchange / "PARK-NOW"):
                return None
            try:
                fd = os.open(packet / "approval.sig", flags)
            except FileNotFoundError:
                time.sleep(min(0.25, remaining))
                continue
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("M9_OWNER_BAD_SIGNATURE_FILE")
                raw = stream.read(_SIGNATURE_LIMIT + 1)
            if not 0 < len(raw) <= _SIGNATURE_LIMIT:
                raise ValueError("M9_OWNER_BAD_SIGNATURE_FILE")
            return raw
        return None

    def verify(self, challenge: bytes, signature: bytes, cutoff: float) -> OwnerDecision | None:
        if type(signature) is not bytes or not 0 < len(signature) <= _SIGNATURE_LIMIT:
            return None
        expires = datetime.fromisoformat(parsed(challenge)["approval_not_after"])
        if expires.utcoffset() != UTC.utcoffset(None) or datetime.now(UTC) >= expires:
            return None
        # The exchange transports untrusted input. It does not own verifier files.
        home = Path.home().resolve(strict=True)
        with tempfile.TemporaryDirectory(prefix=".m9-verify-", dir=home) as tmp:
            private = Path(tmp)
            private_directory(private)
            allowed, signed = private / "allowed", private / "signature"
            retain(allowed, self.allowed)
            retain(signed, signature)
            remaining = cutoff - time.monotonic()
            if remaining <= 0:
                return None
            verified = subprocess.run(
                [
                    str(KEYGEN),
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed),
                    "-I",
                    _PRINCIPAL,
                    "-n",
                    NAMESPACE,
                    "-s",
                    str(signed),
                ],
                input=challenge,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=remaining,
                check=False,
            )
        checked_at = datetime.now(UTC)
        if verified.returncode or checked_at >= expires or time.monotonic() >= cutoff:
            return None
        # Scope is the signed bytes; the local timestamp is verification time.
        return OwnerDecision(sha(challenge), sha(signature), checked_at, expires)
