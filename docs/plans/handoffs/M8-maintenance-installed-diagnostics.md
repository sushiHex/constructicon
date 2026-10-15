# Maintenance diagnostics from a reviewed installed controller

Source-only successor under [#186](https://github.com/sushiHex/constructicon/issues/186).
This does not authorize a host start, recovery or model attempt. The next exact
session procedure must name the merged controller, fresh paths and execution
order. It must pass review and CI before use.

The five capture refusals introduced by PR #200 now map to fixed categories in
the existing bounded diagnostic. The historical grouped message remains
`capture-mismatch`; it cannot establish which comparison failed. Unknown text,
including a known message with appended private content, remains `unknown`.

| Exact recorded comparison failure | Public category |
| --- | --- |
| Candidate differs from capture return | `capture-return` |
| Candidate equals the pinned base | `capture-unchanged` |
| Candidate has another repository | `capture-repository` |
| Candidate has path restrictions | `capture-paths` |
| Candidate has another comparison base | `capture-base` |

These are selected journal facts, not claims about every backend action or
filesystem write. They do not alter capture acceptance, attempt accounting,
the task, finite exam, runtime limits or recovery authority. The reader still
copies the fixed evidence set and validates an independent disposable copy;
no writing journal constructor, migration or scheduler runs.

## Installed route, not a staged override

Both helpers are ordinary controller source files. A successor session installs
and verifies the reviewed controller tree containing this revision. After
positive command completion and joined teardown, its separately reviewed
procedure may invoke the installed `maintenance_diagnostic` module once with
the exact run, authorization, retained command report and a fresh evidence
destination. Successful diagnostic completion means selected facts validated,
not application acceptance. An incomplete command, unexpected diagnostics or
uncertain teardown stops; it is not permission to inspect a live writer.

Use the controller's isolated Python entry and verified source tree, never
the old missing-module bootstrap or a replacement helper injected at runtime.
This note deliberately supplies no unpinned host command. The successor
procedure must capture producer and saver statuses separately, require bounded
schema-valid output and empty stderr, preserve every partial artifact, and park
without another dispatch. No extra forensic session is implied.

## Historical bytes remain historical

The frozen [diagnosis procedure](M8-maintenance-diagnosis.md) at
`2ce8338abd5110c6514672243cc6ff06d9286c93` describes different helper bytes:

- Evidence SHA-256: `2f654a218fcb55eee65a59c1c8ae63bc8a761db3fe71143f41dff69e22a1b578`.
- Diagnostic SHA-256: `f0555df16b076b7a5d65d786d9ffd5febb9878b3065e1a2fbc7565d0197a6c69`.

Its commands and pins are unchanged. They are not instructions for installing
today's helper under yesterday's digest. The old reader reported the five new
messages as unknown; the new reader recognizes them explicitly. This is a
prospective diagnostic change, not a reinterpretation of the completed g10
capture or evidence that g10 made no change.

Current source-byte checks (LF required):

```text
CURRENT_EVIDENCE_SHA256=2f654a218fcb55eee65a59c1c8ae63bc8a761db3fe71143f41dff69e22a1b578
CURRENT_DIAGNOSTIC_SHA256=421790bb5f850627f2828179efcc28bbd346134a35ccb5097356b3262f6d39c3
```

The tests separately pin the frozen procedure's historical literals and these
current helper bytes. They do not need Git ancestry in shallow CI. The actual
controller verification, exact session pins and host evidence remain separate
requirements; a local hash comparison does not establish an installation.
