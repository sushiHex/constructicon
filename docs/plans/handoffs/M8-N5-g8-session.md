# M8 N5: fresh g8 qualification and one additional bounded WRITE

Status: additive procedure for exact-revision owner review and separate host
authorization. This document authorizes no host action or model request. The
controller is the actual PR #164 merge
`C=59de73bbc9b6f6a9a814b6193f0252e92d1bdd3e`, byte-identical to reviewed
`f6972a8`. The procedure revision is a separate artifact, not a document
present at that controller commit. Never substitute the current main head.

This continues [#78](https://github.com/sushiHex/constructicon/issues/78).
The [decision brief](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6135547812)
is not a runnable procedure or execution authority. Recorded installed inputs
are `O=f6cd85a6ed247fdcbb44dc002b8a99fdf18f1324`, D2 installation
`D=8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3`, and qualified g7 in
`/home/m8-service/m8-n5-stage2g7`. These are not fresh observations: verify
the old launch/controller workspaces, installed records, descriptor and
exclusive custody before proceeding. Any disagreement stops for the owner.

The prior WRITE dispatched and is spent. Preserve its state directory,
journal and sidecars, attempt, authorizations, diagnostic copies, operator
store and historical archives. Its no-change diagnosis does not establish
what tools the live model used. The additional turn is not the unused shared
retry for a local failure known not to have dispatched; never reset or refund
the prior attempt. Changed adapter bytes cannot inherit g7 conformance.

## H0: authority and immutable source map

The separate owner authorization names this exact procedure revision, `C/O/D`,
fresh verification of the recorded inputs, exclusive operator custody,
checked g7 continuity, clean reboot, LR2 and the full LR route, fresh
`/home/m8-service/m8-n5-stage2g8`, generation 8, every H7 control and at most
one conditional H8 explicit-refresh attempt. R6 baseline creation or drift
repair is not authorized. Another boot or uncertain custody stops.

WRITE requires an explicit additional-turn budget: at most one new
`turn/start`, the existing fixed task/fixture/gate, 300-second exchange and
callback budget, eight admitted callbacks, 30-second checker, 20-second check,
reviewed byte/capture/gate bounds, two-hour pin window and 1200-second
observation. Observation is not a total cleanup deadline. There is no hard
token or finite monetary ceiling; backend requests and vendor retries remain
unknown. This authorization does not waive the H7/H8 evidence review or the
later W4 pause for actual pins before W5/W6.

Use frozen [OC](M8-N4-operator-commands.md),
[LR](M8-N4-launch-replacement.md), [HR](M8-N4-host-runtime.md),
[HS](M8-N5-host-session.md), [ER](M8-N5-explicit-refresh.md),
[D2](M8-D2-host-installation.md) and [WS](M8-N5-write-session.md).
All existing documents retain their bytes. New-controller blocks come from
`C`; old-controller OC continuity setup comes from `O`; LR2 uses verified `D`.
Mechanically copy named blocks unchanged except the complete replacements
below and LR/HR's documented literal commit declarations. No `sed`, `eval`,
runtime substitutions or rewriting of frozen block bodies generates scripts.

| Script | Reviewed composition |
| --- | --- |
| Prior common | OC's two Setup blocks at `O`, then the prior `W` declaration below |
| Old-installation verification | Literal `C=O`, source prior common, HS H2, then this document's verifier block; inspect affirmative results before the separate capture step |
| Continuity capture | Separate step file: literal `C=O`, source prior common, HS H2, then this document's capture block after the old-installation result checks |
| LR1 anchor | Literal `C=O`, source prior common, this document's reboot-anchor override |
| LR2 | LR2 unchanged, substituting only its documented `D` declaration |
| LR3/R11 | LR3's two blocks at `C`; documented `O=f6cd85a` and `C` declarations |
| LR4/LR5/LR6 | LR4 / HR R12 / LR6 at `C`; fresh shells declare `C`, `W="$HOME/m8-launch"`, and required `J` (LR6 needs `J` prefixed) |
| LR8 | LR8 at `C`, with verified `O=f6cd85a` for the old controller archive |
| LR9/R17-R19 | Conditional LR9, then each HR block separately at `C`; prefix required `C/W/J`, including controller `W` for R19 |
| LR7 | OC setup at `C`, then only OC S3's preflight line; no login |
| New common | OC's two Setup blocks at `C`, then H2-H5 declarations below |
| H2-H5 | HS H2, OC S1, OC S4 plus account comparison, OC S6a unchanged |
| H6/H7 | Complete g8 blocks below |
| H8 | New common, g8 refresh declarations, ER R1 unchanged; ER R0/R2 apply |
| WRITE | New common, complete W0 override below, then WS W1-W6 unchanged |

This is the normal fresh LR route, not the completed g7 retention resume.
Do not replay its paused-workspace archive, original `O=585df33` archive or
specific refusal guard. Leave those historical paths intact. Normal LR3/LR8
archive the currently verified workspaces into absent `m8-launch-$O` and
`m8-controller-$O`; an occupied destination stops, never overwrite or repair.

Prepare LF-only common/step files in fresh package directories. Record source
revision, heading/block, literal declarations and SHA-256 of each executed
file. Historical home steps are comparison only. Each executed step sources
its common file by the exact owner-home package path reviewed in that step,
not a pre-existing home common. For example, H3 declares exact `C` then
sources `"$HOME/n5-g8-h3-package/n5-g8-common.sh"`. The directory must be
absent before upload; never blindly overwrite a step or common file.
LR/HR installers keep their own shell settings: no N5 common and no added
`pipefail`. Each SSH execution is noninteractive with stdin `/dev/null`,
BatchMode and strict host-key checking, never pasted or streamed as a script.

For each common/step pair, use this workstation pattern with its reviewed
filenames and distinct fresh package name. Validate the exact pin, require
the new remote directory absent, and compare hashes before execution:

```bash
set -Eeuo pipefail
C=59de73bbc9b6f6a9a814b6193f0252e92d1bdd3e
[[ "$C" =~ ^[0-9a-f]{40}$ ]] \
  || { echo 'controller pin is invalid; stop for review' >&2; exit 1; }
: "${SSH_TARGET:?Set the separately authorized VM SSH target}"
/usr/bin/grep -Fqx "C=$C" n5-g8-h3.sh
! /usr/bin/grep -q $'\r' n5-g8-common.sh n5-g8-h3.sh
/usr/bin/sha256sum -- n5-g8-common.sh n5-g8-h3.sh > n5-g8-h3.sha256
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$SSH_TARGET" \
  'test ! -e "$HOME/n5-g8-h3-package" && test ! -L "$HOME/n5-g8-h3-package" && /usr/bin/mkdir -m 0700 -- "$HOME/n5-g8-h3-package"' \
  < /dev/null
scp -o BatchMode=yes -o StrictHostKeyChecking=yes \
  n5-g8-common.sh n5-g8-h3.sh n5-g8-h3.sha256 "$SSH_TARGET:n5-g8-h3-package/"
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$SSH_TARGET" \
  'cd "$HOME/n5-g8-h3-package" && sha256sum --check --strict n5-g8-h3.sha256 && bash n5-g8-h3.sh' \
  < /dev/null
```

Old-controller steps instead declare literal `C=O` and source the prior common
in their own reviewed fresh step-package path. Installer files have no N5
common; hash the exact standalone script in its own fresh package.
No transport or host execution occurs until the separate authorization.

## Before reboot: checked g7 continuity at the old controller

First reconfirm root/operator trust and exclusive custody: no other
administrator, agent or authorized writer acts during this session. A process
scan is not that proof. Prepare `n5-g8-prior-common.sh` from OC Setup at `O`,
then append:

```bash
W=/home/m8-service/m8-n5-stage2g7
```

In a fresh shell, declare exact `C=O`, source that common, and run HS H2
unchanged first. Require noninteractive sudo and affirmative no drift before
any later step. Run this complete old-installation verification block in its
own step file, not chained automatically into continuity capture.
It uses LR6/LR8's verifier argv but does not redirect into their historical
workspace records. The fresh kernel profile read goes directly to the launch
verifier; the controller verifier needs no profile input. Capture stdout via
the reviewed transport into fresh private records outside both old workspaces.
The already sourced OC fail-fast/pipefail settings apply here, not to LR/HR
installers. Inspect and record both successful verifiers and affirmative
installation/provenance records at `O`; launch must also affirm `replacement` true, and
controller must show observed tree `different` zero. Exit zero alone is not
that review: launch can report installed with `replacement` false when its
retirement record is missing. No fetch or record repair:

```bash
sudo -n /usr/bin/cat /sys/kernel/security/apparmor/profiles \
  | /usr/bin/python3 -I "$HOME/m8-launch/m8_host_artifacts.py" \
      verify-launch "$C" "$HOME/m8-launch"
/usr/bin/python3 -I "$HOME/m8-controller/m8_host_artifacts.py" \
  verify-controller "$C" "$HOME/m8-controller" < /dev/null
```

Only after those affirmative result checks, run this fresh continuity capture
in a **separate step file**. Declare exact `C=O`, source prior common and repeat
HS H2 first; no script automatically crosses the result-review boundary.
Never judge old evidence using new adapter revisions:

```bash
binding_check "$W/g7.sealed.json" accepted -
load_final_qualification
check_sealed "$W/g7.sealed.json" "$Q"
test "${SEAL%%/*}" = pro \
  || { echo 'prior S6a plan is not N4-qualified pro; stop' >&2; exit 1; }
test -n "$SEAL"
set -C
printf '%s\n' "$SEAL" > "$HOME/n5-g8-account.seal"
```

OC's fail-fast settings and `umask 077` apply. Existing capture file, failed
binding/evidence, changed source or account plan stops. No recapture,
overwrite, credential read or posting of the private seal is supplied.

## H1: normal LR and D2 on one fresh boot

Run LR0-6, then LR8, conditional LR9/HR R17-R19, then LR7. LR1 is clean
Stop-VM/Start-VM, never Save-VM or checkpoint; record the full new boot ID.
Before replacement, source the prior common at `O` in its own fresh shell:

```bash
binding_check "$W/g7.sealed.json" reboot-anchor -
```

Do not run frozen HS H1's g3 check. From reboot until the controller is
current, no maintenance, activation, lane command or second session. LR2's
D2 verify and probe require affirmative passing records on this boot, followed
by affirmative bare no drift. R6 is not authorized. Do not reboot again.
LR9 requires LR8's positive `installed` false, observed controller `state`
equal to `tree` and `different` greater than zero; malformed output or an
arbitrary refusal never authorizes replacement. Require every LR/HR passing
record and marker, not just the final script exit. LR7 is preflight only and
must affirm `"launch_ready": true` at `C`; no new login or provisioning.

## H2-H5: fresh g8 maintenance evidence

Prepare `n5-g8-common.sh` from OC Setup at `C`, followed by:

```bash
W_PRIOR=/home/m8-service/m8-n5-stage2g7
W=/home/m8-service/m8-n5-stage2g8
PRIOR_SEAL="$(/usr/bin/cat -- "$HOME/n5-g8-account.seal")"
```

Each new-controller step declares exact `C` before sourcing this common.
Run HS H2 unchanged, then OC S1 into absent fresh `W`. Incomplete output is
abandoned; no repair or reuse. Run OC S4 unchanged, including its `initial`
check and `S4_SEAL` extraction, followed in the same shell by:

```bash
test "$S4_SEAL" = "$PRIOR_SEAL" \
  || { echo 'S4 account seal differs from the prior checked g7 S6a; stop' >&2; exit 1; }
```

Run OC S6a unchanged, requiring the retained lock, exact competing-maintenance
refusal, completed held startup and checked S4/S6a account equality. Old g7
digests, refresh and descriptor cannot qualify these changed bytes.

## H6: checked maintenance floor 7, publish and activate g8

`load_final_qualification` first validates both complete maintenance records.
The additional check below affirms their **historical maintenance custody
floor** is strict integer 7, not a claim about the current live floor after
activation. Maintenance derives this fact from the locked descriptor inventory;
publication independently requires the next inventory generation. Missing,
bool, float or another floor stops before publication; do not select another
generation from filenames or normalize the records.

```bash
load_final_qualification
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, sys
from pathlib import Path
for name in ("s4-qualification.json", "s6a-qualification.json"):
    custody = json.loads((Path(sys.argv[1]) / name).read_bytes())["custody"]
    assert custody["kind"] == "maintenance"
    assert type(custody["generation_floor"]) is int and custody["generation_floor"] == 7
print("maintenance-floor-7-checked")' "$W" < /dev/null \
  | /usr/bin/grep -qxF maintenance-floor-7-checked
"${ROOT_STORE[@]}" publish --store-root "$R" --key "$K" --generation 8 \
  --qualification-evidence-digest "$Q" --service m8-service --wait 0 \
  < /dev/null | save_sealed "$W/g8.sealed.json"
check_sealed "$W/g8.sealed.json" "$Q"
"${ROOT_STORE[@]}" activate --store-root "$R" --key "$K" --generation 8 \
  --sealed "$W/g8.sealed.json" --qualification-evidence-digest "$Q" \
  --service m8-service --wait 0 < /dev/null
binding_check "$W/g8.sealed.json" accepted -
binding_check "$W_PRIOR/g7.sealed.json" stale-generation "$W/g8.sealed.json"
```

## H7: every active and refusal control on g8

Run the entire block even if natural refresh is measured. Active startup must
pass the unchanged OC schema-4 checker. S6b must exit exactly 1 and affirm
only positive `denied:destination`, with the exact four account/read refusal
faults. EOF-only, destination plus EOF, missing denial or extra faults stops.
S6c must match the exact wrong-plan refusal. No denial waiver or allowlist
expansion; the final stale-g7 check is mandatory.

```bash
load_final_qualification
"${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g8.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-g8-lane" --evidence "$W/h7-g8-active.json" < /dev/null
check_evidence active "$W/h7-g8-active.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
if check_evidence refresh "$W/h7-g8-active.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
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
  "$W/startup-policy.json" "$W/h7-g8-no-chatgpt-policy.json" < /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g8.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/h7-g8-no-chatgpt-policy.json" \
  --lane-dir "$W/h7-g8-s6b-lane" --evidence "$W/h7-g8-s6b-denial.json" --expect-denial \
  < /dev/null; then echo 'S6b unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence denial "$W/h7-g8-s6b-denial.json" active "$SEAL" "$W/h7-g8-no-chatgpt-policy.json" > /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g8.sealed.json" --expected "plus/${SEAL#*/}" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-g8-s6c-lane" --evidence "$W/h7-g8-s6c-plan-refusal.json" \
  < /dev/null; then echo 'S6c unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence wrongplan "$W/h7-g8-s6c-plan-refusal.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
binding_check "$W_PRIOR/g7.sealed.json" stale-generation "$W/g8.sealed.json"
```

## H8: at most one conditional explicit refresh

If H7 printed `refresh-measured`, omit H8. Otherwise, only after every H7
control passes and the separate one-attempt authorization, source the new
common, append these declarations, then copy ER R1 unchanged:

```bash
SEALED="$W/g8.sealed.json"
REFRESH_LANE="$W/h8-g8-explicit-lane"
REFRESH_EVIDENCE="$W/h8-g8-explicit-refresh.json"
```

ER R0/R2 apply: repeat custody/binding/drift checks, retain schema-5 evidence,
its digest and the verdict from that same completed record. No schema-4
checker, stripped field or rewritten schema. Unmeasured refresh, faults,
missing verdict or unexpected output stops. No second attempt, natural-refresh
fallback, expiry edit, token request or credential inspection.

## WRITE: fresh W0 names, exact W1-W6 and owner pin pause

Submit complete H7 and applicable H8 evidence/digest/verdict for owner review
before WRITE. Measured refresh permits review, not automatic dispatch.
Source the reviewed new common at `C`, then use this **complete WS W0
declarations replacement**, not the old WRITE common file:

```bash
: "${C:?Reviewed installed controller commit required}"
SEALED="$W/g8.sealed.json"
S=/home/m8-service/m8-n5-w8
F="$S/write"
SM="$S/smoke"
A=/var/lib/constructicon-m8-launch/qualification/stage4-write-g8.json
ID="n5-stage4g8-$C"
KEY=stage4g8
QUAL=("${PY[@]}" constructicon.api.qualification)
HOST=(--session "$W" --store-key "$K" --sealed "$SEALED"
  --qualification "$W/s6a-qualification.json" --state "$S")
```

Copy WS W1-W6 at `C` unchanged, in order. The short new state path retains
the native socket bound; its attempt/journal/report basenames are scoped by
new `S`. W2 refuses existing state/fixtures; W5 refuses any existing new
authorization. Neither touches the old `m8-n5-w` or `stage4-write.json`.
Failure abandons partial state, never repair it into apparent freshness.

Require W3's credential-free smoke to pass. **Pause after W4 for owner review
of the exact new pins and smoke verdict before W5 root installation.** The
authorization names the new graph, adapter, fixture, workspace, gate and report
identities. Old pins or the spent authorization cannot be reused at new `C`.
W5 installs only those approved pins; W6 is at most one new WRITE turn.

WRITE uses strict report schema 2; smoke stays at schema 1. Callback counts
are admitted observations, not an inbound/backend request count. Progress is
a lower bound; a final snapshot does not by itself mean all callbacks
completed or that directory sync succeeded. Successful supplied observations
must be final and complete; zero can be complete, legacy absence is unknown.
The qualification refuses captured no-change before writer checkpoint or gate
acquisition. None of these facts infers why the prior model made no change.

Non-passing, absent/malformed report or unexpected exit stops, preserving all
private state. No automatic retry, checker recovery, redispatch, refund or
cleanup is supplied. No READ rerun/T6 or shared N5 retry. A fixture pass neither
installs the target nor alone establishes `vendor_conformance_qualified`.

## Evidence and limits

Record reviewed code/procedure/source/package revisions and hashes, verified
old installation, boot/D2/LR records, checked continuity, fresh maintenance
digests and historical floor, g8 descriptor/stale-g7 proof, every H7 result,
applicable H8 evidence/digest/verdict, smoke, owner-reviewed pins and bounded
WRITE verdict on #78. Keep seals, locator-bearing authorizations, retained
journals/diagnostic state private. No credentials, account identifiers, model
text, callback programs/output or raw journal/gate records are posted.

Fake-shell tests establish only command composition and stopping behavior;
they establish no host state, physical installation, refresh or vendor WRITE.
All live steps require their separate exact-revision authorization and evidence.
