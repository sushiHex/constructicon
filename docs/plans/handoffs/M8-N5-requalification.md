# M8 N5: Stage 2 requalification into g5

Status: successor instructions under review for the owner-approved Stage 2
correction and fresh requalification. This document authorizes no action by
itself. Use only with a separate owner authorization naming this document, OC,
LR, M8-D2 and the final merged commit `C`. `C` is assigned after the protocol
correction merges; do not substitute the current planning or failed-run commit.
The old host session ran at full commit
`8a0d87d5fca531f747092cf7c99abc5e502097b8`. Accepted plan bytes and the
existing HS, RS and LR bytes stay intact. OC is used at its exact checked-in
version at `C`, including the checker correction in this change.

The prior Stage 2 attempt at `8a0d87d5fca531f747092cf7c99abc5e502097b8` left `/home/m8-service/m8-n5-stage2`
with active g4 and a failed H7 wrong-plan check. That H7 result is not evidence
for this run. The correction requires a fresh boot/controller at `C`, fresh
Stage 2 directory, new maintenance qualification, and generation g5. The old
g4's checked S6a account seal is carried across the controller change so the
new S4 must observe the same account.

This document reuses the named blocks from
`M8-N4-operator-commands.md` (OC),
`M8-N4-launch-replacement.md` (LR),
`M8-N5-host-session.md` (HS), and
`M8-N5-read-session.md` (RS). Unless an override below says otherwise, run
those blocks at the exact bytes present at `C`, except for explicit overrides
below. Do not modify HS, RS or LR, or construct replacement blocks with `sed`,
substitutions, or generated text. OC's checker is intentionally updated in
this change; use its checked block at `C` unchanged.

## Before LR's reboot: preserve the old account seal

Use the current OC setup plus HS's existing `How to run` override, so `W` is
`/home/m8-service/m8-n5-stage2`. Run this block before LR1's reboot, while the
old controller is installed and the current boot still accepts g4. It reads the
old S4/S6a records only; it writes no file under the old `W`.

```bash
binding_check "$W/g4.sealed.json" accepted -
load_final_qualification
check_sealed "$W/g4.sealed.json" "$Q"
test "${SEAL%%/*}" = pro \
  || { echo 'prior S6a plan is not N4-qualified pro; stop' >&2; exit 1; }
test -n "$SEAL"
set -C
printf '%s\n' "$SEAL" > "$HOME/n5-g5-account.seal"
```

`check_sealed` binds g4 to the digest `Q` returned by the checked S6a record;
the plan guard preserves the existing N4 `pro` continuity decision. The
private owner-home file is create-exclusive under OC setup's `umask 077`.
If it already exists, stop; do not overwrite it or reuse a partial attempt.
`SEAL` is read only after OC checked the prior S4/S6a evidence under the old
adapter and protocol revisions. Do not print or post it. After the new
controller is installed, the current checker will require current adapter and
protocol revisions, so do not silently re-check old evidence with it.

## Authorization and common file after LR

The owner authorization names `C`, this successor, OC, LR and the M8-D2
requalification/baseline steps. It also names continuity with the private
pre-reboot seal and the fresh generation g5. Run LR's Order exactly: LR0 to
LR6, LR8, LR9 if LR8 refused, then LR7; include LR2's separately authorized
host qualification. In LR1, before anything replaces the controller, use the
old controller and the current N5 g4 descriptor for the boot-anchor refusal.
Do not add `set -o pipefail` to LR commands or run lane/store commands before
the controller is current.

For LR's old workspace commit `O`, the preceding successful installation used
`8a0d87d5fca531f747092cf7c99abc5e502097b8` for both launch and controller
workspaces. Verify those workspaces and the installed records before using
that value; a recorded previous value is not proof of unchanged host state.

The LR1 anchor command is:

```bash
binding_check "$W/g4.sealed.json" reboot-anchor -
```

For the post-LR N5 sessions, create `n5-g5-common.sh` as OC's two Setup blocks
followed by this exact override. The `PRIOR_SEAL` assignment reads data into a
quoted shell variable; it never evaluates the file as shell code. Its value is
validated by equality with the freshly checked S4 seal in H4.

```bash
W_OLD=/home/m8-service/m8-n4-session
W_PRIOR=/home/m8-service/m8-n5-stage2
W=/home/m8-service/m8-n5-stage2r
PRIOR_SEAL="$(/usr/bin/cat -- "$HOME/n5-g5-account.seal")"
```

Use the fresh `W` for H3 onward. Do not repair, reuse, or write into `W_PRIOR`.
Keep `W_OLD` only for the original N4 history; g4 is now the immediately
previous generation.

## H0-H5: authorization, setup and qualification

For each owner-authorized OC/HS step, make a step file that starts by setting
the exact owner-authorized `C`, then sources the common file by its explicit
operator-home path. Copy the referenced command block unchanged after those
two lines. For example, the beginning of `n5-g5-h3.sh` is:

```text
C=<the exact 40-hex final commit named in the authorization>
source "$HOME/n5-g5-common.sh"
```

Keep these files as LF. Generate a manifest from each local common/step pair,
SCP both files and that manifest, and let the VM compare both file hashes
before it runs the step. Do not pass script contents on SSH stdin, use `eval`,
or rewrite text after hashing. From workstation Bash, for each fresh
owner-authorized session:

```bash
set -Eeuo pipefail
: "${C:?Set the separately authorized final merged commit}"
: "${SSH_TARGET:?Set the separately authorized VM SSH target}"
[[ "$C" =~ ^[0-9a-f]{40}$ ]]
/usr/bin/grep -Fqx "C=$C" n5-g5-h3.sh
! /usr/bin/grep -q $'\r' n5-g5-common.sh n5-g5-h3.sh
/usr/bin/sha256sum -- n5-g5-common.sh n5-g5-h3.sh > n5-g5-h3.sha256
scp -o BatchMode=yes -o StrictHostKeyChecking=yes \
  n5-g5-common.sh n5-g5-h3.sh n5-g5-h3.sha256 "$SSH_TARGET:"
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$SSH_TARGET" \
  'cd "$HOME" && sha256sum --check --strict n5-g5-h3.sha256 && bash n5-g5-h3.sh' \
  < /dev/null
```

Replace `h3` in the step and manifest names for each step, and generate/hash
the exact pair that will run. The `C` in the local step file must equal the
authorized `C`; the equality check above requires that exact assignment in
the step file. LR remains separate: run LR's own files and
commands exactly as LR specifies. Do not prepend or source `n5-g5-common.sh`
for LR. The sole exception is the LR1 anchor check above: load the old OC/HS
common file with the prior `W`, as in the pre-reboot capture, in its own shell.
Run LR's H1 anchor override exactly once as part of LR1; do not run HS
H1, whose frozen line still names N4 g3. After LR7 confirms the controller is
current, run HS H2 and H3 unchanged with `n5-g5-common.sh`; S1 creates the
fresh `W`.
For H4 run OC's S4 block unchanged at `C`, including its `initial` check and
`S4_SEAL` extraction. Then run this continuity check in the same session:

```bash
test "$S4_SEAL" = "$PRIOR_SEAL" \
  || { echo 'S4 account seal differs from the prior checked S6a; stop' >&2; exit 1; }
```

A mismatch is a stop for the owner. Do not change the plan, substitute a seal,
or count a failed previous H7 as a qualification. HS H5 is OC's S6a
Maintenance-lock positive control: run OC's S6a block unchanged, require the
second maintenance attempt to refuse with exactly the held-lock error, and let
`load_final_qualification` check the new S4/S6a seal equality. Then retain the
new `Q` and `SEAL` for H6.

## H6: publish and activate g5

This is the complete generation-specific replacement for HS H6. It uses the
new S6a digest and a new descriptor, then confirms g4 is stale against g5.

```bash
load_final_qualification
"${ROOT_STORE[@]}" publish --store-root "$R" --key "$K" --generation 5 \
  --qualification-evidence-digest "$Q" --service m8-service --wait 0 \
  < /dev/null | save_sealed "$W/g5.sealed.json"
check_sealed "$W/g5.sealed.json" "$Q"
"${ROOT_STORE[@]}" activate --store-root "$R" --key "$K" --generation 5 \
  --sealed "$W/g5.sealed.json" --qualification-evidence-digest "$Q" \
  --service m8-service --wait 0 < /dev/null
binding_check "$W/g5.sealed.json" accepted -
binding_check "$W_PRIOR/g4.sealed.json" stale-generation "$W/g5.sealed.json"
```

## H7: repeat active startup and both refusals on g5

Run this complete block as the replacement for HS H7. Every lane and evidence
path is fresh within the new session directory. A refusal counts only if the
current checker accepts its exact evidence under `C`; if S6c still fails, stop
and retain the failure rather than claiming the old g4 result.

```bash
load_final_qualification
"${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g5.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-g5-lane" --evidence "$W/h7-g5-active.json" < /dev/null
check_evidence active "$W/h7-g5-active.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
if check_evidence refresh "$W/h7-g5-active.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
then echo refresh-measured; else echo refresh-unmeasured; fi
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, os, sys
from pathlib import Path
p = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert p["connections"] == 8 and len(p["destinations"]) == 2
assert [x[0] for x in p["destinations"]] == ["auth.openai.com", "chatgpt.com"]
p["destinations"] = p["destinations"][:1]
os.umask(0o077)
with open(sys.argv[2], "x", encoding="utf-8") as stream:
    json.dump(p, stream, sort_keys=True); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())' \
  "$W/startup-policy.json" "$W/h7-g5-no-chatgpt-policy.json" < /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g5.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/h7-g5-no-chatgpt-policy.json" \
  --lane-dir "$W/h7-g5-s6b-lane" --evidence "$W/h7-g5-s6b-denial.json" --expect-denial \
  < /dev/null; then echo 'S6b unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence denial "$W/h7-g5-s6b-denial.json" active "$SEAL" "$W/h7-g5-no-chatgpt-policy.json" > /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g5.sealed.json" --expected "plus/${SEAL#*/}" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-g5-s6c-lane" --evidence "$W/h7-g5-s6c-plan-refusal.json" \
  < /dev/null; then echo 'S6c unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence wrongplan "$W/h7-g5-s6c-plan-refusal.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
binding_check "$W_PRIOR/g4.sealed.json" stale-generation "$W/g5.sealed.json"
```

## H8: refresh attempts on g5

This replaces HS H8's generation and evidence names. Keep its existing
authorization, one-attempt-per-session, active-before-refresh and
`refresh-measured`/`refresh-unmeasured` rules unchanged. If H7 reports
`refresh-measured`, omit H8 as HS requires.

```bash
[[ "${N:?Set the attempt number}" =~ ^[1-9][0-9]?$ ]]
/usr/local/bin/m8-host-drift < /dev/null
load_final_qualification
"${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g5.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h8-g5-$N-lane" --evidence "$W/h8-g5-$N-refresh.json" < /dev/null
check_evidence active "$W/h8-g5-$N-refresh.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
if check_evidence refresh "$W/h8-g5-$N-refresh.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
then echo refresh-measured; else echo refresh-unmeasured; fi
```

## Stage 3 READ successor

Stage 3 is a separate authorization for the final merged `C` and this g5
session. Use RS's T0 authorization, T3 pin review, T4 installation, T5 single
turn and verdict rules unchanged. T1 still requires the current drift check and
`load_final_qualification`; its binding check uses g5:

```bash
sudo -n true < /dev/null
/usr/local/bin/m8-host-drift < /dev/null
load_final_qualification
binding_check "$W/g5.sealed.json" accepted -
```

Use this RS `How to run` override. The state, authorization path, ID and key
are fresh; `HOST` binds the new generation and its new S6a evidence. The short
state path keeps the native socket path within RS's existing bound.

```bash
S=/home/m8-service/m8-n5-r5
A=/var/lib/constructicon-m8-launch/qualification/stage3-read-g5.json
ID="n5-stage3g5-$C"
KEY=stage3g5
QUAL=("${PY[@]}" constructicon.api.qualification)
HOST=(--session "$W" --store-key "$K" --sealed "$W/g5.sealed.json"
  --qualification "$W/s6a-qualification.json" --state "$S")
```

If RS T6 is separately authorized after its existing diagnosed-local-failure
gate, use this complete override and retain every T6 condition unchanged. This
document grants no retry and no model request.

```bash
S=/home/m8-service/m8-n5-r5r
A=/var/lib/constructicon-m8-launch/qualification/stage3-read-g5-retry.json
ID="n5-stage3g5r-$C"
KEY=stage3g5r
HOST=(--session "$W" --store-key "$K" --sealed "$W/g5.sealed.json"
  --qualification "$W/s6a-qualification.json" --state "$S")
```

The old Stage 2 H7 failure is not READ or WRITE authorization. This document
grants no retry and no model request.

## Evidence and limits

Retain the prior checked-seal file privately. Post only the successor
authorization, LR/D2 records, new S4/S6a digest/verdicts, g5 descriptor, H7/H8
evidence and the applicable Stage 3 pins/verdict. Never post `SEAL`, the
private file, account identifiers, credentials, tokens, codes or READ answer
text. This document establishes no qualification or production availability;
only the owner-run checks under the separately authorized final `C` can do
that.
