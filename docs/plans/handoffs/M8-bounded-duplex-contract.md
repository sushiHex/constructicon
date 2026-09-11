# M8 bounded duplex transport contract

Status: proposed contract; independent review precedes implementation.
The owner's 2026-09-11 instruction to implement steps 1-4 authorizes this
bounded transport design and its implementation after review. It does not
accept native authentication or supersede ADR 0018. Review findings can amend
this draft; accepted contract bytes are preserved, with outcomes recorded
separately. GitHub [#37](https://github.com/sushiHex/constructicon/issues/37)
owns work state; [#38](https://github.com/sushiHex/constructicon/issues/38)
continues to own authentication decisions.

Base: `ddad9f07f13b64bffd84476b3d7999d373b2ac7f`, merged PR #51. Its tree
equals reviewed `3b1b840c6844728ccd22811b568ce328b28e7cfb`.

## Scope and existing authority

The [qualification plan](M8-native-qualification-plan.md) correctly identifies
the missing duplex interface. This contract addresses that interface only.
[INVARIANTS](../../INVARIANTS.md), [ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md),
the acquisition closure law, and the task-shaped `Executor` remain governing.

`LinuxLauncher.run` currently supplies one predetermined stdin buffer and
closes it. Its `_run` already owns one supervisor, bounded output capture,
the absolute deadline, acquisition guard descriptors, and joined teardown.
The supervisor owns the PID namespace and reaps escaped descendants. Keep
that division. The transport knows neither leases nor models; its caller
continues to validate and hold the acquisition before launch.

The [official app-server protocol](https://learn.chatgpt.com/docs/app-server#protocol)
is bidirectional; later requests can depend on earlier replies. This source
establishes the communication need, not compatibility of a current example
with the pinned 0.153.4 binary. The existing pinned probe remains the native
protocol evidence. This contract changes no binary, catalog, or model pin.

## Decision: one scoped byte conversation

Add one L0 protocol, `ProcessIO`, in `core/process.py`:

```python
class ProcessIO(Protocol):
    async def write(self, data: bytes) -> None: ...
    async def read(self, maximum: int = 8192) -> bytes: ...
    async def close_stdin(self) -> None: ...
```

Add `LinuxLauncher.exchange(..., conversation, timeout_s)` with the same
fixed command, workspace, posture and guard arguments as `run`. The trusted
adapter supplies `conversation: Callable[[ProcessIO], Awaitable[None]]`.
The launcher calls it once, after the same availability probe and successful
spawn. Only the byte channel enters the callback: no process handle, fd,
signal method, filesystem locator, launch function, or renewable timeout.

`exchange` returns the existing `ProcessResult`. Parsed provider data remains
in the adapter, which must combine it with that process result before judging
success. No new public `ExecutorOutcome`, completion API, durable field,
capability kind, journal phase, or MCP method is introduced.

`run` is the batch specialization of the same owned pump: write its existing
buffer, close stdin, and let output capture finish. Preserve its signature,
pre-spawn input validation, task/artifact budget distinction, result fields,
and partial-output behavior. No separate subprocess creation or reaper for
interactive calls. A genuine scripted `ProcessIO` double and Linux streams
must exercise the same protocol tests (I6/I7).

## Byte and concurrency laws

- `write` accepts bytes only. Charge the complete call against the cumulative
  task-input budget before its first write or await. A refused oversized call
  writes no prefix. Chunk admitted bytes into bounded writes and await drain;
  a child that does not read cannot accumulate an unbounded host write queue.
  An interrupted or broken write may have delivered a prefix: never retry it
  automatically, refund its budget, or claim atomic external delivery.
- Duplex input uses `ProcessLimits.input_bytes`, cumulatively across calls;
  there is no per-message budget reset or duplex artifact override. Batch
  input retains its existing `input_kind` selection. Zero-byte writes are
  allowed while stdin is open and spend no bytes.
- `read` accepts an integer in `1..8192` (not bool) and returns at most that
  many bytes, in order. Nonempty chunks are arbitrary stream boundaries, not
  messages. Only drained stdout followed by actual pipe EOF returns `b""`;
  no idle period or decoder observation invents EOF. Repeated EOF reads are
  stable while the callback remains active.
- Reuse the existing bounded stdout capture as the readable history, with a
  cursor and wakeup event. Do not add a second output queue or ever-growing
  transcript. Capture drains independently of callback reads. A slow reader
  therefore reaches the total output limit and stops the invocation; it
  cannot block the controller's termination path. This is bounded capture,
  not a claim of lossless unlimited backpressure.
- Keep cumulative stdout, newline-record, and bounded stderr head/tail rules.
  Check limits before exposing newly read bytes. A bound breach stops the
  conversation and process; salvaged `ProcessResult` bytes are evidence, not
  permission to dispatch a partially received message. A newline limit is
  framing protection only; backend semantic validation stays in its adapter.
- At most one read and one write may be pending on a handle; one of each may
  overlap. Refuse overlapping same-direction calls rather than queueing them
  or nondeterministically choosing a reader. `close_stdin` shares the writer
  exclusion. It is idempotent while active, never reopens, and later writes
  fail. A completed callback invalidates all handle operations, including
  read and close, before any teardown await. Retaining a Python reference
  cannot extend the conversation's lifetime.
- The callback is trusted, asynchronous adapter code. It must join work it
  creates and must not block the event loop or suppress cancellation forever.
  The interface cannot contain arbitrary host Python. Deadline/owner death
  still bound physical child lifetime through the existing supervisor; host
  callback CPU containment is not claimed.

## Completion and failure have one owner

One absolute deadline covers artifact checks, probe, spawn, protocol work,
pipe drain and process wait. No message renews it. The existing supervisor's
non-renewable TERM/KILL grace remains physical cleanup, not a second task
budget. Keep `finish_owned` for cancellation-resistant joined cleanup.

Normal callback return closes stdin, invalidates the handle, and waits for
process completion and output drain within the remaining deadline. It is not
process success. A peer that does not exit after EOF times out; a nonzero exit
cannot become success because the callback returned. The caller may receive
buffered final stdout after child exit while its conversation is still active.

On caller cancellation, callback failure, transport failure, output overflow,
or deadline: invalidate I/O first, request the existing owner-pipe shutdown,
cancel and join protocol work, finish all drains and reaping, then return the
bounded result or propagate the error. Pending reads/writes must wake or be
cancelled; cleanup cannot wait for a peer response. Repeated cancellation
cannot release the guard or orphan the callback. Preserve an original error
and any cleanup failure through exception chaining/grouping; never turn
cleanup failure into a successful result. Normal peer EOF/broken-pipe handling
in the batch specialization stays compatible; duplex protocol truncation is
observable to its adapter rather than silently retried.

The launcher does not poll SQLite or Git. Closing a Git acquisition marker
does not itself kill a running process: closure refuses later use, disposal
waits on the physical guard, and the owning adapter supplies cancellation.
Prove those distinct facts. Do not rename guard retention as active revocation.
On actual owner death, the supervisor's existing owner pipe triggers physical
termination and retains its guard until descendants have been reaped.

## Compatibility and identity

L0 declares the protocol; L1 implements it; provider adapters interpret their
own wire protocols. No `runtime`, walker, Graph, admission, task, grants,
description, or persistence schema changes. No new import-linter exception.

Implement the pump behavior in the already source-hashed launcher module;
bind the new L0 protocol source in the launch revision too. If implementation
is later extracted, its content must join that revision. Changed launch law
produces new capability/check identities; never relabel a retained identity
as running the new law. Preserve historical stored bytes, not the fiction
that a changed implementation has the same content identity.

Runtime content, AppArmor policy, UID/mount/FD recipe, no-network posture,
acquisition guards and supervisor are unchanged. A duplex channel is not
provider connectivity: `--unshare-net` still prevents a native process from
reaching the outer lab's fake HTTP provider. It is only the transport
prerequisite. Native integration must separately prove a supported test
arrangement without removing that flag, adding host sockets, or inventing
an auth/grant identity. A new boundary remains a #38 decision.

## Required proof before the transport slice is complete

The contract review precedes production edits. Then a separate implementation
PR must pass the exact-head repository gate and existing Linux Actions lane,
plus an independent review and assertion mutants for the new guarantees.
Windows skips are not physical proof. Required observations:

1. A real child emits a fresh challenge; the controller reads it, computes a
   response, writes it, and receives confirmation. A predetermined stdin
   buffer must fail this test. Exercise the same conversation with a genuine
   scripted double; neither has model/account access.
2. Fragmented/coalesced output, final bytes before EOF, repeated EOF, no output,
   stderr-only progress, early stdin close, and callback completion with a
   lingering child. Assert both typed outcomes and exact observed bytes.
3. Exact and overflowing cumulative input/output/record limits, a single
   oversized write with zero delivery, stalled reader/writer, same-direction
   overlap, closed/stale-handle use, callback failure, and a non-renewing
   deadline. Demonstrate the observation first so no vacuous refusal passes.
4. Repeated cancellation during spawn, write drain, read wait, adapter work,
   and teardown; no pending callback or I/O task after return. Cleanup failure
   must retain the original failure and cannot report disposal or success.
5. Actual controller death in a child interpreter during the exchange, with
   a payload descendant that changes session. Observe termination and reaping
   separately, and demonstrate the acquisition guard stays held until the
   old namespace is quiescent. Disposal must wait; closure prevents later use.
6. Existing batch, Git capture, contained gate, native-probe and acquisition
   tests and mutation inventories remain green. Run batch and duplex over the
   identical production spawn/teardown path; changed identity is explicit.

Record which tests are portable, which are native Linux, and which claims
remain unexecuted. Preserve the exact-head native artifact independently of
test assertions. No positive scripted transport result is a native CLI proof.

## Sequencing after this contract

The authorized implementation step follows a clean independent contract
review and recorded acceptance of this bounded scope. It does not authorize
automatic merge of its implementation PR. A change to these contracts requires
review, not a quiet implementation exception.

After transport proof, resume Slice A's complete startup-origin inventory and
controlled recipe, followed by Slice B only if its remaining prerequisites
are satisfied. Real SQLite/RunHost recovery, native home/all-descendant
ownership and stale-attempt revocation still need their own evidence. Leave
ADR 0018 intact; propose an authentication successor only after positive
combined qualification and obtain its separate owner decision. No gateway
deployment, account access, paid calls, Pi/OpenRouter implementation, or M9
work follows from this transport contract.
