# constructicon

An OS for agentic software-engineering pipelines. One authored graph IR, one
sealed `ExecutionManifest` per run, scoped capability leases, journal-minted
attestations, idempotent effects with receipts — and component versions that
reach dependents only through explicit promotion.

> Authored intent may be ergonomic; executed reality must be explicit.

Almost every execution concept reduces to four nouns: **Definition** (what may
be reused) · **Manifest** (what this run will execute) · **Invocation** (where
one execution occurred) · **Receipt** (what changed outside the run). M6 adds
four control-plane nouns: **Actor** · **Command** · **Run** · **Reference**.

Agents are the first-class user — authoring graphs, operating runs, and
contributing code; humans participate as observer, advisor, and approver.

## Status

Architecture **frozen**; implementation through **M6** is green — the vertical
slice, crash and resume hardening, git authority, generic bounded loops,
agent-first authoring, and a durable authenticated control plane with an
optional MCP v2 adapter:

```text
Describe → propose strict Graph JSON → typed rejection → repair → admit
         → sealed manifest → submit RunId → execute / resume / inspect

Authenticate → Claim → Plan → Apply once → Record → Return
             → lose response → retry → replay
```

Every mutating control operation requires a caller idempotency key. The command
ledger durably binds actor, operation, key, canonical request, immutable plan,
and exact terminal response. A retry after plan loss, post-mutation response
loss, or post-command-commit response loss creates no duplicate run, approval,
promotion, or rollback.

Long-lived work keeps one identity: `RunId`. `RunHost` owns only process-local
worker coroutines and recovery of PENDING or lost RUNNING runs; the walker
remains the only graph scheduler. Server shutdown abandons hosted work without
inventing user cancellation, leaving the durable run resumable.

Counterfactual runs replay the source run's exact component world except for
explicit exact-version overrides. Effects use a separate simulated identity
namespace and adapter-owned `simulate()` methods; live effect adapters are never
called, and mutable capabilities are discard-only. Parent run, overrides,
effect mode, and capability mode are recorded as `RunOrigin`.

SDK authoring remains the same machine in Python:

```python
from typing import Annotated

from pydantic import BaseModel

from constructicon.sdk import flow, port_type, task


class Issue(BaseModel):
    title: str


class Brief(BaseModel):
    title: str


@task("example/triage", output="brief")
async def triage(
    issue: Annotated[Issue, port_type("example/Issue")],
) -> Annotated[Brief, port_type("example/Brief")]:
    return Brief(title=issue.title)


workflow = flow("example/issue-to-brief", triage)
```

`@task`, `flow`, `component`, `harness`, and loop sugar produce only the
canonical `ComponentDef | Ref | Graph | Loop` contracts. `system.describe()`
publishes the strict Graph and admission schemas, stable component contracts,
capability requirements and availability, root grants, magnetic binding and
loop vocabulary, and bounded proposal limits. `system.admit_graph()` returns a
versioned `AdmissionAccepted | AdmissionRejected` result with itemized repair
faults; it never silently ignores fields or auto-repairs a proposal.

The strongest authority claim remains mechanically true and tested: **the only
path from proposed code to a protected git ref is one exact, attested,
idempotent git transaction.** Agent workspaces are staging repositories with
zero authority refs; a moved base is a truthful rejected receipt; forged,
absent, mismatched, failing, or world-mismatched attestations move nothing;
every hard-crash probe — including a real worker dying via `os._exit` mid-merge
— recovers to exactly one install.

Loops add no scheduler and no gate-aware kernel object. Admission seals their
initial bindings, feedback edges, canonical boolean control, exports, and
atomic member order. Every iteration is a distinct `ExecutionPath`, so
checkpoints, effects, and capability leases reuse the existing recovery laws.
False exports the final completed state; all-true exhaustion becomes
`PARKED/policy_exhausted` at graph closure. The acceptance path turns a broken
Git candidate red→repair→green across fresh staging repositories and installs
one exact verified merge.

## MCP control surface

Install the optional adapter:

```bash
uv sync --extra mcp --dev
constructicon-mcp --database .constructicon/constructicon.db
```

- `stdio` receives a fixed actor and scopes from the trusted launching process.
- Streamable HTTP is authenticated or unavailable: it derives the actor from a
  verified OAuth bearer token and publishes no caller-controlled identity field.
- MCP tools delegate once to the transport-neutral `ControlPlane`; they never
  open SQLite, compute a `RunId`, interpret a cursor, or reconcile a command.
- Responses are bounded and pageable. Opaque cursors are actor- and query-bound;
  full immutable records are available through `constructicon://` detail refs.

The full lifecycle runs with zero credentials:

```bash
uv sync --dev
uv run verify        # ruff + mypy --strict + import-linter + pytest
```

## Documentation

- [docs/INVARIANTS.md](docs/INVARIANTS.md) — the thirteen laws and the never list
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — layers, IR, authoring,
  control plane, manifest, effects, registry, journal, milestones, failure tests
- [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) — extension guides (agents first)
- [docs/designs/SELF_IMPROVEMENT.md](docs/designs/SELF_IMPROVEMENT.md) —
  learning as candidates, never mutations
- [docs/adr/](docs/adr/) — why things are the way they are

## License

MIT — see [LICENSE](LICENSE).
