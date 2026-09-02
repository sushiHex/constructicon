"""M5 additive component contracts preserve historical registry identities."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from constructicon.api.system import Constructicon
from constructicon.core.identity import Digest
from constructicon.runtime.context import NodeContext
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import BRIEF, ISSUE, atomic
from tests.migrations.test_sqlite_v6_to_v7 import _downgrade_v7_schema_to_v6


async def compatibility_impl(
    ctx: NodeContext,
    inputs: Mapping[str, Any],
) -> Mapping[str, Any]:
    return {"brief": {"title": inputs["issue"]["title"]}}


def test_legacy_component_reregistration_is_semantic_not_byte_exact(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy-registry.db"
    journal = SqliteJournal(database)
    definition, implementation = atomic(
        "compat/legacy",
        (ISSUE,),
        (BRIEF,),
        compatibility_impl,
    )
    version = definition.content_hash()
    # Same M1-M4 semantics, deliberately different JSON bytes and key order.
    historical_json = json.dumps(
        json.loads(definition.model_dump_json()),
        sort_keys=True,
        indent=2,
    )
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO components "
            "(name, content_hash, definition_json, registered_at) "
            "VALUES (?, ?, ?, ?)",
            (
                definition.name,
                str(version),
                historical_json,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()

    # Only the migration may mint positive proof for a retained schema-6 row.
    journal = SqliteJournal(database)
    system = Constructicon(journal=journal)
    observed = system._register(definition, implementation)
    assert observed == version
    assert isinstance(observed, Digest)
    with sqlite3.connect(database) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM components WHERE name = ? AND content_hash = ?",
            (definition.name, str(version)),
        ).fetchone()[0]
    assert count == 1
