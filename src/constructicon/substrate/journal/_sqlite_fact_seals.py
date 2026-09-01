"""Mechanical positive seals for immutable durable SQLite facts.

Table owners choose the family, selector, and exact bytes that constitute one
fact.  This module only stores and proves that independent observation, so a
missing or relocated primary row cannot be mistaken for permission to mint it
again.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, digest
from constructicon.substrate.journal._sqlite_base import (
    _durable_digest,
    _durable_text,
)


@dataclass(frozen=True)
class DurableFactSeal:
    family: str
    fact_key: str
    selector: str
    fact_hash: Digest


def durable_fact_hash(family: str, exact_fields: Any) -> Digest:
    """Hash table-owned exact fields under one family-separated identity."""

    return digest(
        "durable-fact-seal",
        1,
        {"family": family, "exact_fields": exact_fields},
    )


def sealed_fact_hash(
    *,
    family: str,
    fact_key: str,
    selector: str,
    fact: Digest,
) -> Digest:
    """Bind one owner's content hash to the identity it is stored under.

    An owner chooses which bytes constitute its fact. If that content hash
    omits the primary key, two same-shaped rows can trade places and every seal
    still matches, which is the one attack seals exist to stop. Every current
    owner does include its key — that has been checked, family by family — but
    each of them kept that rule independently, and a rule kept independently is
    what fails silently in the family added next.

    So the identity is bound here instead. Be exact about what that buys: an
    owner still chooses the strings it passes as `fact_key` and `selector`, and
    passing a constant or the wrong column is still a mistake it can make. What
    it can no longer do is declare an identity to the seal layer and leave that
    identity out of what the seal commits to. `durable_fact_hash` answers what
    a row says; this answers which row it was stored as.
    """

    return digest(
        "durable-fact-seal-identity",
        1,
        {
            "family": family,
            "fact_key": fact_key,
            "selector": selector,
            "fact": str(fact),
        },
    )


def _seal_from_row(row: sqlite3.Row) -> DurableFactSeal:
    try:
        family = _durable_text(row["family"], fact="durable fact seal family")
        fact_key = _durable_text(
            row["fact_key"],
            fact=f"durable {family!r} fact seal key",
        )
        return DurableFactSeal(
            family=family,
            fact_key=fact_key,
            selector=_durable_text(
                row["selector"],
                fact=f"durable {family!r} fact {fact_key!r} selector",
            ),
            fact_hash=_durable_digest(
                row["fact_hash"],
                fact=f"durable {family!r} fact {fact_key!r} hash",
            ),
        )
    except JournalDamaged:
        raise
    except (TypeError, ValueError) as exc:
        raise JournalDamaged("durable fact seal is not a valid record") from exc


def durable_fact_seal(
    connection: sqlite3.Connection,
    *,
    family: str,
    fact_key: str | None = None,
    selector: str | None = None,
) -> DurableFactSeal | None:
    """Read one seal by either stored identity, detecting a split row."""

    if fact_key is None and selector is None:
        raise ValueError("a durable fact seal lookup needs a key or selector")
    clauses: list[str] = []
    parameters: list[str] = [family]
    if fact_key is not None:
        clauses.append("fact_key = ?")
        parameters.append(fact_key)
    if selector is not None:
        clauses.append("selector = ?")
        parameters.append(selector)
    rows = connection.execute(
        "SELECT family, fact_key, selector, fact_hash FROM durable_fact_seals"
        " WHERE family = ? AND ("
        + " OR ".join(clauses)
        + ") LIMIT 2",
        tuple(parameters),
    ).fetchall()
    if len(rows) > 1:
        raise JournalDamaged(
            f"durable {family!r} fact has contradictory key/selector seals"
        )
    if not rows:
        return None
    seal = _seal_from_row(rows[0])
    if seal.family != family:
        raise JournalDamaged("durable fact seal family contradicts its selector")
    if fact_key is not None and seal.fact_key != fact_key:
        raise JournalDamaged(
            f"durable {family!r} fact selector contradicts key {fact_key!r}"
        )
    if selector is not None and seal.selector != selector:
        raise JournalDamaged(
            f"durable {family!r} fact key contradicts selector {selector!r}"
        )
    return seal


def require_durable_fact_seal(
    connection: sqlite3.Connection,
    *,
    family: str,
    fact_key: str,
    selector: str,
    fact_hash: Digest,
) -> DurableFactSeal:
    """Prove one present row against its independent positive seal."""

    seal = durable_fact_seal(
        connection,
        family=family,
        fact_key=fact_key,
        selector=selector,
    )
    if seal is None:
        raise JournalDamaged(
            f"durable {family!r} fact {fact_key!r} has no positive seal"
        )
    if seal.fact_hash != sealed_fact_hash(
        family=family,
        fact_key=fact_key,
        selector=selector,
        fact=fact_hash,
    ):
        raise JournalDamaged(
            f"durable {family!r} fact {fact_key!r} contradicts its positive seal"
        )
    return seal


def store_durable_fact_seal(
    connection: sqlite3.Connection,
    *,
    family: str,
    fact_key: str,
    selector: str,
    fact_hash: Digest,
) -> DurableFactSeal:
    """Insert one write-once seal, or prove the already stored exact fact."""

    sealed = sealed_fact_hash(
        family=family,
        fact_key=fact_key,
        selector=selector,
        fact=fact_hash,
    )
    prior = durable_fact_seal(
        connection,
        family=family,
        fact_key=fact_key,
        selector=selector,
    )
    if prior is not None:
        if prior.fact_hash != sealed:
            raise JournalDamaged(
                f"durable {family!r} fact {fact_key!r} was sealed contradictorily"
            )
        return prior
    try:
        connection.execute(
            "INSERT INTO durable_fact_seals"
            " (family, fact_key, selector, fact_hash) VALUES (?, ?, ?, ?)",
            (family, fact_key, selector, str(sealed)),
        )
    except sqlite3.IntegrityError as exc:
        raise JournalDamaged(
            f"durable {family!r} fact {fact_key!r} has a conflicting seal"
        ) from exc
    return DurableFactSeal(
        family=family,
        fact_key=fact_key,
        selector=selector,
        fact_hash=sealed,
    )


def validate_durable_fact_seal_inventory(
    connection: sqlite3.Connection,
    *,
    known_families: Collection[str],
    expected_count: int,
) -> None:
    """Prove migration left exactly the seals its primary facts require.

    Table-owned seal writers have already inserted or reconciled every primary
    row before this reverse check. Any surplus is therefore an orphan, and an
    unknown family has no projector capable of proving it.
    """

    rows = connection.execute(
        "SELECT family, fact_key, selector, fact_hash FROM durable_fact_seals"
    ).fetchall()
    for row in rows:
        seal = _seal_from_row(row)
        if seal.family not in known_families:
            raise JournalDamaged(
                f"durable fact seal family {seal.family!r} is unknown"
            )
    if len(rows) != expected_count:
        raise JournalDamaged(
            "durable fact seal inventory has an orphan or missing primary fact"
        )
