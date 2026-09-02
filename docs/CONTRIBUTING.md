# Contributing

The expected contributor is an agent (I9). One command verifies everything CI
checks:

```bash
uv run verify        # ruff + mypy --strict + import-linter + pytest
```

Green locally is the goal `verify` serves; CI runs the same command. The full
lifecycle runs with zero credentials (I7) — if your change needs a secret to be
tested, the design is wrong.

Before writing anything new, inspect `system.describe()` and check for an
existing component or contract to compose or extend. Use
`describe_component(name)` for one stable contract and `rdeps(name)` before
changing a shared definition. Compose before you drop a tier (I10).

## Authoring components and graphs (L3/L4)

- Use `@task("namespace/name")` for a new atomic operation. Every data
  parameter and return value needs a concrete annotation; use
  `Annotated[T, port_type("namespace/Type")]` when the Python class name is not
  the intended public nominal identity.
- `T | None` is an optional input. `list[T]` is a gathering input whose Graph
  contract remains `T`; an output `list[T]` is one list payload. Defaults,
  `Any`, variadic parameters, positional-only parameters, and `list[T] | None`
  are rejected because they would add Python-only semantics the Graph cannot
  see.
- Declare atomic capability aliases with `CapabilityRequirement(alias, kind)`.
  Bind an assembled capability id explicitly on the `Ref`; combinators never
  choose one by kind.
- Use `component`, `flow`, `harness`, `loop`, and `panel` only as sugar. The
  produced definition must contain the same `Ref | Graph | Loop` you would
  hand-author. Add an equality test against the direct Graph for new
  combinator behavior. A composite's declared ports are its Graph's; neither
  `component()` nor the registry nor admission accepts a boundary the Graph
  does not export, and boundaries are compared as bytes
  (`core.ports.same_boundary`), never with `==`.
- `panel()` takes definition bundles, never bare names, because it proves the
  gather exact from declared contracts. A panel member declares one input and
  one output typed by the panel contracts in `core/panel.py`, both of
  cardinality one, and the two differ; an aggregator is atomic — its law
  reads its own seat, so compose around the panel, not inside its aggregator —
  and declares exactly one `many` input of the members' result contract and
  no other input of it. A human member is
  `human_panel_member(name, channel_id)` — the standard advisor and ballot
  composed, registered and promoted like any composite — with one channel id
  per participant, and the request payload you write is what tells the
  participant to answer with a `PanelBallotPayload`, whose shape
  `system.describe()` publishes. Report `unavailable` and `timed_out` as
  member data; the kernel infers nothing from elapsed time.
- A named contract revision (`ChannelContract` with a hand-named
  `schema_hash`) cannot embed its JSON Schema on a port. Add the contract and
  its shape to the module's `CONTRACT_SCHEMAS` so `describe()` publishes it,
  and bump the revision when the shape changes. A pure standard component
  that delegates its behaviour to an L0 law stamps that law's revision into
  its implementation identity (`sdk/std.py`, `_under_law`); the panel law's
  revision is derived from its own source, so nothing has to be bumped.
- Architect JSON enters through `system.admit_graph()`. It is strict and bounded;
  rejection is a versioned `AdmissionRejected` with itemized repair data. Never
  add automatic repair or a trusted-SDK bypass. Public execution calls
  `ControlPlane.runs_start(actor, proposal=graph, inputs=..., idempotency_key=...)`,
  which admits again while creating the durable command and run.

## Adding a control operation (L0/L4)

A mutating control operation belongs in the transport-neutral `ControlPlane`,
not inside MCP or a future CLI.

1. Define or reuse a typed response in `core/control.py`.
2. Require the exact actor scope before command claiming.
3. Canonicalize the request and require a bounded caller idempotency key.
4. Claim the command through `ControlStore`.
5. Store every decision needed after a crash in the immutable command plan.
6. Apply or reconcile exactly one durable domain mutation.
7. Complete or reject the command with the exact response that retries replay.

Every new mutation needs fault-injection coverage at all three seams:

```text
after plan commit, before domain mutation
after domain mutation, before command completion
after command completion, before response delivery
```

Retrying the same actor, operation, key, and request must create exactly one
domain fact. Reusing the key with different arguments must be a typed conflict
and perform nothing.

A rejection is evidence too. If it is decided before the domain plan, retain
the complete typed response in a rejection plan. If a post-plan race may still
refuse, its complete response must derive only from that immutable plan and
independently retained domain facts; a code whitelist or mutable current state
is not replay proof. Once a co-located domain fact names the command, the store
must not let that command become rejected.

If one mutation must commit control and channel facts together, its injection
root requires `ControlPlaneStore`: the exact store already assembled as the
system journal. Do not compose separate `ControlStore` and `Channel` calls or
accept a second handle to the same database; neither proves one transaction or
one live world.

Registration and first promotion are local control operations, not setup
bypasses. Assemble an empty `Constructicon` and `ControlPlane`, call
`startup()`, then use `registry_register` and `registry_promote_initial` with a
launcher-minted static admin actor and caller keys. Definitions must carry a
restart-importable `PythonRef`; process-local implementation caches are never
recovery authority. These two methods must not be exposed by transports. Finish
with `shutdown()`.

Keep `api/control.py` as the small public facade. Command claiming, plans,
reconciliation, and terminal responses belong in `_control_commands.py`;
authorized pages and cursor continuations belong in `_control_queries.py`;
immutable detail parsing/chunking stays in `detail.py`.

`RunHost` is not a scheduler. It owns only process-local run worker coroutines,
a concurrency ceiling, PENDING/lost-RUNNING recovery, and abandon-on-shutdown.
The walker remains the only scheduler of graph units.

## Adding an MCP tool or resource (L4 only)

The optional MCP package lives under `constructicon.api.mcp`; no other module may
import `mcp`.

The installed `pyproject.toml` metadata owns the package version.
`constructicon.__version__` derives from it and the MCP server imports that
value. The base wheel must import without MCP; the CLI alone gives concise
`constructicon[mcp]` guidance when the top-level optional dependency is absent.

- The handler derives `AuthenticatedActor` from its `ActorSource`, delegates
  once to `ControlPlane`, and returns the typed result.
- Do not open SQLite, compute identities, interpret cursors, select registry
  versions, or implement recovery in the handler.
- Do not accept actor identity in arguments. Stdio receives a trusted static
  actor; HTTP receives an actor derived from a verified OAuth access token.
- Keep malformed Graph proposals as generic JSON until they enter
  `system.admit_graph()`, preserving M5's strict parser and repairable faults.
- Return bounded summaries and `DetailRef`s. Full immutable records remain in the
  authoritative stores and are read through `constructicon://` references.
- Use the official MCP in-memory client in credential-free tests. Add a fake
  token-verifier lane for HTTP identity or scope behavior.

Tool annotations are client hints, never authorization. Actual authority is the
actor scope plus existing Constructicon admission/effect rules.

## Counterfactual execution

Counterfactual replay is deliberately narrower than general graph migration:

- the source topology and every non-overridden scope remain exact;
- overrides name exact retained component versions and must preserve the source
  contract at every affected scope;
- live effect identities remain unchanged, while simulated effects use their own
  namespace and `EffectAdapter.simulate()`;
- a counterfactual boundary must never call `execute()` or `reconcile()` on an
  external effect adapter;
- mutable capability acquisitions close with `discard`, even after successful
  invocation;
- source run, override set, effect mode, and capability mode are recorded in
  `RunOrigin`.

An adapter that cannot simulate truthfully declares simulation unsupported and
causes admission/control refusal before external I/O.

## Adding an executor (L1)

1. Implement the `constructicon.core.executor.Executor` protocol: `profile`
   (including an honest `IsolationProfile` — admission rejects postures the
   executor cannot mechanically enforce; never overstate), `validate_grants`,
   and `execute` returning a discriminated `ExecutorOutcome`.
2. Truthful telemetry is law (I4): fields the backend does not emit stay
   `None`; damaged streams return `ExecutorPartial`; timeouts salvage partial
   output into `ExecutorFailure`.
3. Tests: recorded transcripts, argv capture, damaged-stream demotion — no
   live calls in CI. Copy `substrate/executors/fake.py` as the shape.

## Adding a gate / check producer (L1)

Implement `CheckResult` production over a workspace; the runner mints the
`Attestation`. A red check is data, not an error.

## Adding an effect adapter (L1)

Implement `constructicon.core.effect.EffectAdapter`:

- declare `native_idempotency` or `reconcilable` recovery; an effect that is
  neither is not admittable;
- honor the computed live idempotency key and implement `reconcile()`;
- declare whether simulation is supported and, when supported, implement
  `simulate()` without external mutation;
- treat the request returned by durable preparation as canonical. If another
  contender prepared the same derived identity first, reconcile or execute its
  stored request rather than the caller's losing value;
- never make an adapter that blindly re-executes an unknown external outcome;
- never return `committed` for simulation — use the truthful `simulated` status.

## Adding a channel transport (L1, M7)

Implement the L0 `Channel` protocol in `substrate/channels/` and add it to the
shared contract suite in `tests/substrate/channels/`; a transport with no second
consumer of that suite is not admittable (I6).

The built-in capability kinds are reserved: `channel.mailbox` must report
`durability="sqlite_wal"`, while `channel.in_process` must report
`durability="process"`. A `sqlite_wal` transport implements
`JournalBackedChannel`, and assembly proves its journal is the exact system
journal. New transports use a new kind and an honest profile; do not make a
compatible-looking second handle stand in for one assembled world.

- carry typed envelopes only (I5), and derive every identity — never accept a
  caller-authored message id, reply id, sequence number, or routing field;
- build messages with `message_for_intent` and `message_for_reply` rather than
  constructing `ChannelMessage` directly, so the two transports cannot drift;
- stamp `Envelope.created_at` exactly once, when the message is first appended,
  and reconcile a repeated intent against that stored time instead of inventing
  a new one;
- treat an equal logical intent under one derived id as idempotent and a
  different one as `JournalDamaged`; a second, different reply to one request is
  a `ChannelReplyConflict` — a lost race, not corruption;
- retain reply payload evidence independently of the message. A durable current
  reply is projected through the immutable command plan that authored it; an
  in-process transport keeps a deep first-write proof so the shared contract
  exercises the same damage boundary;
- retain history: never delete, dequeue, or hide a message, and never let an
  acknowledgement claim that a component consumed a payload (I4);
- page at one `ChannelRevision` cut ordered by durable sequence, reject a zero,
  negative, or oversized bound, and refuse a future or incoherent revision;
- publish a `ChannelProfile` whose `durability` is the truth about this
  transport — a process-local history says `process` and loses state honestly.

## Adding a component that waits on a channel (L2/L3, M7)

An atomic component that requires a channel capability must declare **exactly
one input and one output**. Admission compiles that pair into the manifest as
the exchange the binding may carry, so the component never names a port and
nothing about the message is chosen at call time. A component needing more ports
composes around a one-exchange component (I10); admission rejects the alternative
with an itemized fault rather than guessing which pair is the exchange.

- the whole round trip is `await ctx.channel(alias).ask(payload)`; the payload is
  the only thing the component supplies;
- `ask` raises `InvocationParked` when no reply is stored yet. Let it propagate:
  waiting is not failing, and the walker records the parking facts. Never catch
  it to return a placeholder output;
- return the reply as the declared output port. A reply cannot arrive into an
  input, because a non-optional input must already be bound before the
  invocation starts — on wake the component reruns and reads the stored reply;
- assembly, not the graph, decides routing. Give each participant its own
  capability id whose descriptor carries the `ChannelEndpoint`; changing one is a
  manifest identity change and activation refuses a mismatched live endpoint.

## Changing SQLite persistence (L1)

`SqliteJournal` is one schema-7 WAL store assembled from private responsibility
modules: `_sqlite_base`, `_sqlite_schema`, `_sqlite_execution`,
`_sqlite_execution_facts`, `_sqlite_runs`, `_sqlite_effects`, `_sqlite_leases`,
`_sqlite_attestations`, `_sqlite_registry`, `_sqlite_actors`, `_sqlite_control`,
`_sqlite_commands`, `_sqlite_approvals`, `_sqlite_channels`,
`_sqlite_fact_seals`, and `_sqlite_queries`. A Python module
move is not a data migration. Preserve SQL shape, transaction boundaries,
write-once equality, epoch fences, fault-probe positions, canonical bytes, and
all source-schema fixtures.

Every new immutable fact or cross-row relationship family needs one
owner-defined exact hash, primary key, secondary selector where one exists,
absence check, canonical point projector, bidirectional inventory, and positive
seal written in the fact's transaction. A current open
validates only: it must never create evidence, repair a row, classify an era, or
reseal observed bytes.
Compatibility belongs solely to a versioned migration and must name a real
fixture-proven writer era. Read and batch paths use the same sealed canonical
projection as retries; a faster query is not a weaker evidence boundary. See
[ADR 0016](adr/0016-positive-durable-facts-and-provenance-eras.md).

Schema 7 adds `durable_fact_seals`; `runs.creation_command_id`;
`effects.outcome_run_id` and `effects.outcome_event_seq`;
`channel_messages.command_id` and
`channel_messages.reply_provenance_version`;
`channel_acks.ack_provenance_version`;
`channel_provenance.legacy_message_through` and
`channel_provenance.legacy_ack_through`; the partial unique index
`channel_reply_command_unique`; and `legacy_effect_seals` and
`legacy_capability_lease_seals`. The same seal table owns the migration-only
`resume_plan_pre_v7` family and the current `resume_attempt` relationship
family. Preserve them as one law. Two NULL reply
fields at or below the message cutoff and a version-0
acknowledgement at or below the ack cutoff mean true schema-6 history; a current
reply carries its writer and version 1, and a current acknowledgement is
version 1 above its cutoff with an extant writer. A version-0 acknowledgement's
command id remains an opaque historical scalar: never resolve it into a later
same-named command. A retained schema-6 approval may recover its exact
`ChannelApprovalPlan` through the approval row; an advice reply cannot, and
opaque history never gains a current plan.

The 6→7 migration first records the `channel_provenance` cutoffs, stamps
retained acknowledgements with era 0, populates the run-creation markers, and
seals legacy terminal effect outcomes. It then seals facts in this topological
order: commands → pre-v7 resume-plan evidence → manifests → run worlds →
attestations → approvals → component registrations/promotions → effect
preparations → events → opaque effect-outcome classifications → resume-attempt
relationships → checkpoints → channel provenance → messages → acknowledgements.
Legacy lease lifecycle seals follow the event seals too. Name migration tests by
schema endpoints, not the milestone that introduced them.

Decode durable JSON through the shared strict boundary. Duplicate keys,
non-finite numbers, invalid Unicode scalars, model normalization, malformed
digests, noncanonical aware timestamps, non-integer sequences, and non-0/1
SQLite booleans are damage, not compatibility. If compatibility is real, name
the exact historical writer shape and test a database produced by it; never
broaden a decoder around a hypothetical row.

The admitted historical shapes are equally exact. M1/M2 effect requests omit
`run_id`, `manifest_hash`, and `mode`; M3–M5 requests carry `run_id` and
`manifest_hash` but omit `mode`; current requests carry all three, and a
retained terminal receipt keeps the hash of its own request era. A keyless
pre-v7 outcome event requires its migration-only
`legacy_effect_outcome_pre_v7` seal; current writers never mint that family and
must carry the exact effect key. Schema-5/6 actors may retain one unique
unsorted array of known scopes, and pre-sort component definitions may retain
the unique array order of `labels`, `change_surfaces`, and
`capability_requirements`. These rules reconstruct a typed view without
rewriting stored bytes or admitting any other normalization.

Current SQLite and in-memory command stores accept only an exact-v1 typed
resume plan. The 6→7 migration alone may classify a genuine raw or weak typed
schema-6 plan under `resume_plan_pre_v7`, with its observed `prepared` or
`terminal` phase explicit; current plans never enter that family. An event that
carries `resume_command_id` atomically co-seals a `resume_attempt` relationship
binding its command claim, plan, baseline, and event. An unfenced historical
plan cannot own that receipt. Point, batch, retry, and recovery paths all use
the same relationship projector.

## Kernel changes (L0/L2)

Require an invariant review against `docs/INVARIANTS.md` and, for anything the
plan calls frozen, an ADR in `docs/adr/`. The import-linter layer contract and
the kernel dependency budget (stdlib + Pydantic) are CI law.
