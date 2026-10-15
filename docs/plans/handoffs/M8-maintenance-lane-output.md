# M8 maintenance: lane output contract

Additive correction for [#210](https://github.com/sushiHex/constructicon/issues/210), under [#186](https://github.com/sushiHex/constructicon/issues/186). This document is not execution authority. It authorizes no VM start, resume, login, qualification, refresh, application or retry. The stopped g11 session's authorization is spent, and its occupied q11 paths are never reused. A later live continuation is a separate reviewed procedure, chosen from measured preserved state and authorized on its own. When it composes a lane boundary named below, it uses that boundary's block here instead of the corresponding frozen command.

The frozen [g11 continuation](M8-maintenance-g11-continuation.md), [OC](M8-N4-operator-commands.md), [ER](M8-N5-explicit-refresh.md), [session](M8-maintenance-session.md) and every other accepted plan keep their bytes. The installed lane CLI is not changed to satisfy a procedure check.

## The defect

At controller C=5793ef98ef5597c9ee9811a0d1f031554eb7f514, `codex_lane.main` publishes its evidence and then always writes one JSON summary line to stderr (`codex_lane.py:860-865`). The line is `{"evidence_digest": ..., "faults": [...]}`. The CLI returns zero exactly when `faults` is empty, so a clean run writes the summary too. With `--request-refresh` and no faults, it also writes one `refresh-measured` or `refresh-unmeasured` line to stdout.

The g11 procedure requires "empty stderr at every boundary" (g11 line 40). That rule rejects every clean qualification, so the live session stopped at the first S4 lane. Only the outer transport exit was retained. That exit does not establish S4's own exit or a qualification result, and nothing here infers one from `faults:[]`.

A blanket empty-stderr rule is wrong for these lane boundaries. Dropping the stderr check would be wrong too: unexpected diagnostics must still stop. The contract below accepts exactly the CLI's documented summary. It binds that summary to independently checked published evidence and to the declared exit/fault contract, and refuses any other byte.

## Boundary inventory

Every g11 boundary was reviewed for the class: a normal or expected-refusal path that writes stderr, or stdout beyond the declared markers. Rows marked CONFLICT need the blocks below. CLEAN rows keep the empty-stderr rule. UNKNOWN rows keep it too, and an unexpected byte there still stops and parks.

This is a source audit at C, not a host measurement.

| g11 boundary | Normal or expected-refusal output | Verdict |
| --- | --- | --- |
| C3 OC S4 lane under `maintain` (OC lines 378-382) | Summary on stderr, exit 0; `maintain` passes descriptors 0-2 to the lane (`operator_store.py:1454-1461`) and returns its exit | CONFLICT, L1 |
| C5 active startup (g11 lines 308-311) | Summary on stderr, exit 0 | CONFLICT, L2 |
| C5 S6b `--expect-denial` (g11 lines 341-345) | Summary with its faults on stderr, exit 1 | CONFLICT, L2 |
| C5 S6c wrong plan (g11 lines 347-351) | Summary with its faults on stderr, exit 1 | CONFLICT, L2 |
| C6 ER R1 `--request-refresh` (ER lines 134-138) | Summary on stderr and the verdict on stdout, exit 0; with faults, summary only, exit 1 | CONFLICT, L3 |
| OC S6a held lane and second maintain | Lane stdout/stderr to `/dev/null`; the refusal traceback goes into `$SECOND` by `2>&1` | CLEAN, frozen |
| OC S1 `prepare`, the frozen helpers, C4 `publish`/`activate`, C5 checks and policy writer | Declared stdout only; `operator_store` writes `operator_store: ...` to stderr only on refusal (`operator_store.py:1635-1636`) | CLEAN |
| C7 transfer, `git init --bare -q`, `maintenance_entry prepare` | No stderr; Git's default-branch advice is suppressed under `-q`; entry children capture their stderr | CLEAN |
| C8 `maintenance_entry preflight` and checker | Preview or closed refusal on stdout only (`maintenance_entry.py:389-401`) | CLEAN |
| C10 `maintenance_entry run` capture | No explicit stderr writer. `RunHost._report_failure` can log through asyncio's default handler only after a walker drive already failed. C10's capture then records `unexpected`, a non-normal outcome | UNKNOWN; empty-stderr rule kept |
| C11 `pgrep`, installed diagnostic and validator | Stderr preopened and checked empty, or none; the diagnostic writes stdout only (`maintenance_diagnostic.py:363-381`) | CLEAN |
| `m8-host-drift`, `sudo`, the host's Python 3.12 warnings | Not in the repository | UNKNOWN; observed clean live through C2 |

Parenthesized source lines are the audit's citations at C. No other boundary normally writes the lane summary.

## Contract

A named lane boundary passes only when all of the following hold:

- **Capture:** an operator-side capture records the command's stdout, stderr and returncode in three separate exclusively created files. The capture itself completes affirmatively. Capture success is a fact about recording, never about the command.
- **Checked evidence:** the published evidence passes the frozen `check_evidence` for the boundary's mode. Explicit-refresh evidence has no frozen checker; it gets only the consistency check described in L3.
- **Digest:** a service-side recomputation of the evidence digest equals the digest `check_evidence` printed.
- **stderr:** the captured stderr bytes equal exactly the ASCII line `json.dumps({"evidence_digest": D, "faults": F}) + "\n"`, where D and F come from that checked evidence. Anything else fails: one extra byte or line, an empty stderr, a reordered or different fault, another digest, a warning or a traceback.
- **Exit:** the recorded returncode is 1 when F is non-empty and 0 when F is empty. A clean boundary requires F empty; a declared refusal requires F non-empty. The frozen checker independently requires the exact refusal fault set.
- **stdout:** stdout is empty, except at the explicit-refresh boundary. There it is exactly `refresh-<R>` plus LF, with R the evidence's own `refresh` value.

Failure stops and parks. Captures, evidence and partial files are retained and never reused or repaired. Statuses are not inferred from absent files.

Every other boundary keeps its existing rule, including the frozen held-startup S6a. S6a sends its lane's stdout and stderr to `/dev/null` by design, checks the lane exit through `wait` under errexit, and checks evidence with `check_evidence hold`. Its summary therefore never reaches the outer transport, and S6a stays verbatim. Its second-maintain control checks only the last line of the refusal output, and that pre-existing limit is unchanged. It is not exact-output validation.

No outer timeout is added. The lane's startup deadline starts only after custody is held, so an active-custody lock wait has no bounded duration. An observer timeout or an interruption leaves the command outcome unknown. It never grants a retry.

## L0: common helpers

Append this block to the reviewed new common, after OC's two Setup blocks and the step declarations. `lane_capture` runs as the operator, outside `operator_store maintain`, so the root helper → service lane parent relationship and its inherited lock are unchanged. `lane_expectation` runs as the service and reads the installed controller. `lane_boundary` runs as the operator and reads only the capture.

```bash
lane_capture() {
  test "$#" -ge 2
  /usr/bin/python3 -I -S -B -c 'import json, os, stat, subprocess, sys
from pathlib import Path
try:
    out = Path(sys.argv[1])
    command = sys.argv[2:]
    assert command and out.is_absolute() and out.name not in ("", ".", "..")
    parent = out.parent
    info = parent.lstat()
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and info.st_mode & 0o077 == 0
    assert parent.resolve(strict=True) == parent
    os.mkdir(out, 0o700)
    made = out.lstat()
    assert stat.S_ISDIR(made.st_mode) and made.st_uid == os.getuid() and made.st_mode & 0o077 == 0
    names = ("stdout", "stderr", "status.json")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    fds = [os.open(out / name, flags, 0o600) for name in names]
    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=fds[0], stderr=fds[1], check=False)
    os.fsync(fds[0])
    os.fsync(fds[1])
    after = out.lstat()
    assert (after.st_dev, after.st_ino) == (made.st_dev, made.st_ino) and stat.S_ISDIR(after.st_mode)
    for name, fd in zip(names, fds, strict=True):
        path, opened = (out / name).lstat(), os.fstat(fd)
        assert stat.S_ISREG(path.st_mode) and stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1
        assert (path.st_dev, path.st_ino) == (opened.st_dev, opened.st_ino)
    raw = (json.dumps({"returncode": result.returncode}, sort_keys=True) + "\n").encode("ascii")
    assert os.write(fds[2], raw) == len(raw)
    os.fsync(fds[2])
    for fd in fds:
        os.close(fd)
    directory = os.open(out, os.O_RDONLY | os.O_DIRECTORY)
    os.fsync(directory)
    os.close(directory)
except Exception:
    sys.stderr.write("lane-capture-refused\n")
    raise SystemExit(1) from None' "$@" < /dev/null
}
lane_expectation() {
  test "$#" -eq 3
  "${SERVICE[@]}" /usr/bin/python3 -I -S -B -c 'import json, os, re, stat, sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.core.identity import canonical_json, digest
from constructicon.substrate.executors.codex_lane import EVIDENCE_DOMAIN, EXPLICIT_REFRESH_FIELDS, EXPLICIT_REFRESH_SCHEMA
def unique(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result
        result[key] = value
    return result
path, mode, checked = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
info = path.lstat()
assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
assert info.st_mode & 0o077 == 0 and 0 < info.st_size <= 1048576
fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
with os.fdopen(fd, "rb") as stream:
    opened = os.fstat(stream.fileno())
    assert (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino)
    raw = stream.read(1048577)
assert len(raw) == info.st_size
e = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique)
assert type(e) is dict and e.get("completed") is True
faults, refresh = e.get("faults"), e.get("refresh")
assert type(faults) is list and all(type(fault) is str for fault in faults)
assert type(refresh) is str and refresh in ("measured", "unmeasured")
d = str(digest(EVIDENCE_DOMAIN, 1, json.loads(canonical_json(e))))
if mode == "checked":
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", checked) and d == checked
else:
    assert mode == "explicit" and checked == "-" and set(e) == EXPLICIT_REFRESH_FIELDS | {"completed"}
    assert type(e["schema_version"]) is int and e["schema_version"] == EXPLICIT_REFRESH_SCHEMA
    assert e["request_refresh"] is True
print(json.dumps({"evidence_digest": d, "faults": faults, "refresh": refresh}, sort_keys=True))' "$@" < /dev/null
}
lane_boundary() {
  test "$#" -eq 3
  /usr/bin/python3 -I -S -B -c 'import json, os, re, stat, sys
from pathlib import Path
def unique(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result
        result[key] = value
    return result
def read(path, bound):
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
    assert info.st_mode & 0o077 == 0 and info.st_size <= bound
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        assert (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino)
        raw = stream.read(bound + 1)
    assert len(raw) == info.st_size
    return raw
try:
    out, kind = Path(sys.argv[1]), sys.argv[2]
    x = json.loads(sys.argv[3], object_pairs_hook=unique)
    assert type(x) is dict and set(x) == {"evidence_digest", "faults", "refresh"}
    d, f, r = x["evidence_digest"], x["faults"], x["refresh"]
    assert type(d) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", d)
    assert type(f) is list and all(type(fault) is str for fault in f)
    assert type(r) is str and r in ("measured", "unmeasured")
    assert {path.name for path in out.iterdir()} == {"stdout", "stderr", "status.json"}
    status = json.loads(read(out / "status.json", 64).decode("ascii"), object_pairs_hook=unique)
    assert type(status) is dict and set(status) == {"returncode"} and type(status["returncode"]) is int
    stderr, stdout = read(out / "stderr", 8192), read(out / "stdout", 64)
    assert stderr == (json.dumps({"evidence_digest": d, "faults": f}) + "\n").encode("ascii")
    assert status["returncode"] == (1 if f else 0)
    if kind == "clean":
        assert f == [] and stdout == b""
        print("lane-boundary-checked")
    elif kind == "refusal":
        assert f != [] and stdout == b""
        print("lane-boundary-checked")
    else:
        assert kind == "refresh" and f == [] and stdout == ("refresh-" + r + "\n").encode("ascii")
        print("refresh-" + r)
except Exception:
    print("lane-boundary-refused")
    raise SystemExit(1) from None' "$@" < /dev/null
}
```

Each step that captures a lane declares one fresh absent operator directory `LANES` beside its package. It creates `LANES` with `/usr/bin/mkdir -m 0700` before the first capture. Capture names are unique within the step. An occupied `LANES` or capture path stops before dispatch. Assign every expectation to a variable before passing it on, so that `errexit` stops on a failed check. `lane_boundary` prints exactly one line per boundary. That line is part of the step's declared stdout.

## L1: qualification boundary

This replaces only OC S4's two lane lines and the following `read_seal`. Any S4 comparison declared by the continuation follows in the same shell. Frozen OC S6a then runs verbatim.

```bash
/usr/bin/mkdir -m 0700 -- "$LANES"
lane_capture "$LANES/s4" "${ROOT_STORE[@]}" maintain --store-root "$R" --key "$K" \
  --service m8-service --wait 0 -- \
  "${LANE[@]}" startup --launch-root "$L" \
  --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/s4-lane" --evidence "$W/s4-qualification.json"
S4_Q="$(check_evidence initial "$W/s4-qualification.json" maintenance - "$W/startup-policy.json")"
S4_EXPECTED="$(lane_expectation "$W/s4-qualification.json" checked "$S4_Q")"
lane_boundary "$LANES/s4" clean "$S4_EXPECTED"
S4_SEAL="$(read_seal "$W/s4-qualification.json")"
```

The declared stdout is exactly `lane-boundary-checked` plus LF. `maintain` returns its lane's exit and adds no output on success. Its own refusal (`operator_store: ...`) lands in the capture and fails the stderr equality.

## L2: H7 controls

This replaces g11 C5's three lane invocations and their checks. Every other line of g11 C5 is copied verbatim in its place, and the active-refresh selection keeps its exact `refresh-measured` or `refresh-unmeasured` line. The first two blocks replace the active startup and its `ACTIVE_Q` line:

```bash
/usr/bin/mkdir -m 0700 -- "$LANES"
lane_capture "$LANES/h7-active" "${SERVICE[@]}" "${LANE[@]}" startup --custody active \
  --store-root "$R" --key "$K" --sealed "$W/$GEN.sealed.json" --expected "$SEAL" \
  --launch-root "$L" --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-$GEN-lane" --evidence "$W/h7-$GEN-active.json"
ACTIVE_Q="$(check_evidence active "$W/h7-$GEN-active.json" active "$SEAL" "$W/startup-policy.json")"
ACTIVE_EXPECTED="$(lane_expectation "$W/h7-$GEN-active.json" checked "$ACTIVE_Q")"
lane_boundary "$LANES/h7-active" clean "$ACTIVE_EXPECTED"
```

Then the two refusal controls replace the `if ... --expect-denial` and wrong-plan blocks and their `check_evidence ... > /dev/null` lines:

```bash
lane_capture "$LANES/h7-s6b" "${SERVICE[@]}" "${LANE[@]}" startup --custody active \
  --store-root "$R" --key "$K" --sealed "$W/$GEN.sealed.json" --expected "$SEAL" \
  --launch-root "$L" --configuration "$W/config.toml" \
  --policy "$W/h7-$GEN-no-chatgpt-policy.json" --lane-dir "$W/h7-$GEN-s6b-lane" \
  --evidence "$W/h7-$GEN-s6b-denial.json" --expect-denial
DENIAL_Q="$(check_evidence denial "$W/h7-$GEN-s6b-denial.json" active "$SEAL" "$W/h7-$GEN-no-chatgpt-policy.json")"
DENIAL_EXPECTED="$(lane_expectation "$W/h7-$GEN-s6b-denial.json" checked "$DENIAL_Q")"
lane_boundary "$LANES/h7-s6b" refusal "$DENIAL_EXPECTED"
lane_capture "$LANES/h7-s6c" "${SERVICE[@]}" "${LANE[@]}" startup --custody active \
  --store-root "$R" --key "$K" --sealed "$W/$GEN.sealed.json" --expected "plus/${SEAL#*/}" \
  --launch-root "$L" --configuration "$W/config.toml" --policy "$W/startup-policy.json" \
  --lane-dir "$W/h7-$GEN-s6c-lane" --evidence "$W/h7-$GEN-s6c-plan-refusal.json"
WRONGPLAN_Q="$(check_evidence wrongplan "$W/h7-$GEN-s6c-plan-refusal.json" active "$SEAL" "$W/startup-policy.json")"
WRONGPLAN_EXPECTED="$(lane_expectation "$W/h7-$GEN-s6c-plan-refusal.json" checked "$WRONGPLAN_Q")"
lane_boundary "$LANES/h7-s6c" refusal "$WRONGPLAN_EXPECTED"
```

`GEN` is the continuation's reviewed literal generation label, for example `g12`. The declared stdout is three `lane-boundary-checked` lines with the active-refresh verdict line in its g11 position. The frozen checker still requires S6b's exact denial facts and four faults, and S6c's exact wrong-plan refusal. A declared refusal that exits 0, prints no summary or carries other faults stops. Every control still runs when active refresh was measured.

## L3: explicit refresh

Under ER R0's unchanged custody, drift and continuity checks, this replaces ER R1's lane line:

```bash
/usr/bin/mkdir -m 0700 -- "$LANES"
lane_capture "$LANES/h8-explicit" "${SERVICE[@]}" "${LANE[@]}" startup --request-refresh \
  --custody active --store-root "$R" --key "$K" --sealed "$SEALED" \
  --expected "$SEAL" --launch-root "$L" --configuration "$W/config.toml" \
  --policy "$W/startup-policy.json" --lane-dir "$REFRESH_LANE" \
  --evidence "$REFRESH_EVIDENCE"
REFRESH_EXPECTED="$(lane_expectation "$REFRESH_EVIDENCE" explicit -)"
lane_boundary "$LANES/h8-explicit" refresh "$REFRESH_EXPECTED"
```

The declared stdout is exactly one verdict line, `refresh-measured` or `refresh-unmeasured`. It is re-emitted only after the captured CLI verdict and summary equal the published record's own values. ER R2 keeps its meaning: the verdict is the lane's own post-publication predicate. Faults, a missing verdict or any other byte stops.

This is a consistency binding, not a semantic schema-5 checker. It establishes a complete, closed-field schema-5 record whose recomputed digest and faults are what the CLI printed, and whose `refresh` value is the printed verdict. It does not re-derive the measured predicate. A semantic schema-5 checker is new verification authority outside #210; adding one needs its own review.

## L4: workstation step transport

Save this exact fence as `m8-step-transport.py` in the continuation's reviewed local package and include it in the hash inventory. Run it once per uploaded step, from the package directory, as `/c/Python314/python.exe -I -S -B m8-step-transport.py STEP EXPECTED -- ssh ...`. The ssh argv is the continuation's reviewed strict-key transport. Its remote command checks the package with `sha256sum --check --strict --quiet` before `bash` runs the step. `STEP` is a fresh absent local prefix. `EXPECTED` is the reviewed file holding the step's exact declared stdout.

```python
import json
import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

try:
    step, expected = sys.argv[1], Path(sys.argv[2])
    assert sys.argv[3] == "--" and len(sys.argv) > 4
    declared = expected.read_bytes()
    assert b"\r" not in declared and len(declared) <= 65536
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
        stdout.seek(0)
        assert stdout.read(len(declared) + 1) == declared
except Exception:
    sys.stdout.buffer.write(b"transport-step-refused\n")
    raise SystemExit(1) from None
sys.stdout.buffer.write(b"transport-step-checked\n")
```

Require exit zero and exactly `transport-step-checked` plus LF. The ssh returncode, remote stdout and remote stderr are retained as three separate local files, whatever the outcome. A refusal does not identify the failing remote command. ssh's 255, a failed hash check and a failed step are all non-acceptance. Provenance comes from the step's retained on-host captures and markers, never from the outer exit alone. No transport is retried.

## Evidence and limits

`tests/test_m8_lane_output.py` drives the real `codex_lane.main` in a subprocess, with only custody and launch substituted. Its evidence comes from the production lane code with a scripted peer. The summary flows through the actual L0 capture, the frozen `check_evidence` bytes, `lane_expectation` and `lane_boundary`, on accepting and refusing paths. The tests also run the L4 transport over fake ssh outcomes, and they reproduce the original g11 predicate rejecting a clean CLI run. None of this is host, vendor or qualification evidence. Linux sudo, the installed interpreter and the guest's Git remain host facts to measure in a continuation.
