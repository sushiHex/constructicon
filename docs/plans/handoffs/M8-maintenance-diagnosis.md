# Bounded maintenance outcome diagnosis

Status: reviewed implementation design; host commands and exact helper revision must
pass review and CI before execution. Refs #186. No model attempt is supplied.

## Purpose and authority

The g10 application command reported validated non-acceptance for
`run-8658a41ba5866cd73faef4f9575903be`. The P10 checker maps both a normal
non-success result and a command refusal into that same bounded report. Its
exit zero does not establish the application command's exit, admission or
joined shutdown. The controller is
`e7d40b139c2a0205f37c7050295a3eca55af9d2c`. The VM is parked; qualification
is historical. Diagnose retained evidence before proposing any new attempt.

This additive helper is not part of the application's identity and changes
none of its source, frozen plans, controller installation or qualification.
It runs as the service identity against the unchanged installed controller's
contracts/projectors. Root runs only reviewed stock transport commands.
No provider, ControlPlane, scheduler, recovery, Git command, outbound provider network, vendor
binary, credential reader, qualification or repair is part of diagnosis.

## Evidence boundary

Quiescence is a prerequisite supplied by fresh exclusive custody, a clean boot
and no application/recovery startup. Equal file metadata is not evidence of
quiescence. The procedure must check that prerequisite independently.

Never open original retained files with SQLite. SqliteJournal construction
calls migration and can write even on an already-current schema. Capture only
the fixed journal, existing WAL/SHM/rollback sidecars, main and pending attempt
records and published result, plus the separately retained raw application-run
report, into a new private directory. The latter distinguishes normal false
from a generic command refusal but cannot recover the unpersisted raw exit.
Refuse links, nonregular files, unsafe ownership/modes and byte limits. Originals
must be service-owned and not group/world writable inside their checked 0700
containers; safe readable SQLite file modes are not rewritten. Destination
ancestry must be trusted and non-writable by other principals, but need not be
0700; the newly created capture itself must be service-owned 0700. Record each known
file's presence or absence; compare bounded bytes and custody metadata before
and after capture, excluding atime. A mismatch refuses without deleting the
partial evidence. Missing data is not an unused attempt.

Preserve this private capture. Analyze independent copies in disposable private
scratch, with WAL retained, using SQLite mode=ro in one read transaction.
Do not use immutable=1, which must not silently hide retained WAL facts.
No migrations, checkpoint or journal-mode change. Bound SQLite values, VM
instructions, selected rows and the complete published report. A limit hit
or damaged selected fact refuses rather than inventing a complete result.

## Projection and truthful limits

Reuse the journal's canonical selected run, event, checkpoint and attestation
projectors. Report selected-fact validation, not whole-store health: the keyed
checkpoint reader does not replace the complete open-time inventory. Require
the known schema and exact requested run identity. Never use current time to
infer historical worker ownership or physical cleanup.

The report carries only closed categories, bounded counts and identities:

- Run status and positively recorded admission/world facts.
- Known writer/checker events and checkpoint completion. Classify only exact
  known maintenance refusal messages; other causes are unknown. No raw error,
  path, payload or arbitrary exception-type string crosses the output boundary.
- Attempt identity, purpose and phase. Reservation is not dispatch; intent
  precedes the write; recorded completed means adapter success, not independent
  backend confirmation or application acceptance. Pending .next is retained,
  not promoted to the published attempt.
- Known check outcomes where a matching canonical attestation exists. Missing
  attestation does not establish that the exam never ran.
- A writer checkpoint follows positive executor success and completed capture;
  missing checkpoint alone cannot separate execution failure from capture failure.
- Published result observation is historical and not a fresh acceptance grant.

There is no new effect ledger. This graph's capture publishes inside commit_all;
absence of a generic effect receipt says nothing about whether capture ran.

## Resume, interruption and publication review

The reader is synchronous and has no async resume points. Process interruption
may leave a partial private capture; its occupied destination is never reusable.
Only after source comparison and successful selected-fact projection may a
complete bounded report be emitted. A finally block may close handles or remove
disposable scratch; it must never publish success, remove retained evidence or
promote a pending attempt. Failure emits one closed refusal, not raw exceptions.
An interrupted or refused diagnosis grants no retry or recovery authority.

## Proof obligations

Test genuine accepting and refusing fixtures, including a committed fact that
exists only in WAL. Omitting WAL must fail an assertion. Assert original bytes
and directory inventory unchanged; no constructor, migration, provider or
recovery may run. Exercise known writer, capture and gate failure categories,
accepted historical records, every attempt phase and explicit unknowns.

Reject identity mismatches, damaged seals, malformed or oversized input,
symlinks/nonregular files, changing captures and bound exhaustion. Assert the
entire public output against its declared schema and byte bound while inserting
private markers into every source family. Mutations must fail assertions, not
merely error. Linux proof of the WAL route is required before host execution.

The operator sequence below specifies the service-user transport, controller
verification, drift checks, single start, custody guards and clean park. It
requires final review and CI before any host operation. No existing qualification
or application command is reused.

## Design review disposition

Independent source review approved this design before implementation, with
explicit requirements to capture the raw report, never open the preserved copy
with SQLite, and check both source-parent identities and finite budgets.
The earlier proposed inference of admission from C10's summary was refuted by
the two P10 checker branches and withdrawn before implementation. Both branches
must be represented in the regression suite. No host observation was used to
justify that inference, and no additional host operation has occurred.

## Operator sequence (not executable until pins and gates are reviewed)

Use one LF-only script file per step over non-interactive SSH, closed stdin,
BatchMode and strict host-key checking. Compare each script and helper SHA-256
on the VM with the reviewed local literal before execution. No pasted shell,
stdin script, accept-new key, source patch or second start is supplied.
Every unexpected output stops: preserve all files, cleanly park, and report.

The approved SSH/SCP transport is distinct from application/provider traffic.
Prepare one local package for each D1/D2/D3: `common.sh` is the exact boot guard
below with only its measured boot literal filled; `step.sh` is the complete
matching step fence. D2 additionally contains the two helper blobs from the
reviewed commit. Validate LF-only bytes and shell syntax locally first. Use this
transport for each package, setting STEP to d1, d2 or d3 and LOCAL_PACKAGE to its
prepared local directory. It checks the manifest itself against local bytes,
then every script/helper before invoking the uploaded script; no stdin scripts.

```bash
set -Eeuo pipefail
: "${SSH_TARGET:?Pinned SSH target required}"
: "${SSH_HOST_KEY_ALIAS:?Previously recorded host-key alias required}"
: "${LOCAL_PACKAGE:?Reviewed local package required}"
: "${DIAGNOSIS_EXPECTED_BOOT:?Exact boot UUID recorded after D0 required}"
SSH_OPTIONS=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o "HostKeyAlias=$SSH_HOST_KEY_ALIAS")
case "${STEP:-}" in d1|d2|d3) ;; *) exit 1 ;; esac
D1_STEP_SHA256=64dc148e880e7296af8b95bd07f5b09189ef0127acb1116a3a94566e6e831acd
D2_STEP_SHA256=bf0b34fa3ec6fbdeddc9cbcd9ddf611082da3e48449028fb3873119bf5f9f546
D3_STEP_SHA256=b6ecdb443137bd5d31b79e14ebf9158539d91ae52c533ae22c9a0cd0d72460e1
COMMON_TEMPLATE_SHA256=2d627b81641de4e5609e99bfc838cc13bec7988e87e1775a9e53aed3e7c1f49f
cd "$LOCAL_PACKAGE"
FILES=(common.sh step.sh)
if test "$STEP" = d2; then FILES+=(maintenance_evidence.py maintenance_diagnostic.py); fi
if /usr/bin/grep -q $'\r' "${FILES[@]}"; then
  exit 1
else
  LF_STATUS=$?
  test "$LF_STATUS" -eq 1
fi
python -I -S -B -c 'import hashlib, re, sys
from pathlib import Path
step, measured_boot, common_name, step_name, common_pin, d1_pin, d2_pin, d3_pin = sys.argv[1:]
assert step in {"d1", "d2", "d3"}
assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", measured_boot)
common = Path(common_name).read_bytes()
expected_line = f"EXPECTED_BOOT={measured_boot}".encode("ascii")
boot_lines = re.findall(rb"(?m)^EXPECTED_BOOT=[^\r\n]*$", common)
assert len(boot_lines) == 1 and boot_lines[0] == expected_line
assert common.count(expected_line + b"\n") == 1
normalized = common.replace(expected_line + b"\n", b"EXPECTED_BOOT=UNREVIEWED\n", 1)
assert hashlib.sha256(normalized).hexdigest() == common_pin
step_pin = {"d1": d1_pin, "d2": d2_pin, "d3": d3_pin}[step]
assert hashlib.sha256(Path(step_name).read_bytes()).hexdigest() == step_pin' \
  "$STEP" "$DIAGNOSIS_EXPECTED_BOOT" common.sh step.sh \
  "$COMMON_TEMPLATE_SHA256" "$D1_STEP_SHA256" "$D2_STEP_SHA256" "$D3_STEP_SHA256"
bash -n common.sh
bash -n step.sh
set -C
/usr/bin/sha256sum -- "${FILES[@]}" > SHA256SUMS
MANIFEST_SHA256="$(/usr/bin/sha256sum SHA256SUMS)"
MANIFEST_SHA256="${MANIFEST_SHA256%% *}"
[[ "$MANIFEST_SHA256" =~ ^[0-9a-f]{64}$ ]]
ssh -T "${SSH_OPTIONS[@]}" "$SSH_TARGET" \
  "test ! -e \"\$HOME/maintenance-diagnosis-$STEP-package\" && test ! -L \"\$HOME/maintenance-diagnosis-$STEP-package\" && /usr/bin/mkdir -m 0700 -- \"\$HOME/maintenance-diagnosis-$STEP-package\"" < /dev/null
scp "${SSH_OPTIONS[@]}" "${FILES[@]}" SHA256SUMS \
  "$SSH_TARGET:maintenance-diagnosis-$STEP-package/" < /dev/null
ssh -T "${SSH_OPTIONS[@]}" "$SSH_TARGET" \
  "cd \"\$HOME/maintenance-diagnosis-$STEP-package\" && printf '%s  SHA256SUMS\n' '$MANIFEST_SHA256' | /usr/bin/sha256sum --check --strict && /usr/bin/sha256sum --check --strict SHA256SUMS && bash step.sh" < /dev/null
```

### D0: custody and one clean start

Require the owner's current wave authorization, peer release and fresh exclusive
custody of operator, root and service identities. Notify before starting. The
prior Off observation is not this check. No other session, daemon or scheduled
application/recovery process may run during the capture. If that cannot be
affirmed, stop; metadata equality alone cannot establish a coherent snapshot.

```powershell
$diagnosisVm = Get-VM -Name constructicon-m8
if ($diagnosisVm.State -ne 'Off') { throw 'Expected already Off VM' }
if (@(Get-VMSnapshot -VMName constructicon-m8).Count -ne 0) { throw 'Unexpected checkpoint' }
Start-VM -Name constructicon-m8
```

Read the current DHCP target privately and record the complete boot id. There
is no reboot, checkpoint or R6 authorization. All later steps require this same
boot and continuous exclusive custody.

### D1: installed provenance, drift and no execution startup

Use the existing pinned SSH identity and the verified controller-provenance
workspace retained from g10. Do not refresh it, fetch source on the guest, or
reuse a historical qualification as a readiness check. This is local installed
file verification only; it contacts no vendor and launches no application.

```bash
set -Eeuo pipefail
umask 077
. "$HOME/maintenance-diagnosis-d1-package/common.sh"
sudo -n true < /dev/null
/usr/local/bin/m8-host-drift < /dev/null
/usr/bin/python3 -I "$HOME/m8-controller/m8_host_artifacts.py" \
  verify-controller e7d40b139c2a0205f37c7050295a3eca55af9d2c "$HOME/m8-controller" < /dev/null
```

Require affirmative NO DRIFT and installed true/state tree/different zero at
that exact C. A refusal does not authorize replacement or baseline changes.
Before staging, separately check no application process or application startup
is using the service identity. The drift baseline and exclusive operator/root
custody supply the no-new-start condition; this process check is the positive
point observation, not a lock against an administrator breaking custody.

Save this block as each package's `common.sh`, replacing EXPECTED_BOOT
only with the complete boot UUID recorded after D0. D1, D2 and D3 source it
before their operations. Require exactly the marker
and no process identifiers. pgrep exit two or any other failure is not absence.

```bash
set -Eeuo pipefail
EXPECTED_BOOT=UNREVIEWED
[[ "$EXPECTED_BOOT" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]
test "$(/usr/bin/cat /proc/sys/kernel/random/boot_id)" = "$EXPECTED_BOOT"
if /usr/bin/pgrep -u m8-service; then
  echo 'service identity is active; stop' >&2
  exit 1
else
  PROCESS_STATUS=$?
  test "$PROCESS_STATUS" -eq 1
fi
printf '%s\n' diagnosis-quiescence-checked
```

### D2: stage only the two reviewed helpers

The fresh operator package contains exactly the two helper blobs, common, this step
and their covering SHA-256 manifest. Its manifest digest must first match the
local reviewed literal. The helper digests below pin this implementation and are
checked by the tests; do not derive the expected values from guest files.

```bash
set -Eeuo pipefail
umask 077
. "$HOME/maintenance-diagnosis-d2-package/common.sh"
EVIDENCE_SHA256=2f654a218fcb55eee65a59c1c8ae63bc8a761db3fe71143f41dff69e22a1b578
DIAGNOSTIC_SHA256=f0555df16b076b7a5d65d786d9ffd5febb9878b3065e1a2fbc7565d0197a6c69
[[ "$EVIDENCE_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$DIAGNOSTIC_SHA256" =~ ^[0-9a-f]{64}$ ]]
P="$HOME/maintenance-diagnosis-d2-package"
T=/home/m8-service/m8-maint-diagnosis-1-tools
printf '%s  %s\n' "$EVIDENCE_SHA256" "$P/maintenance_evidence.py" \
  "$DIAGNOSTIC_SHA256" "$P/maintenance_diagnostic.py" | /usr/bin/sha256sum --check --strict
sudo -n /usr/bin/test ! -e "$T" < /dev/null
sudo -n /usr/bin/test ! -L "$T" < /dev/null
sudo -n /usr/bin/mkdir -m 0750 -- "$T" < /dev/null
sudo -n /usr/bin/chown root:m8-service "$T" < /dev/null
sudo -n /usr/bin/install -o root -g m8-service -m 0440 \
  "$P/maintenance_evidence.py" "$T/maintenance_evidence.py" < /dev/null
sudo -n /usr/bin/install -o root -g m8-service -m 0440 \
  "$P/maintenance_diagnostic.py" "$T/maintenance_diagnostic.py" < /dev/null
sudo -n -u m8-service /usr/bin/sha256sum \
  "$T/maintenance_evidence.py" "$T/maintenance_diagnostic.py" < /dev/null
```

Compare the two returned digests with the same reviewed literals. Root executes
only these stock filesystem tools, not either helper. The controller is not
modified. Any occupied target or partial staging stops without cleanup/reuse.

### D3: one capture and bounded diagnosis

Recheck same boot/custody and NO DRIFT first. The bootstrap imports the existing
installed journal package and appends a directory containing only the two new
reviewed modules. It cannot shadow an installed module. The helpers operate as
the service user, with no credentials or inherited environment. They never
import the application entry or construct a journal/provider/control plane.

```bash
set -Eeuo pipefail
umask 077
. "$HOME/maintenance-diagnosis-d3-package/common.sh"
/usr/local/bin/m8-host-drift < /dev/null
sudo -n -u m8-service /usr/bin/env -i PATH=/usr/bin:/bin HOME=/home/m8-service LANG=C.UTF-8 \
  /usr/bin/python3 -I -S -B -c 'import importlib.util, runpy, sys
sys.path.insert(0, "/opt/constructicon-m8-controller")
import constructicon.substrate.journal as journal
assert importlib.util.find_spec("constructicon.substrate.journal.maintenance_diagnostic") is None
assert importlib.util.find_spec("constructicon.substrate.journal.maintenance_evidence") is None
journal.__path__.append(sys.argv.pop(1))
runpy.run_module("constructicon.substrate.journal.maintenance_diagnostic", run_name="__main__", alter_sys=True)' \
  /home/m8-service/m8-maint-diagnosis-1-tools \
  --root /home/m8-service/m8-maint-a2 \
  --out /home/m8-service/m8-maint-diagnosis-1-evidence \
  --command-report /home/m8-service/m8-m2/application-run.json \
  --run-id run-8658a41ba5866cd73faef4f9575903be \
  --authorization-id maintenance-2-e7d40b139c2a0205f37c7050295a3eca55af9d2c < /dev/null
```

Only the complete closed-schema report or the documented closed refusal is
expected. No raw source records leave the guest. Preserve the capture even if
analysis refuses. Do not run a second diagnostic into another directory as an
automatic response to refusal; record the observation and park.

### D4: preserve and park

No qualification, refresh, retry, recovery, disposition, Git operation or model
attempt follows any diagnostic outcome. Retain the helper package, capture and
all original evidence. Cleanly stop from Windows:

```powershell
Stop-VM -Name constructicon-m8
$diagnosisVm = Get-VM -Name constructicon-m8
if ($diagnosisVm.State -ne 'Off') { throw 'VM did not stop' }
if (@(Get-VMSnapshot -VMName constructicon-m8).Count -ne 0) { throw 'Unexpected checkpoint' }
```

Report bounded observed facts and their limits on #186; release custody. The
next change is selected from evidence, never from a missing record or exit zero.
