"""Rebinding a positive seal behind a coordinated corruption.

A seal binds the identity it is stored under, so a test that rewrites a primary
row behind its seal must rebind under that same identity. Reading the stored
key and selector back rather than restating them keeps the helper honest about
which fact it is resealing, and makes a lookup that matches nothing an error
instead of a silent no-op.

Tests that reach for this are aimed at a deeper relationship or command-plan
proof. Ordinary single-row corruption must never call it: the positive seal is
exactly the boundary that should catch that case first.
"""

from __future__ import annotations

import sqlite3

from constructicon.core.identity import Digest
from constructicon.substrate.journal._sqlite_fact_seals import sealed_fact_hash


def reseal_primary_fact(
    connection: sqlite3.Connection,
    *,
    family: str,
    fact: Digest,
    fact_key: str | None = None,
    selector: str | None = None,
) -> None:
    """Rebind one seal to the new content of the row it already identifies."""

    if (fact_key is None) == (selector is None):
        raise ValueError("reseal one fact by exactly one of key or selector")
    column = "fact_key" if fact_key is not None else "selector"
    value = fact_key if fact_key is not None else selector
    stored = connection.execute(
        "SELECT fact_key, selector FROM durable_fact_seals"
        f" WHERE family = ? AND {column} = ?",
        (family, value),
    ).fetchone()
    if stored is None:
        raise AssertionError(f"no {family!r} seal is stored under {value!r}")
    updated = connection.execute(
        f"UPDATE durable_fact_seals SET fact_hash = ? WHERE family = ? AND {column} = ?",
        (
            str(
                sealed_fact_hash(
                    family=family,
                    fact_key=stored[0],
                    selector=stored[1],
                    fact=fact,
                )
            ),
            family,
            value,
        ),
    )
    assert updated.rowcount == 1
