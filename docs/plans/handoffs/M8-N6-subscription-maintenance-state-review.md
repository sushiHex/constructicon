# Claude subscription maintenance without API-key creation

Design draft for [#175](https://github.com/sushiHex/constructicon/issues/175),
under [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md).
The owner prohibits API-key creation, including a fallback later rejected by a
mode check. This draft proposes a bounded, vendor-owned route; it establishes
neither a successful login nor subscription qualification. No live procedure
is authorized by this document.

## The boundary and the remaining uncertainty

The existing pinned native startup now has credential-free physical evidence
in PR #279. That is not evidence for login, stored credentials, refresh,
authenticated startup or a model turn.

Ordinary `auth login --claudeai` is insufficient: the pinned client can create
an API key if the returned OAuth scopes lack inference. Rejecting its eventual
mode would occur after the forbidden account mutation. Instead, the proposed
login acquisition excludes the entire `api.anthropic.com` destination.
The existing CONNECT/SNI relay refuses an unlisted destination before dialing;
there is no URL-path inspection, TLS interception or rewritten OAuth request.

That exclusion also prevents the client's subscription-profile lookup. The
client can persist OAuth credentials with unknown subscription metadata. A
later ordinary refresh can restore that metadata, but startup launches refresh
asynchronously. Neither a delay nor an empty fault list proves it completed.
This route therefore permits a bounded failure: if positive mode and reload
evidence do not arrive, the store stays withdrawn and no model request follows.

## Pinned source evidence

The inspected client is Claude Code **2.1.296**, Linux member SHA-256
`24972e3bc859fab2b46ed4c1e51f7d6130f06d3bd550811a114640de3370d0de`.
`B@` means a zero-based byte offset in that member. These are static source
observations, not live behavior proofs.

| Fact | Source anchor |
| --- | --- |
| Login's reduced-scope branch invokes API-key creation | `sje`, B@233065981; `tho`, B@210471115 |
| Failed profile lookup can leave subscription metadata null | `XYe`, B@210350752; `vwr`, B@210472131 |
| Login can persist an inference-scoped token independently of profile success | `xvr`, B@210421729 |
| Ordinary refresh waits for natural expiry eligibility, not missing subscription metadata | `Hl`, B@210437575 |
| Refresh can obtain subscription metadata and persist it through the vendor's CAS | `vbe`, B@210467304; `Cvr`, B@210420192 |
| Shared initialization starts refresh work asynchronously | B@224555498 |
| Repeated bare initialization reprojects account state | `YL`, B@233767913; `Vg`, B@233772528; `xRe`, B@210449537 |
| Subscription type comes from native token metadata | `kr`, B@210444781 |

The inspected refresh path does not invoke `sje` or `tho`. Later phases must
never send the explicit login/authenticate operations that reach that path.
This is a pinned reachability claim, not a promise about future client versions.

No supported immediate force-refresh command was established. `auth status`
observes rather than repairs metadata. The opposite-direction
`oauth_token_refresh` callback asks an SDK host for an external token; it is not
an admissible refresh request. `setup-token` does not persist the credential and
would require external token supply, which ADR 0021 excludes. Do not fabricate
expiry, provoke a synthetic 401, parse credentials or modify their contents.

## Finite login recipe

The proposed fixed argv is
`/opt/claude/claude --safe-mode auth login --claudeai`. Root positional-option
handling (B@225713273), the boolean `--safe-mode` option (B@225720659), and the
auth/login registration (B@225808900 onward) support this order. The safe-mode
predicate reads the literal argv flag before the main action (B@207257643).
There is no arbitrary-argument option, print prompt, model selection or tool
registration in this login recipe.

Reuse `native_environment()` with cleared inheritance, fixed locators, proxy,
TLS and nonessential-traffic controls. Its login-only sealed policy is
`fixed_policy()` plus literal `forceLoginMethod: "claudeai"`. Keep
`forceRemoteSettingsRefresh: true`; do not weaken production policy to make
login work. The auth-recovery pre-action skips the awaited required-refresh
branch (B@225716387/B@225716789), but may still start background configuration
traffic. This is not evidence of no attempted settings traffic.

Native login egress admits only `platform.claude.com:443`, the pinned token
endpoint. The browser authorization URL is an operator-browser destination,
not grounds to admit `claude.com` to the native zone. All other destinations,
including `api.anthropic.com`, remain denied. The relay does not inspect paths;
denied profile/background calls cannot justify expanding this policy. A denied
connection is enforcement evidence, not proof of mode or login success.

Later refresh/reload policies admit only separately qualified token/profile
destinations, `platform.claude.com:443` and `api.anthropic.com:443`, with exact
globally routable address pins and the existing resolver/TLS restrictions.
The process recipe in those phases cannot select login or authenticate. Every
phase's argv, sealed policy and egress selection participate in its identity;
there is no mutable in-process switch from restricted login egress to broader
refresh egress. Numeric transport budgets and actual address pins belong to
the exact reviewed host procedure, not source-inferred successful connectivity.

Implementation adds a closed login-recipe selection pairing only the fixed
login argv with its login-only sealed policy. It preserves the existing
stream-JSON recipe and READ admission; arbitrary commands and caller-supplied
policies remain inadmissible.

## One store law and three separate native processes

Use the existing root-held `operator_store maintain` custody and durable
withdrawal. The service lane proves the inherited lock with
`inherit_maintenance`; it does not reacquire a free lock as evidence of custody.
Reuse the single opaque credential file, sealed settings, fixed native tree,
existing launcher, supervisors and acquisition-scoped egress. No new store,
process owner, provider abstraction or authentication service is needed.

1. **Attended login.** One fixed `auth login --claudeai` recipe, no repository
   workspace, no model input, no tools, no ambient environment/desktop/helper
   credentials and no browser helper execution. The selected store remains
   opaque vendor-owned state; do not truncate or clear it to obtain a fresh
   login premise. Its finite egress policy omits `api.anthropic.com`.
   Only the vendor interprets the operator's authorization response. Join this
   native process and revoke its egress before any later phase can begin.
   Clean exit is a lifecycle fact, not a login or persistence verdict.
2. **Later refresh observation.** A separate maintenance acquisition, possibly
   after natural expiry, uses the fixed stream-JSON native recipe and separately
   qualified refresh/profile destinations. It sends no login operation, user
   message or SDK-tool registration. A small fixed number of serial bare
   initialization requests may observe changing mode under one absolute
   lifetime. Each request spends its own identity and input allowance before
   writing. Unknown mode never becomes qualified merely because it was observed
   several times. The recipe does not wait indefinitely or renew its deadline.
3. **Fresh-process reload.** After joined teardown, reopen the opaque credential
   through existing custody checks and start a new process. Require a positive
   exact selected Pro/Max mode observation and joined completion again. This is
   the persistence check; a changed mtime, earlier response or vendor save
   disposition cannot replace it.

Each acquisition revalidates withdrawal and physical store identity. Do not
keep a lock or native process alive across a long natural-expiry wait. Losing
custody between sessions grants no continuity: later maintenance must establish
its own current facts. Any publication/activation remains the existing separate
generation operation after complete qualification, never a `finally` action.

The maintenance observer is separate from frozen N6b's one-request
`ClaudeInitialization`. Its finite multiple-observation contract needs review
before implementation. It cannot silently change that callback or the READ
transaction's admission predicate. A wrong provider, API-key source, injected
token source, wrong selected plan, malformed reply or pending action refuses;
it is not a transient unknown mode to retry.

For this pin, null subscription metadata can render as
`{"apiProvider":"firstParty","subscriptionType":"Claude API"}`, with optional
string `email` and `organization` fields and no token/key-source fields.
`wt` (B@210441977) tests inference scope; `Dvr` (B@210446100) maps unknown type
to that literal. This is an ambiguous **not-qualified** observation, never a
positive claim of subscription or refresh in progress. Only this exact bounded
shape may continue to the second scheduled observation. All other mode
mismatches stop immediately. Do not publish the optional account strings.

## Native framing and bounded private I/O

The real startup emitted a `system/ui_invalidate` notification. PR #279 proves
a diagnostic-only, exact-shape, count-bounded allowance; it does not extend the
production READ decoder. Maintenance and eventual READ need an explicit native
framing revision before live use. Reuse one exact classifier once two real
consumers need it; do not import a CI script into production or introduce a
generic event bus. UI records carry no authority and never count as mode,
refresh or completion evidence. Unknown records still refuse.

The login adapter forwards bounded private output to the operator, never to a
public evidence record. Authorization input is opaque, bounded, single-use and
spent before delivery. EOF, an uncertain write or cancellation never resends
it. The operator input primitive must be cancellable and joined; no blocking
input thread may retain the session after teardown. No script may unexpectedly
take over the controlling terminal. The proposed finite budgets are:

| Phase | Fixed bound |
| --- | --- |
| Login | 600-second absolute lifetime; one opaque line including LF, at most 4,096 bytes; 256 KiB native stdout |
| Refresh observation | 120-second absolute lifetime; at most two serial initialize requests; second request no earlier than 30 seconds after the first response; 8 KiB total input; 512 KiB native stdout |
| Fresh reload | 120-second absolute lifetime; one initialize request; 8 KiB total input; 512 KiB native stdout |
| Framed observations | Existing 256 KiB record ceiling; at most eight exact UI notifications across the entire process, not eight per response |

These are proposed operational limits, not vendor guarantees. A matching first
observation finishes without sending a second. The 30-second spacing is only
scheduling; it proves no refresh or persistence fact. Missing, wrong, duplicate
or partial responses are failures, not reasons to spend another request. The
second scheduled observation is allowed only after the exact not-qualified
response above. EOF, cancellation and launch/output limits always take priority.
During the spacing interval the same sole reader/parser stays owned and
bounded. It rejects malformed frames, duplicate responses and callbacks as
they are observed; it does not sleep blindly while a queue accumulates. At the
timer boundary, inspect completed reads and latched failure before spending
the next write. Cancellation joins that reader. Correlation establishes the
request identity, not physical arrival freshness in an unread OS buffer.

Stderr retains the existing launcher's bounded head/tail capture under the same
absolute lifetime; this is not a bound on all stderr bytes emitted. The current
`ProcessIO` exposes stdout only. The login URL and input prompt are stdout in
the inspected handler, so no new live stderr reader or launcher sink is needed.
Only after joined teardown may retained stderr be forwarded privately, using a
bounded cancellable write; it never enters public evidence.

The proposed private input transport is one deliberately operator-started
`ssh -T` session running exactly the reviewed fixed maintenance command, not
an interactive remote shell. The existing root helper passes only descriptors
0-2 and the retained lock to the service lane. No extra descriptor protocol,
local socket service or credential file is introduced. The operator completes
the vendor's browser flow and supplies its response directly to this private
session, never to agent chat or public logs.

This is a named attended step, not permission for automation to acquire a
terminal: all automated and diagnostic commands retain closed stdin. The exact
host procedure must make this distinction explicit and must be reviewed before
the operator starts it. The inspected `authLogin` handler at B@234955202 uses
`readline.createInterface({input: process.stdin})` without a TTY condition
(B@234957060). Its callback prints the manual URL and input prompt to
stdout (B@234957575). `IU.waitForAuthorizationCode` (B@229062501) installs its manual
resolver before invoking that callback. The operator must wait for the prompt:
pre-fed input can arrive before the resolver exists and be lost. The adapter
does not parse the URL or synthesize a response. Fake composition must exercise
this ordering before executable commands.
With configured browser and `BROWSER`, `DISPLAY`, `WAYLAND_DISPLAY` absent,
the inspected opener returns without spawning a helper (B@222639977). These
absences must be fixed launch facts, not assumptions about the operator's host.

On Linux the lane uses one event-loop reader for fd 0, accumulates at most
4,097 bytes to detect overflow, and delivers only one complete LF-terminated
line of at most 4,096 bytes. It neither interprets OAuth fields nor sends an
EOF-terminated partial line. The reader is unregistered on completion,
cancellation or native termination. Forwarding to private fd 1 and the later
retained-stderr write to fd 2 is likewise nonblocking, bounded and cancellable;
a stalled operator cannot extend the absolute lifetime or retain custody
through a blocked synchronous write. Post-join forwarding gets no renewed
deadline; exhausted time means no further output, not extended custody.
Input/output tasks are joined before the maintenance lane returns.

The login coordinator races one operator-line read against one native-stdout
pump. Observed stdout EOF or failure takes priority when both tasks are ready;
an attempted input write is spent even if its completion is uncertain. The
current `ProcessIO` exposes stdout EOF, not physical process exit. Therefore
this rule does not claim to detect an exit still hidden behind buffered output
or a blocked private sink. The shared deadline stops further work; the joined
launcher result supplies the later process fact. Deadline expiry never permits
abandoning cleanup or releasing custody before owned tasks, processes and
connections have joined. Cleanup receives no permission for further native or
operator I/O merely because joining can outlast the work deadline.

The borrowed streams must be Linux pipes or sockets with distinct backing
identities. Different descriptor numbers alone do not prove independence:
duplicates share their nonblocking flag, so restoring one could block another
operation. Admission rejects repeated `(st_dev, st_ino)` pairs before changing
flags. This deliberately also refuses separate opens of the same FIFO. The
caller lends the streams exclusively, including aliases it holds elsewhere;
the helper neither closes borrowed descriptors nor discovers outside aliases.

A dropped SSH connection is not evidence of remote cleanup. Do not advance to
another phase until remote joined termination/current custody is positively
established; any uncertain session leaves the store withdrawn.

Public reports contain finite lifecycle, custody, mode and phase verdicts plus
non-secret artifact identities. They contain no raw vendor output, input,
account identifiers, OAuth URL/code/token, credential digest or exception text.
Walk every public field in tests and check its declared bound. Preserve unknown
facts as unknown; do not name a report `login_success` on the strength of exit 0.

## Resume and crash review

| Boundary | State that may already exist | Required next fact |
| --- | --- | --- |
| Maintenance entry | Prior generation still active; owner death; stale inherited descriptor | Affirmative retained custody and durable withdrawal before any native write |
| Credential open and launch | Same-path replacement; cancellation; partial bootstrap | Checked physical file and current custody; existing pre-launch fence |
| Private input read | Operator EOF, buffered input, native exit or deadline | One bounded owned read; cancellation and observed native EOF/failure win over later delivery; unseen process exit is not inferred |
| Input write | Prefix delivered before failure | Input spent; no resend or successful-login inference |
| Login output read | Sensitive bytes, over-bound output, denied network attempt | Bounded private forwarding; no raw evidence publication |
| Login join | Credentials partly written; payload clean but persistence failed | Joined cleanup and custody check only; store remains withdrawn |
| Later maintenance entry | Boot/generation changed during natural wait | New affirmative custody; no inferred continuity or inherited availability |
| Mode request/read | Refresh incomplete; buffered stale reply; unsolicited callback | Exact correlation, pinned shape and positive selected mode; bounded observations only |
| Refresh-phase close/join | Reply observed before save; cancellation; failed persistence | No qualification until joined result and subsequent fresh-process mode |
| Fresh reload | Torn write; earlier in-memory-only success; changed binding | Checked reopened object and positive fresh mode from the new process |
| Failure or process death | Partial store mutation with no terminal report | Remain withdrawn; no automatic retry, activation or model dispatch |

## Proof sequence before an attended session

First, independently review the finite recipe, not-qualified mode shape, bounds,
private input transport and this asynchronous state machine. Then implement
fake-first through the existing launcher and store seams. Test both accepting
and refusing paths, including natural-refresh delay, no refresh, in-memory-only
mode repair, torn persistence, fresh reload, same-path replacement, input EOF,
uncertain writes, native exit while input waits, repeated cancellation and
late callbacks at every resumed boundary. Each new guard needs an
assertion-killed mutant with an input that actually reaches its bound.
Include a blocked private stdout sink, native-exit/input-ready races, callbacks
and duplicates during observation spacing, and stderr-only flooding. The last
case proves bounded retained stderr and deadline/join behavior, not a fictitious
combined-output refusal.

The Linux fake composition must prove the actual credential mount's persistence
behavior, forbidden sibling persistence, retained lock through joined cleanup,
key-creation destination refusal before any upstream dial and revocation before
phase replacement. Use synthetic credentials and controlled peers, not accounts
or vendor binaries in these new tests. A wrong-mode response must never trigger
a model message, a tool registration, another authentication operation or an
activation write.

Only a reviewed exact-head host procedure may perform attended login. It must
name the installed controller/runtime/vendor identities, private operator
transport, custody, phase budgets, stop/recovery behavior and actual egress
pins. No new R6 baseline or unrestricted destination follows from this design.
Full authenticated startup qualification remains distinct from a maintenance
mode observation. Only after that gate may the separately bounded one-READ
procedure run. A successful model response without the admitted worker/evidence
path is not the requested integration result.
