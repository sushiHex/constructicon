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

The anchor fixes the opaque operator key and the bundle's physical identity.
Descriptors fix the generation, opaque store-instance identity, bundle/root/
lock identities and layout/lock law. The public binding digest is exactly
ADR 0021's `digest("native-operator-binding", 1, {key, generation,
store_instance})`. Paths, raw keys, filesystem identities, and configuration
bytes remain private. No credential file is read or hashed to establish identity.

Physical identity must survive a process restart and distinguish a replacement
object, including inode-number reuse. Use Linux filesystem handles obtained
from opened, non-symlink objects, plus mount and boot identity. Unsupported
handle production, a boot change, or a changed mount is unavailable for
maintenance, not permission to adopt the current path. The
[Linux interface](https://man7.org/linux/man-pages/man2/name_to_handle_at.2.html)
returns an opaque object handle; its mount number alone is not persistent
identity. No `open_by_handle_at` privilege or credential-content probe is needed.

All path components are checked without following symlinks. The bundle and
metadata are operator-owned and not writable by execution. Store and retained
lock are fixed children, not arbitrary locators. A substituted mount at either
child is refused. Hard-linked lock files are refused. Aliasing an entire bundle
cannot assign another key or lock: the retained anchor still binds both;
copying the anchor to another physical bundle fails its identity comparison.
Descriptor publication verifies historical store-instance mappings within this
bundle, so a reused instance cannot name a replacement root. No global alias
registry is introduced.

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

Materialization owns a cancellable candidate store-lock descriptor. It opens
the retained file without creation, verifies the physical identity, and polls
nonblocking exclusive `flock` while checking run control and permanent
acquisition closure. Once acquired, initial verification returns a positive
binding receipt. After the final control/closure checks, fd ownership and the
receipt transfer to the handle together, with no intervening await.

The handle retains that same open-file description until closure. It does not
reopen or reacquire it for a turn. Each execution gives it and the existing
per-acquisition guard to the existing supervisor. No `LOCK_UN` is used: closing
one descriptor must not unlock another process's inherited description.

Lock order is store then acquisition. Recovery takes only the acquisition
guard after publishing permanent closure; it never waits for a store while
holding an acquisition guard. Future maintenance takes the store lock. Local
close never reacquires either store lock or a successor's guard.

Close sets its latch first, joins any materialization handoff, cancels and joins
the active launcher, and only then drops its retained store descriptor. Repeated
close calls join the same cleanup, not launch duplicate cleanup. An inert close
performs no filesystem mutation. Once entry occurred, close publishes permanent
acquisition closure. Recovery validates the complete stale reference, publishes
that same fence, and waits the old acquisition guard without signaling stored
PIDs or deleting persistent vendor state. Stale cleanup cannot select or upgrade
to the new active generation.

## Resume and interruption ledger

The following are design obligations, not claims about executed tests.

| Boundary | State that may already exist on arrival/resume | Required next action |
| --- | --- | --- |
| Materialize entry | Handle already closed, entered, or selected by another coroutine | Refuse before I/O; set entry once before any await |
| Descriptor/open failure | Some descriptors opened, no lock or receipt | Close only locally owned descriptors; never mark ready |
| Lock wait | Cancellation, ownership loss, close, withdrawal, or old reaper still holding the lock | Recheck control and closure on every resume; no deadline reset |
| Lock acquired | Descriptor/root changed while waiting; close raced acquisition | Revalidate opened root and lock, selected descriptor, active generation and control under lock |
| Joined closure read | Caller cancellation latched while Git worker completes; closure may now exist | `finish_owned` propagates cancellation after joining; check local latch/control again |
| Initial receipt transfer | Candidate fd exists but handle not ready | One synchronous transfer; failure leaves no partially ready handle |
| Execute entry | Another execute pending, stale materialization receipt, close requested | Set single-execution latch before await; recheck binding before launch |
| Acquisition guard wait | Close/recovery arrived while store fd is held | Check closure/control after acquisition; do not start a child |
| Launch probe | Probe has returned but close/withdrawal may have arrived | Revalidate store immediately before spawn; propagate cancellation rather than treating a probe as a turn |
| Spawn handoff | Supervisor may already own both descriptions when Python is cancelled | Existing joined teardown; parent never unlocks inherited descriptions |
| Exchange resumes | Turn buffered, process exited, gate incomplete, close or binding drift | Process completion is not binding acceptance; require a fresh terminal receipt |
| Terminal check | Active generation withdrawn or replaced, root/lock changed, control lost | Refuse and publish no turn; successful check and outcome publication have no intervening await |
| Close entry | Inert, waiting, transferring, executing, or already cleaning up | Latch closed first; join owned work; cleanup cannot publish success |
| Close cancellation | Launcher/reaper still alive, cleanup exception pending | Finish owned cleanup before propagating; never report `LeaseClosure` early |
| Owner process death | Supervisor alone retains store and acquisition descriptions | Owner pipe terminates descendants; lock handoff only after quiescence |
| Recovery meets old waiter | Durable closure committed before waiter has acquired store | Waiter rechecks closure and refuses; no late launch after recovery |
| Late old reaper | Successor waiting or already owns another acquisition | Reaper closes only its own copies; no explicit unlock, unlink, or PID replay |

No `finally` block mints an initial or terminal receipt. No empty fault list,
missing descriptor, free lock, clean exit, or previous receipt establishes a
new positive gate. Receipts are local observations bound to the sealed digest,
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
of each positive receipt, active-generation comparison, root/lock identity,
no-replace publication, supervisor inheritance, closed/control resume check,
and terminal suppression. Mutants that error or tests that skip are unproven.

Before implementation, independent reviewers must attack this design. Before
the PR handoff, record exact-head local gate, Linux CI, mutation results,
review findings and their reproduction/classification in the living M8 record.
No merge or ready action is delegated by this document.
