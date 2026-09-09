# M8 hosted-runner qualification

This is a prerequisite investigation, not the PR B containment gate and not a
live execution service. See [proposed ADR 0019](adr/0019-hosted-linux-runners-are-requalified-not-image-pinned.md).

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
named transition has no unconfined fallback or local policy override. Loading
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

Only fixed benign diagnostics run here. Bounded subprocess timeouts and a
ten-minute job deadline are not a proof of the future hostile-output pump or
process-tree teardown. This diagnostic root mounts installed `/usr` read-only;
PR B still needs its small, immutable, content-pinned runtime root. No model,
repository-controlled payload, or untrusted shell instruction executes in it.

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
