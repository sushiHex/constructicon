"""The owner's standing approval of consumer READs, and private custody checks.

A ``StandingApproval`` is one canonical JSON record with a closed key set
(ADR 0026). The owner issues it, records its digest in an owner issue comment
and places it in the private custody directory; the supervisor spends it one
counted slot per window and never refunds a slot. Nothing here signs or
authenticates a signer: the record's authority is its reviewed digest and its
custody, exactly as for a selection.

The supervisor checks it twice. Check point (a), ``admit``, runs before any
process: against what the reviewed selection already fixes. Check point (b),
``confirm``, runs after qualification: against the actual packet bytes.
Each refusal is one closed ``approval-*`` code naming the refusing field.
There is no in-window human step and no manual fallback.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Match the operator phase tools' isolated local entry.
if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from scripts.ops.claude_read_commands import bounded, parsed, sha
from scripts.ops.claude_read_session import json_bytes, retain
from scripts.ops.m9_read_command import ADVICE

from constructicon.api.change_review_advice import INSTRUCTION_MAX_BYTES

SCHEMA_VERSION = 1
RECORD_LIMIT = 8192
MAX_RUNS = 100  # a reviewed bound on the slot scan, not an issuance recommendation
EXPOSURE = "subscription; backend requests unknown; no enforced monetary ceiling"
# Fresh per window: a standing record that names one is refused by name.
# The target is the DHCP address, which changes every boot; the stable host
# identity is the strict host-key alias (``host_key_alias``).
FORBIDDEN = ("boot", "candidate", "generation", "operator_binding_digest", "provider_revision",
             "target")
# Matched by exact equality against the consumer pins.
PINNED = ("source_graph", "component", "guard", "capability", "actor", "scope", "grants")
KEYS = frozenset({
    "schema_version", "consumer", "controller", "runtime", *PINNED, "instruction_max_bytes",
    "max_runs", "not_after", "exposure", "host_key_alias",
})
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
# The alias rule ``claude_read_session._target`` (claude_read_session.py:79-81) enforces.
_ALIAS = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,252}\Z")


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


def _refuse(field: str) -> ValueError:
    return ValueError("approval-" + field)


def _utc(value: object) -> bool:
    return type(value) is datetime and value.utcoffset() == timedelta(0)


def _valid(record: dict[str, Any]) -> datetime:
    """Each value's own shape; returns the parsed expiry. Raises the first bad field."""
    checks = {
        "schema_version": lambda v: type(v) is int and v == SCHEMA_VERSION,
        # One consumer: the owner's choice (ADR 0026). M9 has no standing record.
        "consumer": lambda v: v == ADVICE.id,
        "controller": lambda v: type(v) is str and re.fullmatch(r"[0-9a-f]{40}", v) is not None,
        "runtime": lambda v: type(v) is str and _DIGEST.fullmatch(v) is not None,
        "source_graph": lambda v: type(v) is str and _DIGEST.fullmatch(v) is not None,
        "component": lambda v: type(v) is str and _DIGEST.fullmatch(v) is not None,
        "guard": lambda v: type(v) is str and _DIGEST.fullmatch(v) is not None,
        "capability": lambda v: type(v) is str and bool(v),
        "actor": lambda v: type(v) is str and bool(v),
        "scope": lambda v: type(v) is str and bool(v),
        "grants": lambda v: type(v) is dict and bool(v),
        # The instruction class: the guard pin plus this bound, never above the route's.
        "instruction_max_bytes": lambda v: type(v) is int and 0 < v <= INSTRUCTION_MAX_BYTES,
        "max_runs": lambda v: type(v) is int and 0 < v <= MAX_RUNS,
        "not_after": lambda v: type(v) is str,
        "exposure": lambda v: v == EXPOSURE,
        "host_key_alias": lambda v: type(v) is str and _ALIAS.fullmatch(v) is not None,
    }
    for key in sorted(checks):
        if not checks[key](record[key]):
            raise _refuse(key)
    try:
        not_after = datetime.fromisoformat(record["not_after"])
    except ValueError as exc:
        raise _refuse("not_after") from exc
    if not _utc(not_after) or not_after.isoformat() != record["not_after"]:
        raise _refuse("not_after")
    return not_after


@dataclass(frozen=True)
class StandingApproval:
    """One checked standing owner approval: canonical bytes and their digest."""

    raw: bytes
    sha256: str
    record: dict[str, Any]
    not_after: datetime
    # The record's file. Both check points re-read it, so deleting or replacing
    # it revokes the approval; a record never loaded from a file never stands.
    path: Path | None = None

    @classmethod
    def load(cls, path: Path, sha256: str, work: Path) -> StandingApproval:
        """The record named on the CLI; it must live directly in the custody directory."""
        if not (path.is_absolute() and path.parent == work):
            raise _refuse("location")
        try:
            raw = bounded(path, RECORD_LIMIT)
        except (OSError, ValueError) as exc:
            # Absent, replaced by a link, or out of bound: deletion revokes.
            raise _refuse("unreadable") from exc
        if type(sha256) is not str or _HEX.fullmatch(sha256) is None or sha(raw) != sha256:
            raise _refuse("digest")
        return replace(cls.from_bytes(raw), path=path)

    @classmethod
    def from_bytes(cls, raw: bytes) -> StandingApproval:
        try:
            record = parsed(raw)
        except (ValueError, RecursionError) as exc:
            raise _refuse("shape") from exc
        if type(record) is not dict:
            raise _refuse("shape")
        for key in FORBIDDEN:
            if key in record:
                raise _refuse("forbidden-" + key)
        if record.keys() - KEYS:
            raise _refuse("unknown-key")
        missing = sorted(KEYS - record.keys())
        if missing:
            raise _refuse("missing-" + missing[0])
        not_after = _valid(record)
        if raw != json_bytes(record):
            raise _refuse("canonical")
        return cls(raw, sha(raw), record, not_after)

    @property
    def max_runs(self) -> int:
        return self.record["max_runs"]

    def decision(self, slot: int) -> str:
        """H(approval digest, slot): the name of that slot's exclusive selection marker."""
        return sha(json_bytes({"approval_sha256": self.sha256, "slot": slot}))

    def free_slot(self, work: Path) -> int | None:
        """The lowest unspent slot. A spent slot is never refunded."""
        for slot in range(1, self.max_runs + 1):
            if not os.path.lexists(work / ("selection-" + self.decision(slot))):
                return slot
        return None

    def suspension(self, work: Path) -> Path:
        """Written when a window is admitted; removed only when it ends accepted and clean."""
        return work / ("suspended-" + self.sha256)

    def revocation(self, work: Path) -> Path:
        """The owner's explicit revocation: any entry at this name, whatever its content."""
        return work / ("revoked-" + self.sha256)

    def _live(self) -> str | None:
        """The record's file still holds exactly the loaded bytes."""
        if self.path is None:
            return "approval-unreadable"
        try:
            current = bounded(self.path, RECORD_LIMIT)
        except (OSError, ValueError):
            return "approval-revoked"
        return None if current == self.raw else "approval-revoked"

    def _standing(self, work: Path, now: datetime, holder: str | None) -> str | None:
        if (gone := self._live()) is not None:
            return gone
        if not (_utc(now) and now < self.not_after):
            return "approval-expired"
        if os.path.lexists(self.revocation(work)):
            return "approval-revoked"
        marker = self.suspension(work)
        if holder is None:
            if os.path.lexists(marker):
                return "approval-suspended"
        else:
            # Only this window's own admission marker may be present.
            try:
                held = bounded(marker, 64)
            except (OSError, ValueError):
                return "approval-suspended"
            if held != holder.encode("ascii"):
                return "approval-suspended"
        if self.free_slot(work) is None:
            return "approval-exhausted"
        return None

    def _fit(self, consumer: object, packet: object) -> str | None:
        """Exact equality of every fixed field against a selection or packet view."""
        record = self.record
        if consumer != record["consumer"]:
            return "approval-consumer"
        if type(packet) is not dict:
            return "approval-pins"
        for key in ("controller", "runtime"):
            if packet.get(key) != record[key] or type(packet.get(key)) is not str:
                return "approval-" + key
        alias = packet.get("alias")
        if type(alias) is not str or alias != record["host_key_alias"]:
            return "approval-host_key_alias"
        pins = packet.get("pins")
        if type(pins) is not dict:
            return "approval-pins"
        for key in PINNED:
            if key not in pins or json_bytes(pins[key]) != json_bytes(record[key]):
                return "approval-" + key
        instruction = pins.get("instruction")
        try:
            size = len(instruction.encode("utf-8")) if type(instruction) is str else None
        except UnicodeEncodeError:
            size = None
        if (
            size is None
            or type(pins.get("instruction_bytes")) is not int
            or pins["instruction_bytes"] != size
            or size > record["instruction_max_bytes"]
        ):
            return "approval-instruction_max_bytes"
        return None

    def admit(self, selected: dict[str, Any], work: Path, now: datetime) -> str | None:
        """Check point (a), before any process: standing, then the selection's fixed pins.

        ``selected`` is ``QualificationBoundary.selected_pins()``.
        """
        if type(selected) is not dict:
            return "approval-pins"
        return self._standing(work, now, None) or self._fit(selected.get("consumer"), selected)

    def confirm(
        self, consumer: str, packet: bytes, work: Path, now: datetime, holder: str,
    ) -> str | None:
        """Check point (b), after qualification: the actual packet bytes.

        The packet is ``QualificationBoundary.qualify``'s checked packet
        (m9_qualification_boundary.py, the ``packet`` it builds from ``live``):
        its ``pins`` are the consumer's printed pins, beside ``alias``,
        ``controller`` and ``runtime``.
        """
        try:
            view = parsed(packet) if type(packet) is bytes else None
        except (ValueError, RecursionError):
            view = None
        return self._standing(work, now, holder) or self._fit(consumer, view)


def issue(
    selected: dict[str, Any], *, not_after: datetime, max_runs: int = 3,
    instruction_max_bytes: int = INSTRUCTION_MAX_BYTES,
) -> bytes:
    """A canonical record from a reviewed selection's fixed pins (pure).

    The owner reviews the bytes, places them in custody and records their
    digest in an owner issue comment. Recommended: seven days and three runs.
    """
    if selected.get("consumer") != ADVICE.id:  # M9 selects no consumer pins to issue for
        raise _refuse("consumer")
    pins = selected["pins"]
    raw = json_bytes({
        "schema_version": SCHEMA_VERSION,
        "consumer": selected["consumer"],
        "controller": selected["controller"],
        "runtime": selected["runtime"],
        **{key: pins[key] for key in PINNED},
        "instruction_max_bytes": instruction_max_bytes,
        "max_runs": max_runs,
        "not_after": not_after.astimezone(UTC).isoformat(),
        "exposure": EXPOSURE,
        "host_key_alias": selected["alias"],
    })
    approval = StandingApproval.from_bytes(raw)
    refusal = approval._fit(selected["consumer"], selected)
    if refusal is not None:
        raise ValueError(refusal)
    return raw


def main(argv: list[str] | None = None) -> int:
    from scripts.ops.m9_qualification_boundary import QualificationBoundary

    parser = argparse.ArgumentParser(description="Issue one standing approval record.",
                                     allow_abbrev=False)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--selection-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max-runs", type=int, default=3)
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days must be at least 1")
    try:
        header = parsed(bounded(args.selection, 2 * 1024 * 1024))
        host = QualificationBoundary(
            args.selection, args.selection_sha256, args.out.parent / "unused-issuance-work",
            target=header["target"], alias=header["alias"],
        )
        now = datetime.now(UTC).replace(microsecond=0)
        raw = issue(host.selected_pins(), not_after=now + timedelta(days=args.days),
                    max_runs=args.max_runs)
        retain(args.out, raw)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        code = str(exc) if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(exc)) else type(exc).__name__
        parser.exit(2, f"standing approval not issued: {code}\n")
    print(sha(raw))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
