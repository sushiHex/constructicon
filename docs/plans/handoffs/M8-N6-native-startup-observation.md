# M8 N6 — credential-free native startup observation

Implementation design for [#175](https://github.com/sushiHex/constructicon/issues/175)
under [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md).
The owner authorized the next Claude-only wave after PR #277. This slice is
the first gate: a pinned, unmodified CLI in a disposable hosted Linux runner,
without credentials, a provider route, a user message or a READ worker.
It does not authorize private-host installation or attended authentication.

## Evidence sought, not an availability gate

PR #277 established the launcher/native/worker composition using a compiled
nonvendor peer. Run the real CLI through that same native recipe and require
an affirmative bounded startup response, stdin closure, EOF and joined
teardown. The credential file starts empty and is disposable. There is no
inherited home, account configuration or provider connection.

Keep the pinned Linux member from [N6a](M8-N6a-state-review.md): version
2.1.296, 257068216 bytes, SHA-256
`24972e3bc859fab2b46ed4c1e51f7d6130f06d3bd550811a114640de3370d0de`.
Verify the downloaded archive and selected regular member before installation;
do not execute an installer, package script or version command. The existing
launcher independently verifies the installed tree before native execution.

The first hosted observation exposed an incomplete runtime closure: static ELF
inspection confirms this member also needs `librt.so.1`, `libpthread.so.0` and
`libdl.so.2`, absent from the Python/Git fixture. Provision a separate fresh
diagnostic runtime with those three fixed, custody-checked system libraries,
freeze it and record its own digest. Preserve the original fixture and Codex
closure. No loader trace of the vendor, executable permission expansion or
broader host mount is needed to supply these declared dependencies.

The test sends only one correlated bare initialize request. It registers no
SDK server and writes no user message. Subscription admission must refuse the
empty-store observation. A mode mismatch alone is insufficient diagnostic
success: the probe must also establish the exact supported unauthenticated
projection, version, idle session, correlation and empty pending requests.
Production initialization and READ gates stay unchanged.

The expected account projection is exactly
`{"apiProvider":"firstParty","tokenSource":"none"}`. In the pinned member,
`vl` at B@210395964 returns the no-token source, `xRe` at B@210449537 keeps
that source, and `Vg` at B@233772528 serializes it with the provider. The
initialize `models` field is a catalog, not a selected-model observation.
This source expectation is not an observed startup result: the real process
may instead refuse before a control response, which fails this proof.

No raw vendor response, stderr, account metadata or prompt enters evidence.
Publish bounded dispositions and counts, artifact/recipe identities and
explicit false subscription-qualified/production-available fields. A timeout,
missing response, malformed frame or failed cleanup is not a successful probe.
Failure may identify a concrete compatibility defect; it never authorizes a
broader mount, network route or weakened startup predicate.

## One owner, no external destination

Reuse `LinuxLauncher.exchange`, the existing final native transition, sealed
admin layout, retained fake-store lock and cumulative process limits. The
native process has no workspace. Its proxy endpoint is backed by a local
deny-only peer with no upstream connection operation; any attempted proxy
traffic is bounded, refused and counted. Do not infer absence of attempts
from an empty fault list or describe this as TLS/destination qualification.
The route-less native namespace remains the network boundary.

The observation is a diagnostic test, not another provider or durable command
family. Do not generalize the Codex qualification assembly or reinterpret the
existing `ClaudeInitialization` success latch. That callback intentionally
requires a subscription mode match and is not an empty-store probe.

## Async-resume and crash review

| Boundary | Already possible on resumption | Required fact |
| --- | --- | --- |
| Provisioning | Partial tree or failed digest check | No fixture report until all checked immutable inputs exist; fresh-only target. |
| Prerequisite await | Deadline expiry, changed binding, failed policy | Existing launcher rechecks the pinned binding and refuses before native spawn. |
| Initialize write | Partial/full delivery, EOF or output buffered | Spend the sole request before await; never retry it. |
| Response read | Multiple frames, oversized partial frame, early exit | Bound each read and total retention; correlate exactly one complete frame. |
| Stdin closure | Response refusal, cancellation or late bytes | No later request; close once and retain refusal rather than resetting state. |
| Tail read | Surplus output or no EOF | Require actual EOF under the same deadline; surplus cannot become success. |
| Exchange return/error | Joined failure, binding change | Check terminal binding after joined outcomes; primary cancellation/fatal errors remain primary. |
| Peer disposal | Accepted connection or blocked read | Close and join every local peer task; no detached observer survives the probe. |

Orderly stdin closure follows a completed diagnostic response even when that
response refuses the expected mode. After I/O failure or cancellation, do not
start an unbounded second protocol operation in a `finally`: the existing
launcher owns termination and joins. A cancellation already delivered by the
deadline does not schedule another cancellation for a later blocking close.

The diagnostic result is built only after protocol, process and cleanup facts
are affirmatively established. No mutable public `passed` latch, timeout
extension, automatic retry or fallback recipe is introduced.

## Tests and sequencing

First test the accepting no-auth transcript, a subscription-shaped transcript
that must not count as this diagnostic, malformed/cross-request/pending/extra
records, input/output bounds, EOF/close failures and cancellation. Mutants must
fail assertions, not merely error. Run physical accepting and refusing fixture
cases before crediting a real pinned CLI observation. Hosted execution must be
mandatory when selected; a skipped test is not evidence.

After this gate, separately design and qualify attended subscription login:
private owner input, maintenance fencing, persistence and fresh-process reload,
permitted account/configuration traffic and returned-scope behavior. Then
authenticated startup and one bounded subscription READ remain separate gates.
The source-observed reduced-scope API-key branch cannot be dismissed merely
because the command includes `--claudeai`. No login or live READ is performed
by this diagnostic slice.
