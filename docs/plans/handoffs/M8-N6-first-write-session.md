# Claude first WRITE: bounded procedure proposal

**Proposal, unexecuted.** This living procedure prepares one owner window under
[ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md),
[M8 N6](../milestones/M8-live-executors-rev3.md#n6--independent-claude-code-qualification)
and the [WRITE state review](M8-N6-WRITE-state-review.md). It grants no host,
credential, publication, activation or model-call authority. The window can be
approved only after the code is merged with applicable final-head CI and review,
and the exact private package below is bound to that merged controller `C`.
Earlier READ evidence and spent READ authorization do not qualify this WRITE.

## Owner scope and unresolved inputs

The proposed call uses the installed unmodified Claude Code subscription client,
`claude-sonnet-4-6`, effort `low`, and the fixed WRITE qualification task:
`Use contained_python to create n5-write.txt containing exactly ready followed
by a newline. Change no other files.` Its fresh disposable Git fixture contains
the reviewed empty seed, not user repository content. Success requires a changed
captured candidate and the fixed exact-file gate. No candidate installation or
target merge is selected.

The core authorization allows one epoch and one exclusive attempt. The executor
grant is 300 seconds, with at most eight sequential admitted callbacks, 128 KiB
UTF-8 program bytes and 32 KiB UTF-8 output per callback. The task requests one
program; zero successful callbacks cannot qualify. Native cumulative input,
stdout, record, stderr and connection bounds must be read from the actual sealed
WRITE recipe and reviewed before authority placement. Capture/gate/outer
observation retain their separately declared bounds; none renews the model turn.
No enforced token, backend request-count or financial ceiling is claimed. The
owner must explicitly accept the actual subscription overage policy and this
one attempt's exposure, or the attempt is not released. No paid-API fallback,
model change, egress widening, second smoke or retry is selected.

Keep `C`, the fresh boot UUID, installed launch/configuration pins, generation
`FLOOR`, `GENERATION = FLOOR + 1`, fresh semantic qualification digest `Q`, raw
evidence hash, expiry, actor/key and all private paths **UNREVIEWED** until checked.
Do not substitute historical values. The owner may approve deterministic fresh
pin derivation and exact-match placement in one window; a scope/input deviation
returns to the owner, not an automatic remint.

## Source, transport and controller preparation

Reuse the existing source-export/hash checks and strict noninteractive transport
patterns from [the Claude host procedure](M8-N6-host-session.md) and
[first READ preparation](M8-N6-first-read-session.md). Export the selected Git
blobs at reviewed `C`, bind LF-only phase scripts and their manifest, and review
their exact bytes before any host effect. Reuse the established checked CLI
compiler/transport operations where their input contract fits. This procedure
does not copy the READ phase sequence or add a transport framework.

Each released phase has closed stdin, its own absent output names, native exit
status, complete bounded stdout/stderr and a finite transport deadline. Review
the retained complete receipt before the next phase. Missing/partial records
stop the window; a transport timeout is not termination evidence. Source-bound
shell glue and the inline WRITE checker must be compiled/parsed and exercised
offline against bounded fixtures before the private package is approved. The
templates below are not yet a host-ready package.

The ordered prerequisites are fresh cooperative custody and Windows ACL check,
boot/independent boot anchor, current-boot D2 verification/probe, and the exact
retained drift guard with its expected whole output. Review installed controller
equality at `C` using the existing [R15/R17-R19](M8-N4-host-runtime.md#controller-runbook-r15-r20)
and [LR8/LR9](M8-N4-launch-replacement.md#lr9-controller-replacement-after-login)
contracts. LR9 replacement is allowed only when the owner window includes it
and LR8 positively reports an installed tree with nonzero computed differences.
Absent, unknown or arbitrary refusal is HOLD. A current controller needs no
replacement. Verify exact installed equality and R19 imports on either route,
including the WRITE entry and its dependency closure at `C`.

For any controller replacement, preserve the previously reviewed R17-R20
transport constraint: write each runbook block verbatim to its own LF-only
file, verify its SHA-256 locally and on the host, copy with `scp`, and invoke
the file through strict batch SSH with plain `bash` and closed stdin. Add no
`-e`, `pipefail`, wrapper or stdin pipe. The separate controller-vars file
contains only the reviewed declaration lines; new session-phase options do
not belong there. Require the runbook's explicit completion/install/check
markers, not exit zero alone. Unexpected output stops; do not resume again
without the applicable owner decision.

No login, R6 launch replacement, checkpoint, restore, vendor upgrade or credential
inspection/copy is selected. Verify the existing installed launch artifact and
enforcing profiles using their original source/artifact pins, with staging
unavailable; do not reinterpret a controller mismatch as permission to change
the vendor launch. Precompile **and validate** the explicit withdrawal cleanup
script and its receipt checks **before activation**. Validation must include
the existing `claude_read_commands.cleanup_gate` exact withdrawal-source and
bound-package checks, using this window's real boot/generation/paths and retained
artifact bytes. A self-consistent manifest alone does not establish correct
cleanup source. Reuse that shared cleanup check without fabricating READ-phase
receipts or passing WRITE through the READ activation compiler. Keep the checked
recovery/park path ready.

## Fresh WRITE startup, withdrawal and next generation

The private package binds canonical fresh service-owned run/acquisition roots,
root-protected authorization parents and bounded capture paths. Acquisition
socket paths must satisfy the existing encoded length bound. Fixture, journal,
attempt, evidence and authority names start absent, including dangling links.
The declarations below remain placeholders; trusted installed entry arrays
`STORE`, `LANE` and `WRITE` invoke respectively `operator_store.main`,
`claude_lane.main` and `claude_write_qualification.main` through the established
`/usr/bin/python3 -I -S -B` installed-controller bootstrap.

```bash
set -Eeuo pipefail -C
umask 077
C=UNREVIEWED
EXPECTED_BOOT=UNREVIEWED
FLOOR=UNREVIEWED
GENERATION=UNREVIEWED
Q=UNREVIEWED
```

Under the existing retained-store maintenance wrapper, run once:

```bash
sudo -n "${STORE[@]}" maintain --store-root "$STORES" --key "$STORE_KEY" \
  --service "$SERVICE" --wait 0 -- "${LANE[@]}" qualify \
  --launch-config "$CONFIG" --launch-config-sha256 "$L" \
  --lane-dir "$RUN/write-qualify" --evidence "$QUAL" \
  --mode subscription --recipe write < /dev/null \
  > "$R/write-qualify.stdout" 2> "$R/write-qualify.stderr"
```

Require native zero and empty stdout/stderr. This is no-model startup, not WRITE
acceptance. The current CLI accepts `--mode subscription`; historical
`--selected-plan` examples are not its contract. Independently check this fresh
WRITE evidence using the installed host validator with explicit WRITE recipe;
the READ phase checker cannot judge the changed launch revision. A fixed trusted
checker may use the following source-bound body, with its private arguments:

```python
import sys
from pathlib import Path
sys.path.insert(0, "/opt/constructicon-m8-controller")
from constructicon.substrate.executors.claude_lane import read_configuration
from constructicon.substrate.executors.claude_host import validate_startup_evidence
from constructicon.substrate.executors.claude_native import ClaudeNativeRecipe
from constructicon.substrate.executors.claude_protocol import ClaudeAuthMode

configuration = read_configuration(Path(sys.argv[1]), expected_sha256=sys.argv[2])
if (configuration.model, configuration.effort) != ("claude-sonnet-4-6", "low"):
    raise SystemExit(1)
mode, qualification = validate_startup_evidence(
    Path(sys.argv[3]), configuration, recipe=ClaudeNativeRecipe.STREAM_JSON_WRITE,
)
if mode is not ClaudeAuthMode.SUBSCRIPTION:
    raise SystemExit(1)
print(str(qualification))
```

Require native zero, empty stderr and exactly one valid semantic digest as `Q`;
independently compare the complete evidence snapshot, its raw SHA-256 and the
source-derived semantic digest. Require affirmative matching mode/settings/hooks,
closed stdin, actual EOF, clean joined process/relay/credential cleanup and current
custody. Unknown vendor principal remains unknown. Keep the store withdrawn.

Use the existing fixed inherited-maintenance withdrawal child from the READ
procedure, bound to this package and checked offline, to affirm durable
withdrawal/current physical binding and the actual inventory `FLOOR`. Independently
review the unoccupied next generation, then use existing `publish` and `activate`
commands with that `GENERATION`, this exact `Q`, and the emitted sealed identity.
Check both conformance revisions equal `Q` and binding matches the current
physical instance. Install the exact sealed JSON at a fresh protected destination
using the existing service-readable 0600 custody law. Do not overwrite or repair.
Publication alone is not activation; require separate positive receipts.

From successful or possibly completed activation onward, every abort owes the
precompiled explicit withdrawal, including failures during fixture/mint/pins or
authority placement. Unknown lock/process ownership uses reviewed recovery,
never lock stealing, activation retry or deletion of evidence.

## Fixture, candidate, independent pins and authority placement

```bash
sudo -n -u "$SERVICE" -- "${WRITE[@]}" prepare --fixture "$RUN/fixture" \
  < /dev/null > "$R/write-fixture.json" 2> "$R/write-fixture.stderr"
sudo -n -u "$SERVICE" -- "${WRITE[@]}" mint \
  --fixture "$RUN/fixture" --launch-config "$CONFIG" --launch-config-sha256 "$L" \
  --store-root "$STORES" --store-key "$STORE_KEY" --sealed "$AUTH/sealed.json" \
  --qualification "$QUAL" --acquisition-root "$ACQ" \
  --authorization-id "$AUTHORIZATION_ID" --actor "$ACTOR" --key "$WRITE_KEY" \
  --journal "$RUN/write.sqlite" --attempt-record "$RUN/write-attempt.json" --hours 1 \
  < /dev/null > "$R/write-candidate.json" 2> "$R/write-mint.stderr"
```

Retain the complete candidate and its raw hash as preparation data. Place no
authorization file before independent comparison: any valid protected candidate
file would already be usable by `run --authorization`, regardless of its name.
The independent metadata command takes no candidate or authorization input.
Its trusted `--journal` argument is the same declared dedicated path used by
`mint`, not a path learned from candidate bytes.

```bash
sudo -n -u "$SERVICE" -- "${WRITE[@]}" pins \
  --fixture "$RUN/fixture" --launch-config "$CONFIG" --launch-config-sha256 "$L" \
  --store-root "$STORES" --store-key "$STORE_KEY" --sealed "$AUTH/sealed.json" \
  --qualification "$QUAL" --acquisition-root "$ACQ" \
  --journal "$RUN/write.sqlite" < /dev/null \
  > "$R/write-pins.json" 2> "$R/write-pins.stderr"
```

Require native zero, empty stderr and a complete JSON record of at most 8192
UTF-8 bytes. `pins` recomputes actual graph/revision/grants, workspace/gate/fixture/
report pins and `Q`, plus actual native/worker/resource launcher limits and the
fixed callback ceiling under `declared_limits`. These are declared bounds, not
usage or backend request, token or money guarantees. It opens and closes the
current binding metadata, reports
`active_binding_checked: true` and a timezone-aware check time. It launches no
model, credential, login or egress operation and reserves no attempt. Its active
check is a point-in-time metadata observation, not an exclusive store lock or
proof that later acquisition will succeed. Its provider has no qualification
authorization, remains unavailable, and cannot enroll or release a task.

Owner/root review outside `pins` compares the actual pins with the complete candidate,
source `C`, current generation/evidence, fixture/task/model/effort, grants,
dedicated journal/attempt, fixed graph/scope/binding, epoch one, actual expiry,
callback/wire/egress bounds and accepted overage exposure. Compare both raw hashes
and semantic fields; never accept a candidate merely because it echoes itself.
Only an exact match to the owner-approved window and fresh-pin derivation rules
releases the final root-owned 0640 authority placement at the absent runtime
destination `$AUTH/authorization.json`. Recheck installed bytes and every custody,
boot/drift, source, qualification, binding and time premise immediately before run.
Any deviation is HOLD; no successor key, journal or remint is selected.

## One WRITE, explicit withdrawal and closure

```bash
sudo -n -u "$SERVICE" -- "${WRITE[@]}" run \
  --fixture "$RUN/fixture" --launch-config "$CONFIG" --launch-config-sha256 "$L" \
  --store-root "$STORES" --store-key "$STORE_KEY" --sealed "$AUTH/sealed.json" \
  --qualification "$QUAL" --acquisition-root "$ACQ" \
  --authorization "$AUTH/authorization.json" < /dev/null \
  > "$R/write-report.json" 2> "$R/write-run.stderr"
```

Release this command once. Success needs native zero, empty stderr and the
complete bounded report with verdict `passed`, backed by a completed attempt,
non-base candidate, exact tested tree and journal-minted attestation, unchanged
target and all three executor/workspace/gate obligations actually closed and
released. A no-op worker, partial callback, native success text or missing
obligation is not WRITE success. Retain only emitted telemetry at its actual
scope; unobserved cost, model requests/retries or vendor identity remain unknown.

Every post-activation terminal outcome or abort runs the precompiled explicit
withdrawal child with expected floor `GENERATION`, under `maintain --wait 0`.
Require positive native zero, empty stderr and the exact `withdrawn-checked`
receipt; missing active metadata is not proof. If work or lock ownership is
uncertain, preserve custody and records for the reviewed recovery decision.
No retry, credential deletion, attempt reset or automatic new generation follows.
Finally park explicitly and independently observe Off/idle before releasing
custody. Public reporting carries finite checked facts, not private paths, host
output or transcripts. This proposal supplies no evidence that any stage ran.

## Review disposition

Adopted semantic schema/every-table/checkpoint snapshots around metadata pins
and mint, including a real journal reopen/migration path. Initial schema
creation is allowed; metadata preparation must leave existing domain rows
unchanged and create no attempt or model call. Adopted validation of the exact
retained cleanup source/package before activation, beyond compilation alone.

Rejected a protected "review-only" authorization file: any valid protected
candidate already permits the run regardless of basename, so comparison must
precede every authorization placement. Rejected an extra `SqliteJournal.close()`
duty: that API does not exist and its `_txn`/`_read` operations already close
their connections in `finally`; no persistent connection is owned here.
