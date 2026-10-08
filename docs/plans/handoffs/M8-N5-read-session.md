# M8 N5 Stage 3: the one READ turn session

Status: command runbook for the separately authorized owner session (frozen
plan: M8-N5-state-review.md, Stage 3, and its refusal and retry rules). Nothing
here authorizes a host action. Exactly one command, T5's `run`, may send a
model request, and only once.

It runs on the host Stage 2 left (`M8-N5-host-session.md`, HS):
- the controller at HS's commit `C`;
- generation g4 active, with its sealed identity and S6a's evidence in HS's
  `W`.

It reuses HS's common file and OC's functions (`M8-N4-operator-commands.md`)
rather than copying them. The code it runs is `constructicon.api.qualification`
at `C` (M8-N5-stage3-read.md).

## How to run

As HS describes, each block runs through a fresh, noninteractive SSH session
with stdin from the script or `/dev/null`. The common file is HS's
`n5-common.sh` followed by this block:

```bash
S=/home/m8-service/m8-n5-stage3
A=/var/lib/constructicon-m8-launch/qualification/stage3-read.json
ID="n5-stage3-$C"
KEY=stage3
QUAL=("${PY[@]}" constructicon.api.qualification)
HOST=(--session "$W" --store-key "$K" --sealed "$W/g4.sealed.json"
  --qualification "$W/s6a-qualification.json" --state "$S")
```

`S` is this attempt's service-owned state: the closure authority, the
acquisitions, the journal and the attempt record. It is short because the
native egress socket under it is bounded to 107 bytes; the provider refuses a
longer one. `A` is the authorization, which only root installs. `ID` and `KEY` name the
authorization and its run.

## T0. Authorization

The owner's comment on #78 names:
- `C`, the commit HS ran at;
- this runbook;
- the fixed task, as the source of `qualification_read_node` at `C`;
- one READ turn, under the READ grants at `C` (120 s);
- the window: two hours from T3.

A missing item is a stop. The authorization is one attempt: a retry is a new
authorization (T6).

## T1. The host is still Stage 2's

```bash
sudo -n true < /dev/null
/usr/local/bin/m8-host-drift < /dev/null
load_final_qualification
binding_check "$W/g4.sealed.json" accepted -
```

Require status zero from each. `load_final_qualification` re-checks S6a's
evidence and its seal. The binding check fails after a reboot (HS decision 4),
which is a stop, not a repair.

## T2. Fresh state

```bash
"${SERVICE[@]}" /bin/mkdir -m 0700 "$S" < /dev/null
"${SERVICE[@]}" /usr/bin/git init --bare -q "$S/closure.git" < /dev/null
```

`mkdir` refuses an existing `S`: nothing in it is ever reused. A failed attempt
abandons `S`, and a new one needs a new path, recorded in T0's authorization.

## T3. Mint the pins

The service computes the authorization from this host's assembled provider,
which stays unavailable. Minting is computation, not authority.

```bash
"${SERVICE[@]}" "${QUAL[@]}" mint "${HOST[@]}" --stage qualification-read \
  --authorization-id "$ID" --actor operator:n5-stage3 --key "$KEY" \
  --attempt-record "$S/stage3.attempt" --journal "$S/stage3.sqlite" --hours 2 \
  < /dev/null | "${SERVICE[@]}" /bin/sh -c 'set -Ceu; umask 077; cat >"$1"' sh "$S/minted.json"
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, sys
a = json.load(open(sys.argv[1], encoding="utf-8"))
assert a["stage"] == "qualification-read" and a["max_epoch"] == 1
assert a["attempt_record"] == sys.argv[2] and a["journal"] == sys.argv[3]
assert a["grants"]["posture"] == "read" and a["grants"]["timeout_s"] == 120
print(json.dumps({key: a[key] for key in ("authorization_id", "source_graph_hash", "revision",
    "operator_binding_digest", "not_after")}, sort_keys=True))' \
  "$S/minted.json" "$S/stage3.attempt" "$S/stage3.sqlite" < /dev/null
```

The printed pins go to the owner.

## T4. Root installs the authorization

Only after the owner has reviewed T3's pins:

```bash
sudo -n /usr/bin/install -d -o root -g root -m 0755 "${A%/*}" < /dev/null
sudo -n /usr/bin/install -o root -g m8-service -m 0640 "$S/minted.json" "$A" < /dev/null
```

The reader accepts only this shape: root-owned, group `m8-service`, mode
`0640`, one link, under root-owned directories.

## T5. The one READ turn

```bash
"${SERVICE[@]}" "${QUAL[@]}" run "${HOST[@]}" --authorization "$A" --timeout 600 \
  < /dev/null || true
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, os, sys
if not os.path.exists(sys.argv[1]):
    print("never-acquired"); raise SystemExit
r = json.load(open(sys.argv[1], encoding="utf-8"))
verdict = {"completed": "completed", "not dispatched": "not-dispatched"}.get(
    r.get("dispatch"), "acquired-only" if r["phase"] == "acquired" else "possibly-dispatched")
print(verdict)' "$S/stage3.attempt" < /dev/null
```

`run` prints only the run's status. The attempt record is the verdict:
- **`completed`:** Stage 3 passed. The record holds the answer's length, usage
  or "unknown", the served model or "unknown", the readbacks, relay counts,
  process facts and identities, and never the answer's text.
- **`not-dispatched`**, **`acquired-only`** or **`never-acquired`:**
  `turn/start` was never written whole. If the failure is diagnosed as local,
  T6 applies.
- **`possibly-dispatched`:** a record left at its intent, or a turn that ended
  without an accepted answer. It is never retried automatically; stop for the
  owner. A wrong answer is not a local failure.

A second `run` of the same authorization refuses at acquisition: the record
already exists, whatever the journal holds.

## T6. One retry, only after a diagnosed local failure

Only for those three verdicts, with the failure diagnosed as
local, and only once. The owner's new comment on #78 names the diagnosis.
Then T2 to T5 run again with this block appended to the common file:

```bash
S=/home/m8-service/m8-n5-stage3r
A=/var/lib/constructicon-m8-launch/qualification/stage3-read-retry.json
ID="n5-stage3r-$C"
KEY=stage3r
```

Every name is new: the state, the record, the journal, the authorization and
its run.

## Evidence and limits

Post on #78:
- the authorization link;
- T3's pins;
- `run`'s status;
- the attempt record (every phase it reached is in its last write).

Never post a credential, token, code, email, account identifier or the
answer's text. `vendor_conformance_qualified` stays false.
