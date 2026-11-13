# Second fixed maintenance task: channel stored-reply delivery

Delivery record for the [decision record](maintenance-channel-reply-task.md).
Refs [#393](https://github.com/sushiHex/constructicon/issues/393). The
refactor itself stays with #327: `src/constructicon/substrate/channels/in_process.py`
is unchanged here. This record authorizes no installation, host session, model
call or spending.

## Review history

- Root's narrow authority and design review of the decision record passed at
  `f682bd59`, with two non-blocking wording fixes. Both were applied in
  `180b597`, the decision record's committed bytes.
- Terra's independent behavior and value review found a modest gain: real,
  small duplication, not a feature. It asked the task to preserve:
  - the distinction between a missing request and a missing reply;
  - history validation first, under the one nonreentrant lock;
  - the order request proof, port guard, derived lookup, `_complete_reply`;
  - the acknowledgement path's reply check before its claim;
  - `reply_for`'s detached return.

  Terra also observed that behavior alone admits a no-op, and structure alone
  admits an unused-helper fake. The exam therefore requires the exact tree,
  while the calibration battery checks behavior.

## What was built

- **Two closed tasks.** `core/maintenance.py` adds `ChannelReplyRequest`,
  `ChannelReplyResult` and `ChannelReplyAttemptAuthorization`. A private
  shared base, `_AttemptAuthorization`, carries the existing exact-attempt law:
  epoch, WRITE grant shape, admission and acquisition faults. Each subclass
  narrows `purpose` and `request`. A redeclared field keeps its position, so
  the plan-manifest wire is unchanged. A golden captured from `b0d2c0b`'s
  source checks this: the same model, field order, canonical digest, run id and
  JSON schema (`tests/core/test_maintenance_channel_authorization.py`).
- **The task table.** `api/plan_manifest_application.py` holds exactly two
  `MaintenanceTask` rows, selected by the exact request type. The rows share
  only the following mechanics:
  - the writer and checker bodies, with their unchanged guard text and
    refusal messages;
  - resource custody;
  - the gate, attestation and sole-parent proof.

  The table has no registry. Preparation selects the task with a closed
  `--task` choice, and the pinned source set names it again. Assembly and
  `require_maintenance_attempt` refuse an authorization of the other type by
  name, before RunHost startup.
- **Fixed instruction.** It quotes the oracle's helper source verbatim. The
  helper is `_stored_reply(self, request: ChannelMessage, request_id: Digest) ->
  ChannelMessage | None`. It has no docstring and is placed immediately after
  `_complete_message`, as the class's last method. It returns the raw retained
  message, and its fault text interpolates the caller's identifier as
  `request_id`. The two call sites are `stored = self._stored_reply(request, request_id)`
  and `reply = self._stored_reply(request, message_id)`.
- **Gate oracle.** `substrate/gates/channel_reply.py` uses the standard library
  only. It applies a 65536-byte bound, parses raw bytes with `ast.parse`, and
  applies one closed rewrite of the base. It accepts only if the whole-module
  `ast.dump(..., include_attributes=False)` is equal. It refuses a base that
  already defines or references the helper, or that lacks the exact block in
  either caller. The check program embeds the whole oracle source and the base
  bytes. Before the candidate is parsed, it pins:
  - the base blob's digest;
  - every other path's mode and blob;
  - the target as a regular 100644 file within the bound.

  Its receipt records the worker's `sys.version`.
- **Acceptance.** The existing proof is shared: journal, manifest, attestation
  and sole base parent. The channel task also requires:
  - `diff-tree` to be exactly one `M` record, 100644 to 100644, at the target;
  - the attestation to name `channel-stored-reply-exact-extraction` under the
    request's `check_set_hash`.

  The stored result has its own `purpose`, and the inspector reports it.
- **Identity.** `substrate/gates/channel_reply.py` is added explicitly to the
  `maintenance_application_revision()` source list. The check set embeds it
  too. Both revisions therefore change for both tasks. Preparation refuses a
  channel base whose target already contains the helper.
- **Diagnostic.** `maintenance_diagnostic.py` gains a closed two-entry table
  keyed by graph name, holding purpose, request, result and check name. An
  attempt purpose must name exactly one row, and a channel stored result must
  carry its purpose. The journal, attempt, pending attempt and result each
  name their task, and a snapshot whose sections name two tasks is refused at
  the `task` stage. Each section alone would otherwise validate. Its new
  reviewed bytes are pinned here, beside the earlier eras' unchanged pins:

```text
CHANNEL_DIAGNOSTIC_SHA256=f202f8b9ea48baedd1ca66f8bdd9e9ed4258dbfe066801f9a35fed1a620ea2ba
```

  The diagnostic later gained the attempt's `content_digests` projection (#407):
  digests and lengths of each callback program, its output and the reply. That
  pin stays as written, and the bytes with the projection are pinned beside it:

```text
CONTENT_DIGESTS_DIAGNOSTIC_SHA256=28a2c47d0b3199131d626181dd8da6b1a467efe2c432428b6c40fbab88781a77
```

- **Result packet.** `api/maintenance_report.py` (#394) reads the run's retained
  graph and selects the matching row of the diagnostic's table. That row
  provides the request model, the checker and lease scopes, and the result
  fields. A channel packet reports `base_sha256` and `candidate_sha256` in
  place of the plan task's `input_sha256` and `render_sha256`. Every packet now
  names its `purpose`. A stored result naming another task than the journal is
  refused, and a diagnostic `task` refusal is passed through by name.

## Evidence

Credential-free and fake-first. The positive candidate is a hand-written
refactor kept as test data
(`tests/fixtures/channel_stored_reply/in_process_candidate.py.txt`). It is never
generated by the oracle's expected-tree builder.

- The real entry, Graph, capture, contained gate, journal and published result
  accept it. Two writers are tested: the genuine L0 writer double, and the real
  Codex adapter with a scripted native callback. A committed writer checkpoint
  recovers the checker without a second acquisition.
- Whole-module refusals include:
  - a no-op, an unused helper, one caller only, or an extra edit elsewhere;
  - changed fault text or fault identifier;
  - a reordered statement, or the call moved outside `with self._lock`;
  - a wrong helper name, position, annotation, docstring or decorator;
  - an added class decorator, a changed default, or a new class attribute;
  - a duplicate class, or a module-level edit;
  - `unicode_escape` smuggling.

  At the program level, a second, changed or removed file is refused. A mode
  change is refused on POSIX; that case is skipped on Windows.
- Calibration, which is CI evidence and not gate authority, runs base and
  candidate in separate fresh `-I` interpreters. It compares results, exact
  exception type and text, acknowledgement and revision state, and the lock
  depth of every retained-index lookup. The battery covers the record's
  scenarios. A control candidate that skips the torn-reply proof is
  distinguished.

## Limits

- **Size bounds sit inside the gate, as for the plan-manifest task.** The
  decision record first said byte and diff size are bounded before the gate
  runs. Neither graph node holds the authority, so no task-level check can
  precede `gate.verify()`. Before that point, only the generic Git process and
  pack ceilings bound the export. Inside the gate program and before any parse,
  two checks apply: inventory equality allows exactly one changed path, and the
  target is bounded to 65536 bytes. Together they bound the diff. Acceptance
  then requires exactly one `M` record. The plan-manifest task has the same
  arrangement with its 32768-byte bound. The decision record now says this.

- The port guard (`pins no reply port`) cannot be reached through coherent
  damage. Either the request's intent proof or the message model's own
  validator refuses first. Its fault text is proved by the exam's tree
  equality, not by the battery.
- A pydantic `model_copy` with a foreign request object is serialized through
  the declared field type, so revalidation projects it. This predates the
  change for the plan-manifest type. Assembly still compares the revalidated
  request with the actual assembled one.
- No Linux contained-gate run, host installation, Python 3.12 worker or live
  model attempt is claimed. The exam proves one exact extraction, not general
  semantic equivalence.
