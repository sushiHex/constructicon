# M8 N4 operator commands

Status: command runbook draft for the separately authorized owner session. Nothing
here authorizes a host action. The accepted N4 state review and its S0--S10
limits govern. No command below sends a model request. A failed or unmeasured
control leaves the profile unqualified; stop and retain its bounded evidence.

Put the two Setup bash blocks in one local `n4-common.sh` file and each step's
bash block in its own local `n4-s0.sh` through `n4-s10.sh` file. Run each step
through a fresh, noninteractive SSH session; do not paste commands into an
interactive VM shell. From workstation Bash, set the owner-authorized `C` and
SSH target, then use this pattern for each step (substitute the step filename):

```bash
set -Eeuo pipefail
: "${C:?Set the owner-authorized merged commit}"
: "${SSH_TARGET:?Set the owner-authorized VM SSH target}"
[[ "$C" =~ ^[0-9a-f]{40}$ ]]
{ /usr/bin/cat n4-common.sh n4-s0.sh; } | /usr/bin/ssh -T -o BatchMode=yes "$SSH_TARGET" "C=$C /bin/bash -se"
```

The common file defines variables and functions in every session; it does not
rerun a step. Run S0, S1, S2, S3, S4, S6a, S5, S7, then S8, then the two separately authorized
PowerShell VM commands in S9, then S9's bash block with a fresh SSH session.
Run S10 through another fresh SSH session after the wait. Every command's
stdin is either the explicit script stream or `/dev/null`; the SSH session
does not preserve shell variables between steps. Use fresh filenames shown
here; no step is an in-place retry. Do not run a CI, artifact installer, or
drift-baseline *creation* command in this session.

## Setup: fixed controller and evidence checks

The controller is an unpacked tree at `/opt/constructicon-m8-controller`.
This is the reviewed isolated Python bootstrap, equivalent to
`scripts/ci/m8_host_artifacts.py:controller_command`. Root invokes only
`operator_store`; `maintain` drops to `m8-service` before the lane starts.
The setup is read-only. `C` is the separately authorized merged commit and
`W` is a fresh service-owned output directory that S1 will create.

```bash
set -Eeuo pipefail
umask 077
: "${C:?Set the owner-authorized 40-hex merged commit before running this script}"
R=/var/lib/constructicon-m8-launch/operator-stores
L=/var/lib/constructicon-m8-launch
K=n4-codex-pro
W=/home/m8-service/m8-n4-session
PY=(/usr/bin/python3 -I -S -B -c 'import sys; sys.path.insert(0, "/opt/constructicon-m8-controller"); import runpy; runpy.run_module(sys.argv.pop(1), run_name="__main__", alter_sys=True)')
ROOT_MODULE=constructicon.substrate.executors.operator_store
LANE_MODULE=constructicon.substrate.executors.codex_lane
SERVICE=(sudo -n -u m8-service /usr/bin/env -i PATH=/usr/bin:/bin HOME=/home/m8-service LANG=C.UTF-8)
ROOT_STORE=(sudo -n "${PY[@]}" "$ROOT_MODULE")
LANE=("${PY[@]}" "$LANE_MODULE")
[[ "$C" =~ ^[0-9a-f]{40}$ ]]
```

The following shell functions check the completed producer records as the
service user. `check_evidence MODE FILE CUSTODY EXPECTED POLICY` prints the
same content digest as `EvidenceFile.publish`, only after a closed-schema and
affirmative-fact check. `MODE` is `login`, `qualify`, `hold`, `active`,
`denial`, `wrongplan`, or `refresh`. `EXPECTED` is `-` until the plan has been
observed, then the closed `pro`/`prolite` literal. The refusal modes require
their exact expected faults; any additional fault stops the session. The
checker reads no credential and emits no identity or transcript content.

```bash
check_evidence() {
  test "$#" -eq 5
  "${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, stat, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.core.identity import canonical_json, digest
from constructicon.substrate.executors.codex_lane import (EVIDENCE_DOMAIN, LANE_SCHEMA, LOGIN_FIELDS, STARTUP_FIELDS, STARTUP_METHODS, QUALIFICATION_PLANS, configuration_digest, _policy)
from constructicon.substrate.executors.codex_protocol import SPEND_FIELDS, USAGE_FIELDS, SPEND_UNREADABLE_FAULT, named_method, named_value
from constructicon.substrate.executors.egress import identity_digests
mode, name, custody, expected, policy_name, directory = sys.argv[1:]
def require(value):
    if not value: raise ValueError("lane evidence lacks an affirmative required fact")
path = Path(name)
info = path.stat()
require(stat.S_ISREG(info.st_mode) and info.st_size <= 1048576 and info.st_size > 0)
raw = path.read_bytes()
require(len(raw) == info.st_size)
def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result
e = json.loads(raw, object_pairs_hook=no_duplicates)
login = mode == "login"
require(type(e) is dict and set(e) == set(LOGIN_FIELDS if login else STARTUP_FIELDS) | {"completed"})
require(e["completed"] is True and e["schema_version"] == LANE_SCHEMA)
require(e["lane"] == ("login" if login else "startup"))
require(e["vendor_identity"] == "unverified" and e["vendor_conformance_qualified"] is False)
require(type(e["faults"]) is list and all(type(x) is str for x in e["faults"]))
require(type(e["custody"]) is dict and e["custody"].get("kind") == custody)
require(set(e["custody"]) == ({"kind", "generation_floor"} if custody == "maintenance" else {"kind", "binding_digest"}))
config = (Path(directory) / "config.toml").read_text(encoding="utf-8")
require(e["configuration_digest"] == str(configuration_digest(config)))
policy = _policy(Path(policy_name))
require(e["egress"] == {key: str(value) for key, value in identity_digests(policy).items()})
require(type(e["relay"]) is dict and set(e["relay"]) == {"destinations", "denied", "closed"})
require(e["relay"]["closed"] is True and type(e["relay"]["destinations"]) is dict and type(e["relay"]["denied"]) is dict)
sealed = {f"{kind}:{item.host}:{item.port}" for kind in ("accepted", "relayed") for item in policy.destinations}
require(set(e["relay"]["destinations"]) <= sealed)
require(all(type(value) is int and value > 0 for value in e["relay"]["destinations"].values()))
require(all(type(value) is int and value > 0 for value in e["relay"]["denied"].values()))
require(type(e["credential"]) is dict and set(e["credential"]) == {"present", "regular_0600", "mtime_changed", "checked"})
require(e["credential"]["present"] is True and e["credential"]["regular_0600"] is True and e["credential"]["checked"] is True)
p = e["process"]
require(type(p) is dict and set(p) == {"returncode", "payload_returncode", "timed_out", "bound_exceeded", "exchange_failed", "elapsed_s", "stderr_bytes"})
require(p["returncode"] == 0 and p["payload_returncode"] == 0 and p["timed_out"] is False and p["bound_exceeded"] is False and p["exchange_failed"] is False)
require(type(p["elapsed_s"]) in (int, float) and p["elapsed_s"] >= 0 and type(p["stderr_bytes"]) is int and p["stderr_bytes"] >= 0)
if login:
    require(custody == "maintenance" and expected == "-" and e["faults"] == [])
    require(e["credential"]["mtime_changed"] is True and e["relay"]["denied"] == {})
else:
    methods = [named_method(item) for item in STARTUP_METHODS]
    require(type(e["methods_sent"]) is list and type(e["withheld_methods"]) is list)
    require(type(e["gate"]) is dict and set(e["gate"]) == {"completed", "plan"})
    require(e["observation"] == {"malformed_records": 0, "first_error": False})
    require(e["refresh"] in ("measured", "unmeasured"))
    require(e["hold_s"] == (90 if mode == "hold" else 0))
    if mode == "wrongplan":
        require(custody == "active" and expected in QUALIFICATION_PLANS)
        require(e["methods_sent"] == methods[:3] and e["gate"] == {"completed": False, "plan": None} and e["readback"] is None)
        wrong_plan = "account plan " + named_value(expected) + " is not the expected " + repr("plus")
        required_faults = {wrong_plan, "the startup gate did not complete", "the startup did not send exactly the four authorized methods", "no spend readback was judged"}
        require(set(e["faults"]) == required_faults and len(e["faults"]) == len(required_faults))
        require(e["relay"]["denied"] == {})
    elif mode == "denial":
        require(custody == "active" and expected in QUALIFICATION_PLANS)
        require(e["methods_sent"] == methods and e["gate"] == {"completed": False, "plan": expected} and e["readback"] is None)
        required_faults = {SPEND_UNREADABLE_FAULT, "the startup gate did not complete", "no spend readback was judged"}
        require(set(e["faults"]) == required_faults and len(e["faults"]) == len(required_faults))
        require(set(e["relay"]["denied"]) == {"denied:destination"} and e["relay"]["denied"]["denied:destination"] >= 1)
    else:
        require(mode in ("qualify", "hold", "active", "refresh") and e["faults"] == [])
        require(e["methods_sent"] == methods and e["gate"]["completed"] is True)
        require(e["gate"]["plan"] in QUALIFICATION_PLANS and (expected == "-" or e["gate"]["plan"] == expected))
        require(type(e["readback"]) is dict and set(e["readback"]) == set(SPEND_FIELDS) | set(USAGE_FIELDS))
        require(e["readback"]["has_credits"] is False and e["readback"]["unlimited"] is False and e["readback"]["balance_zero"] is not False)
        require(e["relay"]["denied"] == {})
        require(custody == ("maintenance" if mode in ("qualify", "hold") else "active"))
        if mode == "refresh":
            require(e["refresh"] == "measured" and e["credential"]["mtime_changed"] is True)
            require(e["relay"]["destinations"].get("accepted:auth.openai.com:443", 0) > 0)
print(digest(EVIDENCE_DOMAIN, 1, json.loads(canonical_json(e))))' \
    "$1" "$2" "$3" "$4" "$5" "$W" < /dev/null
}
check_sealed() {
  test "$#" -eq 2
  "${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import stat, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.substrate.executors.operator_store import UNQUALIFIED_REVISION
path = Path(sys.argv[1]); info = path.stat()
if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 1048576: raise ValueError("sealed identity file is unavailable")
identity = NativeOperatorStoreIdentityV1.model_validate_json(path.read_bytes())
revision = str(UNQUALIFIED_REVISION) if sys.argv[2] == "unqualified" else sys.argv[2]
if str(identity.subscription_mode_adapter_revision) != revision or str(identity.store_conformance_revision) != revision:
    raise ValueError("sealed identity revisions do not match")
print("sealed-identity-checked")' "$1" "$2" < /dev/null | /usr/bin/grep -qxF sealed-identity-checked
}
save_sealed() {
  test "$#" -eq 1
  "${SERVICE[@]}" /bin/sh -c 'set -Ceu; umask 077; cat >"$1"' sh "$1"
}
read_plan() {
  test "$#" -eq 1
  "${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.substrate.executors.codex_lane import QUALIFICATION_PLANS
plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["gate"]["plan"]
if plan not in QUALIFICATION_PLANS: raise ValueError("qualification has no approved plan literal")
print(plan)' "$1" < /dev/null
}
binding_check() {
  test "$#" -eq 3
  "${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import asyncio, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.core.errors import ContractViolation
from constructicon.core.native_operator import NativeOperatorStoreIdentityV1
from constructicon.substrate.executors.operator_store import BindingStore
async def no_closure(): pass
async def open_binding(sealed):
    held = None
    store = BindingStore(Path(sys.argv[1]), sys.argv[2], sealed)
    try:
        held = await asyncio.wait_for(store.acquire_lock(store.open_candidate(), lambda: None, no_closure), timeout=10)
        store.check_held(held)
    finally:
        if held is not None: store.close_held(held)
async def check():
    sealed = NativeOperatorStoreIdentityV1.model_validate_json(Path(sys.argv[3]).read_bytes())
    mode = sys.argv[4]
    if mode == "accepted":
        if sys.argv[5] != "-": raise ValueError("accepted check has an unexpected comparison")
        await open_binding(sealed)
    elif mode == "stale-generation":
        current = NativeOperatorStoreIdentityV1.model_validate_json(Path(sys.argv[5]).read_bytes())
        if sealed.operator_binding_digest == current.operator_binding_digest:
            raise ValueError("old and current binding digests are identical")
        await open_binding(current)
        try: await open_binding(sealed)
        except ContractViolation as exc:
            if str(exc) != "native store binding is unavailable": raise
        else: raise ValueError("stale sealed binding was accepted")
    elif mode == "reboot-anchor":
        if sys.argv[5] != "-": raise ValueError("reboot check has an unexpected comparison")
        try: await open_binding(sealed)
        except ContractViolation as exc:
            if str(exc) != "native store anchor is unavailable": raise
        else: raise ValueError("pre-reanchor binding was accepted")
    else: raise ValueError("unknown binding check mode")
    print(mode)
asyncio.run(check())' "$R" "$K" "$1" "$2" "$3" < /dev/null | /usr/bin/grep -qxF "$2"
}
load_s4_plan() {
  check_evidence qualify "$W/s4-qualification.json" maintenance - "$W/startup-policy.json" > /dev/null
  S4_PLAN="$(read_plan "$W/s4-qualification.json")"
}
load_final_qualification() {
  load_s4_plan
  Q="$(check_evidence hold "$W/s6a-qualification.json" maintenance "$S4_PLAN" "$W/startup-policy.json")"
  test "${Q#sha256:}" != "$Q" && test "${#Q}" -eq 71
  PLAN="$(read_plan "$W/s6a-qualification.json")"
  test "$PLAN" = "$S4_PLAN"
}
```

The digest checker is deliberately strict. A different refusal shape or a
failed checker is a stop, even if the lane returned status 1. `check_sealed`
accepts only a service-readable identity; root's activation code independently
checks the descriptor and withdrawal. The `save_sealed` pipe carries public
identity JSON only and uses create-exclusive shell redirection (`set -C`).

## Operator session

### S0. Preconditions

Confirm and record the links on #77 before touching the host: the written
owner authorization for this exact session; N3c and #73 evidence; deletion of
the `pre-m8-artifacts` checkpoint under its own authorization; the N4 PR
merged at `C` with green checks; the launch runtime verified at `C`; and the
controller separately installed and verified at the same `C` under its R15
authorization. Obtain the existing passing `m8-host-drift` baseline record
from #73/R6. Then run the host's bare no-drift check, whose invocation is
recorded in the R2 host-interface evidence. Require status zero and the
affirmative no-drift output. The command below checks the existing baseline;
it does not create or update one. If any record or matching commit is
missing, stop.
If `sudo -n true` fails, stop before the drift check or any store operation;
the session has no noninteractive root authority.

```bash
sudo -n true < /dev/null
/usr/local/bin/m8-host-drift < /dev/null
```

### S1. Prepare

Run as `m8-service`, with `W` absent. The resolver is called once per fixed
host; only the first globally routable IPv4 answer is selected. The directory
is created `0700` and contains exactly `config.toml`, `login-policy.json`,
`startup-policy.json`, and the final `pin-record.json`. All files are `0600`.
The login policy seals only `auth.openai.com:443`; startup seals that host and
`chatgpt.com:443`, both with a connection bound of 8. The configuration has
the reviewed `gpt-5.5` model, bound catalog and disabled auxiliary features.

```bash
"${SERVICE[@]}" "${LANE[@]}" prepare --out "$W" < /dev/null
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, stat, sys
from pathlib import Path
w = Path(sys.argv[1]); names = {"config.toml", "login-policy.json", "startup-policy.json", "pin-record.json"}
assert stat.S_IMODE(w.stat().st_mode) == 0o700 and {p.name for p in w.iterdir()} == names
assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in w.iterdir())
p = json.loads((w / "pin-record.json").read_text(encoding="utf-8"))
assert p["schema_version"] == 1 and p["completed"] is True and len(p["pins"]) == 2
assert [x["host"] for x in p["pins"]] == ["auth.openai.com", "chatgpt.com"]
assert all(x["resolver"] == "system getaddrinfo" for x in p["pins"])
print("s1-completed")' "$W" < /dev/null | /usr/bin/grep -qxF s1-completed
```

Keep the completed pin record for S9's same-policy comparison. An exception or
crash may leave an incomplete `W`; never repair or reuse it. A new attempt
needs a new path and, where applicable, fresh authorization.

### S2. First provisioning

Root provisions fresh unqualified g1 in the already installed protected store
root. The lane will create the first empty credential under maintenance in S3.
No shell command creates `auth.json` and no selection becomes active here.

```bash
"${ROOT_STORE[@]}" provision --store-root "$R" --key "$K" \
  --service m8-service --wait 0 < /dev/null | save_sealed "$W/g1.sealed.json"
check_sealed "$W/g1.sealed.json" unqualified
```

### S3. Login

Root withdraws through `maintain`; the child is `m8-service` with only the
inherited lock and terminal descriptors. The owner sees the device URL and
one-time code on the terminal and completes sign-in on their own device. Do
not save stdout, stderr text, code, account identifier, or credential bytes.

`preflight` runs first, as the service. It runs every check a lane makes before
its vendor process: the artifact checks and the benign physical launch probe,
which also proves the `constructicon-m8-launch//&constructicon-m8-workload
(enforce)` child attachment. It starts no vendor process. A failure stops
the session before a device code exists, so the owner's sign-in window is
never spent on a launch-set defect.

```bash
"${SERVICE[@]}" "${LANE[@]}" preflight --launch-root "$L" < /dev/null | \
  /usr/bin/grep -qF '"launch_ready": true'
"${ROOT_STORE[@]}" maintain --store-root "$R" --key "$K" \
  --service m8-service --wait 0 -- \
  "${LANE[@]}" login --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/login-policy.json" \
  --lane-dir "$W/s3-lane" --evidence "$W/s3-login.json" --first-login < /dev/null
check_evidence login "$W/s3-login.json" maintenance - "$W/login-policy.json" > /dev/null
"${SERVICE[@]}" /bin/sh -c 'set -Ceu; umask 077; /usr/bin/date -u +%Y-%m-%dT%H:%M:%SZ >"$1"' \
  sh "$W/s3-completed-at.utc" < /dev/null
```

The timestamp is written only after the affirmative login check, making it a
conservative lower bound for S10's 24-hour wait. It contains no secret.

### S4. Qualification

Run a new maintenance startup with no `--expected`; maintenance admits only
the built-in `(pro, prolite)` pair. It sends exactly `initialize`,
`initialized`, `account/read`, `account/rateLimits/read`, then closes stdin.
The checked evidence contains the observed plan and a judged spend readback.

```bash
"${ROOT_STORE[@]}" maintain --store-root "$R" --key "$K" \
  --service m8-service --wait 0 -- \
  "${LANE[@]}" startup --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/s4-lane" --evidence "$W/s4-qualification.json" < /dev/null
check_evidence qualify "$W/s4-qualification.json" maintenance - "$W/startup-policy.json" > /dev/null
S4_PLAN="$(read_plan "$W/s4-qualification.json")"
```

### S6a. Maintenance-lock positive control

This runs before S5. It is another maintenance withdrawal, so S4 cannot be
the evidence named by the next published descriptor. The held startup below
becomes the final qualification. It pauses for 90 seconds after the gate and
before stdin closes. A separate nonblocking maintenance attempt must refuse
on the retained lock. No second vendor process is run for that attempt.

```bash
load_s4_plan
"${ROOT_STORE[@]}" maintain --store-root "$R" --key "$K" \
  --service m8-service --wait 5 -- \
  "${LANE[@]}" startup --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/s6a-lane" --evidence "$W/s6a-qualification.json" --hold 90 \
  < /dev/null > /dev/null 2> /dev/null &
H=$!
T="$("${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import sys; sys.path.insert(0, "/opt/constructicon-m8-controller"); from constructicon.substrate.executors.operator_store import _bundle_token; print(_bundle_token(sys.argv[1]))' "$K" < /dev/null)"
LOCK="$R/$T/retained.lock"
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import fcntl, os, sys, time
deadline = time.monotonic() + 30
while True:
    fd = os.open(sys.argv[1], os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("lock_held")
        raise SystemExit(0)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
    if time.monotonic() >= deadline: raise SystemExit(1)
    time.sleep(0.1)' "$LOCK" < /dev/null | /usr/bin/grep -qxF lock_held
if SECOND="$("${ROOT_STORE[@]}" maintain --store-root "$R" --key "$K" \
  --service m8-service --wait 0 -- /usr/bin/true < /dev/null 2>&1)"; then
  echo 'unexpected second maintenance acceptance' >&2; exit 1
else
  test "$?" -eq 1
fi
printf '%s\n' "$SECOND" | /usr/bin/tail -n 1 | \
  /usr/bin/grep -qxF 'constructicon.core.errors.ContractViolation: native store retained lock is held'
wait "$H"
check_evidence hold "$W/s6a-qualification.json" maintenance "$S4_PLAN" "$W/startup-policy.json" > /dev/null
```

The probe observes a held lock, not its owner. The first lane's completed
evidence and terminal custody check supply the second fact. A timeout or a
different traceback is a failed control.

### S5. Publish g2

The checked digest of S6a, not S4, is the operator attestation `Q`. Root puts
that exact digest in both conformance revisions of g2. Publication alone
does not select a generation.

```bash
load_final_qualification
"${ROOT_STORE[@]}" publish --store-root "$R" --key "$K" --generation 2 \
  --qualification-evidence-digest "$Q" --service m8-service --wait 0 \
  < /dev/null | save_sealed "$W/g2.sealed.json"
check_sealed "$W/g2.sealed.json" "$Q"
```

### S7. Activate g2

Root invokes the existing activation law using the sealed g2 identity. The
fresh service-side `BindingStore` check is the affirmative selection result.

```bash
load_final_qualification
"${ROOT_STORE[@]}" activate --store-root "$R" --key "$K" --generation 2 \
  --sealed "$W/g2.sealed.json" --qualification-evidence-digest "$Q" \
  --service m8-service --wait 0 < /dev/null
binding_check "$W/g2.sealed.json" accepted -
binding_check "$W/g1.sealed.json" stale-generation "$W/g2.sealed.json"
```

### S8. Active startup and S6b/S6c refusals

The active startup uses the exact observed `PLAN` and the S1 policy. Then
run the two separately declared refusals. A refusal passes only if its
completed evidence has the specific faults and facts checked below.

```bash
load_final_qualification
"${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g2.sealed.json" --expected "$PLAN" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/s8-lane" --evidence "$W/s8-active.json" < /dev/null
check_evidence active "$W/s8-active.json" active "$PLAN" "$W/startup-policy.json" > /dev/null
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, os, sys
from pathlib import Path
p = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert p["connections"] == 8 and len(p["destinations"]) == 2
assert [x[0] for x in p["destinations"]] == ["auth.openai.com", "chatgpt.com"]
p["destinations"] = p["destinations"][:1]
os.umask(0o077)
with open(sys.argv[2], "x", encoding="utf-8") as stream:
    json.dump(p, stream, sort_keys=True); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())' \
  "$W/startup-policy.json" "$W/s6b-no-chatgpt-policy.json" < /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g2.sealed.json" --expected "$PLAN" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/s6b-no-chatgpt-policy.json" \
  --lane-dir "$W/s6b-lane" --evidence "$W/s6b-denial.json" --expect-denial \
  < /dev/null; then echo 'S6b unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence denial "$W/s6b-denial.json" active "$PLAN" "$W/s6b-no-chatgpt-policy.json" > /dev/null
if "${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g2.sealed.json" --expected plus --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/s6c-lane" --evidence "$W/s6c-plan-refusal.json" \
  < /dev/null; then echo 'S6c unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
check_evidence wrongplan "$W/s6c-plan-refusal.json" active "$PLAN" "$W/startup-policy.json" > /dev/null
binding_check "$W/g1.sealed.json" stale-generation "$W/g2.sealed.json"
```

S6b's policy removes `chatgpt.com`, so the rate-limit readback is denied.
S6c sends `--expected plus`, so the observed approved plan refuses at the
account gate. Both methods lists are checked using the producer's
`named_method` representation. Neither path sends `thread/start`.

### S9. Restart

Use the separately authorized clean VM restart. Do not save or restore a VM
checkpoint after login. On the workstation:

```powershell
Stop-VM constructicon-m8
Start-VM constructicon-m8
```

Run S9's bash script through a new, noninteractive SSH session. The common
setup is loaded again, but S1 and provisioning are not repeated. Recompute
`Q` and `PLAN` from S4 and S6a's retained checked records. Require the bare
host drift check again before any store or lane operation. Before maintenance,
the old binding must refuse for the specific boot-bound anchor reason.
Root's publish helper must also refuse before re-anchoring; its failure output
is checked, and no new descriptor is accepted from that call.

```bash
/usr/local/bin/m8-host-drift < /dev/null
load_final_qualification
binding_check "$W/g2.sealed.json" reboot-anchor -
if PREANCHOR="$("${ROOT_STORE[@]}" publish --store-root "$R" --key "$K" \
  --generation 3 --qualification-evidence-digest "$Q" --service m8-service --wait 0 \
  < /dev/null 2>&1)"; then echo 'pre-anchor publish unexpectedly accepted' >&2; exit 1; else test "$?" -eq 1; fi
printf '%s\n' "$PREANCHOR" | /usr/bin/tail -n 1 | \
  /usr/bin/grep -qxF 'operator_store: native store anchor is unavailable'
"${ROOT_STORE[@]}" maintain --store-root "$R" --key "$K" \
  --service m8-service --wait 0 -- \
  "${LANE[@]}" startup --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/s9-lane" --evidence "$W/s9-qualification.json" < /dev/null
Q3="$(check_evidence qualify "$W/s9-qualification.json" maintenance "$PLAN" "$W/startup-policy.json")"
test "${Q3#sha256:}" != "$Q3" && test "${#Q3}" -eq 71
"${ROOT_STORE[@]}" publish --store-root "$R" --key "$K" --generation 3 \
  --qualification-evidence-digest "$Q3" --service m8-service --wait 0 \
  < /dev/null | save_sealed "$W/g3.sealed.json"
check_sealed "$W/g3.sealed.json" "$Q3"
"${ROOT_STORE[@]}" activate --store-root "$R" --key "$K" --generation 3 \
  --sealed "$W/g3.sealed.json" --qualification-evidence-digest "$Q3" \
  --service m8-service --wait 0 < /dev/null
binding_check "$W/g3.sealed.json" accepted -
binding_check "$W/g2.sealed.json" stale-generation "$W/g3.sealed.json"
"${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g3.sealed.json" --expected "$PLAN" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/s9-active-lane" --evidence "$W/s9-active.json" < /dev/null
check_evidence active "$W/s9-active.json" active "$PLAN" "$W/startup-policy.json" > /dev/null
```

The S9 readback and relay record show whether S1's fixed pins still served
after the reboot. S9 does not re-resolve either name. A stale pin that prevents
the readback is a failed qualification, not a cue to change policy in place.

### S10. Refresh

At least 24 hours after the S3 timestamp, within the same authorization, run
S10's bash script through a new, noninteractive SSH session. The common setup
is loaded again; `PLAN` and `S4_PLAN` are recomputed from the retained checked
S4/S6a records. Require the bare host drift check again before the startup.
Run one active g3 startup. The time check deliberately starts from the timestamp
written after S3's affirmative login, so it cannot overstate elapsed time.
Refresh is measured only if that same run has a clean judged readback,
`accepted:auth.openai.com:443 > 0`, and a changed credential-file mtime. It
does not identify which vendor manager refreshed.

```bash
/usr/local/bin/m8-host-drift < /dev/null
load_final_qualification
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
value = Path(sys.argv[1]).read_text(encoding="ascii").strip()
since = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
if datetime.now(UTC) - since < timedelta(hours=24): raise ValueError("24 hours have not elapsed")
print("refresh-time-met")' "$W/s3-completed-at.utc" < /dev/null | /usr/bin/grep -qxF refresh-time-met
"${SERVICE[@]}" "${LANE[@]}" startup --custody active --store-root "$R" --key "$K" \
  --sealed "$W/g3.sealed.json" --expected "$PLAN" --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/s10-lane" --evidence "$W/s10-refresh.json" < /dev/null
check_evidence refresh "$W/s10-refresh.json" active "$PLAN" "$W/startup-policy.json" > /dev/null
```

If the last checker refuses, retain the completed evidence as *unmeasured*.
Do not infer zero spend or successful refresh from an elapsed day, a mode
flag, or an empty fault list. `vendor_conformance_qualified` remains false
until every control is measured and the owner records a qualified disposition.

## Evidence and limits

Post only the authorization links and bounded records on #77 and in the
living implementation record: S1 pin record, g1/g2/g3 sealed identities,
S3/S4/S6a/S6b/S6c/S8/S9/S10 lane evidence, their checked digests and
verdicts, and the S6a lock/refusal result. Do not post login stdout, stderr
text, a credential, token, code, email or account identifier. The policy
names only the two operator-sealed hosts. The relay cannot distinguish a
model request from a readback on `chatgpt.com`; the four recorded methods and
absence of `thread/start` are the phase evidence. No vendor request or DNS
resolution in this runbook is executed by tests.
