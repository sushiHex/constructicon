# 0024 — Retain observations of native executor dispatch

**Status:** accepted, 2026-11-05. Refs
[#376](https://github.com/sushiHex/constructicon/issues/376).

The owner selected adoption and implementation after independent review.
The [decision record](https://github.com/sushiHex/constructicon/issues/376#issuecomment-6671894961)
adopts the [reviewed proposal](../plans/handoffs/executor-metering-observations-proposal.md)
at `665f678`, SHA-256
`7f4c6d6f052ef76ce6120bdeff6c2f82e4e81d31c27f07fbbe3879679a19bb90`.
The proposal's draft wording is retained as history.

This is the narrow successor required by
[ADR 0018](0018-live-executors-are-leased-contained-processes.md) for a new
durable observation. [ADR 0021](0021-subscription-executors-bind-operator-stores.md)
continues to govern native custody and scope;
[ADR 0016](0016-positive-durable-facts-and-provenance-eras.md) governs
retention. No vendor, credential, host or live model operation is authorized.

The existing event journal retains an intent and at most one outcome per
run, logical acquisition and owner epoch. Trusted assembly binds the
versioned source and fixed configured model to the exact native adapter
revision; the journal checks the current owner, the acquisition, its event,
and the sealed manifest. The intent commits after framing and byte bounds
and before the first native user/task write. Replay cannot permit a send;
the adapter rechecks ownership, control and expiry after commit. A write
failure or lost reply never retries the native send. Intent without outcome
means possibly dispatched and proves no usage.

The adapter settles only observations retained through its existing
correlation and cleanup boundary. A result lost at that boundary may leave
an unavailable outcome or intent alone. Each phase co-commits the ordinary
event seal and a relation seal under the exact event position and independent
acquisition-and-phase selector. The relation binds the acquisition event
and manifest and, for outcomes, the exact prior intent. The generic event
writer cannot mint this family. The same canonical verifier serves point
and scoped inventory reads.

Schema 11 positively seals every existing RunId as unmeasured legacy and
co-commits a current era with later run creation. Resuming a legacy run
does not change its era. No private attempt file, historical output or
transcript is imported. Existing result versions remain exactly decoded.

Result version 3 reports this evidence at the same event cut as status and
capability accounting. Codex cumulative fresh-thread and Claude main-loop
usage are separate groups with known subtotals, including trustworthy
partial counters. Missing axes stay null. Bounded detail exposes the
acquisition and event evidence at that cut. Only supported native adapters
can contribute actual observations; a real dispatch in a counterfactual
run belongs to that run, while fake or simulated producers contribute no
actual observations. Neither estimate nor confirmed charge is known.
