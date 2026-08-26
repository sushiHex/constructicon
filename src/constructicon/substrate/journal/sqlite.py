"""SQLite v5: one WAL store implementing Journal, RegistryStore, ControlStore.

The private mixins are implementation decomposition only; callers see one concrete
``SqliteJournal`` and the concepts remain separate L0 protocols.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from constructicon.core.envelope import utc_now
from constructicon.substrate.journal._sqlite_v5_control import _M6ControlMixin
from constructicon.substrate.journal._sqlite_v5_reads import _M6ReadMixin
from constructicon.substrate.journal._sqlite_v5_schema import (
    SCHEMA_VERSION,
    _M6SchemaMixin,
)
from constructicon.substrate.journal.sqlite_legacy import (
    SqliteJournal as _LegacySqliteJournal,
)


class SqliteJournal(
    _M6ControlMixin, _M6ReadMixin, _M6SchemaMixin, _LegacySqliteJournal
):
    def __init__(
        self, db_path: Path | str, *, now_fn: Callable[[], datetime] = utc_now
    ) -> None:
        super().__init__(db_path, now_fn=now_fn)


__all__ = ["SCHEMA_VERSION", "SqliteJournal"]
