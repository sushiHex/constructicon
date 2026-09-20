# M8 N3a: state and resume review

Status: pre-implementation design review. Base: `153ab8e`. Scope: N3a of
[issue 76](https://github.com/sushiHex/constructicon/issues/76).
Authority: [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md)
and [M8 rev 3, N3](../milestones/M8-live-executors-rev3.md).
This record does not amend either accepted artifact.

## Boundary and reuse

N3a supplies a dedicated store, a retained physical lock, immutable descriptors,
and positive initial and terminal binding checks. It does not qualify vendor
authentication, account continuity, egress, refresh, overage, or deployment.
N3b owns egress; N3c owns the full maintenance and refresh matrix. The production
provider remains unavailable after this slice. All fixture contents are harmless.

The existing schema-3 store identity and schema-4 description already express
the public facts. `system.describe()` over the existing fake native assembly
confirmed the leased executor seam. No L0 model, journal schema, scheduler,
account database, or second process owner is needed.

Reuse `AcquisitionPaths`, `AcquisitionClosure`, the acquisition guard,
`LinuxLauncher.exchange`, its existing supervisor, and `finish_owned`.
The supervisor already inherits guard open-file descriptions, retains them
until its descendants are reaped, and excludes them from payload descriptors.
The new store guard joins that same tuple; it is not a second launcher.

Current gaps are explicit: `CodexOperatorHandle.materialize` is a no-op;
`close` cancels without joining; `reconcile` owns no durable native payload;
`LinuxLauncher` has no native-store mount. N3a must close these seams, not
claim a filesystem proof from descriptor models alone.

## Private configuration, not an identity service

Use a fixed provisioned bundle: a protected binding anchor, immutable
generation descriptors, explicit active selection, one retained lock, and one
writable `store/` child. Only `store/` enters the native namespace at the fixed
`/vendor-store` destination. There is no caller-selected mount destination or
general mount-list API. A launch with this mount cannot also take a workspace.
Ordinary workers receive no store mount. HOME remains disposable.

The bundle path is derived only from a trusted root and the opaque key's digest
token. The immutable anchor key must match that token; neither caller nor
descriptor supplies an arbitrary locator. The anchor fixes the opaque operator
key and the bundle's physical identity.
Descriptors fix the generation, opaque store-instance identity, bundle/root/
lock identities and layout/lock law. The public binding digest is exactly
ADR 0021's `digest("native-operator-binding", 1, {key, generation,
store_instance})`. Paths, raw keys, filesystem identities, and configuration
bytes remain private. No credential file is read or hashed to establish identity.

Every check compares the descriptor's recomputed binding digest and layout/lock
law digests with the sealed `NativeOperatorStoreIdentityV1`, not merely another
internally consistent descriptor. Active selection binds the canonical
descriptor digest, key and generation with no missing-field defaults.

Physical identity must survive a process restart and distinguish a replacement
object, including inode-number reuse. Use Linux filesystem handles obtained
from opened, non-symlink objects using `name_to_handle_at(AT_EMPTY_PATH)`, with
a hard handle-byte bound and strict encoding, plus mount and boot identity. Unsupported
handle production, a boot change, or a changed mount is unavailable for
maintenance, not permission to adopt the current path. The
[Linux interface](https://man7.org/linux/man-pages/man2/name_to_handle_at.2.html)
returns an opaque object handle; its mount number alone is not persistent
identity. No `open_by_handle_at` privilege or credential-content probe is needed.

All path components are checked without following symlinks. The bundle and
metadata are operator-owned and not writable by execution. Store and retained
lock are fixed children, not arbitrary locators. A substituted mount at either
child is refused by comparing its mount identity with the anchor's. Hard-linked
lock files are refused. Aliasing an entire bundle
cannot assign another key or lock: the retained anchor still binds both;
copying the anchor to another physical bundle fails its identity comparison.
The publisher derives the opaque store-instance label from the positively
observed root identity using a domain-separated digest; the caller cannot
select it. Boot/mount facts deliberately fence that relationship, so reboot
requires maintenance rather than silent reuse. Key/generation slots derive
uniquely from the key token and generation. Trusted root, key bundle, metadata
directories, store and lock must share one mount: no submount or bind-mount
alias is admitted. Therefore another key cannot name the same physical root,
and replacement cannot reuse its derived instance. Historical descriptors
within the key bundle still pin the instance's retained-lock relationship.
There is no global mapping index, publication service or second custody lock.
Direct hostile rewriting of trusted configuration is outside the accepted
boundary, not a supported alternate publication path.

Publication is an offline operator-configuration operation, never normal
execution: bounded strict canonical metadata, same-directory temporary file,
file fsync, atomic no-replace publication, directory fsync. An existing
key/generation refuses even when bytes match. The temporary name is never a
descriptor. Publication does not activate anything. A separately supplied,
strict active selection must name the exact descriptor and binding digest;
absence, withdrawal, malformed bytes, or a mismatch refuses. Never select
the latest generation or infer activation from descriptor presence.

The withdrawal/qualification/activation workflow is N3c. Its compatibility
contract is already fixed here: withdrawal must be durable before mutation;
publication alone is disabled; activation follows qualification. N3a tests
these input states at its read boundary, not a new maintenance API or a claim
that the full crash matrix has run.

## Ownership and lock order

`acquire` returns an inert handle and complete recovery reference. It neither
opens the store nor takes a lock. The walker records the lease and enrolls
cleanup before materialization. The recovery reference contains acquisition
identity and the sealed binding digest, not the private bundle path or key.

Materialization first acquires the per-acquisition guard, then owns a cancellable
candidate store-lock descriptor. Both are retained for the handle lifetime,
including idle time, rather than only during a running exchange. It opens
the retained file without creation, verifies the physical identity, and polls
nonblocking exclusive `flock` while checking run control and permanent
acquisition closure. Once acquired, initial verification returns a positive
`BindingCheck`. After the final control/closure checks, ownership of both
descriptors and the positive check transfer together, with no intervening await.

The handle retains that same open-file description until closure. It does not
reopen or reacquire it for a turn. Each execution gives it and the existing
retained per-acquisition guard to the existing supervisor. No `LOCK_UN` is used: closing
one descriptor must not unlock another process's inherited description.

Lock order is acquisition then store. Recovery takes only the acquisition
guard after publishing permanent closure; future maintenance takes only the
store lock. A store waiter observes closure and releases its acquisition guard.
Execution reacquires neither guard. Local close never reacquires either lock.

Close sets its latch first, publishes permanent closure once entry occurred,
cancels and joins materialization and the active launcher, and only then drops
its retained descriptors. It must not call a disposal helper which waits its
own retained acquisition guard before cancelling local work. Publication
failure still runs all local teardown and then surfaces the failure. Repeated
close calls join the same cleanup, not launch duplicate cleanup. Materialization
and cleanup have explicit owned tasks, never a wait on the calling walker task.
An inert close
performs no filesystem mutation. Once entry occurred, close publishes permanent
acquisition closure. Recovery validates the complete stale reference, publishes
that same fence, and waits the old acquisition guard without signaling stored
PIDs or deleting persistent vendor state. Stale cleanup cannot select or upgrade
to the new active generation.

## Resume and interruption ledger

The following are design obligations, not claims about executed tests.

| Boundary | State that may already exist on arrival/resume | Required next action |
| --- | --- | --- |
| Materialize entry | Handle already closed, entered, or selected by another coroutine | Refuse before I/O; set entry once before any await; own one materialization task |
| Acquisition guard wait | Recovery already holds or closed this acquisition | Check control and closure after entry; retain the guard through idle and execution |
| Descriptor/open failure | Some descriptors opened, no completed binding check | Close only locally owned descriptors; never mark ready |
| Lock wait | Cancellation, ownership loss, close, withdrawal, or old reaper still holding the lock | Recheck control and closure on every resume; no deadline reset |
| Lock acquired | Descriptor/root changed while waiting; close raced acquisition | Revalidate opened root and lock, selected descriptor, active generation and control under lock |
| Joined closure read | Caller cancellation latched while Git worker completes; closure may now exist | `finish_owned` propagates cancellation after joining; check local latch/control again |
| Initial check transfer | Candidate descriptors exist but handle not ready | One synchronous transfer; failure leaves no partially ready handle |
| Execute entry | Another execute pending, stale materialization check, close requested | Set single-execution latch before await; recheck binding before launch |
| Launch probe | Probe has returned but close/withdrawal may have arrived | A narrow trusted native-store verifier runs inside the launcher after probe and before spawn; propagate cancellation rather than treating a probe as a turn |
| Spawn handoff | Supervisor may already own both descriptions when Python is cancelled | Existing joined teardown; parent never unlocks inherited descriptions |
| Exchange resumes | Turn buffered, process exited, gate incomplete, close or binding drift | Process completion is not binding acceptance; require a fresh terminal `BindingCheck` |
| Terminal check | Active generation withdrawn or replaced, root/lock changed, control lost | Refuse and publish no turn; successful check and outcome publication have no intervening await |
| Close entry | Inert, waiting, transferring, executing, or already cleaning up | Latch closed first; join owned work; cleanup cannot publish success |
| Close cancellation | Launcher/reaper still alive, cleanup exception pending | Finish owned cleanup before propagating; never report `LeaseClosure` early |
| Owner process death | Supervisor alone retains store and acquisition descriptions | Owner pipe terminates descendants; lock handoff only after quiescence |
| Recovery meets old waiter | Durable closure committed before waiter has acquired store | Waiter rechecks closure and refuses; no late launch after recovery |
| Late old reaper | Successor waiting or already owns another acquisition | Reaper closes only its own copies; no explicit unlock, unlink, or PID replay |

No `finally` block mints an initial or terminal check. No empty fault list,
missing descriptor, free lock, clean exit, or previous check establishes a
new positive gate. Check results are local observations bound to the sealed digest,
not new public account attestations or durable command records.

## Publication and crash states

| Last completed fact | Crash/restart interpretation |
| --- | --- |
| No descriptor; partial temporary file | Disabled; no valid selection can be inferred |
| Descriptor file fsynced, not linked | Disabled; temporary file is not published |
| Descriptor published, directory fsync unfinished | Publication not acknowledged; never activate as a consequence |
| Descriptor durably published, no active selection | Disabled; independent qualification is still absent |
| Explicit active selection for another generation | Old sealed binding refuses initially and terminally |
| Withdrawal started but not durably acknowledged | Maintenance must not mutate; N3a grants no mutation permission |
| Withdrawal durable | Disabled even though old descriptors and conformance remain |
| Replacement root at identical path after real restart | Old physical handle differs; refuse, never rewrite descriptor |
| New descriptor exists before activation | Old selection cannot silently adopt it; new one remains disabled |

## Proof plan

Each refusal has a permitting counterpart. Tests enter through the actual
provider/handle and preserve the real conversation and publication gates.
Portable tests substitute only platform-bound filesystem/lock observations;
they do not certify Linux behavior. Linux Actions runs the real filesystem,
lock, supervisor, native mount and restart proofs. Windows skips are not passes.

Required pairs: active descriptor accepted versus missing/withdrawn/stale;
unchanged root accepted after a fresh interpreter versus same-path replacement;
first publication accepted versus duplicate key/generation refused; initial
and terminal checks each permit a genuine result and independently block drift;
store contender waits then proceeds after quiescence; owner death cannot release
the supervisor's lock early; ordinary worker cannot read the native store while
native fixture can; descendant cannot reach metadata, lock, or host workspace.

Cancellation/closure tests cover the ledger's waits and handoffs, including
repeated close and an old waiter resuming after durable closure. A field-walking
public-surface test asserts declared bounds and excludes seeded private binding
metadata on both success and refusal. This does not mislabel arbitrary native
turn content as universally secret-free; N2 deliberately preserves turn data.

Every new gate fault receives an assertion-killed mutant, including omission
of each positive check, active-generation comparison, root/lock identity,
no-replace publication, supervisor inheritance, closed/control resume check,
and terminal suppression. Mutants that error or tests that skip are unproven.

Before implementation, independent reviewers must attack this design. Before
the PR handoff, record exact-head local gate, Linux CI, mutation results,
review findings and their reproduction/classification in the living M8 record.
No merge or ready action is delegated by this document.

## Pre-implementation review corrections

Sol's lifecycle review found two introduced design defects, confirmed against
`codex.py`, `acquisition.py` and the supervisor: execution-only acquisition
locking let recovery report quiescence over an idle store holder; calling
disposal before joining local work could deadlock on the handle's own guard.
Both guards now span the entire materialized lifetime, in acquisition/store
order, and local close publishes closure separately from local teardown.
The probe-to-spawn window requires verification inside the launcher, not a
check merely before calling `exchange`.

Terra's descriptor review required explicit key-token/anchor matching, sealed
identity cross-checks, fd-based bounded filesystem-handle capture, and the
`BindingCheck` name to distinguish an observation from a durable receipt.
Sol also required instance uniqueness beyond a caller assertion. A
configuration-wide inventory under a directory publication lock was considered
and rejected as unnecessary: the publisher derives the instance from physical
identity, and direct-child/same-mount topology excludes aliases. Sol and Terra
confirmed this smaller design closes the concern without a registry.
The full maintenance ordering and
crash matrix remains prospective N3c work; N3a proves its selected-binding read
boundary, not qualification of a maintenance procedure.
Both independent source-based reviews now report no design blocker after
these corrections. An additional Hardline Codex review timed out after 300
seconds and provides no review evidence. Implementation may now begin;
the proof ledger remains prospective until tests actually run.

One reviewer proposed forwarding an open store-directory fd through bubblewrap
to eliminate pathname substitution. Source inspection refuted that premise:
[bubblewrap 0.9.0](https://github.com/containers/bubblewrap/blob/v0.9.0/bubblewrap.c)
canonicalizes bind sources with `realpath`, including `/proc/self/fd/N`.
The reviewer withdrew the proposal. No new supervisor fd channel is justified.
The actual boundary is a parent that descendants cannot modify, the retained
lock for cooperative trusted maintenance, and the post-probe and terminal
checks. It does not defend against a privileged operator ignoring the lock
and rewriting trusted configuration, which ADR 0021 explicitly excludes.

## Implementation review ledger

The implementation is still under review; this section records reproduced
corrections, not a completed Linux qualification. The following introduced
defects were found while the permitting and refusing tests were being built:

- A held check reused identities captured before a lock wait. It must reopen
  the protected paths and compare their current identity to the retained
  descriptors, without taking another lock or releasing the held one.
- Matching descriptor and sealed law digests did not establish that either
  named the running implementation. Both must match the actual source-derived
  laws. The publisher-derived store instance must also be re-derived, not
  accepted merely because its downstream digests agree.
- A directory's link count grows when the native client creates a child
  directory. That mutable count is not root replacement. The root object
  identity stays pinned; a retained regular lock must still have one link.
- Offline publication followed existing paths during ownership changes before
  proving they were direct, nonsymlink children. A later refusal cannot undo
  that side effect. Verification must precede any ownership mutation, using
  the opened descriptor rather than resolving the path again.

One implementation review claim was rejected after checking primary sources:
`name_to_handle_at(..., AT_EMPTY_PATH)` was said to require
`CAP_DAC_READ_SEARCH`. That capability check belongs to `open_by_handle_at`,
which this implementation never calls. The reviewer withdrew the finding;
the [Linux 6.8 source](https://github.com/torvalds/linux/blob/v6.8/fs/fhandle.c)
keeps the two paths distinct. The existing FD-based identity primitive remains;
the unprivileged Actions lane must still demonstrate it on the actual host.
