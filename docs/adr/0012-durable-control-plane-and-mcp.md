# 0012 — Durable control plane; MCP as an adapter

**Status:** accepted (M6)

## Decision

M6 introduces a transport-neutral `ControlPlane`. MCP is its first adapter,
not the owner of control semantics.

```text
Authenticated Actor
        ↓
transport adapter (MCP first; CLI later)
        ↓
ControlPlane
        ↓
durable Command → existing Constructicon domain operation → stored response
```

Removing the MCP package leaves actor identity, authorization, command
idempotency, run submission, recovery, pagination, detail references,
approvals, promotion, rollback, and counterfactual execution intact.

## Four control-plane nouns

- **Actor** — a transport-minted identity and scope set. A tool argument can
  never claim the caller's identity.
- **Command** — one durable mutation intent, keyed by actor + operation + caller
  idempotency key and bound to the canonical request hash.
- **Run** — Constructicon's existing long-lived work identity. M6 does not add a
  parallel MCP task state machine.
- **Reference** — a bounded pointer to immutable full detail.

## Command law

Every mutation follows one sequence:

```text
Authorize
→ canonicalize request
→ claim command
→ store immutable plan
→ apply or reconcile one domain mutation
→ store the exact terminal response
→ return
```

A retry of the same actor, operation, idempotency key, and request returns the
stored response. Reusing that key with different arguments is a typed conflict
and performs nothing. A prepared command with an expired owner is reclaimed at
a higher epoch and reconciled from its durable domain fact; it is never blindly
re-executed.

Plans freeze all decisions needed after a crash. A run-start plan contains the
sealed manifest, exact inputs, deterministic `RunId`, and origin. Promotion
contains the exact attestation and attested baseline. Rollback contains the
expected stable pointer and derived target.

## Runs and hosting

MCP operations return the existing `RunId` immediately. `RunHost` owns only
process-local worker coroutines and a run-level concurrency bound; the walker
remains the sole graph scheduler.

Server shutdown **abandons** hosted work rather than recording user
cancellation: owned process trees stop, mutable uncheckpointed acquisitions are
discarded, ownership is released or allowed to expire, and the durable run
remains resumable. Only `runs_cancel` records cancellation intent.

## Counterfactual execution

A counterfactual is a contract-compatible replay of one source manifest:

- every source component scope remains pinned;
- an override names an exact retained version and applies to every occurrence of
  that component name;
- topology-changing or contract-incompatible overrides are refused;
- effects use a separate simulated idempotency namespace and call
  `EffectAdapter.simulate`, never `execute` or `reconcile`;
- every mutable capability acquisition closes with `discard`;
- source run, overrides, effect mode, and capability mode are durable origin
  data.

A simulated receipt is truthful (`status="simulated"`) and can never collide
with a live M1–M5 effect identity.

## Bounded reads

One opaque cursor codec binds continuation state to:

```text
schema version + actor + endpoint kind + query hash + snapshot upper bound
```

A cursor cannot be reused by another actor or with changed filters. Pages are
stable against later inserts. Full immutable records are reached through one
`constructicon://` detail-reference vocabulary and chunked without altering the
stored value.

## MCP boundary

The optional MCP package lives only under `constructicon.api.mcp`. It uses the
high-level MCP Python SDK so Pydantic request and response types remain the wire
contract. Graph proposals remain generic JSON at this boundary and enter
`system.admit_graph`, preserving M5's strict parser and repairable faults.

- `stdio` receives a fixed actor from the trusted launching process.
- Streamable HTTP derives the actor from a verified OAuth access token.
- SSE, embedded authorization servers, MCP Tasks, subscriptions, sampling,
  elicitation, and Apps are outside M6.

A mutating MCP handler derives its actor, delegates once to `ControlPlane`, and
returns the typed result. It never opens SQLite, computes a `RunId`, interprets a
cursor, reconciles a command, or decides authority.
