# Verification tooling evidence

## Child termination status (Refs #195)

The verifier previously retained only failed stage names. Its failure summary
now includes each exact numeric subprocess return code, preserving the four
stages' order, execution count and aggregate exit 1. No retry, new timeout or
gate relaxation is introduced. A positive all-zero result remains unchanged.

Nine fake subprocess cases cover success, ordinary stage failures, multiple
failures, negative signal codes and signed/unsigned Windows native statuses.
The focused tests, lint and typing passed; independent narrow review reproduced
the tests and found no blocking defect. Full gate and exact-head CI evidence
belong on the PR; focused tests alone do not establish them.

The contributor guide describes one explicit verbose pytest invocation with
exclusive local transcript creation and a final child-status line. It does not
retry until green. The transcript has no byte cap and should stay private until
reviewed for test data. A last-started test is a location clue, not a cause;
parent termination can leave the child's final status unknown. The earlier
Windows full-suite interruption remains unexplained by this tooling change.

## Pinned helper checkout bytes (Refs #198)

The additional Windows full gate at `029910f` completed with one failure,
5,604 passes and 773 skips in 2,619.67 seconds. The existing direct-file pin
test rejected CR bytes in `maintenance_evidence.py`; the verifier retained
`pytest (returncode=1)`. Both diagnostic helpers had canonical LF Git blobs
matching the frozen procedure pins, but CRLF working files under
`core.autocrlf=true` with no explicit LF attributes. This was a pre-existing
checkout conversion defect, not corrupted committed helper bytes.

Two exact-path attributes now require LF for those helpers. Their committed
bytes, frozen procedure and refusing direct-file hash assertion are unchanged.
The regression checks both attributes and performs a real temporary-repository
checkout with `core.autocrlf=true`: an unrestricted control converts to CRLF,
while both helpers must equal their canonical Git blobs byte for byte.
This prevents fresh-checkout recurrence; it does not turn the historical gate
into a pass or establish any host, VM or vendor result.

All 12 focused maintenance-diagnosis tests passed on Windows, including the
original direct-file pin assertion and the real checkout regression. Existing
clean working files must be rematerialized to apply newly added attributes;
the regression removes only its disposable files before checkout so an
unchanged-index optimization cannot substitute for observing converted bytes.
Full gate and exact-head CI results remain PR evidence.

The original implementation head `ced23b4` completed the Windows full gate:
5,606 tests passed and 773 skipped in 2,410.47 seconds, with verifier exit 0.
Its CI also passed all selected checks and four physical proof lanes.
Independent review reproduced the 12 focused tests and real checkout
conversion and found no blocking defect. These are original-head results;
integration with subsequent main changes uses separate focused Windows and
final-head CI evidence on the PR, not a second claimed Windows full run.
After integrating main `eff68fb`, all 72 targeted Windows diagnosis, checkout,
and CI-scope/manifest tests passed. The pin-sensitive helpers and accepted
procedure bytes remain identical to that main baseline.
