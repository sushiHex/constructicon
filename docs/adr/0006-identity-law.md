# ADR 0006 — One identity law; scope vs invocation

**Decision.** Every hash is `digest(domain, schema_version, payload)` —
domain-separated SHA-256 over canonical JSON; digest fields never participate
in their own payloads; idempotency keys are computed, never caller-authored.

Static `ScopePath` (manifest-time location; iterations do not exist yet) is
distinct from dynamic `ExecutionPath` (scope + iteration frames);
`invocation_id(run_id, path)` is the one identity used by envelopes,
checkpoints, events, receipts, channels, cancellation, and API references.
Port addresses carry their scope so nested duplicate node ids stay distinct.
