# M8 native mediation: credential-free Linux experiment

Status: bounded investigation under
[#37](https://github.com/sushiHex/constructicon/issues/37), 2026-09-10.
Not a successor ADR, production adapter, subscription proof, or live profile.
Base: `d94a47931d63b3e59de72450bb8e794178b6bad4`; work in
[PR #48](https://github.com/sushiHex/constructicon/pull/48).

## Result and decision boundary

An unmodified Linux Codex CLI can complete a credential-free turn against a
local fake Responses provider and dispatch its experimental dynamic tool to
Constructicon's existing contained worker. That closes the earlier uncertainty
about whether an offline integration path exists. It does not prove complete
mediation: the tested configuration still advertises a native `view_image`
reader, besides `request_user_input` and the supplied `contained_python` tool.

The image probe goes further than advertisement: `view_image` reads a valid
PNG from the native harness's private home and sends those exact bytes to the
fake provider, with no dynamic callback or contained-worker invocation. That
file is outside the acquired workspace. It is a harmless fixture, not a real
secret, but it refutes the proposed exclusive worker mediation for this recipe.
The regression deliberately passes when it reproduces that negative result;
green investigation CI is not green native-authentication eligibility.

The tested `exec_command` attempt is refused by the native router, creates no
harness-home canary, and never reaches the supplied worker. Disabling this
execution path does not disable the image reader. This result does not judge
every other configuration recipe or establish a provider-wide impossibility.

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
inferring them from configuration flags. Generated `ClientRequest` metadata
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
impossibility result. Further native investigation would need to close the
remaining model-reader and startup/extension surfaces and prove lifecycle
ownership before a successor design could be accepted.

The API/cloud gateway route remains available as an explicit alternative, but
no actual deployment or separately billed route has been selected. Slice E
cannot claim deployed conformance from this loopback fake. Steps beyond this
boundary need the missing decision, not another speculative kernel interface.
The [OpenRouter reuse assessment](../../designs/OPENROUTER.md) likewise changes
no authentication authority or M8 scope.

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
The explicit image/exec assertions and strengthened worker assertions added
after that observation must pass again on the final PR head. PR #48 carries
the final-head gate/review evidence; this earlier run is not substituted for it.
