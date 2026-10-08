# M8 N5 Stage 2: the host update session

Status: command runbook for the separately authorized owner session (frozen
plan: M8-N5-state-review.md, Stage 2). Nothing here authorizes a host action,
and no command sends a model request. It moves the host to a new merged commit
`C` and requalifies the operator store there, without a new login:
- the launch and controller replacement;
- a fresh session directory;
- S4 and S6a under maintenance;
- generation g4, its active startup, and g3 refusing;
- then refresh attempts.

It reuses the N4 runbook (`M8-N4-operator-commands.md`, OC) and the
launch-replacement runbook (`M8-N4-launch-replacement.md`, LR) rather than
copying them. Where a step says "OC's S4 block", it means that bash block,
byte for byte.

## Decisions this session takes as given

Each is the recommended default. The owner's authorization confirms each one
or names its replacement.
1. **S6b and S6c run.** They are the declared refusals, and their shapes are
   measured on the real binary (#129).
2. **The plan continues N4's.** S4 is checked as `initial`, since N4's evidence
   predates the account seal. Its plan must be `pro`, the plan N4 qualified,
   or the session stops for the owner.
3. **Evidence is posted on #78**, the N5 issue.
4. **Refresh attempts stay on this boot.** A reboot makes the active binding
   refuse until maintenance re-anchors it. After a reboot, further attempts
   need their own authorized requalification into the next generation.
5. **The controller replacement (LR9) is authorized here.** The controller
   check at `C` refuses whenever `src/constructicon` changed since the
   installed commit.

## How to run

Run every block through a fresh, noninteractive SSH session, exactly as OC's
preamble describes, with stdin from the script or `/dev/null`.

The common file `n5-common.sh` is OC's two Setup blocks followed by this
block. Its later assignment of `W` wins over OC's:

```bash
W_OLD=/home/m8-service/m8-n4-session
W=/home/m8-service/m8-n5-stage2
```

`W_OLD` holds N4's g1 to g3 and their evidence, and this session only reads
it. S1 creates `W`, and nothing in it is ever reused or repaired. The LR
blocks set their own `W` for their workspaces; run them in their own shells,
never after loading the common file.

## H0. Authorization

The owner's comment on #78 names:
- `C`;
- this runbook, OC and LR;
- the five decisions above, or their replacements;
- that M8-D2 requalification and its baseline run under their own
  authorization when drift requires them.

A missing item is a stop.

## H1. Launch and controller at `C`

Run LR's Order: LR0 to LR6, then LR8, then LR9 if LR8 refused, then LR7. LR1's
anchor check names N4's newest descriptor:

```bash
binding_check "$W_OLD/g3.sealed.json" reboot-anchor -
```

LR7's preflight must print `"launch_ready": true`, under the controller at
`C`.

## H2. S0 at `C`

```bash
sudo -n true < /dev/null
/usr/local/bin/m8-host-drift < /dev/null
```

Require status zero, and the affirmative no-drift output, from both.

## H3. S1 into the fresh directory

OC's S1 block, unchanged; it creates `W`. It must print nothing and exit zero.
If it fails, the directory is abandoned, and a new attempt needs a new path.

## H4. S4, and the plan's continuity

OC's S4 block, then this block in the same session:

```bash
test "${S4_SEAL%%/*}" = pro \
  || { echo "S4's plan is not the plan N4 qualified; stop for the owner" >&2; exit 1; }
```

The `initial` check binds whatever identity S4 observes. From here on, every
check names that seal.

## H5. S6a

OC's S6a block, unchanged. Its second maintenance must refuse with exactly the
held-lock error, and `load_final_qualification` then requires S6a's seal to
equal S4's.

## H6. Publish and activate g4

S6a's checked digest is the attestation `Q`, as in OC's S5.

```bash
load_final_qualification
"${ROOT_STORE[@]}" publish --store-root "$R" --key "$K" --generation 4 \
  --qualification-evidence-digest "$Q" --service m8-service --wait 0 \
  < /dev/null | save_sealed "$W/g4.sealed.json"
check_sealed "$W/g4.sealed.json" "$Q"
"${ROOT_STORE[@]}" activate --store-root "$R" --key "$K" --generation 4 \
  --sealed "$W/g4.sealed.json" --qualification-evidence-digest "$Q" \
  --service m8-service --wait 0 < /dev/null
binding_check "$W/g4.sealed.json" accepted -
binding_check "$W_OLD/g3.sealed.json" stale-generation "$W/g4.sealed.json"
```

## H7. Active startup on g4, then the S6b and S6c refusals

This is OC's S8, at g4, with this session's file names. The active run is also
offered to the `refresh` checker, and either answer is recorded. A refusal
passes only with its exact faults.

```bash
load_final_qualification
"${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g4.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-lane" --evidence "$W/h7-active.json" < /dev/null
check_evidence active "$W/h7-active.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
if check_evidence refresh "$W/h7-active.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
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
  "$W/startup-policy.json" "$W/h7-no-chatgpt-policy.json" < /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g4.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/h7-no-chatgpt-policy.json" \
  --lane-dir "$W/h7-s6b-lane" --evidence "$W/h7-s6b-denial.json" --expect-denial \
  < /dev/null; then echo 'S6b unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence denial "$W/h7-s6b-denial.json" active "$SEAL" "$W/h7-no-chatgpt-policy.json" > /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g4.sealed.json" --expected "plus/${SEAL#*/}" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-s6c-lane" --evidence "$W/h7-s6c-plan-refusal.json" \
  < /dev/null; then echo 'S6c unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence wrongplan "$W/h7-s6c-plan-refusal.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
binding_check "$W_OLD/g3.sealed.json" stale-generation "$W/g4.sealed.json"
```

## H8. Refresh attempts

The token's expiry is not observable, so no elapsed time is a criterion. Each
attempt is its own authorized session on the same boot. It takes a number `N`,
passed beside `C`:

```text
ssh ... "C=$C N=$N /bin/bash -se"
```

Each attempt gets fresh lane and evidence names. One active startup is first
checked as `active`, which must pass, and then as `refresh`:

```bash
[[ "${N:?Set the attempt number}" =~ ^[1-9][0-9]?$ ]]
/usr/local/bin/m8-host-drift < /dev/null
load_final_qualification
"${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g4.sealed.json" --expected "$SEAL" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h8-$N-lane" --evidence "$W/h8-$N-refresh.json" < /dev/null
check_evidence active "$W/h8-$N-refresh.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
if check_evidence refresh "$W/h8-$N-refresh.json" active "$SEAL" "$W/startup-policy.json" > /dev/null
then echo refresh-measured; else echo refresh-unmeasured; fi
```

- **`refresh-measured` ends the attempts.** It requires a clean judged
  readback, an `auth.openai.com` connection and a changed credential, in that
  one run.
- **`refresh-unmeasured` is retained as such.** It is never read as zero spend
  or as a refresh.
- **A failed `active` check is a stop,** not an unmeasured attempt.
- **A refresh during S4 or S6a is recorded but never counted.** That evidence
  is under maintenance custody.

## Evidence and limits

Post on #78:
- the authorization link;
- LR's records;
- the S1 pin record;
- g4's sealed identity;
- the S4, S6a, H7 and H8 evidence, with their checked digests and verdicts;
- the S6a lock result.

Never post login output, a credential, token, code, email or account
identifier. `vendor_conformance_qualified` stays false until every control is
measured and the owner records a qualified disposition.
