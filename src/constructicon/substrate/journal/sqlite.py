"""One WAL store implementing Journal, RegistryStore, and ControlStore.

The private mixins are implementation decomposition only; callers see one concrete
``SqliteJournal`` and the concepts remain separate L0 protocols.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from constructicon.core.envelope import utc_now
from constructicon.substrate.journal._sqlite_base import (
    _checkpoint_identity,
    _manifest_semantically_equal,
    _path_key,
    _SqliteBase,
)
from constructicon.substrate.journal._sqlite_control import _SqliteControlMixin
from constructicon.substrate.journal._sqlite_execution import _SqliteExecutionMixin
from constructicon.substrate.journal._sqlite_queries import _SqliteQueriesMixin
from constructicon.substrate.journal._sqlite_registry import _SqliteRegistryMixin
from constructicon.substrate.journal._sqlite_schema import (
    SCHEMA_VERSION,
    _SqliteSchemaMixin,
)


class SqliteJournal(
    _SqliteControlMixin,
    _SqliteQueriesMixin,
    _SqliteSchemaMixin,
    _SqliteExecutionMixin,
    _SqliteRegistryMixin,
    _SqliteBase,
):
    def __init__(self, db_path: Path | str, *, now_fn: Callable[[], datetime] = utc_now) -> None:
        super().__init__(db_path, now_fn=now_fn)


__all__ = [
    "SCHEMA_VERSION",
    "SqliteJournal",
    "_checkpoint_identity",
    "_manifest_semantically_equal",
    "_path_key",
]
