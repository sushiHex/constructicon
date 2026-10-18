# M8 maintenance: q13 preparation composition

Additive successor for [#186](https://github.com/sushiHex/constructicon/issues/186),
bounded by the [post-q12 preparation decision](M8-post-q12-preparation-decision.md).
This is preparation, not live authority. No VM, vendor, model or private host
artifact was used to author it. Frozen sources remain unchanged. One proposed
q13, one proposed start and at most one application attempt do not authorize
execution: exact-head review, measured private prerequisites and the owner's
fresh go remain required. No failure authorizes a diagnostic, retry or q14.

## What changes, and what does not

q12 stopped at C1's drift-output boundary. Its expected sentence was not a
measurement. This successor selects the exact merged
[G1 private-output guard](M8-private-output-guard.md) at every drift call:
nine steps, ten sites, including conditional H8 and both diagnosis calls.
Only G1 may invoke the drift tool. Each guarded step has one private value pair,
one fresh private parent and an absent child per call. Declared public stdout is
`drift-checked`, never the captured sentence.

C, O and BASE stay at the already-retained controller
`5793ef98ef5597c9ee9811a0d1f031554eb7f514`; D stays at the installed D2 source.
This is not a runtime upgrade. The controller inputs (`src/constructicon`,
`scripts/ci/m8_host_artifacts.py`, `uv.lock`) have no source diff between that
controller and preparation baseline `dc61d16`. That source comparison is not
installed-tree evidence: LR8 must freshly report `installed: true`,
`different: 0`, or stop. LR9 replacement is not selected or authorized.

Generation 11 was historically unpublished when q12 stopped. That is not a fresh
store measurement: the unchanged strict floor-10 checks must pass before
publication. q11/q12 workspaces, m3/m4 closures, a3/a4 applications and authorities
3/4 are not reused. q13 uses new session, package, record, capture, m5/a5 and
authority-5 destinations. Existing g10 and q11 references are read-only history.

The task, model, effort, callbacks, epoch, exchange and authorization bounds stay
those of the frozen source. The exact lane L0–L3 fences, record checker and T5
remain selected by source digest; no alternate shell language or transport is
introduced. G1 does not certify sudo silence, Python silence, stock utilities,
qualification, binding, or application completion.

## Q0: no-go criteria

All [q12 Q0 criteria](M8-maintenance-q12-continuation.md#q0-no-go-criteria) remain
requirements, applied to this document's exact merged head and q13 names, with
these stricter preparation conditions. The separate
[q13 readiness and measurement specification](M8-q13-readiness.md) records the
current no-go facts; it is not a host-execution authorization.

1. The private drift stdout expectation has no independent owner approval by file
   digest, or there is no approved independently sourced tool digest to pin. Both remain
   `UNREVIEWED` here. Neither may be learned from the invocation it validates.
   A candidate measurement is not approval.
2. Any of the 19 steps below lacks an explicit evidence classification. A
   fragment, synthetic boundary or source test is not a composed executed step.
   The preparation decision's remaining composed-proof obligations and private
   facts must be settled before a go; this document does not waive them.
3. Any host substitution is unlabeled, or a synthetic accepting boundary lacks a
   different plausible refusing input. Required silence includes whole stderr.
4. The first-package/remaining-session-value build cannot be reproduced without
   invented values. Template or complete synthetic-value test builds are not
   operator packages. The private pair belongs in the first values file; only
   preview, run and boot fields may await C8/boot.
5. Any source, fence, pin, package manifest, review head, CI head or authorization
   disagrees; any blocker, unresolved review or missing fresh custody/idle fact
   remains. A green unit suite alone is not live readiness.
6. Fresh local and remote destinations are occupied, including any G1 capture
   parent/child. Captures are never reused. Private evidence retention must name
   its custodian, retention period, stable reference and integrity digest.

At a refusal: retain private captures/status, stop at that boundary, park by the
reviewed D4 wrapper, release custody only after its checked marker, and report the
step and bounded outcome without raw host bytes. No after-stop probing.

## Q1: workstation sequence

No command here is authorized now. All future shell invocations close stdin.
Use a clean checkout of the exact authorized merged head and a fresh private
execution directory `P`; it may hold only the reviewed bundle, independently
approved private expectation and reviewed values before preparation begins.
Keep values, captures, addresses and key aliases private. No public posting or
push is part of any packaged step.

1. Check exact-head CI/review, the 19-step evidence ledger and private no-go facts.
   Run the unchanged usage preflight once; require `idle-observed` immediately
   before D0 and send the custody start notice.
2. Prepare the reviewed bundle below under its fresh q13 filename. Save a private
   TOML values file with exactly `DRIFT_STDOUT_HEX` and `DRIFT_TOOL_SHA256`,
   each independently reviewed. Build with isolated Python:
   `/c/Python314/python.exe -I -S -B scripts/m8_procedure_package.py build docs/plans/handoffs/M8-maintenance-q13-continuation.md "$P/maintenance-q13-package-1" --values "$P/drift-values.toml" < /dev/null`.
   Require 16 written steps and exactly C9/C10/C11 deferred. Record the manifest
   digest and compare it with the authorization. Failure is no-go, not permission
   to fill runtime fields synthetically or use `--template`.
3. Save the q12 Q6 Python fence verbatim as `$P/m8-q13-transport.py` (the q12
   document digest is pinned below); save Q1b as `$P/q13.sh`, and create the
   fresh private `$P/run` directory mode 0700.
4. Save frozen diagnosis D0/D4 PowerShell fences verbatim, including LF, as
   `maintenance-q13-d0.ps1` and `maintenance-q13-d4.ps1`. Save the two Python
   wrappers below under the matching `.py` names. Run discovery's pinned helper
   check before D0, run D0 once, then the remaining discovery fences once.
   Require `q13-vm-start-checked`; export the discovered target privately.
5. Upload package 1 and the single bundle using Q1b. Run each step in Q8's table
   order once through T5, C1 through C8 only; stop before C9. Stop at the first
   refusal.
6. Review the real C8 record and recorded boot. A second private values file must
   repeat the identical approved private pair and add exactly
   `PREVIEW_SHA256`, `RUN_ID`, `EXPECTED_BOOT`. The run must equal
   `run-4c5df557e3d2f6a0f44030084115f865`, derived from actor/key maintenance-5,
   not selected from output. Build/upload package 2 with those values; record its
   reproducible, different manifest. Resume at C9, never rerun earlier steps.
7. After a normal C10 alternative 0 only, run C10 inspect. Normal alternative 1
   skips inspect. C11 is the single predeclared diagnosis after either normal
   return, not a rescue command after an unknown/refused boundary.
8. Park on every outcome using D4 once; require `q13-vm-park-checked` before
   custody release. Preserve the two wrappers' private captures with all T5/G1
   records. Public reporting follows the park and separate owner authority.

The wrappers differ from q12 only in fresh capture names and public q13 markers:

```python
import hashlib
import json
import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

try:
    source = Path("docs/plans/handoffs/M8-maintenance-diagnosis.md").read_bytes()
    assert b"\r" not in source
    assert hashlib.sha256(source).hexdigest() == "41f76f299999fbd4af5a41da6b1142f11c89cc8a57f60b68f6d1d252811d1e45"
    step = Path("maintenance-q13-d0.ps1")
    raw = step.read_bytes()
    assert b"\r" not in raw
    assert hashlib.sha256(raw).hexdigest() == "a0078c72bcb376a605a3c8e6aa8117a3aa262a92f6ff135758c3d05333f9fc6b"
    with ExitStack() as stack:
        stdout = stack.enter_context(Path("maintenance-q13-d0.stdout").open("x+b"))
        stderr = stack.enter_context(Path("maintenance-q13-d0.stderr").open("x+b"))
        status = stack.enter_context(Path("maintenance-q13-d0.status.json").open("xb"))
        result = subprocess.run([
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(step.resolve()),
        ], stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, check=False)
        status.write(json.dumps({"returncode": result.returncode}, sort_keys=True).encode() + b"\n")
        for output in (stdout, stderr, status):
            output.flush()
            os.fsync(output.fileno())
        assert result.returncode == 0
        assert os.fstat(stdout.fileno()).st_size == 0 and os.fstat(stderr.fileno()).st_size == 0
except Exception:
    sys.stdout.buffer.write(b"q13-vm-start-refused\n")
    raise SystemExit(1) from None
sys.stdout.buffer.write(b"q13-vm-start-checked\n")
```

```python
import hashlib
import json
import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

try:
    source = Path("docs/plans/handoffs/M8-maintenance-diagnosis.md").read_bytes()
    assert b"\r" not in source
    assert hashlib.sha256(source).hexdigest() == "41f76f299999fbd4af5a41da6b1142f11c89cc8a57f60b68f6d1d252811d1e45"
    step = Path("maintenance-q13-d4.ps1")
    raw = step.read_bytes()
    assert b"\r" not in raw
    assert hashlib.sha256(raw).hexdigest() == "2c26ff58c3a9fa3f1ec4995764725e96d818401205c8140a2ca7ecbf5b540381"
    with ExitStack() as stack:
        stdout = stack.enter_context(Path("maintenance-q13-d4.stdout").open("x+b"))
        stderr = stack.enter_context(Path("maintenance-q13-d4.stderr").open("x+b"))
        status = stack.enter_context(Path("maintenance-q13-d4.status.json").open("xb"))
        result = subprocess.run([
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(step.resolve()),
        ], stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, check=False)
        status.write(json.dumps({"returncode": result.returncode}, sort_keys=True).encode() + b"\n")
        for output in (stdout, stderr, status):
            output.flush()
            os.fsync(output.fileno())
        assert result.returncode == 0
        assert os.fstat(stdout.fileno()).st_size == 0 and os.fstat(stderr.fileno()).st_size == 0
except Exception:
    sys.stdout.buffer.write(b"q13-vm-park-refused\n")
    raise SystemExit(1) from None
sys.stdout.buffer.write(b"q13-vm-park-checked\n")
```

## Q1b: exact workstation commands

Same strict-key transport as q12, with fresh q13 names. Export private `P`,
`SSH_TARGET` (only after discovery) and `SSH_HOST_KEY_ALIAS`. Every helper runs
as a new process; there is no carried shell state.

```bash
exec </dev/null
set -Eeuo pipefail
: "${P:?Private execution directory required}"
: "${SSH_HOST_KEY_ALIAS:?Previously recorded host-key alias required}"
PY=(/c/Python314/python.exe -I -S -B)
# LogLevel=ERROR keeps a server banner or client warning off stderr, which T5
# requires empty; real errors still reach stderr, so T5 still refuses them.
OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o "HostKeyAlias=$SSH_HOST_KEY_ALIAS"
  -o ConnectTimeout=15 -o LogLevel=ERROR)
# SSH_TARGET exists only after address discovery; each helper requires it then.
q13_mkdir() {
  : "${SSH_TARGET:?Private discovered target required}"
  ssh -T "${OPTS[@]}" "$SSH_TARGET" \
    "test ! -e \"\$HOME/$1\" && test ! -L \"\$HOME/$1\" && /usr/bin/mkdir -m 0700 -- \"\$HOME/$1\""
}
# A fresh remote directory, then the local package's contents into it.
q13_upload() {
  q13_mkdir "$2"
  scp "${OPTS[@]}" "$1"/* "$SSH_TARGET:$2/"
}
# One packaged step through T5: transport and expectation local, script remote.
q13_step() {
  : "${SSH_TARGET:?Private discovered target required}"
  "${PY[@]}" "$P/m8-q13-transport.py" "$P/run/$1-$2" "$P/$1/$2.expected.json" -- \
    ssh -T "${OPTS[@]}" "$SSH_TARGET" \
    "cd \"\$HOME/$1\" && sha256sum --check --strict --quiet MANIFEST.sha256 && bash $2.sh"
}
# Bundle upload: a fresh remote directory, then the one file into it.
q13_bundle() {
  q13_mkdir maintenance-q13-c7-package
  scp "${OPTS[@]}" "$P/maintenance-q13-5793ef98.bundle" "$SSH_TARGET:maintenance-q13-c7-package/"
}
case "${1-}" in
  q13_mkdir | q13_upload | q13_step | q13_bundle) "$@" ;;
  *) echo 'usage: q13.sh q13_mkdir|q13_upload|q13_step|q13_bundle ARGUMENTS' >&2; exit 2 ;;
esac
```

## Q2: pins

Retained source pins and already prepared bundle bytes are unchanged. Only the
bundle's fresh destination name changes. The q12 source preparation established
its sole maintenance ref, strict fsck, three source hashes and absent vector;
the authorized package must recheck the hash/size. This is source evidence,
not a fresh installed-host observation.

```bash
C=5793ef98ef5597c9ee9811a0d1f031554eb7f514
O=5793ef98ef5597c9ee9811a0d1f031554eb7f514
D=8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3
BASE=5793ef98ef5597c9ee9811a0d1f031554eb7f514
BUNDLE_SHA256=4afec171317d727b95a4f43e2d22c403e917e3994cfca214db8dccfb031d9282
BUNDLE_SIZE=4189475
BUNDLE=/home/m8-service/maintenance-q13-5793ef98.bundle
[[ "$C" =~ ^[0-9a-f]{40}$ && "$O" =~ ^[0-9a-f]{40}$ && "$D" =~ ^[0-9a-f]{40}$ \
   && "$BASE" =~ ^[0-9a-f]{40}$ && "$BUNDLE_SHA256" =~ ^[0-9a-f]{64}$ \
   && "$BUNDLE_SIZE" =~ ^[1-9][0-9]{0,7}$ ]] \
  || { echo 'merged controller and reviewed source pins required; stop' >&2; exit 1; }
test "$C" = "$BASE" && test "$C" = "$O" && test "$BUNDLE_SIZE" -le 67108864 \
  || { echo 'installed controller, reviewed base and bundle bound required; stop' >&2; exit 1; }
```

## Q3: declarations

Current session, read-only historical floor/account, fresh application, then
the final qualification recheck. These are q12's four fences with only reviewed
fresh destination/actor/key substitutions.

```bash
W=/home/m8-service/m8-maint-q13
```

```bash
W_PRIOR=/home/m8-service/m8-maint-q10
GEN=g11
GEN_PRIOR=g10
PRIOR_SEAL="$(/usr/bin/cat -- "$HOME/maintenance-g9-account.seal")"
```

```bash
S=/home/m8-service/m8-m5
APP=/home/m8-service/m8-maint-a5
A=/var/lib/constructicon-m8-maintenance-5/application-5.json
ID="maintenance-5-$C"
ACTOR=operator:maintenance-5
KEY=maintenance-5
ENTRY=("${PY[@]}" constructicon.api.maintenance_entry)
HOST=(--session "$W" --store-key "$K" --sealed "$W/g11.sealed.json"
  --qualification "$W/s6a-qualification.json" --state "$S" --launch-root "$L")
```

```bash
load_final_qualification
binding_check "$W/g11.sealed.json" accepted -
check_sealed "$W/g11.sealed.json" "$Q"
```

## Q4: private host records and transport

Select q12 Q4's record checker and Q6's T5 verbatim by the pinned source digest
below. They keep private variable records out of stdout; status, whole stdout
grammar and empty stderr are all required. They are not weakened to accommodate
a host warning. Installer fences keep their original shell options.

## Q5: new and renamed VM fences

Fence 0 preserves current D2 records before any LR2 overwrite. The archive logic
is q12's Python implementation, not the older `cp --no-clobber` route.

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
print("g11-boot-d2-records-preserved")' \
  "$HOME/m8-host" "$HOME/maintenance-q13-d2-prior" < /dev/null
```

Fences 1 and 2 below are retained for index clarity only; composition selects
the exact q12 physical-preflight and retained-evidence fences instead.

```bash
"${SERVICE[@]}" "${LANE[@]}" preflight --launch-root "$L" < /dev/null | \
  /usr/bin/grep -qF '"launch_ready": true'
echo physical-preflight-checked
```

```bash
W=/home/m8-service/m8-maint-q11
Q11_Q="$(check_evidence initial "$W/s4-qualification.json" maintenance - "$W/startup-policy.json")"
Q11_EXPECTED="$(lane_expectation "$W/s4-qualification.json" checked "$Q11_Q")"
/usr/bin/python3 -I -S -B -c 'import json, sys
x = json.loads(sys.argv[1])
assert type(x) is dict and set(x) == {"evidence_digest", "faults", "refresh"}
assert x["faults"] == [] and x["evidence_digest"] == sys.argv[2]
print("q11-s4-retained-evidence-consistent")' "$Q11_EXPECTED" \
  sha256:7b711f6085b9bbe2fbdd60e68923a6e125717ae067eeb8432aecc58cbe27fbdb < /dev/null
```

Fence 3 is the suffix of the q12 H8 preconditions. Composition selects sudo,
then exact G1, then this suffix inside the unmeasured branch. L2 and L3 retain
their exact reviewed bytes.

```bash
load_final_qualification
: "${SEALED:?Set the reviewed new-generation descriptor path}"
: "${REFRESH_LANE:?Set the reviewed fresh lane path}"
: "${REFRESH_EVIDENCE:?Set the reviewed fresh evidence path}"
binding_check "$SEALED" accepted -
check_sealed "$SEALED" "$Q"
```

Fence 4 transfers the unchanged bundle into fresh q13 names.

```bash
SOURCE_UPLOAD="$HOME/maintenance-q13-c7-package/maintenance-q13-5793ef98.bundle"
test "$SOURCE_UPLOAD" != "$HOME/maintenance-q13-c7-package/UNPREPARED.bundle" \
  || { echo 'reviewed upload literal required; stop' >&2; exit 1; }
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

Fences 5 and 6 split q12 diagnosis at its second raw drift call, changing only
fresh names. Composition inserts a distinct G1 capture between them. The first
G1 runs before fence 5; quiescence must pass before the second G1.

```bash
RUN_ID=UNREVIEWED
EXPECTED_BOOT=UNREVIEWED
[[ "$RUN_ID" =~ ^run-[0-9a-f]{32}$ \
  && "$EXPECTED_BOOT" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]
test "$(/usr/bin/cat /proc/sys/kernel/random/boot_id)" = "$EXPECTED_BOOT"
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api._maintenance_source import read_bounded
from constructicon.core.identity import parse_json_value
from constructicon.substrate.executors.maintenance import read_maintenance_authorization
a = read_maintenance_authorization(Path(sys.argv[3]))
assert str(a.run_id) == sys.argv[4] and a.authorization_id == sys.argv[5]
s = parse_json_value(read_bounded(Path(sys.argv[1]), 256).decode("utf-8", errors="strict"))
assert type(s) is dict and set(s) == {"application", "saver", "diagnostics"}
assert type(s["application"]) is int and s["application"] == 0
assert type(s["saver"]) is int and s["saver"] == 0 and s["diagnostics"] == "clean"
r = parse_json_value(read_bounded(Path(sys.argv[2]), 8192).decode("utf-8", errors="strict"))
assert type(r) is dict and set(r) == {"accepted", "run_id"}
assert type(r["accepted"]) is bool and r["run_id"] == str(a.run_id)
print("normal-application-completion-checked")' \
  "$S/application-status.json" "$S/application-run.json" "$A" "$RUN_ID" "$ID" < /dev/null \
  | /usr/bin/grep -qxF normal-application-completion-checked
set -C
QUIESCENCE_CAPTURE="$HOME/maintenance-q13-package-2/quiescence.private"
QUIESCENCE_STDERR="$HOME/maintenance-q13-package-2/quiescence.stderr"
test ! -e "$QUIESCENCE_CAPTURE"
test ! -L "$QUIESCENCE_CAPTURE"
test ! -e "$QUIESCENCE_STDERR"
test ! -L "$QUIESCENCE_STDERR"
exec {QUIESCENCE_FD}>"$QUIESCENCE_CAPTURE"
exec {QUIESCENCE_ERR_FD}>"$QUIESCENCE_STDERR"
if /usr/bin/pgrep -u m8-service >&"$QUIESCENCE_FD" 2>&"$QUIESCENCE_ERR_FD"
then QUIESCENCE_STATUS=0; else QUIESCENCE_STATUS=$?; fi
exec {QUIESCENCE_FD}>&-
exec {QUIESCENCE_ERR_FD}>&-
test "$QUIESCENCE_STATUS" -eq 1
test -f "$QUIESCENCE_STDERR"
test ! -L "$QUIESCENCE_STDERR"
test ! -s "$QUIESCENCE_STDERR"
printf '%s\n' diagnosis-quiescence-checked
```

```bash
"${SERVICE[@]}" /bin/bash -c 'set -Eeuo pipefail
umask 077
set -C
CAPTURE_ROOT=$1
shift
test ! -e /home/m8-service/m8-maint-diagnosis-5-evidence
test ! -L /home/m8-service/m8-maint-diagnosis-5-evidence
for NAME in diagnostic-report.json diagnostic-status.json diagnostic.stderr diagnostic-saver.stderr; do
    test ! -e "$CAPTURE_ROOT/$NAME"
    test ! -L "$CAPTURE_ROOT/$NAME"
done
exec 3>"$CAPTURE_ROOT/diagnostic-report.json"
exec 4>"$CAPTURE_ROOT/diagnostic-status.json"
exec 5>"$CAPTURE_ROOT/diagnostic.stderr"
exec 6>"$CAPTURE_ROOT/diagnostic-saver.stderr"
if "$@" < /dev/null 2>&5 | /usr/bin/cat >&3 2>&6
then P11_STATUS=("${PIPESTATUS[@]}"); else P11_STATUS=("${PIPESTATUS[@]}"); fi
test "${#P11_STATUS[@]}" -eq 2
FD=3
for NAME in diagnostic-report.json diagnostic-status.json diagnostic.stderr diagnostic-saver.stderr; do
    test -f "/dev/fd/$FD"
    test -f "$CAPTURE_ROOT/$NAME"
    test ! -L "$CAPTURE_ROOT/$NAME"
    test "$CAPTURE_ROOT/$NAME" -ef "/dev/fd/$FD"
    FD=$((FD + 1))
done
DIAG_DIAGNOSTICS=unexpected
if test ! -s /dev/fd/5 && test ! -s /dev/fd/6
then DIAG_DIAGNOSTICS=clean; fi
printf "{\"diagnostic\":%s,\"saver\":%s,\"diagnostics\":\"%s\"}\n" \
    "${P11_STATUS[0]}" "${P11_STATUS[1]}" "$DIAG_DIAGNOSTICS" >&4
exec 3>&- 4>&- 5>&- 6>&-' q13-diagnostic-capture "$S" \
  "${PY[@]}" constructicon.substrate.journal.maintenance_diagnostic \
  --root "$APP" --out /home/m8-service/m8-maint-diagnosis-5-evidence \
  --command-report "$S/application-run.json" --run-id "$RUN_ID" --authorization-id "$ID" < /dev/null
"${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, re, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.api._maintenance_source import read_bounded
from constructicon.core.identity import parse_json_value
from constructicon.core.qualification_write import CallbackObservation
def exact(value, keys):
    assert type(value) is dict and set(value) == set(keys)
def enum(value, choices):
    assert type(value) is str and value in choices
def count(value, bound):
    assert type(value) is int and 0 <= value <= bound
result = {"schema_version": 1, "complete": False, "stage": "output", "error": "diagnostic refused or incomplete"}
try:
    s = parse_json_value(read_bounded(Path(sys.argv[3]), 256).decode("utf-8", errors="strict"))
    exact(s, {"diagnostic", "saver", "diagnostics"})
    assert type(s["diagnostic"]) is int and s["diagnostic"] in (0, 1)
    assert type(s["saver"]) is int and s["saver"] == 0 and s["diagnostics"] == "clean"
    r = parse_json_value(read_bounded(Path(sys.argv[1]), 8192).decode("utf-8", errors="strict"))
    assert type(r) is dict and type(r.get("schema_version")) is int and r["schema_version"] == 1
    assert type(r.get("complete")) is bool
    if r["complete"] is False:
        exact(r, {"schema_version", "complete", "stage", "error"})
        enum(r["stage"], {"capture", "snapshot", "journal", "attempt", "command", "result", "output"})
        assert r["error"] == "diagnostic refused or incomplete" and s["diagnostic"] == 1
    else:
        assert s["diagnostic"] == 0 and re.fullmatch(r"run-[0-9a-f]{32}", sys.argv[2])
        exact(r, {"schema_version", "complete", "meaning", "run_id", "journal", "attempt", "pending_attempt", "command", "result"})
        assert r["meaning"] == "selected-historical-facts-only" and r["run_id"] == sys.argv[2]
        enum(r["pending_attempt"], {"missing", "identity-matched-not-published"})
        enum(r["command"], {"missing", "accepted", "normal-nonacceptance", "command-refused"})
        enum(r["result"], {"missing", "historical-acceptance-observed"})
        j = r["journal"]
        assert type(j) is dict
        if j.get("observation") == "missing":
            exact(j, {"observation"})
        else:
            exact(j, {"observation", "status", "command_origin", "events_checked", "nodes", "checks"})
            assert j["observation"] == "selected-facts-validated"
            enum(j["status"], {"pending", "running", "succeeded", "failed", "cancelled", "parked"})
            enum(j["command_origin"], {"validated", "unrecorded"})
            count(j["events_checked"], 256)
            exact(j["nodes"], {"writer", "checker"})
            for node in j["nodes"].values():
                exact(node, {"started", "checkpoint", "failures"})
                enum(node["started"], {"observed", "unrecorded"})
                enum(node["checkpoint"], {"missing", "validated"})
                assert type(node["failures"]) is list and len(node["failures"]) <= 8
                for failure in node["failures"]:
                    exact(failure, {"type", "cause"})
                    enum(failure["type"], {"ContractViolation", "JournalDamaged", "OSError", "ValueError", "unknown"})
                    enum(failure["cause"], {"writer-workspace", "writer-base", "writer-not-positive", "capture-mismatch", "capture-return", "capture-unchanged", "capture-repository", "capture-paths", "capture-base", "checker-input", "gate-not-positive", "unknown"})
            assert type(j["checks"]) is list and len(j["checks"]) <= 8
            for check in j["checks"]:
                exact(check, {"name", "status"})
                enum(check["name"], {"plan-manifest-trusted-vectors", "snapshot-integrity", "unknown"})
                enum(check["status"], {"passed", "failed", "conflict", "timeout", "cancelled", "infrastructure_error"})
        a = r["attempt"]
        assert type(a) is dict
        if a.get("observation") == "missing":
            exact(a, {"observation"})
        else:
            assert a.get("observation") == "identity-matched"
            enum(a.get("phase"), {"acquired", "intent", "outcome"})
            keys = {"observation", "phase", "dispatch", "callbacks"}
            if a["phase"] == "outcome":
                keys |= {"executor_status", "failure_kind"}
                if "process" in a:
                    keys.add("process")
                    exact(a["process"], {"timed_out", "bound_exceeded"})
                    assert all(type(v) is bool for v in a["process"].values())
                enum(a["dispatch"], {"completed", "not dispatched", "possibly dispatched"})
                assert a["executor_status"] is None or type(a["executor_status"]) is str and a["executor_status"] in {"success", "partial", "failure"}
                enum(a["failure_kind"], {"unknown", "spawn", "timeout", "exit", "unavailable"})
                assert a["dispatch"] != "completed" or a["executor_status"] == "success"
            else:
                assert a["dispatch"] == "unknown"
            exact(a, keys)
            if a["callbacks"] != "unrecorded":
                c = CallbackObservation.model_validate(a["callbacks"])
                assert not (a.get("dispatch") == "completed" or a.get("executor_status") == "success") or c.responses_complete
    out = json.dumps(r, sort_keys=True, separators=(",", ":"))
    assert len(out.encode("utf-8")) + 1 <= 8192
    result = r
except Exception:
    pass
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
raise SystemExit(0 if result["complete"] is True else 1)' \
  "$S/diagnostic-report.json" "$RUN_ID" "$S/diagnostic-status.json" < /dev/null
```

## Q7: private drift declarations

One pair per guarded step, before its first exact G1. These are private unknowns,
not synthetic or measured facts. The values file fills each as readonly.

```bash
DRIFT_STDOUT_HEX=UNREVIEWED
DRIFT_TOOL_SHA256=UNREVIEWED
```

Each guarded step assigns its own fresh `DRIFT_RECORDS` parent, then selects:

```bash
umask 077
/usr/bin/mkdir -m 0700 -- "$DRIFT_RECORDS" || exit "$?"
```

## Q8: all 19 steps and evidence boundaries

This inventory classifies offline evidence, not an assertion that all 19 have run.
“Fragment” means source/component assertions, not the actual packaged producer
through T5. Existing q12 composed rehearsals cover only physical preflight and
H7/H8. The merged real isolated CLI seam is valuable but does not upgrade C3/C4
to fully composed evidence. The new q13 structural tests are also not host facts.
The C7/C8 whole-step join ran at `03804a2` in
[the foundation lane](https://github.com/sushiHex/constructicon/actions/runs/39132967503/job/117691747157).
Its completion artifact records all five scenarios, not just collection or an
empty fault list. Any later code change still needs its own final-head gate.

| Packaged step (table order) | Existing or planned offline proof | Still not established by that proof |
| --- | --- | --- |
| `q13-c1-controller` | Historical controller verifier captured; exact record checker fragment. | Installed controller verifier; sudo and G1 private expectations unmeasured. |
| `q13-c1-history` | Historical-account sequencing fragment. | Retained account seal and capture remain host facts. |
| `q13-c2-preserve` | q13 packaged T5 accepting/refusing proof over disposable prior files; real archive producer. | Actual prior D2 files and fresh destination remain host facts. |
| `q13-c2-d2` | Record-checker grammar and qualification components. | Fresh boot, AppArmor profiles and installed D2 probe. |
| `q13-c2-lr3` | Record-checker grammar and launch components. | OS, policy, identities, filesystem and installed launch checks. |
| `q13-c2-r11` | Record-checker grammar and artifact components. | Network acquisition and vendor artifact custody; no vendor run offline. |
| `q13-c2-kept-launch` | Verifier accepting/refusing fragments. | Actual installed launch, no replacement authorized. |
| `q13-c2-controller` | Controller and import-check fragments. | LR8 must report installed true/different zero; no LR9 install. |
| `q13-c2-preflight` | q12 packaged T5 accepting foundation proof. | Actual current host readiness is still a fresh observation. |
| `q13-c3-retained` | Evidence validators and retained-evidence checker. | Exact retained q11 S4 digest is not manufactured offline. |
| `q13-c3-qualification` | Lane boundary and real isolated CLI qualification seam. | Whole C3, historical continuity and held-lock S6a not joined by that seam. |
| `q13-c4-publish` | Floor checks and real emitted qualification/publication/activation seam. | Whole packaged C3-to-C4 continuity not claimed. |
| `q13-c5-h7` | q13 packaged T5 alternatives/refusals with real lane CLI and exact G1 integration. | Synthetic peer, custody and binding substitutes are not live refresh/account measurements. |
| `q13-c7-prepare` | Executed packaged T5 proof over a genuine bundle and immutable activated store; wrong consumer and diagnostic output refuse. | Synthetic native peer and disposable paths are not the private host's topology or transfer. |
| `q13-c8-preflight` | Executed packaged T5 proof through real assembly and unchanged whitelist/saver checks; source drift and qualification mismatch refuse. | Fresh live preview, run and authorization fields are not approved offline. |
| `q13-c9-authority` | Authorization contracts; deferred until reviewed C8 values. | Root installation and fresh authority custody. |
| `q13-c10-application` | Application entry accepting/refusing component fixtures; deferred. | One real application attempt, never an offline model invocation. |
| `q13-c10-inspect` | Closed inspector grammar; run only after application alternative 0. | Actual accepted candidate inspection. |
| `q13-c11-diagnosis` | Capture/quiescence/closed diagnosis fragments; deferred. | Actual process quiescence and journal observations; two distinct G1 captures. |

Exactly 16 steps precede the application: C1 through C9 inclusive. The first
package writes C1 through C8 plus the later-use C10 inspect (16 files pairs);
C9 authority, C10 application and C11 diagnosis are the three deferred steps.
C10 inspect is built early, but never runs early.

## Composition

```toml
labels = {current = ["g11", "q13"], historical = ["g9", "g10", "q10", "q11"]}

[sources.q12]
path = "M8-maintenance-q12-continuation.md"
sha256 = "1fbd0a983fc9537f47198221b5a84937da6b3e79fe0c15fb77b3e9b2ba4d76b1"

[sources.guard]
path = "M8-private-output-guard.md"
sha256 = "648d5eb2eabc250874a548e5ef036f20657ed61d6149fd96075b60aff41139b7"

[sources.oc]
path = "M8-N4-operator-commands.md"
sha256 = "bd0972ac633be8ac919a1d271e9c6580cf0fdff7c0edafc9a2ce45fd4aa7e7b9"

[sources.hs]
path = "M8-N5-host-session.md"
sha256 = "f11045d5e3b0f0494f9760f5b31d4c083e5fb6477fe11a513a12d12299f76cad"

[sources.lr]
path = "M8-N4-launch-replacement.md"
sha256 = "16cb614cdf76b1d1f9fc983b3eeb8decc9bf00b28e8cf92dd246489e477aada4"

[sources.hr]
path = "M8-N4-host-runtime.md"
sha256 = "349a79981c4b6d0de494fa873a6b52a39850787aa37b56f1797ea1addb86ac9b"

[sources.session]
path = "M8-maintenance-session.md"
sha256 = "66aa57ec86e3dbe1462eeb1a17a832aed6ce2cf72d3385e1fd267d74e0647ee2"

[sources.g11]
path = "M8-maintenance-g11-continuation.md"
sha256 = "f8c4b87400772731433230c7470047d97dbe24915130dd221924329f2eb8e2b5"

[sources.lane]
path = "M8-maintenance-lane-output.md"
sha256 = "a44983423444271ef56a17295edca3309af34e27fb54ff2d968e1b7bbe2ea0e9"

[[steps]]
name = "q13-c1-controller"
stdout = ["drift-checked", "controller-record-checked"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q7: private drift declarations", fences = [0]},
  {literal = 'DRIFT_RECORDS="$HOME/maintenance-q13-drift-c1-controller"'},
  {source = "self", heading = "Q7: private drift declarations", fences = [1]},
  {literal = "sudo -n true < /dev/null"},
  {literal = 'DRIFT_CAPTURE="$DRIFT_RECORDS/before"'},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {literal = 'RECORDS="$HOME/maintenance-q13-records-c1"'},
  {source = "q12", heading = "Q4: private host records", fences = [0]},
  {literal = "{"},
  {source = "session", heading = "P1: already Off, one fresh start and historical continuity", fences = [1]},
  {literal = '} > "$RECORDS/p1.out"'},
  {literal = 'record_check controller "$RECORDS/p1.out" "$C"'},
]

[[steps]]
name = "q13-c1-history"
historical = true
stdout = ["historical-g10-account-capture-revalidated"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {literal = "W=/home/m8-service/m8-maint-q10"},
  {source = "g11", heading = "C1: one fresh boot, historical g10 and the retained capture", fences = [1]},
]

[[steps]]
name = "q13-c2-preserve"
stdout = ["g11-boot-d2-records-preserved"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "self", heading = "Q5: new and renamed VM fences", fences = [0]},
]

[[steps]]
name = "q13-c2-d2"
stdout = ["d2-record-checked", "drift-checked"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {literal = 'RECORDS="$HOME/maintenance-q13-records-d2"'},
  {source = "q12", heading = "Q4: private host records", fences = [0]},
  {literal = "{"},
  {source = "lr", heading = "LR2. Host qualification on this boot", fences = [0], set = {D = "8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3"}},
  {literal = '} > "$RECORDS/lr2.out"'},
  {literal = 'record_check d2 "$RECORDS/lr2.out" "$D"'},
  {source = "self", heading = "Q7: private drift declarations", fences = [0]},
  {literal = 'DRIFT_RECORDS="$HOME/maintenance-q13-drift-c2-d2"'},
  {source = "self", heading = "Q7: private drift declarations", fences = [1]},
  {literal = 'DRIFT_CAPTURE="$DRIFT_RECORDS/after-record"'},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
]

[[steps]]
name = "q13-c2-lr3"
stdout = ["lr3-record-checked"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {literal = 'RECORDS="$HOME/maintenance-q13-records-lr3"'},
  {source = "q12", heading = "Q4: private host records", fences = [0]},
  {literal = "{"},
  {source = "lr", heading = "LR3. Preconditions and provenance", fences = [0], set = {O = "5793ef98ef5597c9ee9811a0d1f031554eb7f514"}},
  {literal = '} > "$RECORDS/lr3.out"'},
  {literal = 'record_check lr3 "$RECORDS/lr3.out"'},
]

[[steps]]
name = "q13-c2-r11"
stdout = ["r11-record-checked"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {literal = 'RECORDS="$HOME/maintenance-q13-records-r11"'},
  {source = "q12", heading = "Q4: private host records", fences = [0]},
  {literal = "{"},
  {source = "lr", heading = "LR3. Preconditions and provenance", fences = [1], set = {C = "5793ef98ef5597c9ee9811a0d1f031554eb7f514"}},
  {literal = '} > "$RECORDS/r11.out"'},
  {literal = 'record_check r11 "$RECORDS/r11.out" "$C"'},
]

[[steps]]
name = "q13-c2-kept-launch"
stdout = ["kept-launch-verified"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {literal = 'W="$HOME/m8-launch"'},
  {source = "g11", heading = "C2: preserve current D2 records and verify the kept launch", fences = [1]},
]

[[steps]]
name = "q13-c2-controller"
stdout = ["lr8-record-checked", "r19-record-checked"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {literal = 'RECORDS="$HOME/maintenance-q13-records-lr8"'},
  {source = "q12", heading = "Q4: private host records", fences = [0]},
  {literal = "{"},
  {source = "lr", heading = "LR8. Controller", fences = [0], set = {O = "5793ef98ef5597c9ee9811a0d1f031554eb7f514", C = "5793ef98ef5597c9ee9811a0d1f031554eb7f514"}},
  {literal = '} > "$RECORDS/lr8.out"'},
  {literal = 'record_check lr8 "$RECORDS/lr8.out" "$C"'},
  {literal = "{"},
  {source = "hr", heading = "R19 — Import check as `m8-service`", fences = [0]},
  {literal = '} > "$RECORDS/r19.out"'},
  {literal = 'record_check r19 "$RECORDS/r19.out"'},
]

[[steps]]
name = "q13-c2-preflight"
stdout = ["physical-preflight-checked"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "q12", heading = "Q5: new and renamed VM fences", fences = [1]},
]

[[steps]]
name = "q13-c3-retained"
historical = true
stdout = ["q11-s4-retained-evidence-consistent"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "lane", heading = "L0: common helpers", fences = [0]},
  {source = "q12", heading = "Q5: new and renamed VM fences", fences = [2]},
]

[[steps]]
name = "q13-c3-qualification"
historical = true
stdout = ["drift-checked", '{"prepared": true, "out": "/home/m8-service/m8-maint-q13"}', "lane-boundary-checked"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 1]},
  {source = "lane", heading = "L0: common helpers", fences = [0]},
  {literal = 'LANES="$HOME/maintenance-q13-lanes-c3"'},
  {source = "self", heading = "Q7: private drift declarations", fences = [0]},
  {literal = 'DRIFT_RECORDS="$HOME/maintenance-q13-drift-c3-qualification"'},
  {source = "self", heading = "Q7: private drift declarations", fences = [1]},
  {literal = "sudo -n true < /dev/null"},
  {literal = 'DRIFT_CAPTURE="$DRIFT_RECORDS/before"'},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "oc", heading = "S1. Prepare", fences = [0]},
  {source = "lane", heading = "L1: qualification boundary", fences = [0]},
  {source = "g11", heading = "C3: fresh q11 and checked historical account continuity", fences = [1]},
  {source = "oc", heading = "S6a. Maintenance-lock positive control", fences = [0]},
]

[[steps]]
name = "q13-c4-publish"
historical = true
stdout = []
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 1]},
  {source = "g11", heading = "C4: checked floor 10, publish and activate g11", fences = [0]},
]

[[steps]]
name = "q13-c5-h7"
historical = true
stdout = [
  ["lane-boundary-checked", "refresh-measured", "lane-boundary-checked", "lane-boundary-checked"],
  ["lane-boundary-checked", "refresh-unmeasured", "lane-boundary-checked", "lane-boundary-checked", "drift-checked", "refresh-measured"],
]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 1]},
  {source = "lane", heading = "L0: common helpers", fences = [0]},
  {literal = 'LANES="$HOME/maintenance-q13-lanes-c5"'},
  {source = "lane", heading = "L2: H7 controls", fences = [0]},
  {literal = 'if test "$ACTIVE_REFRESH" = unmeasured; then'},
  {source = "g11", heading = "C6: at most one conditional H8 request", fences = [0]},
  {literal = 'LANES="$HOME/maintenance-q13-lanes-c6"'},
  {source = "self", heading = "Q7: private drift declarations", fences = [0]},
  {literal = 'DRIFT_RECORDS="$HOME/maintenance-q13-drift-c5-h7"'},
  {source = "self", heading = "Q7: private drift declarations", fences = [1]},
  {literal = "sudo -n true < /dev/null"},
  {literal = 'DRIFT_CAPTURE="$DRIFT_RECORDS/conditional-h8"'},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "self", heading = "Q5: new and renamed VM fences", fences = [3]},
  {source = "lane", heading = "L3: explicit refresh", fences = [0]},
  {literal = "fi"},
]

[[steps]]
name = "q13-c7-prepare"
stdout = ["drift-checked", "maintenance-bundle-transferred", '{"base": "5793ef98ef5597c9ee9811a0d1f031554eb7f514", "bundle_sha256": "4afec171317d727b95a4f43e2d22c403e917e3994cfca214db8dccfb031d9282", "source_prepared": true}']
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 2]},
  {source = "self", heading = "Q7: private drift declarations", fences = [0]},
  {literal = 'DRIFT_RECORDS="$HOME/maintenance-q13-drift-c7-prepare"'},
  {source = "self", heading = "Q7: private drift declarations", fences = [1]},
  {literal = "sudo -n true < /dev/null"},
  {literal = 'DRIFT_CAPTURE="$DRIFT_RECORDS/before"'},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "self", heading = "Q3: declarations", fences = [3]},
  {source = "self", heading = "Q5: new and renamed VM fences", fences = [4]},
  {source = "g11", heading = "C7: fresh closure, source bundle and authority", fences = [2]},
]

[[steps]]
name = "q13-c8-preflight"
stdout = ["drift-checked"]
record = {keys = ["application_revision", "authorization_id", "base", "gate", "grants", "not_after", "operator_binding_digest", "preview_sha256", "revision", "run_id", "source_graph_hash", "workspace"], max_bytes = 8192}
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 2]},
  {source = "self", heading = "Q7: private drift declarations", fences = [0]},
  {literal = 'DRIFT_RECORDS="$HOME/maintenance-q13-drift-c8-preflight"'},
  {source = "self", heading = "Q7: private drift declarations", fences = [1]},
  {literal = "sudo -n true < /dev/null"},
  {literal = 'DRIFT_CAPTURE="$DRIFT_RECORDS/before"'},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "self", heading = "Q3: declarations", fences = [3]},
  {source = "g11", heading = "C8: retain preflight and display its closed failure stage", fences = [0]},
]

[[steps]]
name = "q13-c9-authority"
deferred = true
stdout = ["drift-checked"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 2]},
  {source = "self", heading = "Q7: private drift declarations", fences = [0]},
  {literal = 'DRIFT_RECORDS="$HOME/maintenance-q13-drift-c9-authority"'},
  {source = "self", heading = "Q7: private drift declarations", fences = [1]},
  {literal = "sudo -n true < /dev/null"},
  {literal = 'DRIFT_CAPTURE="$DRIFT_RECORDS/before"'},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "self", heading = "Q3: declarations", fences = [3]},
  {source = "session", heading = "P9: install exact reviewed preview as fresh root authority", fences = [0]},
]

[[steps]]
name = "q13-c10-application"
deferred = true
stdout = [
  ["drift-checked", '{"accepted": true, "command": "normal-completed", "meaning": "application-accepted", "run_id": "run-4c5df557e3d2f6a0f44030084115f865"}'],
  ["drift-checked", '{"accepted": false, "command": "normal-completed", "meaning": "application-not-accepted", "run_id": "run-4c5df557e3d2f6a0f44030084115f865"}'],
]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 2]},
  {source = "self", heading = "Q7: private drift declarations", fences = [0]},
  {literal = 'DRIFT_RECORDS="$HOME/maintenance-q13-drift-c10-application"'},
  {source = "self", heading = "Q7: private drift declarations", fences = [1]},
  {literal = "sudo -n true < /dev/null"},
  {literal = 'DRIFT_CAPTURE="$DRIFT_RECORDS/before"'},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "self", heading = "Q3: declarations", fences = [3]},
  {source = "g11", heading = "C10: one application, independent statuses and closed outcome", fences = [0]},
]

[[steps]]
name = "q13-c10-inspect"
stdout = []
record = {keys = ["candidate_commit", "input_sha256", "meaning", "render_sha256", "run_id", "schema_version"], max_bytes = 1024}
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 2]},
  {source = "session", heading = "P10: one application run, retain verdict and park", fences = [1]},
]

[[steps]]
name = "q13-c11-diagnosis"
deferred = true
stdout = ["drift-checked", "diagnosis-quiescence-checked", "drift-checked"]
record = {keys = ["attempt", "command", "complete", "journal", "meaning", "pending_attempt", "result", "run_id", "schema_version"], max_bytes = 8192}
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 2]},
  {source = "self", heading = "Q7: private drift declarations", fences = [0]},
  {literal = 'DRIFT_RECORDS="$HOME/maintenance-q13-drift-c11-diagnosis"'},
  {source = "self", heading = "Q7: private drift declarations", fences = [1]},
  {literal = "sudo -n true < /dev/null"},
  {literal = 'DRIFT_CAPTURE="$DRIFT_RECORDS/before"'},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "self", heading = "Q5: new and renamed VM fences", fences = [5]},
  {literal = 'DRIFT_CAPTURE="$DRIFT_RECORDS/after-quiescence"'},
  {source = "guard", heading = "G1: private drift boundary", fences = [0]},
  {source = "self", heading = "Q5: new and renamed VM fences", fences = [6]},
]
```

## Evidence and limits

`tests/test_m8_maintenance_q13_continuation.py` checks the one production
composition, exact immutable source selections, ten G1 sites, private declaration
placement, fresh destinations, output contracts, deferrals and Bash syntax.
Its disposable-file preservation test drives the actual packaged archive through
the unchanged T5, including refusal. It does not turn any private unknown into
an approved value. Passing a synthetic complete-values build proves only that
the composition can compile without changing G1 or lane scope.

The H7 test also drives the actual packaged step through T5: measured refresh
skips G1/H8 while all controls still run; unmeasured refresh runs exact G1 then
one H8. A different plausible synthetic drift sentence refuses before H8, an
accepted denial control stops before G1, and a normal unmeasured H8 is rejected
by T5 despite command status zero. Its custody/binding substitutions are those
of the existing q12 fixture, not proof of the real qualification/store join.
Native Windows substitutes only its unavailable file flags and interpreter/LF
plumbing; POSIX retains native flags. No new platform-based skip hides a case.

G1's documented limits remain: trusted filesystem custody between digest read
and execution; no capture timeout/disk bound; EOF is not process-tree termination.
No snapshot, installed digest, drift sentence, actual qualification, actual store
generation, host readiness or completed application is inferred here. Missing
coverage or measurement is a no-go fact, not an invitation to widen this wave.

