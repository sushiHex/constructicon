# Maintenance rehearsal launcher and result packet

Refs [#391](https://github.com/sushiHex/constructicon/issues/391).

## Outcome and boundary

An operator can run one credential-free maintenance contribution from a
checkout outside pytest (`python -m tests.e2e.maintenance_rehearsal run`), then
read one bounded packet for that run in a fresh process
(`python -m constructicon.api.maintenance_report`, wrapped by the rehearsal's
`report`). The walkthrough is in
[CONTRIBUTING](../../CONTRIBUTING.md#run-it-outside-pytest-and-read-the-packet).

The rehearsal is test-side and reuses the existing credential-free witness:
`tests/maintenance_task_world.py`, the `concrete_application` committed-tree
world and the `portable_binding` store, rebuilt programmatically through
factored helpers that the fixtures now call. The native peer and operator store
are fake, and a portable launcher substitutes isolation. This is not physical
containment, a vendor observation or a live attempt. The base is the committed
tree with `tests/vectors/plan_manifest.json` stripped. Current main contains
that file and `prepare_source` refuses it, so the base is synthetic and its
acceptance is not a current-main contribution.

The shipped report composes existing readers: byte capture, the read-only
diagnostic, `inspect_result`, and (on its own disposable copy only) the journal
reads behind the schema-3 run result's metering and capability accounting,
lease rows, and the checker's attestation. The target ref is one fixed
hook-free, non-fetching Git read. It adds no result format, accounting,
scheduler or provider. The maintenance application revision is unchanged: no
file in its identity closure, the diagnostic, the evidence capture or the
mutation anchors was edited.

## Labels and limits

The outcome classifies observations and never claims application acceptance.
That verdict is `derive_maintenance_result`'s whole proof (exact request,
candidate and subject, sole base parent, history, file delta and digests), and
the report re-derives none of it. `maintenance-result.json` is a sidecar the
diagnostic only shape- and RunId-checks. The strongest outcome,
`succeeded-with-acceptance-record`, means a succeeded run, this run's own
positive attestation and an acceptance record were observed; the record's
candidate is not re-checked against the journal. A stored record the journal
does not support is `contradictory-evidence`. The packet is one
LF-terminated record of at most 8192 bytes including that newline, emitted as a
single binary write so Windows text-mode translation cannot exceed the bound.
Integration review (root lane) found these gaps in earlier heads; focused
tests now bind each, including the real CLI's raw bytes at and one byte over the
cap.

Leases are journal-recorded states, not physical quiescence. A target observed
at the base is a current read, not proof that cleanup ran. Metering coverage is
the projection's own, with estimate and charge unknown. A no-op names the
diagnostic's producer-mapped writer cause (`capture-unchanged`).

The report reads only the current journal schema (11). A store from the
installed C490 controller (schema 10) is refused as `unsupported-schema` and
never migrated or opened. Backward-compatible reading is out of scope. The
shipped command refuses at `capture` on Windows because evidence custody is
POSIX-only. The rehearsal substitutes the same Windows predicates as the journal
tests. On Windows a long state path makes the full-tree checkout fail at staging
(`contained staging initialization failed`), so use a short one.

## Evidence

Fresh-process tests cover the contribution and no-op packets; a same-key replay
with zero native `turn/start` calls and an unchanged attempt record; and real
process death through the journal's existing `completion.after_commit` fault
probe once the writer checkpoint is committed. The same-key resume then
succeeds with no writer dispatch, and the packet taken after the death reports
the dead process's leases as not closed. Every file under the root, including
the authority's refs and hooks, is byte-identical before and after each report.
Refusal tests cover a missing store, a schema-10 store (the journal constructor
is forbidden), hostile path-bearing command reports, bad arguments and
unsubstituted custody. A store holding long, path-bearing failure and attempt
text still yields a bounded packet free of those markers.
