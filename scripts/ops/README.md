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
sizes. SQLite opens in read-only/query-only mode without a journal constructor,
migration, recovery or checkpoint. SQLite read locks may touch its guarded shared
memory; this is not a zero-filesystem-write claim. The attempt and journal are
separate observations, not an atomic snapshot or journal-integrity attestation.

Output contains only a closed bounded vocabulary, never raw exception text,
model output, relay destinations, credentials, identities or private paths.
Missing and incomplete facts remain null/partial. A valid record means that its
observed shape and identity passed these checks, not that a run succeeded. Only
an affirmative retained `not dispatched` outcome rules out dispatch; an intent
or missing record cannot establish vendor request count or billing. Callback
settlement counts are distinct from optional worker observations.

Exit 1 can accompany structured invalid evidence: retain and inspect that JSON.
Do not discard it or treat absent diagnostics as a passing observation. The
Linux generated-chain test exercises this reader against the actual fake READ
artifacts; portable tests exercise missing, refusing and bounded publication paths.
