# M8 maintenance: fresh private authority after the P8 refusal

Prepared procedure for [#186](https://github.com/sushiHex/constructicon/issues/186),
not host execution evidence. [PR #191](https://github.com/sushiHex/constructicon/pull/191)
merged as `e7d40b139c2a0205f37c7050295a3eca55af9d2c`, tree-identical to reviewed
head `448d763`. Exact-head local verification passed 5,478 tests with 764
platform skips. [Verification and mutations](https://github.com/sushiHex/constructicon/actions/runs/38646967445),
[runner qualification](https://github.com/sushiHex/constructicon/actions/runs/38646967327)
and [all four Linux proof lanes](https://github.com/sushiHex/constructicon/actions/runs/38646967337)
passed, including the native accepting maintenance seam. The
[connector review](https://github.com/sushiHex/constructicon/pull/191#issuecomment-6180866354)
completed at that head with no published findings; this is not formal approval. The source
bundle pins below are prepared locally; final procedure/package revisions and
fresh host facts are still required before execution under the owner's wave
authorization.

This is an additive successor to the frozen
[maintenance session](M8-maintenance-session.md) and
[preservation continuation](M8-maintenance-continuation.md). Neither changes.
The previous boot completed g9 qualification, H7 and applicable H8, prepared
`m8-maint-a1` and `m8-m1`, then stopped at P8. Retained stdout was positively
classified as the fixed refusal. Separate read-only diagnosis affirmed
`source_check:refused`, `source_reason:authority-custody`, all seven installed
artifact fields equal, and `sealed_check:passed`. Eight service-owned Git
entries had group-write bits, with directory modes 0775 and ref/HEAD file modes
0664. This establishes the custody refusal; a launcher-revision mismatch was
not observed. The VM is parked Off with zero checkpoints and custody released.

Retain q9/g9, a1, m1, the old bundle, preview, source records, diagnostics,
operator packages and both existing account/D2 captures. No chmod, repair,
deletion, overwrite or reuse of the refused authority is supplied. The fix
creates a fresh private authority and keeps the original custody guard.
P9/P10 did not run; absence of a model attempt is the recorded session fact,
not an inference from a missing result file.

## C0: prepare literal pins and the new reviewed composition

The owner authorization must name this final procedure, actual merged C,
installed O/D, one fresh start from Off, the fixed verify-kept-launch route,
conditional controller replacement, g10 qualification and every H7 control,
at most one conditional H8 request, the fresh bundle/base/hash and q10/a2/m2
paths, and one exact application attempt. Existing model/callback/byte/epoch,
300-second exchange and one-hour authorization limits remain; observation is
1200 seconds and joined cleanup has no overall wall-clock claim. Token/spend
observations do not supply a finite monetary ceiling.

Before every workstation transport and executed step use this literal guard:

```bash
C=e7d40b139c2a0205f37c7050295a3eca55af9d2c
O=01e816ea441ff8f0cee2fa7b82d83873357e6f51
D=8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3
BASE=e7d40b139c2a0205f37c7050295a3eca55af9d2c
BUNDLE_SHA256=ea40e3715bae7fe7f42d3c2ceb5616864d6d71c1ff4346ffec69f6b5a39a8521
BUNDLE_SIZE=3962468
BUNDLE=/home/m8-service/maintenance-source-e7d40b139c2a0205f37c7050295a3eca55af9d2c.bundle
[[ "$C" =~ ^[0-9a-f]{40}$ && "$O" =~ ^[0-9a-f]{40}$ && "$D" =~ ^[0-9a-f]{40}$ \
   && "$BASE" =~ ^[0-9a-f]{40}$ && "$BUNDLE_SHA256" =~ ^[0-9a-f]{64}$ \
   && "$BUNDLE_SIZE" =~ ^[1-9][0-9]{0,7}$ ]] \
  || { echo 'merged controller and reviewed source pins required; stop' >&2; exit 1; }
test "$C" = "$BASE" && test "$BUNDLE_SIZE" -le 67108864 \
  || { echo 'reviewed controller/base and bundle bound required; stop' >&2; exit 1; }
test "$BUNDLE" != /home/m8-service/UNPREPARED.bundle \
  || { echo 'reviewed immutable bundle path required; stop' >&2; exit 1; }
```

Prepare LF-only common/step packages with fresh absent names beginning
`maintenance-private-`; retain their source headings/revisions, literal
declarations, SHA-256 manifests and each manifest's local hash. Use the
maintenance session P0's reviewed file-upload transport with BatchMode,
strict host keys and closed stdin. Execute uploaded files in fresh shells;
no stdin scripts, interactive paste, eval, sed or runtime rewriting.
LR/HR installers retain their own shell settings, not the N5 common.

Stock Git must affirm that C is the actual merge on main and its tree equals
the final reviewed head. Recompare all six launch blobs from O to C:
`scripts/ci/m8_host_artifacts.py`, the launch AppArmor policy, `_supervisor.py`,
`_egress_bridge.py`, `linux.py` and `.github/workflows/m8-containment.yml`.
The equality was checked at actual merged C. The prepared bundle contains
complete history and advertises exactly `refs/heads/reviewed-source` at BASE.
Stock Git independently fetched it into an empty repository and passed fsck;
its actual size is 3,962,468 bytes and its SHA-256 is the literal above.
All three installed SOURCE_HASHES matched, and
`tests/vectors/plan_manifest.json` was absent. These are local source facts,
not upload, installation, qualification or application evidence. Preserve the
prepared artifact; unknown or changed pins stop.

Reuse frozen [OC](M8-N4-operator-commands.md),
[LR](M8-N4-launch-replacement.md), [HR](M8-N4-host-runtime.md),
[HS](M8-N5-host-session.md), [ER](M8-N5-explicit-refresh.md) and
[D2](M8-D2-host-installation.md). Delegated blocks are copied verbatim with
their documented literal declarations. Complete replacements are below.
This is a new reviewed composition: launch verification has no retirement,
staging, installation or fallback route.

| Step | Exact source and composition |
| --- | --- |
| Historical common | C0 guard, then literal `C=01e816ea441ff8f0cee2fa7b82d83873357e6f51`, OC's two Setup blocks, then `W=/home/m8-service/m8-maint-q9` |
| C1 provenance/capture | Historical common; HS H2; maintenance P1's controller-verifier block at O; review separately, then C1's g9 capture comparison below |
| C2 D2 | New C2 preservation below, then LR2 at verified D in D2's own workspace/fresh shell |
| C2 launch provenance | LR3's two blocks at C/O, archiving current operator launch workspace; no LR4, R12 or LR6 |
| C2 kept-launch check | Complete verification block below in fresh C/W/J shell; require installed true and replacement false or stop |
| C2 controller | LR8 at C/O; only its exact observed-tree refusal permits LR9 followed by HR R17/R18; HR R19 on both routes |
| C2 physical preflight | OC Setup at C; only OC S3's preflight line; require launch_ready true |
| New common | C0 guard, OC's two Setup blocks at C, then C3 declarations below |
| C3 qualification | HS H2, OC S1, OC S4 followed by C3 comparison in the same shell, OC S6a unchanged |
| C4/C5 | Complete floor-9/g10 and H7 replacements below |
| C6 | New common and C6 declarations; ER R1 unchanged, under ER R0/R2 |
| C7 | New common and C7 declarations; complete fresh bundle handoff and preparation below |
| C8 | New common and C7 declarations; complete preflight replacement below |
| C9/C10 | New common and C7 declarations; maintenance P9/P10 verbatim, with approved literal PREVIEW_SHA256 |

## C1: one fresh boot, historical g9 and the retained capture

Reconfirm exclusive operator/root/service-identity custody, including the
pause. Notify before starting. Use this complete P1 start replacement; require
fresh Off and zero checkpoints. No Save-VM, checkpoint, R6, reboot or second
start is supplied:

```powershell
$maintenanceController = 'e7d40b139c2a0205f37c7050295a3eca55af9d2c'
$maintenanceBase = 'e7d40b139c2a0205f37c7050295a3eca55af9d2c'
$maintenanceBundleSha256 = 'ea40e3715bae7fe7f42d3c2ceb5616864d6d71c1ff4346ffec69f6b5a39a8521'
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

Read DHCP, select the reviewed SSH target and record the full boot id. Before
controller replacement repeat HS H2 and the frozen P1 controller verifier at
O; require fresh installed true/state tree/different zero. Then, in a separate
historical-common step, compare the retained account capture to positively
checked q9/g9 evidence. Do not copy the g8 historical prefix or recapture:

```bash
binding_check "$W/g9.sealed.json" reboot-anchor -
load_final_qualification
check_sealed "$W/g9.sealed.json" "$Q"
test "${SEAL%%/*}" = pro \
  || { echo 'historical g9 account is not the qualified pro plan; stop' >&2; exit 1; }
test -n "$SEAL"
/usr/bin/python3 -I -S -B -c 'import os, stat, sys
from pathlib import Path
path = Path(sys.argv[1]); info = path.lstat()
assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
assert info.st_uid == os.getuid() and info.st_mode & 0o077 == 0
assert 0 < info.st_size <= 256
fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
with os.fdopen(fd, "rb") as stream:
    opened = os.fstat(stream.fileno())
    assert (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino)
    raw = stream.read(257)
assert len(raw) == info.st_size and raw == (sys.argv[2] + "\n").encode("utf-8")
after = path.lstat()
assert all(getattr(after, field) == getattr(info, field) for field in
    ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid", "st_size", "st_mtime_ns", "st_ctime_ns"))
print("historical-g9-account-capture-revalidated")' \
  "$HOME/maintenance-g9-account.seal" "$SEAL" < /dev/null
```

Require marker-only stdout, one LF and empty stderr for this comparison. OC
still requires exactly the reboot-anchor refusal, not arbitrary unavailability.
No maintain/activate/vendor lane or second session runs before the controller
is current. The seal remains private; this proves historical continuity only.

## C2: preserve current D2 records and verify the kept launch

Before LR2 overwrites its three current q9-boot records, preserve them in a
new private archive. Keep `maintenance-g9-d2-prior` unchanged; it is an older
archive. Run this separate operator block after C0, without N5 common/root:

```bash
set -Eeuo pipefail
umask 077
/usr/bin/python3 -I -S -B -c 'import os, stat, sys
from pathlib import Path
source, archive = map(Path, sys.argv[1:])
assert source.resolve() == source and stat.S_ISDIR(source.lstat().st_mode)
assert archive.parent.resolve() == archive.parent and not os.path.lexists(archive)
names = ("profiles-verify", "verify.json", "qualification.json")
records = []
for name in names:
    path = source / name; info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 1048576
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        assert (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino)
        raw = stream.read(1048577)
    after = path.lstat()
    assert len(raw) == info.st_size
    assert all(getattr(after, field) == getattr(info, field) for field in
        ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid", "st_size", "st_mtime_ns", "st_ctime_ns"))
    records.append(raw)
archive.mkdir(mode=0o700)
for name, raw in zip(names, records, strict=True):
    fd = os.open(archive / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    assert (archive / name).read_bytes() == raw and (source / name).read_bytes() == raw
assert {path.name for path in archive.iterdir()} == set(names)
print("g9-boot-d2-records-preserved")' \
  "$HOME/m8-host" "$HOME/maintenance-g10-d2-prior" < /dev/null
```

Require exit zero, exactly that marker plus LF and empty stderr. Failure keeps
partial archive and all sources; it grants no deletion, repair or second copy.
Run LR2 verbatim at D; require affirmative installed true and qualified true
on this boot, then fresh bare drift check zero/NO DRIFT. No R6 or drift repair.

Run LR3's preconditions and R11 variant at C/O in their own fresh shells.
Archive the old operator launch workspace under its actual O; do not retire
the installed launch. Fresh source provenance and pinned downloads feed the
following check; no old staging or retire.json is copied. With the fresh
`W=$HOME/m8-launch`, execute this complete new verification block:

```bash
set -Eeuo pipefail
J=(/usr/bin/python3 -I "$W/m8_host_artifacts.py")
test "${#C}" -eq 40
sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$W/profiles-verify"
if "${J[@]}" verify-launch "$C" "$W" < "$W/profiles-verify" > "$W/verify.json"
then KEPT_EXIT=0; else KEPT_EXIT=$?; fi
/usr/bin/python3 -I -S -B -c 'import json, sys
from pathlib import Path
r = json.loads(Path(sys.argv[1]).read_bytes())
assert sys.argv[2] == "0" and r["installed"] is True and r["replacement"] is False
print("kept-launch-verified")' "$W/verify.json" "$KEPT_EXIT" < /dev/null
```

Require the full verifier record's affirmative provenance and installed
comparison, the marker, exit zero and declared clean diagnostics before LR8.
Failure stops; it cannot select LR4/LR6, a launch install, drift normalization
or a wider route. A kept launch is measured by fresh verification at C, not
assumed from equal source blobs. The store is retained and never listed.

Run LR8 at C/O. Only installed false/observed state tree/different greater
than zero permits the exact LR9 block followed by HR R17/R18 at C. Require
R18 installed true/different zero. Run HR R19 on both routes. No checkpoint
or R16. Then OC S3's preflight line alone under OC Setup at C must affirm
launch_ready true with its benign physical attachment. No login/provision.

## C3: fresh q10 and checked historical account continuity

Append these declarations to OC's two Setup blocks at C in each new common:

```bash
W_PRIOR=/home/m8-service/m8-maint-q9
W=/home/m8-service/m8-maint-q10
PRIOR_SEAL="$(/usr/bin/cat -- "$HOME/maintenance-g9-account.seal")"
```

Repeat HS H2. Execute OC S1 into absent W, then OC S4 and this complete
comparison in the same shell, then OC S6a unchanged:

```bash
test "$S4_SEAL" = "$PRIOR_SEAL" \
  || { echo 'fresh S4 account differs from historical checked g9; stop' >&2; exit 1; }
```

Require complete producer records, positive held lock, the exact competing
maintenance refusal and joined held startup. Historical q9 cannot qualify C.
The next generation comes only from both checked strict floor-9 facts below.

## C4: checked floor 9, publish and activate g10

```bash
load_final_qualification
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, sys
from pathlib import Path
for name in ("s4-qualification.json", "s6a-qualification.json"):
    custody = json.loads((Path(sys.argv[1]) / name).read_bytes())["custody"]
    assert custody["kind"] == "maintenance"
    assert type(custody["generation_floor"]) is int and custody["generation_floor"] == 9
print("maintenance-floor-9-checked")' "$W" < /dev/null \
  | /usr/bin/grep -qxF maintenance-floor-9-checked
"${ROOT_STORE[@]}" publish --store-root "$R" --key "$K" --generation 10 \
  --qualification-evidence-digest "$Q" --service m8-service --wait 0 \
  < /dev/null | save_sealed "$W/g10.sealed.json"
check_sealed "$W/g10.sealed.json" "$Q"
"${ROOT_STORE[@]}" activate --store-root "$R" --key "$K" --generation 10 \
  --sealed "$W/g10.sealed.json" --qualification-evidence-digest "$Q" \
  --service m8-service --wait 0 < /dev/null
binding_check "$W/g10.sealed.json" accepted -
binding_check "$W_PRIOR/g9.sealed.json" stale-generation "$W/g10.sealed.json"
```

Missing, bool, float or any other floor stops before publication. Do not infer
the floor from filenames or reuse the g9 qualification digest for changed C.

## C5: complete H7 and explicit checked refresh selection

This complete H7 replacement preserves every control and verdict law in
maintenance P5. A checker failure never means unmeasured refresh:

```bash
load_final_qualification
"${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g10.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-g10-lane" --evidence "$W/h7-g10-active.json" < /dev/null
ACTIVE_Q="$(check_evidence active "$W/h7-g10-active.json" active "$SEAL" "$W/startup-policy.json")"
ACTIVE_REFRESH="$("${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api._maintenance_source import read_bounded
from constructicon.core.identity import digest, parse_json_value
from constructicon.substrate.executors.codex_lane import EVIDENCE_DOMAIN
r = parse_json_value(read_bounded(Path(sys.argv[1]), 1048576).decode("utf-8", errors="strict"))
assert str(digest(EVIDENCE_DOMAIN, 1, r)) == sys.argv[2]
assert type(r) is dict and type(r.get("refresh")) is str and r["refresh"] in ("measured", "unmeasured")
print(r["refresh"])' "$W/h7-g10-active.json" "$ACTIVE_Q" < /dev/null)"
case "$ACTIVE_REFRESH" in
  measured)
    REFRESH_Q="$(check_evidence refresh "$W/h7-g10-active.json" active "$SEAL" "$W/startup-policy.json")"
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
  "$W/startup-policy.json" "$W/h7-g10-no-chatgpt-policy.json" < /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g10.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/h7-g10-no-chatgpt-policy.json" \
  --lane-dir "$W/h7-g10-s6b-lane" --evidence "$W/h7-g10-s6b-denial.json" --expect-denial \
  < /dev/null; then echo 'S6b unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence denial "$W/h7-g10-s6b-denial.json" active "$SEAL" "$W/h7-g10-no-chatgpt-policy.json" > /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g10.sealed.json" --expected "plus/${SEAL#*/}" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-g10-s6c-lane" --evidence "$W/h7-g10-s6c-plan-refusal.json" \
  < /dev/null; then echo 'S6c unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence wrongplan "$W/h7-g10-s6c-plan-refusal.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
binding_check "$W_PRIOR/g9.sealed.json" stale-generation "$W/g10.sealed.json"
```

S6b requires exactly positive denied:destination and the four declared faults;
EOF-only, destination plus EOF or extra faults stop. S6c requires its exact
wrong-plan refusal. Finish every control even when active refresh was measured.

## C6: at most one conditional H8 request

Only after C5 completed every control and explicitly printed
refresh-unmeasured, use these declarations with new common and ER R1 verbatim.
refresh-measured omits H8. Missing verdict or failed checker stops:

```bash
SEALED="$W/g10.sealed.json"
REFRESH_LANE="$W/h8-g10-explicit-lane"
REFRESH_EVIDENCE="$W/h8-g10-explicit-refresh.json"
```

ER R0/R2 remain unchanged: same boot/custody/pins, schema-5 producer record,
digest and verdict; no OC schema-4 check on explicit evidence. Unmeasured,
faulty, missing or unexpected output stops. No second refresh attempt,
natural-refresh fallback, token request, manufactured 401 or expiry edit.
Review complete H7/applicable H8 evidence before application preparation.

## C7: fresh closure, source bundle and authority

Append these complete declarations to new common:

```bash
S=/home/m8-service/m8-m2
APP=/home/m8-service/m8-maint-a2
A=/var/lib/constructicon-m8-maintenance-2/application-2.json
ID="maintenance-2-$C"
ACTOR=operator:maintenance-2
KEY=maintenance-2
ENTRY=("${PY[@]}" constructicon.api.maintenance_entry)
HOST=(--session "$W" --store-key "$K" --sealed "$W/g10.sealed.json"
  --qualification "$W/s6a-qualification.json" --state "$S" --launch-root "$L")
```

Repeat HS H2, load_final_qualification and g10 accepted/check_sealed, plus
the recorded boot/custody check. Fresh reviewed P7 package includes common,
step, bundle and their SHA-256 manifest. Transfer the prepared literal artifact
as service, without changing home custody:

```bash
SOURCE_UPLOAD="$HOME/maintenance-private-p7-package/maintenance-source-e7d40b139c2a0205f37c7050295a3eca55af9d2c.bundle"
test -f "$SOURCE_UPLOAD" && test ! -L "$SOURCE_UPLOAD"
test "$(/usr/bin/stat -c %s -- "$SOURCE_UPLOAD")" -eq "$BUNDLE_SIZE"
/usr/bin/sha256sum --binary -- "$SOURCE_UPLOAD" < /dev/null \
  | /usr/bin/grep -qxF "$BUNDLE_SHA256 *$SOURCE_UPLOAD"
"${SERVICE[@]}" /usr/bin/test ! -e "$BUNDLE" < /dev/null
"${SERVICE[@]}" /usr/bin/test ! -L "$BUNDLE" < /dev/null
"${SERVICE[@]}" /bin/sh -c 'set -Ceu; umask 077; cat >"$1"' sh "$BUNDLE" < "$SOURCE_UPLOAD"
"${SERVICE[@]}" /usr/bin/test -f "$BUNDLE" < /dev/null
"${SERVICE[@]}" /usr/bin/test ! -L "$BUNDLE" < /dev/null
"${SERVICE[@]}" /usr/bin/sha256sum --binary -- "$BUNDLE" < /dev/null \
  | /usr/bin/grep -qxF "$BUNDLE_SHA256 *$BUNDLE"
echo maintenance-bundle-transferred
```

Only the positive marker and clean diagnostics permit this preparation block:

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

Require installed import and positive exact source pin. New source creation
uses explicit Git init --shared=0600, the child-private creation mask and
pinned sharedRepository=0600. It does not change the parent mask or repair a1.
No old state is reused. Any incomplete
transfer/preparation stops and retains partial bytes; no retry or new host
smoke/fake provider/model request is supplied.

## C8: retain preflight and display its closed failure stage

Repeat HS H2, load_final_qualification, g10 accepted/check_sealed and actual
boot/custody checks. This complete P8 replacement runs the genuine installed
provider assembly once, with no model request. It captures both pipeline
statuses before any other command, preserving stdout in the absent private
preview even when the CLI refuses. A failed saver is never a CLI refusal fact:

```bash
"${SERVICE[@]}" /usr/bin/test ! -e "$S/preflight.json" < /dev/null
"${SERVICE[@]}" /usr/bin/test ! -L "$S/preflight.json" < /dev/null
if "${SERVICE[@]}" "${ENTRY[@]}" preflight --root "$APP" "${HOST[@]}" \
  --authorization-id "$ID" --actor "$ACTOR" --key "$KEY" \
  < /dev/null | save_sealed "$S/preflight.json"
then P8_STATUS=("${PIPESTATUS[@]}"); else P8_STATUS=("${PIPESTATUS[@]}"); fi
test "${#P8_STATUS[@]}" -eq 2
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import hashlib, json, os, stat, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api._maintenance_source import read_bounded
from constructicon.core.identity import parse_json_value
from constructicon.core.maintenance import MaintenanceAttemptAuthorization
try:
    assert sys.argv[8] == "0"
    path = Path(sys.argv[1]); info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    assert info.st_uid == os.getuid() and info.st_mode & 0o077 == 0
    raw = read_bounded(path, 8192)
    assert 0 < len(raw) <= 8192
    if sys.argv[7] == "1":
        r = parse_json_value(raw.decode("utf-8", errors="strict"))
        assert type(r) is dict and set(r) == {"accepted", "error", "stage"}
        assert r["accepted"] is False and r["error"] == "maintenance command refused or incomplete"
        assert type(r["stage"]) is str and r["stage"] in ("source", "assembly", "preview", "unknown")
        print(json.dumps({"preflight": False, "stage": r["stage"]}, sort_keys=True))
        raise SystemExit(1)
    assert sys.argv[7] == "0"
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
        "not_after": a.not_after.isoformat(), "grants": a.grants.model_dump(mode="json")}, sort_keys=True))
except Exception:
    print(json.dumps({"preflight": False, "stage": "unknown"}, sort_keys=True))
    raise SystemExit(1) from None' \
  "$S/preflight.json" "$APP" "$ID" "$ACTOR" "$KEY" "$BASE" \
  "${P8_STATUS[0]}" "${P8_STATUS[1]}" < /dev/null
```

On refusal require the closed false/stage record and exit one, then stop and
park; no P9, retry or cleanup follows. Malformed/empty/oversized/old-format
output, failed saver, unexpected status or unsuccessful validation produces
unknown and stops. Retain the private preview and all partial state. Review
stderr separately: no exception text becomes a declared stage or permission
to continue. Successful exit zero prints only P8's existing bounded pin
whitelist. Full preview remains private; a proposal is not installed authority.

## C9/C10: exact reviewed authority, one attempt and park

Only after complete H7/H8 review and successful C8 pin review, execute frozen
maintenance P9/P10 command fences verbatim with C7's fresh declarations.
Replace P10's old prerequisite prose with this explicit current-generation
requirement: repeat HS H2, load_final_qualification, g10 accepted/check_sealed,
the recorded boot/custody check and unchanged approved literal preview digest.
The same actual boot, installation and reviewed pins must still hold before
the one application command. The historical g9 prerequisite is not delegated.
Put the approved literal PREVIEW_SHA256 in both reviewed
step packages; never compute its expected value from current bytes. The new
root authority directory is outside the launch root and must be absent.
P9's stock root writes and exact reader remain unchanged. Run P10 at most once
with its own existing authorization, fixed data exam and observation/cleanup
limits. Inspect only accepted historical result; no recovery dispatch, merge,
push, promotion, second attempt or refund is supplied.

Unexpected output stops at every boundary, including exit-zero commands.
Keep all old/new journals, sidecars, attempts, bundles, authorities, results,
candidates, store evidence and operator packages. Notify, preserve evidence
and cleanly Stop-VM; never Save-VM or checkpoint. Post only bounded public
facts on #186 under session authority, with exact revisions/hashes/boot,
verifier/physical records, H7/H8 verdicts, approved pin whitelist and outcome.
Keep credentials, seals, private locators/transcripts and full authority
records private. An accepted contribution PR is a separate ordinary repository
step; the worker has no installation, push or merge capability.

Before execution record the final procedure/package hashes and reconfirm the
owner-authorized scope and fresh custody/boot/installation facts. Prepared
source pins and credential-free proof do not supply those host observations.
This procedure alone authorizes no host action.
