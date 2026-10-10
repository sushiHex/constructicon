# M8 N5: operator-requested refresh

Status: owner-approved design extension, implementation under review. The owner
approved the narrow proposal recorded on [#78](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6094638628).
Approval covers implementation and this additive procedure, not live execution.
The frozen N4/N5 plans and host runbooks retain their bytes. An exact merged
controller commit, deployment commands and new generation need separate host
authorization before this procedure can run.

## Why this extension exists

H8's three active g5 attempts passed their active checks but did not measure
refresh. Natural refresh is reachable, not scheduled: at pinned Codex
`rust-v0.160.1`, a parseable expiry governs the five-minute proactive window;
the eight-day last-refresh test is only a fallback. Neither private value was
inspected. No calendar date can supply the missing proof.

The supported `account/read` request can select `refreshToken: true`. Source at
`d27764b82f7118f674371e6d6e76271d9d606edb` establishes:

- `app-server-protocol/src/protocol/v2/account.rs:544-551` declares the managed
  refresh selector. External-token mode ignores it.
- `app-server/src/request_processors/account_processor/workspace_routing.rs:157-168`
  requests refresh, discards its outcome, then reads the account. A successful
  account response alone is not refresh evidence.
- `login/src/auth/manager.rs:2844-2881` first performs an account-guarded reload.
  An unchanged managed source reaches authority refresh regardless of expiry;
  a changed same-account source can succeed without that request.

These paths are relative to the vendor's `codex-rs/`. Source inspection and
credential-free fixtures do not qualify the private host.

## One bounded extension

`codex_lane startup --request-refresh` selects true for the existing account
request, within the existing four-method startup conversation. It requires
active custody and an expected account seal. Login and maintenance refuse the
option before evidence reservation, store access or process launch. The lower
conversation boundary independently refuses it outside startup-only mode.
The selector is a strict boolean, not a task/grant option or a model tool.
Explicit refresh also refuses the declared-denial control: that control can
accept a relay denial, whereas refresh qualification requires a clean run.

No new protocol loop, token client, credential parser, authentication broker,
store or scheduler is introduced. Normal startup and model turns still send
false. All existing account, mode, plan, routing, egress, byte, deadline,
process, lock and cleanup checks remain. An explicit request does not authorize
a thread, model turn, retry, different destination or another account.

### Requested is not measured

Default evidence retains schema 4 and its closed field sets. Explicit startup
uses schema 5 with the additional `request_refresh: true` field. This records
the selected behavior, not that a request was sent or a refresh succeeded.
Source-derived adapter/protocol revisions change; default evidence values
containing those revisions are therefore not byte-identical across controllers.

The existing measured predicate is unchanged: the same run must contain an
accepted connection to `auth.openai.com:443`, a changed credential mtime and
no startup faults. Clean startup includes the judged account and spend
readbacks, exact four methods and settled launch checks. A missing connection,
unchanged credential or failed gate remains unmeasured. Existing attribution
limits remain: this does not identify which vendor manager refreshed or prove
that the readback used the replacement credential.

Old schema-4 runbook checkers must reject explicit evidence. Never strip its
field or rewrite its version to pass one. Maintenance qualification remains
schema 4, so the current sealed-account reader stays unchanged. Explicit
active-startup evidence supplements that qualification; it does not replace
the maintenance evidence sealed into the descriptor.

## Async and failure review

Before the first await, invalid selection/custody refuses. During the account
request, notices or buffered responses can already refuse the conversation;
the existing correlation and account-coherence checks continue to apply.
A response can be clean while vendor refresh failed or only reloaded state.
After the response, the existing spend gate and drain still run. Only after
launch teardown returns are relay, credential and process facts combined.

Cancellation, partial writes, failed cleanup or failed evidence publication
cannot print a passing operator verdict. A successful explicit request with
missing measurement is an unmeasured result, never permission to repeat it.
There is no new latch, retry loop or durable refresh claim. Each operator
attempt owns fresh lane/evidence paths under the existing exclusive publication
law. A later attempt requires its own authorization.

## Operator procedure after separately authorized deployment

This section extends H8 only. It is not a controller-installation runbook.
Before using it, complete the reviewed installation and next-generation
requalification at the separately authorized merged commit `C`. Preserve the
old g5 evidence and checked account continuity; do not patch the installed
controller, reuse its old qualification digest for changed source, or reuse a
pre-reboot descriptor. The new generation and fresh session paths must be
named in that deployment's reviewed successor commands.

This route requires an additional pre-READ installation/requalification. The
later WRITE deployment may still batch its required changes; the earlier
single-post-READ-installation goal does not eliminate this cost.

### R0: custody and immutable inputs

Reconfirm exclusive operator custody. Check the expected boot, installed
controller/launch facts at `C`, and `m8-host-drift`. Stop on drift or any
unexpected output; changing the R6 baseline needs its own authorization.
Verify the prior/new qualification continuity and current active descriptor.
Do not read the credential contents, change expiry/last-refresh, manufacture a
401, or make an HTTP token request outside the contained vendor.

As in the existing successor runbook, prepare reviewed LF-only files, compare
local and VM SHA-256 values, then execute the file via non-interactive SSH with
stdin from `/dev/null`. No interactive paste, stdin script transport, `eval`
or unreviewed substitution. The exact `C`, new common file and declarations
must be included in the authorized script's reviewed bytes.

### R1: one explicit-refresh attempt

Use the new generation's reviewed common file: its normal OC definitions
provide `SERVICE`, `LANE`, `R`, `K`, `L`, `W` and `load_final_qualification`.
The deployment-specific declarations supply `SEALED` (the new generation's
descriptor file), `REFRESH_LANE` and `REFRESH_EVIDENCE` (fresh paths in `W`).
No defaults select g5 or any previous attempt.

```bash
sudo -n true < /dev/null
/usr/local/bin/m8-host-drift < /dev/null
load_final_qualification
: "${SEALED:?Set the reviewed new-generation descriptor path}"
: "${REFRESH_LANE:?Set the reviewed fresh lane path}"
: "${REFRESH_EVIDENCE:?Set the reviewed fresh evidence path}"
binding_check "$SEALED" accepted -
check_sealed "$SEALED" "$Q"
"${SERVICE[@]}" "${LANE[@]}" startup --request-refresh \
  --custody active --store-root "$R" --key "$K" --sealed "$SEALED" \
  --expected "$SEAL" --launch-root "$L" --configuration "$W/config.toml" \
  --policy "$W/startup-policy.json" --lane-dir "$REFRESH_LANE" \
  --evidence "$REFRESH_EVIDENCE" < /dev/null
```

The common file's existing fail-fast settings apply to this lane script, not
to LR's separately reviewed installation scripts. Any failed command stops.
Fresh-path checks and evidence publication belong to the existing lane; do
not delete a prior attempt to make a rerun possible.

### R2: verdict and handoff

Retain the published evidence and its printed digest. The explicit CLI's
post-publication verdict comes from that same completed evidence:

- `refresh-measured`: the existing measured predicate held in this run.
- `refresh-unmeasured`: active startup passed, but refresh was not measured.
- Faults, absent verdict, publication error or unexpected output: stop. Do not
  infer passing evidence from exit status, an empty file or a successful RPC.

Record the exact command revision, generation, boot, drift result, evidence
digest and verdict on #78; do not post credentials or the private account seal.
No automatic second attempt. Schema-5 evidence and the applicable checker/
verdict behavior must be included in the owner review before Stage 3 pins are
installed. A measured result permits that review, not an automatic READ call.

PRs #145/#147 remain behind the existing T5/no-T6 gate. S4-6 remains a post-READ
decision. The accepted WRITE design and later Claude qualification are not
implemented or authorized for host execution by this extension.
