# M5 rev 3 — implementation record

> **Provenance:** The exact full-length M5 rev 3 planning prose disappeared from
> the conversation view before it was durably archived. The accompanying
> `M5-agent-first-authoring-introspection-recovered-rev2.md` preserves the latest
> recovered implementation-ready plan. This file preserves the exact scope and
> architectural assertions recorded by merged PR #5.

## Summary

M5 rev 3 implemented:

- strict, version-exact Graph JSON with fail-closed unknown fields and reserved
  compiler IDs;
- one typed, bounded `AdmissionFault` / accepted / rejected contract for parsing
  and semantic repair;
- one `admit_graph()` path for JSON, mappings, and canonical Graph objects;
- public execution that re-admits rather than trusting a preview manifest;
- `SystemDescription` derived from one `RegistrySnapshot`, capability catalog,
  live availability, and root grants;
- deduplicated port schemas addressable by exact contract hash;
- nullable declarative capability requirements (`None` = legacy opaque,
  `()` = complete none);
- versioned component authority identity preserving M1–M4 hashes and semantic
  legacy re-registration;
- restart-safe `@task` adapters binding user source and SDK adapter revision;
- exact optional/gathering signature lowering with rejection of hidden
  Python-only semantics;
- `component`, `flow`, `harness`, and loop sugar producing only the canonical
  three-construct IR;
- SDK/direct/proposed Graph manifest-identity equivalence;
- a serialized architect repair path: schema rejection → magnetic ambiguity →
  map repair → execution;
- ADR 0011 and architecture, README, contributor, and agent-guide updates.

## Architectural assertions

```text
one Graph model
one strict parser
one validator
one authoring vocabulary
one schema catalog
one typed diagnostic model
one versioned component authority contract
one reloadable task adapter mechanism
one manifest identity for equivalent intent
zero SDK execution semantics
```

## Verification record

The exact final PR head reported:

```text
Ruff                 clean
mypy --strict        clean across 48 source files
import-linter        3 contracts kept, 0 broken
pytest               180 passed
uv run verify        OK
```

The acceptance lane gave a scripted architect only serialized
`SystemDescription` and serialized rejection results; it repaired strict-schema
and magnetic-ambiguity faults, admitted the canonical Graph, proved identity
against a hand-authored Graph, and executed through the public re-admitting path.

## Source record

- [Merged PR #5](https://github.com/sushiHex/constructicon/pull/5)
- Merge commit: `e8f7f843bdf6c9bc41f962c32cd17b45209dc30d`
