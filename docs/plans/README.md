# Historical planning archive

This directory preserves the planning record that shaped Constructicon. It is a
history of intent, review, and implementation sequencing. It is **not** a second
source of architectural truth.

## Authority order

When records disagree, use this order:

1. **`docs/INVARIANTS.md`** — the laws a change must preserve.
2. **`docs/ARCHITECTURE.md`** — current system truth.
3. **accepted ADRs in `docs/adr/`** — durable decisions and rationale.
4. **code and tests** — executable behavior and failure proofs.
5. **this archive** — historical intent, superseded options, and implementation
   handoffs.

Plans are immutable records. Do not edit an old plan to make it agree with a
later decision. Add a successor document, ADR, or explicit implementation record.

## System-design lineage

| Record | Provenance | Status |
| --- | --- | --- |
| [System Design v6](system-design/system-design-v6.md) | Exact recovered document | Historical; superseded by v12 |
| [System Design v12](system-design/system-design-v12-frozen/) | Exact recovered document, split only at original section boundaries | Frozen planning baseline; M0 resolved here |

## Milestone plans

| Milestone | Record | Provenance | Status |
| --- | --- | --- | --- |
| M1 | [Vertical slice](milestones/M1-vertical-slice-recovered-record.md) | Recovered from the frozen milestone line and merged PR #1 | Historical implementation record; original standalone plan not recovered |
| M2 | [Crash and resume hardening](milestones/M2-crash-resume-hardening.md) | Exact conversation plan | Historical plan; final implementation details are recorded by PR #2 and current architecture |
| M3 | [Git authority rev 1](milestones/M3-git-authority-rev1.md) | Exact recovered document | Historical implementation plan |
| M4 | [Generic bounded loops rev 2](milestones/M4-generic-bounded-loops-rev2.md) | Exact recovered document | Historical implementation plan |
| M5 | [Recovered authoring and introspection rev 2](milestones/M5-agent-first-authoring-introspection-recovered-rev2.md) | High-confidence reconstruction, explicitly labeled in the document | Latest recovered full plan; exact lost prose was not recoverable |
| M5 | [Rev 3 implementation record](milestones/M5-rev3-implementation-record.md) | Merged PR #5 scope and acceptance record | Complements the recovered plan; not a reconstruction of missing prose |
| M6 | [Durable control plane rev 1](milestones/M6-durable-control-plane-rev1.md) | Exact recovered document | Superseded by rev 2 |
| M6 | [Durable control plane rev 2](milestones/M6-durable-control-plane-rev2-polished.md) | Exact polished document | Implementation baseline for M6 |
| M6.1 | [Control-plane hardening and compression](milestones/M6.1-control-plane-hardening-and-compression.md) | Exact recovered document | Corrective plan; includes PR A hardening and PR B compression |
| M6.2 | [Internal compression scope](milestones/M6.2-internal-compression-extracted-scope.md) | Exact extraction from the M6.1 parent plan | Discoverability copy; parent plan remains authoritative for this historical scope |

## Handoffs

| Record | Purpose |
| --- | --- |
| [M6.1 / M6.2 implementation handoff](handoffs/M6.1-M6.2-implementation-handoff.md) | Preserves an earlier artifact-based implementation handoff and its exact base/checksum assumptions; historical only |

## Completeness and recovery notes

- **M0** is not a separate file because System Design v12 explicitly resolves the
  semantic milestone.
- **M1** has no recovered standalone plan. The archive says so rather than
  inventing one.
- **M5 rev 3** disappeared from the visible conversation before archival. The
  recovered rev 2 document and merged PR #5 implementation record preserve the
  recoverable substance without pretending the lost wording is exact.
- **M6.2** was planned as PR B inside M6.1, not as an independent milestone
  document. The extracted scope exists only to make that plan easy to find.
- PR descriptions remain useful implementation summaries, but the documents here
  preserve the deeper planning record beside the code they governed.

## Integrity

[`MANIFEST.sha256`](MANIFEST.sha256) records the SHA-256 digest of every archived
Markdown document, including every System Design v12 source part. A historical
plan should change only through an explicit correction that also updates the
manifest and explains why preservation required it.
