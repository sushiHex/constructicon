"""Source-only proposal for a complete drift inventory; not a host collector.

Nothing here reads files, runs commands, captures a baseline or qualifies a host.
Callers supply already bounded bytes and positively completed synthetic/collected
query results. Live adoption needs a separately reviewed collector and procedure.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import StrEnum
from subprocess import CompletedProcess
from typing import Literal

FactKey = Literal[
    "kernel", "bwrap_digest", "bwrap_version", "bwrap_held", "apparmor_enabled",
    "userns_restrict", "apparmor_abi", "os_release", "architecture",
]
KEYS: tuple[FactKey, ...] = (
    "kernel", "bwrap_digest", "bwrap_version", "bwrap_held", "apparmor_enabled",
    "userns_restrict", "apparmor_abi", "os_release", "architecture",
)
MAX_BASELINE_BYTES = 2048
MAX_QUERY_BYTES = 129  # one scalar of at most 128 ASCII bytes, plus its LF


class Refusal(StrEnum):
    BASELINE = "invalid-baseline"
    OBSERVATION = "incomplete-observation"


class InventoryRefused(ValueError):
    """Fixed reason only: never echo host bytes, keys or command diagnostics."""

    def __init__(self, reason: Refusal) -> None:
        self.reason = reason
        super().__init__(reason.value)


def _valid_scalar(key: FactKey, value: str) -> bool:
    if key in ("bwrap_digest", "apparmor_abi"):
        return re.fullmatch(r"[0-9a-f]{64}", value) is not None
    if key in ("bwrap_held", "userns_restrict"):
        return value in ("0", "1")
    if key == "apparmor_enabled":
        return value in ("Y", "N")
    if key == "architecture":
        return re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", value) is not None
    # Kernel, package and OS version tokens; no controls, whitespace or TSV syntax.
    return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+:~_-]{0,127}", value) is not None


@dataclass(frozen=True)
class HostFacts:
    """Complete proposed inventory. Completeness is not health or qualification."""

    kernel: str
    bwrap_digest: str
    bwrap_version: str
    bwrap_held: bool
    apparmor_enabled: bool
    userns_restrict: bool
    apparmor_abi: str
    os_release: str
    architecture: str

    def __post_init__(self) -> None:
        for key in KEYS:
            value = getattr(self, key)
            if key in ("bwrap_held", "apparmor_enabled", "userns_restrict"):
                valid = type(value) is bool
            else:
                valid = type(value) is str and _valid_scalar(key, value)
            if not valid:
                raise InventoryRefused(Refusal.BASELINE)


def _facts(values: Mapping[str, str], reason: Refusal) -> HostFacts:
    if set(values) != set(KEYS):
        raise InventoryRefused(reason)
    if any(not _valid_scalar(k, values[k]) for k in KEYS):
        raise InventoryRefused(reason)
    return HostFacts(
        kernel=values["kernel"], bwrap_digest=values["bwrap_digest"],
        bwrap_version=values["bwrap_version"], bwrap_held=values["bwrap_held"] == "1",
        apparmor_enabled=values["apparmor_enabled"] == "Y",
        userns_restrict=values["userns_restrict"] == "1",
        apparmor_abi=values["apparmor_abi"], os_release=values["os_release"],
        architecture=values["architecture"],
    )


def decode_baseline(blob: bytes) -> HostFacts:
    """Accept exactly nine distinct known LF-terminated TSV rows, in any order."""
    if type(blob) is not bytes or not blob or len(blob) > MAX_BASELINE_BYTES:
        raise InventoryRefused(Refusal.BASELINE)
    try:
        text = blob.decode("ascii")
    except UnicodeDecodeError:
        raise InventoryRefused(Refusal.BASELINE) from None
    rows = text.split("\n")
    if rows[-1] != "":
        raise InventoryRefused(Refusal.BASELINE)
    values: dict[str, str] = {}
    for row in rows[:-1]:
        parts = row.split("\t")
        if len(parts) != 2 or parts[0] in values:
            raise InventoryRefused(Refusal.BASELINE)
        values[parts[0]] = parts[1]
    return _facts(values, Refusal.BASELINE)


def decode_observation(outcomes: Mapping[str, CompletedProcess[bytes]]) -> HostFacts:
    """Require all nine affirmative query completions before interpreting values.

    A return code belongs to the underlying fact query, not an outer printf that
    can swallow its failure. No command is executed and no provenance is inferred.
    The future collector must bound reads before producing these results.
    """
    if set(outcomes) != set(KEYS):
        raise InventoryRefused(Refusal.OBSERVATION)
    values: dict[str, str] = {}
    for key in KEYS:
        result = outcomes[key]
        if (not isinstance(result, CompletedProcess) or type(result.returncode) is not int
                or result.returncode != 0 or type(result.stdout) is not bytes
                or not 1 <= len(result.stdout) <= MAX_QUERY_BYTES or result.stderr != b""
                or type(result.stderr) is not bytes):
            raise InventoryRefused(Refusal.OBSERVATION)
        try:
            value = result.stdout.decode("ascii")
        except UnicodeDecodeError:
            raise InventoryRefused(Refusal.OBSERVATION) from None
        if not value.endswith("\n") or "\n" in value[:-1]:
            raise InventoryRefused(Refusal.OBSERVATION)
        values[key] = value[:-1]
    return _facts(values, Refusal.OBSERVATION)


@dataclass(frozen=True)
class Comparison:
    status: Literal["unchanged", "drifted"]
    changed_keys: tuple[FactKey, ...]


def compare(baseline: HostFacts, current: HostFacts) -> Comparison:
    """Only complete inputs reach comparison; output contains no host values."""
    changed = tuple(key for key in KEYS if getattr(baseline, key) != getattr(current, key))
    return Comparison("drifted" if changed else "unchanged", changed)


# The explicit type and inventory must stay in one-to-one correspondence.
assert tuple(field.name for field in fields(HostFacts)) == KEYS
