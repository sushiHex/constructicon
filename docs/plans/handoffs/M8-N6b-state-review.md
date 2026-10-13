# M8 N6b — owned initialization lifecycle design

Read/design proposal for [#171](https://github.com/sushiHex/constructicon/issues/171)
after N6a, under #40, ADR 0021 and M8 rev 3 N6.
No implementation, native launch, credentials, model call or availability is
established here. N6a's 2.1.296 / SDK 0.3.296 artifact identity remains the source
pin; this proposal does not silently update it or inherit the older screen.

## Existing seams and their actual strength

- `core/process.py:ProcessIO` has one reader and writer, prompt short reads,
  actual EOF as empty bytes, cumulative input spending before delivery, and no
  write retry. It has no read-nowait, arrival timestamps or process identity.
- `substrate/executors/linux.py:138` already defines
  `Conversation = Callable[[ProcessIO], Awaitable[None]]`. `exchange` at 622
  owns the process, deadline and byte scope. `_ProcessIO.write` at 439 can have
  delivered bytes before its drain fails; `read` at 475 returns only available
  bytes and accepts bounds 1..8192; `close_stdin` at 496 closes the writer but
  does not establish peer EOF or clean exit.
- The launcher invalidates its channel before cancelling the conversation
  (`stop`, 790ff), captures output independently, joins drains and protocol work,
  and only then constructs `ProcessResult` (915–1010). `ProcessExchangeError`
  carries captured private bytes, not permission to publish them.
- `ProcessResult` at 125 distinguishes supervisor return code, timeout, output
  bound and the private trusted-reaper `payload_returncode`. None of those
  replaces an affirmative adapter completion fact.
- The current native mount recipe is Codex-specific (`NATIVE_HOME` / vendor
  mount at 141ff, `NativeLayout`). Reusing process ownership is not reusing that
  recipe as qualified Claude startup. A networkless fixed Python test process
  may exercise the same exchange without a native store; it proves no Claude
  native isolation, login or egress.
- Existing TaskSpec / ExecutorOutcome and leased capability close/reconcile
  contracts remain the eventual task seam. Contained WRITE capture already
  requires an owned workspace/control check and occurs after model teardown;
  this startup-only slice creates neither a workspace output nor a candidate.

ADR 0021's startup law requires binding, subscription mode, effective config
and catalog before any model request. M8 rev 3 N6 applies the independent
Claude startup/layout/tool/egress proofs. N6a judges only this reply's reported
mode; none of its unjudged metadata becomes a completed startup gate here.

## Smallest proposed code boundary

One new `substrate/executors/claude_initialize.py`, tests, and narrow extensions
to the existing Claude mutation inventory. Leave N6a and Codex source unchanged.
No new L0 protocol, generic stream framework, executor/provider or capture path.

```python
class ClaudeInitialization:
    def __init__(self, *, selected_plan: ClaudePlan, input_limit: int): ...
    async def __call__(self, io: ProcessIO) -> None: ...

async def observe_initialization(
    launcher: LinuxLauncher, command: tuple[str, ...], *,
    selected_plan: ClaudePlan, guard_fds: tuple[int, ...], timeout_s: float,
) -> ClaudeInitializationObservation: ...
```

The callback owns no process or background task. The narrow binding calls
existing `launcher.exchange` once with this callback, workspace none / READ,
the caller's owned guards and unchanged deadline. No native store argument or
Claude vendor launch recipe is supplied by this slice. The host-selected command
is a fixed scripted process in the tests, never vendor execution. A future
qualified native assembly may reuse the callback, not claim this test binding
as its credential route.

`ClaudeInitializationObservation` is a frozen, bounded local report: optional
N6a mode verdict plus one finite lifecycle verdict. The latter distinguishes
`initialization-observed`, `refused`, `incomplete` and `process-refused`;
additional failure detail, if needed by tests, is one closed reason enum rather
than exception text. No raw stdout/stderr, prompts, accounts, ids or commands
leave the binding. No public mutable gate latch grants authority.

The callback's completion latch is private and single-use. It starts false;
it is set only after MODE_MATCH, successful stdin close and actual EOF with no
extra bytes. Reentry irreversibly poisons the callback and clears completion,
without resetting or reusing earlier evidence. If a second entry overlaps an
original suspended write/read/close, the original must check that poison when
each await resumes and before the completion latch; it cannot later overwrite
the refusal. It sends no further request or callback response after poisoning.
The binding can report `initialization-observed` only after its actual
`await launcher.exchange(...)` returns a clean ProcessResult from that same
call: returncode 0, payload_returncode 0, no timeout and no bound. It accepts
neither a caller-authored completion boolean nor a supplied unrelated result.
Cancellation after callback EOF but before launcher return yields no trusted
completed observation; cancellation propagates after launcher-owned teardown.

The returned report is observation, not an attestation, availability assertion,
or permission to submit a model request. Even its affirmative result does not
complete ADR 0021 startup or N6.

## Transaction and every await

Generate an unpredictable host-owned id inside first entry; do not accept a
caller-selected reply id or reuse one after failure. Encode one N6a bare
initialize record; check it against the supplied cumulative input allowance
before writing. There is exactly one write and no retries or refunds.

| Await | State that must be reconsidered when it resumes |
| --- | --- |
| `io.write(request)` | Bytes may already have been delivered. Failure/cancel is incomplete, never resend. No reply can complete the exchange before this write returns successfully. |
| `io.read(maximum)` while framing | Read may be short, contain a reply plus extra bytes, or end at EOF inside a record. Keep one bounded private buffer, never a transcript/second reader. Reject over-bound/invalid chunks and incomplete EOF. |
| N6a judgment (no await) | Require the exact allocated id, selected plan and pinned reply shape. Refuse unsolicited native requests, wrong ids, errors, busy state and every nonmatch; never answer a callback or send a user message. |
| `io.close_stdin()` | MODE_MATCH is only a partial fact. Close failure/cancel cannot mark completion. Launcher still owns teardown. |
| `io.read(...)` for EOF | First audit bytes already buffered after the reply. Any additional bytes, duplicate reply or unsolicited record refuse; actual empty read alone closes this transcript. A quiet live pipe is not EOF. |
| `launcher.exchange(...)` | Callback EOF is not process completion. Deadline, capture/reaper faults, nonzero/unknown payload exit or caller cancellation can still defeat the observed transaction. Only the joined actual result may qualify the report. |

Reuse N6a's RECORD_BYTES ceiling, including LF. Read at most the ProcessIO
8192-byte maximum and the remaining bounded record allowance; do not allocate
an unbounded queue. A reply split across UTF-8/chunks is assembled as bytes
before N6a decodes it. Reject all extra bytes immediately instead of retaining
or interpreting further private metadata. There are no accepted preambles or
notifications in this deliberately narrow transaction.

LF is included in RECORD_BYTES. If the bounded buffer fills without LF, it can
no longer become a valid record within the ceiling: refuse immediately, without
`read(0)` or an extra-byte probe. The review's proposed one-byte/EOF probe was
rejected for this specific reason; no additional distinction is needed.

The callback records only private finite observations on failure; exceptions
and cancellation cannot leave an affirmative default. Ordinary channel/callback
exceptions propagate privately through the launcher, which owns the join. An
exception from the launcher is **not** a result, even when it carries a private
ProcessExchangeError.result. No frozen observation is returned on that path.

The operational exception boundary has one deliberately small policy, covering
ordinary Exception failures (including ProcessExchangeError and ExceptionGroup)
and cancellation groups. Discard the original failed-launch exception without
reading or publishing its message, result, traceback or cause. If it is
CancelledError, or a BaseExceptionGroup contains a CancelledError leaf, raise a
fresh static CancelledError. Otherwise an ordinary failed launch raises one
fresh static ContractViolation. Make that raise outside the catching clause,
with `from None`, so neither the original exception nor its captured bytes/group
survives as the published cause/context. A small local type-only group traversal
detects cancellation; it is not a general exception sanitizer. Caller-invalid
arguments likewise have static errors. Fatal KeyboardInterrupt/SystemExit and
arbitrary fatal BaseException classes are not converted to ordinary reports;
this slice does not claim to sanitize a hostile trusted launcher's fatal errors.

Mixed cancellation/cleanup failures stay cancelled and failing, never an
ordinary report; the fresh exception does not claim cleanup succeeded. A clean
result can be reported only after launcher return, so cancellation after EOF
cannot manufacture process completion. No new timeout is started within the
callback; the launcher's deadline continues through EOF and all cleanup.

## Explicit remaining unknowns

Unpredictable ids plus correlation reject accidental/wrong-id replies; they
do not authenticate vendor honesty, principal identity, or physical arrival
freshness. ProcessIO cannot distinguish bytes already in an unread OS/launcher
buffer from bytes arriving after the request. No polling/yield/sleep is proposed
as a substitute. A reply returned to the reader after the write is a local read
ordering fact only. Fresh/non-resumed process and native startup custody need
independent future assembly evidence.

Actual pinned Claude behavior after bare initialize followed by stdin EOF has
**not** been exercised or qualified. A fake can prove the driver's required
EOF/exit behavior; it cannot prove Claude exits cleanly, emits no later records,
or refrains from inference. A vendor that does not satisfy this bounded exchange
remains unqualified; no fallback, timeout extension or repeated initialization
is authorized to make it pass.

Empty pending arrays and idle session state still do not exclude an inherited
prompt. Catalog, config, startup helpers, feature/cloud settings, tools, egress,
store layout/refresh/locking, spending and post-turn mode checks remain outside
this slice. No ExecutorSuccess, provider publication or capture is possible.

## Proof scope before implementation is declared complete

Portable scripted ProcessIO/launcher tests must accept both selected plans with
fragmented replies, exact bounded input and actual EOF/clean process evidence.
Refusal tests cover unsolicited/wrong/duplicate replies, same-chunk trailing
bytes, partial UTF-8 and record EOF, bound-binding frames, callbacks, write
failure after delivery, read/close failure, stale/reentered callback and clean
process exit without callback completion. Mutants must fail by assertion.

Exercise cancellation while writing, reading, closing, draining, and after
callback EOF while launcher completion is held. No retry, extra request/model
message or completed report may appear. Preserve an observed mode verdict when
a later drain/process failure makes the transaction incomplete; absent mode
stays None. Sentinels in private reply/error/capture bytes must not be published.
Test overlapping reentry at suspended awaits, including a late valid reply that
cannot resurrect completion. Test ProcessExchangeError containing captured
sentinels, setup/cleanup exceptions, direct cancellation with a private cause,
and mixed/nested cancellation groups: static fresh errors, no forwarded result,
cause or context, and no normal observation on failed-launch paths.

A fixed nonvendor Python worker through the existing Linux duplex fixture can
prove actual process ownership, deadline, EOF/exit and joins. Mark Windows skips
unverified, not physical proof. No credentials, vendor SDK import/execution,
vendor network, model call, host operation or production availability is in scope.

## Credential-free implementation evidence

The new `claude_initialize.py` is 172 lines: one single-use callback, its narrow
owned-exchange binding, frozen enum-only observations and private predicates.
One private lifecycle state (`new/incomplete/refused/completed`) replaces
separate entry/poison/completion booleans. Framing searches only each new chunk,
not the accumulated prefix; EOF needs only a one-byte read after stdin close.
N6a, Codex and core source remain unchanged.

Tests were written first; the initial run failed collection because this module
did not exist. This records ordering, not a semantic guard kill. The implemented
portable lifecycle suite executed **83 passed**. Together with N6a, the focused
run executed **209 passed, 6 skipped, 30 deselected** in 0.63 s. The six new
Linux cases are **unverified locally on Windows**: two selected plans with
clean/bad actual exits, deadline after an affirmative worker reply, and
cancellation after an affirmative reply. They use only fixed Python workers,
retain the two real probe/workload subprocess handles, and require both handles
terminated before return/raise. The cancellation observer races task completion
and joins both waiters; no scheduling sleep stands in for phase evidence.

Ruff passed for the new source/tests, appended duplex cases and inventory;
strict mypy passed for the one new source file, and diff whitespace checks
passed. New inventory metadata/one-place checks also passed (85 passed,
33 deselected with the lifecycle suite). No new workflow entry is needed:
the existing physical foundation step already executes the whole duplex file.

The existing Claude inventory executed **76 assertion-killed mutants**, exit 0,
with no NOT PROVEN result: 36 retained N6a guards and 40 new lifecycle guards.
Mutations are isolated child code objects, not working-tree rewrites. Both the
private callback gate and public observation/process-result call sites are
pinned, including cancellation category/privacy and incomplete completion.
Full exact-head CI, independent implementation review and actual Linux execution
remain separate evidence. No vendor executable, SDK import, credentials, model,
host or vendor network was exercised locally.
