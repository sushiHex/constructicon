# M8 inert hook execution: acceptance and evidence

Status: bounded investigation authorized by the owner, 2026-09-11.
Acceptance is committed before implementation. GitHub
[#59](https://github.com/sushiHex/constructicon/issues/59) owns work state;
[#38](https://github.com/sushiHex/constructicon/issues/38) owns authentication.

Base: `489db82fdf200502956e4c54aaa2c09cede598a9`, squash merge of #58,
tree-identical to reviewed `574c424abacb1fac12b85190b47a32d1dcfcfdb9`.
That investigation proved attempted trusted hooks, not successful execution:
the minimal image lacks `/bin/sh`. Its negative control remains intact.

## Scope and source-grounded hypothesis

[ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md),
the [qualification plan](M8-native-qualification-plan.md), and the accepted
[fixture proposal](M8-provider-fixture-proposal.md) remain authoritative.
No production source, launcher policy, runtime-image asset, credential,
network/grant schema, native recovery, or additional adapter changes here.

Keep Codex 0.153.4, source
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`, the existing package/catalog
digests, and both `gpt-5.5` and `gpt-5.6-sol` profiles. The package already
contains `codex-resources/zsh/bin/zsh`. Its pinned source
[session shell selection](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/session/session.rs)
selects that asset when `features.shell_zsh_fork` is enabled; the
[hook configuration](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/session/mod.rs)
passes the session environment's shell into the hook runner.
These source observations are a hypothesis, not executable proof or a claim
that an experimental feature is stable. The release registry identifies it
as `UnderDevelopment`, default `false`, expressly not ready for external use.
It accepts the flag without a debug-build gate. Preserve any unstable-feature
warning in the native wire; schema recognition does not establish a supported
production recipe. Independent acceptance review confirmed this distinction
before the first native run. Current
[official hook guidance](https://learn.chatgpt.com/docs/hooks) provides
orientation; the pinned release and observed behavior decide this result.

Test one explicitly controlled configuration variant over the existing image.
Do not add a host shell, symlink, environment inheritance, debug override,
second owner, or general shell-selection abstraction. If the packaged asset
or supported release control cannot serve the proof, retain the exact refusal
and stop for an explicit, separately reviewed runtime proposal.

## Observable acceptance

1. For both pinned profiles and both JSON/TOML hook origins, first discover
   one inert SessionStart command without trusting it. Observe its source key,
   content hash, enablement and trust state. Trust only that exact command in
   a fresh fixture; test its explicitly disabled counterpart separately.
2. A trusted positive requires the exact public marker written by the command,
   one corresponding start/completion pair, successful completion without
   error entries, and association with the controller-observed native session.
   Discovery or ENOENT is not successful execution. Untrusted and disabled
   cases require an untouched marker and zero attempt events, including failed
   attempts. Marker absence alone cannot prove non-execution.
3. Keep full native wire records and process outcomes, two complete peer
   requests, and post-join peer errors. Require successful owned termination,
   no callback dispatch, no timeout or truncation. The same finite context and
   tool checks apply; only the explicitly selected shell label may differ.
   Do not learn expected context from the request under test. No new native
   model-callable shell tool is allowed by this fixture variant.
4. Preserve the old missing-shell regression and every existing combined,
   placement, mediation and containment gate. Add load-bearing assertion
   mutants for positive completion, negative non-attempt, native-session
   association, marker truth and exact-context selection. Inspect downloaded
   artifacts independently from those assertions on the exact reviewed head.

The release feature listing and runtime inventory must identify the effective
selection and already-packaged shell. Any unanticipated tool/context change
is a refusal to investigate, not permission to weaken the expected transcript.
The shell is a positive-control fixture ingredient, not new production
authority or a recommendation to enable hooks in a native executor.

## Decision boundary and results

Execution is not yet performed. Exact-head local verification, CI, Linux
evidence, mutation checks and independent source/artifact review are future
gates. Windows skips will not count as physical proof.

Return four distinct classes to #38: proved at this fixture's scope, refuted,
unexecuted, and blocked by a named prerequisite. Success closes this finite
hook gap only. It cannot establish authenticated/cloud controls, CLI sender
authentication, provider deployment conformance or journal-driven native
recovery. A positive combined qualification, if actually established, may
warrant a proposed successor ADR; acceptance remains the owner's decision.
A supported negative can complete #59 without qualifying native authentication.
