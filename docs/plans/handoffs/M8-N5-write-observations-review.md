# N5 WRITE: capture refusal and callback observations

Living, additive design review for
[N5](https://github.com/sushiHex/constructicon/issues/78). This does not edit
the accepted [Stage 4 design](M8-N5-stage4-write.md) or authorize a live turn.

## Evidence and authority

The retained attempt completed its native turn but did not qualify WRITE.
A copy-only diagnostic found a writer checkpoint whose candidate equalled
the sealed base, followed by the checker's existing exact-gate refusal.
A credential-free reproduction confirmed that ordinary capture and gate
semantics can produce this outcome after a successful no-op callback.
That reproduction is a possible explanation, not proof of what the live
callback did. The old attempt did not persist callback observations.

The owner approved a focused privacy, observation, regression and review wave.
The public diagnostic comments have had private execution locators removed;
the evidence identities and conclusions remain. This does not erase any
third-party cache or comment edit history.

The qualification-only capture refusal is within that approval. The owner
then explicitly [authorized the narrow callback exception](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6134552934)
to the `codex.py` freeze, with fresh installation and qualification before live
use and no new model-attempt authorization. `codex_protocol.py` and accepted
plan bytes remain unchanged. This document records the reviewed design, not
executed tests or authorization inferred from a green gate.

## Smallest change

After the existing WRITE writer completes capture, compare the actual
candidate commit with the sealed base. Equality refuses with a static
qualification-specific explanation before publishing a writer checkpoint.
The checker is consequently never acquired on this path. Generic capture,
Git and gate semantics stay unchanged: an already-integrated candidate can
remain meaningful outside this qualification. The changed writer has a new
source-derived component identity; retained definitions are not rewritten.

For callback observations, use the existing exclusive attempt record and
atomic replacement mechanism, not another journal or transcript. A bounded,
versioned block would record admitted callbacks and completed response writes,
plus one finite worker-result category per admitted callback. The callback
ceiling bounds both counters and the result vector. Do not retain callback
ids, programs, output, paths, exception text or account identifiers.

Admission is not receipt: rejected inbound requests are not counted as
admitted callbacks. A null worker result means no result was observed, not
worker failure or proof that no worker ran. Only an actual process result
supports a worker category. A successful worker does not prove a complete
response write, a changed tree or qualification success.

Progress snapshots are partial lower bounds, not a complete census. An
explicit final-snapshot indicator distinguishes an observed outcome snapshot
from interrupted progress. It does not mean every callback completed or that
the final filesystem sync returned successfully. Missing legacy observations
stay unknown, never zero. A progress-write failure latches, prevents the next
effect and prevents settlement from overwriting it with an apparently final
census. After workers join, a final snapshot can be visible even if the final
directory sync raises: it contains the actual final observations, but cannot
certify that syscall's success or survival of a later power loss.

WRITE's strict report contract would advance to schema 2; smoke stays at
schema 1. One callback observation block is authoritative. Backend request
count and vendor retry count remain unknown. No bound becomes a claim about
tokens, money, backend requests or wall-clock cleanup duration.

## Await, crash and latch review

| Boundary | State that can already exist | Required fact and consequence |
| --- | --- | --- |
| Callback observation initialization | Exclusive attempt reservation, no dispatch intent | Preserve acquired phase; zero is only an initialized partial snapshot. |
| Before turn write | Reservation and initialized observations | The existing intent boundary still owns possibly-dispatched classification. Carry observations through phase changes. |
| Before callback effect await | Validated unique call, spent callback slot | Persist admission before launching. Failure refuses without launching the next effect. |
| Worker/native-read race | Buffered records, EOF or cancellation can beat worker collection | Join owned work; record an actual worker result at its producer boundary, not only after the race chooses it. Missing result stays unknown. |
| After worker return | Observed process result, possibly invalid workspace or output | Observe finite result facts before later validation can discard them. They do not imply a response was sent. |
| Response write await | Worker finished; response may be partial or absent | Increment completed count only after the whole response write positively succeeds. |
| Progress replacement failure | Old or new file may survive, including rename before directory fsync | Latch failure; a surviving snapshot is partial. Do not retry it into a falsely finalized outcome. |
| Final settlement | Interrupted callbacks or a prior progress-write failure | Preserve the latest observations; never turn absence or stale zeros into affirmative non-occurrence. A visible outcome snapshot proves publication of final observations, not successful directory sync. |
| Capture await | Completed native turn without any net workspace change | Compare captured candidate with sealed base. Refuse equality before checkpoint; never retry the model. |
| Refusal cleanup | Executor and workspace obligations exist, gate was not acquired | Verify their actual durable closure dispositions; do not invent a third obligation or infer success from an empty list. |
| Repeated qualification | Spent authorization and terminal journal state | No redispatch, no extra capture, no automatic budget refund. |

A separate Sol design review cleared the qualification guard and identified
two essential observation corrections before implementation: partial snapshots
need explicit provenance, and zero initialization must not advance dispatch
phase. Implementation and final-head review must prove those boundaries,
not merely repeat this table.

## Required evidence

The permanent lifecycle regression must exercise successful no-op callback,
ordinary capture, early writer refusal, no writer checkpoint, no gate
acquisition and no redispatch. Its permitting counterpart still captures a
changed candidate, reaches the real fixed gate and closes all three expected
obligations. Platform substitutions are not Linux containment evidence.

Callback tests must cover affirmative final-snapshot zero, observed
success and refusal categories, partial response/cancellation, worker/read
races, progress-write failure, final-write failure before and after publication,
and old records without observations. Public
surface tests walk every field against its declared bound. Every added guard
gets an assertion-killed mutant; test errors and unexecuted tests are not proof.

## Next deployment decision, not execution

The changed graph/report require fresh pins. An authorized adapter edit also
changes the adapter revision: existing g7 qualification cannot qualify those
bytes. After review and merge, prepare the exact controller/procedure revisions
and the established replacement and fresh-qualification sequence for an owner
decision. Preserve the refused workspace and spent attempt as evidence.

The dispatched attempt is not the unused retry for a known-not-dispatched
local failure. A further model turn requires its own explicit budget decision.
This wave performs no host installation, reboot, qualification, credential
operation, model dispatch or attempt-record reset.
