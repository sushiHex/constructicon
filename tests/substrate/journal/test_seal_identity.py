"""A seal says which row it is about, not only what that row said.

An owner chooses the bytes that constitute its fact. Anti-relocation is not
theirs to choose: if the content hash omits the primary key, two same-shaped
rows can trade places and every seal still matches — the one attack positive
seals exist to stop. Nineteen owners each remembering to fold their key in is a
convention, and a convention is what fails silently in the one family nobody
checked.

So the seal layer binds the identity itself, where it already holds it and no
owner can forget.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from constructicon.core.errors import JournalDamaged
from constructicon.substrate.journal._sqlite_fact_seals import (
    durable_fact_hash,
    require_durable_fact_seal,
    sealed_fact_hash,
    store_durable_fact_seal,
)
from constructicon.substrate.journal.sqlite import SqliteJournal

FAMILY = "test_twins"
CONTENT = durable_fact_hash(FAMILY, {"shape": "identical"})


def _sealed(fact_key: str, selector: str | None = None) -> str:
    return str(
        sealed_fact_hash(
            family=FAMILY,
            fact_key=fact_key,
            selector=selector if selector is not None else fact_key,
            fact=CONTENT,
        )
    )


def test_identical_content_under_different_identities_seals_differently() -> None:
    assert _sealed("twin-a") != _sealed("twin-b")


def test_the_key_and_the_selector_are_both_bound() -> None:
    """Neither half of the identity may be traded for the other."""

    assert _sealed("a", "b") != _sealed("b", "a")
    assert _sealed("a", "a") != _sealed("a", "b")
    assert _sealed("a", "b") != _sealed("b", "b")


def test_the_family_separates_two_facts_that_agree_about_everything_else() -> None:
    same = sealed_fact_hash(
        family="other_family",
        fact_key="a",
        selector="a",
        fact=CONTENT,
    )
    assert str(same) != _sealed("a")


def test_two_twin_facts_cannot_trade_places_behind_their_seals(
    tmp_path: Path,
) -> None:
    """The paired swap: the one relocation a content-only hash cannot see.

    Move one row and it loses its seal; move two same-shaped rows into each
    other's identity and, under a hash that names only content, both seals
    still match. Binding the identity is what turns that back into damage.
    """

    journal = SqliteJournal(tmp_path / "twins.db")
    with journal._txn() as connection:
        for twin in ("twin-a", "twin-b"):
            store_durable_fact_seal(
                connection,
                family=FAMILY,
                fact_key=twin,
                selector=twin,
                fact_hash=CONTENT,
            )

    with sqlite3.connect(tmp_path / "twins.db") as raw:
        # Exactly the swap: each seal keeps its own hash and takes the other's
        # identity, which is what a relocated pair of primary rows looks like.
        raw.execute(
            "UPDATE durable_fact_seals SET fact_key = ?, selector = ?"
            " WHERE family = ? AND fact_key = ?",
            ("twin-swap", "twin-swap", FAMILY, "twin-a"),
        )
        raw.execute(
            "UPDATE durable_fact_seals SET fact_key = ?, selector = ?"
            " WHERE family = ? AND fact_key = ?",
            ("twin-a", "twin-a", FAMILY, "twin-b"),
        )
        raw.execute(
            "UPDATE durable_fact_seals SET fact_key = ?, selector = ?"
            " WHERE family = ? AND fact_key = ?",
            ("twin-b", "twin-b", FAMILY, "twin-swap"),
        )
        raw.commit()

    with journal._read() as connection:
        for twin in ("twin-a", "twin-b"):
            with pytest.raises(JournalDamaged, match="contradicts its positive seal"):
                require_durable_fact_seal(
                    connection,
                    family=FAMILY,
                    fact_key=twin,
                    selector=twin,
                    fact_hash=CONTENT,
                )
