# ADR 0002 — The sealed ExecutionManifest

**Decision.** Validation produces a first-class immutable manifest — resolved
component versions, explicit typed port bindings, fully concrete grants, and
three identities (input/world/manifest hash). The walker accepts only
manifests. Authored intent may be ergonomic (magnetism, adjacency, inheritance,
selector strings); executed reality is explicit — none of those survive
admission.

**Why.** One object answers: what ran, what connected, what was granted, what
to resume, what to reproduce, what an attestation binds to, what to inspect.
It prevents the walker, journal, API, and reproduction from each inventing a
partial representation of "the resolved run".
