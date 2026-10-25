# Claude first admitted READ: operator procedure

Living procedure proposal for [#40](https://github.com/sushiHex/constructicon/issues/40),
under accepted ADR 0021 and M8 rev 3. The owner authorized preparation of this
package, not its first model attempt. This procedure supplies no account,
credential, publication, activation or model-call authority by itself. The
owner must approve the concrete bounded procedure, task, one-attempt scope,
actual budget limitations and deterministic fresh-pin derivation before effects.
Independent checks of actual evidence, generation and minted authorization remain
mandatory before authority placement. One approval may cover this whole declared
scope; return to the owner only for an input/scope deviation. This preparation-only
wave has not supplied that call approval. Historical Codex decisions do not apply.

## Established starting point

Controller `8085b6af19dfaa31c8194b878d418a8e00b0ae73` includes the canonical named
admin-policy mount correction. The separately authorized session completed all
twelve controller replacement phases, exact installed equality, R19/Claude
imports, launch verification and one authenticated startup qualification.
The [finite result](https://github.com/sushiHex/constructicon/issues/40#issuecomment-6392574752)
affirms Max mode-match, matching settings/hooks, three writes, stdin close,
EOF, joined-clean process/relay/credential cleanup and current custody.
Its semantic evidence digest is
`sha256:d8000f87ffdcb36a995188d798d440ff27c06c2ecc66e61b093289524a170a6c`.
The VM was explicitly parked and independently observed off/idle; custody was
released. No READ, model call, descriptor publication or activation occurred.

That digest is historical evidence, not the next boot's seal. The schema-5
record truthfully retains `subscription_qualified: false` and
`production_available: false`. This is affirmative startup evidence, not a
blanket production or account-identity claim.

## Exact proposed call and enforceable bounds

Use only the installed Claude Code 2.1.296 subscription binding, selected Max,
and the unchanged launch configuration's explicit model/effort
(`claude-sonnet-4-6`, `low`). No login, credential inspection/copy, API-key
fallback, operator-requested credential refresh, model change or egress widening
is selected. Ordinary vendor behavior remains observational; the sealed
`forceRemoteSettingsRefresh: true` policy is preserved.
Recheck those actual installed inputs before preparation and immediately before
release of the READ.

The existing `constructicon.api.claude_qualification` component sends one user
message: `Use the read_file tool exactly once to read ready.txt. Reply with the
single word found in that file, and nothing else.` The fresh private Git fixture
contains only `ready.txt` with bytes `ready` plus LF, at base
`841fb659ad76d0bd140bae9842675e6d6822da17`, ref `refs/heads/claude-read`.
No user repository or account content enters the task. Admission requires the
fixed graph, one executor lease, one READ workspace lease and that exact fixture.

The authorization permits one epoch and one durable attempt record. The READ
lease has a 120-second deadline; the journal/RunHost drive has a 180-second outer
wait and joins owned work before returning. These are controller bounds, not a
guaranteed wall-clock cap on transport or all cleanup. Native I/O retains its
8-KiB input, 512-KiB cumulative stdout and 256-KiB record bounds; the contained
file worker caps output at 64 KiB. Fixture population separately permits a
32-KiB archive. The reviewed observe egress policy has its existing finite
16-connection ceiling and destination/address pins. Connections are not backend
model requests.

Tokens are observations when emitted. There is no enforced token, backend
request-count or money ceiling in this recipe. The one user message and one
successful admitted file callback do not establish a backend request count.
The owner's exact-call decision must explicitly accept these unmeasured limits,
the subscription overage policy and any cost exposure for this one attempt;
otherwise stop before authorization placement. Do not import Codex acceptance,
promise zero spend, add a made-up cap or weaken the native startup predicates.

## Package and current-boot prerequisites

Bind a fresh private package from the reviewed source procedure. Keep private
boot, transport, home paths, account facts and locators out of public artifacts.
Every action has closed stdin, exact source/tool hashes, retained native
status/stdout/stderr and a distinct output name. The private transport package
must declare its deadlines and finite readback/validation bounds. The existing
capture runner checks retained stream sizes after completion; shell redirections
and those checks are not disk-write caps or proof of remote process termination.
Native protocol bounds are separate. These fences are reviewed phase
templates: bind them into separately checked script files, stage/hash-check the
scripts, and invoke them over the established noninteractive SSH transport.
Do not paste them into an interactive shell or treat its `set -e` as a retained
native status. No fence is host-ready until its actual private package is bound.
Run one phase once, review its complete records, and release the next. Missing
or partial evidence never permits retry. Preserve the actual interruption prefix.

Before host effects, require the existing cooperative custody/usage protocol,
Windows ACL check, fresh boot, current-boot D2 verify/probe and exact pinned
successful drift guard. Freshly verify the complete controller at the C above,
its helper/lock/import closure, and the complete installed Claude launch and
three enforcing profiles. Use the existing pinned controller/Claude artifact
helpers; keep the staging tree unavailable during installed verification.

Retain the unchanged expected launch configuration SHA-256
`b39350ce52abf846268e610af1175689e968386dc29c4ed67ea9d081d3391277`, runtime
`sha256:df3c24ebb2dca096ae72a08c300c02975954b843ebc2f74a91ce2283bdfd11ca`, vendor
`sha256:09cf490824fae9c65aec3b6842eef6a7d6ff192d178f1f0fb91b805ac695622f` and policy
SHA-256 `7d0c68c12110d54ed669d050f04a259ffb18981a5bfe60f88809303fa7d34ad6` as
independently reviewed literals. Fresh rederivation decides whether they still
match; a mismatch is HOLD, not permission to adopt new pins or reinstall.

The common declarations below are phase inputs, not an execution approval.
The private package must replace every UNREVIEWED, establish canonical paths,
ancestor custody and fresh destination absence, and pin every resulting file.
`R` is a fresh operator-private capture directory; `RUN` is a fresh service-owned
0700 root outside the launch tree and store. `AUTH` is a distinct fresh root-owned,
service-searchable directory with no group/other write access. `ACQ` is a fresh
service-owned 0700 root disjoint from the fixture and store. Its derived
`payloads/acq-<32 hex>/egress.sock` must fit 107 encoded bytes. Do not choose a
long session-root descendant and discover the socket bound during dispatch.

```bash
set -Eeuo pipefail -C
umask 077
C=8085b6af19dfaa31c8194b878d418a8e00b0ae73
L=b39350ce52abf846268e610af1175689e968386dc29c4ed67ea9d081d3391277
CONTROLLER=/opt/constructicon-m8-controller
CONFIG=/var/lib/constructicon-m8-claude/launch-config.json
STORES=/var/lib/constructicon-m8-claude-stores
STORE_KEY=claude-subscription
SERVICE=m8-service
R=UNREVIEWED
RUN=UNREVIEWED
AUTH=UNREVIEWED
ACQ=UNREVIEWED
QUAL=UNREVIEWED
CHECKER=UNREVIEWED
FLOOR=UNREVIEWED
GENERATION=UNREVIEWED
ACTOR=UNREVIEWED
READ_KEY=UNREVIEWED
AUTHORIZATION_ID=UNREVIEWED
for value in "$R" "$RUN" "$AUTH" "$ACQ" "$QUAL" "$CHECKER"              "$FLOOR" "$GENERATION" "$ACTOR" "$READ_KEY" "$AUTHORIZATION_ID"; do
  test "$value" != UNREVIEWED
done
STORE=(/usr/bin/python3 -I -S -B -c 'import sys; sys.path.insert(0,"/opt/constructicon-m8-controller"); from constructicon.substrate.executors.operator_store import main; raise SystemExit(main())')
LANE=(/usr/bin/python3 -I -S -B -c 'import sys; sys.path.insert(0,"/opt/constructicon-m8-controller"); from constructicon.substrate.executors.claude_lane import main; raise SystemExit(main())')
READ=(/usr/bin/python3 -I -S -B -c 'import sys; sys.path.insert(0,"/opt/constructicon-m8-controller"); from constructicon.api.claude_qualification import main; raise SystemExit(main())')
```

Root creates only the approved fresh parents with those custody/modes, using
fixed stock tools. No existing path is repaired or removed. Fixture, journal,
attempt, payload and authorization names stay absent until their owning phase.
The installed checker must be the exact C Git blob of
`scripts/check_claude_phase.py`: SHA-256
`0c6b8634b19530fa7b6761091f61b81671d9dee8dcbd788439e553894383df7c`, 13,822 bytes,
root-owned single-link 0444 beneath its canonical root-owned 0555 parent and
safe root-owned ancestors. Reuse its checked installation; missing/changed
checker custody stops preparation.

## Fresh qualification and exact digest

Use the existing-store maintenance wrapper once on this boot with fresh lane
and evidence names. Keep the store withdrawn. This is a no-model acquisition;
its success does not release the READ by itself.

```bash
sudo -n "${STORE[@]}" maintain --store-root "$STORES" --key "$STORE_KEY"   --service "$SERVICE" --wait 0 -- "${LANE[@]}" qualify   --launch-config "$CONFIG" --launch-config-sha256 "$L"   --lane-dir "$RUN/qualify" --evidence "$QUAL" --selected-plan max   < /dev/null > "$R/qualify.stdout" 2> "$R/qualify.stderr"
sudo -n -u "$SERVICE" -- /usr/bin/python3 -I -S -B -c   'import sys,runpy; sys.path.insert(0,"/opt/constructicon-m8-controller"); p=sys.argv.pop(1); runpy.run_path(p,run_name="__main__")'   "$CHECKER" --phase qualify --evidence "$QUAL" --config "$CONFIG"   --config-sha256 "$L" --selected-plan max   < /dev/null > "$R/qualification.digest" 2> "$R/checker.stderr"
```

The checked transport retains each native status independently. Require native
0, empty stderr, and the positive checker digest. Independently compare that
semantic `digest("claude-maintenance-entry-evidence", 1, parsed_record)` with the
retained complete schema-5 evidence snapshot. Also pin the exact raw evidence
file SHA-256 separately. A raw-file SHA is not the semantic conformance digest.
Require all three matching judges, exactly three writes, close/EOF, joined-clean,
process clean, relay/credential closed and custody current. Record this boot's
new digest as `Q`; never substitute the historical `d8000f...` result.

## Affirm withdrawal, publish and activate one generation

The reviewed metadata inventory must positively identify the existing descriptor
set and its highest generation `FLOOR`; absence is not generation 1. The following
fixed service child uses only the existing inherited-maintenance contract. It
neither launches a credential lane nor opens credential content. It proves a
durable withdrawal, the retained lock, current physical binding and highest
inventory floor. Use it here with the reviewed `FLOOR`, then after READ with the
published `GENERATION`. Keep its exact bytes in the private package.

```bash
WITHDRAW_CODE='import argparse,os,sys; from pathlib import Path
sys.path.insert(0,"/opt/constructicon-m8-controller")
from constructicon.substrate.executors.operator_store import inherit_maintenance
p=argparse.ArgumentParser(allow_abbrev=False)
p.add_argument("--expected-floor",type=int,required=True)
p.add_argument("--store-root",type=Path,required=True)
p.add_argument("--key",required=True)
p.add_argument("--custody",choices=("maintenance",),required=True)
p.add_argument("--lock-fd",type=int,required=True)
p.add_argument("--floor",type=int,required=True)
a=p.parse_args()
if a.floor!=a.expected_floor: raise SystemExit(1)
with inherit_maintenance(a.store_root,a.key,a.lock_fd,generation_floor=a.floor,parent=os.getppid()) as held:
    held.check()
    print("withdrawn-checked")'
sudo -n "${STORE[@]}" maintain --store-root "$STORES" --key "$STORE_KEY"   --service "$SERVICE" --wait 0 -- /usr/bin/python3 -I -S -B -c "$WITHDRAW_CODE"   --expected-floor "$FLOOR" < /dev/null   > "$R/withdraw-before.stdout" 2> "$R/withdraw-before.stderr"
```

Require its completed native 0, empty stderr and exact `withdrawn-checked` plus
LF. Independently review `GENERATION = FLOOR + 1`, at least 2. Publication also
rechecks `require_next_generation` under the retained lock; a missing inventory,
occupied generation or mismatch stops instead of selecting another generation.
Before publication, revalidate the same raw evidence snapshot and semantic `Q`.
The publish helper trusts the supplied digest; it does not run the checker.

```bash
Q=UNREVIEWED
[[ "$Q" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "$FLOOR" =~ ^[0-9]+$ && "$GENERATION" =~ ^[0-9]+$ ]]
test "$GENERATION" -eq "$((FLOOR + 1))"
test "$GENERATION" -ge 2
sudo -n "${STORE[@]}" publish --store-root "$STORES" --key "$STORE_KEY"   --service "$SERVICE" --wait 0 --generation "$GENERATION"   --qualification-evidence-digest "$Q" < /dev/null   > "$R/published-sealed.json" 2> "$R/publish.stderr"
```

Review the complete bounded emitted identity: its operator binding must match
the checked key/generation/current physical instance and both conformance
revisions must equal `Q`. The sealed identity carries digests, not raw
key/generation fields; do not invent those fields. Install that exact JSON
at the absent `$AUTH/sealed.json` using the reviewed stock install command,
owner service, mode 0600, single link, safe canonical ancestors. The service
must read it for assembly; the helper accepts only root/service-owned 0600.
Before either stock install below, affirm the exact destination is absent,
including a dangling symlink, and recheck the source bytes/type/link/custody.
`AUTH` and every ancestor must be canonical and root-owned, without group/other
write access; service search permission never includes parent write permission.
Continued exclusive custody prevents another root writer between the absence
check and install. The stock install itself is not an atomic no-clobber primitive.
A failed/uncertain install stops; no overwrite, retry or repair is selected.
Then activate that same generation and identity, separately:

```bash
sudo -n /usr/bin/test ! -e "$AUTH/sealed.json"
sudo -n /usr/bin/test ! -L "$AUTH/sealed.json"
sudo -n /usr/bin/install -o "$SERVICE" -g "$SERVICE" -m 0600   "$R/published-sealed.json" "$AUTH/sealed.json" < /dev/null
sudo -n "${STORE[@]}" activate --store-root "$STORES" --key "$STORE_KEY"   --service "$SERVICE" --wait 0 --generation "$GENERATION"   --qualification-evidence-digest "$Q" --sealed "$AUTH/sealed.json"   < /dev/null > "$R/activate.stdout" 2> "$R/activate.stderr"
```

Require separate native 0 and empty stdout/stderr for activation. The helper
checks the descriptor, current objects and generation above the withdrawal
floor before replacing active selection. READ assembly requires this active
selection; do not run it inside a maintenance acquisition that withdraws it.
Publication/activation is narrowly for this qualification, not production enablement.

The withdrawal duty starts when activation succeeds or may have completed, not
when READ starts. Every later abort or scope deviation, including fixture,
minting, authorization installation or pre-dispatch failure, must reach the
fixed withdrawal check below before orderly parking/release. Prepare that
separate cleanup phase before activation. If activation's outcome or an owned
process/lock is uncertain, stop for the reviewed recovery inventory; never retry
activation, steal the lock or infer withdrawal from an absent active file.

## Fixed fixture, candidate authorization and owner call decision

```bash
sudo -n -u "$SERVICE" -- "${READ[@]}" prepare --fixture "$RUN/fixture"   < /dev/null > "$R/fixture.json" 2> "$R/fixture.stderr"
sudo -n -u "$SERVICE" -- "${READ[@]}" mint   --fixture "$RUN/fixture" --launch-config "$CONFIG" --launch-config-sha256 "$L"   --store-root "$STORES" --store-key "$STORE_KEY" --sealed "$AUTH/sealed.json"   --qualification "$QUAL" --acquisition-root "$ACQ"   --authorization-id "$AUTHORIZATION_ID" --actor "$ACTOR" --key "$READ_KEY"   --journal "$RUN/read.sqlite" --attempt-record "$RUN/read-attempt.json" --hours 1   < /dev/null > "$R/authorization-candidate.json" 2> "$R/mint.stderr"
```

Require each native status 0 and empty stderr. Review the fixture's exact
revision, complete candidate authorization and raw JSON hash. `mint` emits
pins; it does not install authority or dispatch. Require stage
`qualification-read`, exact fixed graph/scope/binding, provider/store/workspace
revisions, current generation, model/effort/READ grants, dedicated absolute
journal, exclusive attempt path, `max_epoch: 1` and actual expiry. Every path
and actual pin is part of the concrete private package. Do not mint a successor
because a previous candidate expired or an attempt outcome is uncertain.

**Authority-placement HOLD:** independently check the actual candidate bytes/hash,
actor/key/run, binding/generation, fixture/task/model/effort, expiry, one attempt,
actual egress and all budget limitations against the owner's approved procedure
and deterministic fresh-pin rules. Preparation authority alone is insufficient.
An exact match releases placement without a second post-mint owner roundtrip;
any deviation returns to the owner. Install only those checked bytes as a
root-owned, service-readable 0640, single-link file under protected ancestors:

```bash
sudo -n /usr/bin/test ! -e "$AUTH/authorization.json"
sudo -n /usr/bin/test ! -L "$AUTH/authorization.json"
sudo -n /usr/bin/install -o root -g "$SERVICE" -m 0640   "$R/authorization-candidate.json" "$AUTH/authorization.json" < /dev/null
```

The destination must be freshly absent. Recheck exact installed bytes, owner,
mode, link count, ancestors, boot/drift/custody, installed controller/launch,
qualification snapshot, active identity and authorization window before release.
No source or model/effort change is permitted between approval and dispatch.

## One run, terminal checks and no retry

```bash
sudo -n -u "$SERVICE" -- "${READ[@]}" run   --fixture "$RUN/fixture" --launch-config "$CONFIG" --launch-config-sha256 "$L"   --store-root "$STORES" --store-key "$STORE_KEY" --sealed "$AUTH/sealed.json"   --qualification "$QUAL" --acquisition-root "$ACQ"   --authorization "$AUTH/authorization.json"   < /dev/null > "$R/read-status.json" 2> "$R/read.stderr"
```

Success requires native 0, empty stderr and exactly `{"status": "succeeded"}`
plus LF, backed by the dedicated journal's terminal run and completed attempt.
The fixed component requires one successful contained callback and stripped
answer `ready`; native success alone cannot satisfy it. The provider requires
one admitted started/completed callback, protocol completion, non-denying closed
relay, joined process/worker, terminal store binding and credential/lock release.
The control lifecycle waits for owned work; acquisition disposal remains part
of the checked terminal result. Retain finite actual telemetry; absence remains
unknown, not zero. This qualifies only the observed READ profile and bounds.

Completed journal replay returns the existing result without another attempt;
this procedure schedules no second `run`. An acquired, intent, incomplete or
uncertain attempt stops for reviewed recovery, never a new journal/key/process.
A transport timeout does not prove termination. Preserve records and custody.

After successful activation, on every subsequent terminal outcome or abort
(including before READ), explicitly withdraw with the fixed child above, now
expecting `GENERATION`:

```bash
sudo -n "${STORE[@]}" maintain --store-root "$STORES" --key "$STORE_KEY"   --service "$SERVICE" --wait 0 -- /usr/bin/python3 -I -S -B -c "$WITHDRAW_CODE"   --expected-floor "$GENERATION" < /dev/null   > "$R/withdraw-after.stdout" 2> "$R/withdraw-after.stderr"
```

Require affirmative native 0, empty stderr and `withdrawn-checked` plus LF.
Missing `active.json` is not withdrawal proof. If the process may still own the
lock, this `--wait 0` check refuses; do not kill, steal, retry or activate another
generation. Preserve the prefix and use the reviewed recovery decision. Do not
remove credentials, descriptors, authorization, journal or attempt evidence.
Finish with explicit park and independent off/idle observation before releasing
custody. No automatic cleanup, provider activation, WRITE or further model call
is selected. Record what actually ran and stop at its actual evidence strength.

The review removed an extra post-mint owner-approval checkpoint that was a
conservative interpretation, not an accepted-plan requirement. Exact owner
scope and independent actual-pin checks remain mandatory; no plan changed.

## Source and evidence references

- [Accepted M8 rev 3](../milestones/M8-live-executors-rev3.md), N5/N6.
- [Startup qualification and admitted READ composition](M8-N6-qualified-read-state-review.md).
- [Maintenance operator boundary](M8-N6-maintenance-operator-procedure.md).
- [Public qualification receipt](https://github.com/sushiHex/constructicon/issues/77#issuecomment-6392574546).
- [Source API](../../../src/constructicon/api/claude_qualification.py),
  [fixture](../../../src/constructicon/api/_claude_read_fixture.py),
  [host reader](../../../src/constructicon/substrate/executors/claude_host.py),
  [offline store commands](../../../src/constructicon/substrate/executors/operator_store.py).
