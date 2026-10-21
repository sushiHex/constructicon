# M8 N6 — proposed native composition boundary

Proposed next slice for [#175](https://github.com/sushiHex/constructicon/issues/175),
under [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md).
**Design and source evidence only; not approved or native-qualified.**
Production availability and Claude qualification remain false. This document
authorizes no vendor process, account, credential, VM, model call or live
procedure. It creates no durable authority, new provider or availability latch.

The [fixed startup contract](M8-N6-fixed-startup-contract.md),
[READ state review](M8-N6c-READ-state-review.md) and
[standalone execution-denial proof](M8-N6-execution-denial-proof.md) remain
separate evidence. Successful fake transcripts and a contained file reader do
not establish that their physical native composition exists.

## Proposed bounded implementation

Reuse `LinuxLauncher.exchange`, `ProcessIO`, the existing supervisors, cumulative
I/O bounds and joined teardown. Compose `claude_read.py:run_read_transaction`
with `claude_read_worker.py:ClaudeReadWorker`. Do not introduce another process
owner, scheduler, workflow representation or completion-level provider seam.

Add one fixed Claude native recipe beside the existing Codex native recipe.
These two concrete recipes would justify shared launch mechanics, rather than
a caller-authored mount catalogue, environment framework or policy plugin.
Each recipe fixes its executable, environment, layout, policy inputs
and accepted AppArmor labels. Their content and implementation belong in the
launch identity. Model and effort remain sealed explicit selections.

`linux.py:NativeStoreMount`, `NativeLayout` and `NativeVendor` currently encode
Codex assumptions: `.codex`, `config.toml`, `auth.json`, environments and a model
catalog. Reinterpreting those fields as Claude inputs would hide a different
contract. The Claude branch needs its own finite layout and artifact checks;
any shared mechanics must preserve existing Codex and worker refusal paths.

The native zone receives no workspace. Its one admitted callback invokes the
existing fixed READ worker through a separately assembled launcher with no
vendor, native store or egress mount. The worker keeps `owned_view`, `use()`
and closure/control checks; the workspace remains read-only. Native descendants
receive neither acquisition guards nor the trusted controller's descriptors.

## Execution transition, not a replacement boundary

The standalone noexec profile deliberately permits broad file and socket I/O.
It proves execution denial, not filesystem or network isolation. It must not
replace the production namespace/mount boundary or be called a native policy.

The transition must occur on the final fixed native executable. The current
`_supervisor.py:supervise_namespace` first starts trusted Python namespace PID 1,
then starts the payload. An egress bridge additionally creates its forwarder
before replacing itself with the vendor command. Applying noexec to bubblewrap's
first executable would prevent this trusted bootstrap from completing.

Use a separately identified fixed native policy/recipe that retains existing
confinement and `no_new_privs` through the final transition. Its exact kernel
transition syntax and labels require proof; do not assume the standalone `px`
rule composes unchanged with the existing stacked profile. There is no missing
target fallback, inherited-execution fallback or unconfined recovery path.

After that transition, deny subsequent executable launches by the native process
and its descendants, including self, shell and descriptor routes. Protect trusted
PID 1 and any pre-existing bridge forwarder from native ptrace/control paths.
The worker uses its separate existing policy and may execute its fixed reader.
Noexec does not stop in-process computation, JavaScript, libraries or Bun workers;
the source-qualified settings/hooks/tool restrictions remain necessary.

`linux.py:probe` currently expects the generic enforcing label. The new native
recipe needs affirmative recipe-specific prerequisite evidence, while retaining
the existing mount, namespace, capability, descriptor and reaper checks.
Qualification must also observe the actual final process's enforcing label
through trusted supervision. A separate generic probe or a label reported by
native stdout is not independent evidence of that transition.

## Proxy candidate: an explicit successor recipe

The current `claude_startup.py:fixed_environment()` keeps `HTTPS_PROXY` empty.
The existing `_egress_bridge.py:environment` sets it to the fixed constant
`http://127.0.0.1:18080` before native exec. These are different initial recipes.
Adopting that constant needs an explicit source-reviewed revision; it must not
silently be described as the currently reviewed contract.

The following observations use CLI **2.1.296** / SDK **0.3.296**. `B@` denotes
a zero-based byte offset in the inspected Linux member, SHA-256
`24972e3bc859fab2b46ed4c1e51f7d6130f06d3bd550811a114640de3370d0de`.
Inspection read source bytes only; none of these observations is a live result.

- `jz` chooses the first truthy value in `https_proxy`, `HTTPS_PROXY`,
  `http_proxy`, `HTTP_PROXY`, B@207822167/B@207822230; `cf` validates a URL with
  a host, B@207822750. With cleared inheritance and the other proxy entries
  empty, the exact bridge constant wins on this path.
- The inspected native occurrences of `CLAUDE_CODE_HTTPS_PROXY` and
  `CLAUDE_CODE_HTTP_PROXY`, B@225797555/B@225797581, are recognized-name telemetry
  entries, not inputs to that selector. Their empty values do not override it.
- `mCr`, `PUe`, `ly`, B@207822933/B@207823023/B@207823113, process exclusions.
  Empty `NO_PROXY` and absent lowercase `no_proxy` supply no exclusion there.
  The byoc filter case-folds protected initial names, B@211237006; its initial
  snapshot, B@211250305, protects a nonempty proxy value as well as an empty one.
- The model-client construction supplies `na(forAnthropicAPI, url)`,
  B@211571707; `na` applies the selected proxy, B@207826264. `ES` configures
  Axios and Undici, B@207826957. The bundled proxy agent dials the proxy and
  sends CONNECT for the destination, B@207743889/B@207744346. A nonempty proxy
  also excludes the startup direct preconnect, B@224552720.

This is a compatibility candidate, not proof that every connection is proxied.
`jv` explicitly bypasses loopback destinations, B@207824467, using `Xk`,
B@207792344. Socket-path and explicit transport paths also exist. The fixed
environment/configuration excludes those alternate inputs; the route-less
network namespace and sealed relay remain the physical boundary. Native TLS,
all necessary destination routes and actual Bun transport behavior remain
qualification work. Do not add the vendor's separate remote agent-proxy feature.

## Opaque credential persistence candidate

ADR 0021 pins the qualified store root/lock, not the credential inode. The
existing Codex single-file mount is implementation-specific, not a requirement
that every native client rewrite its credentials in place.

At this pin, configuration root `ve` uses `CLAUDE_CONFIG_DIR` when defined,
otherwise `HOME/.claude`, B@207256450. Secure root `Dw`, B@209490609, uses
`CLAUDE_SECURESTORAGE_CONFIG_DIR` when defined; its empty value selects
`HOME/.claude`, while omission uses `ve()`. Keep these locators explicit and
distinct from immutable admin inputs and their ancestors.

The plaintext backend appends `.credentials.json`, B@209495802; Linux `Jn`
selects that backend, B@209499823. The inspected ordinary backend factory
supplies no alternate backend, B@220397323. Its write requests mode `0600`,
then explicitly chmods the destination to `0600`, B@209496449. Directory
creation is recursive without an explicit restrictive mode at that call;
the assembly must establish ownership, modes and stable ancestors itself.

`En` delegates to `Ape`, B@207937915/B@207937978: normally create a sibling
`<target>.tmp.<8 hex digits>` and rename it over the destination. The rename
fallback explicitly includes `EBUSY`, B@207932847. That arm opens the existing
target with no-follow/nonblocking flags, checks its type, truncates, writes and
applies the mode. Atomic rename alone therefore does not establish that a
single persistent file mount is incompatible.

However, staging creation failure does not automatically select in-place
writing. The optional `inPlaceOnTempCreateRefused` exception is not passed by
the credential writer. A writable disposable parent is required for this
candidate, even if only the credential file is persistent. Secure mutations
also create `.storage-write.lock`, B@209494398. Refresh creates
`.oauth_refresh.lock`, the legacy `realpath(directory)+".lock"` sibling and
`.oauth_refresh.lock.owner`, B@210434636/B@210435062/B@209802221.
The finite layout must therefore provide a disposable writable containing
directory for that legacy sibling, not only a writable secure-storage directory.
Neither directory may contain or parent immutable admin inputs.

Refresh `Hl` reloads/checks credentials, locks, calls refresh and saves through
compare-and-swap mutation, B@210437575/B@210420192. Its `"refreshed"` disposition
is not affirmative persistence: the inspected path ignores the save function's
`"save_failed"` disposition when returning it. Successful persistence must be
observed separately. The backend's general removal arm uses unlink, which
also cannot be assumed to work against a file mount.

The narrow candidate is one opaque persistent credential file in a writable
disposable secure-storage directory. Qualify actual mount-point `EBUSY`, fallback
write/chmod, later reload, torn-write recovery and joins before selecting it.
A dedicated persistent directory remains an alternative requiring its own
qualified finite layout and persistence-exclusion proof; source inspection has
not established that broader mount as necessary. Read or hash no real secrets
to investigate either candidate.

## Await boundaries and affirmative evidence

One acquisition deadline starts before assembly work; no worker or prerequisite
probe renews it. Recheck ownership, refusal, remaining time and received bytes
after each await. Retain the sole reader and join every owned task.

| Resumed boundary | State that may already exist | Positive fact required before advancing |
| --- | --- | --- |
| Acquire guards/open store | Closure, replacement, cancellation | Same owned acquisition, held lock and checked binding; no exposure yet. |
| Artifact/probe work | Drift, absent profile, deadline expiry | Exact admitted artifacts, actual enforcing labels and successful prerequisite probe. |
| Mount/bootstrap/final exec | Partial setup, dead forwarder, failed transition | Fixed mounts/environment; affirmative readiness; final native enforcing label. |
| Startup controls/handshake | Surplus frames, late callbacks, partial writes | Same-exchange correlated observations and complete actual MCP handshake. |
| Sole user write | Prefix or full delivery despite interruption | Dispatch spent before await; successful complete write, never a retry. |
| READ worker/race | Native EOF/terminal/damage and worker completion together | Admitted call spent before launch; native race accounted; worker joined under its guard. |
| Response/result/postchecks | Uncertain response write, mode drift, pending work | One response attempt; bound terminal correlation; fresh terminal observations. |
| Drain/cleanup | Extra frames, controller death, surviving descendants | Actual EOF, joined native/worker/forwarder tree, cleanup and final binding check. |

## Proof stages and remaining gates

The proposed PR first needs source/design review of the finite recipe, followed
by fake-only physical proof through the actual launcher path. A fixed nonvendor
peer must permit the full transaction, including READ and zero-callback cases;
its Pro/Max-shaped reports are fake inputs, not subscription evidence.

Measure native and fork-child labels, all execution-denial routes, missing-target
refusal and positive unconstrained execution controls. Prove immutable policy,
native workspace/guard absence, worker read-only/network exclusion, opaque fake
credential persistence and forbidden sibling persistence. Bind I/O, callback,
retention and deadline limits with inputs that reach those limits.

Inject transition/bootstrap failures, uncertain writes, simultaneous worker/EOF,
postcheck redelivery, timeout, repeated cancellation and controller death. Require
affirmative joins and lock retention through surviving descendants. Add assertion-
killed guard mutants; written or skipped Linux tests are not measured proof.

These source and fake physical gates do not qualify vendor subscription startup,
TLS/destinations, refresh/expiry, persisted credentials, no fallback, included-
limit refusal or deployment. Those require separate authorization and evidence.
