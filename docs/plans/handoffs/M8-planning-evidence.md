# M8 planning evidence — interfaces are not containment proof

Status: planning evidence for [M8 rev 1](../milestones/M8-live-executors-rev1.md),
not an implementation record or an approved deployment profile.

Observed on 2026-09-09 UTC against Constructicon
`71c4fe38ec8898d8af0f463c56ff34f3850bf63e`. No real model invocation,
credential access, sandbox installation, or host security-policy change was
performed. Repository and upstream reads plus local CLI help/version commands
are the evidence described here.

## Repository observations

`system.describe()` was called on a temporary SQLite-backed assembly containing
only a `FakeExecutor` and its descriptor. It returned description schema 2,
no components, and the existing fake READ profile (`filesystem="none"`, owned
process tree, allowlisted environment, enforced network declaration). This is
a controlled inspection of the assembled contract, not a discovery of globally
installed or privately registered components.

The source inspection covered:

- `core/executor.py`, `core/grants.py`, and `core/workspace.py`: existing task,
  outcome, profile, grant, workspace, and lease contracts.
- `runtime/validator.py::_register_atomic`: posture/profile checks, not complete
  live grant validation. `IsolationProfile.satisfies` does not inspect its
  `network_enforced` field.
- `api/system.py::__init__`: exact channel coherence, but no corresponding
  live executor coherence check.
- `runtime/registry.py::activate`: sealed capability revision equality; no
  automatic verification of a CLI's installed executable behind that string.
- `runtime/walker.py`: leases precede invocation, resource cleanup is existing
  machinery, and checkpoints—not backend conversations—govern recovery.
- `substrate/executors/`: only `FakeExecutor` is present. The existing triage
  fixture asserts that concrete type, so it is not yet backend-substitution
  evidence.
- `api/introspection.py`: profiles appear in `SystemDescription`, explaining
  why adding complete live policy needs an explicit description version decision.
- ADR 0009: exported snapshots use file permissions and content verification,
  explicitly not hostile same-user containment; typed executor workspaces were
  deferred until M8 had a consumer.

No private running journal or user registry was opened. No `rdeps()` result for
a nonexistent live component is represented as a meaningful impact analysis.
The future acceptance component must be described and its dependents inspected
once it is actually registered.

An admission-only counterexample also ran against the base code. A temporary
system was given a READ-only fake whose `validate_grants` returned a sentinel
refusal, alongside a descriptor claiming WRITE and `network_enforced=False`.
The existing `test/triage` definition and isolation fixture's lone graph were
registered in that temporary system; WRITE admission succeeded. No node or
executor was executed. This confirms the descriptor/coherence and complete
grant-validation gaps without claiming an OS escape or a live exploit.

The walker records a successful checkpoint before ordinary lease closure.
Consequently, executor process teardown must finish inside `execute`, before
its caller can return a successful node payload. Merely adding a kill operation
to lease `close` would leave the checkpoint ahead of the claimed completion.

## Local tool availability

| Tool | Observation | What it does not prove |
| --- | --- | --- |
| Codex | Windows `codex-cli 0.153.4`; `exec --help` read | Linux behavior, stream correctness, or containment |
| Claude Code | Windows `2.1.260`; `--help` read | Linux behavior, auth safety, or containment |
| Pi | No executable found on PATH | That the upstream source is unavailable |
| WSL | Executable exists; listing reports no installed distribution | A usable Linux execution environment |
| Docker/Podman | No executable found on PATH | That a container runtime is required by the selected design |

Help output is a versioned interface observation. It is not a transcript of a
model run, and Windows binaries are not pins for future Linux acceptance.

## Primary external sources

Sources were opened/read, not only found in search snippets. Mutable web pages
are dated references; implementation fixtures must add the exact executable
digests that produced their bytes.

### Codex

- [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode):
  `exec --json` produces JSONL; an output schema can request structured output;
  ephemeral operation and stdin prompts are documented. User-config bypass is
  distinct from auth state. The automation guidance warns against exposing API
  keys to repository-controlled code and describes a proxy-based CI pattern.
- [Sandboxing](https://learn.chatgpt.com/docs/sandboxing): sandbox enforcement
  and approval policy are distinct; Linux/WSL use bubblewrap-related facilities,
  while native Windows is a different implementation. This does not establish
  Constructicon's whole-process boundary.
- [Advanced configuration](https://learn.chatgpt.com/docs/config-file/config-advanced):
  native model-provider base URLs and wire/auth configuration are configurable.
  This makes a controlled route a candidate; it does not prove a gateway's
  authority limits or subscription compatibility.

The initial developers.openai.com documentation URLs redirected to the linked
official learn.chatgpt.com pages. Markdown versions were read directly when
the browser's text extractor rejected their content type.

### Claude Code

- [Programmatic execution](https://code.claude.com/docs/en/headless): print mode
  has native JSON/stream JSON and schema output. Bare mode changes credential
  loading and does not reuse subscription login; ordinary print mode can load
  project configuration without an interactive trust prompt.
- [CLI reference](https://code.claude.com/docs/en/cli-reference): `--tools`
  selects available tools; `--allowedTools` concerns permission approval.
  Safe mode preserves authentication but has managed-policy exceptions. Neither
  flag alone proves complete configuration isolation.
- [LLM gateways](https://code.claude.com/docs/en/llm-gateway): native provider
  routing through a configured gateway is documented. This is not evidence of
  any provisioned gateway in the current environment.
- [Bash sandboxing](https://code.claude.com/docs/en/sandboxing): the upstream
  sandbox is useful defense in depth; Constructicon still owns the physical
  launch boundary required by ADR 0008.

### Pi

The former `badlogic/pi-mono` URLs redirected to `earendil-works/pi`.
Pinned source examined:
`6160683a4a8012f0d1cd30c145df18b4ca6f5176`.

- [CLI/readme at that revision](https://github.com/earendil-works/pi/blob/6160683a4a8012f0d1cd30c145df18b4ca6f5176/packages/coding-agent/README.md):
  print/JSON modes, explicit tool selection, ephemeral sessions, and separate
  resource-discovery controls. The package at this revision identifies itself
  as `@earendil-works/pi-coding-agent` version `0.85.1`; no package was installed.
- [Native JSON stream contract](https://github.com/earendil-works/pi/blob/6160683a4a8012f0d1cd30c145df18b4ca6f5176/packages/coding-agent/docs/json.md):
  message updates are delta-only; message end carries the final message and
  usage updates are cumulative. JSON event mode is not a structured-answer
  schema guarantee. The plan therefore does not advertise one.

### Linux containment candidate

- [Bubblewrap README](https://github.com/containers/bubblewrap/blob/4df8ddc7f6bb2080637aa26bf7b205321f504bfc/README.md),
  pinned at `4df8ddc7f6bb2080637aa26bf7b205321f504bfc`: bubblewrap is a tool for
  building a policy, not a complete policy. Its documentation explains empty
  mount namespaces, PID/network isolation, private temporary storage, terminal
  and exposed-socket risks. These support the proposed mechanism, not a claim
  that Constructicon has executed it safely.
- [Linux PID namespaces manual](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html):
  namespace-init termination kills its remaining processes. M8 still has to
  prove that host death, cancellation, deadlines, and normal return actually
  terminate the correct namespace, including the launch race.

No systemd service, OCI daemon, or cgroup manager is selected merely to mirror
the executor abstraction. Additional OS machinery would need a demonstrated
failure the chosen ownership boundary cannot handle, followed by review.

## Provenance discipline

ADR 0005 names ideas from `sushiHex/hardline-mcp@6d1187a` and
`disler/fusion-harness@01a3482`. The abbreviated revisions resolve to
`6d1187a4a6af8d76fab456bbea818dc2048c410a` and
`01a348202482cad0e7d3c34eada180f711aaddd7`, respectively; both trees contain
`LICENSE`. This planning PR copies no upstream code. That tree check is not a
new license audit or a claim that current upstream code was reviewed.

Before implementation reuses source or patterns, read the pinned license and
relevant source, record files-copied versus ideas-reimplemented, preserve
required notices, and document local changes and update procedure. Do not
fetch a moving upstream head and attribute it to the old pinned revision.

## What remains to be proved

No Linux isolation, gateway provisioning, credential-lifetime enforcement,
Linux CLI invocation, native model stream capture, or subprocess containment
was executed in this planning session. Those are mandatory implementation
gates, with named probes in the plan. Documentation and `--help` observations
cannot substitute for them.

The owner must decide Linux-first support, gateway-only initial authentication,
finite supported tool sets, and the schema-3 description boundary. Until that
decision and the implementation proof, live profiles remain proposals.
