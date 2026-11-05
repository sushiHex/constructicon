# Candidate: atomic SQLite migration rungs (issue #368)

Branch `fix/cloud-migration`, based on `b22581ac2922b27f35b0a83b528a25a2cb279073`.
Code + tests only; delivery handoff and implementation record are left to the
orchestrator.

## Reproduction (premise confirmed)

A schema-5 store; opener A reads `user_version = 5` and pauses before
`BEGIN IMMEDIATE`; opener B's constructor climbs to the current schema; A
resumes. `_migrate_m5_to_m6` took the lock, ran `executescript(_V6_SCHEMA)`
(which also commits the open transaction, so the lock was dropped) and wrote
`user_version = 6` over a current store. Later opens failed with
`JournalDamaged`. M1->M2, M2->M3, M3->M4 and M4->M5 had the same missing
under-lock check; M2->M3 had no transaction at all; M4->M5, M5->M6 and M1->M2
used `executescript` after `BEGIN IMMEDIATE`. M6->M7, M7->M8, M8->M9 already
re-read under the lock and are unchanged.

## Design

`_begin_rung(connection, expected)` in `_sqlite_schema.py`: `BEGIN IMMEDIATE`,
re-read `user_version`, roll back and return `False` if it is not `expected`.
Every rung M1->M2 .. M5->M6 starts with it and returns early when stale.
`executescript` inside a rung is replaced by statement-wise `execute` of the
same DDL (`_ddl_statements`, already used by the fresh create) so DDL, backfill
and the version stamp commit together under one held lock. No retry, timeout,
tolerance or heal-on-open was added; rung bodies and refusal rules are
unchanged. Frozen plans/ADRs, workflows and fixtures untouched.

## Evidence (all credential-free, no vendor binaries)

`tests/migrations/test_migration_rung_atomicity.py`:
- two real `SqliteJournal` constructors, A held by a trace callback at its
  `BEGIN IMMEDIATE`, B finishes first, for genuine stale v5/v4/v3/v2 stores:
  A succeeds, version stays current, store reopens, historical run readable
  (accepting).
- tables and version published together for M4->M5 / M5->M6 (observed from an
  outside read-only connection after every statement).
- malformed v3 lease row still raises `JournalDamaged`, version stays 3,
  refused again on reopen (refusing).
- every private stale step (including M1->M2) is a no-op on a current store.
With the source change stashed, 11 of 12 new test cases fail (the refusal test
passes both ways, as intended); with it all pass.

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/migrations
tests/test_mutation_inventories.py tests/test_refusal_names.py` -> 157 passed;
`uv run ruff check` on both files clean; `mypy` on `_sqlite_schema.py` clean.

## Not run

Full suite / `uv run verify`, import-linter, CI (not observed, no claim made),
the capability-provenance mutation script itself (only the inventory-validity
tests above), Windows/platform lanes.

## Limitations

- M1->M2 race is covered by a stale-step test, not a constructor race (no cheap
  genuine M1 fixture for the pause harness).
- v2/v3/v4/v5 race fixtures are produced by down-shaping a current store, as
  the existing v4/v5 migration tests do, not by pinned historical writers.
- Rungs that raise mid-body rely on connection close to roll back, as before.

Issue: #368
