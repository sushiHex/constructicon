# 0019 — Hosted Linux runners are requalified, not image-pinned

Status: accepted, 2026-09-09; PR B's implementation proofs remain required.

## Decision record

Following PR #28's merge, the owner authorized the next four steps: record
this acceptance, start PR B, prove process lifetime and acquisition ownership,
then complete its Linux containment and review gates. This accepts standard
GitHub Actions as the evidence environment and the per-host qualification law
below. It does not credit qualification as production containment or authorize
a live provider, gateway, paid runner, or changes to the Windows host.

### Exact scope of supersession

This is an owner-authorized successor decision, not evidence that a rolling
runner satisfies the earlier pinned-image requirement. It supersedes only
the immutable CI-host-image selection in M8 rev 1 section 3.1 and its use as
the host prerequisite for PR B, as incorporated by ADR 0018. For this selected
environment, repeatable execution of the complete native proof suite on each
observed host replaces the promise of reproducing an identical VM image.

The archived plan and ADR 0018 retain their exact historical bytes. All other
requirements remain governing: the pinned runtime, launcher and policy closure;
non-root Linux execution; unchanged global restrictions; physical containment,
death/race and mutation proofs; and refusal when prerequisites fail. No earlier
host's result qualifies a later host. Gateway-only authentication is unaffected.
This ADR governs the named host-image conflict; it does not waive a proof or
grant the implementation discretion to change another frozen requirement.

## Context

The owner selected GitHub Actions on 2026-09-09: "Continue with GitHub Actions.
Use elegant implementation." No Hyper-V installation, separate machine, paid
runner, model credential, or gateway is authorized. The repository is public;
standard hosted runner compute is free, with artifact storage still bounded.

[ADR 0018](0018-live-executors-are-leased-contained-processes.md) and the
[frozen M8 plan](../plans/milestones/M8-live-executors-rev1.md) remain unchanged.
Their initial immutable Ubuntu CI-image assumption cannot literally be met by
a standard hosted runner: `ubuntu-24.04` fixes the OS release, not an image
build. Pro does not supply the larger-runner custom-image feature.

## Qualification decision

Separate the host we observe from the launch artifacts we control. Record the
exact hosted image, kernel, service identity, executable bytes, and effective
policy. Pin the reviewed bubblewrap package; PR B must additionally pin its
actual runtime root, launcher, and policy closure. Repeat physical proofs on
every supplied host. Changed or missing prerequisites refuse qualification;
no skipped Linux test counts as passing. A new image cannot inherit an old
image's physical evidence, and reproducing its exact VM is not promised.

Keep trusted CI provisioning separate from the non-root probe and from the
Constructicon installer/runtime. The first two hosted runs found AppArmor and
the global restriction enabled but no packaged or loaded bubblewrap profile;
both refused before namespace creation. The owner then explicitly authorized
the bubblewrap profile. Provision it only on the disposable hosted runner,
alongside the fixed package and non-sudo account. Do not change sysctls,
replace an existing profile, or modify Windows.

Attach the reviewed qualification profile to a private, root-owned copy of
the pinned executable. At payload exec, retain the launch profile and stack
a profile denying capabilities and further user namespaces. Require that
exact enforcing attachment and the refusal of an identical unprofiled copy.
Use an explicit named transition without fallback, and add policy without
using caches or optional local overrides. This is qualification-only policy;
PR B must still bind and prove its actual complete launch closure.

Windows keeps the cross-platform local verification gate. Native Linux CI
supplies the OS evidence; it is not described as having run on Windows. This
changes the location of development evidence, not the executor's architecture:
each Linux test owns its control process, journal, repository, and acquisitions
on that Linux filesystem. No remote executor, cross-job live process, state
transfer service, or Windows-path bridge is introduced.

## Proof boundary and sequencing

The qualification workflow is an investigation prerequisite, not PR B. Its
benign diagnostic root borrows installed userspace read-only; that userspace
is not the final pinned runtime. It exercises namespace creation, a read-only
workspace, kernel-reported AppArmor attachment, and refusal without that
attachment. It does not establish complete host/FD exclusion, process-death
cleanup, runtime immutability, allocation races, or gateway conformance.

A positive result cannot enable a live provider. PR B's complete physical and
mutation gates remain mandatory, followed by C/D/E before live WRITE. This
acceptance permits hosted CI to supply those proofs, not inherit them from
qualification. The frozen plan is retained, not edited to claim it originally
specified this model.

## Sources

- [GitHub runner images](https://github.com/actions/runner-images): rolling
  image updates and image-version evidence in job logs.
- [GitHub billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions):
  standard public compute and separate storage limits.
- [Custom images](https://docs.github.com/en/actions/how-tos/manage-runners/larger-runners/use-custom-images):
  actual image-version pinning is a larger-runner feature.
- [Ubuntu AppArmor](https://documentation.ubuntu.com/security/security-features/privilege-restriction/apparmor/):
  profiles authorize unprivileged user namespaces.
- [AppArmor's bubblewrap profile](https://gitlab.com/apparmor/apparmor/-/blob/8e431ebcd915216a03ebc8d01e72b1741bb2f855/profiles/apparmor/profiles/extras/bwrap-userns-restrict):
  precedent for stacking a restricted payload profile under no-new-privileges.
  Our qualification profile uses a private attachment and denies child userns
  directly; it is not a copy or claim about the stock Ubuntu profile.
- [AppArmor parser](https://manpages.ubuntu.com/manpages/noble/man8/apparmor_parser.8.html):
  add-only loading and cache bypass.
