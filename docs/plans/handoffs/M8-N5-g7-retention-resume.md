# M8 N5 g7: resume after the retained-authorization refusal

Status: deployment package for separate owner review and host authorization.
The target controller is PR #160's verified squash commit
`f6cd85a6ed247fdcbb44dc002b8a99fdf18f1324` (`C`), whose tree is byte-identical
to reviewed and checked `58db676`. This document authorizes no host action.
Do not substitute a PR head or a later main head. The target code pin and this
procedure's later reviewed documentation revision are separate artifacts;
this pinned procedure is not an artifact present at `C`. Frozen source
documents retain their bytes.

This continues [#78](https://github.com/sushiHex/constructicon/issues/78) and
implements the bounded resume scope of
[#159](https://github.com/sushiHex/constructicon/issues/159). The refusal is a
pre-existing lifecycle composition defect, not a reason to waive an inventory
guard or remove authorization history. No installed root path was written by
the refused LR4 chain. That is the recorded disposition of the verified chain,
not an inference from an empty error list.

## Recorded pause and source map

These are recorded inputs, not a fresh observation of the host:

- `O=585df33eb196cd4afd10d5c12cb1efb37fd5a6e1`: still-installed launch and
  controller; original launch workspace archived as `$HOME/m8-launch-$O`.
- `P=d22bff86e8695a7efef04dc3f47c6d4b0847599c`: successful paused R11
  provenance in `$HOME/m8-launch`, followed by the specific LR4 refusal.
- `D=8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3`: installed D2 qualification.
- `B=d8d9e311-6b35-4d6a-aaeb-cb11c86c5084`: clean boot, LR1 reboot-anchor
  refusal and LR2 D2 passing records plus no drift; no maintenance followed.
- The checked preboot g6 continuity file remains private at
  `$HOME/n5-g7-account.seal`. The g6 active binding is reboot-invalid.
- `$HOME/m8-controller` still belongs to `O`; LR8/controller archival never
  ran. The fresh g7 maintenance directory has not been created.

The base [g7 procedure](M8-N5-g7-session.md) supplies the unchanged generation,
continuity and WRITE gates. Its original `C=P` is superseded **only for this
authorized resume** by the actual merged retention-fix `C`; it is not edited.
At that new `C`, mechanically copy the named blocks from
[LR](M8-N4-launch-replacement.md),
[host runtime](M8-N4-host-runtime.md) (HR),
[OC](M8-N4-operator-commands.md),
[HS](M8-N5-host-session.md),
[ER](M8-N5-explicit-refresh.md), and
[WRITE](M8-N5-write-session.md) (WS). Old-controller OC continuity checks still
use `O`, and D2 records still use `D`. Never judge old g6 evidence at new `C`.

The source map for the reviewed package is:

| Script | Composition |
| --- | --- |
| Resume-check | Exact `C=O`, old-controller OC setup with g7 prior `W`, this document's boot check, HS H2 block, g7 LR1 anchor override |
| Resume-archive | Exact new `C`, the complete archive guard below |
| Resume-preconditions | LR3 first block's unchanged suffix from `Q='constructicon-m8-bwrap (enforce)` through `echo "LR3 passed"` |
| R11 | LR3 second Bash block at new `C`, fresh canonical launch workspace |
| LR4/LR5/LR6 | LR4 / HR R12 / LR6 unchanged, declaring `C`, launch `W` and required `J` in each fresh shell |
| LR8 | LR8 unchanged, new `C`, **original `O`** for controller archive |
| LR9, R17/R18/R19 | Conditional LR9, then each HR block unchanged in its own fresh shell at new `C` |
| LR7 | OC setup at new `C` plus only S3's preflight line; no login |
| H2-H8 | New-controller common and exact g7 declarations/blocks; HS H2, OC S1/S4/S6a, and ER R1 as the g7 procedure specifies |
| W0-W6 | New-controller common, `SEALED="$W/g7.sealed.json"`, WS blocks unchanged |

Record each source revision, heading, selected block/suffix, declaration and
resulting script hash. The preconditions selection is an explicit additive
LR3 override, not permission to rewrite frozen blocks at runtime. No `sed`,
substitution or `eval` generates the package. Keep installation shell settings:
no N5 common file and no added `pipefail` in LR/HR scripts. LR0 is authorization,
not an executable block. No R9/R16 checkpoint commands are supplied.

## Authorization, boot continuity and immutable transport

The owner's separate resume authorization must name this exact revision,
actual merged `C`, `P/O/D/B`, the recorded pause, continuous exclusive custody,
this one workspace archive, new provenance, complete LR route and g7 controls.
Affirmatively confirm no maintenance, activation, account/model acquisition,
second session or intervening administrator since the controlled boot. A
process scan is not that proof. This is continuation of the same paused wave,
not a second qualification session.

Require the exact full boot ID before any write:

```bash
C=585df33eb196cd4afd10d5c12cb1efb37fd5a6e1
source "$HOME/n5-g7-prior-common.sh"
B=d8d9e311-6b35-4d6a-aaeb-cb11c86c5084
test "$(/usr/bin/cat /proc/sys/kernel/random/boot_id)" = "$B" \
  || { echo 'paused boot changed; stop for owner review' >&2; exit 1; }
```

Repeat HS H2's noninteractive sudo and bare drift checks. Require affirmative
passing output, and retain the existing passing LR1/LR2 records for this boot.
The old-controller LR1 reboot-anchor check may be repeated read-only; never
try `accepted` on the reboot-invalid g6 binding. No recapture, overwrite or
posting of the private preboot seal. Drift, changed boot or uncertain custody
stops for the owner. R6 is not authorized. A different boot needs a separately
reviewed route and fresh LR1/LR2 records; it is not a fallback supplied here.

Resume-check alone declares `C=O` and sources only the old-controller common;
that read-only setup supplies fail-closed shell settings before any check.
Every subsequent script declares exact new `C` and runs in a fresh shell. The
workstation guard below refuses an invalid pin before any transport. Use g7
H0's LF-only, SHA-256 common/step-pair transport discipline unchanged,
with strict host-key checking, BatchMode, and SSH execution stdin `/dev/null`.
Hash each installer file as the file actually executed; it has no N5 common.

```bash
C=f6cd85a6ed247fdcbb44dc002b8a99fdf18f1324
[[ "$C" =~ ^[0-9a-f]{40}$ ]] \
  || { echo 'retention-fix controller pin is invalid; stop for review' >&2; exit 1; }
```

## Complete LR3 workspace-resume override

Run only after the boot/custody/drift gates. This replaces LR3's old-workspace
archive operation, which already completed. The old archive and controller
workspace must be real private operator directories, and the controller's
old archive must still be absent. Check the precise paused refusal, its
affirmative provenance, and the script bytes pinned at `P` before moving.
The hash below is the raw `P:scripts/ci/m8_host_artifacts.py` blob, not the new
fix's script. Cached main may have advanced since `P`; no current-main equality
is claimed. No credential, authorization or installed-root contents are read.

```bash
umask 077
: "${C:?Reviewed merged retention-fix commit required}"
P=d22bff86e8695a7efef04dc3f47c6d4b0847599c
O=585df33eb196cd4afd10d5c12cb1efb37fd5a6e1
W="$HOME/m8-launch"
ARCHIVE="$HOME/m8-launch-refused-$P"
[[ "$C" =~ ^[0-9a-f]{40}$ ]] && test "$C" != "$P" && test "$C" != "$O" \
  && /usr/bin/python3 -I -S -B -c 'import hashlib, json, os, stat, sys
from pathlib import Path
home, p, o = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
w = home / "m8-launch"
archive = home / ("m8-launch-refused-" + p)
uid = os.getuid()
def directory(path):
    info = os.lstat(path)
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == uid
    assert stat.S_IMODE(info.st_mode) == 0o700 and path.resolve(strict=True) == path
def regular(path):
    info = os.lstat(path)
    assert stat.S_ISREG(info.st_mode) and info.st_uid == uid and info.st_nlink == 1
    assert stat.S_IMODE(info.st_mode) == 0o600
    return path.read_bytes()
directory(w)
directory(home / ("m8-launch-" + o))
directory(home / "m8-controller")
assert not os.path.lexists(archive)
assert not os.path.lexists(home / ("m8-controller-" + o))
assert not os.path.lexists(w / "staging")
r = json.loads(regular(w / "retire.json"))
assert r["schema_version"] == 2 and r["command"] == "judge-retire" and r["commit"] == p
assert r["ready"] is False and r["first_parent"] is True and r["script_matches_commit"] is True
assert r["failure"] == "ValueError: /var/lib/constructicon-m8-launch holds entries the retirement does not name: [\u0027qualification\u0027]"
sha = "f0aa7b3a6e904f04c504e243114ce4b3a9ca99c48326c9c7259c1f9623399ded"
assert r["blobs"]["scripts/ci/m8_host_artifacts.py"]["sha256"] == sha
assert hashlib.sha256(regular(w / "m8_host_artifacts.py")).hexdigest() == sha
v = json.loads(regular(w / "vendor.json"))
assert v["schema_version"] == 2 and v["command"] == "vendor-inputs" and v["commit"] == p
assert v["listed"] is True and v["first_parent"] is True and v["script_matches_commit"] is True
assert v["blobs"]["scripts/ci/m8_host_artifacts.py"]["sha256"] == sha
print("paused-workspace-checked")' "$HOME" "$P" "$O" < /dev/null \
  | /usr/bin/grep -qxF paused-workspace-checked \
  && test ! -e "$ARCHIVE" && test ! -L "$ARCHIVE" \
  && /usr/bin/mv -n -- "$W" "$ARCHIVE" \
  && test ! -e "$W" && test ! -L "$W" \
  && test -d "$ARCHIVE" && test ! -L "$ARCHIVE" \
  && echo paused-workspace-preserved
```

Require status zero and `paused-workspace-preserved`. Existing archive,
symlink, different custody/provenance, other refusal, missing evidence or
partial later failure stops. Preserve both workspace archives; never remove,
overwrite, retarget or repair them. A move followed by later failure is a
recorded stopped state, not permission to rerun this move or refund an attempt.

Then run Resume-preconditions from the source map: the unchanged LR3 suffix
rechecks all host prerequisites and requires the canonical workspace absent.
Require `LR3 passed` before the unchanged R11 block creates fresh provenance at
new `C`. Do not reuse the paused source repository, catalog, tarball or script
as new-commit evidence. R11 must affirm first-parent membership, pinned blob
extraction, derived inputs/digests and `R11 complete` at the actual new `C`.

## Installation, g7 and the one WRITE

Continue LR4, LR5/HR R12, LR6, LR8, conditional LR9/HR R17-R19, then LR7,
using the source map and original `O` for controller archival. An arbitrary
LR8 failure is not authorization: LR9 requires `installed` false and observed
controller `state` equal to `tree` with `different` greater than zero. Require
every affirmative retirement, staging, installation, verification and probe
record; the final script exit alone is insufficient. No maintenance or lane
startup until the controller is current. LR7 is preflight only, never login.

Prepare the new-controller g7 common file from OC's two Setup blocks at new
`C` plus the g7 H2-H5 declarations. Use fresh `/home/m8-service/m8-n5-stage2g7`,
the retained checked private g6 seal, fresh qualification digest and generation
7. Resume g7 H2-H7 unchanged; all H7 controls run even if refresh is measured.
Destination denial must be positive and exclusive; EOF-only or destination
plus EOF stops. H8 is omitted if this H7 measured refresh, otherwise at most
one separately authorized ER R1 attempt. Preserve schema-5 evidence/digest/
verdict; never pass it through the schema-4 checker or reuse old g6 refresh.

After the owner reviews the complete g7 evidence, declare
`SEALED="$W/g7.sealed.json"` and use WS W0-W6 unchanged. Pause after W4 for
review of exact minted pins and smoke verdict before W5 root installation.
One W6 turn, fixed grants/checker/check/window/observation, no automatic retry
or recovery. No READ rerun/T6, shared N5 retry or token/credential inspection.
The qualification directory, store and prior authorization history are retained;
this archive block never reaches them or resets spent state.

## Evidence and limits

Record the authorization, reviewed revisions/hashes, current boot/custody/drift,
preserved workspace paths, fresh new-commit provenance and complete LR/g7/WRITE
results on #78. Keep private seals, locator-bearing authorizations and diagnostic
state private. Never post credentials, account identifiers, model/callback text
or raw journal/gate contents. Fake-shell tests establish composition and stops
only; they do not establish a host state, installation or vendor qualification.
