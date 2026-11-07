# Shared deadline and early proof-inventory checks

This delivery pairs [#343](https://github.com/sushiHex/constructicon/issues/343)
and [#275](https://github.com/sushiHex/constructicon/issues/275). The settings
observation creates its absolute deadline in `observe_settings`; its regression
now advances the event-loop clock by 40 ms at each read against that same 60 ms
deadline. It checks that initialize is observed while settings is not. On Windows,
ten separate focused runs passed. A deliberately renewed conversation deadline
with the original outer timeout disabled failed the settings-observed assertion.
The prior reported 7-of-8 Windows failure rate was not independently reproduced;
the old real sleeps allowed scheduler delay to consume the deadline before the
first assertion could be satisfied.

The containment workflow runs the existing exact-once proof-routing and live
mutation-target checks as a prerequisite to the physical lanes. Tests exercise
omitted, duplicated and misrouted proof entries and pin the dependency; the
existing aggregate requires successful physical proofs for full scope. The
credential-free prerequisite passed 40 tests in 4.19 seconds wall time locally,
including process startup. The issue reports an earlier inventory failure after
1,145 seconds with four physical jobs already running. The new ordering avoids
provisioning those jobs for this class of failure; CI is the first execution of
that workflow and supplies actual Actions timing and Linux evidence.

No physical provisioning, vendor binary, credential, VM or provider call was
used for the local checks. The delivery PR owns final-head CI and review evidence;
these results do not establish native qualification or reproduce the reported
Windows failure frequency.
