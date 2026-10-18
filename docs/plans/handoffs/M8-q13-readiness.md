# M8 q13: readiness and measurement boundary

Source-only preparation under [#186](https://github.com/sushiHex/constructicon/issues/186),
[#189](https://github.com/sushiHex/constructicon/issues/189) and
[#226](https://github.com/sushiHex/constructicon/issues/226).
This is a living readiness record, not authority to operate the host.
The [preparation decision](M8-post-q12-preparation-decision.md) owns the budget;
the [q13 composition](M8-maintenance-q13-continuation.md) owns the proposed steps.

## Decision boundary

**NO-GO for host execution.** A complete source package, a green gate and a
synthetic accepting rehearsal cannot establish the installed drift tool's bytes,
its output contract, current host state or owner approval of private evidence.
The exact-head review and evidence ledger must distinguish each of these facts.

The proposed budget remains one q13 live session and at most one application
attempt. A dispatched or uncertain dispatch consumes the attempt. No refusal
authorizes q14, another diagnostic, R6, a controller replacement or a model retry.
Preparation remains source-only and credential-free; the q12 go is spent.

## Retain the controller, prove the installation

The proposed controller, source and application base remain
`5793ef98ef5597c9ee9811a0d1f031554eb7f514`; installed D2 source remains
`8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3`.
The source comparison against preparation baseline
`dc61d16da5f1393850b89a368c2c3776a116026e` is empty for `src/`, `uv.lock`,
`pyproject.toml` and `scripts/ci/m8_host_artifacts.py`. This supports retaining
the controller rather than rebuilding it for documentation and test changes.
It does not measure the installed controller. The composition retains fresh
launch/controller verification and R19; a difference is a stop, not permission
to install. Recheck this source comparison on the final head.

## Measurement is not approval

The retained q12 C1 output is a combined step stream, not a standalone capture
of the drift executable. No independently approved expected stdout file or
installed-tool digest has been established by this preparation. Do not split a
line out of that stream and present it as a measured emitter contract.

A future minimal measurement proposal must do only the following:

1. Establish exact procedure pins, fresh destinations, custody and the reviewed
   start/park transport. It needs its own explicit go; no command runs now.
2. Read the complete installed drift tool into private evidence and record its
   SHA-256. Review those bytes before invocation if no independent reviewed
   source reference is available. A first-observation digest pins subsequent
   identity; it does not certify the tool's correctness or origin.
3. Invoke only that reviewed tool as the operator, with stdin closed. Retain
   separate complete stdout and stderr, positive launch state and observed
   direct-child status. No sudo, controller, lane, store, credential or model
   operation belongs in the measurement step.
4. Record capture completion separately from a healthy verdict. A nonzero exit
   or diagnostic is evidence, never an affirmative drift check. Failed launch,
   failed stream drain, missing status or uncertain completion stays incomplete.
   A completed direct child does not prove descendant termination.
5. Park and retain the private evidence with custodian, retention period, stable
   reference, byte sizes and integrity digests. Publish only bounded facts, not
   raw tool source, host output, addresses or operator identifiers.

The installed tool's interface is not assumed safe merely because an earlier
command returned zero. The measurement proposal must identify its reviewed
capture fence and whole-stream tests before execution; an improvised command or
a new generic exception to the packager's drift guard is not a substitute.

The owner then approves the expected stdout file by digest against independent
evidence and the tool's intended semantics, following the
[post-q12 review](M8-post-q12-review.md#q13-preparation).
The later G1 invocation validates against that approved input. No invocation
creates its own expectation. Historical private evidence needed for comparison
must be preserved before separately authorized public-history removal.

Whether this is a separate capture-only session or a checkpoint within q13 is
an owner budget decision, not an implementation detail. A separate session
would extend the proposed one-session ceiling. An in-session checkpoint would
consume q13's session even if approval cannot be obtained. Neither route is
authorized here, and no budget exemption is inferred from "read-only".

## Exact go package

Before requesting execution, retain one package containing:

- the reviewed merged procedure head, source document/fence digests, unchanged
  controller/source/D2 pins, initial-package manifest and the exact permitted
  reconstruction rule for the deferred package;
- the 19-step evidence ledger, naming composed executed proofs, fragments and
  host-only unknowns separately, with exact-head test and CI evidence;
- the private approved drift expectation and tool digest references, independent
  approval record and explicit measurement-session accounting;
- positive custody/idle and fresh destination checks, without treating absence
  of a message as exclusive custody;
- the unchanged attempt budget, stop/park procedure and limits: synthetic peers
  are not live qualification; stream EOF is not process-tree termination;
  transport uncertainty never licenses retry;
- one focused independent readiness review and dispositions of its findings.

The deferred package uses actual C8 preview/run and measured boot values. Its
manifest cannot exist in advance as an observed fact. Before C9, verify that
only those permitted fills changed and that the owner-approved drift pair is
unchanged. An exact initial-package digest does not vouch for future measured
values. All unresolved facts remain explicit no-go items.
