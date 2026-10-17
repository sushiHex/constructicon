# M8 maintenance: q12 and one fresh application attempt

Prepared additive successor for [#186](https://github.com/sushiHex/constructicon/issues/186). Preparation is not execution authority: review, CI, merge, the rehearsal and the owner's go on this document's exact merged commit remain required. Frozen documents keep their bytes. This one composes them through `scripts/m8_procedure_package.py` from pinned fences, and adds only what is new.

## What g11 established, and what changes

The g11 session ([outcome](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6201449870)) ended as follows:
- It booted once.
- It verified the historical controller and g10 continuity.
- It preserved the then-current D2 records and verified the kept launch.
- Its LR8 refused with an exact installed-tree difference. The authorized LR9 and HR R17/R18 then installed controller C=`5793ef98ef5597c9ee9811a0d1f031554eb7f514`, verified `installed: true`, `different: 0`.
- R19 and the physical preflight passed, and q11 `prepare` succeeded.
- It stopped at its first S4 boundary, because g11 required empty stderr where the lane always prints its summary ([#210](https://github.com/sushiHex/constructicon/issues/210)).

No generation was published, so the store's highest descriptor is still 10 (`operator_store.py:1313`). The g11 authorization is spent. q11, a3, m3 and authority 3 are never reused as destinations.

This procedure changes only the following:

| Change | Why |
| --- | --- |
| **The installed controller is C.** O equals C. No controller replacement is authorized: LR8 must report `installed: true`, `different: 0`, or the session stops. | g11 R18 installed C. A difference now would be unexplained drift, not a pending install. |
| **Fresh names:** session q12, closure m4, application a4, authority 4, packages `maintenance-q12-*`, D2 archive `maintenance-q12-d2-prior`. Generation 11 is published, with g10 as the stale prior. | The g11 names are occupied or spent. Generation 11 was never published. |
| **The [#210 lane-output contract](M8-maintenance-lane-output.md)** governs S4 (L1), every H7 control (L2) and explicit refresh (L3). | The g11 stop. |
| **A read-only check of the retained q11 S4 evidence** comes before q12 qualifies. | It settles whether g11's S4 published clean evidence, which was left unknown. |
| **Every VM step runs through the transport T5 below.** Each step has exactly declared stdout, empty stderr and exit zero. Variable host records go to private files and are checked by a typed record checker. | g11's diagnostics rule was prose. Here it is mechanical. |
| **The #209 usage preflight** must print `idle-observed` before the start. | #209. |
| **C5 and C6 are one step.** H8 runs only when every H7 control passed and active refresh was unmeasured. | A reviewed branch is one of two exact outputs, never an operator judgment. |

The model, effort, callbacks, epoch, task, exam, every bound, the 300-second exchange, the one-hour authorization and the single attempt are unchanged. There is no retry, at any step.

## Q0: no-go criteria

The owner approved these criteria on 2026-10-16. Any one of them refuses the go, or stops the session before D0. Each is checked against the evidence named.

1. **Rehearsal not on the exact commit.** The `m8-containment` workflow, dispatched on this document's merged commit (it runs only on pull requests and dispatch), did not pass, or its foundation lane did not run `tests/test_m8_maintenance_q12_rehearsal.py` with every test passing. Evidence: the run URL, its head SHA and that step's log.
2. **Rehearsal coverage short.** A packaged VM step has neither passed T5 in the rehearsal nor been named, with its reason, in `tests/test_m8_maintenance_q12_rehearsal.py`'s unrehearsable list. Or the #210 boundary blocks did not each run on an accepting and a refusing path in `tests/test_m8_lane_output.py`. Evidence: the CI logs of both files on the merged commit.
3. **Review incomplete.** Any of the following, with the diff, the review list and the thread list as evidence:
   - The merged tree differs from the reviewed head.
   - The connector review of the final head has a finding that is neither fixed nor declined with a recorded reason the owner's authorization explicitly accepts.
   - A review thread is unresolved.
4. **Pins disagree.** Any of the following:
   - The authorization, the Q2 guard and the rebuilt package manifest name different C, O, D, BASE, bundle SHA-256 or size.
   - Rebuilding the first package from the merged commit does not reproduce its manifest hash.

   Evidence: the three-way comparison.
5. **VM or custody not idle.** Either of the following:
   - `scripts/m8_vm_usage.py` does not print `idle-observed` immediately before D0.
   - A hardline custody claim is unreleased.

   Evidence: the preflight output and the hardline history. The owner is reachable for the authorized hour.
6. **Fresh paths occupied.** At the session's start, before Q1b's first command, the bundle prepared below is not the only file under the private execution directory. Every VM destination is also checked absent by its own step.
7. **No stop plan.** Q8's stop report is not prepared. Evidence: this document.
8. **Public exposure.** A step pushes or posts publicly, or reaches a destination beyond the reviewed policy's two. Publication happens only after the park, under #186's rules. Evidence: the assembled package; a grep shows no push, PR or comment command.
9. **Acceptance mismatch.** The fixed task's source hashes at C differ from the three `SOURCE_HASHES`. An accepted application leads to an ordinary contribution PR, which is the "accepted contribution" #186 defines. Evidence: the bundle preparation below.
10. **Open blocker.** An open issue states that it blocks a live #186 attempt. Evidence: the issue list.

## Q1: workstation sequence

Everything runs from the checked repository root at the authorized commit, with Git Bash or isolated Python. Every invocation closes stdin. Private outputs stay in the private execution directory and are never published.

1. **Preflight.** Run `/c/Python314/python.exe -I -S -B scripts/m8_vm_usage.py` once. Require exit zero and `idle-observed`, then send the custody start notice over hardline.
2. **Build the first package.** Build it with `/c/Python314/python.exe -I -S -B scripts/m8_procedure_package.py build docs/plans/handoffs/M8-maintenance-q12-continuation.md maintenance-q12-package-1`. Record the printed manifest hash. The CLI names the deferred steps C9–C11.
3. **Start.** Copy the frozen diagnosis D0 PowerShell fence verbatim, including its final LF, to `maintenance-q12-d0.ps1`. Save the Q1 start fence below as `maintenance-q12-d0.py` and run it once with `/c/Python314/python.exe -I -S -B maintenance-q12-d0.py`. Require exactly `q12-vm-start-checked`.
4. **Discover the address.** Run the discovery continuation's three fences once, as in g11 C1, keeping the address private.
5. **Upload.** Upload the package directory and the prepared bundle through the maintenance session P0's file-upload transport, under fresh absent names: `maintenance-q12-package-1`, and `maintenance-q12-c7-package/maintenance-q12-5793ef98.bundle`.
6. **Run each VM step once, in table order,** through T5:

   ```
   /c/Python314/python.exe -I -S -B m8-q12-transport.py STEP STEP.expected.json -- ssh ... \
     'cd PACKAGE && sha256sum --check --strict --quiet MANIFEST.sha256 && bash STEP.sh'
   ```

   `PACKAGE` is the uploaded package the step was built in, `STEP` is a fresh absent local prefix, and `ssh ...` is the reviewed strict-key transport. Stop at the first refusal.
7. **Build the second package after C8.** Review C8's record. Write the values file below, then build `maintenance-q12-package-2` with `--values`. Upload it and run C9 onward from it. C11 also keeps its quiescence capture there.
8. **Park on every outcome.** Save the Q1 park fence as `maintenance-q12-d4.py`, with D4 verbatim as `maintenance-q12-d4.ps1`. Run it once and require `q12-vm-park-checked`. Release custody only after that marker.

Start fence (`maintenance-q12-d0.py`):

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
    step = Path("maintenance-q12-d0.ps1")
    raw = step.read_bytes()
    assert b"\r" not in raw
    assert hashlib.sha256(raw).hexdigest() == "a0078c72bcb376a605a3c8e6aa8117a3aa262a92f6ff135758c3d05333f9fc6b"
    with ExitStack() as stack:
        stdout = stack.enter_context(Path("maintenance-q12-d0.stdout").open("x+b"))
        stderr = stack.enter_context(Path("maintenance-q12-d0.stderr").open("x+b"))
        status = stack.enter_context(Path("maintenance-q12-d0.status.json").open("xb"))
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
    sys.stdout.buffer.write(b"q12-vm-start-refused\n")
    raise SystemExit(1) from None
sys.stdout.buffer.write(b"q12-vm-start-checked\n")
```

Park fence (`maintenance-q12-d4.py`):

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
    step = Path("maintenance-q12-d4.ps1")
    raw = step.read_bytes()
    assert b"\r" not in raw
    assert hashlib.sha256(raw).hexdigest() == "2c26ff58c3a9fa3f1ec4995764725e96d818401205c8140a2ca7ecbf5b540381"
    with ExitStack() as stack:
        stdout = stack.enter_context(Path("maintenance-q12-d4.stdout").open("x+b"))
        stderr = stack.enter_context(Path("maintenance-q12-d4.stderr").open("x+b"))
        status = stack.enter_context(Path("maintenance-q12-d4.status.json").open("xb"))
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
    sys.stdout.buffer.write(b"q12-vm-park-refused\n")
    raise SystemExit(1) from None
sys.stdout.buffer.write(b"q12-vm-park-checked\n")
```

The values file for the second build holds exactly the following:
- `PREVIEW_SHA256`: the reviewed C8 `preview_sha256`;
- `RUN_ID`: C8's `run_id`, which must equal `run-5c7172babff67a7d53412b6c598bc34b`, derived from the actor and key;
- `EXPECTED_BOOT`: this session's measured boot UUID.

## Q1b: exact workstation commands

These run in Git Bash on the workstation, from a dedicated clean checkout of the authorized commit (detached), which is the repository root for every relative path. Three values are exported privately and never published:
- `P`: the private execution directory. At the session's start it holds only the prepared bundle (Q0 criterion 6). It then receives the dispatcher, the packages, the transport program, T5's per-step captures (`$P/run/<package>-<step>`) and the values file.
- `SSH_TARGET`: the target, exported only once address discovery has run.
- `SSH_HOST_KEY_ALIAS`: the recorded alias.

D0 and D4 write their own capture files into the checkout root. They stay there, untracked, until they are moved into `P` after the park.

Save this fence as `$P/q12.sh`. Each command is one fresh, non-interactive process, `bash "$P/q12.sh" <helper> <arguments>`, so no shell state carries between commands:

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
q12_mkdir() {
  : "${SSH_TARGET:?Private discovered target required}"
  ssh -T "${OPTS[@]}" "$SSH_TARGET" \
    "test ! -e \"\$HOME/$1\" && test ! -L \"\$HOME/$1\" && /usr/bin/mkdir -m 0700 -- \"\$HOME/$1\""
}
# A fresh remote directory, then the local package's contents into it.
q12_upload() {
  q12_mkdir "$2"
  scp "${OPTS[@]}" "$1"/* "$SSH_TARGET:$2/"
}
# One packaged step through T5: transport and expectation local, script remote.
q12_step() {
  : "${SSH_TARGET:?Private discovered target required}"
  "${PY[@]}" "$P/m8-q12-transport.py" "$P/run/$1-$2" "$P/$1/$2.expected.json" -- \
    ssh -T "${OPTS[@]}" "$SSH_TARGET" \
    "cd \"\$HOME/$1\" && sha256sum --check --strict --quiet MANIFEST.sha256 && bash $2.sh"
}
# Bundle upload: a fresh remote directory, then the one file into it.
q12_bundle() {
  q12_mkdir maintenance-q12-c7-package
  scp "${OPTS[@]}" "$P/maintenance-q12-5793ef98.bundle" "$SSH_TARGET:maintenance-q12-c7-package/"
}
case "${1-}" in
  q12_mkdir | q12_upload | q12_step | q12_bundle) "$@" ;;
  *) echo 'usage: q12.sh q12_mkdir|q12_upload|q12_step|q12_bundle ARGUMENTS' >&2; exit 2 ;;
esac
```

The sequence, once each, stopping and parking at the first refusal. `PY` below means `/c/Python314/python.exe -I -S -B`:
1. **Preflight:** run `PY scripts/m8_vm_usage.py`. It must print `idle-observed`. Then send the custody start notice.
2. **Build and prepare locally:**
   - `PY scripts/m8_procedure_package.py build docs/plans/handoffs/M8-maintenance-q12-continuation.md "$P/maintenance-q12-package-1"`. Record its manifest hash, which must equal the authorization's.
   - Save the fence above as `$P/q12.sh`, and the Q6 fence as `$P/m8-q12-transport.py`.
   - Create `$P/run` with `mkdir -m 0700`.
3. **Start and discover:** from the checkout root:
   - run the discovery continuation's first fence, the helper's pinned hash check, before D0;
   - run D0 (Q1 step 3);
   - run the discovery continuation's second and third fences;
   - export `SSH_TARGET` privately from the discovered address.
4. **Upload:**
   - `bash "$P/q12.sh" q12_upload "$P/maintenance-q12-package-1" maintenance-q12-package-1`.
   - `bash "$P/q12.sh" q12_bundle`.
5. **Run the first package:** `bash "$P/q12.sh" q12_step maintenance-q12-package-1 <step>` for each step in Q7's order, from `q12-c1-controller` to `q12-c8-preflight`, and nothing after it.
6. **Write the values file:** `$P/values.toml` is TOML, exactly `PREVIEW_SHA256 = "..."`, `RUN_ID = "..."` and `EXPECTED_BOOT = "..."`, taken from the reviewed C8 record and the recorded boot UUID.
7. **Build and upload the second package:** build `"$P/maintenance-q12-package-2"` with `--values "$P/values.toml"`, then upload it with `bash "$P/q12.sh" q12_upload "$P/maintenance-q12-package-2" maintenance-q12-package-2`. Because `RUN_ID` is filled, the second package rebuilds every step. Its manifest differs, and that is expected.
8. **Run the rest from the second package:** with `bash "$P/q12.sh" q12_step maintenance-q12-package-2 <step>`, resume at `q12-c9-authority`, then `q12-c10-application`, `q12-c10-inspect` (only after alternative 0) and `q12-c11-diagnosis`. Never rerun an earlier step.
9. **Park:** run D4 (Q1 step 8) on every outcome.

## Q2: pins

Every VM step starts with this guard. LR fences receive the same commits through their documented declarations (`set`):

```bash
C=5793ef98ef5597c9ee9811a0d1f031554eb7f514
O=5793ef98ef5597c9ee9811a0d1f031554eb7f514
D=8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3
BASE=5793ef98ef5597c9ee9811a0d1f031554eb7f514
BUNDLE_SHA256=4afec171317d727b95a4f43e2d22c403e917e3994cfca214db8dccfb031d9282
BUNDLE_SIZE=4189475
BUNDLE=/home/m8-service/maintenance-q12-5793ef98.bundle
[[ "$C" =~ ^[0-9a-f]{40}$ && "$O" =~ ^[0-9a-f]{40}$ && "$D" =~ ^[0-9a-f]{40}$ \
   && "$BASE" =~ ^[0-9a-f]{40}$ && "$BUNDLE_SHA256" =~ ^[0-9a-f]{64}$ \
   && "$BUNDLE_SIZE" =~ ^[1-9][0-9]{0,7}$ ]] \
  || { echo 'merged controller and reviewed source pins required; stop' >&2; exit 1; }
test "$C" = "$BASE" && test "$C" = "$O" && test "$BUNDLE_SIZE" -le 67108864 \
  || { echo 'installed controller, reviewed base and bundle bound required; stop' >&2; exit 1; }
```

Bundle preparation evidence, measured at C on 2026-10-17 UTC:
- **The bundle:** a fresh bundle with the sole ref `refs/heads/maintenance` at C, imported by stock Git into an empty repository, with `fsck --full --strict`, holding 164 commits.
- **Source hashes:** all three `SOURCE_HASHES`, read from C's own source, match C.
- **Vector path:** the vector path is absent at C.
- **Measured values:** the SHA-256 and size above.

The bundle is private and kept under the private execution directory until it is uploaded. This is local source evidence, not host evidence.

## Q3: declarations

The current session:

```bash
W=/home/m8-service/m8-maint-q12
```

The superseded generation and the checked historical account, used by the C3, C4 and C5 steps:

```bash
W_PRIOR=/home/m8-service/m8-maint-q10
GEN=g11
GEN_PRIOR=g10
PRIOR_SEAL="$(/usr/bin/cat -- "$HOME/maintenance-g9-account.seal")"
```

The application, with fresh names:

```bash
S=/home/m8-service/m8-m4
APP=/home/m8-service/m8-maint-a4
A=/var/lib/constructicon-m8-maintenance-4/application-4.json
ID="maintenance-4-$C"
ACTOR=operator:maintenance-4
KEY=maintenance-4
ENTRY=("${PY[@]}" constructicon.api.maintenance_entry)
HOST=(--session "$W" --store-key "$K" --sealed "$W/g11.sealed.json"
  --qualification "$W/s6a-qualification.json" --state "$S" --launch-root "$L")
```

The published generation, rechecked before each application step:

```bash
load_final_qualification
binding_check "$W/g11.sealed.json" accepted -
check_sealed "$W/g11.sealed.json" "$Q"
```

## Q4: private host records

Installer fences print variable host records: verifier JSON, listings, versions and boot ids. Each step that runs one first declares a fresh absent `RECORDS` directory. It then sets the mask and creates that directory outside any redirect, so the redirect can neither truncate nor expose an existing file. The fence runs in a brace group whose stdout goes to one record file, and `record_check` then checks that record's whole grammar. The installers keep their own shell settings: no errexit is added, and `record_check` exits the step on any refusal.

```bash
umask 077
test -n "$RECORDS" && /usr/bin/mkdir -m 0700 -- "$RECORDS" || exit 1
record_check() {
  test "$#" -ge 2 || exit 1
  /usr/bin/python3 -I -S -B -c 'import json, os, stat, sys
from pathlib import Path
def unique(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result
        result[key] = value
    return result
def read(path):
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
    assert info.st_mode & 0o077 == 0 and 0 < info.st_size <= 1048576
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        assert (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino)
        raw = stream.read(1048577)
    assert len(raw) == info.st_size and raw.endswith(b"\n")
    return raw.decode("utf-8", errors="strict")
class Record:
    def __init__(self, text):
        self.text, self.at = text, 0
    def line(self, expected=None):
        end = self.text.index("\n", self.at)
        value, self.at = self.text[self.at:end], end + 1
        assert expected is None or value == expected
        return value
    def through(self, last):
        while self.line() != last:
            pass
    def json(self):
        value, end = json.JSONDecoder(object_pairs_hook=unique).raw_decode(self.text, self.at)
        assert type(value) is dict and self.text[end] == "\n"
        self.at = end + 1
        return value
    def end(self):
        assert self.at == len(self.text)
def proven(r, command, commit):
    assert r.get("command") == command and r.get("commit") == commit
    assert r.get("first_parent") is True and r.get("script_matches_commit") is True
def controller(r, commit):
    proven(r, "verify-controller", commit)
    assert r.get("schema_version") == 2 and r.get("installed") is True
    tree = r.get("observed")
    assert type(tree) is dict and set(tree) == {"/opt/constructicon-m8-controller"}
    entry = tree["/opt/constructicon-m8-controller"]
    assert type(entry) is dict and entry.get("uid") == 0 and entry.get("state") == "tree"
    assert type(entry.get("different")) is int and entry["different"] == 0
    assert entry.get("differences") == []
try:
    kind, record = sys.argv[1], Record(read(Path(sys.argv[2])))
    if kind == "controller":
        controller(record.json(), sys.argv[3])
    elif kind == "d2":
        record.line(Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").rstrip("\n"))
        record.line("verify exit 0")
        verify = record.json()
        proven(verify, "verify", sys.argv[3])
        assert verify.get("installed") is True
        record.line("probe exit 0")
        probe = record.json()
        assert probe.get("qualified") is True and probe.get("commit") == sys.argv[3]
        assert probe.get("scope") == "runner_prerequisites_only"
        assert probe.get("production_available") is False
    elif kind == "lr3":
        record.line("/usr/bin/bwrap: OK")
        record.through("LR3 passed")
    elif kind == "r11":
        record.through("R11 complete")
        vendor = record.json()
        proven(vendor, "vendor-inputs", sys.argv[3])
        assert vendor.get("listed") is True and vendor.get("schema_version") == 2
    elif kind == "lr8":
        record.through("LR8 fetched")
        record.line("verify exit 0")
        controller(record.json(), sys.argv[3])
    elif kind == "r19":
        record.line("check exit 0")
        check = record.json()
        assert set(check) == {"files", "outside", "passed"}
        assert type(check["files"]) is int and check["files"] > 0
        assert check["outside"] == [] and check["passed"] is True
    else:
        raise AssertionError(kind)
    record.end()
except Exception:
    print("record-refused")
    raise SystemExit(1) from None
print(kind + "-record-checked")' "$@" < /dev/null || exit 1
}
```

The checker requires each record's completion line and its exact status line before reading any JSON:
- `LR3 passed`, `R11 complete` and `LR8 fetched` end their `&&` chains.
- `verify exit 0`, `probe exit 0` and `check exit 0` precede the JSON they introduce.

Duplicate keys are refused at any depth. It checks the properties the frozen prose requires, not each record's full key set. Those records are built incrementally and stay private, and a missing optional key must not become a false stop.

## Q5: new and renamed VM fences

The D2 records of the g11 boot, preserved before LR2 overwrites them:

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
  "$HOME/m8-host" "$HOME/maintenance-q12-d2-prior" < /dev/null
```

The physical preflight. These are OC S3's first two lines, verbatim, and the following login lines are excluded:

```bash
"${SERVICE[@]}" "${LANE[@]}" preflight --launch-root "$L" < /dev/null | \
  /usr/bin/grep -qF '"launch_ready": true'
echo physical-preflight-checked
```

The retained q11 S4 evidence, read only. Its checked digest and faults must equal the summary g11 retained (`faults: []`). A failure stops: it would mean g11's S4 published something other than what its summary said.

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

ER R1's preconditions, verbatim (L3 replaces its lane line):

```bash
sudo -n true < /dev/null
/usr/local/bin/m8-host-drift < /dev/null
load_final_qualification
: "${SEALED:?Set the reviewed new-generation descriptor path}"
: "${REFRESH_LANE:?Set the reviewed fresh lane path}"
: "${REFRESH_EVIDENCE:?Set the reviewed fresh evidence path}"
binding_check "$SEALED" accepted -
check_sealed "$SEALED" "$Q"
```

The bundle transfer, with fresh names:

```bash
SOURCE_UPLOAD="$HOME/maintenance-q12-c7-package/maintenance-q12-5793ef98.bundle"
test "$SOURCE_UPLOAD" != "$HOME/maintenance-q12-c7-package/UNPREPARED.bundle" \
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

The diagnosis, with fresh names. It runs only after a normal C10 return:

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
QUIESCENCE_CAPTURE="$HOME/maintenance-q12-package-2/quiescence.private"
QUIESCENCE_STDERR="$HOME/maintenance-q12-package-2/quiescence.stderr"
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
/usr/local/bin/m8-host-drift < /dev/null
"${SERVICE[@]}" /bin/bash -c 'set -Eeuo pipefail
umask 077
set -C
CAPTURE_ROOT=$1
shift
test ! -e /home/m8-service/m8-maint-diagnosis-4-evidence
test ! -L /home/m8-service/m8-maint-diagnosis-4-evidence
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
exec 3>&- 4>&- 5>&- 6>&-' q12-diagnostic-capture "$S" \
  "${PY[@]}" constructicon.substrate.journal.maintenance_diagnostic \
  --root "$APP" --out /home/m8-service/m8-maint-diagnosis-4-evidence \
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

## Q6: transport T5

Save this fence as `m8-q12-transport.py` and include it in the hash inventory. It extends L4 (`M8-maintenance-lane-output.md`), whose bytes are unchanged. A step's expectation is the packager's `<step>.expected.json`: one or more distinct exact alternatives, and optionally one closed record line.
- **Accepts only when:** exit is zero, stderr is empty, and stdout equals exactly one alternative's LF-terminated lines, followed by the record line when one is declared.
- **The record line:** one ASCII JSON object with exactly the declared keys and no duplicates, within its byte bound.
- **Output:** it prints which alternative matched.

```python
import json
import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path


def unique(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result
        result[key] = value
    return result


try:
    step, expected = sys.argv[1], Path(sys.argv[2])
    assert sys.argv[3] == "--" and len(sys.argv) > 4
    declared = expected.read_bytes()
    assert b"\r" not in declared and len(declared) <= 65536
    spec = json.loads(declared.decode("utf-8", errors="strict"), object_pairs_hook=unique)
    assert type(spec) is dict and set(spec) == {"alternatives", "record"}
    alternatives, record = spec["alternatives"], spec["record"]
    assert type(alternatives) is list and alternatives
    rendered = []
    for lines in alternatives:
        assert type(lines) is list
        assert all(type(line) is str and "\n" not in line and "\r" not in line for line in lines)
        rendered.append("".join(line + "\n" for line in lines).encode("utf-8"))
    assert len(set(rendered)) == len(rendered)
    if record is not None:
        assert type(record) is dict and set(record) == {"keys", "max_bytes"}
        keys, bound = record["keys"], record["max_bytes"]
        assert type(keys) is list and keys and all(type(key) is str for key in keys)
        assert len(set(keys)) == len(keys) and type(bound) is int and 2 <= bound <= 8192
    with ExitStack() as stack:
        stdout = stack.enter_context(Path(step + ".stdout").open("x+b"))
        stderr = stack.enter_context(Path(step + ".stderr").open("x+b"))
        status = stack.enter_context(Path(step + ".status.json").open("xb"))
        result = subprocess.run(sys.argv[4:], stdin=subprocess.DEVNULL,
                                stdout=stdout, stderr=stderr, check=False)
        status.write(json.dumps({"returncode": result.returncode}, sort_keys=True).encode() + b"\n")
        for output in (stdout, stderr, status):
            output.flush()
            os.fsync(output.fileno())
        assert result.returncode == 0
        assert os.fstat(stderr.fileno()).st_size == 0
        size = os.fstat(stdout.fileno()).st_size
        assert size <= 65536 + 8192
        stdout.seek(0)
        raw = stdout.read(size + 1)
        assert len(raw) == size
    matched = []
    for index, prefix in enumerate(rendered):
        if record is None:
            if raw == prefix:
                matched.append(index)
            continue
        rest = raw[len(prefix):]
        if not raw.startswith(prefix) or rest.count(b"\n") != 1 or not rest.endswith(b"\n"):
            continue
        try:
            assert rest.isascii() and len(rest) <= bound
            line = json.loads(rest.decode("ascii"), object_pairs_hook=unique)
            assert type(line) is dict and set(line) == set(keys)
        except (AssertionError, ValueError):
            continue
        matched.append(index)
    assert len(matched) == 1
except Exception:
    sys.stdout.buffer.write(b"transport-step-refused\n")
    raise SystemExit(1) from None
sys.stdout.buffer.write(b"transport-step-checked %d\n" % matched[0])
```

T5 checks framing, not meaning. A record's values are the producing step's typed checker's job, and for C8 the reviewer's. Like L4, T5 retains the ssh returncode, stdout and stderr locally whatever the outcome. A refusal does not identify the failing remote command.

## Q7: steps

| Step | Exact stdout (T5) | Notes |
| --- | --- | --- |
| `q12-c1-controller` | `NO DRIFT`, `controller-record-checked` | P1's verifier at C, privately recorded |
| `q12-c1-history` | `historical-g10-account-capture-revalidated` | OC's reboot-anchor refusal first |
| `q12-c2-preserve` | `g11-boot-d2-records-preserved` | before LR2 |
| `q12-c2-d2` | `d2-record-checked`, `NO DRIFT` | LR2 at D, then the bare drift check |
| `q12-c2-lr3` | `lr3-record-checked` | archives the g11 launch workspace |
| `q12-c2-r11` | `r11-record-checked` | fresh provenance at C |
| `q12-c2-kept-launch` | `kept-launch-verified` | installed true, replacement false |
| `q12-c2-controller` | `lr8-record-checked`, `r19-record-checked` | LR8 at C and R19; any refusal stops |
| `q12-c2-preflight` | `physical-preflight-checked` | |
| `q12-c3-retained` | `q11-s4-retained-evidence-consistent` | read only |
| `q12-c3-qualification` | `NO DRIFT`, the S1 record, `lane-boundary-checked` | H2, S1, L1, the account comparison, S6a |
| `q12-c4-publish` | (none) | floor 10, then publish and activate generation 11 |
| `q12-c5-h7` | alternative 0 or 1 | L2; then, only if unmeasured, H8 through L3 |
| `q12-c7-prepare` | `NO DRIFT`, `maintenance-bundle-transferred`, the source pin | |
| `q12-c8-preflight` | `NO DRIFT` and a 12-key pin record | human review before the second build |
| `q12-c9-authority` | `NO DRIFT` | deferred; P9 with the approved preview |
| `q12-c10-application` | `NO DRIFT` and accepted true (0) or false (1) | deferred; the one attempt |
| `q12-c10-inspect` | a 6-key result record | only after alternative 0 |
| `q12-c11-diagnosis` | `NO DRIFT`, `diagnosis-quiescence-checked`, `NO DRIFT`, a 9-key report | deferred; after either normal return |

C5's alternative 1 runs H8, so its stdout ends with H8's drift line and verdict. Only `refresh-measured` is declared there. An unmeasured or faulty H8 stops, as ER R2 requires. C10's refused and unknown outcomes exit 1, which is a T5 refusal: stop and park, with no inspection or diagnosis. A normal non-acceptance (alternative 1) skips the inspection, and C11 may follow.

## Q8: the next stop, planned

No step after g11's first S4 has run live on this controller, so the next stop is most likely at or after C3. Where each step could stop, and what that would mean:
- **C1:** a refusal other than the reboot anchor would be unexplained state. C2's LR8 and R19 repeat checks g11 passed, so a refusal there would be drift since g11.
- **`q12-c3-retained`:** this decides the question g11 left open. A pass means g11's S4 published clean evidence matching its summary. A failure stops before any new qualification.
- **C3's L1:** the first contract-checked qualification. A clean pass is expected from g11's `faults: []`. A refusal retains the capture, and its stderr is the lane's own summary.
- **C5:** L2 and L3 have run only against the real CLI with a scripted peer (#210's tests), never live.
- **C8 to C10:** g10 passed preflight and returned a validated non-acceptance with a grouped capture mismatch, whose cause is unknown. #199 to #204 changed the capture path since then. A normal non-acceptance is therefore a possible outcome, not a defect of this procedure. It is diagnosed once in C11 and not retried.
- **C10's stderr:** the #210 audit left it UNKNOWN. Its only writers are asyncio's reports of a run-host or recovery-pump failure (`run_host.py:584-599`, `667-680`). Both run after a failure has already happened, and C10's capture then records `unexpected`. A successful run has no stderr writer.
- **The transport:** an ssh loss or a blocked custody wait leaves the remote outcome unknown. T5 grants no retry, recovery or cancellation. The operator parks only after a fresh observation, and reports the uncertainty.
- **C4 must not be interrupted.** An abrupt interruption during publication can leave a `.pending-*` descriptor (`operator_store.py:672`). The store then refuses binding, maintenance and publication until a separately authorized recovery (`tests/substrate/test_operator_store_maintenance.py:392`). Parking or rebooting does not repair it. Let C4 finish, or record the interruption as unrecoverable for this session.

The stop report posted to #186 contains only the following:
- the step reached;
- T5's line;
- whether the stopping command's own status was retained;
- the D4 marker;
- that nothing was retried.

Private captures, records, seals and addresses stay private. No cause is inferred from an exit or a missing file.

## Composition

```toml
labels = {current = ["g11", "q12"], historical = ["g9", "g10", "q10", "q11"]}

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
name = "q12-c1-controller"
stdout = ["NO DRIFT", "controller-record-checked"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "hs", heading = "H2. S0 at `C`", fences = [0]},
  {literal = 'RECORDS="$HOME/maintenance-q12-records-c1"'},
  {source = "self", heading = "Q4: private host records", fences = [0]},
  {literal = "{"},
  {source = "session", heading = "P1: already Off, one fresh start and historical continuity", fences = [1]},
  {literal = '} > "$RECORDS/p1.out"'},
  {literal = 'record_check controller "$RECORDS/p1.out" "$C"'},
]

[[steps]]
name = "q12-c1-history"
historical = true
stdout = ["historical-g10-account-capture-revalidated"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {literal = "W=/home/m8-service/m8-maint-q10"},
  {source = "g11", heading = "C1: one fresh boot, historical g10 and the retained capture", fences = [1]},
]

[[steps]]
name = "q12-c2-preserve"
stdout = ["g11-boot-d2-records-preserved"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "self", heading = "Q5: new and renamed VM fences", fences = [0]},
]

[[steps]]
name = "q12-c2-d2"
stdout = ["d2-record-checked", "NO DRIFT"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {literal = 'RECORDS="$HOME/maintenance-q12-records-d2"'},
  {source = "self", heading = "Q4: private host records", fences = [0]},
  {literal = "{"},
  {source = "lr", heading = "LR2. Host qualification on this boot", fences = [0], set = {D = "8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3"}},
  {literal = '} > "$RECORDS/lr2.out"'},
  {literal = 'record_check d2 "$RECORDS/lr2.out" "$D"'},
  {literal = "/usr/local/bin/m8-host-drift < /dev/null"},
]

[[steps]]
name = "q12-c2-lr3"
stdout = ["lr3-record-checked"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {literal = 'RECORDS="$HOME/maintenance-q12-records-lr3"'},
  {source = "self", heading = "Q4: private host records", fences = [0]},
  {literal = "{"},
  {source = "lr", heading = "LR3. Preconditions and provenance", fences = [0], set = {O = "5793ef98ef5597c9ee9811a0d1f031554eb7f514"}},
  {literal = '} > "$RECORDS/lr3.out"'},
  {literal = 'record_check lr3 "$RECORDS/lr3.out"'},
]

[[steps]]
name = "q12-c2-r11"
stdout = ["r11-record-checked"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {literal = 'RECORDS="$HOME/maintenance-q12-records-r11"'},
  {source = "self", heading = "Q4: private host records", fences = [0]},
  {literal = "{"},
  {source = "lr", heading = "LR3. Preconditions and provenance", fences = [1], set = {C = "5793ef98ef5597c9ee9811a0d1f031554eb7f514"}},
  {literal = '} > "$RECORDS/r11.out"'},
  {literal = 'record_check r11 "$RECORDS/r11.out" "$C"'},
]

[[steps]]
name = "q12-c2-kept-launch"
stdout = ["kept-launch-verified"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {literal = 'W="$HOME/m8-launch"'},
  {source = "g11", heading = "C2: preserve current D2 records and verify the kept launch", fences = [1]},
]

[[steps]]
name = "q12-c2-controller"
stdout = ["lr8-record-checked", "r19-record-checked"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {literal = 'RECORDS="$HOME/maintenance-q12-records-lr8"'},
  {source = "self", heading = "Q4: private host records", fences = [0]},
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
name = "q12-c2-preflight"
stdout = ["physical-preflight-checked"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q5: new and renamed VM fences", fences = [1]},
]

[[steps]]
name = "q12-c3-retained"
historical = true
stdout = ["q11-s4-retained-evidence-consistent"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "lane", heading = "L0: common helpers", fences = [0]},
  {source = "self", heading = "Q5: new and renamed VM fences", fences = [2]},
]

[[steps]]
name = "q12-c3-qualification"
historical = true
stdout = ["NO DRIFT", '{"prepared": true, "out": "/home/m8-service/m8-maint-q12"}', "lane-boundary-checked"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 1]},
  {source = "lane", heading = "L0: common helpers", fences = [0]},
  {literal = 'LANES="$HOME/maintenance-q12-lanes-c3"'},
  {source = "hs", heading = "H2. S0 at `C`", fences = [0]},
  {source = "oc", heading = "S1. Prepare", fences = [0]},
  {source = "lane", heading = "L1: qualification boundary", fences = [0]},
  {source = "g11", heading = "C3: fresh q11 and checked historical account continuity", fences = [1]},
  {source = "oc", heading = "S6a. Maintenance-lock positive control", fences = [0]},
]

[[steps]]
name = "q12-c4-publish"
historical = true
stdout = []
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 1]},
  {source = "g11", heading = "C4: checked floor 10, publish and activate g11", fences = [0]},
]

[[steps]]
name = "q12-c5-h7"
historical = true
stdout = [
  ["lane-boundary-checked", "refresh-measured", "lane-boundary-checked", "lane-boundary-checked"],
  ["lane-boundary-checked", "refresh-unmeasured", "lane-boundary-checked", "lane-boundary-checked", "NO DRIFT", "refresh-measured"],
]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 1]},
  {source = "lane", heading = "L0: common helpers", fences = [0]},
  {literal = 'LANES="$HOME/maintenance-q12-lanes-c5"'},
  {source = "lane", heading = "L2: H7 controls", fences = [0]},
  {literal = 'if test "$ACTIVE_REFRESH" = unmeasured; then'},
  {source = "g11", heading = "C6: at most one conditional H8 request", fences = [0]},
  {literal = 'LANES="$HOME/maintenance-q12-lanes-c6"'},
  {source = "self", heading = "Q5: new and renamed VM fences", fences = [3]},
  {source = "lane", heading = "L3: explicit refresh", fences = [0]},
  {literal = "fi"},
]

[[steps]]
name = "q12-c7-prepare"
stdout = ["NO DRIFT", "maintenance-bundle-transferred", '{"base": "5793ef98ef5597c9ee9811a0d1f031554eb7f514", "bundle_sha256": "4afec171317d727b95a4f43e2d22c403e917e3994cfca214db8dccfb031d9282", "source_prepared": true}']
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 2]},
  {source = "hs", heading = "H2. S0 at `C`", fences = [0]},
  {source = "self", heading = "Q3: declarations", fences = [3]},
  {source = "self", heading = "Q5: new and renamed VM fences", fences = [4]},
  {source = "g11", heading = "C7: fresh closure, source bundle and authority", fences = [2]},
]

[[steps]]
name = "q12-c8-preflight"
stdout = ["NO DRIFT"]
record = {keys = ["application_revision", "authorization_id", "base", "gate", "grants", "not_after", "operator_binding_digest", "preview_sha256", "revision", "run_id", "source_graph_hash", "workspace"], max_bytes = 8192}
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 2]},
  {source = "hs", heading = "H2. S0 at `C`", fences = [0]},
  {source = "self", heading = "Q3: declarations", fences = [3]},
  {source = "g11", heading = "C8: retain preflight and display its closed failure stage", fences = [0]},
]

[[steps]]
name = "q12-c9-authority"
deferred = true
stdout = ["NO DRIFT"]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 2]},
  {source = "hs", heading = "H2. S0 at `C`", fences = [0]},
  {source = "self", heading = "Q3: declarations", fences = [3]},
  {source = "session", heading = "P9: install exact reviewed preview as fresh root authority", fences = [0]},
]

[[steps]]
name = "q12-c10-application"
deferred = true
stdout = [
  ["NO DRIFT", '{"accepted": true, "command": "normal-completed", "meaning": "application-accepted", "run_id": "run-5c7172babff67a7d53412b6c598bc34b"}'],
  ["NO DRIFT", '{"accepted": false, "command": "normal-completed", "meaning": "application-not-accepted", "run_id": "run-5c7172babff67a7d53412b6c598bc34b"}'],
]
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 2]},
  {source = "hs", heading = "H2. S0 at `C`", fences = [0]},
  {source = "self", heading = "Q3: declarations", fences = [3]},
  {source = "g11", heading = "C10: one application, independent statuses and closed outcome", fences = [0]},
]

[[steps]]
name = "q12-c10-inspect"
stdout = []
record = {keys = ["candidate_commit", "input_sha256", "meaning", "render_sha256", "run_id", "schema_version"], max_bytes = 1024}
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 2]},
  {source = "session", heading = "P10: one application run, retain verdict and park", fences = [1]},
]

[[steps]]
name = "q12-c11-diagnosis"
deferred = true
stdout = ["NO DRIFT", "diagnosis-quiescence-checked", "NO DRIFT"]
record = {keys = ["attempt", "command", "complete", "journal", "meaning", "pending_attempt", "result", "run_id", "schema_version"], max_bytes = 8192}
parts = [
  {source = "self", heading = "Q2: pins", fences = [0]},
  {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
  {source = "self", heading = "Q3: declarations", fences = [0, 2]},
  {source = "hs", heading = "H2. S0 at `C`", fences = [0]},
  {source = "self", heading = "Q5: new and renamed VM fences", fences = [5]},
]
```

## Evidence and limits

- **Mechanical composition:** every VM step is built by the packager from the pinned sources above. Its lints refuse unreviewed lane invocations, undeclared or historical labels, unfilled placeholders and documented declarations. Its tests and mutation inventory cover them. Tests also build this composition and check every built step with `bash -n`.
- **The rehearsal:** this is the go's evidence, gated by Q0. It runs only two built steps through T5:
  - `q12-c5-h7`, with real bash and the real lane CLI over a scripted peer: both alternatives and two refusals;
  - `q12-c2-preflight`, on the foundation lane with real tools.

  Every other step is named, with its reason, in the rehearsal's unrehearsable list. Their frozen fences are tested where they were reviewed. T5's framing and every built expectation are tested against T5 itself.
- **What this is not:** none of this is host, vendor, qualification or application evidence. The installed `m8-host-drift` output (`NO DRIFT`) and host `sudo` diagnostics remain host facts, observed clean through g11's C2.
- **Limits recorded rather than solved:**
  - Content hashes do not freeze shell context. A literal before a reviewed fence could redefine what it calls, and review covers the few literals here.
  - T5 checks framing, not meaning.
  - A normal non-acceptance remains possible. g10's capture-mismatch cause is still unknown.
