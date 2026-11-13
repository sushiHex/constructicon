# Refusal code — the guard that fired, carried to the operator

**Status:** proposal, 2026-11-12. Not accepted; nothing here is implemented or
authorized. Source references are to `main` at `c9f0c84`. It changes no
invariant and loosens no guard. One independent review pass is recorded at the
end. It withdrew three parts of the first draft, and this version is smaller
for it.

## The problem

The rule is: name the refusal, verify at the producer. The producers do. Each
guard knows exactly why it refused. The name does not survive the trip up.

**The cause is computed, then discarded, at each hop.**

| Where | Goes in | Comes out |
| --- | --- | --- |
| `substrate/executors/codex.py:964-966` | any exception from the callback: worker did not complete, invalid UTF-8, tool output over its bound | `the contained callback failed (<exception type>)` |
| `codex.py:2117-2123` | either exit non-zero, timeout, launcher bound | one sentence: "did not complete" |
| `codex.py:2149-2162`, then `codex_protocol.py:460` | the worker category is decided before the 32,768-byte tool bound is checked | worker `success`, and a refused callback, with no link |
| `codex_protocol.py:1671-1689` | every fault routed here: call ceiling, repeated ids, account, spend | `kind="unavailable"` and joined prose |
| `substrate/journal/maintenance_diagnostic.py:184-188` | that prose, read back from the attempt record | `failure_kind`, one of four, by prefix match |
| `api/plan_manifest_application.py:147-148` | any executor failure or partial | `writer-not-positive` |
| `plan_manifest_application.py:186-190` | a failed check, a missing subject, four subject mismatches | `gate-not-positive` |
| `substrate/gates/contained.py:369-383` | the exam's asserts and the oracle's closed code, as traceback text | an unstructured `detail`; the check is `failed` |
| `maintenance_diagnostic.py:336-339` | each check's detail | name and status only |
| `api/maintenance_report.py:283-289` | up to eight failures on each node | the first failure of the first failing node |
| `substrate/executors/claude_provider.py:322-331` | ten permit faults and the grant faults | `Claude READ qualification acquisition refused` |
| `substrate/executors/claude_read.py:993-995`, `:1002`, `:1032-1033` | call ceiling, wrong method, state, shape or tool, output over its limit | `mcp-call` |
| `substrate/executors/claude_read_worker.py:207-216` | non-zero exit, timeout, bound, oversized or mistyped output | `worker process refused` |

The Claude worker's refusal then loses even that. It is re-raised
(`claude_read.py:1051`), wrapped by the launcher, and rejected as evidence
because its cause is not the adapter's own refusal type (`claude_read.py:272-279`).
The outcome is a bare `Claude READ refused` (`claude_read.py:1307`).

**English is the wire format.** The walker records a failure as
`{"error": str(exc), "error_type": ...}` (`runtime/walker.py:1800`, `:1834`).
The diagnostic recovers the cause by exact match on that sentence
(`_FAILURES`, `maintenance_diagnostic.py:67-79`, used at `:302`).
`scripts/check_m8_mutations.py:38-69` pins the same sentences again.

**The copies have drifted.** `_FAILURES` maps "maintenance capture differs from
the requested candidate" to `capture-mismatch`
(`maintenance_diagnostic.py:71`). No production code raises that sentence.
Only a test fixture writes it
(`tests/substrate/journal/test_maintenance_diagnostic.py:146`).

`core/errors.py:1` says "One error taxonomy". There is one hierarchy of
exception types. For *why a guard refused* there are several closed
vocabularies that do not compose.

## The design

**A refusal code names the guard that fired. It is chosen at that guard from
one closed set, and recorded once, in the event the walker already seals.**

Admission already works this way. `AdmissionFault` carries an `AdmissionCode`
such as `graph.grant.widening` beside its message (`core/admission.py:32-63`).
This design gives a run's refusals the same treatment, the same dotted grammar
and the same home.

```python
# core/refusal.py
class RefusalCode(StrEnum):            # one enum; the whole closed set
    PERMIT_RUN = "permit.run"
    ...
    WRITER_NOT_POSITIVE = "writer.not_positive"
    CAPTURE_UNCHANGED = "capture.unchanged"
    CALLBACK_WORKER_NONZERO = "callback.worker.nonzero"
    ...

# core/errors.py
class ContractViolation(ConstructiconError):
    def __init__(self, message, *, refusal: Sequence[RefusalCode] = ()): ...
    refusal: tuple[RefusalCode, ...]   # members only; at most twelve
```

- **One enum in L0, not a base with families.** Every layer can then type,
  decode and check a code, and the set cannot be extended from outside. This
  is `AdmissionCode`'s pattern exactly.
- **`refusal` is an ordered list of the guard's own closed reasons**, most
  general first. It is not a causal claim. A writer that refuses because a
  callback's worker exited non-zero records
  `[writer.not_positive, callback.worker.nonzero]`. An acquisition refused for
  three permit faults records those three.
- **The walker writes it.** Both `NodeFailed` sites, and the cleanup branch
  using the *original* node error (`walker.py:1791-1801`), add
  `"refusal": [...]` when the recorded exception carries one. Otherwise the
  payload is today's two keys, byte for byte.
- **Nothing is mined.** A code is recorded only when the recorded exception is
  itself a `ContractViolation` that carries it. An exception group, a wrapping
  error or a cancellation records none. That is the evidentiary rule the
  Claude adapter already applies (`claude_read.py:272-279`).
- **`AdmissionError` is untouched.** It keeps its own typed faults. The
  attribute lives on `ContractViolation` only, so an admission refusal is
  never presented as an uncoded one.

One sealed event then holds the answer:

```json
{"error": "maintenance writer did not positively succeed",
 "error_type": "ContractViolation",
 "refusal": ["writer.not_positive", "callback.worker.nonzero"]}
```

### The code set comes from producer sites

A code exists only where a guard exists. The set covers the vendor-neutral
guards on the live WRITE path. An inventory test must tie each member to its
raise site, in the style of the existing mutation checkers.

| Prefix | Codes | Producer sites |
| --- | --- | --- |
| `permit` | `run`, `invocation`, `binding`, `source_graph`, `capability`, `revision`, `operator_binding`, `grants`, `epoch`, `expired` | `core/qualification.py:160-172`, `core/maintenance.py:176-188`, `codex.py:1775-1782`; see [RUN_PERMIT.md](RUN_PERMIT.md) |
| `writer` | `workspace`, `base`, `not_positive` | `plan_manifest_application.py:139`, `:142`, `:148` |
| `capture` | `return`, `unchanged`, `repository`, `paths`, `base` | `plan_manifest_application.py:152-160` |
| `checker` | `input` | `plan_manifest_application.py:183` |
| `gate` | `not_positive`, `subject` | `plan_manifest_application.py:186-190`, split by which condition held |
| `callback` | `order`, `not_open`, `malformed`, `repeated_id`, `call_ceiling`, `deadline`, `unanswered`, `program_bound`, `tool_output_bound` | `codex.py:897-949`, `:1126-1127`, `:1405`; `codex_protocol.py:446`, `:460` |
| `callback.worker` | `nonzero`, `timeout`, `output_bound`, `incomplete`, `invalid_utf8` | `codex.py:2117-2127`; the five non-success values of `WorkerResultCategory` |

That is thirty-five codes. The `callback` codes are vendor-neutral: they name
the mediated-callback contract of ADR 0020, which both adapters implement.

Left out on purpose:

- **Vendor protocol refusals.** Claude's 39 codes and Codex's roughly forty
  conversation refusals describe a vendor's wire. Claude's also carry family,
  phase and predicate context (`claude_read.py:203-258`) that one code would
  lose. They stay in their adapters, typed as they are.
- **`capture-mismatch`.** It has no producer.
- **The exam's inner reasons.** See "What this does not split" below.

### What happens to the existing vocabularies

| Vocabulary | After |
| --- | --- |
| `_FAILURES`, sentence to cause, 11 entries | **Retired** as a mechanism. It stays only as the reader for events written before codes. Substrate stops restating application sentences. |
| The two permit refusal prefixes, 10 sentences each | **Named** by the ten `permit` codes. The sentences stay as the message. |
| `WorkerResultCategory`, 6 values | **Stays.** It is an observation of the worker. Its five non-success values map one to one onto `callback.worker` codes, and one function decides both. Worker `success` beside `callback.tool_output_bound` is then two true facts with a visible link. |
| `ExecutorError.kind`, 4 values | **Stays.** It is the coarse class at the executor seam. |
| `failure_kind` by prefix match | **Stays for now.** Its source is the prose in the persisted attempt record. Retiring it needs `kind` recorded as its own fact there, which belongs with PR #410's change to that record. |
| `ClaudeReadRefusalCode`, `ExtractionRefusal.code`, `WriteReportIssue`, diagnostic and preflight stages | **Stay, untouched.** A vendor's protocol, an exam's verdict, a reader's findings about records, and where a reader stopped. None is a guard on the live path refusing an action. |

One mechanism is deleted, one set of sentences gets names, and the rest stay
because they answer a different question. One enum is introduced, on a pattern
the repository already has.

### A code names a guard. It does not classify behaviour.

`capture-unchanged` covers three different model behaviours: no tool call, a
read with no write, and a rewrite that changed nothing. The design
deliberately keeps **one** code for them. One guard fired, at
`plan_manifest_application.py:154`, and it saw one fact: the captured tree
equals the base. Splitting the code by what the model "must have done" would
be inference recorded as fact, which I4 forbids.

What separates the three is evidence, and that is what PR #410's digests are
for. Codes answer *which guard*. Observations answer *what happened*.

### What the operator reads

After this design and PR #410:

| Observed today | `refusal` | Observations that finish the answer |
| --- | --- | --- |
| `capture-unchanged`, model made no call | `capture.unchanged` | 0 callbacks admitted; a reply digest and length |
| `capture-unchanged`, model only read | `capture.unchanged` | 1 callback, worker `success`; a small program; an output about the size of the target |
| `capture-unchanged`, model rewrote nothing | `capture.unchanged` | callbacks completed; a larger program; a small output |
| `writer-not-positive`, a call raised | `writer.not_positive`, `callback.worker.nonzero` | worker `nonzero` |
| `writer-not-positive`, a call printed too much | `writer.not_positive`, `callback.tool_output_bound` | worker `success`; output length over 32,768 |
| `writer-not-positive`, a ninth call | `writer.not_positive`, `callback.call_ceiling` | 8 started, 8 completed |
| `gate-not-positive`, an extra file | `gate.not_positive` | the failed check's name and status, as today |
| `gate-not-positive`, a wrong edit | `gate.not_positive` | the failed check's name and status, as today |

### What this does not split

- **A read and a no-op rewrite are separated only by sizes.** That is the
  reader's inference. A positive answer needs a per-callback "tree changed"
  observation, which belongs with PR #410's record.
- **The two `gate-not-positive` shapes stay one.** The tree inventory and the
  exact extraction are one check program, so both fail the same named check.
  The first draft added a code to `CheckResult`; that is withdrawn (see the
  review record). The clean way to separate them uses a carrier that already
  exists: make the exam two named checks, inventory and extraction. Check name
  and status already reach the report (`maintenance_diagnostic.py:336-339`).
  That changes the exam, so it is an owner question, not part of this design.

### Confidentiality

- **The set is one enum in source.** A code cannot be a string that is not a
  member: the constructor checks membership, and the type is closed.
- **No text enters.** There is no interpolation and no free-text field.
- **A sealed value was a member when written.** The walker writes only what
  the exception carried, and the event is sealed. Readers still decode through
  the enum and print `unknown` otherwise, on every surface that prints one.
- **What it reveals is which trusted branch ran**, in what order, and how many
  reasons there were. The alphabet is public source. That bounds the channel;
  it does not make it zero.

Raw event surfaces already publish `NodeFailed` payloads, including the
free-text `error` (`api/_control_queries.py:261`, `api/detail.py:561`,
`substrate/journal/projection.py:83`). The code will appear there too. It is
the more bounded of the two fields.

### Codes never select policy

**No decision depends on a recorded code.** Guards decide; codes describe.
The design keeps codes out of every value that is compared or hashed for
authority: they are not in check results, attestations, subjects or
manifests. The rule is tested by behaviour, not by scanning source: paired
runs that differ only in whether the failing guard is coded must end in the
same status, the same checkpoints and the same attestations.

### Eras and readers

**No new era or schema version is needed for the event key.** The reason is
specific to this event:

- the journal's projector for an ordinary event requires a JSON object and
  constrains no `NodeFailed` shape (`substrate/journal/_sqlite_base.py:312`);
- the seal is over the exact stored bytes
  (`substrate/journal/_sqlite_execution_facts.py:100`, `:198`), so a key
  cannot be removed from a written event;
- absence means "not recorded" for current writers as well as old ones, so it
  never selects a historical path.

ADR 0016 covers every immutable current fact, so this is an argument that the
key fits the existing law, not that it is exempt from it. It is the first
owner question.

**Readers.**

| Reader | Effect |
| --- | --- |
| Raw event queries, detail and JSONL projection | Publish the new key; a projection's bytes and digest differ for new runs only |
| Run-result failures (`_control_queries.py:318`), operator evidence (`scripts/ops/read_attempt_evidence.py:578`) | Ignore it |
| The maintenance diagnostic (`maintenance_diagnostic.py:294-304`) | Ignores it until its own schema step |
| M9 rejection check (`api/_m9/trial.py:203-216`) | Compares the whole payload; unaffected while that exception stays uncoded, which it must |
| Tests asserting exact `NodeFailed` payloads for maintenance guards | Change when those guards are coded |

**Reports.** Showing the code to the operator is a report schema step, and it
is constrained by exact-key readers
(`maintenance_diagnostic.py:152-156`, frozen package readers under
`docs/plans/handoffs/`), by an 8,192-byte cap that replaces the whole report on
overflow (`maintenance_diagnostic.py:66`, `:387`; `maintenance_report.py:55`),
and by a 32,768-byte cap on operator evidence. PR #410 changes the same
records. One schema step should carry both, with a worst-case size test:
eight failures on each node, each with twelve codes, together with eight
callbacks' digests. A section must never be dropped silently.

## Concepts retired

| Retired | Replaced by |
| --- | --- |
| Sentence matching as the carrier of cause (`_FAILURES`) | `refusal` in the sealed event |
| Application sentences restated in substrate | the enum, once |
| A phantom cause with no producer | nothing; it is deleted with its fixture |
| "Worker succeeded" beside "callback refused" with no link | one function deciding category and code |

Introduced: `RefusalCode`, the run-time sibling of `AdmissionCode`.

## Delivery

"Moves" lists source-derived revisions. Every source change also moves the
installed tree and the M9 selector's source identity.

| Step | Change | Moves |
| --- | --- | --- |
| 1 | `core/refusal.py` with the `writer`, `capture`, `checker` and `gate` codes; `refusal=` on `ContractViolation`; the walker's three sites. Tests: an uncoded failure's payload is byte-identical; a coded test double is sealed and read back; an exception group records none; the paired-run test. Walker mutation needles updated (`scripts/check_m8_mutations.py:744-839`). | None found: neither file is in a source-derived revision |
| 2 | The application's eleven raise sites pass their code. The inventory test. `capture-mismatch` and its fixture are deleted. | The maintenance application revision |
| 3 | The `permit` codes, with RUN_PERMIT.md step 2. | As that step |
| 4 | The `callback` codes: every conversion from exception to string to fault list to failure value keeps the first code (`codex.py:964-966`, `codex_protocol.py:1671-1689`), and `ExecutorError` carries it as an optional field serialized only when set. The Claude worker path keeps its code through the launcher wrap. Qualification nodes that raise fresh errors from an outcome pass it on (`api/qualification.py:101`, `api/_qualification_write_graph.py:96`, `api/claude_write_qualification.py:82`). | Both adapter revisions and the Codex protocol revision |
| 5 | The report schema step, with PR #410's fields. The diagnostic prefers `refusal` and keeps `_FAILURES` for uncoded events. | The next generation's package readers |

Step 4 is the expensive one, and it is where `writer-not-positive` finally
splits. It touches a seam model that every adapter serializes; the Pi adapter
walks every outcome field against a publication bound
(`substrate/executors/pi_protocol.py:496`). It belongs in the planned
requalification.

Until revision pins are narrowed, rewording a refusal sentence still moves the
whole-module revision that contains it. Codes do not change that.

## The strongest case against

*Each vocabulary before this one was also meant to be the closed set. After
the review, what is left does not split `capture-unchanged` (the digests do)
or `gate-not-positive` (that needs a changed exam), and the one split it does
deliver arrives only at step 4, which costs a requalification. Why not record
the callback refusal as one more closed field in the attempt record, beside
PR #410's digests, and stop?*

- **That alternative is real, and for `writer-not-positive` alone it is
  cheaper.** It should be chosen if the planned requalification is not taken.
- **What it leaves is the mechanism.** The operator's cause would still come
  from matching English in a table that has already drifted, restated across a
  layer boundary, and the next application guard would add a twelfth sentence
  to it. Steps 1 and 2 remove that for the cost of one application revision,
  which every generation moves anyway.
- **The sealed event is the right home.** The attempt record is a private
  sidecar that says of itself that it is not a ledger
  (`substrate/executors/attempt_record.py:14-17`). A cause that only it holds
  cannot be read through the control plane at all.

The honest size of this design is therefore: steps 1 and 2 are cheap and worth
doing on their own; step 4 is worth doing only inside a requalification that
is happening for other reasons.

## First PR

Step 1. One new L0 module, one constructor argument, three walker sites and
their tests. No producer is edited, no report changes, no revision moves. From
that commit on, a guard given a code has it sealed with no further plumbing.

## Open questions for the owner

1. **ADR 0016.** Accept an optional key on a sealed `NodeFailed` event without
   a new era, for the three reasons above? If yes, record it as one paragraph
   in `ARCHITECTURE.md`.
2. **Maintenance names in L0.** The enum puts `writer`, `capture` and `checker`
   in `core`, beside the maintenance contracts already there
   (`core/maintenance.py`). Accept that, or wait until the fixed-task code has
   its own package?
3. **Two checks for the exam.** Split the stored-reply exam into an inventory
   check and an extraction check so `gate-not-positive` separates by check
   name? It changes the exam and its check-set hash.
4. **Step 4 or the sidecar.** If no requalification is planned, record the
   callback refusal in the attempt record instead?
5. **One report schema step.** Hold the report change until it can carry both
   `refusal` and PR #410's fields?

## Review record

One pass by an independent model, asked to attack the first draft with the
repository mounted read-only. Each premise below was then checked at source.

| Finding | Checked | Result |
| --- | --- | --- |
| An empty enum base with families is extensible, cannot be decoded by a typed field, and needs a decoder no layer can own | reasoning; `substrate/journal/_sqlite_attestations.py:103` | Accepted. One L0 enum instead |
| `CheckResult.code` enters acceptance and proof equality | `plan_manifest_application.py:649`; `_sqlite_execution.py:978-983`, `:1000-1004`; `_sqlite_attestations.py:103-105` | Confirmed. Withdrawn; codes stay out of checks and attestations |
| The oracle is embedded stdlib-only source and its codes carry a role prefix | `substrate/gates/channel_reply.py:1-8`, `:66-76` | Confirmed. `gate.extraction` withdrawn; printing a code from the exam needs its own framing design |
| Raw event surfaces publish the key | `_control_queries.py:258-263`, `projection.py:80-85` | Confirmed. Stated above |
| The Claude worker refusal ends as a bare refusal, not `mcp-call` | `claude_read.py:268-279`, `:1303-1309` | Confirmed. Corrected above |
| The ADR 0016 argument was "non-authoritative fields are exempt" | ADR 0016 decision text | Accepted. Replaced by the projector-specific argument |
| Permit faults are siblings, not a causal chain | `core/qualification.py:174` | Accepted. `refusal` is an ordered list of reasons |
| `failure_kind` is parsed from the persisted attempt record | `maintenance_diagnostic.py:184-188` | Confirmed. No longer claimed as retired |
| "Rewording a refusal then moves nothing" is false under whole-module hashes | `codex.py:2619`, `_maintenance_identity.py:14-18` | Confirmed. Claim removed |
| A source scan cannot prove codes never affect decisions | reasoning | Accepted. Paired-run test instead |
| `capture-mismatch` is written by a test fixture | `tests/substrate/journal/test_maintenance_diagnostic.py:144-148` | Confirmed. Scope narrowed to production code |
| The cleanup branch records the original error | `walker.py:1797-1801` | Confirmed. Named as a third walker site |
| Pi walks every outcome field | `pi_protocol.py:494-498` | Confirmed. Listed under step 4 |

Taken from the review without opening the source: the walker mutation-needle
lines, the qualification wrapper lines in step 4, the 32,768-byte operator
evidence cap, and the journal projector lines in "Eras and readers".

## Not verified

- The four items just listed.
- That no value comparing or hashing an `ExecutorFailure` exists outside the
  sites named. Step 4 must establish this before adding a field.
- That `maintenance_diagnostic.py` and `runtime/walker.py` are outside every
  source digest an operator package pins. No in-repository revision hashes
  them.
- The worst-case report size. It must be measured.
- PR #410's final field names; they were read from its draft.
- The Pi adapter's refusals and the journal's own, which have no codes here.
