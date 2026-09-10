# M8 hosted-runner qualification

This is a prerequisite investigation, not the PR B containment gate and not a
live execution service. See [accepted ADR 0019](adr/0019-hosted-linux-runners-are-requalified-not-image-pinned.md).

The owner chose GitHub Actions instead of installing virtualization on the
Windows development PC. `M8 runner qualification` uses a fresh standard
`ubuntu-24.04` VM, read-only repository permission, SHA-pinned actions, no
persisted checkout credential, and no model/provider secrets. The checkout
and evidence name the exact PR head, not an implicitly generated merge tree.

Provisioning is a visible workflow step, explicitly authorized by the owner:
install Ubuntu's fixed `bubblewrap=0.9.0-1ubuntu0.1` package using authenticated
APT metadata, create `m8-probe` without sudo authority, and load the reviewed
[qualification profile](../scripts/ci/constructicon-m8-bwrap.apparmor). A hosted
runner guard precedes provisioning. No sysctl or existing profile is changed.
The test and a private copy of bubblewrap live in a root-owned directory; the
test executes with a fresh environment as the service account. The runtime
imports no CI code, and no Windows security setting is modified.

The profile attaches only to `/opt/constructicon-m8-qualification/bwrap`, not
the system executable. The launcher may establish its namespaces; at payload
exec, an additional profile denies capabilities and further user namespaces.
Stacking retains the original confinement under no-new-privileges. A mandatory
named transition has no executable-profile search, fallback, or local policy
override. The launch profile permits namespace setup; the fixed bubblewrap
recipe, not these broad file rules, supplies filesystem/network isolation. Loading
uses `apparmor_parser --add --skip-cache`: an existing name is an error, not
permission to replace a profile. The probe verifies reviewed executable and
policy hashes and records the distribution-supplied AppArmor ABI digest.

The probe requires Ubuntu 24.04, enabled AppArmor, the global user-namespace
restriction still set to 1, non-set-ID bubblewrap, and effective policy
attachment. It attempts a benign launch with separate user/mount/PID/IPC/UTS/
network namespaces, no-new-privileges, dropped capabilities, and a read-only
sentinel. It checks namespace identities, UID/GID, private loopback, absent
host home/sysfs, denied writes, and denied nested bubblewrap. The kernel must
report the exact two-profile stack in enforce mode. A byte-identical
copy outside the policy's attachment path must fail with a permission refusal.
That negative probe never removes the system's policy.

UID/GID map columns are namespace-relative. The pinned bubblewrap's `--dev`
setup maps the service identity through zero in an intermediate namespace;
zero there is not host root. Nested bubblewrap must fail specifically at
namespace creation. The unprofiled copy may instead be stopped by capability
restrictions at loopback setup; its exact refusal stage is recorded. Only the
named operation's permission error counts, not an arbitrary failed command.

Only fixed benign diagnostics run here. Bounded subprocess timeouts and a
ten-minute job deadline are not a proof of the future hostile-output pump or
process-tree teardown. This diagnostic root mounts installed `/usr` read-only;
PR B still needs its small, immutable, content-pinned runtime root. The payload
is this PR's fixed diagnostic code, not a workload repository or model output.

The job uploads only `m8-qualification.json`, retained for seven days. It
contains selected public host facts and bounded diagnostics, not an environment
dump or a reusable credential. Unsupported or incomplete probes exit nonzero;
`qualified: false` is evidence of refusal, never a passing skip. Missing evidence
also fails artifact publication. Job and commit links belong in the PR report.

Local unit checks exercise refusal logic on Windows; they cannot supply Linux
evidence. After merge, `workflow_dispatch` allows requalification without a
code change. A green result qualifies only the observed prerequisites on that
job's host. It does not replace any accepted M8 physical test or provide an
always-on host for parked runs. No gateway has been provisioned.

Implementation references: [bubblewrap 0.9.0](https://github.com/containers/bubblewrap/blob/v0.9.0/bubblewrap.c)
for its device-setup mappings; [Linux UID maps](https://man7.org/linux/man-pages/man7/user_namespaces.7.html)
for reader-relative columns; [AppArmor exec transitions](https://github.com/torvalds/linux/blob/v6.17/security/apparmor/domain.c)
for named-stack selection versus a leading-`&` executable attachment search.

## PR B: the separate containment gate

`M8 Linux containment` provisions its own scoped policy and immutable closure
under `/var/lib/constructicon-m8-launch`. It does not borrow the qualification
root or its result. The `m8-service` account has no sudo and runs the native
launcher, workspace, closure and recorded-executor suites. Missing prerequisites
are failures when `M8_CONTAINMENT_REQUIRED=1`; ordinary unsupported-host skips
never satisfy this job. The assertion-only mutation inventory runs separately.

The closure contains curated Python/Git and their runtime libraries, plus the
standalone reaper. Content, topology and permissions contribute to its digest;
the service cannot rewrite it. Root-owned installation and every ancestor are
checked. Provisioning stays an explicit disposable-host operation, not code
an unavailable adapter runs to repair its environment.

The seven-day `m8-containment-*` artifact includes `m8-runtime.json` (the same
inventory hashed by the launcher, executable/policy/ABI digests), `m8-host.txt`
(commit, observed image/kernel/service/profile facts), and `boundary.json`
(selected child namespace, mount, descriptor, ID-map, device and limit facts).
It never captures the host environment or credentials. Read these alongside
the exact job's test and mutation results: files alone are not a passing gate,
and an earlier job does not qualify a later rolling image.

PR B's portion demonstrates the networkless boundary, not an always-on execution
host, provider gateway, live subscription login, candidate import, or gate
implementation. The additional slice proofs below are separately required.

## PR C: capture on the same native boundary

PR C extends this job with real Git pack verification, hostile staging
metadata, READ export, public capture/counterfactual lifecycles, repeated
cancellation, and literal controller-death seams. The paused publisher probe
lets recovery finish before the old process attempts its Git transaction.
A stopped trusted importer proves its inherited guard outlives Python owner
death; the successor cannot remove the quarantine until that child quiesces.
The separate `check_m8_capture_mutations.py` inventory changes code objects in
isolated test processes. Assertion failures count; skips, timeouts, or broken
mutation instruments do not. Both PR B and PR C inventories must pass.

Contained Git and its system-Python bootstrap use the launcher's existing
fixed-artifact rule too: executables and ancestors must be root-owned and
not service-writable. The application venv is not selected for bootstrap. A
service-owned executable is unavailable, even with its write bits cleared.
Operators replace tools between deployed worlds, not during a running one;
new installed content requires a new admitted revision. These are the same
trusted-runtime assumptions as the launcher, not protection from a privileged
operator modifying a live installation.

These additions do not offer a live model route or execute candidate gates
on the host. The original PR B evidence proves its boundary only; capture
claims require the new exact-head tests and their mutation results.

## PR D: checks on the same native boundary

PR D adds mount-free runtime identification, exact prepared-snapshot checks,
hostile repository code, stdout/stderr bounds, repeated cancellation and real
owner-death recovery. The public lifecycle proves heartbeat advancement while
checks run, then no successful checkpoint or attestation after cancellation or
ownership loss. Recovery before first verification needs no candidate or base.
It refuses a changed storage locator before cleanup. A positive public-control
lane also installs the gate's exact subject through the same-world merge effect.
Private launcher exit evidence distinguishes setup failure from legitimate
check exits 125--127 without trusting repository output.

`check_m8_gate_mutations.py` independently challenges phase separation, runtime
drift, physical READ mounts, output truthfulness, exact exported bytes, control
observation, cleanup/closure and assembly. The B, C and D inventories all remain
mandatory; a skip or broken instrument never counts as a killed mutation.
These are credential-free gate proofs, not provider-route or live-adapter proof.
