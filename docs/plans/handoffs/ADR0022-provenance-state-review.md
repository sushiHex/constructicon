# ADR 0022 provenance slice: state and crash review

Design review before source implementation for
[#179](https://github.com/sushiHex/constructicon/issues/179), under accepted
[ADR 0022](../../adr/0022-operator-disposal-records-abandoned-capabilities.md).
Inspected branch `implement/adr22-provenance` at `6b7b653`, 2026-10-13.
The acceptance revision is PR 178; implementation merges wait for its merge.
This document supplies no executed implementation evidence. Root reviewed the
complete state analysis before source or tests changed. A focused independent
Sol pass also found no blocking gap in migration order, floor reconstruction,
or missing-evidence handling. Test-first implementation was authorized after
those checks; executed proof belongs in the living implementation record.

## Smallest implementation boundary

Implement persistence schema 8, universal positive run eras, their exact
floor-inventory commitment, the two migration-only old-lost witness families,
and current worker writer guards. Current journal capability reads and open
must validate these facts through canonical projectors. No public disposal
command, new result response, accounting URI, MCP handler, provider operation,
RunHost change, or graph/walker behavior is introduced here.

Add only strict frozen L0 storage values that the actual projectors consume:
an accounting era and exact historical lost-event/initial-lifecycle evidence.
Do not impose the future command request's bounds on valid retained legacy
identities. Defer its request, administrative snapshot, plan, receipt and
response contracts until their implementing slices. Extend the existing
co-located journal; do not add a protocol, separate manager or memory journal.

Reuse `_sqlite_fact_seals` for exact identity-bound positive seals. Keep the
operation-specific proof owners beside `_sqlite_leases` or in one companion
capability provenance module. Existing exact history validation remains the
single law used by migration, current lease reads and floor reconstruction;
factor a validated internal history value only where reconstruction needs its
already-checked events. Preserve cross-run same-identity damage checks rather
than adding a run filter that hides them. Do not move the full inventory check
into the common worker event-allocation path.

The era has one row selected by run id and one independent seal. Its exact
facts are run identity/world, source, floor and canonical inventory digest.
Witness keys are the exact event identity, or the exact initial legacy pair.
A lost-event witness also retains its lease pair for pair projection. Multiple
historical lost transitions may name the same pair, so pair selection must
not accidentally become a unique constraint: the shared seal table's unique
selector includes the exact event identity as well as the pair. Point and
pair/batch reads validate the same typed witness against its source event.

## What exists at each boundary

The persistence path is synchronous. There is no new application `await`,
provider await, background task or local authority latch. The relevant
interleavings are SQLite lock acquisition, snapshot establishment, commit,
exception delivery and another connection's commit. An async caller can be
cancelled before or after its synchronous call; cancellation cannot publish a
partial transaction or supply migration evidence.

| Boundary | State on entry | Required state on exit or interruption |
| --- | --- | --- |
| New journal open | Version read before the write lock may already be stale. | Re-read version under the migration/create lock; a loser joins the winner rather than minting again. |
| 7 to 8 migration lock | Existing schema-7 facts may be valid or damaged; no v8 proof is owed yet. | Validate the old journal using its unchanged canonical inventory before minting any v8 fact. |
| Migration statements | New DDL, era rows and witness seals are private to one write transaction. | Failure rolls all of them back; outside readers see either coherent version 7 or coherent version 8. |
| Version publication | Every run era, floor commitment and applicable witness has been written and validated. | Version 8 and its facts become visible in the same commit. No DDL helper may implicitly commit early. |
| Current open | A writer may commit between inventory statements. | One read snapshot covers rows, histories, era commitments, witness/row seals and expected counts. Open validates and never repairs. |
| Current creation | A run id may already exist, or its retained proof may survive a deleted row. | Existing-run retry proves the era; a genuinely inserted run co-commits a creation era. Neither case reseals missing evidence. |
| Creation commit | Manifest, run, world seal, origin and creation era are uncommitted. | Failure rolls the complete creation back. A crash after commit leaves a complete fact that the same creation retry validates. |
| Capability read | A later transition/acquisition may commit while projection is running. | One snapshot validates current history and reconstructs the older sealed floor. The next read sees the later complete state. |
| Current worker transition | A row may be historical lost or active; worker ownership may be stale. | No new lost fact or lost-to-active transition is minted. Ordinary active-to-closed and its existing ownership fences still work. |

Use individual DDL `execute` calls within `BEGIN IMMEDIATE`, following current
fresh-schema creation. Do not use `executescript` within the new migration: an
implicit commit would publish part of this state. Schema-version and required
table checks must refuse an incomplete current schema before create-if-missing
helpers could turn damage into repair.

## Migration and creation authority

The 7 to 8 step rechecks that version is exactly 7 under `BEGIN IMMEDIATE`.
First run the existing schema-7 table, world, command, event, lease and seal
inventory, with its original known-family/count law. A new schema-8 predicate
must not run early and condemn genuine old facts for missing new evidence.
Conversely, current-open checks must not accept the old-family law as a bypass.

For each retained run, validate world and complete event extent, then record
`source="schema7-migration"`, its actual latest sequence as floor, and the
complete canonical acquisition/lifecycle inventory digest at that cut. Include
empty runs and legacy acquisitions in every state. Mint exact witnesses for
valid retained lost transitions and initially lost legacy seals. Then validate
all schema-8 inventories, set `user_version=8` and commit. No earlier run/event,
legacy-seal, plan, response or manifest bytes are rewritten.

Migration-only mint helpers refuse a current schema even when called directly
from a test. Lost-event witnesses require the exact migration era and a source
event at or below its floor; initial-lost witnesses require the exact migrated
legacy seal. A creation-era run cannot acquire either historical witness.
Do not classify new unattributed lost events as historical on read or open.

Fresh schema creation has no retained runs or historical witnesses. Actual
`create_run` insertion co-commits `source="schema8-creation"`, floor zero and
the canonical empty inventory. The idempotent existing-run branch requires
its retained era; it does not call the creation-era mint helper. Check orphan
era rows/seals before treating an absent run as permission to create it.

The first deployable schema-8 slice also refuses current worker requests that
mint lost or reactivate lost. Deferring this guard until disposal exists would
permit new facts that cannot obtain either pre-v8 proof or a current receipt.
Retained histories keep their original lawful transitions, including old lost
events followed by other states. The migration-only evidence describes those
events, not an invented administrative actor, reason or physical cleanup.

## Reconstructing the committed floor

Canonical inventory is ordered by exact `(lease_id, acquisition_epoch)`, not by
query order or mutable observation time. Each member includes immutable
acquisition fields, exact initial provenance, and the lifecycle established
at the floor, including its observed update time and applicable exact event
provenance. This digest is not the current row inventory after later activity.

Validate each retained acquisition's full current history first. A current
acquisition appears in the committed inventory only if its exact
`LeaseAcquired` sequence is at or before the floor. Start its historical state
at active/None and replay only applicable transitions through the floor.
A retained legacy acquisition starts from its positive initial lifecycle seal;
its lack of an initial event position is not repaired. Replay its applicable
exact post-seal transitions through the migration floor. Preserve the existing
historical interpretation of older events summarized by that legacy seal.

Later valid acquisitions are omitted from the older inventory; later valid
transitions do not change its reconstructed lifecycle. The reconstruction
still validates current final rows, full canonical histories, cross-run
identities, reverse event-to-row inventory and the run's event extent. An
accounting cut below the positively recorded floor refuses; only exact creation
evidence selects full history from zero. A missing era is always damage for a
retained run, including a genuinely empty migrated run.

A lost-event witness binds the exact historical event and acquisition
provenance, even if later retained events changed its row's current state.
An initial-lost witness binds the legacy seal's initial lifecycle, not a demand
that the current row still be lost. Multiple old lost events on one pair remain
distinct witnesses. Do not accidentally require the final row to match an
older witnessed state.

## Missing-evidence cases and tests written first

Every damage case uses the same canonical point/batch projector as the
permitting case, and also exercises reopen where inventory applies. Use
assertions that affirm the accepting fact, selected era, preserved bytes and
actual injected seam. No test infers success from an empty error list.

| Test class | Permitting evidence and refusal attack |
| --- | --- |
| Strict contracts | Exact typed era/witness round trips; reject bool/float sequences, unknown source and noncanonical storage without normalizing retained facts. |
| Genuine history | Actual schema-7 writer produces a lost transition; actual schema-6 writer produces an initial lost acquisition. Both migrate, read and reopen, preserve old bytes, and receive only their exact historical witness families. |
| Universal eras | Empty migrated runs, nonlegacy-only runs, and legacy active/closed/lost runs all receive migration eras; new creation receives its zero era atomically. |
| Floor reconstruction | A migrated acquisition later closes and a new pair is acquired; reopen and canonical projection reproduce the original committed digest. Later acquisitions are not mistaken for migration members. |
| Erased eventless history | An explicitly admitted synthetic eventless legacy shape migrates. Erasing acquisition+legacy seal fails its retained commitment; erasing those plus era+era seal fails run-to-era coverage. This is reader-admitted damage evidence, not a claim that an old writer emitted an eventless row. |
| Era damage | Delete row, seal, or both while the run survives; relocate/swap identities; change a valid source, floor, world or inventory digest to another valid value. No current open/read/create retry repairs it. |
| Witness damage | Delete/move witness or source; change canonical source bytes; attach a witness above floor or to a creation-era run; retain multiple lost events on one pair; initial-lost and transition-lost facts stay disjoint. |
| Worker guards | Refused new lost/reactivation requests leave row, event extent and ownership unchanged; active acquire, ordinary close and retained old-history reads remain permitted. |
| Migration crash | Inject before version publication after some new writes; version/facts roll back. Inject after commit; reopen sees the complete v8 graph once. Affirm the seam was reached. |
| Creation crash | Inject after run insertion before era publication; rollback leaves no partial creation. Existing after-commit probe/retry proves one complete creation era and refuses deleted evidence. |
| Race and snapshot | Two openers choose rung 7; the loser preserves winner-created current facts. A writer commits inside an inventory/read interval; the reader holds one coherent snapshot and a later read sees that commit. |

Planned test modules are `tests/core/test_capability_accounting_provenance.py`,
`tests/migrations/test_sqlite_v7_to_v8.py`, and
`tests/substrate/journal/test_capability_accounting_provenance.py`, with narrow
extensions to existing lease-projection, migration-race and read-snapshot
suites. Actual historical-writer fixture creation uses pinned source in a
separate local Python process, with no vendor execution or credentials. It
must not disguise a current database by lowering its version. Existing older
schema fixture helpers still need to climb to current without leaving new era
families behind when constructing their named older worlds.

Root owns mutation inventory, archive manifest, living implementation record,
CI and PR integration. This lane supplies stable killing-test node ids once
tests exist and does not edit accepted ADR/plan bytes or commit independently.
Required final local gate is `uv run verify` with
`PYTHONIOENCODING=utf-8` and `UV_PROJECT_ENVIRONMENT=.venv312`; focused tests run
on Python 3.12 first. Any unexecuted or platform-skipped proof is reported as
such. The eventual disposal command/replay and public accounting proofs remain
later slices rather than claims established by this provenance implementation.
