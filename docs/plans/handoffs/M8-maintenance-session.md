# M8 maintenance: fresh g9 and one application attempt

Status: draft exact procedure for [#186](https://github.com/sushiHex/constructicon/issues/186).
The deployment controller is **UNMERGED** until PR #187 is merged and its
actual merge commit and reviewed tree are verified. `bc606c9` is a reviewed
branch head, not a deployment commit. The bundle, base and bundle digest are
also unprepared. The guards below refuse these placeholders before transport.
Replace them with reviewed literal pins, review the resulting complete script
bytes and procedure revision, then obtain the required session authorization.
This draft authorizes no VM operation or vendor request.

The owner approved the maintenance implementation and related work; this
procedure makes the proposed host actions concrete. It continues the
[maintenance entry design](M8-maintenance-entry-state-review.md), not N5's
additional WRITE fixture. The application has its own authorization, dedicated
journal and one attempt. Historical g8 evidence cannot qualify the changed
adapter. No R6 baseline, repair, retry, recovery dispatch, login, credential
inspection, fake-provider deployment, push, promotion or merge is supplied.

## P0: pins, custody and reviewed composition

Claude reported the VM Off with zero checkpoints; the owner reports nobody
else uses it. These are reports, not fresh VM measurements. Reconfirm exclusive
operator/root/service-identity custody immediately before starting. Record the
actual VM state and checkpoints without changing either. Stop on disagreement.
Preserve all old session, journal, sidecar, attempt, authorization, diagnostic,
store and archive bytes. A process scan is not exclusive-custody proof.

The session authorization names the final procedure revision, actual merged
`C`, installed `O/D`, one clean start from Off, the exact LR root operations
including conditional LR9, fresh g9 qualification, every H7 control, at most
one conditional H8 request, the immutable source bundle/base/hash and fresh
application/state/authority paths. It also names one application turn under the
existing 300-second exchange/callback and byte limits, eight admitted callbacks,
fixed data task/exam, one epoch and preflight's one-hour expiry. Observation is
1200 seconds; joined cleanup has no claimed overall wall-clock bound. Tokens
are observational; backend requests/retries are unknown, with no finite
monetary ceiling. Actual H7/H8 evidence and preflight pins are reviewed before
the application authority is installed. Prior approval is not a fresh pin fact.

Copy this guard before every workstation transport and every executed step,
including old-controller and installer steps. After pin preparation replace
only its literal declarations; do not supply branch head as `C`:

```bash
C=UNMERGED
O=59de73bbc9b6f6a9a814b6193f0252e92d1bdd3e
D=8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3
BASE=UNPINNED
BUNDLE_SHA256=UNPINNED
BUNDLE=/home/m8-service/UNPREPARED.bundle
[[ "$C" =~ ^[0-9a-f]{40}$ && "$BASE" =~ ^[0-9a-f]{40}$ && "$BUNDLE_SHA256" =~ ^[0-9a-f]{64}$ ]] \
  || { echo 'merged controller and reviewed source pins required; stop' >&2; exit 1; }
test "$BUNDLE" != /home/m8-service/UNPREPARED.bundle \
  || { echo 'reviewed immutable bundle path required; stop' >&2; exit 1; }
```

Use frozen [OC](M8-N4-operator-commands.md), [LR](M8-N4-launch-replacement.md),
[HR](M8-N4-host-runtime.md), [HS](M8-N5-host-session.md),
[ER](M8-N5-explicit-refresh.md) and [D2](M8-D2-host-installation.md).
All retain their bytes. Copy referenced blocks verbatim, with documented
literal commit declarations, or the complete replacements explicitly below.
Do not generate scripts with `sed`, `eval` or runtime substitutions.

| Step | Exact source and composition |
| --- | --- |
| Prior common | After the P0 deployment guard, declare `C=59de73bbc9b6f6a9a814b6193f0252e92d1bdd3e`, then OC's two Setup blocks and `W=/home/m8-service/m8-n5-stage2g8` |
| P1 prior check | Prior common, HS H2, P1 controller-verifier block; review its affirmative record before the separate capture file |
| P1 capture | Prior common, HS H2, P1 capture block; no accepted old binding check |
| P2 preservation | Complete P2 preservation block below, separate from LR2; require its positive marker |
| P2 D2 | Only after preservation succeeds, LR2 at verified D in D2's own workspace and a fresh shell |
| P2 launch | LR3's two blocks at C with O above; LR4; HR R12; LR6, each in a fresh shell with required C/W/J prefixes |
| P2 controller | LR8 at C with O above; conditional LR9 then HR R17/R18 at C; HR R19 on both routes |
| P2 physical preflight | OC Setup at C, only OC S3's preflight line, requiring `launch_ready:true` |
| New common | OC's two Setup blocks at C, then P3 declarations below |
| P3 qualification | HS H2; OC S1; OC S4 followed by P3 comparison; OC S6a unchanged |
| P4/P5 | Complete g9 floor-8 and H7 replacements below |
| P6 | New common and P6 declarations, ER R1 unchanged; ER R0/R2 apply |
| Application | New common, P7 declarations, P7-P10 blocks below, each in its own reviewed step file |

Prepare LF-only local common/step files and record source revision,
heading/block, literal declarations and SHA-256. Each step sources the exact
common file in its own fresh reviewed package, not historical home scripts.
LR/HR installers keep their own shell settings: no N5 common or added
`pipefail`. All SSH/SCP commands use BatchMode, strict host-key checking and
stdin `/dev/null`; execute uploaded files, never stdin scripts or pasted text.
The following transport example is for P3's prepare step; use distinct absent
package/file names for every other step and hash all uploaded inputs:

```bash
set -Eeuo pipefail
: "${SSH_TARGET:?Set the authorized VM SSH target}"
/usr/bin/grep -Fqx "C=$C" maintenance-p3.sh
! /usr/bin/grep -q $'\r' maintenance-common.sh maintenance-p3.sh
/usr/bin/sha256sum -- maintenance-common.sh maintenance-p3.sh > maintenance-p3.sha256
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$SSH_TARGET" \
  'test ! -e "$HOME/maintenance-p3-package" && test ! -L "$HOME/maintenance-p3-package" && /usr/bin/mkdir -m 0700 -- "$HOME/maintenance-p3-package"' < /dev/null
scp -o BatchMode=yes -o StrictHostKeyChecking=yes \
  maintenance-common.sh maintenance-p3.sh maintenance-p3.sha256 "$SSH_TARGET:maintenance-p3-package/" < /dev/null
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$SSH_TARGET" \
  'cd "$HOME/maintenance-p3-package" && sha256sum --check --strict maintenance-p3.sha256 && bash maintenance-p3.sh' < /dev/null
```

Before upload, stock git proves C is the actual merge on main and its tree
equals the final reviewed head. Record those facts and exact-head CI/native
proof links. Prepare a new immutable git bundle containing the reviewed BASE;
record its actual SHA-256, size (at most 64 MiB), base and bundle ref inventory.
Review that BASE contains the installed consumer/reference/exam bytes and no
`tests/vectors/plan_manifest.json`. Upload the bundle to the literal absent
service-owned path, compare its local and remote digest, and retain it private.
`prepare` checks these bytes before importing them. Unknown pins stop.

## P1: already Off, one fresh start and historical continuity

Notify before the fresh start. On the Windows host, confirm Off and zero
checkpoints, then start once. Do not create a checkpoint or run Stop-VM merely
to mimic the old pre-reboot route. Stop on Saved/Running/unknown state:

```powershell
$maintenanceController = 'UNMERGED'
$maintenanceBase = 'UNPINNED'
$maintenanceBundleSha256 = 'UNPINNED'
if ($maintenanceController -cnotmatch '^[0-9a-f]{40}$' -or
    $maintenanceBase -cnotmatch '^[0-9a-f]{40}$' -or
    $maintenanceBundleSha256 -cnotmatch '^[0-9a-f]{64}$') {
    throw 'Merged controller and reviewed source pins required before VM operation'
}
$maintenanceVm = Get-VM -Name constructicon-m8
if ($maintenanceVm.State -ne 'Off') { throw 'Expected already Off VM' }
if (@(Get-VMSnapshot -VMName constructicon-m8).Count -ne 0) { throw 'Unexpected checkpoint' }
Start-VM -Name constructicon-m8
```

Read the DHCP address and use the reviewed SSH target. Record the full
`/proc/sys/kernel/random/boot_id`. From this boot until the controller is
current, no `maintain`, `activate`, vendor lane or second session runs. P1's
checker is local historical-file observation and store refusal, not a vendor
lane. Do not run frozen g8's pre-reboot accepted-binding capture or HS H1's g3
check. Require fresh old-controller provenance at O and this verifier's
`installed:true`, observed controller `state:tree`, `different:0`. Keep output
private outside the historical workspaces; never overwrite their records:

```bash
/usr/bin/python3 -I "$HOME/m8-controller/m8_host_artifacts.py" \
  verify-controller "$C" "$HOME/m8-controller" < /dev/null
```

Only after reviewing that affirmative result, run this separate capture step.
The old O checker validates retained S4/S6a against O's installed adapter,
configuration, runtime record and vendor/catalog copies. This is historical
continuity, not current host-runtime qualification; no old-launch-current-OS
condition is invented. The binding check requires the specific reboot-anchor
refusal, not arbitrary unavailability. Its expected literal exception is
`native store anchor is unavailable`:

```bash
binding_check "$W/g8.sealed.json" reboot-anchor -
load_final_qualification
check_sealed "$W/g8.sealed.json" "$Q"
test "${SEAL%%/*}" = pro \
  || { echo 'historical g8 account is not the qualified pro plan; stop' >&2; exit 1; }
test -n "$SEAL"
set -C
printf '%s\n' "$SEAL" > "$HOME/maintenance-g9-account.seal"
```

An occupied capture path, changed controller or failed checker stops; no
recapture, normalization or credential read. Keep the account seal private.

## P2: D2 fresh-boot physical qualification and normal LR

Before verbatim LR2 overwrites its three existing output records, preserve
their current bytes in a separate operator step. All three files must exist,
be regular and not symlinks; missing records stop rather than imply there is
nothing to preserve. The archive must be absent, including a dangling symlink.
Run this complete block without root or N5 common, after the P0 guard:

```bash
set -Eeuo pipefail
umask 077
V="$HOME/m8-host"
D2_PRIOR="$HOME/maintenance-g9-d2-prior"
if test -e "$D2_PRIOR" || test -L "$D2_PRIOR"; then
  echo 'D2 prior archive is occupied; stop' >&2; exit 1
fi
for D2_NAME in profiles-verify verify.json qualification.json; do
  if ! test -f "$V/$D2_NAME" || test -L "$V/$D2_NAME"; then
    echo 'D2 prior record is missing or redirected; stop' >&2; exit 1
  fi
done
/usr/bin/mkdir -m 0700 -- "$D2_PRIOR"
for D2_NAME in profiles-verify verify.json qualification.json; do
  /usr/bin/cp -p --no-clobber -- "$V/$D2_NAME" "$D2_PRIOR/$D2_NAME"
  /usr/bin/cmp -s -- "$V/$D2_NAME" "$D2_PRIOR/$D2_NAME"
done
echo d2-prior-records-preserved
```

Only the positive `d2-prior-records-preserved` marker permits the separately
reviewed LR2 step. Keep the archive private and unchanged. Failure preserves
any partial archive and all sources, stops before LR2, and authorizes no
archive deletion, overwrite or repair.

Run LR2's D2 verify/probe at D. Require affirmative `installed:true` and
`qualified:true` records on this boot, then bare `m8-host-drift` exit 0 with
affirmative no drift. Reboot and quiet drift alone do not establish physical
attachment. No R6 or drift repair; any failure stops and preserves evidence.

Run normal LR3/R11, LR4, HR R12, LR6, LR8, conditional LR9/HR R17/R18,
HR R19, then LR7, at the exact C. Fresh-shell installer prefixes declare C,
their workspace and J where required. Require every passing record and marker,
not just the final shell exit. The normal archives are `m8-launch-$O` and
`m8-controller-$O`; an occupied destination stops. Do not replay historical
retention-resume routes, delete the launch root/store or restore a checkpoint.
LR4's judge proves retirement targets/store identity before fixed root writes.
LR6 must affirm installed and replacement true.

LR8 pass requires installed true and different zero. LR9 runs only after its
record affirms installed false, observed state tree and different greater than
zero, using LR9's exact guard. A malformed/arbitrary refusal stops. On this
route require R18 installed and verifier installed true/different zero. R19
must pass on **both routes**. LR7 follows the current controller and requires
launch_ready true, including benign physical attachment. No login/provision.
Do not reboot again; a changed boot or uncertain custody stops the session.
This session selects no cleanup, checkpoint restore or rerun branch from the
referenced failure tables. Preserve any partial installation and its records,
park the VM, and obtain a new decision instead.

## P3: fresh qualification and account comparison

Append to OC Setup at C for each new common file:

```bash
W_PRIOR=/home/m8-service/m8-n5-stage2g8
W=/home/m8-service/m8-maint-q9
PRIOR_SEAL="$(/usr/bin/cat -- "$HOME/maintenance-g9-account.seal")"
```

Run HS H2 unchanged, then OC S1 into absent W. Preserve its completed pin
record; incomplete output is abandoned. Run OC S4 and this comparison in the
same shell, then OC S6a unchanged:

```bash
test "$S4_SEAL" = "$PRIOR_SEAL" \
  || { echo 'fresh S4 account differs from historical checked g8; stop' >&2; exit 1; }
```

Require complete S4/S6a evidence, exact competing-maintenance refusal, retained
lock and joined held startup. Old g8 digests/refresh cannot qualify new bytes.

## P4: checked maintenance floor 8, publish and activate g9

This is a complete H6 replacement. Both checked records must affirm strict
integer historical maintenance floor 8 before publication. Missing, bool,
float or any other floor stops; do not choose a generation from filenames.

```bash
load_final_qualification
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, sys
from pathlib import Path
for name in ("s4-qualification.json", "s6a-qualification.json"):
    custody = json.loads((Path(sys.argv[1]) / name).read_bytes())["custody"]
    assert custody["kind"] == "maintenance"
    assert type(custody["generation_floor"]) is int and custody["generation_floor"] == 8
print("maintenance-floor-8-checked")' "$W" < /dev/null \
  | /usr/bin/grep -qxF maintenance-floor-8-checked
"${ROOT_STORE[@]}" publish --store-root "$R" --key "$K" --generation 9 \
  --qualification-evidence-digest "$Q" --service m8-service --wait 0 \
  < /dev/null | save_sealed "$W/g9.sealed.json"
check_sealed "$W/g9.sealed.json" "$Q"
"${ROOT_STORE[@]}" activate --store-root "$R" --key "$K" --generation 9 \
  --sealed "$W/g9.sealed.json" --qualification-evidence-digest "$Q" \
  --service m8-service --wait 0 < /dev/null
binding_check "$W/g9.sealed.json" accepted -
binding_check "$W_PRIOR/g8.sealed.json" stale-generation "$W/g9.sealed.json"
```

## P5: every H7 control, even when refresh is measured

Active startup passes the unchanged OC schema-4 checker. S6b exits exactly 1
and affirms only positive denied:destination with the exact four account/read
refusal faults. EOF-only, destination plus EOF, missing denial or extra faults
stops. S6c requires its exact wrong-plan refusal. No waiver or allowlist change.
The refresh selector reads the producer's explicit verdict from bounded JSON
whose digest equals the successful active check's captured digest. A parse,
digest or refresh-checker error stops; it is never evidence of unmeasured
refresh and cannot permit H8.

```bash
load_final_qualification
"${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g9.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-g9-lane" --evidence "$W/h7-g9-active.json" < /dev/null
ACTIVE_Q="$(check_evidence active "$W/h7-g9-active.json" active "$SEAL" "$W/startup-policy.json")"
ACTIVE_REFRESH="$("${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api._maintenance_source import read_bounded
from constructicon.core.identity import digest, parse_json_value
from constructicon.substrate.executors.codex_lane import EVIDENCE_DOMAIN
r = parse_json_value(read_bounded(Path(sys.argv[1]), 1048576).decode("utf-8", errors="strict"))
assert str(digest(EVIDENCE_DOMAIN, 1, r)) == sys.argv[2]
assert type(r) is dict and type(r.get("refresh")) is str and r["refresh"] in ("measured", "unmeasured")
print(r["refresh"])' "$W/h7-g9-active.json" "$ACTIVE_Q" < /dev/null)"
case "$ACTIVE_REFRESH" in
  measured)
    REFRESH_Q="$(check_evidence refresh "$W/h7-g9-active.json" active "$SEAL" "$W/startup-policy.json")"
    test "$REFRESH_Q" = "$ACTIVE_Q"
    echo refresh-measured ;;
  unmeasured) echo refresh-unmeasured ;;
  *) echo 'unexpected active refresh verdict; stop' >&2; exit 1 ;;
esac
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, os, sys
from pathlib import Path
p = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert p["connections"] == 8 and len(p["destinations"]) == 2
assert [x[0] for x in p["destinations"]] == ["auth.openai.com", "chatgpt.com"]
p["destinations"] = p["destinations"][:1]
os.umask(0o077)
with open(sys.argv[2], "x", encoding="utf-8") as stream:
    json.dump(p, stream, sort_keys=True); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())' \
  "$W/startup-policy.json" "$W/h7-g9-no-chatgpt-policy.json" < /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g9.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/h7-g9-no-chatgpt-policy.json" \
  --lane-dir "$W/h7-g9-s6b-lane" --evidence "$W/h7-g9-s6b-denial.json" --expect-denial \
  < /dev/null; then echo 'S6b unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence denial "$W/h7-g9-s6b-denial.json" active "$SEAL" "$W/h7-g9-no-chatgpt-policy.json" > /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g9.sealed.json" --expected "plus/${SEAL#*/}" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-g9-s6c-lane" --evidence "$W/h7-g9-s6c-plan-refusal.json" \
  < /dev/null; then echo 'S6c unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence wrongplan "$W/h7-g9-s6c-plan-refusal.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
binding_check "$W_PRIOR/g8.sealed.json" stale-generation "$W/g9.sealed.json"
```

## P6: at most one conditional H8

If P5 prints refresh-measured, omit H8. Only if P5 completes every H7 control
and explicitly prints refresh-unmeasured, under the session's conditional
one-attempt authorization, append these declarations to the new common and
execute ER R1 unchanged. A missing verdict or failed P5 never permits H8:

```bash
SEALED="$W/g9.sealed.json"
REFRESH_LANE="$W/h8-g9-explicit-lane"
REFRESH_EVIDENCE="$W/h8-g9-explicit-refresh.json"
```

ER R0/R2 apply: current boot/custody/install/drift, binding and evidence checks;
retain schema-5 evidence, printed digest and verdict from the same completed
record. Do not use OC's schema-4 checker on it. Unmeasured refresh, faults,
missing verdict or unexpected output stops. No second attempt, natural-refresh
fallback, expiry edit, manufactured 401 or token request. Submit complete H7
and applicable H8 evidence for the session's evidence review before P7.

## P7: installed entry, fresh closure and reviewed application source

Append these complete declarations to new common. S is deliberately short for
the native socket bound; APP is a separate new private authority:

```bash
S=/home/m8-service/m8-m1
APP=/home/m8-service/m8-maint-a1
A=/var/lib/constructicon-m8-maintenance/application-1.json
ID="maintenance-1-$C"
ACTOR=operator:maintenance-1
KEY=maintenance-1
ENTRY=("${PY[@]}" constructicon.api.maintenance_entry)
HOST=(--session "$W" --store-key "$K" --sealed "$W/g9.sealed.json"
  --qualification "$W/s6a-qualification.json" --state "$S" --launch-root "$L")
```

In this separate step repeat HS H2, load_final_qualification and
binding_check of g9 accepted, then run:

```bash
"${SERVICE[@]}" "${PY[@]}" constructicon.api.maintenance_entry --help < /dev/null > /dev/null
"${SERVICE[@]}" /bin/mkdir -m 0700 "$S" < /dev/null
"${SERVICE[@]}" /usr/bin/git init --bare -q "$S/closure.git" < /dev/null
"${SERVICE[@]}" "${ENTRY[@]}" prepare --root "$APP" --bundle "$BUNDLE" \
  --bundle-sha256 "$BUNDLE_SHA256" --base "$BASE" --target-ref refs/heads/maintenance \
  < /dev/null | save_sealed "$S/source-prepared.json"
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api._maintenance_source import SOURCE_HASHES, SourcePin, read_bounded
p = SourcePin.model_validate_json(read_bounded(Path(sys.argv[1]), 8192))
retained = SourcePin.model_validate_json(read_bounded(Path(sys.argv[2]) / "source-pin.json", 8192))
assert p == retained and p.base_commit == sys.argv[3] and p.bundle_sha256 == sys.argv[4]
assert p.target_ref == "refs/heads/maintenance" and p.sources == SOURCE_HASHES
print(json.dumps({"source_prepared": True, "base": p.base_commit, "bundle_sha256": p.bundle_sha256}, sort_keys=True))' \
  "$S/source-prepared.json" "$APP" "$BASE" "$BUNDLE_SHA256" < /dev/null
```

Require successful installed entry import and positive source pin matching
reviewed bundle/base/hash. Prepare refuses existing APP, mutable metadata
aliases, unexpected consumer bytes or an existing vector contribution.
Failure preserves partial state and stops; no deletion or reuse. No N5 fixture,
second host smoke, fake provider or vendor model turn runs here.

## P8: genuine-provider preflight and exact private preview

Repeat HS H2, load_final_qualification, g9 accepted/check_sealed and the recorded
boot/custody check. Preflight assembles the genuine installed WRITE provider
and actual workspace/gate pins, without a model request. Run once into an
absent private preview path:

```bash
"${SERVICE[@]}" "${ENTRY[@]}" preflight --root "$APP" "${HOST[@]}" \
  --authorization-id "$ID" --actor "$ACTOR" --key "$KEY" \
  < /dev/null | save_sealed "$S/preflight.json"
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.core.maintenance import MaintenanceAttemptAuthorization
raw = Path(sys.argv[1]).read_bytes()
assert 0 < len(raw) <= 8192
a = MaintenanceAttemptAuthorization.model_validate_json(raw)
assert a.authorization_id == sys.argv[3] and a.actor_id == sys.argv[4] and a.idempotency_key == sys.argv[5]
assert a.journal == sys.argv[2] + "/maintenance.sqlite"
assert a.attempt_record == sys.argv[2] + "/maintenance-attempt.json"
assert a.request.base_commit == sys.argv[6] and a.request.target_ref == "refs/heads/maintenance"
assert a.scope.segments == ("constructicon-plan-manifest-maintenance", "writer") and a.binding == "executor"
assert a.capability_id == "codex-operator" and a.max_epoch == 1
assert a.workspace.capability_id == "maintenance-workspace" and a.gate.capability_id == "maintenance-gate"
assert datetime.now(timezone.utc) < a.not_after
print(json.dumps({"preview_sha256": hashlib.sha256(raw).hexdigest(), "run_id": str(a.run_id),
    "authorization_id": a.authorization_id, "base": a.request.base_commit,
    "source_graph_hash": str(a.source_graph_hash), "application_revision": str(a.application_revision),
    "revision": a.revision, "operator_binding_digest": str(a.operator_binding_digest),
    "workspace": a.workspace.model_dump(mode="json"), "gate": a.gate.model_dump(mode="json"),
    "not_after": a.not_after.isoformat(), "grants": a.grants.model_dump(mode="json")}, sort_keys=True))' \
  "$S/preflight.json" "$APP" "$ID" "$ACTOR" "$KEY" "$BASE" < /dev/null
```

Review the printed bounded pin whitelist and actual preview digest before P9;
keep full locator-bearing preview private. Its purpose is
plan-manifest-maintenance, not qualification-write. Expiry is one hour from
preflight, not N5's two-hour window; no --hours/--timeout/--fixture flag exists.
Preflight is a proposal, not installed authority or live acceptance. Stop if
the window/pins/custody change; do not edit or remint authority in this session.

## P9: install exact reviewed preview as fresh root authority

Only after the session's pin review, with the same actual boot/pins/custody,
replace PREVIEW_SHA256 below with the literal digest approved from P8, then
install the exact preview bytes. Copy this literal into P10's reviewed step
too; never compute the expected digest from the current file. Require the
entire maintenance authority directory absent, so no existing parent metadata
is normalized. The authority lives outside the launch root, whose exact entry
inventory must remain valid. The unprivileged check reuses the store's
ancestor-custody primitive on A's actual grandparent, `/var/lib`, before any
root write. Root runs only these fixed stock commands:

```bash
PREVIEW_SHA256=UNREVIEWED
[[ "$PREVIEW_SHA256" =~ ^[0-9a-f]{64}$ ]] \
  || { echo 'approved literal preview digest required; stop' >&2; exit 1; }
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import hashlib, os, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api._maintenance_source import read_bounded
from constructicon.substrate.executors.operator_store import _open_trusted_directory
assert hashlib.sha256(read_bounded(Path(sys.argv[1]), 8192)).hexdigest() == sys.argv[2]
os.close(_open_trusted_directory(Path(sys.argv[3]).parent.parent))
print("reviewed-preview-and-root-checked")' "$S/preflight.json" "$PREVIEW_SHA256" "$A" < /dev/null \
  | /usr/bin/grep -qxF reviewed-preview-and-root-checked
sudo -n /usr/bin/test ! -e "${A%/*}" < /dev/null
sudo -n /usr/bin/test ! -L "${A%/*}" < /dev/null
sudo -n /usr/bin/test ! -e "$A" < /dev/null
sudo -n /usr/bin/test ! -L "$A" < /dev/null
sudo -n /usr/bin/install -d -o root -g root -m 0755 "${A%/*}" < /dev/null
sudo -n /usr/bin/install -o root -g m8-service -m 0640 "$S/preflight.json" "$A" < /dev/null
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.substrate.executors.maintenance import read_maintenance_authorization
a = read_maintenance_authorization(Path(sys.argv[1]))
assert Path(sys.argv[1]).read_bytes() == Path(sys.argv[2]).read_bytes()
print("maintenance-authority-installed")' "$A" "$S/preflight.json" < /dev/null \
  | /usr/bin/grep -qxF maintenance-authority-installed
```

No overwrite. The existing reader requires root ownership, mode 0640, one
link, 8192-byte bound and root-owned unwritable nonsymlink ancestors. Another
trusted service-identity process must not rewrite the private preview or
application authority during the session; this is existing single-operator
custody, not a new boundary between mutually hostile service processes.

## P10: one application run, retain verdict and park

Repeat HS H2, load_final_qualification and g9 accepted/check_sealed, recorded
boot/custody and unchanged reviewed preview digest before this one command.
Run reassembles and rechecks actual pins; there is no cached preflight provider.
Store stdout in an absent private file; the command's normal JSON is bounded
by its fixed fields and its refusal contains no private subprocess text:

```bash
PREVIEW_SHA256=UNREVIEWED
[[ "$PREVIEW_SHA256" =~ ^[0-9a-f]{64}$ ]] \
  || { echo 'approved literal preview digest required; stop' >&2; exit 1; }
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import hashlib, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api._maintenance_source import read_bounded
from constructicon.substrate.executors.maintenance import read_maintenance_authorization
preview = read_bounded(Path(sys.argv[1]), 8192)
assert hashlib.sha256(preview).hexdigest() == sys.argv[2]
read_maintenance_authorization(Path(sys.argv[3]))
assert read_bounded(Path(sys.argv[3]), 8192) == preview
print("reviewed-installed-authority-checked")' "$S/preflight.json" "$PREVIEW_SHA256" "$A" < /dev/null \
  | /usr/bin/grep -qxF reviewed-installed-authority-checked
"${SERVICE[@]}" /usr/bin/test ! -e "$S/application-run.json" < /dev/null
"${SERVICE[@]}" /usr/bin/test ! -L "$S/application-run.json" < /dev/null
if "${SERVICE[@]}" "${ENTRY[@]}" run --root "$APP" "${HOST[@]}" --authorization "$A" \
  < /dev/null | save_sealed "$S/application-run.json"
then RUN_EXIT=0; else RUN_EXIT=$?; fi
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.substrate.executors.maintenance import read_maintenance_authorization
raw = Path(sys.argv[1]).read_bytes()
assert 0 < len(raw) <= 8192
r = json.loads(raw)
a = read_maintenance_authorization(Path(sys.argv[2]))
status = int(sys.argv[3])
assert type(r) is dict and type(r.get("accepted")) is bool
if set(r) == {"accepted", "run_id"}:
    assert status == 0 and r["run_id"] == str(a.run_id)
elif set(r) == {"accepted", "error"}:
    assert status == 1 and r["accepted"] is False
    assert r["error"] == "maintenance command refused or incomplete"
else:
    raise ValueError("unexpected maintenance outcome")
print(json.dumps({"accepted": r["accepted"], "run_id": str(a.run_id),
    "meaning": "application-accepted" if r["accepted"] else "application-not-accepted"}, sort_keys=True))' \
  "$S/application-run.json" "$A" "$RUN_EXIT" < /dev/null
```

Run P10 once. Normal accepted false can accompany exit zero; exit alone is
never acceptance. Empty/malformed/missing report, unexpected exit, incomplete
dispatch/capture/gate/publication or any refusal stops with truthful evidence.
Preserve APP's dedicated journal/sidecars, attempt, source authority, candidate,
result, closure state, private preview and installed authority. Never reset an
attempt/journal, delete partial output, refund a turn or dispatch again.

Only for accepted true, inspect the result with the installed entry:

```bash
"${SERVICE[@]}" "${ENTRY[@]}" inspect --result "$APP/maintenance-result.json" < /dev/null
```

The result is historical-application-acceptance, not current qualification.
Run derives exact journal/manifest/attestation, one-file and sole-parent proof
after joining shutdown; a generic successful tree gate is insufficient. Missing
result is a failed publication, not unused budget. No inspection starts recovery.

After command shutdown/evidence preservation, notify and park with clean
`Stop-VM -Name constructicon-m8`; never Save-VM or checkpoint. On an earlier
unexpected output, preserve the partial records and park without continuing.
Report boot, exact revisions/script hashes, physical records, full control
verdicts, preview digest/pin whitelist and bounded outcome on #186 under the
session authority. Keep credentials, account seal, private locators/transcripts
and full authority records private. Accepted candidate export/PR proposal is a
separate normal repository step; this procedure provides no worker merge power.

These local shell tests prove guards/composition/CLI shape only. Linux CI
establishes the exact scripted application path; fresh host qualification and
genuine preflight establish installed assembly; only P10 first observes this
genuine provider executing the application. None substitutes for another.
