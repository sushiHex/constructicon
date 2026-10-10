# M8 N5: deployment and requalification into g6

Status: deployment package for separate owner review and host authorization.
This document authorizes no host action, refresh attempt or model request.
The installed controller target is the already merged commit
`585df33eb196cd4afd10d5c12cb1efb37fd5a6e1` (`C`, PR #154). This new document
belongs to a later documentation revision; it is not an artifact present at
`C`. Review and authorize its exact bytes separately from the installed code.

This continues [#78](https://github.com/sushiHex/constructicon/issues/78).
The [recorded LR/D2 handoff](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6091184737)
names the installed launch/controller commit
`ce08c6b363a56dcbac942edf021afc94800334fb` (`O`) and D2 qualification installation commit
`8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3` (`D`). Those are recorded inputs,
not fresh observations of the host. Verify the workspaces and installed
records before using them. Any disagreement stops this package for the owner.
The [g5 control handoff](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6091238008)
records active g5 in `/home/m8-service/m8-n5-stage2r`.

The reviewed blocks are referenced from their exact bytes at `C`:
[operator commands](M8-N4-operator-commands.md) (OC),
[launch replacement](M8-N4-launch-replacement.md) (LR),
[host session](M8-N5-host-session.md) (HS),
[READ session](M8-N5-read-session.md) (RS), and
[explicit refresh](M8-N5-explicit-refresh.md) (ER).
The old-controller OC setup used for continuity capture and LR1 instead comes
from `O`, so its source revision checks judge the old g5 records.
The [g5 successor](M8-N5-requalification.md) explains that continuity law.
Keep every existing document's bytes. Copy named blocks unchanged unless a
complete override below replaces them; do not generate replacements with
`sed`, substitutions, `eval` or text rewriting after review/hashing.

## H0: authorization and immutable scripts

The owner's authorization on #78 must name this document's reviewed revision,
`C`, `O`, `D`, OC, LR, HS, ER and
[M8-D2](M8-D2-host-installation.md). It must name the private pre-reboot
checked g5 seal, fresh session `/home/m8-service/m8-n5-stage2g6`, generation 6,
all H7 controls, and at most one ER R1 attempt on this boot if H7 does not
measure refresh. LR9's controller replacement and LR2's D2 requalification
must be included; R6 baseline creation remains separately authorized if drift
requires it. No READ authorization is included in H0.

Before continuity capture or reboot, reconfirm exclusive operator custody:
root is trusted and no other administrator or agent acts on this host during
the session. Stop if ownership or quiescence is uncertain. ER R0 repeats
custody confirmation before H8; it does not replace this initial check.

Prepare reviewed LF-only local common/step files. The old-controller files use
`O`; every post-installation step starts with this exact assignment, then
sources the applicable common file by its explicit owner-home path:

```text
C=585df33eb196cd4afd10d5c12cb1efb37fd5a6e1
source "$HOME/n5-g6-common.sh"
```

For each step, compare local and VM hashes before execution. This is the exact
workstation Bash pattern for H3; use the corresponding reviewed filename for
each other step. The common/step pair being hashed is the pair being run.

```bash
set -Eeuo pipefail
C=585df33eb196cd4afd10d5c12cb1efb37fd5a6e1
: "${SSH_TARGET:?Set the separately authorized VM SSH target}"
/usr/bin/grep -Fqx "C=$C" n5-g6-h3.sh
! /usr/bin/grep -q $'\r' n5-g6-common.sh n5-g6-h3.sh
/usr/bin/sha256sum -- n5-g6-common.sh n5-g6-h3.sh > n5-g6-h3.sha256
scp -o BatchMode=yes -o StrictHostKeyChecking=yes \
  n5-g6-common.sh n5-g6-h3.sh n5-g6-h3.sha256 "$SSH_TARGET:"
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$SSH_TARGET" \
  'cd "$HOME" && sha256sum --check --strict n5-g6-h3.sha256 && bash n5-g6-h3.sh' \
  < /dev/null
```

Use the same file/hash discipline for the pre-reboot and LR1 common/step pair
at `O`, with an exact `C=ce08c6b363a56dcbac942edf021afc94800334fb` line in
those steps. LR's installation scripts keep their own reviewed declarations,
files and settings: never prepend or source the N5 common file for them. No
interactive paste or script transport on SSH stdin. Run no host command until
the separate authorization exists.

## Before LR's reboot: capture checked g5 continuity

Prepare `n5-g6-prior-common.sh` as OC's two Setup blocks at `O`, followed by
this exact override. It depends on no earlier private seal file:

```bash
W=/home/m8-service/m8-n5-stage2r
```

While the old controller and current boot still accept g5, source that common
file in a fresh shell at `O` and run this block. It reads the old S4/S6a and
descriptor; its only write is a fresh private owner-home file, under OC's
`umask 077`:

```bash
binding_check "$W/g5.sealed.json" accepted -
load_final_qualification
check_sealed "$W/g5.sealed.json" "$Q"
test "${SEAL%%/*}" = pro \
  || { echo 'prior S6a plan is not N4-qualified pro; stop' >&2; exit 1; }
test -n "$SEAL"
set -C
printf '%s\n' "$SEAL" > "$HOME/n5-g6-account.seal"
```

An existing file, failed binding, failed evidence check or different plan is a
stop. Do not overwrite or reuse a partial capture. Do not print or post the
seal. Do not re-check old g5 evidence with the new controller's revisions.

## H1: LR and D2 on one fresh boot

Run LR's Order exactly: LR0 to LR6, LR8, LR9 if LR8 refused, then LR7.
Use the recorded `O` above only after verifying both old workspaces and the
installed records. LR1's clean Stop-VM/Start-VM uses no save or checkpoint.
Record the new boot ID. Before replacing the old controller, source
`n5-g6-prior-common.sh` at `O` in its own shell for this sole LR1 override:

```bash
binding_check "$W/g5.sealed.json" reboot-anchor -
```

Do not run frozen HS H1, which names N4 g3. From reboot until the controller
is current, run no maintenance, activation, lane command or second session.
LR2 runs D2 R4 verification and R5 probe in D2's own workspace, fresh shell,
with the verified recorded `D`. Both require affirmative passing records on
this boot. If drift requires R6, stop for that separately authorized baseline;
then require the bare drift check to pass. Do not reboot again before LR8/9
and LR7 pass. Do not add `pipefail` to LR's installation commands. LR7 must
affirm `"launch_ready": true` under the current controller at `C`.

## H2-H5: fresh g6 maintenance qualification

Prepare `n5-g6-common.sh` as OC's two Setup blocks at `C`, followed by this
exact override. The private file is read as quoted data, never shell code:

```bash
W_PRIOR=/home/m8-service/m8-n5-stage2r
W=/home/m8-service/m8-n5-stage2g6
PRIOR_SEAL="$(/usr/bin/cat -- "$HOME/n5-g6-account.seal")"
```

After LR7, run HS H2 unchanged, requiring noninteractive sudo and affirmative
no drift. Run HS H3 (OC S1) unchanged into the absent fresh `W`. Abandon any
incomplete directory; do not repair or reuse it. No new login or provisioning.

For H4, copy OC S4 unchanged, including its `initial` check and `S4_SEAL`
extraction, then run this in the same session:

```bash
test "$S4_SEAL" = "$PRIOR_SEAL" \
  || { echo 'S4 account seal differs from the prior checked g5 S6a; stop' >&2; exit 1; }
```

A mismatch stops for the owner. H5 is OC S6a unchanged: require the retained
lock, the exact second-maintenance refusal and completed held-startup evidence.
`load_final_qualification` then checks the new S4/S6a seal equality and obtains
the new digest `Q`. No old qualification digest substitutes for changed source.

## H6: publish and activate g6

This complete replacement for HS H6 seals only the new S6a digest, and proves
the immediately prior g5 is stale:

```bash
load_final_qualification
"${ROOT_STORE[@]}" publish --store-root "$R" --key "$K" --generation 6 \
  --qualification-evidence-digest "$Q" --service m8-service --wait 0 \
  < /dev/null | save_sealed "$W/g6.sealed.json"
check_sealed "$W/g6.sealed.json" "$Q"
"${ROOT_STORE[@]}" activate --store-root "$R" --key "$K" --generation 6 \
  --sealed "$W/g6.sealed.json" --qualification-evidence-digest "$Q" \
  --service m8-service --wait 0 < /dev/null
binding_check "$W/g6.sealed.json" accepted -
binding_check "$W_PRIOR/g5.sealed.json" stale-generation "$W/g6.sealed.json"
```

## H7: active startup and both refusals on g6

Run every command below; a measured natural refresh omits H8 but does not
omit either refusal or the final stale-generation check. OC's schema-4
checker judges these default startup records under `C`. A failed active check,
unexpected exit or refused evidence check stops the session.

```bash
load_final_qualification
"${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g6.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-g6-lane" --evidence "$W/h7-g6-active.json" < /dev/null
check_evidence active "$W/h7-g6-active.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
if check_evidence refresh "$W/h7-g6-active.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
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
  "$W/startup-policy.json" "$W/h7-g6-no-chatgpt-policy.json" < /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g6.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/h7-g6-no-chatgpt-policy.json" \
  --lane-dir "$W/h7-g6-s6b-lane" --evidence "$W/h7-g6-s6b-denial.json" --expect-denial \
  < /dev/null; then echo 'S6b unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence denial "$W/h7-g6-s6b-denial.json" active "$SEAL" "$W/h7-g6-no-chatgpt-policy.json" > /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g6.sealed.json" --expected "plus/${SEAL#*/}" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-g6-s6c-lane" --evidence "$W/h7-g6-s6c-plan-refusal.json" \
  < /dev/null; then echo 'S6c unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence wrongplan "$W/h7-g6-s6c-plan-refusal.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
binding_check "$W_PRIOR/g5.sealed.json" stale-generation "$W/g6.sealed.json"
```

## H8: one explicit-refresh attempt if still unmeasured

If H7 printed `refresh-measured`, omit H8. Otherwise, only after every H7
control passed and with the separately authorized one-attempt budget, source
the new common file at `C`, append these exact declarations, then copy ER R1's
sole Bash block unchanged:

```bash
SEALED="$W/g6.sealed.json"
REFRESH_LANE="$W/h8-g6-explicit-lane"
REFRESH_EVIDENCE="$W/h8-g6-explicit-refresh.json"
```

ER R0/R2 apply unchanged. R1 checks sudo, drift, the current qualification and
descriptor before one `startup --request-refresh`. Retain the published
schema-5 evidence, printed digest and CLI verdict from that same evidence.
Never send this record through OC's schema-4 `check_evidence`, strip fields
or rewrite its schema. `refresh-unmeasured`, faults, absent verdict or any
unexpected output stop. No natural-refresh fallback, second attempt, retry,
expiry edit, credential inspection or direct token request is authorized.
H8 never replaces the schema-4 maintenance evidence sealed into g6.

## Stage 3: fresh READ inputs for separate review

READ remains a separate owner authorization naming `C`, this g6 session and
RS T0's task, grants and window. Before it, submit the complete H7 evidence,
any H8 schema-5 evidence and verdict, and the applicable checker/verdict
behavior for owner review. A measured result permits that review; it neither
installs pins nor calls READ automatically. PRs #145/#147 remain behind
T5/no-T6; S4-6 remains a post-READ decision.

The READ common file is `n5-g6-common.sh` followed by this complete RS
`How to run` override. Every state/authorization/run name is fresh and the
short state path preserves the existing native socket bound:

```bash
S=/home/m8-service/m8-n5-r6
A=/var/lib/constructicon-m8-launch/qualification/stage3-read-g6.json
ID="n5-stage3g6-$C"
KEY=stage3g6
QUAL=("${PY[@]}" constructicon.api.qualification)
HOST=(--session "$W" --store-key "$K" --sealed "$W/g6.sealed.json"
  --qualification "$W/s6a-qualification.json" --state "$S")
```

RS T1 has this complete binding override; T2 through T5 retain their exact
blocks and conditions, with T3's minted pins reviewed by the owner before T4:

```bash
sudo -n true < /dev/null
/usr/local/bin/m8-host-drift < /dev/null
load_final_qualification
binding_check "$W/g6.sealed.json" accepted -
```

No T6 command or retry path is supplied or authorized here. Do not append
the old g5/g4 retry override. A reboot, failed gate or spent turn stops for
the owner under the existing disposition rules.

## Evidence and limits

Keep the checked account seal file private. Post only the authorization and
reviewed script revisions/hashes, installed commit and launch facts, boot,
D2/LR records, new S1/S4/S6a records and checked digests, g6 descriptor,
stale-g5 and H7 control results, H8 digest/verdict if run, and separately
reviewed READ pins/verdict on #78. Never post `SEAL`, its private file,
credential contents, account identifiers, tokens, codes or READ answer text.

The fake-shell tests establish command composition and stopping behavior;
they establish no physical installation, refresh or vendor qualification.
`vendor_conformance_qualified` remains false until every required control is
measured and the owner records the disposition. This package does not deploy
WRITE, qualify Claude or grant any host operation by being merged.
