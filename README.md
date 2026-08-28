# Constructicon

[![verify](https://github.com/sushiHex/constructicon/actions/workflows/verify.yml/badge.svg)](https://github.com/sushiHex/constructicon/actions/workflows/verify.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Assemble the plan. Seal the run. Prove what ships.**

Constructicon is an execution and authority layer for agentic software
engineering. Agents can write code, compose workflows, and operate runs.
Constructicon compiles that intent into a sealed, crash-safe execution, scopes
every capability, records every external change, and allows only proven results
to reach protected Git.

> Authored intent may be ergonomic. Executed reality must be explicit.

## Why Constructicon exists

Most agent frameworks focus on generating work: prompts, roles, routing, memory,
and tool loops. Constructicon focuses on the boundary after generation:

**What exact plan ran, against which component world, what evidence passed, what
changed, and can the answer survive a crash or retry?**

Constructicon is not another agent persona system or model router. It is the
deterministic machinery beneath autonomous software work.

| Common agent harness | Constructicon |
| --- | --- |
| Interprets a mutable workflow while it runs | Compiles one immutable `ExecutionManifest` before execution |
| Accepts an agent's claim that checks passed | Mints attestations from checks observed by trusted deterministic code |
| Gives the worker credentials to push code | Gives agent workspaces zero authority over protected refs |
| Repeats an effect after an uncertain failure | Reconciles the external world first, then records one receipt |
| Lets component updates drift into active work | Pins one component world per run and changes future resolution only through explicit promotion |
| Approves a branch or patch in the abstract | Gates the prepared merge commit and installs that exact commit or nothing |

### The central promise

**The only path from proposed code to a protected Git ref is one exact,
attested, idempotent Git transaction.**

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

### Run a small workflow

Create `demo.py` in the repository root:

```python
import asyncio
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel

from constructicon.api.system import Constructicon
from constructicon.sdk import flow, port_type, task
from constructicon.substrate.journal.sqlite import SqliteJournal


class Issue(BaseModel):
    title: str


class Brief(BaseModel):
    title: str


@task("demo/triage", output="brief")
async def triage(
    issue: Annotated[Issue, port_type("demo/Issue")],
) -> Annotated[Brief, port_type("demo/Brief")]:
    return Brief(title=issue.title)


async def main() -> None:
    state_dir = Path(".constructicon")
    state_dir.mkdir(exist_ok=True)

    system = Constructicon(
        journal=SqliteJournal(state_dir / "demo.db"),
    )

    version = system.register(triage)
    system.promote_initial(component=triage.name, version=version)

    workflow = flow("demo/issue-to-brief", triage)
    result = await system.start(
        workflow.definition.body,
        {"issue": {"title": "Fix the flaky retry"}},
    )

    print(result.status)
    print(result.outputs)


asyncio.run(main())
```

Run it:

```bash
uv run python demo.py
```

`@task`, `flow`, `component`, `harness`, and `loop` are authoring sugar only.
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
stable pagination, and full immutable records remain available by reference.

For HTTP, Constructicon is authenticated or unavailable. Actor identity comes
from a verified OAuth bearer token, never from a caller-controlled tool
argument.

## What is implemented

Constructicon `0.1.0` is a developer preview. The core architecture is frozen,
and milestones M1 through M6 are implemented and green:

| Milestone | Capability |
| --- | --- |
| M1 | Sealed manifests, checkpoint resume, and idempotent effects |
| M2 | Persistent registry, crash hardening, cancellation, liveness, and projections |
| M3 | Protected Git authority, real gates, attestations, and exact verified merge |
| M4 | Generic bounded repair loops without a second scheduler |
| M5 | Agent-first JSON authoring, SDK sugar, introspection, and repairable admission |
| M6 | Durable authenticated control plane, MCP v2 adapter, and counterfactual replay |

Next:

- **M7:** journal-backed channels, panels, and human advisor or approval round
  trips
- **M8:** live Claude Code, Codex, and Pi executors once their isolation
  profiles can be enforced honestly
- **M9:** self-improvement through evaluated candidates and explicit promotion

The deterministic execution core, Git authority path, Python SDK, and MCP
control plane exist today. Live coding-agent adapters are intentionally not
treated as ready until their isolation claims can be mechanically enforced.

## When Constructicon fits

Constructicon is aimed at teams and researchers building agents that can affect
real repositories and need stronger answers than "the agent said it worked."

It is a good fit when you need:

- restart-safe, long-running software workflows
- exact provenance for code, checks, versions, and external effects
- an authority boundary independent of the model or agent provider
- reproducible and counterfactual runs against a recorded component world
- machine-shaped APIs with typed, repairable rejection
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
L4  api        ControlPlane, MCP, system assembly
L3  sdk        @task, component, flow, harness, loop
L2  runtime    registry, admission, manifest, walker, resume
L1  substrate  journal, Git authority, gates, executors, effects
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
