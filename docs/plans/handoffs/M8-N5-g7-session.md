# M8 N5: batched deployment into g7, then the one WRITE session

Status: deployment package for separate review and host authorization.
This document authorizes no host action, refresh attempt or model request.
The controller is PR #157's verified squash commit
`d22bff86e8695a7efef04dc3f47c6d4b0847599c` (`C`), whose tree is byte-identical
to reviewed and checked `f3e79d5`. Never substitute a PR head, predicted merge
hash or a later main head. The controller is a code pin;
this package belongs to a later documentation revision and is not an artifact
present at that controller commit. Review and authorize its exact bytes too.

This continues [#78](https://github.com/sushiHex/constructicon/issues/78).
The [g6 procedure](M8-N5-g6-session.md) and
[g6 disposition](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6096575750)
record the installed controller `O=585df33eb196cd4afd10d5c12cb1efb37fd5a6e1`,
active generation 6 in `/home/m8-service/m8-n5-stage2g6`, and D2 installation
`D=8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3`. These are recorded inputs,
not fresh observations of the host. Verify both workspaces and installed
records; any disagreement stops for the owner. The
[READ disposition](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6101919423)
is final: T5 passed, no T6; S4-6 retains vendor defaults inside the fixed
deadline, retry occurrence unknown and shared N5 retry unused. No READ rerun
or shared retry is supplied here.

Use these frozen sources at the reviewed installed `C`:
[operator commands](M8-N4-operator-commands.md) (OC),
[launch replacement](M8-N4-launch-replacement.md) (LR),
[host session](M8-N5-host-session.md) (HS),
[explicit refresh](M8-N5-explicit-refresh.md) (ER),
[D2 installation](M8-D2-host-installation.md), and
[WRITE session](M8-N5-write-session.md) (WS).
The pre-reboot continuity and LR1 OC setup instead comes from `O`.
Keep all existing documents' bytes. Copy named blocks unchanged unless a
complete override below replaces them. Do not use `sed`, substitutions,
`eval` or rewriting of frozen blocks to generate reviewed scripts.

## H0: authorization and immutable scripts

The owner's authorization must name this exact procedure revision, actual
merged `C`, verified `O` and `D`, all source revisions above, the private
pre-reboot checked g6 seal, fresh boot, generation 7 and fresh
`/home/m8-service/m8-n5-stage2g7`. Include LR2 requalification, LR9 only on
affirmative controller-tree drift, every H7 control, and at most one ER R1
attempt if this new H7 leaves refresh unmeasured. R6 baseline creation is
separately authorized only if drift requires it. WRITE authorization also
names WS W0's one turn, task, fixture/gate, bounds and window; the exact W4
pins still require owner review before W5. No credentials are inspected.

Before continuity capture or reboot, reconfirm exclusive operator custody:
root is trusted and no other administrator or agent acts during this session.
Stop if ownership or quiescence is uncertain. ER R0 repeats this before H8.

Prepare LF-only common/step files locally, with a source map naming each
copied block and its revision. Every post-installation step declares the
actual reviewed `C`, validates it, then sources `$HOME/n5-g7-common.sh`:

```text
C=d22bff86e8695a7efef04dc3f47c6d4b0847599c
source "$HOME/n5-g7-common.sh"
```

The workstation pattern below refuses an invalid pin before transport.
Use the corresponding reviewed filenames for each step, hashing the exact
common/step pair that will execute:

```bash
set -Eeuo pipefail
C=d22bff86e8695a7efef04dc3f47c6d4b0847599c
[[ "$C" =~ ^[0-9a-f]{40}$ ]] \
  || { echo 'controller pin is invalid; stop for review' >&2; exit 1; }
: "${SSH_TARGET:?Set the separately authorized VM SSH target}"
/usr/bin/grep -Fqx "C=$C" n5-g7-h3.sh
! /usr/bin/grep -q $'\r' n5-g7-common.sh n5-g7-h3.sh
/usr/bin/sha256sum -- n5-g7-common.sh n5-g7-h3.sh > n5-g7-h3.sha256
scp -o BatchMode=yes -o StrictHostKeyChecking=yes \
  n5-g7-common.sh n5-g7-h3.sh n5-g7-h3.sha256 "$SSH_TARGET:"
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$SSH_TARGET" \
  'cd "$HOME" && sha256sum --check --strict n5-g7-h3.sha256 && bash n5-g7-h3.sh' \
  < /dev/null
```

Use the same hash/LF discipline for old-controller common/step files, with
literal `C=585df33eb196cd4afd10d5c12cb1efb37fd5a6e1` in those steps.
LR's installation scripts keep their own declarations and shell settings:
never prepend or source N5 common into them, and never add `pipefail`.
Run no host command until the separate authorization exists. No interactive
paste or script transport on SSH stdin; each SSH script invocation uses
`/dev/null`.

## Before LR's reboot: capture checked g6 continuity

Prepare `n5-g7-prior-common.sh` from OC's two Setup blocks at `O`, then append:

```bash
W=/home/m8-service/m8-n5-stage2g6
```

Source it in a fresh shell at `O` before reboot. This fresh private capture
uses the currently accepted g6 evidence, not an earlier g5 seal file:

```bash
binding_check "$W/g6.sealed.json" accepted -
load_final_qualification
check_sealed "$W/g6.sealed.json" "$Q"
test "${SEAL%%/*}" = pro \
  || { echo 'prior S6a plan is not N4-qualified pro; stop' >&2; exit 1; }
test -n "$SEAL"
set -C
printf '%s\n' "$SEAL" > "$HOME/n5-g7-account.seal"
```

OC's `umask 077` applies. Existing file, failed binding/evidence or wrong plan
stops. Never overwrite a partial capture, print it or post it. Never judge old
g6 evidence using the new controller's revisions.

## H1: LR and D2 on one fresh boot

Run LR0 through LR6, then LR8. Run LR9 only if LR8 affirmatively reports
`installed` false and the observed `/opt/constructicon-m8-controller` entry
has `state` equal to `tree` and `different` greater than zero. Absence of
the positive mismatch record, verifier failure or malformed output stops;
an arbitrary LR8 refusal never authorizes replacement. Then require LR7.
The batched controller contains #145, #147 and the reviewed #157 WRITE code.

LR1 is clean Stop-VM/Start-VM, never save/checkpoint; record the fresh boot ID.
Before controller replacement, source `n5-g7-prior-common.sh` at `O` in a
fresh shell for this sole LR1 override:

```bash
binding_check "$W/g6.sealed.json" reboot-anchor -
```

Do not run frozen HS H1 (g3). Until the controller is current, no maintenance,
activation, lane command or second session. LR2's D2 R4 verification and R5
probe run in D2's own workspace/fresh shell at verified `D`; require both
affirmative passing records on this boot. Drift requiring R6 stops for that
separate authorization; subsequently require bare drift to pass. Do not reboot
again before LR8/9 and LR7 finish. LR7 must affirm `"launch_ready": true` at `C`.

## H2-H5: fresh g7 maintenance qualification

Prepare `n5-g7-common.sh` from OC's two Setup blocks at `C`, then append these
complete declarations. The private seal is quoted data, never shell code:

```bash
W_PRIOR=/home/m8-service/m8-n5-stage2g6
W=/home/m8-service/m8-n5-stage2g7
PRIOR_SEAL="$(/usr/bin/cat -- "$HOME/n5-g7-account.seal")"
```

After LR7, run HS H2 unchanged (noninteractive sudo and affirmative no drift),
then HS H3/OC S1 unchanged into absent fresh `W`. Abandon incomplete output;
no repair, reuse, login or provisioning. Copy OC S4 unchanged, including its
`initial` check and `S4_SEAL` extraction, followed in the same shell by:

```bash
test "$S4_SEAL" = "$PRIOR_SEAL" \
  || { echo 'S4 account seal differs from the prior checked g6 S6a; stop' >&2; exit 1; }
```

H5 is OC S6a unchanged: retained lock, exact competing-maintenance refusal,
completed held startup and `load_final_qualification` must all pass. That
helper checks fresh S4/S6a equality and derives new `Q`. Old g6 evidence or
its refresh result cannot substitute for changed-source qualification.

## H6: publish and activate g7

This complete HS H6 replacement seals only the fresh qualification:

```bash
load_final_qualification
"${ROOT_STORE[@]}" publish --store-root "$R" --key "$K" --generation 7 \
  --qualification-evidence-digest "$Q" --service m8-service --wait 0 \
  < /dev/null | save_sealed "$W/g7.sealed.json"
check_sealed "$W/g7.sealed.json" "$Q"
"${ROOT_STORE[@]}" activate --store-root "$R" --key "$K" --generation 7 \
  --sealed "$W/g7.sealed.json" --qualification-evidence-digest "$Q" \
  --service m8-service --wait 0 < /dev/null
binding_check "$W/g7.sealed.json" accepted -
binding_check "$W_PRIOR/g6.sealed.json" stale-generation "$W/g7.sealed.json"
```

## H7: active startup and both refusals on g7

Run all commands, including both refusals and final stale-g6 proof, even if
natural refresh is measured. OC's schema-4 checker remains unchanged. #145
requires the declared destination denial, not EOF: S6b must exit 1 and the
checker must affirm exactly `denied:destination` (positive count), with the
existing exact four account/read refusal faults. EOF-only, destination plus
EOF, missing denial, extra faults or a fault-free exit 0 all stop; no expanded
fault allowlist or denial waiver. Clean startup continues to reject every
denial kind. #145 changes verdict semantics, not these reviewed commands.

```bash
load_final_qualification
"${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g7.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-g7-lane" --evidence "$W/h7-g7-active.json" < /dev/null
check_evidence active "$W/h7-g7-active.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
if check_evidence refresh "$W/h7-g7-active.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
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
  "$W/startup-policy.json" "$W/h7-g7-no-chatgpt-policy.json" < /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g7.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/h7-g7-no-chatgpt-policy.json" \
  --lane-dir "$W/h7-g7-s6b-lane" --evidence "$W/h7-g7-s6b-denial.json" --expect-denial \
  < /dev/null; then echo 'S6b unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence denial "$W/h7-g7-s6b-denial.json" active "$SEAL" "$W/h7-g7-no-chatgpt-policy.json" > /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g7.sealed.json" --expected "plus/${SEAL#*/}" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-g7-s6c-lane" --evidence "$W/h7-g7-s6c-plan-refusal.json" \
  < /dev/null; then echo 'S6c unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence wrongplan "$W/h7-g7-s6c-plan-refusal.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
binding_check "$W_PRIOR/g6.sealed.json" stale-generation "$W/g7.sealed.json"
```

## H8: one explicit-refresh attempt if still unmeasured

If H7 printed `refresh-measured`, omit H8. Otherwise only after every H7
control passes and with separately authorized one-attempt budget, source the
new common at `C`, append these declarations and copy ER R1's sole Bash block
unchanged. ER R0/R2 apply unchanged:

```bash
SEALED="$W/g7.sealed.json"
REFRESH_LANE="$W/h8-g7-explicit-lane"
REFRESH_EVIDENCE="$W/h8-g7-explicit-refresh.json"
```

R1 checks sudo, drift, fresh qualification and descriptor before exactly one
`startup --request-refresh`. Retain schema-5 evidence, digest and CLI verdict
from that same evidence. Never use schema-4 `check_evidence`, strip fields or
rewrite its schema. Unmeasured refresh, faults, absent verdict or unexpected
output stops. No natural-refresh fallback, second attempt, retry, expiry edit,
credential inspection or direct token request. H8 does not replace the
schema-4 maintenance evidence sealed into g7.

## WRITE: unchanged W0-W6 after the g7 evidence review

Submit every H7 result and applicable H8 evidence/verdict for owner review
before WRITE. The old g6 refresh does not qualify this controller. A measured
result permits review, not automatic pins, root installation or dispatch.

Use the reviewed `n5-g7-common.sh` at `C`, followed by this complete declaration:

```bash
SEALED="$W/g7.sealed.json"
```

Then copy WS W0 through W6 unchanged, in order, using their exact bytes at
the actual merged `C`. No READ common file or earlier-generation descriptor.
W0 supplies fresh `/home/m8-service/m8-n5-w`, independent WRITE/smoke fixtures,
stage4 authorization and journal/attempt names; do not change them or reuse
partial state. W1 rechecks binding/drift, W2 prepares fresh state, W3 requires
credential-free smoke, and W4 computes the actual fixture/workspace/gate/report
pins. **Pause after W4 for owner review of the exact pins and smoke verdict,
before W5 root installation.** W5 installs only that reviewed authorization;
W6 is exactly one WRITE turn. The 300-second grants, 30-second checker,
20-second check, two-hour pin window and 1200-second observation stay unchanged;
observation is not a total cleanup deadline. Vendor defaults remain inside
the fixed deadline, retry occurrence unknown and shared N5 retry unused.

Non-passing, absent/malformed report or unexpected exit stops with private
state preserved. No recovery/retry command, refunded turn or cleanup is
authorized. A fixture pass does not install a target or alone establish
`vendor_conformance_qualified`.

## Evidence and limits

Post reviewed authorization/script revisions and hashes, actual installed
commits, boot/D2/LR facts, fresh maintenance digests, g7 descriptor, stale-g6
proof, complete H7 outcomes, applicable H8 evidence/digest/verdict, smoke,
reviewed WRITE pins and bounded WRITE report on #78. Keep the private seal,
full locator-bearing authorization and retained diagnostic state private.
Never post credentials, tokens, account identifiers, model text, callbacks
or raw journal/gate details.

Fake-shell tests prove composition and stops only, not installation, vendor
qualification, authenticated WRITE or refresh. Every host step remains unrun
until separately authorized and recorded; merging this package grants none.
