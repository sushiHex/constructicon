# Claude READ operator tooling

`claude_read_session.py` is the versioned entry point for the existing bounded
Claude READ procedure. It compiles, transports, reads back, or checks **one
explicit phase**. It neither starts a VM nor selects a successor, retries an
operation, creates a login, or grants model-call authority.

The operator-tool content revision and the installed controller commit are
different inputs. An operator-only change does not require reinstalling an
unchanged controller. Phase packages bind both revisions, the exact private
bindings, script bytes, phase, boot and target-specific grant.

## Commands

For a new bounded READ window, use `claude_read_window.py` to compose these
same phase operations. It retains the checked prefix, derives late bindings
from the canonical receipts, and prepares withdrawal before activation. Each
`advance` still requires an independently reviewed, phase-specific grant;
the entry does not manufacture approvals or automatically release successors.

```bash
python -I -B scripts/ops/claude_read_window.py describe < /dev/null

python -I -B scripts/ops/claude_read_window.py create \
  --bindings PRIVATE_INITIAL_BINDINGS_JSON --evidence PRIVATE_EVIDENCE_DIR \
  --work FRESH_PRIVATE_WINDOW_DIR --operator-revision REVIEWED_OPERATOR_REVISION \
  --target OPERATOR_AT_ADDRESS --alias CHECKED_ALIAS \
  --owner-approval-sha256 INDEPENDENTLY_APPROVED_SHA256 < /dev/null

python -I -B scripts/ops/claude_read_window.py prepare \
  --work PRIVATE_WINDOW_DIR < /dev/null

python -I -B scripts/ops/claude_read_window.py advance \
  --work PRIVATE_WINDOW_DIR --grant PRIVATE_PHASE_GRANT_JSON \
  --grant-sha256 REVIEWED_PHASE_GRANT_SHA256 < /dev/null
```

`prepare` returns the exact package, manifest and required checks. Review the
complete evidence before supplying the next grant. `advance` spends an exclusive
phase claim before transport; failed or interrupted phases cannot be retried.
The claim records possible dispatch, not successful completion. A checked result
requires every declared external operation and canonical receipt to complete.
Existing source, boot, custody, drift, scope and cost decisions remain prerequisites.

After an activation claim, `prepare --cleanup` and `advance --cleanup` select
the already prepared withdrawal package, with its own reviewed grant. This path
remains available after a later refusal; it never recompiles recovery from damaged
later evidence. An uncertain withdrawal requires the existing recovery procedure.
No local success marker proves remote process termination or host idleness.

The window executes only its phase's exact declared SSH/SCP operations. Unknown
commands, altered interpreter/transport arguments and repeated operations refuse;
there is no fixture environment switch that falls back to native execution.
Credential-free CLI tests substitute the external boundary under a process-spawn
denial hook and retain affirmative substitution records. This test guard is not
a production containment boundary. The Linux rehearsal uses the same composition
against its disposable foundation.

VM custody, start, address discovery, park and final idle observation remain the
existing separately reviewed host operations. They are deliberately outside this
entry and cannot be invoked through its external boundary. Do not wrap those
operations into an untested private sequencer. This tooling supplies no permission
to resume a stopped window, change controller/runtime pins or make another READ.

The `pre-reload-inventory` phase is **mutating maintenance**, not a read-only
listing: it durably withdraws the active binding and performs the existing
conditional boot-anchor repair under the retained maintenance lock. Its own
bounded outputs must positively establish withdrawal and a descriptor generation
of at least one before RELOAD can compile. Post-qualification `inventory` still
owns the generation used for publication; the two observations are distinct.

Use a reviewed checkout and its project environment. Run commands with closed
stdin. These examples contain placeholders; they are not a host-ready session.

```bash
python -I -B scripts/ops/claude_read_session.py describe < /dev/null

python -I -B scripts/ops/claude_read_session.py compile \
  --phase PHASE --bindings PRIVATE_BINDINGS_JSON --evidence PRIVATE_EVIDENCE_DIR \
  --out FRESH_PACKAGE_DIR --operator-revision REVIEWED_OPERATOR_REVISION < /dev/null

python -I -B scripts/ops/claude_read_session.py transport \
  --package PACKAGE_DIR --manifest PACKAGE_SHA256 \
  --operator-revision REVIEWED_OPERATOR_REVISION --evidence PRIVATE_EVIDENCE_DIR \
  --captures PRIVATE_CAPTURE_DIR --target OPERATOR_AT_ADDRESS --alias CHECKED_ALIAS \
  --grant PRIVATE_GRANT_JSON --grant-sha256 REVIEWED_GRANT_SHA256 < /dev/null

python -I -B scripts/ops/claude_read_session.py readback \
  --package PACKAGE_DIR --manifest PACKAGE_SHA256 \
  --operator-revision REVIEWED_OPERATOR_REVISION --evidence PRIVATE_EVIDENCE_DIR \
  --captures PRIVATE_CAPTURE_DIR --target OPERATOR_AT_ADDRESS --alias CHECKED_ALIAS \
  --part DECLARED_READBACK_NAME < /dev/null

python -I -B scripts/ops/claude_read_session.py check \
  --package PACKAGE_DIR --manifest PACKAGE_SHA256 \
  --operator-revision REVIEWED_OPERATOR_REVISION --evidence PRIVATE_EVIDENCE_DIR \
  < /dev/null
```

`describe` publishes the content revision, fixed phase names, named manual
checks and permitted readbacks. Bindings contain the controller/launch/D2
source identities, checked helper/checker/drift pins, selected compatible Pro
or Max plan, fresh namespace and private paths, and measured late pins. Keep
the bindings, owner decision, target, grants and captures outside the repository.
Do not place credentials or raw vendor transcripts in any of these inputs.

A phase's command and exact output contract are selected together. Callers
cannot supply an alternative success marker. Collect its declared readbacks
and check the retained result before releasing dependent work. A successful
transport exit means native completion, not permission to skip the remaining
receipt, actual-pin or owner checks. Failed native transport returns nonzero
while retaining its status and bounded captures.

## Local preparation

Use `prepare-bindings` with a trusted installation-only JSON and one fresh
namespace. `describe` lists its exact fields. Installation inputs carry the
independently checked controller, launch, checker and drift identities, operator
home, actor and selected compatible plan. They contain no old session roots,
qualification, generation or authority. The preparer derives R (the fresh
operator evidence workspace), RUN, AUTH, ACQ, QUAL, the idempotency key and
authorization ID. R is never the operator-store directory.

```bash
python -I -B scripts/ops/claude_read_session.py prepare-bindings   --installation PRIVATE_INSTALLATION_JSON --namespace FRESH_NAMESPACE   --out FRESH_BINDINGS_JSON --operator-revision REVIEWED_OPERATOR_REVISION   < /dev/null
```

Omitting `--boot` preserves `UNREVIEWED`; it does not qualify a host or certify
path absence. After measuring the actual boot in the separately approved
session, repeat preparation with the same installation and namespace plus
`--boot MEASURED_BOOT_UUID`, writing a different fresh bindings file. Physical
absence and custody remain the existing host gates. No output is overwritten.

After explicitly checking one completed phase and collecting all its declared
readbacks, derive only that phase's late bindings:

```bash
python -I -B scripts/ops/claude_read_session.py prepare-late   --phase COMPLETED_PHASE --bindings PRIVATE_BINDINGS_JSON   --evidence PRIVATE_EVIDENCE_DIR --out FRESH_BINDINGS_JSON   --operator-revision REVIEWED_OPERATOR_REVISION < /dev/null
```

Supported phases are `qualify-check`, `inventory`, `publish`, `mint` and
`candidate-pins`. Qualification uses `checker.stdout`, never a phase-success
marker; generation comes from the checked inventory. Later digests bind the
canonical retained seal and candidate. The `candidate-pins` action additionally
requires `--owner-approval PRIVATE_EVIDENCE_DIR/owner-approval.json` and
`--owner-approval-sha256 INDEPENDENTLY_APPROVED_SHA256`. Supply the existing
explicit decision artifact; preparation never writes one or treats a freshly
computed file digest as owner approval. Phase grants remain separate inputs.

Before activation, prepare withdrawal at its canonical location:

```bash
python -I -B scripts/ops/claude_read_session.py prepare-cleanup   --bindings PRIVATE_BINDINGS_JSON --evidence PRIVATE_EVIDENCE_DIR   --operator-revision REVIEWED_OPERATOR_REVISION < /dev/null
```

This builds only `PRIVATE_EVIDENCE_DIR/cleanup-package`. Each preparation action
is local and returns without transport, choosing a successor, granting work or
changing the installed controller. Local operator and metadata source digests
change with this tooling; installed controller identity remains independent.
Retain both accurately instead of claiming a new local tree equals an older
installed tree. Prior phase receipts retain their original operator revision and cannot satisfy
a new revision's phase gates. Do not resume across revisions or relabel old receipts.

## Execution and recovery

The source references the existing repository procedure fences through
`m8_procedure_package`; it introduces no second runbook language. Current
source and actual fresh facts must match the separately approved session.
Never add a remote-command wrapper after freezing that source. A missing step
is an offline tooling defect, not permission to invent a command during a run.

Prepare the generation-bound `withdraw-after` package before activation.
Activation retains its may-have-completed duty before possible dispatch. Every
later abort carries that duty, including failures before mint or READ. Unknown
remote outcome or lock ownership requires the reviewed recovery disposition;
absence of a file is not proof of withdrawal. Preserve the interrupted prefix,
never replace a journal/key/attempt or retry to obtain a passing result.

## Evidence boundaries

Portable tests cover actual isolated entry, immutable packages and grants,
phase-specific receipt contracts, transport failure propagation and refusal
paths. They do not establish execution of the complete generated Bash chain.

`test_claude_read_linux_rehearsal.py` executes that chain in the disposable
foundation fixture, using actual generated scripts, real controller/store/lane
commands and the existing compiled harmless protocol peer. Actual outputs and
readbacks feed subsequent checks. SSH/SCP are replaced at their process
boundary by local execution/copy; the host drift baseline is a measured
test-scoped platform double. This is not an SSH-network, private-host drift,
vendor-conformance or subscription-availability proof. The Linux cases count
only when the required hosted step actually executes them.

Live use retains its separate custody, host, qualification, exact authorization,
one-attempt budget, cleanup and owner-decision requirements. The runtime remains
unavailable merely because the operator tests pass.

## Retained READ evidence

`read_attempt_evidence.py` is a standalone standard-library reader for the two
fixed artifacts `read-attempt.json` and `read.sqlite` in a private run directory.
It runs as `m8-service`, never root, using previously checked authorization and
run identities:

```bash
/usr/bin/python3 -I -S -B read_attempt_evidence.py \
  --run-root PRIVATE_RUN_ROOT --authorization-id CHECKED_AUTHORIZATION_ID \
  --run-id CHECKED_RUN_ID --max-epoch 1 < /dev/null
```

This interface example is not a host-ready command package. Any later host
collection needs a separately reviewed source-hash-bound transport and fresh
custody/boot checks. It grants no installation, acquisition, retry or model-call
authority. It does not extend an expired READ authorization.

The reader checks private ownership, modes, stable file identities and bounded
sizes. The root must be service-owned `0700`. Attempt records require `0600`;
SQLite files may add read bits inside that private directory, while non-owner
write, execute and special bits still refuse. The reader does not chmod evidence.
SQLite opens in read-only/query-only mode without a journal constructor,
migration, recovery or checkpoint. SQLite read locks may touch its guarded shared
memory; this is not a zero-filesystem-write claim. The attempt and journal are
separate observations, not an atomic snapshot or journal-integrity attestation.

Output contains only a closed bounded vocabulary, never raw exception text,
model output, relay destinations, credentials, identities or private paths.
Contextual refusals retain fixed family, receive-phase and predicate labels
plus terminal-result acceptance separately from callback counts. Historical
flat refusals stay readable. Up to 64 contextual events fit the shared 32 KiB
metadata capture/validation bound; no arbitrary vendor subtype is exposed.
Missing and incomplete facts remain null/partial. A valid record means that its
observed shape and identity passed these checks, not that a run succeeded. Only
an affirmative retained `not dispatched` outcome rules out dispatch; an intent
or missing record cannot establish vendor request count or billing. Callback
settlement counts are distinct from optional worker observations.

Exit 1 can accompany structured invalid evidence: retain and inspect that JSON.
Do not discard it or treat absent diagnostics as a passing observation. The
Linux generated-chain test exercises this reader against the actual fake READ
artifacts; portable tests exercise missing, refusing and bounded publication paths.

## Metadata-only session

`read_metadata_session.py` compiles, transports or checks one fixed collection.
It shares the READ entry's existing private staging, SSH/SCP arguments and
closed-stdin capture boundary. There is no successor, retry, VM operation,
installation, store acquisition, login or vendor/model execution.

```bash
python -I -B scripts/ops/read_metadata_session.py describe < /dev/null

python -I -B scripts/ops/read_metadata_session.py compile \
  --request PRIVATE_REQUEST_JSON --history PRIVATE_HISTORY_DIR \
  --out FRESH_PACKAGE_DIR --revision REVIEWED_SOURCE_REVISION < /dev/null

python -I -B scripts/ops/read_metadata_session.py transport \
  --package PACKAGE_DIR --manifest PACKAGE_SHA256 \
  --history PRIVATE_HISTORY_DIR --captures FRESH_PRIVATE_CAPTURE_DIR \
  --revision REVIEWED_SOURCE_REVISION < /dev/null

python -I -B scripts/ops/read_metadata_session.py check \
  --package PACKAGE_DIR --manifest PACKAGE_SHA256 \
  --history PRIVATE_HISTORY_DIR --captures PRIVATE_CAPTURE_DIR \
  --revision REVIEWED_SOURCE_REVISION < /dev/null
```

The private history contains exact `read-context.json`, `bindings.json` and
`authorization-candidate.json` bytes. The request binds their hashes and checks
the original boot, controller, run directory, authorization and derived run ID.
These are historical lookup identities. Expiry and model grants are not reused
as present authority. The independent `fresh` context binds the observed boot,
SSH target/alias, fresh namespace and previously owner-approved drift inputs.
Custody and address discovery remain measured operator prerequisites; no JSON
boolean manufactures approval.

The generated command checks the current boot and reuses the reviewed G1 drift
guard, separating its exact marker from collector JSON. It invokes only the
fixed reader as `m8-service` with isolated system Python and closed stdin. Source
travels as a safely quoted `-c` argument: service access to the operator's private
staging directory is not widened. This standalone inspection does not run or
qualify the installed controller. Drift retains its declared coverage limits.

`check` validates the package, request, capture context, actual process completion
and closed bounded observation. A completed reader exit1 retains invalid/partial
facts and returns `collection_checked: false`; timeout, SSH failure or absent
output cannot pass. `collection_checked: true` confirms the inspection and
projection checks only. Missing or partial records remain unknown and cannot
authorize another attempt or establish model execution, request count or billing.

Keep all requests, history, packages, custody observations and captures private.
Use a Git-byte-exact source image and explicitly select its measured revision;
Windows checkout line endings are not interchangeable with reviewed Git bytes.
Live use requires the bounded owner-selected window and fresh custody/boot/drift
checks. Unexpected output stops collection; retain the prefix and park without
retry. This metadata window carries no model-call authority.
