# q13: exact accepted-candidate transfer

Proposed source-only procedure under [#245](https://github.com/sushiHex/constructicon/issues/245)
and [#186](https://github.com/sushiHex/constructicon/issues/186).
This document grants no host execution authority. The q13 session is spent;
its candidate is preserved, not recreated by another model or application run.

## One artifact, one historical contribution

The source is the protected authority repository, never a mutable staging
workspace. Export only the raw candidate commit, its single added vector blob,
and the existing closed historical acceptance projection. Do not export a
workspace, credential store, journal, private locator, configuration, unrelated
object history, or rendered executable test code.

The independently recorded pins are:

- candidate: `058d85fed094256f09b909789a8e07b72092337f`;
- sole parent/base: `5793ef98ef5597c9ee9811a0d1f031554eb7f514`;
- run: `run-4c5df557e3d2f6a0f44030084115f865`;
- only added path: `tests/vectors/plan_manifest.json`, mode `100644`;
- input SHA-256:
  `ef04c5d45233e6a7cd7b54e9cc29d1e67a9511f1a030f6a57df8278a9759d67e`;
- render SHA-256:
  `ec1a425474b6cd7c286c65556bfa9e5bd3278c525436d1efa867acd249fc3d02`.

The living [implementation record](M8-implementation-record.md) supplies the
historical observations. The transferred projection must agree with these pins;
it is not a new attestation or fresh executor qualification. Its producer,
`inspect_result`, explicitly does not establish authenticity by itself.

## Minimal mechanism

Reuse the retained controller's `inspect_source`, `read_bounded`, `GitProcess`
and `inspect_result` when reading the host. Its source/controller pin stays at
the base above; no replacement or new installed API is assumed. The new helper
is separately reviewed procedure code, not a command to import candidate code.
Run as the service principal, never as root or a vendor client.

Before emission, require the exact parent and raw added-file delta already
required by the maintenance application. Bound the commit to 4,096 bytes and
the vector blob to the existing 32,768-byte law. Accept only the closed commit
header grammar: tree, one parent, author, committer, then a message; no extra
headers. Check the Git object identity and observed input digest. Retain these
bytes privately and inspect them, including the public-text checks, before any
public push. Emit one bounded, closed JSON artifact only after every check passes.
No earlier output is an accepted artifact.

The design review corrected an initial assumption: capture supplies fixed
identity/date/message only when it makes a commit. A writer can commit before
capture, and the accepted application checks parent and delta, not those
headers. Therefore fixed commit metadata is not an observed q13 fact. Never
reconstruct or sanitize it while claiming to preserve the original commit ID.

On the workstation, use a fresh quarantine and the independently present base.
Reconstruct the tree from that base plus the one regular-file blob, then require
the resulting tree and raw commit object identity to equal the exported and
historically pinned values. This proves the whole-tree delta rather than
trusting an exported list of changed paths. Re-run the existing trusted vector
exam from reviewed authority source, not source supplied in the artifact;
require both observed input/render digests and the positive exam verdict.
Keep historical matching distinct from the new exam result. A matching render
digest alone does not prove the historical mutants ran or passed. Preserve the
vector bytes exactly, including valid JSON whitespace; no checkout line-ending
conversion may silently change them.

This is narrower than importing a Git bundle: it transports no ancestry or
pack object closure and accepts no arbitrary refs or paths. It is not a new
general artifact protocol or a replacement for normal Git capture. After
verification, ordinary contribution tooling can publish the data-only change
against current main with explicit provenance to the original candidate.

## Await, partial-output and crash review

- Before each source Git await, custody and source inspection must have passed.
  Source objects are immutable and addressed by exact object IDs; a changed
  ref cannot silently select another candidate. Current exclusive custody,
  not a historical quiet observation, excludes concurrent maintenance.
- Each await can raise, be cancelled or return after a prior check. Reuse the
  joined, bounded Git pump. Do not publish in `finally`, and do not turn an
  empty output or absent failure list into a successful check.
- Validate all selected bytes before a fresh exclusive output is published.
  A missing, truncated or partially written artifact is incomplete. A crash
  consumes the attempted capture; it does not authorize automatic repetition.
- Receiver refusal leaves no contribution branch or installed candidate. Any
  scratch objects belong to a disposable quarantine, never the main checkout.
  Check all public fields by the artifact's closed schema and bounds.
- A complete transport proves receipt of bytes, not historical acceptance.
  Matching the independent pins, reconstructed commit and trusted exam are
  separate positive gates. A later ordinary PR proves neither fresh provider
  readiness nor a new host qualification.

## Host-session boundary

Exact commands, package hashes, transport checks and accepting/refusing
rehearsals must be reviewed before a separate execution go. Reuse the existing
strict-host-identity transport and fresh private destinations. Query usage and
obtain current custody rather than asking the owner to infer host use.
Stop and park on unexpected output or uncertain transport; do not retry.

The historical drift tool has the baseline-inventory limitation recorded in
[#238](https://github.com/sushiHex/constructicon/issues/238). Matching its output
does not certify complete custody or current qualification. The eventual
procedure must name the specific controller/source/metadata checks needed for
this read-only transfer; it must not silently authorize an R6 re-baseline,
controller replacement, new credential qualification, or model attempt.

## Required proofs before review-ready

Use disposable real Git repositories and the actual helper. Prove a valid
one-file transfer and refuse wrong candidate, base, parent cardinality, mode,
extra paths, commit metadata, input/render digest, acceptance projection,
oversized/malformed/duplicate-key artifact, partial output, and occupied
destinations. Exercise publication failure without a falsely complete record.
Tests must execute without vendor binaries, credentials or private-host access.
The final procedure composition must be rehearsed, not merely its fragments.

An independent Sol design pass and Fable's source-grounded second opinion
support this raw-object reconstruction instead of importing a bundle. The
fixed-metadata premise above was rejected and corrected before implementation
review. Final-head proof and execution authorization remain pending.

## T0: custody, preparation and lifecycle

This is one new read-only session, not a continuation of q13's spent dispatch.
Before starting, obtain the exact-package execution go, query current usage with
`scripts/m8_vm_usage.py`, obtain the peer's current release and record exclusive
custody under [the custody procedure](M8-vm-custody.md). Unknown is not idle.
Use the unchanged D0 and D4 PowerShell fences in
[the diagnosis procedure](M8-maintenance-diagnosis.md), SHA-256
`41f76f299999fbd4af5a41da6b1142f11c89cc8a57f60b68f6d1d252811d1e45`.
These are the only platform-specific commands: require Off and no checkpoints,
notify before the one start, and cleanly stop and verify Off after success or
refusal. Do not start until review and CI complete. No automatic retry follows
a partial transfer; retain its private evidence and park.

Build this document with the existing `m8_procedure_package.py`, after recording
the fresh full boot UUID in a private values TOML as `EXPECTED_BOOT`. Its two
steps are deferred until that value exists. `--template` is rehearsal only.
The build's exclusive fresh directory and manifest-last rule apply unchanged.
Copy the reviewed `scripts/m8_candidate_transfer.py` into the package as
`m8_candidate_transfer.py`; extend the covering manifest with its exact staged
blob digest. Freeze and record the resulting manifest digest before upload.
The helper must be LF-only and match the reviewed Git blob. A generated package
or a hash derived only from the guest is not review evidence.

Use the existing private SSH target and host-key alias, never a newly trusted
key. Run every step as a script file with closed stdin, not pasted interactively.
The package is `$HOME/maintenance-q13-export-package`, created once as a private
0700 directory. Strict SSH options are `BatchMode=yes`,
`StrictHostKeyChecking=yes`, the recorded `HostKeyAlias`, `ConnectTimeout=15`
and `LogLevel=ERROR`. Upload by SCP. Before either step, compare the package
manifest's SHA-256 to the workstation's recorded literal, then run
`sha256sum --check --strict --quiet MANIFEST.sha256`. Do not accept exit status
alone: the first step must print exactly `candidate-source-preflight-checked`;
the second must produce the bounded artifact accepted by the local capture.

### Exact local preparation

Save this Python fence verbatim as a private `prepare.py`. Invoke it with
`python -I -S -B prepare.py CHECKOUT OUTPUT VALUES REVIEWED_COMMIT`: the checkout,
fresh package directory, private boot-values TOML and exact reviewed procedure
commit, in that order. The checkout must be at that commit.
This prepares files only; it never starts the VM or invokes SSH. It reads helper
bytes from the reviewed commit, not a possibly modified working copy. The
packager also executes directly from that commit's blob, without adding the
checkout to Python's import path. Untracked or ignored package initializers
and adjacent standard-library shadows therefore cannot execute during preparation.
The packager independently binds document bytes to their manifest. Preserve the
printed final manifest digest as `PACKAGE_SHA256` for the commands below.

```python
import hashlib
import subprocess
import sys
import types
from pathlib import Path

checkout, output, values = map(Path, sys.argv[1:4])
revision = sys.argv[4]
assert len(revision) == 40 and all(c in "0123456789abcdef" for c in revision)
def git(*args):
    return subprocess.check_output(["git", "-C", str(checkout), *args],
                                   stdin=subprocess.DEVNULL, timeout=30)
assert git("rev-parse", "HEAD").decode().strip() == revision
assert git("status", "--porcelain", "--untracked-files=no") == b""
packager = git("show", revision + ":scripts/m8_procedure_package.py")
assert 0 < len(packager) <= 65536 and b"\r" not in packager
package = types.ModuleType("q13_procedure_package")
sys.modules[package.__name__] = package
exec(compile(packager, "<reviewed-procedure-packager>", "exec"), package.__dict__)

docs = checkout / "docs/plans/handoffs"
document = docs / "M8-q13-candidate-transfer.md"
steps = package.assemble(document, values=package.session_values(values))
assert len(steps) == 2 and not any(step.waiting for step in steps)
package.build(document, output, values=package.session_values(values))
helper = git("show", revision + ":scripts/m8_candidate_transfer.py")
assert 0 < len(helper) <= 65536 and b"\r" not in helper
q12 = (docs / "M8-maintenance-q12-continuation.md").read_bytes()
assert hashlib.sha256(q12).hexdigest() == "1fbd0a983fc9537f47198221b5a84937da6b3e79fe0c15fb77b3e9b2ba4d76b1"
fences = package.fences(package.section(q12.decode(), "Q6: transport T5"))
transport = [body.encode() for language, body in fences if language == "python"]
assert len(transport) == 1 and b"\r" not in transport[0]
for name, raw in (("m8_candidate_transfer.py", helper), ("transport.py", transport[0])):
    with (output / name).open("xb") as stream:
        stream.write(raw)
# Preserve the generated steps-only manifest; the final covering manifest is
# a separate exclusive file, published only after every member has been written.
members = sorted(p for p in output.iterdir() if p.is_file())
raw = "".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
              for p in members).encode("ascii")
with (output / "PACKAGE.sha256").open("xb") as stream:
    stream.write(raw)
print(hashlib.sha256(raw).hexdigest())
```

### Exact closed transport

Run this fence as a Git Bash script file on the workstation with stdin closed.
`PACKAGE` is the fresh prepared directory, `CAPTURE` an absent private directory,
`SSH_TARGET` and `SSH_HOST_KEY_ALIAS` the existing private identities,
`PACKAGE_SHA256` the recorded preparation digest. Execute from the reviewed
checkout using its own environment. These are inputs, not values inferred from
the guest. Any nonzero result stops this script and requires the D4 park path;
do not resume the next line. The preflight uses the frozen T5 only for its small
trusted control output; only candidate transport claims the new byte/deadline
bounds. No pipeline supplies an SSH script through stdin.

```bash
set -Eeuo pipefail
: "${PACKAGE:?}" "${CAPTURE:?}" "${SSH_TARGET:?}" "${SSH_HOST_KEY_ALIAS:?}" "${PACKAGE_SHA256:?}"
[[ "$PACKAGE_SHA256" =~ ^[0-9a-f]{64}$ ]]
OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o "HostKeyAlias=$SSH_HOST_KEY_ALIAS"
      -o ConnectTimeout=15 -o LogLevel=ERROR)
SSH="$(uv run python -I -c 'import shutil; from pathlib import Path; print(Path(shutil.which("ssh")).resolve())' < /dev/null)"
printf '%s  %s\n' "$PACKAGE_SHA256" "$PACKAGE/PACKAGE.sha256" | sha256sum --check --strict --quiet
(cd "$PACKAGE" && sha256sum --check --strict --quiet PACKAGE.sha256)
"$SSH" -T "${OPTS[@]}" "$SSH_TARGET" \
  'umask 077; test ! -e "$HOME/maintenance-q13-export-package" && test ! -L "$HOME/maintenance-q13-export-package" && mkdir -m 0700 "$HOME/maintenance-q13-export-package"' < /dev/null
scp "${OPTS[@]}" "$PACKAGE"/* "$SSH_TARGET:maintenance-q13-export-package/" < /dev/null
REMOTE="cd \"\$HOME/maintenance-q13-export-package\" && printf '%s  PACKAGE.sha256\n' '$PACKAGE_SHA256' | /usr/bin/sha256sum --check --strict --quiet && /usr/bin/sha256sum --check --strict --quiet PACKAGE.sha256"
uv run python -I "$PACKAGE/transport.py" "$PACKAGE/preflight" \
  "$PACKAGE/q13-export-preflight.expected.json" -- "$SSH" -T "${OPTS[@]}" \
  "$SSH_TARGET" "$REMOTE && bash q13-export-preflight.sh" < /dev/null
uv run python -I scripts/m8_candidate_transfer.py capture --out "$CAPTURE" -- \
  "$SSH" -T "${OPTS[@]}" "$SSH_TARGET" \
  "$REMOTE && bash q13-export-candidate.sh" < /dev/null
```

## T1: controller and import preflight

The frozen record checker creates a fresh private records directory. The
controller verifier is checked against its independently pinned source before
invocation. R19 remains byte-identical; the export bootstrap additionally checks
the modules it actually imports. This proves neither provider qualification nor
the completeness of the historical drift baseline.

```bash
set -Eeuo pipefail
umask 077
P="$HOME/maintenance-q13-export-package"
C=5793ef98ef5597c9ee9811a0d1f031554eb7f514
RECORDS="$P/records"
sudo -n true < /dev/null
```

```bash
printf '%s  %s\n' c3c714b2f6c1d1c62c9e1e9c31c6851277c6b661ee9c983efbceaa255911c856 \
  "$HOME/m8-controller/m8_host_artifacts.py" | /usr/bin/sha256sum --check --strict --quiet
/usr/bin/python3 -I "$HOME/m8-controller/m8_host_artifacts.py" \
  verify-controller "$C" "$HOME/m8-controller" < /dev/null > "$RECORDS/controller.json"
record_check controller "$RECORDS/controller.json" "$C" > /dev/null
W="$RECORDS/import"
/usr/bin/mkdir -m 0700 -- "$W"
```

```bash
record_check r19 "$RECORDS/import.out" > /dev/null
printf '%s\n%s\n' "$EXPECTED_BOOT" "$C" > "$RECORDS/preflight.ok"
printf '%s\n' candidate-source-preflight-checked
```

## T2: immutable export

This command reads only `/home/m8-service/m8-maint-a5/authority.git` and the
closed result projection, with source inspection before and after. It does not
instantiate `GitAuthority` (whose constructor writes a hook), load the journal,
or start the control plane. The reviewed helper travels as one Python argument;
it is never installed into the controller or made readable through the service
user's access to the operator home. The bootstrap checks every imported module's
file before invoking the export. Nothing but the completed artifact reaches
stdout; diagnostics and partial captures stay private.

```bash
set -Eeuo pipefail
umask 077
P="$HOME/maintenance-q13-export-package"
C=5793ef98ef5597c9ee9811a0d1f031554eb7f514
```

```bash
test "$(/usr/bin/cat "$P/records/preflight.ok")" = "$(printf '%s\n%s' "$EXPECTED_BOOT" "$C")"
CODE="$(/usr/bin/cat "$P/m8_candidate_transfer.py"; printf '.')"
CODE=${CODE%.}
cd /
sudo -n -u m8-service env -i PATH=/usr/bin:/bin HOME=/home/m8-service LANG=C.UTF-8 \
  /usr/bin/python3 -I -S -B -c 'import sys, sysconfig, types
sys.path.insert(0, "/opt/constructicon-m8-controller")
m = types.ModuleType("q13_transfer")
sys.modules[m.__name__] = m
exec(compile(sys.argv[1], "<reviewed-transfer>", "exec"), m.__dict__)
roots = ("/opt/constructicon-m8-controller/", sysconfig.get_paths()["stdlib"] + "/", sysconfig.get_paths()["platstdlib"] + "/")
files = [getattr(v, "__file__", None) for v in list(sys.modules.values())]
if any(f and not f.startswith(roots) for f in files):
    raise SystemExit("candidate-transfer-import-refused")
raise SystemExit(m.main(["export", "--root", "/home/m8-service/m8-maint-a5"]))' "$CODE" < /dev/null
```

## T3: receive, reconstruct and park

Run the workstation helper from this checkout's own environment. Use its
`capture --out FRESH -- ABSOLUTE_SSH ...` command to invoke the manifest-checked
T2 script. It closes stdin, bounds retained stdout to 80 KiB plus one overflow
sentinel byte and stderr to 1 KiB plus one sentinel byte, and applies a 60-second
exchange deadline. Cleanup joins the owned process and readers; that deadline
is not a hard wall-clock bound on cleanup or a remote-termination guarantee.
A local SSH kill does not prove remote termination;
on timeout preserve captures, stop and park without repeating T2.
Only positive exit, both EOFs, empty stderr and a valid closed artifact publish
`artifact.json`. `status.json` records incomplete outcomes too. Do not use the
older T5 transport to claim an output or elapsed-time bound it does not have.

With the host still held under custody, invoke:

```bash
uv run python -I scripts/m8_candidate_transfer.py verify \
  --artifact "$CAPTURE/artifact.json" --trusted-base "$CHECKOUT" \
  --quarantine "$QUARANTINE" < /dev/null
```

`CAPTURE`, `CHECKOUT` and `QUARANTINE` are private absolute workstation paths;
the quarantine must not exist. Require the closed receipt with
`historical_projection_matched`, `tree_reconstructed` and `reexam_passed` all
true, plus exact independently recorded pins. Then execute the unchanged D4
park fence, verify Off/no checkpoints, record bounded facts on #245 and release
custody. Do not publish raw private captures. Inspect the exact commit metadata
and vector text privately before creating the ordinary data-only contribution
PR. #186 remains open until that separate contribution and its criteria close.

## Composition

```toml
labels = {current = ["q13"], historical = []}

[sources.diagnosis]
path = "M8-maintenance-diagnosis.md"
sha256 = "41f76f299999fbd4af5a41da6b1142f11c89cc8a57f60b68f6d1d252811d1e45"
[sources.records]
path = "M8-maintenance-q12-continuation.md"
sha256 = "1fbd0a983fc9537f47198221b5a84937da6b3e79fe0c15fb77b3e9b2ba4d76b1"
[sources.runtime]
path = "M8-N4-host-runtime.md"
sha256 = "349a79981c4b6d0de494fa873a6b52a39850787aa37b56f1797ea1addb86ac9b"

[[steps]]
name = "q13-export-preflight"
deferred = true
stdout = ["candidate-source-preflight-checked"]
parts = [
  {source = "self", heading = "T1: controller and import preflight", fences = [0]},
  {literal = "{"},
  {source = "diagnosis", heading = "D1: installed provenance, drift and no execution startup", fences = [1]},
  {literal = "} > /dev/null"},
  {source = "records", heading = "Q4: private host records", fences = [0]},
  {source = "self", heading = "T1: controller and import preflight", fences = [1]},
  {literal = "{"},
  {source = "runtime", heading = "R19 — Import check as `m8-service`", fences = [0]},
  {literal = '} > "$RECORDS/import.out"'},
  {source = "self", heading = "T1: controller and import preflight", fences = [2]},
]

[[steps]]
name = "q13-export-candidate"
deferred = true
stdout = []
parts = [
  {source = "self", heading = "T2: immutable export", fences = [0]},
  {literal = "{"},
  {source = "diagnosis", heading = "D1: installed provenance, drift and no execution startup", fences = [1]},
  {literal = "} > /dev/null"},
  {source = "self", heading = "T2: immutable export", fences = [1]},
]
```

The second step's bytes are consumed by `capture`, not by the package's static
stdout expectation. Its empty expectation is not evidence of successful export.
