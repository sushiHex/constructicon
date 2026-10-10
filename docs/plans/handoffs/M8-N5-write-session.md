# M8 N5 Stage 4: the one WRITE session

Status: implementation runbook; no host execution is established here.
This implements the accepted [Stage 4 design](M8-N5-stage4-write.md) and its
[owner clarifications](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6094163551).
The [READ disposition](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6101919423)
is final: no T6, vendor retry defaults retained inside the fixed deadline,
retry occurrence unknown, shared N5 retry unused.

## W0. Reviewed installation and authority

Before using any command, the session record on #78 must name the reviewed
merged controller commit `C`, this procedure revision, the owner authorization,
fresh boot and current qualified generation. The batched controller must
contain PR #147, PR #145 and the reviewed WRITE implementation. Follow the
existing fresh-boot launch/controller replacement and next-generation
qualification route first. This document supplies no substitute installation
or baseline command. A failed drift check stops; R6 is not implied.

Require exclusive operator custody. Reuse the reviewed operator common file
from that **completed** qualification, defining `SERVICE`, `PY`, `W`, `K`,
`L`, `load_final_qualification` and `binding_check`. Its exact `C`, generation
descriptor `SEALED`, and qualification evidence must be recorded and checked,
not guessed from the largest filename. The separately reviewed deployment
successor supplies these declarations; a placeholder is not runnable evidence.

Each block is a script file, run by non-interactive SSH with stdin
`/dev/null`, never pasted into an interactive shell. Preserve reviewed script
bytes, prove LF-only locally and compare SHA-256 on the VM before execution.
The common file's `set -Eeuo pipefail` and `umask 077` apply to these session
blocks, not to installation scripts that specify different shell options.

Append these declarations to the common file. The names are fresh: do not
reuse READ state or an earlier incomplete WRITE directory. The short state
path preserves the native socket length bound. `SEALED` is supplied by the
reviewed deployment successor, not selected by this block.

```bash
: "${C:?Reviewed installed controller commit required}"
: "${SEALED:?Reviewed active generation descriptor required}"
S=/home/m8-service/m8-n5-w
F="$S/write"
SM="$S/smoke"
A=/var/lib/constructicon-m8-launch/qualification/stage4-write.json
ID="n5-stage4-$C"
KEY=stage4
QUAL=("${PY[@]}" constructicon.api.qualification)
HOST=(--session "$W" --store-key "$K" --sealed "$SEALED"
  --qualification "$W/s6a-qualification.json" --state "$S")
```

The owner's authorization covers one WRITE turn, the fixed task and exact
fixture/gate, the 300-second WRITE grants, the 30-second checker and 20-second
check, and the two-hour pin window. Observation is 1200 seconds, not a total
cleanup deadline. Minting computes pins; root installation grants authority.
No token, backend-request or finite monetary ceiling is claimed.

## W1. Still the qualified host

```bash
sudo -n true < /dev/null
/usr/local/bin/m8-host-drift < /dev/null
load_final_qualification
binding_check "$SEALED" accepted -
```

Require every check to pass. A reboot, changed source/runtime/egress or
invalidated generation stops. Do not repair a failed qualification here.

## W2. Fresh state and two independent fixtures

```bash
"${SERVICE[@]}" /bin/mkdir -m 0700 "$S" < /dev/null
"${SERVICE[@]}" /usr/bin/git init --bare -q "$S/closure.git" < /dev/null
"${SERVICE[@]}" "${QUAL[@]}" prepare-write --fixture "$F" < /dev/null
"${SERVICE[@]}" "${QUAL[@]}" prepare-write --fixture "$SM" < /dev/null
```

The helpers require canonical private service custody and refuse existing
fixture roots. Each has its own empty seed authority and acquisition roots.
No CI helper runs on the host. Failure abandons partial output; never delete
an attempt record or repair an incomplete fixture into an apparently fresh one.

## W3. Credential-free smoke

```bash
"${SERVICE[@]}" "${QUAL[@]}" smoke-write --fixture "$SM" --launch-root "$L" \
  < /dev/null | "${SERVICE[@]}" /bin/sh -c \
  'set -Ceu; umask 077; cat >"$1"' sh "$S/smoke-report.json"
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
assert r["verdict"] == "passed"
print(json.dumps(r, sort_keys=True))' "$S/smoke-report.json" < /dev/null
```

Smoke runs the real deterministic worker, capture and fixed gate without a
Codex provider, store lock, account read or model request. Require its bounded
report to pass before continuing. It has its own journal and cannot qualify
authenticated callbacks. The WRITE fixture is independently rechecked when
minting and again before recovery/dispatch.

## W4. Compute and review the WRITE pins

```bash
"${SERVICE[@]}" "${QUAL[@]}" mint "${HOST[@]}" --stage qualification-write \
  --fixture "$F" --authorization-id "$ID" --actor operator:n5-stage4 --key "$KEY" \
  --attempt-record "$S/stage4.attempt" --journal "$S/stage4.sqlite" --hours 2 \
  < /dev/null | "${SERVICE[@]}" /bin/sh -c \
  'set -Ceu; umask 077; cat >"$1"' sh "$S/minted.json"
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, sys
a = json.load(open(sys.argv[1], encoding="utf-8"))
assert a["stage"] == "qualification-write" and a["max_epoch"] == 1
assert a["attempt_record"] == sys.argv[2] and a["journal"] == sys.argv[3]
assert a["grants"]["posture"] == "write" and a["grants"]["timeout_s"] == 300
assert a["grants"]["allowed_tools"] == ["contained_python"]
assert a["write"]["fixture"]["target_ref"] == "refs/heads/n5-write"
print(json.dumps({key: a[key] for key in ("authorization_id", "source_graph_hash",
    "revision", "operator_binding_digest", "not_after", "write")}, sort_keys=True))' \
  "$S/minted.json" "$S/stage4.attempt" "$S/stage4.sqlite" < /dev/null
```

Record the exact reviewed pins and smoke verdict on #78 before W5. They bind
the actual workspace/gate revisions, fixture/base and report definition, not
only the executor. Keep the full locator-bearing authorization private.

## W5. Root installs the reviewed authorization

Only after the owner-approved session's pin review:

```bash
sudo -n /usr/bin/test ! -e "$A" < /dev/null
sudo -n /usr/bin/test ! -L "$A" < /dev/null
sudo -n /usr/bin/install -d -o root -g root -m 0755 "${A%/*}" < /dev/null
sudo -n /usr/bin/install -o root -g m8-service -m 0640 "$S/minted.json" "$A" < /dev/null
```

Do not overwrite an existing authorization. The existing root-file reader
checks ownership, mode, links, ancestor custody and its 8192-byte bound.

## W6. The one WRITE turn and its derived verdict

```bash
if "${SERVICE[@]}" "${QUAL[@]}" run "${HOST[@]}" --authorization "$A" \
  --fixture "$F" --timeout 1200 < /dev/null \
  | "${SERVICE[@]}" /bin/sh -c 'set -Ceu; umask 077; cat >"$1"' sh "$S/write-report.json"
then WRITE_EXIT=0; else WRITE_EXIT=$?; fi
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
assert r["verdict"] in ("passed", "not-qualified", "incomplete")
assert int(sys.argv[2]) in (0, 1)
assert (r["verdict"] == "passed") == (int(sys.argv[2]) == 0)
print(json.dumps(r, sort_keys=True))' "$S/write-report.json" "$WRITE_EXIT" < /dev/null
```

Run W6 once. `passed` requires a completed attempt, exact captured change,
candidate-bound journal attestation, succeeded run, affirmatively settled
obligations and unchanged target. A completed turn alone is not WRITE success.
Missing, contradictory, oversized or unsettled evidence cannot pass. The
report is emitted only after joining control shutdown. An empty/malformed
file, absent report or unexpected exit is a stop, never a passing verdict.

On any other verdict, stop and preserve the state, attempt and authority.
No recovery or retry command is authorized here. A valid writer checkpoint
can permit checker-only recovery without another acquisition; absent that
checkpoint a spent record refuses writer replay. Diagnosis and a separate
owner decision must precede either path. Possible dispatch, wrong output,
capture failure or gate failure never refunds the model attempt.

## Evidence and limits

Post the authorization/procedure/controller references, boot/generation,
checked drift and binding results, smoke report, reviewed pins and bounded
WRITE report on #78. Never post credentials, account ids, private seals,
model text, callback code/output, host paths or raw journal/gate details.
Retain the private files for diagnosis; no automatic cleanup is prescribed.

The existing READ logged-out rehearsal does not prove WRITE's assembled
path. A WRITE logged-out rehearsal is a separate proof: it can establish only
pre-dispatch refusal and spent-record behavior, never authenticated acceptance.
Its execution remains unverified until recorded on the implementation PR.
Scripted physical acceptance proves worker/capture/gate composition, not a
vendor account. Host smoke and the live WRITE result remain unrun until
separately recorded. A passed fixture does not install a target or by itself
set `vendor_conformance_qualified` true.
