# Verification tooling evidence

## Bounded locked-wheel acquisition diagnostics (Refs #264)

Locked-controller-wheel acquisition now reports fixed `http`, `timeout`, `tls`,
`dns`, `connection`, `response-read` or fallback `transport` categories. These
describe observed exception types or the response-read stage, not an inferred
upstream cause. Only the immediate typed `URLError.reason` is inspected; opaque
strings and nested reasons remain generic. HTTP failures may include an exact
integer status from 100 through 599; missing or malformed status stays absent.
The renderer allowlists categories and retains the existing bounded package
label. No exception text, URLs, environment values or host details are rendered.

Credential-free tests exercise every category at both opening and reading,
hostile messages and status values, CLI exit 1 without a cache file, accepting
downloads/cache hits, and integrity refusal. The existing 120-second request
timeout, single attempt, exact lock selection, digest validation and offline
import proof remain unchanged. A typed timeout observation does not identify
which network operation timed out; generic transport failure remains unknown.
No dependency, credential, vendor, VM, workflow or runtime capability changed.

The wheel, controller environment and CI-scope tests passed on Windows Python
3.11: 177 passed and 23 skipped. The 49 wheel cases also passed separately;
explicit helper/test lint and the complete source/test lint passed. Skips are
not offline import or physical proof. Full verification and exact-head CI
evidence belong on the PR; focused tests alone do not establish them.

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

Connector review identified an introduced test-isolation defect: inherited
global attributes could keep the unrestricted control LF. A disposable
`core.attributesFile` configuration reproduced that assertion failure (one
failure, one pass). Disabling global/system configuration alone still failed
with default XDG global attributes (one failure, two passes). Both findings
were adopted; the repository's two helper attributes were not at fault.

All Git calls in the checkout test, including canonical HEAD blob reads, now
use the same isolated environment and explicit empty attributes file. Inherited
`GIT_*` overrides are removed, global/system configuration is disabled, and
system attributes are disabled. Three real-checkout cases cover ordinary,
configured-global and default-global attributes without editing user settings.
All 74 focused Windows diagnosis and CI-scope/manifest tests passed after the
correction. Earlier full-gate and CI results remain evidence for their named
heads, not for this test correction.
