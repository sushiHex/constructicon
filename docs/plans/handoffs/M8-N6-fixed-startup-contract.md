# M8 N6 — proposed finite Claude startup contract

Proposed source-qualified recipe for [#175](https://github.com/sushiHex/constructicon/issues/175),
under [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md).
**Independently source-reviewed for credential-free READ implementation.**
This document does not authorize live execution. It supplements the unchanged
[N6c state review](M8-N6c-READ-state-review.md), not its replacement.
Production availability and Claude qualification remain false.

## Evidence and decision boundary

The inspected pin is CLI 2.1.296 / SDK 0.3.296. Linux member SHA-256 is
`24972e3bc859fab2b46ed4c1e51f7d6130f06d3bd550811a114640de3370d0de`;
SDK declarations SHA-256 is
`fc2866dfe2c01468edb19b1d94f26156bfacecdf1e7f1452b276ed2f8cc0b08f`.
`B@` denotes a zero-based native-member byte offset; `D:` a declaration line.
Inspection read bytes only. No vendor process, account, credential or model
was used. The byoc behavior below is pinned-source evidence, not a claim of
documented generic-SDK support or operator approval of this recipe.

PR #273 supplies a standalone fake-only no-further-exec feasibility proof.
It does not supply the production launcher transition, Claude store layout,
vendor TLS conformance, or this startup contract. An accepting fake may prove
the transaction after source review; it cannot mint those production facts.

## One fixed launch and source boundary

Use ordinary fresh headless stream-json input/output, safe mode, explicit
empty `--tools`, exact model/effort, and no positional prompt. Omit bare mode,
resume/continue/fork/teleport, parked claim, remote SDK URL, attached machines,
plugins, hook callbacks, structured-output schema and reconnect conveniences.
No CLI or initialize option may add these surfaces later.
Safe mode is active before preAction: Cr reads raw argv before `--`,
B@207257643; the action's later SAFE_MODE environment write is not its origin.

The sole user frame sets `client_composed: true`: TaskSpec instructions are
assembled content, not interactive CLI commands. The declared literal-true
field (D:6363-6365; native schema B@208203950) sets `skipSlashCommands` at
B@233760696 and `skipAttachments` through ry at B@233152685. Headless dispatch
maps the latter to `"mentions"`, B@233442534. Cn B@224403156 excludes slash
dispatch and the typed-mention expansion path. Ambient context can still be
attached later through sr/gle(null), B@224402100; this is not an all-context
suppression claim. Bridge and scheduled-origin overrides are excluded by the
fixed ordinary user envelope. Prompt hooks, tool permissions and between-tool
context retain their existing restrictions. No caller may opt this field out
or add origin/permission fields to the generated frame. Focused independent
source review confirmed this narrow command/mention exclusion.

Use a fresh process and disposable native state with no inherited home,
profiles, global configuration, gateway record, transcript or project files.
The native zone has no workspace. Its writable disposable state is distinct
from immutable policy files and ancestors; the vendor store is the only
persistent native-write exception. Bindings must prevent alias/symlink/rename
substitution, not merely assert an empty path at construction.

Immutable admin inputs contain no nonremote policy helper or MDM source.
Use an immutable empty enterprise managed-MCP file and immutable admin policy
with `forceRemoteSettingsRefresh: true` and
`deniedMcpServers: [{serverUrl: "*"}]`. Omit `--strict-mcp-config`: enterprise
configuration plus that flag refuses, B@217799919. Do not substitute parent
`managedSettings` for the admin source. Source-tier replacement by a nonremote
helper is excluded; a remote helper/static fallback retains the remote slot.

No further native execution is permitted after the initial qualified launch.
Workers execute separately under existing contained READ contracts, with no
network and a provider-minted read-only view. Native descendants cannot reach
the workspace, trusted descriptor, retained lock or policy ancestors.

## Finite initial environment

Construct an environment from an allowlist; inherit no other variables.
Supply every listed empty value as an initially present key. The initial
environment is captured before settings application, not reconstructed from
the eventual `get_settings` answer.

Fixed values:

```text
CLAUDE_CODE_ENVIRONMENT_KIND=byoc
DISABLE_GROWTHBOOK=1
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
CLAUDE_CODE_CLASSIFIER_SUMMARY=0
CLAUDE_CODE_ENABLE_REMOTE_RECAP=0
_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=0
NODE_TLS_REJECT_UNAUTHORIZED=1
CLAUDE_CODE_CERT_STORE=bundled
```

Initially empty keys:

```text
CLAUDE_CODE_SIMPLE
CLAUDE_INTERNAL_FC_OVERRIDES
CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY
CLAUDE_CODE_BYOC_ENABLE_DATADOG
ANTHROPIC_API_KEY
ANTHROPIC_AUTH_TOKEN
CLAUDE_CODE_OAUTH_TOKEN
CLAUDE_CODE_OAUTH_REFRESH_TOKEN
CLAUDE_CODE_OAUTH_SCOPES
CLAUDE_CODE_OAUTH_CLIENT_ID
AWS_BEARER_TOKEN_BEDROCK
ANTHROPIC_FOUNDRY_API_KEY
ANTHROPIC_FOUNDRY_AUTH_TOKEN
ANTHROPIC_AWS_API_KEY
CLAUDE_CODE_USE_BEDROCK
CLAUDE_CODE_USE_VERTEX
CLAUDE_CODE_USE_FOUNDRY
CLAUDE_CODE_USE_ANTHROPIC_AWS
CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD
CLAUDE_CODE_USE_MANTLE
CLAUDE_CODE_USE_GATEWAY
ANTHROPIC_BASE_URL
CLAUDE_CODE_API_BASE_URL
CLAUDE_CODE_CUSTOM_OAUTH_URL
ANTHROPIC_CUSTOM_HEADERS
ANTHROPIC_FEDERATION_RULE_ID
ANTHROPIC_ORGANIZATION_ID
ANTHROPIC_WORKSPACE_ID
ANTHROPIC_SERVICE_ACCOUNT_ID
ANTHROPIC_IDENTITY_TOKEN
ANTHROPIC_IDENTITY_TOKEN_FILE
ANTHROPIC_SCOPE
ANTHROPIC_PROFILE
CLAUDE_CODE_CLIENT_CERT
CLAUDE_CODE_CLIENT_KEY
CLAUDE_CODE_CLIENT_KEY_PASSPHRASE
NODE_EXTRA_CA_CERTS
NODE_OPTIONS
HTTP_PROXY
HTTPS_PROXY
ALL_PROXY
NO_PROXY
CLAUDE_CODE_HTTP_PROXY
CLAUDE_CODE_HTTPS_PROXY
```

Fix `HOME`, native configuration/scratch locators and `ANTHROPIC_CONFIG_DIR`
to the qualified acquisition layout; the latter contains no implicit profile.
Fix the ordinary SDK entrypoint and requested model/effort in the sealed
recipe. Do not inherit host-credential, background-auth, token-FD, remote,
bridge, claim, session-ingress, gateway-lineage or worker-epoch markers.

`byoc` selects hostOrchestrated, B@211228786. The safe applicator snapshots
initial names, B@211250305; `filterSettingsEnv` routes them through case-folded
`y`, B@211245801/B@211237006. Both applicators and Kdt's later assignment see
filtered values. V/H additionally exclude the named host/background/remote
inputs, B@211234600/B@211238000. This is **not universal env immutability**.
The process-wrapper assignment explicitly bypasses an empty wrapper value,
B@211250305; omit that marker and bound execution physically.

Auth strings parse empty as absent; provider bools are false for empty;
`_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL` and remote recap require typed `0`.
Auth selectors/cache: B@210395096/B@210424026/B@210425249. Source groups:
iq B@208758943; UF B@208764194; endpoint FF B@208762608; TLS Uc B@208767995.
Continuous exclusion prevents transient alternate-auth cache population;
restoring final values alone would not clear Gbe. A fresh native global store
must also exclude retained enterpriseGateway state: route selection consults
gateway slots before bool selectors, B@207733095. Empty provider flags alone
are insufficient. Native-runtime TLS interpretation remains qualification work.

## Readiness observations and retained state

Join the forced initial settings-loader attempt and second helper/fallback pass
in preAction, B@225714800, then final XA, B@225706334. Successful loading need
not mean a remote fetch: KA/k B@211226001 makes known Pro/Max ineligible under
this recipe's excluded profile/API alternatives. pt B@224524999 then returns
`settings:null`, `fetchSucceeded:true`, `resolution:"ineligible"`; cjt
B@224540224 accepts. These are internal source branches, not invented wire
fields or a permission to infer eligibility solely from a plan label.
Use one spawn-relative deadline shorter than the first one-hour policy poll.
Exclude remote ingress,
login/logout, settings update/reload controls and mutable local policy sources;
the deadline alone is not exclusion of event-driven reloads.

Before SDK registration and user dispatch, make correlated bare initialize,
`get_settings` and `get_hooks_listing` requests. Require bounded parsed replies,
no error/unreadable-policy result, supported subscription mode, and the sealed
model/effort. Permit Pro and Max. Expiry/no-fallback is a separate conformance
case, not something inferred from a cached mode projection or usage snapshot.

`get_settings` is declared at D:4241; native producer B@233738416/NTr
B@209450024 returns `effective`, `sources`, `applied`, optional `errors`.
For the minimal permitting fixture, each source's settings has only the fixed
policy keys above and `env`; environment keys must be a subset of this finite
protected inventory. Reject other keys rather than silently accepting helper,
hook, gateway, model, plugin or permission configuration. Compare the fixed
policy values and require no configured hooks in any source. This is a finite
source allowlist, not a claim that merged settings equal `process.env`.
Own `--model` resolves through ea/gp/sxo/lxo, B@225460773, and `--effort`
through Bit/tsn, B@211176929: these store session model-selection state,
not raw flagSettings model/effort rows. Compare emitted `applied.model` and
`applied.effort` exactly. The model's PD write is background-job-only,
B@215532127, excluded by the launch. Empty tools and safe mode similarly
change launch state/environment, not extra raw source settings.

`get_hooks_listing`, D:4085-4180 onward, reports `policyHookCount`,
`policyUnreadable`, policy/safe-mode state and listed hooks. Require
`policyHookCount == 0`, no unreadable/errors, expected safe mode, and no
unqualified listed/session hooks. Do not invent rows for retained builtins.
Its producer JLo B@233062267 uses y$t/ros B@233058412/B@214489604;
these read current settings/session entries, **not retained q4**.

Actual dispatch rQ/B B@214068947 includes q4. Fresh Hdo/QRt captures the
initial admin-policy snapshot, B@211686300/B@233925698. If the joined loader
publishes no settings, that snapshot remains the relevant one: ljt
B@224533842 calls V only for non-null settings. This covers the ineligible
Pro/Max branch and an eligible successful null-settings result. Do not require
a nonexistent notification in either case. If settings are published, V marks
KEo then notifies, B@224536717/B@209049230; headless xMe subscribes then c$t
replays an earlier notification, B@233567400/B@225747278. YEo reads that flag,
B@209049286. Replay synchronously invokes l$t -> DB, B@225746600/B@211686353,
replacing the snapshot before application-state update and sH/initialize.
The direct replay is not the broadcaster's exception-swallowing path. Thus
checked current policy and q4 agree through an initial unchanged snapshot or
publication/synchronization, not an unconditional remote-refresh/replay law.
A supplied `hooks_ok` flag or made-up eligibility/notification wire field
proves neither branch.

## Point-of-use and startup restrictions

Empty launch tools plus dispatch lookup/refusal close ordinary builtin use,
B@215150088/B@217867211/B@217868572. EndConversation is an exception;
continuous GrowthBook suppression closes fetch/disk paths, B@210266450,
and empty internal overrides prevents a separate override. No preconstructed
context or later schema/machine append is admitted. Native context usage omits
systemTools/deferredBuiltinTools, B@217714304; fixtures must preserve omission.

Wildcard MCP denial precedes managed allowance, B@217773642; all-source denials
union, B@217770045; later discovery reuses filtering, B@217788820. SDK entries
are a separate host-owned exemption. Register one exact server only after the
first gate; initialize B@233678762 supports registration before its repeated
metadata branch. Await the actual MCP handshake, not merely initialize reply.

SessionStart lacks toolUseContext, B@218541286; HTTP hooks are filtered,
B@218607800; prompt/agent hooks refuse missing context, B@218621447. Fresh
startup has no usable global MCP client. Script/command helpers meet noexec;
managed JSON cannot construct trusted callback/function objects. Retained ten
builtins require their pinned provenance/scan qualification: gKe -> kme and
tzt enforce declared calls/env writes, B@217954921/B@217437646/B@217443214.
No subprocess denial is claimed to prohibit in-process code.

Through-turn managed prompt/agent/HTTP hooks are excluded by zero policy hooks
plus the proved snapshot ordering and excluded update inputs. Contextful
UserPromptSubmit is otherwise real, B@218551221/B@223989773. Prompt helpers
use no tools; agent helpers retain the existing pool plus an internal result
tool, B@218498307/B@218509399. They are not silently covered by the
SessionStart missing-context argument. Named bootstrap Fgt/Wss/fRe guards
and local dho/selector work remain pinned qualified startup code; essential
traffic suppression is continuous, not checked only after startup.

## Transaction, receipts and remaining gates

Use N6c's monotone phases and irreversible refusal latch. Before every await,
record the operation's spent/started state; after it, recheck latch, deadline,
ownership and bytes already received. Keep one reader and account for surplus.
Spend dispatch before its sole write; spend callback ID before worker launch;
attempt each response once. Worker/EOF races cannot discard consumed bytes or
publish a callback response after observed terminal damage. Terminal checks
grant no new work; drain requires EOF and same-launch joined success.

Each acceptance receipt derives from that acquisition: sealed recipe/source
revision, correlated observations, actual handshake, one successful dispatch,
admitted READ callback or explicit zero-callback case, correlated terminal,
terminal observations, EOF, joined cleanup and final physical binding check.
No independent caller-supplied `startup_ok`/`gate_completed` is accepted.
One absolute deadline, cumulative native I/O, per-worker limits, callback count
and aggregate retention bound all work; no monetary/backend-request cap follows.

Independent source review cleared this conjunction after the correction below.
The permitting fake still needs accepting/interleaving and assertion-mutant
evidence. Physical composition must then prove noexec label/transition, narrow
opaque Claude store refresh, immutable sources/aliases, native/worker isolation,
destination-restricted opaque TLS and joined teardown with fixed nonvendor
processes. Native subscription refresh/expiry, no fallback, included-limit
refusal and deployment remain independent qualification gates. No live action
or public claim of vendor support/production availability follows here.

Review disposition: adopted the introduced unconditional-refresh/replay defect
and split the accepting source branches above. A focused independent Astra
follow-up confirmed the correction and cleared credential-free implementation.
Rejected an own-argv contradiction: model/effort use session state, as traced
above. Rejected a categorical ADR objection to source-qualified byoc: ADR 0021
requires supported subscription authentication and qualified fixed controls,
not public documentation for every flag; source qualification still does not
establish vendor support or production conformance.
