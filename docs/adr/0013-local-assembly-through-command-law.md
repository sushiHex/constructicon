# 0013 — Local assembly uses the durable command boundary

**Status:** accepted (M6.2)

## Decision

Component registration and the first stable promotion are mutations. Trusted
local assembly therefore performs them through the same durable `ControlPlane`
command law as remote operations:

```text
launcher-minted static admin actor
→ registry_register(actor, definition, idempotency_key)
→ registry_promote_initial(actor, component, version, idempotency_key)
```

Both authorize before implicit startup or command claim. A non-static actor is
rejected even if it carries admin scope; a static actor without admin scope is
rejected for the missing scope. Their plans bind the exact canonical definition,
content hash, registration timestamp/origin, initial baseline, policy draft,
attestation identity, and promotion receipt needed for crash recovery.

These methods are public Python launcher operations but are absent from MCP and
future remote transports. `Constructicon` keeps only private direct domain verbs
for `_CommandExecutor` and `RunHost`; it exposes no mutable journal or registry
handle and no unauthenticated registration, bootstrap, or execution wrapper.

## Consequences

- Startup, fixtures, and launchers cannot treat trusted locality as an
  idempotency bypass.
- Registration writes or reconciles only the immutable version row. An in-memory
  implementation cache is never durable authority; persisted atomics must bind
  from their restart-importable `PythonRef` in a fresh process.
- Initial promotion first mints or reloads its exact deterministic policy
  attestation, then appends or reloads one exact promotion receipt. Response
  loss between those facts is recoverable.
- Historical databases created through the former direct bootstrap path remain
  valid. The keyed command reconciles identical existing rows and receipts
  without rewriting them.

## Rejected alternatives

- A second local-only mutation facade would create two command laws.
- Exposing these commands through MCP would give a remote transport authority
  intended only for trusted process assembly.
- Persisting implementation closures or relying on `_impls` would make recovery
  process-local and contradict restart-safe component identity.
