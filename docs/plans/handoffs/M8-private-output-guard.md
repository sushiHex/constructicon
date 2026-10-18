# M8 private host output guard

Source-only preparation for [#226](https://github.com/sushiHex/constructicon/issues/226)
and the selected successor checks in [#189](https://github.com/sushiHex/constructicon/issues/189).
This is a reusable boundary, not the q13 procedure or authority to execute it.
Frozen procedures and tests retain their bytes. No host output or installed-tool
digest is recorded here.

## Contract and composition

The procedure declares `DRIFT_STDOUT_HEX=UNREVIEWED` and
`DRIFT_TOOL_SHA256=UNREVIEWED` exactly once in every step selecting G1, lexically
before its first G1 fence. Repeated G1 fences in that step share this one pair.
The packager checks this source contract even for templates and deferred steps;
another step's fills, inherited variables and literal assignments do not satisfy
it. This establishes lexical placement, not arbitrary Bash control flow.
The packager fills these from the
private `--values` TOML file as read-only shell variables. The first is canonical
lowercase hex encoding a nonempty printable UTF-8 line, including its final LF,
at most 4,096 decoded bytes. Shell metacharacters are data. The second is the
64-character lowercase SHA-256 of the installed tool. Neither is learned from
the invocation being checked. The expectation needs the owner's independent
approval by file digest, as the [post-q12 review](M8-post-q12-review.md) describes.

Initialize the private records parent before the first guard; each call assigns
`DRIFT_CAPTURE` an absent child of that parent. Select the exact G1 fence at each
call site, including inside the conditional H8 branch and twice in diagnosis.
The fence creates its own capture directory exclusively. An occupied directory,
file or symlink refuses before executing the tool; captures are never reused.

For successor compositions the packager refuses every mention of `m8-host-drift`
outside an exact G1 fence,
after the same shell normalization as its lane guard. Repeating the reviewed
fence is allowed; matching a count does not authorize an unguarded call. This is
an honest-composition lint, with the packager's existing threat model: generated
shell, encoded names, deliberate indirection and changes to surrounding shell
context require source review. It does not interpret Bash or prove an arbitrary
reviewed composition's declared output. A declared emitter remains a provenance
claim until the assembled step is exercised against its contract.
The exact frozen q12 document remains assemblable for historical test compatibility,
by document digest only. That exemption gives no execution authority; changing
even one byte removes it. q12's assumed output remains a known defect.

G1 records whether launch was requested and the direct child's numeric status,
stdout and stderr. Two concurrent bounded-memory drains copy pipes into retained
private files. Both drains must reach EOF successfully before comparison; the
child and its descendants never receive the capture file handles. Direct-child
exit alone does not complete capture. A failed drain refuses, preserving whatever
private bytes were captured, not certifying them as complete.
It emits only `drift-checked` after status zero, empty stderr and exact stdout.
A mismatch exits the entire step before its next command, even when the fence
appears in an `if` body or a context where Bash disables errexit. Raw diagnostics
remain private. The `launch_requested` field is false until launch is requested;
then that field is true, with `returncode: null` until the
completed process supplies a status. An exception during launch does not prove
that no process started. A completed nonzero exit is retained as such.

## G1: private drift boundary

```bash
/usr/bin/python3 -I -S -B - "$DRIFT_CAPTURE" "$DRIFT_STDOUT_HEX" "$DRIFT_TOOL_SHA256" <<'PY' || exit "$?"
import hashlib
import json
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

def main():
    capture, encoded, digest = sys.argv[1:]
    if not re.fullmatch(r"(?:[0-9a-f]{2}){2,4096}", encoded):
        raise ValueError("expectation encoding")
    expected = bytes.fromhex(encoded)
    text = expected.decode("utf-8")
    if not text.endswith("\n") or not text[:-1].strip() or not text[:-1].isprintable():
        raise ValueError("expectation line")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("tool digest")
    directory = Path(capture)
    directory.mkdir(mode=0o700)
    result = {"launch_requested": False, "returncode": None}
    tool = Path("/usr/local/bin/m8-host-drift")
    try:
        with (directory / "stdout").open("x+b") as stdout, (directory / "stderr").open("x+b") as stderr:
            if hashlib.sha256(tool.read_bytes()).hexdigest() != digest:
                raise ValueError("tool changed")
            result["launch_requested"] = True
            with subprocess.Popen([str(tool)], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  bufsize=0) as child, ThreadPoolExecutor(max_workers=2) as drains:
                stdout_copied = drains.submit(shutil.copyfileobj, child.stdout, stdout, 65536)
                stderr_copied = drains.submit(shutil.copyfileobj, child.stderr, stderr, 65536)
                status = child.wait()
                result["returncode"] = status
                stdout_copied.result()
                stderr_copied.result()
                stdout.flush()
                stderr.flush()
                stdout.seek(0)
                actual = stdout.read(4097)
                stderr.seek(0)
                diagnostic = stderr.read(1)
                if status != 0 or diagnostic or actual != expected:
                    raise ValueError("output contract")
    finally:
        with (directory / "status.json").open("x", encoding="utf-8", newline="\n") as record:
            record.write(json.dumps(result, sort_keys=True) + "\n")
    sys.stdout.buffer.write(b"drift-checked\n")

try:
    main()
except (OSError, ValueError, UnicodeError):
    sys.stderr.buffer.write(b"drift-guard-refused\n")
    raise SystemExit(1) from None
PY
```

## Evidence and limits

`tests/test_m8_private_output_guard.py` assembles G1 through the production
packager and runs the resulting step with Bash. Its host executable is explicitly
synthetic. The accepting sentence is longer than a marker; a different plausible
affirmative line refuses. Cases include extra lines, missing LF, CRLF, stderr,
nonzero status, oversized stdout, an occupied capture, a mismatching tool digest,
the conditional branch and repeated calls. Every accepting path asserts the
whole stdout and empty stderr. Every mismatch checks that the next command did
not run. These are portable executable proofs, not private-host observations.
Test-only control-socket barriers hold a real descendant's inherited streams open
until the guard awaits EOF, without sleep-based success criteria. Late stdout and
stderr are captured and refuse; a silent descendant closes both streams before
acceptance. A completed drain that raises also refuses despite matching bytes.
Executable mutations removing either drain-result check, or bypassing both EOF
joins before comparison, fail verdict assertions. These synchronization hooks are
test instrumentation, not production interfaces or host evidence.

A host-only stub in a successor must be labelled **synthetic**, or **measured**
with a stable private evidence reference, custodian, retention period and integrity
digest. Synthetic success must have a paired, different plausible output that
fails the same boundary. Where the contract requires silence, success asserts
empty stderr as well as status and stdout. Earlier frozen tests are not repaired
or reclassified as measurements by these checks.

The comparison is bounded after capture: output is streamed to disk without a
capture limit, and execution has no timeout. A descendant retaining a pipe can
keep the guard waiting indefinitely. EOF establishes stream completion, not
process-tree termination. Capturing may fail or be interrupted; an absent status
record or failed drain is incomplete capture evidence, even if a direct-child
return code was recorded. A trusted tool could deliberately reopen capture paths;
this is not containment against an adversarial filesystem actor.
The hash check reads the installed
path before subprocess reopens it; trusted host custody must prevent replacement
between those operations. This pins an observed file digest, not descriptor-bound
execution. A matching line and tool digest do not establish qualification, sudo
silence, host Python silence, stock-utility behaviour, or a completed application.

No installed digest, private expectation, approved private evidence reference,
complete q13 composition or live rehearsal is supplied by this slice.
