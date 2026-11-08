# Second fixed maintenance task: channel stored-reply extraction

Decision record for [#393](https://github.com/sushiHex/constructicon/issues/393).
The refactor itself belongs to [#327](https://github.com/sushiHex/constructicon/issues/327).
It is kept for a future model attempt and is **not** applied here. This record
defines a second closed maintenance task. It does not amend frozen plan bytes
or ADRs. The existing task keeps its wire format, instruction, exam and
acceptance meaning, although the implementation bytes that host both tasks
change on purpose. It authorizes no installation, host session, model call
or spending.

## Decision

The maintenance application gains exactly one more fixed, closed task. It
runs alongside the existing plan-manifest task:

| Task | Purpose literal | Output |
| --- | --- | --- |
| Existing | `plan-manifest-maintenance` | One absent JSON vector file, data only (unchanged) |
| New | `channel-stored-reply` | One modified Python file, an exact helper extraction |

The tasks form a fixed two-case table. Root custody selects the task through
the authorization's purpose literal. There is no registry, scheduler,
caller-selected instruction, caller-selected exam or open extension point.
This follows `M8-maintenance-entry-state-review.md`: a distinct closed
authorization, and no caller-selected task or exam. The first task's purpose,
request wire bytes, instruction, exam, acceptance proof and result meaning do
not change. An existing plan-manifest authorization must still parse to the
same model and digest.

Value, stated plainly: the target is a small, behavior-preserving cleanup of
real duplication, not a feature or a bug fix. The intended outcome is that the
application can accept a useful code change under a trusted exam. That is a
design goal until actual CI and later live evidence show it.

## Identity and installation consequences

Adding the task edits files hashed by `maintenance_application_revision()`
(`core/maintenance.py`, `api/plan_manifest_application.py`,
`api/maintenance_entry.py`, among others) and the bytes of the Codex adapter.
Both revisions therefore change, for both tasks.

- The installed C490 controller cannot run the new task. Its historical evidence
  is unchanged and stays historical.
- Before any live attempt, a new reviewed controller installation is required,
  followed by fresh N4 startup and controls and an actual WRITE-provider
  preflight. One consolidated installation should follow this task and #395.
- No C490-era pin carries over: authorization, application revision,
  `check_set_hash`, q13 or g12–g14 values do not authorize the new revision.
- Every new trusted file is listed explicitly. This covers new task, contract
  or shared-mechanics modules and the gate oracle. Each file is either added to
  the hashed source list in `maintenance_application_revision()` or pinned
  through `SOURCE_HASHES` and the gate's check set. Importing a helper does not
  bind its bytes, and no acceptance or authority helper may change under an
  unchanged application revision.
- The gate embeds the whole trusted stdlib oracle source. It pins the base
  blob and file inventory before parsing the candidate, and it imports no
  project module at runtime.

## Task definition

- **Target:** `src/constructicon/substrate/channels/in_process.py` at a base
  commit and blob pinned during preparation. Preparation refuses a base whose
  target already contains the helper, so a finished #327 removes this task's
  value instead of being re-proved.
- **Allowed change:** exactly one path, modified in place with mode 100644. The
  candidate's only parent is the base. Inside the gate program, before the
  candidate is parsed, inventory equality allows only this path to change and
  its byte size is bounded. Before the gate, only the generic Git process and
  pack ceilings apply, as for the existing task.
- **Instruction:** a fixed constant. It asks for one private method,
  `_stored_reply(self, request, request_id)`, with a fixed position and
  annotations. The method extracts the reply-port guard, the derived reply id
  and the retained lookup that `reply_for` and `acknowledge` both repeat, and
  returns the raw stored message. Both callers keep their lock scope,
  validation order, missing-request handling, `_complete_reply` call, detach
  and return unchanged. The exact fault text keeps the caller's identifier.

## Trusted gate exam

The contained gate runtime is the copied Python 3.12 standard library, with no
pytest, Pydantic or project packages. The gate check is therefore stdlib-only
and never imports the base or the candidate.

1. Read the base and candidate bytes and refuse anything over the byte bound.
   Parse the **raw bytes** with `ast.parse(bytes)`, so any encoding
   declaration is resolved exactly as Python's loader would resolve it. Whole-module
   equality (step 3) then rejects code smuggled through an encoding, for
   example a `unicode_escape` cookie that hides an assignment inside a
   comment. A file whose encoding still yields exactly the expected tree is
   not refused for its spelling. The tests cover that smuggling negative and a
   plain UTF-8 positive. The exam receipt records the actual worker
   interpreter version, not the developer's.
2. Build the expected module from the base AST with one closed rewrite:
   - in each caller, replace the exact three-statement block with one
     assignment from `self._stored_reply(request, <caller id>)`;
   - insert the fixed helper at its fixed position.

   Refuse if the base lacks the exact block in both callers, or already defines
   the helper.
3. Accept only if `ast.dump(candidate)` equals `ast.dump(expected)` for the
   **whole module**, without attributes. Both are built in the same worker
   interpreter. Comparing selected method bodies is not enough: class
   decorators, defaults, new class attributes and module edits must also match.

This rejects a no-op, an unused helper, an extra or reordered edit, and a
changed fault text. It proves this one exact extraction. It does not prove
general semantic equivalence.

## Acceptance proof

The proof reuses the existing generic machinery: contained capture, the
contained gate, the journal attestation and the sole-base-parent check. On top
of that, the task requires:
- `diff-tree` is exactly one `M` record, 100644 to 100644, at the target path;
- the attestation names the new check and its `check_set_hash`.

The result model is the new task's own. Its stored result never reuses the
plan-manifest result type or meaning.

## Host-side calibration evidence

These checks run in CI and are not live gate authority:
- the existing shared channel contract tests;
- a differential fault battery run against the base and a fixture candidate in
  separate fresh interpreters.

The battery covers:
- absent request, no reply, and a valid reply with detach;
- acknowledgement new, replay and conflict;
- a reply id as input, a forged pointer, and a torn reply with ack indexes
  removed;
- competing faults: history plus a bad request, a request proof plus a missing
  port, and a torn reply plus a conflicting ack.

It compares results, exception type and exact text, acknowledgement and
revision state, and lock scope. The fixture candidate lives in test data; the
target file stays unrefactored.

## Exception boundaries

- **Wrong purpose.** A plan-manifest authorization never admits the new task,
  and the reverse also holds. The mismatch is refused by name before RunHost
  startup.
- **Resume across revisions.** A retained run resumes only under the same
  purpose and the exact application revision it was admitted under. A run from
  an older revision is refused, not recovered by the new controller.
- **Old pins.** No earlier authorization, check set or live pin authorizes the
  new revision. A fresh preparation and authorization are required.
- **Asynchronous resume.** Recovery follows the existing contracts: a
  committed writer checkpoint never redispatches the writer, and an uncertain
  dispatch never grants a new identity or retry.

## Not decided here

The live task pins, base commit, model, budget and cost exposure, and the
installation procedure all need their own explicit decisions.
