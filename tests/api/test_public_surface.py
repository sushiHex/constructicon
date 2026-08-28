"""The public L4 surface exposes no unauthenticated mutation back door."""

from __future__ import annotations

from typing import Any


def test_constructicon_has_no_public_domain_mutators_or_mutable_stores(world: Any) -> None:
    for name in (
        "start",
        "resume",
        "reproduce",
        "cancel",
        "promote",
        "rollback",
        "prepare",
        "run_prepared",
        "register",
        "promote_initial",
        "journal",
        "registry",
    ):
        assert not hasattr(world, name), name
