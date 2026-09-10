# M8 native authentication: feasibility investigation

Status: investigation result, 2026-09-09 (America/Los_Angeles). Not an accepted
successor ADR, implementation plan, or proof of working subscription execution.
Repository baseline: `c39afe7033a259932dbf4110160501519b8710e0` (PR B merged).

## Result

The owner authorized investigating native subscription execution and using
`sushiHex/hardline-mcp` as an example. The interfaces below justify a bounded,
credential-free experiment; they do **not** yet establish a native executor
that satisfies Constructicon's authority laws. No account was inspected, login
performed, provider request sent, or credential copied. No host sandbox policy
changed. The Windows binaries were inspected, not qualified as Linux adapters.

Keep [ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md)
in force. In particular, neither a copied login file nor a reusable access
token belongs inside its whole-CLI untrusted boundary. The candidate below
would move a credential-owning harness into the trusted computing base. That
requires evidence and an explicitly accepted successor decision, not a change
to a launcher flag. This record grants neither implementation nor deployment
authority for that candidate.

## Reuse before extension

`system.describe()` was exercised against a fresh, credential-free test
assembly: schema 3, no registered components, one fake executor, READ root
grants, and no network. This is catalog inspection, not evidence of a live
provider. Source inspection establishes the reusable contracts:

- [`ExecutorProvider`, `Executor`, `TaskSpec`, `ExecutorOutcome`](../../../src/constructicon/core/executor.py)
  already describe task-shaped work independent of provider or transport.
- [`WorkspaceView`, `WriteWorkspace`, `LeaseContext`, `LeasedCapability`](../../../src/constructicon/core/workspace.py)
  already provide workspace and acquisition ownership. PR B supplies a concrete
  networkless Linux boundary and retained cleanup ownership.

There is no reason here for a completion API in the kernel, provider enum,
second scheduler, new job ledger, or universal broker interface. Cloud and local
models continue to enter through a compatible concrete task harness, as
[ADR 0005](../../adr/0005-executor-seam.md) requires. Authentication feasibility
does not decide model quality, fallback, or billing.

## Observed interfaces and their limits

### Codex

The installed Windows CLI reports `codex-cli 0.153.4`. Its static
`app-server generate-json-schema --experimental --out <temporary-directory>`
command succeeded without starting a server or making a model request.
Generated `ThreadStartParams` includes `dynamicTools`; `DynamicToolCallParams`
requires `arguments`, `callId`, `threadId`, `tool`, and `turnId`;
`DynamicToolCallResponse` requires `contentItems` and `success`. The command
approval response instead carries a `decision`, not substituted tool output.

The [official app-server reference](https://learn.chatgpt.com/docs/app-server)
documents bidirectional tool calls, experimental dynamic tools, and a remote
CodeMode host shared by threads in one server. These are useful integration
points, not a statement that all filesystem, execution, or startup behavior
uses them. `externalSandbox` assumes external enforcement; it creates none.
External-token authentication still supplies a token to the server. Client
RPCs such as filesystem access and process spawning must be distinguished
from model-callable tools, not assumed equivalent merely because both exist.

The [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
describes separate shell, execution, CodeMode, plugin, and MCP controls.
Disabling one family is not proof that every other path is mediated. Published
documentation can advance beyond the installed build: generated metadata
confirms only the fields above, not current remote-CodeMode compatibility or
a complete tool-disable recipe. No such recipe was executed here.

For reproducibility, SHA-256 of the generated files, without normalization:

```text
401bba20cfbd95762bef0467d840430c46be53369093ad9f26425ba757e34efc  DynamicToolCallParams.json
abb082cad67f11fcc98ba75f2eff75d7d1723af0c657655329b83ff160451a02  DynamicToolCallResponse.json
6d0767113e22f311381809b6b236b0dde2b99b01992879c26bf7b1ea0e003cb7  CommandExecutionRequestApprovalResponse.json
25f490368ec6df52a2a3b82a5469d2413307eb93439121b309f415b5648eee7a  v2/ThreadStartParams.json
```

These identify this observation; they are not protocol compatibility goldens.
ChatGPT sign-in and separately billed API authentication remain distinct in
the [authentication documentation](https://learn.chatgpt.com/docs/auth).
Neither a local auth-mode marker nor a successful schema probe proves which
account, quota, or model would serve an invocation.

### Claude Code

The installed Windows binary reports `2.1.260 (Claude Code)`; no invocation or
authentication probe was run. The current
[CLI reference](https://code.claude.com/docs/en/cli-reference) distinguishes
`--tools ""` from MCP configuration: removing built-in tools does not remove
MCP tools. Safe mode also retains certain managed customizations. Neither is
an operating-system containment contract.

The [SDK permission flow](https://code.claude.com/docs/en/agent-sdk/permissions)
is particularly important: hooks, rules, and permission mode precede
`canUseTool`; automatically allowed calls can bypass that callback. It is not
a universal execution interceptor. This observation is about the documented
SDK interface, not a claim that this investigation ran that SDK or that all
Claude Code integration routes are impossible.

The [provider's credential-use guidance](https://code.claude.com/docs/en/legal-and-compliance)
distinguishes an end user signing into an unmodified Claude Code binary from
a developer collecting or intermediating Claude.ai credentials. It states
conditions for hosted native binaries and different guidance for SDK use.
This investigation proposes neither an OAuth relay nor subscription-token
use through the SDK. Technical feasibility and permission for a particular
deployment must be established separately; this record is not legal advice
or confirmation of an account's eligibility.

### Pi

The [coding-agent README at `400d690`](https://github.com/badlogic/pi-mono/blob/400d6905ce46ec46e79da8a7701b1b48850192df/packages/coding-agent/README.md)
documents RPC/SDK integration, replacement of built-in tools, and custom
providers. This is a useful second interface to investigate, not a reason to
design a common broker first. Pi was not installed on this host, and no Pi
driver, subscription route, or containment property was tested. Its advertised
provider support is not independent evidence of provider authorization.

## What to learn from Hardline, and what not to copy

Source inspected at
[`sushiHex/hardline-mcp@28cf5b5`](https://github.com/sushiHex/hardline-mcp/tree/28cf5b5084cabe33dfa20b103eb606d94911fc39),
primarily `hardline_mcp/adapters.py`, `jobs.py`, and adapter/spawn tests. No
Hardline code or live test was executed, and no implementation was copied.

Useful lessons are explicit subprocess stdin ownership, prompt/argument
separation, bounded lifetime handling, transcript damage demotion, and honest
requested-versus-observed metadata. Constructicon should express these through
its existing executor outcomes, invocation identity, and lease cleanup rather
than importing Hardline's independently owned job service.

Two source facts make it unsuitable as a containment template:

- Its Codex advisory path copies `auth.json` into a temporary Codex home.
  Temporary storage does not remove credential authority from that process.
  The same path distinguishes subscription configuration from verification;
  preserve that honesty, not the credential-copy mechanism.
- Its Claude READ path combines disabled edit tools with a Bash guard and
  explicitly describes that guard as weaker than a sandbox. A READ promise
  cannot depend on classifying a command string while other file readers,
  interpreters, hooks, or child processes retain access.

Its guarded CLI invocation is evidence for integration ergonomics, not a
counterexample to [I1 and I3](../../INVARIANTS.md). Likewise, backend redirection
must not replace an admitted provider silently, and a best-effort process-tree
kill must not replace PR B's evidence of exact acquisition quiescence.

## Candidate worth testing, not yet a design decision

Separate native authentication from model-selected tool execution. An
unmodified native harness would own its vendor-supported login. An
adapter-private tool channel would send only task-scoped requests to workers
inside Constructicon's existing READ/WRITE boundary. Each invocation would
own its harness, channel, and workers under the existing acquisition lifetime;
one invocation would not share a server or resumable conversation with another.

This separation is not itself isolation. A native built-in reader that can
read its harness's login files, or an interpreter executing in its address
space, defeats it. The candidate fails unless every model-selected operation
is mediated or unavailable, with OS enforcement protecting credentials and
authority from the untrusted worker regardless of CLI permission decisions.
Renaming a credential-bearing CLI "trusted" is not that proof.

The future proof must distinguish and account for:

| Surface | Required boundary evidence |
| --- | --- |
| Model-selected reads, writes, patches, shell, code execution | Only the acquisition's workspace and granted tools; no host paths, journal, credentials, or sibling state |
| MCP/apps, plugins, subagents, hooks, startup helpers | Exact inventory and controlled configuration; no alternate local execution or inherited service authority |
| Provider authentication, refresh, and transport | Vendor-supported native flow; explicit credential-owning trusted code and network destinations; no model-controlled arbitrary proxy |
| Private protocol and tool results | Invocation-bound endpoint; grants come from admission, never request arguments; bounded framing/output and refusal of unknown operations |
| Cancellation, crash, and restart | Existing closure revokes further work; guards remain held until every owned process is quiescent; no retry revives a prior epoch |

OS isolation of workers does not prove that a built-in operation remaining in
the credential-owning harness is safe. Conversely, a finite set of successful
callback tests does not prove absence of bypasses. Both the complete pinned
surface inventory and physical boundary tests are required.

There are unresolved contract decisions, not fields to add speculatively:

- `ExecutorGrantPolicy` schema 1 currently offers `none` or
  `provider_route_only` network access. A native authenticated harness cannot
  silently relabel its broader authority as the latter. A viable successor
  must define the authority split and explicit wire/version compatibility.
- The public MCP adapter remains a one-delegation ControlPlane skin. A private
  tool transport is not permission to add another public MCP authority path.
  Prove one concrete adapter protocol before proposing a shared abstraction.
- The trust-boundary change must name the exact ADR 0018 clauses superseded,
  while preserving physical READ/WRITE enforcement, truthful profile identity,
  revocation, and recovery. If that cannot preserve the invariants, reject the
  candidate rather than weaken them.

## Smallest next experiment

Investigate Codex app-server first because local generated metadata provides
a concrete starting interface, not because subscription feasibility is proved
or because future adapters should conform to Codex's protocol.

1. In a disposable Linux environment, pin one native binary and inventory its
   actual model-tool, client-RPC, configuration, and startup paths. Reproduce
   the relevant protocol metadata there. Do not reuse a desktop home or login.
2. Exercise a minimal adapter-private driver against scripted protocol peers:
   correct tool dispatch, unknown-operation refusal, framing/output bounds,
   response loss, cancellation, and cross-invocation isolation. Put actual
   hostile worker fixtures through PR B's existing boundary and cleanup law.
   This proves driver/worker behavior only, not native CLI completeness.
3. Separately establish that the pinned, unmodified CLI can drive the intended
   path using a credential-free local fake provider or another supported
   offline test interface. Do not assume either exists. If it requires a
   live account, undocumented credential emulation, or a modified binary, stop
   this experiment and record the gap; do not substitute peer tests as proof.
4. Only a positive combined result warrants a successor ADR and a bounded
   implementation plan. Name remaining live-account/operator conformance
   gates separately. No credentials, paid calls, new authentication mode,
   profile availability, or gateway deployment follow from this record.

If no native adapter qualifies, report that outcome and leave it unavailable.
An API/cloud gateway remains an explicit, separately billed alternative under
ADR 0018, not silent fulfillment of the owner's subscription goal. Safe WRITE
capture and contained gates remain independent M8 work.

Native CLIs may also be external authors/reviewers using the existing public
ControlPlane/MCP contract and their own operator-managed login. That is a
different role, not an in-graph executor, client-containment proof, automatic
approval authority, or completion of M8 subscription support. No such client
was configured or exercised during this investigation.

## Verification boundary

This change is documentation only. Archive hashes and links can verify its
integrity; the ordinary repository gate can verify the unchanged baseline.
Neither supplies a missing native mediation, authentication, or containment
proof. The schema-generation and source observations above are the complete
new executable/interface evidence claimed by this investigation.
