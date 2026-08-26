# ADR 0004 — Component versioning and release channels

**Decision.** Every registration appends an immutable content-hash version and
moves no pointer. Bare refs resolve the `stable` channel (never
latest-registered — with agents as first-class contributors, latest-resolution
would deploy unevaluated registrations to every dependent). Promotion is a
separate attestation-verified pointer move, append-only; rollback is a pointer
move; in-flight runs keep their pinned resolution. A *candidate* is a query
over unpromoted versions, never a channel — many candidates can coexist. M9
adds `canary` via the schema-evolution policy.

**Reproducible means versioned at the component level:** every version is
retained and addressable; a run's journaled resolution is re-executable.
