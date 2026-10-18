# M8 q13: readiness and measurement boundary

Source-only preparation under [#186](https://github.com/sushiHex/constructicon/issues/186),
[#189](https://github.com/sushiHex/constructicon/issues/189) and
[#226](https://github.com/sushiHex/constructicon/issues/226).
This is a living readiness record, not authority to operate the host.
The [preparation decision](M8-post-q12-preparation-decision.md) owns the budget;
the [q13 composition](M8-maintenance-q13-continuation.md) owns the proposed steps.

## Decision boundary

**NO-GO for host execution.** A complete source package, a green gate and a
synthetic accepting rehearsal cannot establish the current installed drift
tool's bytes, current host state or owner approval of private evidence.
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

## Recovered source, not a new host measurement

After the initial design pass, the other session identified the complete
historical drift-tool source. The retained private file is 2,578 bytes, 62 lines,
LF-only, SHA-256
`e3541663b621a79558be4186a0def104d17c7b7b10a5066bb34edfeb53eb0165`.
Both complete source listings in the historical
[R2 report](https://github.com/sushiHex/constructicon/issues/73#issuecomment-5790260256)
match that digest after converting the comment's CRLF line endings to LF.
The source and a candidate expectation are preserved outside the public checkout
in durable private evidence, not only in the original temporary scratchpad.
Custody is the owner and this preparation session; retain through q13 closeout,
then seek owner direction before deletion. The private handoff holds locations.

The source's successful output is a fixed literal plus LF. The baseline selects
the successful branch; it does not supply bytes to that literal. Extracting the
literal without executing the script produces a 52-byte expectation, SHA-256
`5b0478e374b71d9017020aa6bf2b08f20bc0087d0bd8bb8a43dc524cc028d79b`.
This corrects the design review's premise that baseline content was needed to
specify the successful output. It is an independently sourced candidate contract,
not output learned from the invocation it would validate.

Owner approval of these exact inputs is still required. If approved, G1 compares
the current installed file to the historical source pin before invocation. A
difference stops; no new bytes are adopted. That route needs no separate bootstrap
session merely to obtain a digest. It does not claim that the host file has
remained unchanged or that the tool establishes fresh qualification.
In particular, this historical tool compares rows present in its baseline but
does not prove the baseline's key inventory is complete. This source-level limit
is tracked separately in [#238](https://github.com/sushiHex/constructicon/issues/238).
G1 must not be described as repairing it; the existing D2 qualification checks remain.

## Measurement is not approval

The retained q12 C1 output is a combined step stream, not a standalone capture
of the drift executable. The candidate above was recovered from independent
source, not split out of that stream. No owner approval or current-host
measurement has been established by this preparation.

If that source-based pin is not accepted, a future minimal measurement proposal
must do only the following:

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

Whether that fallback is a separate capture-only session or a checkpoint within q13 is
an owner budget decision, not an implementation detail. A separate session
would extend the proposed one-session ceiling. An in-session checkpoint would
consume q13's session even if approval cannot be obtained. Neither route is
authorized here, and no budget exemption is inferred from "read-only".

## Exact go package

The offline obligation and the first authorized host checks are separate.
The preparation decision requires the whole C3 qualification/C4 publication
join to be exercised now that the disposable isolated store exists; the earlier
shared-fixture limitation no longer exempts those steps. The C7/C8 result alone
does not discharge that obligation. Its final-head accepting and refusing
evidence must be included before requesting the go.

Installed controller, D2/launch records, historical seals, actual store floor,
boot and fresh destinations remain observations made by their prescribed steps.
They are not fabricated as offline evidence. The go package specifies these
checks and their stop rules; it does not claim their future results. The usage
preflight and positive idle/custody check run at the authorized session's start,
immediately before D0, as Q1 requires. A custody claim cannot remain fresh merely
because a previous session held it. No checks here authorize starting the host
before the exact go.

The source preparation's C7/C8 composed proof executed at `03804a2` in
[run 39132967503](https://github.com/sushiHex/constructicon/actions/runs/39132967503).
Artifact `12139591767` records acceptance plus wrong-consumer, source-drift,
qualification-mismatch and diagnostic-output refusals, a real 90-second hold,
an unchanged activated store and no application attempt. Verify, runner
qualification and all four containment lanes passed that head. The subsequent
ledger-only update changes no executable fence or implementation; final-head
CI and review remain required before merging it.

This closes the offline C7/C8 proof obligation, not the host-execution no-go.
The native peer is synthetic. In particular, the CI service home's inherited
default ACL was measured to defeat the shell saver's private mode; the disposable
fixture now uses `/tmp` and checks the resulting mode before qualification.
Nothing here establishes the private host's ACLs or relaxes its saved-file checks.

Before requesting execution, retain one package containing:

- the reviewed merged procedure head, source document/fence digests, unchanged
  controller/source/D2 pins, initial-package manifest and the exact permitted
  reconstruction rule for the deferred package;
- the 19-step evidence ledger, naming composed executed proofs, fragments and
  host-only unknowns separately, with exact-head test and CI evidence;
- the private approved drift expectation and historical source/tool pin references,
  independent approval record and any explicit measurement-session accounting;
- the prescribed positive custody/idle and fresh destination checks, their
  in-session order and stop rules, without presenting unperformed checks as
  results or treating absence of a message as exclusive custody;
- the unchanged attempt budget, stop/park procedure and limits: synthetic peers
  are not live qualification; stream EOF is not process-tree termination;
  transport uncertainty never licenses retry;
- one focused independent readiness review and dispositions of its findings.

The deferred package uses actual C8 preview/run and measured boot values. Its
manifest cannot exist in advance as an observed fact. Before C9, verify that
only those permitted fills changed and that the owner-approved drift pair is
unchanged. An exact initial-package digest does not vouch for future measured
values. All unresolved facts remain explicit no-go items.
