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
