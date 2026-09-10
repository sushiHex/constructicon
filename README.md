# Constructicon

[![verify](https://github.com/sushiHex/constructicon/actions/workflows/verify.yml/badge.svg)](https://github.com/sushiHex/constructicon/actions/workflows/verify.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Assemble the plan. Seal the run. Prove what ships.**

Constructicon is an execution and governance layer for agentic software
engineering: sealed workflows, durable human collaboration, and proof-carrying
Git changes.

Agents propose work and compose its structure. Constructicon validates that
proposal, pins what will execute, scopes its capabilities, and records the
evidence for external changes. Humans observe, advise, and approve through the
same typed control plane.

> Authored intent may be ergonomic. Executed reality must be explicit.

**Developer preview.** M1 through M7.1 are complete. M8 has landed executor
contracts and a networkless Linux containment foundation; live Claude Code,
Codex, and Pi adapters are not available yet. See [current status](#what-is-implemented).

## Why Constructicon exists

An agent's proposal, a successful check, a human approval, and an installed
change are different facts. Constructicon keeps the relationships between
them explicit and recoverable:

**What exact plan ran, against which component world, what evidence passed, what
changed, and can the answer survive a crash or retry?**

The model may change. The execution, recovery, and authority laws do not move
into the model or its provider.

### The central promise

**Within Constructicon's Git authority, proposed code reaches a protected ref
through one exact, attested, idempotent Git transaction.**

Gates run against the prepared merge commit into the current base.
`merge_verified` installs that exact commit. A moved base, missing evidence,
forged result, mismatched subject, or failed check moves nothing.

## How it works

```text
Agent, MCP client, or Python SDK
                |
                v
        strict Ref | Graph | Loop
                |
                v
     admission and typed rejection
                |
                v
       sealed ExecutionManifest
                |
                v
 capability-scoped, journaled execution
                |
                v
 CheckResult -> Attestation -> EffectReceipt
                |
                v
       exact verified Git transaction
```

Agents may author the work and its structure. They do not get to decide that
their own work is safe, mint their own proof, or grant themselves more
authority.

### Core guarantees

- **Intent compiles. Execution is sealed.** Admission resolves references,
  bindings, versions, loops, and grants into one immutable manifest. The walker
  executes only that manifest.
- **Authority is physical.** LLMs propose. Deterministic code validates,
  executes, reconciles, and disposes.
- **Effects carry proof.** Irreversible actions require a journal-minted
  attestation for the exact subject and sealed world.
- **Crashes are normal.** Completed invocations resume from checkpoints.
  Unknown external outcomes are reconciled before anything is repeated.
- **Versions do not drift.** Definitions are immutable, runs pin one
  `world_hash`, and new versions affect future runs only through promotion.
- **Learning produces candidates, never mutations.** A component cannot rewrite
  itself, promote itself, or define its own exam.

### Humans are participants, not side channels

Journal-backed mailboxes carry typed requests, replies, and acknowledgements.
A run can park while waiting for advice or approval, release its invocation
resources, and wake from the durable reply after a process restart. Advice and
approval have separate authority; a human decision does not replace evidence
from deterministic checks.

`panel()` composes ordinary graph nodes with explicit membership and mapped
fan-in. The standard quorum aggregator evaluates typed member results under
an explicit policy. Human members use the same channel contracts; there is no
panel-specific scheduler. See [channels and panels](docs/ARCHITECTURE.md#channels).

### One executor seam, multiple kinds of backend

Claude Code, Codex, and Pi are the initial integration targets, not a closed
provider list. Future cloud APIs and local models can enter through compatible
task harnesses implementing the existing `Executor` / `ExecutorProvider`
contracts. Provider configuration, authentication, and native stream decoding
belong in the adapter; the graph language and walker do not grow provider
switches. An adapter is interchangeable only where it can enforce the admitted
capabilities.

Subscription reuse for solo developers is an explicit goal, **not a working
integration today**. The accepted initial authentication boundary remains
gateway-only. The [native-authentication investigation](docs/plans/handoffs/M8-native-auth-feasibility.md)
identifies possible interfaces and the missing isolation proof; it does not
authorize copying desktop credentials or silently substituting API billing.
See [adding an executor](docs/CONTRIBUTING.md#adding-an-executor-l1).

## Quick start

Constructicon currently targets Python 3.11 or newer and uses
[`uv`](https://docs.astral.sh/uv/) for development.

```bash
git clone https://github.com/sushiHex/constructicon.git
cd constructicon
uv sync --dev
uv run verify
```

`verify` runs the same credential-free gate as CI: Ruff, strict mypy,
import-linter, and pytest.

The separate [Linux containment lane](docs/M8_CI.md#pr-b-the-separate-containment-gate)
provisions its physical test boundary on GitHub Actions. Platform skips in a
local run are not containment evidence.

### Run a small workflow

This example executes a deterministic Python task. It needs no model login,
executor service, or protected Git repository.

Definitions must be importable after restart. Create `demo_component.py` in the
repository root:

```python
from typing import Annotated

from pydantic import BaseModel

from constructicon.sdk import port_type, task


class Issue(BaseModel):
    title: str


class Brief(BaseModel):
    title: str


@task("demo/triage", output="brief")
async def triage(
    issue: Annotated[Issue, port_type("demo/Issue")],
) -> Annotated[Brief, port_type("demo/Brief")]:
    return Brief(title=issue.title)
```

Then create `demo.py`:

```python
import asyncio
from pathlib import Path

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.control import (
    ADMIN_SCOPE,
    OPERATE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    PromotionCommandResult,
    RegistrationCommandResult,
    RunResultPreview,
    RunSubmission,
)
from constructicon.core.run import RunStatus
from constructicon.sdk import flow
from constructicon.substrate.journal.sqlite import SqliteJournal
from demo_component import triage


async def main() -> None:
    state_dir = Path(".constructicon")
    state_dir.mkdir(exist_ok=True)

    journal = SqliteJournal(state_dir / "demo.db")
    system = Constructicon(journal=journal)
    control = ControlPlane(system=system, store=journal)
    launcher = AuthenticatedActor(
        actor_id="static:demo-launcher",
        auth_method="static",
        scopes=frozenset({READ_SCOPE, OPERATE_SCOPE, ADMIN_SCOPE}),
    )
    await control.startup()
    try:
        registered = await control.registry_register(
            launcher,
            definition=triage,
            idempotency_key="demo-register-triage-v1",
        )
        assert isinstance(registered, RegistrationCommandResult)
        promoted = await control.registry_promote_initial(
            launcher,
            component=registered.component,
            version=registered.version,
            idempotency_key="demo-promote-triage-v1",
        )
        assert isinstance(promoted, PromotionCommandResult)

        workflow = flow("demo/issue-to-brief", triage)
        submitted = await control.runs_start(
            launcher,
            proposal=workflow.definition.body,
            inputs={"issue": {"title": "Fix the flaky retry"}},
            idempotency_key="demo-run-1",
        )
        assert isinstance(submitted, RunSubmission)
        async with asyncio.timeout(30):
            while True:
                result = control.runs_result(launcher, submitted.run_id)
                assert isinstance(result, RunResultPreview)
                if result.status not in (RunStatus.PENDING, RunStatus.RUNNING):
                    break
                await asyncio.sleep(0.05)
        assert result.status is RunStatus.SUCCEEDED, result.model_dump_json()
        print(result.status.value, result.outputs)
    finally:
        await control.shutdown()


asyncio.run(main())
```

Run it:

```bash
uv run python demo.py
```

Expected output:

```text
succeeded {'brief': {'title': 'Fix the flaky retry'}}
```

Run the unchanged example again to replay the same command keys and read the
same completed run. If you change a command's arguments, give that operation
a new idempotency key; reusing a key with a different request is a refusal.

`@task`, `flow`, `component`, `harness`, `loop`, and `panel` are authoring sugar only.
They immediately lower to the same canonical `Ref | Graph | Loop` contracts
used by strict agent-authored JSON. There is no privileged SDK workflow model
and no trusted bypass around admission.

## Agent control through MCP

Install the optional MCP adapter and start a local stdio control plane:

```bash
uv sync --extra mcp --dev
uv run constructicon-mcp \
  --database .constructicon/constructicon.db
```

The MCP adapter is a thin transport over the same typed `ControlPlane`.
Mutating operations require caller idempotency keys, bounded responses use
revision-pinned pagination, and full immutable records remain available by
reference. Local registration and initial promotion are intentionally Python
launcher operations, not MCP tools.

The CLI does not provision executor or channel capabilities. Assemble those in
a Python launcher; persisted definitions do not substitute for live capability
bindings. The same MCP surface exposes human inboxes, replies, acknowledgements,
and request-bound approvals under the actor's scopes.

For HTTP, Constructicon is authenticated or unavailable. Actor identity comes
from a verified OAuth bearer token, never from a caller-controlled tool
argument.

## What is implemented

Constructicon `0.1.0` is a developer preview, not a hosted coding-agent service.
The execution and authority laws are governed by the
[invariants](docs/INVARIANTS.md) and accepted [ADRs](docs/adr/README.md).
Milestones M1 through M7.1 are complete:

| Milestone | Capability |
| --- | --- |
| M1 | Sealed manifests, checkpoint resume, and idempotent effects |
| M2 | Persistent registry, crash hardening, cancellation, liveness, and projections |
| M3 | Protected Git authority, real gates, attestations, and exact verified merge |
| M4 | Generic bounded repair loops without a second scheduler |
| M5 | Agent-first JSON authoring, SDK sugar, introspection, and repairable admission |
| M6 | Durable authenticated command law, race-safe hosting, revision-pinned reads, MCP v2 adapter, and counterfactual replay |
| M7 | Durable channels, human advice and approval, restart-safe waiting, and deterministic panels |
| M7.1 | Explicit panel membership, ordered mapped fan-in, exact endpoint diagnostics, and strengthened counterfactual admission |

**M8 is in progress.** Merged work includes complete executor grant policy,
content-bound launch identity, record-before-materialization leases, a
networkless Linux launcher, owned READ/WRITE workspaces, and process cleanup
that survives controller death. Failure of the trusted reaper itself is outside
that recovery guarantee. The physical boundary is tested on GitHub Actions with
hostile fixtures, not live model calls.

Still outstanding: safe asynchronous WRITE capture, contained gate execution,
provider-route conformance, and the live adapters. A networkless launcher is
not a working subscription integration or a live coding-agent backend. Track
the remaining work in the [M8 implementation record](docs/plans/handoffs/M8-implementation-record.md)
and [authentication assessment](docs/designs/EXECUTOR_AUTHENTICATION.md).

**M9 remains planned:** self-improvement through evaluated immutable candidates
and explicit promotion, without letting the learner define its own exam.

## When Constructicon fits

Constructicon is aimed at solo developers, teams, and researchers building
agent-driven workflows over real repositories.

It is a good fit when you need:

- restart-safe, long-running software workflows
- exact provenance for code, checks, versions, and external effects
- an authority boundary independent of the model or agent provider
- reproducible and counterfactual runs against a recorded component world
- machine-shaped APIs with typed, repairable rejection
- durable human advice, approvals, and explicitly composed panels
- protected Git changes that are exact, attested, and idempotent

It is not a hosted coding-agent product, a prompt framework, or a general model
router.

## The conceptual kernel

Almost every execution concept reduces to four nouns:

| Noun | Meaning |
| --- | --- |
| **Definition** | What may be reused |
| **Manifest** | What this run will execute |
| **Invocation** | Where one execution occurred |
| **Receipt** | What changed outside the run |

Everything else is a policy that transforms or admits these, a transport that
carries them, a projection that renders them, or a capability leased to execute
them.

## Architecture

```text
L4  api        ControlPlane, RunHost, MCP, system assembly
L3  sdk        @task, component, flow, harness, loop, panel
L2  runtime    registry, admission, manifest, walker, resume
L1  substrate  journal, Git authority, workspaces, gates, executors, effects, channels
L0  core       every contract in the system, defined once
```

Dependencies point toward contracts. The runtime never imports concrete
substrate implementations, and the kernel is limited to the standard library
plus Pydantic. CI enforces both rules.

## Documentation

- [Invariants](docs/INVARIANTS.md): the laws every change must preserve
- [Architecture](docs/ARCHITECTURE.md): the complete current design and
  milestone acceptance tests
- [Contributing](docs/CONTRIBUTING.md): extension guides for agents and humans
- [M8 implementation record](docs/plans/handoffs/M8-implementation-record.md):
  shipped foundations, remaining slices, and proof boundaries
- [Executor authentication](docs/designs/EXECUTOR_AUTHENTICATION.md):
  subscription goals, current constraints, and the next feasibility experiment
- [Linux CI evidence](docs/M8_CI.md): runner qualification versus containment proof
- [Historical planning archive](docs/plans/README.md): non-normative plans,
  recovered records, and implementation handoffs
- [Self-improvement design](docs/designs/SELF_IMPROVEMENT.md): learning as
  candidates, never self-authorized mutation
- [Architecture decisions](docs/adr/): why the system is shaped this way

## Contributing

Contributions are welcome, especially around real executor integrations,
failure probes, channel transports, and examples.

Before adding a new concept, read [the invariants](docs/INVARIANTS.md), inspect
`system.describe()`, and look for an existing contract to compose. The full
repository gate is one command:

```bash
uv run verify
```

The expected standard is simple: if a failure can happen between two durable
facts, test the crash there.

## License

MIT. See [LICENSE](LICENSE).
