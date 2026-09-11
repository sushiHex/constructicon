# M8 native mediation: credential-free Linux experiment

Status: bounded investigation under
[#37](https://github.com/sushiHex/constructicon/issues/37), updated 2026-09-11.
Not a successor ADR, production adapter, subscription proof, or live profile.
Base: `d94a47931d63b3e59de72450bb8e794178b6bad4`; work in
[PR #48](https://github.com/sushiHex/constructicon/pull/48).
The bounded follow-up in [PR #49](https://github.com/sushiHex/constructicon/pull/49)
starts from its squash merge, `dbfe05ce21d7f2441ec88daaa424fdc895e95b7e`.

## Result and decision boundary

An unmodified Linux Codex CLI can complete a credential-free turn against a
local fake Responses provider and dispatch its experimental dynamic tool to
Constructicon's existing contained worker. That closes the earlier uncertainty
about whether an offline integration path exists. The image-enabled control
and the disabled-image configuration have different observed results; neither
qualifies complete mediation or native authentication.

The earlier recipe left `view_image` enabled. PR #48's fallback-model control
reproduces its result: the native reader sends the exact PNG fixture from the
harness's private home to the fake provider, without a dynamic callback or
contained-worker invocation. Its tool inventory contains `request_user_input`,
`view_image` and `contained_python`. This harmless file is outside the acquired
workspace; the result refutes exclusive worker mediation for that enabled
configuration only.

With `features.view_image = false`, that fallback-model inventory contains only
`request_user_input` and `contained_python`. Even when the fake provider requests
`view_image` directly, the native router returns `unsupported call: view_image`
instead of the image bytes. The contained-worker callback still succeeds in
both configurations. The tested image-reader path is therefore closed by this
control; it is not a remaining failure of the disabled-image recipe.

The tested `exec_command` attempt is refused in both configurations, creates no
harness-home canary, and never reaches the supplied worker. These observations
do not cover every model-dependent tool inventory, startup/extension path,
client-RPC reachability or lifecycle boundary. Green investigation CI is not
green native-authentication eligibility or a provider-wide impossibility proof.

Keep [ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md)
in force and live native authentication unavailable. No reusable credential
was inspected, copied, requested or supplied; no provider account, paid model,
real gateway or desktop security setting was touched. The experiment gives
no evidence for accepting a credential-owning harness as trusted code.

## Reproduction and artifact identities

Run the existing [M8 containment workflow](../../../.github/workflows/m8-containment.yml)
on the experiment head. It provisions only the already authorized disposable
GitHub-hosted Ubuntu 24.04 environment. The native probe uses a separate outer
PID/network namespace with only loopback; it verifies the interface and route
inventory before executing the CLI as the non-sudo `m8-service` user. The whole
experiment has no provider egress. This lab wrapper is not an additional
production launcher or a Windows/Linux bridge.

The [release package](https://github.com/openai/codex/releases/download/rust-v0.153.4/codex-package-x86_64-unknown-linux-musl.tar.gz)
is Codex `0.153.4`, `x86_64-unknown-linux-musl`. SHA-256:

```text
a822187e1a2420c61c5926721bfbd878701ed95547c9bb0d4de4498a16ba1821  release archive
56ef98ab4032d317ab26e9b5e5a175650717351edb16ed9cde0cb6d1734d62da  bin/codex
401bba20cfbd95762bef0467d840430c46be53369093ad9f26425ba757e34efc  DynamicToolCallParams.json
abb082cad67f11fcc98ba75f2eff75d7d1723af0c657655329b83ff160451a02  DynamicToolCallResponse.json
25f490368ec6df52a2a3b82a5469d2413307eb93439121b309f415b5648eee7a  v2/ThreadStartParams.json
```

The workflow verifies the release archive before root-owned extraction. The
schema probe identifies the executed binary and hashes all 416 generated JSON
schemas; the three protocol files above also match the earlier Windows static
observation. A cross-platform schema match is not cross-platform containment.

Portable checks, without Linux or a native binary:

```bash
uv run pytest tests/test_native_codex_probe.py -q
uv run python scripts/check_native_codex_probe_mutations.py
```

The native step invokes
`tests/substrate/test_native_codex_mediation.py` inside the isolated namespace.
Do not run the harness on a desktop with an inherited environment or real
home. The workflow's empty environment and per-test disposable Codex home are
part of the experiment. They are not a proposed credential-storage mechanism.

## Three proofs kept separate

### Private driver

[`tests/native_codex_probe.py`](../../../tests/native_codex_probe.py) is a test
instrument, not a shipped adapter or generalized RPC library. It sends only
initialize, thread/start and turn/start, creating one thread/turn per process;
it never resumes or shares a conversation. It accepts one tool operation,
with thread/turn/call identities checked before the worker is awaited.
Arguments carry a bounded program, never a workspace, grant or actor. Unknown
operations and foreign identities refuse.

The call is spent before execution. Response loss or cancellation never causes
this driver to execute the same call again. It does not promise durable command
replay: a future executor must use the existing lease/checkpoint lifecycle,
not retain this process-local test state as execution authority.

The ordinary suite uses scripted peers and real pipes to test malformed JSON,
duplicate keys, non-finite values, invalid Unicode, EOF/truncation, record and
total bounds, worker output bounds, response loss, cancellation and separate
invocations. The nine portable assertion mutants target the driver checks;
none is a native completeness proof. Stderr and stdout have no shared order:
observing overflow may follow a dispatched call, but cannot yield a successful
probe. Process-group cleanup is lab hygiene, not escaped-descendant ownership.

### Contained worker

The probe reuses `RecordedExecutorProvider`, `ContainedWorkspaceProvider`,
the acquisition guard/closure, and `LinuxLauncher`. It neither registers a
native production profile nor adds a kernel contract. The worker runs the
fixture program from stdin in the acquired READ snapshot, with no route or
native harness home mounted. The worker fixture checks an absent host file and
harness image, and requires EROFS from an attempted workspace write. Cleanup
verifies no active worker, removed snapshot and committed closure.
The existing native B/C/D suites carry the broader physical and restart proof.

This specifically proves composition with the existing worker boundary. It
does not independently prove all grants, WRITE behavior, gateway revocation,
or crash/restart ownership of a future credential-bearing harness.

### Native CLI and surface inventory

The [official app-server reference](https://learn.chatgpt.com/docs/app-server)
documents experimental dynamic tools. The
[configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
documents custom Responses providers without OpenAI authentication. The local
fake uses that interface with no Authorization header, not a fabricated token
or undocumented account emulation. It emits deterministic tool and terminal
records; no LLM participates in the measurement.

The recorded model request inventories the effective tools, rather than
inferring them from configuration flags. The artificial `probe-model` uses
fallback model metadata, so its inventory does not establish the tools of a
real deployment model. Generated `ClientRequest` metadata
separately inventories 155 client RPCs, including filesystem/process operations,
hooks, skills, plugins, MCP, authentication and remote control. Those RPCs are
not thereby model tools; the probe issues none of them. Their presence is also
not proof that startup paths are disabled.

The recipe requests disabled shell, unified execution, patch, multi-agent,
CodeMode, JS and apps features in a fresh home, and uses a single ephemeral
thread. The effective tool inventory, config warnings and startup diagnostics
remain the evidence. Unknown flags or a successful thread cannot establish
that a feature was disabled. The native sandbox availability diagnostic can
appear even though the explicitly unsandboxed lab thread completes; only the
separate Constructicon worker boundary is credited with containment.

The enabled/disabled matrix uses `features.view_image`, accepted by the pinned
binary. The attempted `tools.view_image` spelling was rejected as an unknown
configuration field. The binary's own `features list` output records
`view_image` as stable and enabled by default; the provider request and forced
call results separately prove the disabled control's behavior. The shared
fixture creates its empty configuration directory before any CLI command.

Full request records, observed methods/warnings, worker outputs and schema
digests are emitted as `codex-*.json` in the workflow artifact. They contain
only the deterministic fixture and disposable paths. Artifact retention is
seven days; this committed record retains the durable conclusions and pins,
and the checked-in instrument can reproduce them. No raw chat/session is
committed as evidence.

## What remains an explicit decision

[#38](https://github.com/sushiHex/constructicon/issues/38) still requires the
owner's concrete authentication/deployment choice. A working callback is not
positive combined mediation evidence, so it does not authorize a native
successor ADR. Conversely, this bounded recipe is not a provider-wide
impossibility result. Further native investigation must assess model-dependent
tool inventories, startup/extensions and client-RPC reachability, and prove
lifecycle ownership before a successor design could be accepted. The passing
disabled-image case closes that tested path, not this broader proof obligation.

The API/cloud gateway route remains available as an explicit alternative, but
no actual deployment or separately billed route has been selected. Slice E
cannot claim deployed conformance from this loopback fake. Steps beyond this
boundary need the missing decision, not another speculative kernel interface.
The [OpenRouter reuse assessment](../../designs/OPENROUTER.md) likewise changes
no authentication authority or M8 scope. The follow-up below bounds the next
experiment and supplies the current decision packet; it does not reopen ADR
0018 or turn unmeasured obligations into passing controls.

## Bounded follow-up (PR #49)

### Model profiles and tool surfaces

The binary/archive identities above are unchanged. The exact tagged source is
[`3d2ee51`](https://github.com/openai/codex/tree/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a).
Its bundled
[model catalog](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/models-manager/models.json)
has SHA-256 `d7136a413cfac1b5b1686d9e0dcc5c80ca05bebed5e9fc3911376561d0ef6ee8`.
The two selected entries, `gpt-5.5` and `gpt-5.6-sol`, declare a free-form patch
tool. The pinned
[tool registry](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/tools/spec_plan.rs)
uses the model metadata when registering that tool. Source inspection motivated
the experiment; the binary's requests and fixture writes establish its result.

Both names pass unchanged through the private config, thread request, fake
provider request and fake response. Neither has a missing-model-metadata
diagnostic. No catalog was rewritten to make the result pass, and no live model
or subscription participated. The fixture is not a billing or entitlement test.

| Profile | Observed published surface | Forced native patch |
| --- | --- | --- |
| `probe-model` fallback | Ordinary `tools`: dynamic worker, question tool, optionally image reader | Not tested; no metadata-based patch claim |
| `gpt-5.5` | Ordinary `tools`: the same set plus native patch | Writes the disposable-home fixture; zero worker calls |
| `gpt-5.6-sol` | `additional_tools` in input: CodeMode `functions` and `collaboration` namespaces; CodeMode describes the dynamic worker, patch and optional image reader | Writes the disposable-home fixture; zero worker calls |

Both real profiles write the fixture with images enabled and disabled, despite
`apply_patch_freeform = false`. Sol's published CodeMode/collaboration surface
also contradicts the requested false flags. Those are negative qualification
results, not reasons to flatten or silently omit the unexpected inventory.
The fixture sends direct tool records to test routing; it does not claim a
real model chose them or that every CodeMode/nested-tool route was exercised.

The first matrix run on `cf29776` passed the fallback and `gpt-5.5` cases but
failed Sol's ordinary-`tools` assertion. The downloaded evidence contained its
distinct `additional_tools` representation and successful patch writes. The
instrument now asserts that representation explicitly instead of weakening
the inventory check or crediting a configuration flag. A green test reproducing
an unmediated write means the experiment worked, not that mediation passed.

### Bounded surface and lifetime assessment

The new test cases are in
[`test_native_codex_mediation.py`](../../../tests/substrate/test_native_codex_mediation.py).
Three RPC names (`fs/readFile`, `process/spawn`, `config/value/write`) are
presented as model calls, never sent as client RPCs. The expected exact
unsupported-call refusal distinguishes name routing from malformed arguments.
Portable tests separately prove the private driver refuses those names as
server requests even with otherwise valid worker arguments. This is not an
exhaustive reachability analysis of all 155 client RPCs.

A project-local MCP fixture is an inert Python process that records startup
and advertises no tools. Explicit trusted and untrusted project configurations
provide the positive and negative controls; an empty home alone would make a
non-launch test vacuous. This covers one startup path, not arbitrary hooks,
plugins, skills, inherited system config or every configuration precedence.

The lifetime cases use an actually running WRITE worker in an acquired staging
workspace, observed through its heartbeat. On cancellation and native-process
death, the driver joins the worker and its existing launcher, stops that
heartbeat, and reaps the native process. The acquisitions remain open and the
workspace remains present at driver return; explicit test cleanup closes and
disposes them afterward. Both states are asserted and recorded separately.
This does not prove event-driven acquisition disposal. No extra lifecycle store
or scheduler is introduced. Native death while the driver awaits its worker
is bounded by the existing 12-second test deadline, not an immediate death
notification; the test must not credit it as instantaneous revocation.

These cases do not kill the driver process or restart a credential-owning
harness. Existing B/C/D owner-death tests remain worker-boundary evidence;
composing them with a native harness is a remaining proof obligation. No
process-group helper is promoted into escaped-descendant ownership evidence.

| Obligation | Status for this bounded recipe | Scope of the evidence |
| --- | --- | --- |
| Native callback into contained READ worker | Pass | Both real profiles; not every model or grant |
| Disabled native image reader | Pass | Exact image control on each profile |
| Native patch exclusively mediated | Fail | Both real profiles write outside the worker without dispatch |
| Requested disabled model-dependent features | Fail | Sol still publishes CodeMode/collaboration; execution of every nested route untested |
| Three client-RPC names as model calls | Pass | Exact unsupported-call refusals in both profiles; not an exhaustive RPC proof |
| Untrusted-project MCP startup blocked | Pass | No marker when untrusted; trusted control starts the inert extension |
| Cancellation/death with active worker | Pass, bounded | Worker joined, heartbeat stops, native process reaped; native death uses the overall deadline |
| Event-driven native acquisition disposal | Unknown | Acquisitions remain open at driver return; disposal is explicit test cleanup, not event-path evidence |
| All hooks/extensions/config sources | Unknown | One project MCP path cannot establish completeness |
| Driver death and native harness restart ownership | Unknown | Not proved by worker-only recovery or process groups |
| Credential-bearing native eligibility | Not qualified | No credentials; complete mediation already fails for this recipe |

The [authentication packet](../../designs/EXECUTOR_AUTHENTICATION.md#bounded-decision-packet-pr-49)
owns the resulting alternatives. This experiment stops at a supported negative
result for the named recipe; it does not expand itself into a different trust
boundary, a new provider investigation, or API billing. Unknown rows are
explicit prerequisites for any future native qualification, not an invitation
to mark that work complete when this investigation merges.

## Verification observations

At `b725a3e7135ba6d15451dcdccc5268af48169521`,
[standard CI](https://github.com/sushiHex/constructicon/actions/runs/34527579889)
passed 1,861 tests with 101 explicit skips; all four import contracts, ruff and
strict mypy passed. The
[native lane](https://github.com/sushiHex/constructicon/actions/runs/34527579807)
passed four native probe cases and the 268-test existing containment suite.
It killed the nine portable probe mutants and all 91 existing B/C/D mutants.
The downloaded artifact's `codex-view_image.json` independently confirms the
exact PNG bytes in the fake provider's second request, with zero worker calls.
That earlier artifact describes the enabled-image experiment, not the later
disabled control.

At `2af6db3b7db2e338bdf692c7335affd9793188db`,
[standard CI](https://github.com/sushiHex/constructicon/actions/runs/34534289049)
passed 1,862 tests with 104 explicit skips. Local `uv run verify` passed 1,814
tests with 152 Windows skips; ruff, strict mypy and all four import contracts
passed. The
[native lane](https://github.com/sushiHex/constructicon/actions/runs/34534289033)
passed all seven probe cases, the 268-test existing containment suite, and all
100 portable/native assertion mutants. Runner qualification also passed.

The downloaded exact-head `codex-view_image-images-true.json` records the image
bytes; `codex-view_image-images-false.json` records the two-tool inventory and
`unsupported call: view_image`, with no worker call. These artifacts were
inspected independently of the test assertions. The fixture regression failed
before directory creation moved to shared setup and passed afterward.

The confirming review on that head found a documentation overclaim: this
record still presented the enabled reader as unresolved without reporting the
passing disabled control. This correction and the linked authentication
summary distinguish both configurations without changing code or qualifying
authentication. PR #48 carries final-head gate/review evidence; the recorded
runs above are not substituted for checks on subsequent commits.

At `2ec171f7e574d66ceafcd765aac9ef92224b6aec`, the
[follow-up native lane](https://github.com/sushiHex/constructicon/actions/runs/34545164135)
passed all 39 native probe cases, the existing 268-test containment suite, and
the then-current 100 assertion mutants. Standard CI and runner qualification
also passed. The downloaded artifact was inspected separately: the trusted
project starts the inert MCP fixture while the untrusted project does not;
each lifetime case records one worker call, native exit `-9`, and a stopped
heartbeat. That artifact's closure/removal fields were recorded after manual
test cleanup, not caused by cancellation or native death. The RPC-name cases retain
the exact unsupported-call outputs, and both real profiles retain the native
patch write with zero worker calls.

The follow-up also strengthens the portable instrument: model selection is
observed across config and real-pipe thread creation rather than assumed,
and client-RPC names cannot become worker authority. All 35 portable tests
and 13 instrument mutants pass locally. The four additional mutants exercise
model propagation at its three boundaries and RPC-method separation. These
are instrument proofs, not native authentication evidence. PR #49 carries the
final exact-head gate and independent review; these earlier runs do not
substitute for that gate.

The independent review of `7df6f8d` caught that lifetime attribution error:
the assertions and evidence followed explicit `close()` calls, but this
record credited disposal to the ending itself. The correction measures open
acquisitions and a present workspace before cleanup, then closed acquisitions
and removed workspace after cleanup. Evidence names both phases explicitly;
no new event-driven disposal mechanism or native eligibility is invented to
satisfy an overclaim. PR #49's confirming review covered `7bbd807`; it merged
as `746af92` with a byte-identical tree.

## Controlled catalog experiment (PR #50)

The owner authorized this bounded follow-up after PR #49. The hypothesis was
specific: use the documented startup `model_catalog_json` override to remove
model-selected native tool metadata without changing the binary, selected
model names, instructions, or the worker boundary. The
[configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
establishes the setting, not its adequacy as an authority boundary.

CI downloads the exact tagged catalog identified above and verifies its hash
before entering the offline lab. One test-only transformation preserves every
entry and field except these selectors on `gpt-5.5` and `gpt-5.6-sol`:
`apply_patch_tool_type = null`, `tool_mode = "direct"`, and
`multi_agent_version = null`. The existing false feature flags remain in place.
The other model entries are unchanged, not qualified or silently removed.
No fallback model is substituted for either selected name.

The unchanged override is a positive control: it must reproduce the bundled
catalog's tools and native patch writes. Its reserialized bytes have SHA-256
`a5615a518d5c17d195ef62502671f797bb38860a27e180457e7557fb64f41647`.
The restricted override's bytes have SHA-256
`4f22dc85ec6e08bddd3b4e793601bf4298cd3d2c869e3a0f77c4ef2b55ca246d`.
These identify submitted configuration, not an attested effective policy.

The first native run, on `f0746dc`, exposed two incorrect instrument assumptions:
unsupported free-form calls say `unsupported custom tool call`, and Sol's
direct tools still travel in `additional_tools` under a `functions` namespace.
The downloaded artifact proved that this was no longer CodeMode: there was
no `exec`, `wait`, or collaboration namespace, and no native patch write.
The corrected assertions preserve this wire distinction rather than flattening
it into the other model's ordinary `tools` field.

| Restricted profile | Observed tools | Forced patch |
| --- | --- | --- |
| `gpt-5.5` | Question and contained worker, plus image reader only in the enabled control | Refused; no fixture written |
| `gpt-5.6-sol` | Same operations inside `functions`, without CodeMode or collaboration | Refused; no fixture written |

The contained READ callback still succeeds for both profiles. Disabled images
remain refused; enabled images still export the canary and are therefore only
a negative control, never an eligible configuration. The three RPC-name probes
retain their exact refusal. These results close the named patch and published
model-dependent surface gaps for this catalog recipe, not complete mediation
for all settings, tools, models, or startup paths.

### Literal driver death and acquisition disposal

The new child-interpreter fixture uses the same pinned native binary and
restricted catalog, plus the existing `RecordedExecutorProvider`, workspace
provider, and Linux launcher. It reports the fixture lease rows before
materialization, then the native PID immediately after spawn. The active-worker
case emits a separate report after
the contained WRITE worker has written a heartbeat; the before-worker case
never starts that worker. Killing the Python driver with SIGKILL bypasses its
cleanup. Before any test cleanup or recovery call, the native PID stops
executing and the heartbeat stops. PID start time distinguishes the observed
process from a reused PID; a zombie counts as non-executing, not reaped.

The acquisitions remain open and the workspace remains present after death.
Explicit successor `reconcile` calls close both old acquisitions and remove
their payloads through the existing closure law. A second interpreter uses a
fresh home and epoch and completes one new native invocation; its normal
owner cleanup closes and disposes its own acquisitions. Failure cleanup is
separate and never credited as death or recovery evidence.

This is a lease-level composition proof. The stale rows are serialized test
fixtures, **not** rows recovered from SQLite by RunHost. The probe neither
resumes a native conversation nor proves cleanup of the native home, all native
descendants, credential revocation, or response-loss/restart under the complete
durable run lifecycle. Worker PID-namespace ownership remains the production
launcher's proof, not a new claim about the native harness's process group.

Independent review caught two failure-path defects in this instrument. The
parent originally learned the native PID only after the worker heartbeat,
leaving earlier failures without that cleanup target. It now receives a
separate process-start event immediately, with a before-worker stall regression.
Unconditional in-process reconciliation could also wait forever on a stuck
guard. Both measured recovery and failure cleanup now run the existing
reconciliation calls in a disposable interpreter with a five-second deadline;
the parent kills that interpreter on timeout. A deliberately held guard pins
the bound. Cleanup errors are attached to the original failure rather than
replacing it. This is lab containment of the test's failure path, not a new
production recovery service or permission to dispose an active resource.

The confirming review found that the fresh invocation still used the old late
reporting path. Both invocations now use one test-local start/cleanup law,
including failure cleanup of their own epoch's rows; a stalled successor pins
that case. Native PID cleanup tolerates exit between inspection and kill and
preserves other cleanup errors alongside the original failure. Portable tests
and mutations pin that exit race and refusal to kill a reused PID. The record
also distinguishes the early process-start report from the later heartbeat
report, rather than attributing worker activity to both. A final review extended
that same enrollment law to pre-spawn materialization: lease rows must reach
the parent before population can block. The kill-during-materialization case
proves closure and disposal without inventing a native PID or worker activity.

The next confirming pass found a narrower observation race: file creation
preceded the worker's first heartbeat write. The active report now waits for
nonempty bytes, not existence. A deterministic portable regression steps
through missing, empty, and written states; restoring existence-only polling
fails it. The parent's later read is not substituted for that event's evidence.

The corrected `3acd4bc` native step passed all 77 cases and 18 portable
instrument mutants. Additional missing/malformed-catalog and removed-tool
direct-call controls follow on the same PR. Its exact final head must pass
the complete CI/native gates and independent review; an earlier successful
step is not substituted for that gate.

### Decision boundary

The catalog hypothesis has a supported positive result at its stated scope.
It does not qualify a credential-owning harness or supersede ADR 0018. The
remaining combined proof must include controlled startup/configuration sources,
native process/home ownership through journal-driven death and restart, and
actual authority revocation. No production adapter, profile availability,
login, gateway, or billing change was made. The
[authentication assessment](../../designs/EXECUTOR_AUTHENTICATION.md#controlled-catalog-follow-up-pr-50)
and issue #38 retain those gates; Pi and OpenRouter remain behind their own
qualification and authentication prerequisites.
