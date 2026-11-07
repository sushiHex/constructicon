"""Record a trusted operator's manual approval of one actual-pin challenge."""

from __future__ import annotations

import os
import stat
import time
from datetime import UTC, datetime
from pathlib import Path

from scripts.ops.claude_read_commands import bounded, parsed, sha
from scripts.ops.claude_read_session import retain
from scripts.ops.m9_read_window import OwnerDecision

_DECISION_LIMIT = 256


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


class ManualApproval:
    """The trusted operator records the user's decision; this does not authenticate a signer."""

    def __init__(self, exchange: Path):
        if not exchange.is_absolute() or exchange.resolve(strict=True) != exchange:
            raise ValueError("M9_OWNER_UNSAFE_EXCHANGE")
        if not exchange.is_dir():
            raise ValueError("M9_OWNER_UNSAFE_EXCHANGE")
        self.exchange = exchange

    def await_decision(self, challenge: bytes, pins: bytes, cutoff: float) -> bytes | None:
        if parsed(challenge)["pins_sha256"] != sha(pins) or time.monotonic() >= cutoff:
            raise ValueError("M9_OWNER_PINS_UNPROVED")
        packet = self.exchange / sha(challenge)
        packet.mkdir(mode=0o700)
        retain(packet / "pins.json", pins)
        retain(packet / "challenge.json", challenge)
        print(f"M9 manual owner approval requested: {packet}", flush=True)
        decision = packet / "approval.json"
        flags = os.O_RDONLY | (os.O_BINARY if os.name == "nt" else os.O_NOFOLLOW | os.O_NONBLOCK)
        while (remaining := cutoff - time.monotonic()) > 0:
            if os.path.lexists(self.exchange / "PARK-NOW"):
                return None
            try:
                before = decision.lstat()
            except FileNotFoundError:
                time.sleep(min(0.25, remaining))
                continue
            if not stat.S_ISREG(before.st_mode) or getattr(before, "st_file_attributes", 0) & 0x400:
                raise ValueError("M9_OWNER_BAD_DECISION_FILE")
            with os.fdopen(os.open(decision, flags), "rb") as stream:
                after = os.fstat(stream.fileno())
                if not stat.S_ISREG(after.st_mode) or (before.st_dev, before.st_ino) != (
                    after.st_dev, after.st_ino,
                ):
                    raise ValueError("M9_OWNER_BAD_DECISION_FILE")
                raw = stream.read(_DECISION_LIMIT + 1)
            if not 0 < len(raw) <= _DECISION_LIMIT:
                raise ValueError("M9_OWNER_BAD_DECISION_FILE")
            if (
                bounded(packet / "pins.json", len(pins)) != pins
                or bounded(packet / "challenge.json", len(challenge)) != challenge
            ):
                raise ValueError("M9_OWNER_PINS_CHANGED")
            return raw
        return None

    def verify(self, challenge: bytes, raw: bytes, cutoff: float) -> OwnerDecision | None:
        if type(raw) is not bytes or not 0 < len(raw) <= _DECISION_LIMIT:
            return None
        digest = sha(challenge)
        try:
            decision = parsed(raw)
            expires = datetime.fromisoformat(parsed(challenge)["approval_not_after"])
        except (ValueError, TypeError, KeyError, RecursionError):
            return None
        checked_at = datetime.now(UTC)
        if (
            decision != {"decision": "approve", "challenge_sha256": digest}
            or expires.utcoffset() != UTC.utcoffset(None)
            or checked_at >= expires
            or time.monotonic() >= cutoff
        ):
            return None
        return OwnerDecision(digest, sha(raw), checked_at, expires)
