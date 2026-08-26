# ADR 0007 — One transactional log, many projections

**Decision.** SQLite (stdlib, WAL) is authoritative for runs, events,
checkpoints, attestations, and effect records; a node completion commits
checkpoint + event in one transaction. JSONL, summaries, and human renderings
are regenerable projections. Durable mailbox sends (M7) commit through the
same transaction or the effect boundary — never a second independent store.

**Rejected.** OpenTelemetry as the store (telemetry has no read-back — an
exporter maps events to OTel GenAI spans instead); LangGraph's checkpoint
format (framework-internal, object-serializer-based — its *model* is adopted,
checkpoints per step with per-run pinning, in plain JSON columns);
Temporal-style replay-from-history (requires deterministic orchestration code;
wrap Temporal if constructicon ever outgrows one machine).
