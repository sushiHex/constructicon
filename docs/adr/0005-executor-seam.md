# ADR 0005 — The executor seam is task-shaped

**Decision.** All models — subscription CLIs (Claude Code, Codex) and
API-backed harnesses (Pi) — fit one task-shaped contract and are
interchangeable as plugs *where their declared capability profile satisfies
the node contract*. No completion-level provider abstraction is ever built:
subscription CLIs are already harnesses; API models enter through an existing
harness; gates and orchestration only consume task-level results.

**Vendoring provenance.** Adapter and mailbox patterns are vendored (ideas
reimplemented async-native, no pip dependency) from sushiHex/hardline-mcp
@6d1187a and disler/fusion-harness @01a3482, both MIT. Their measured lessons
are law here: truthful telemetry (unemitted fields stay None), partial-output
salvage, damaged-stream demotion, bounded responses, kill-tree cancellation.
