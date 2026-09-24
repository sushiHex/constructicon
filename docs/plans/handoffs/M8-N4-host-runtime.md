# M8-N4 host runtime: reviewed-artifact installation of the launch set

Status: design, implementation and bounded operator runbook for the host prerequisite of
[N4 (#77)](https://github.com/sushiHex/constructicon/issues/77). Base: `9006f93`.
It extends [M8-D2](M8-D2-host-installation.md) (#94, merged `8c1b14e`) and does
not redesign it. Authority: the owner's
[three-role/two-host decision](https://github.com/sushiHex/constructicon/issues/73#issuecomment-5752858107)
on #73 and the #94 ruling that **root on the private host executes no
repository code** (M8-D2, "Privilege boundary"). Nothing here authorizes a host
change: the runbook runs only under the separate authorization named in R8.

## Scope

M8-D2 installed the qualification set only and recorded the launch set as
"carried, not built" (M8-D2:19-22), because the runtime closure is copied from
the host's own `/usr` and git cannot cover it. This design installs the launch
set that the containment workflow provisions for every lane
(`m8-containment.yml:86-110`) and the pinned vendor inputs it acquires
(`:179-192`):

- the launch root, its bubblewrap copy and the launch AppArmor profile;
- the immutable runtime closure (Python, Git and their dynamic closure, the
  supervisor, the N4 proxy bridge and the reserved egress leaf) and
  `runtime.json`;
- the pinned Codex package and the pinned models catalog;
- the operator-store root and the `m8-service` account it names.

**Excluded, deliberately.** Everything CI provisions only to test: the
`unprofiled-bwrap` copy (`m8-containment.yml:99`, used only by
`test_linux_containment.py:1077`), the startup, placement and bridge fixture
images (`build_m8_startup_fixture.py`, which copies test code from `tests/`
into the image, `:36`, `:41-42`), the N3a store fixture
(`build_m8_store_fixture.py`) and the run-scoped evidence directory. Test code
never reaches the credential host. Publishing an operator-store bundle and the
production native image are settled by "Owner decisions" 1 and 4.

The CI guards stay byte-identical (`test_hosted_runner_guards_are_unchanged`).
No host marker exists.

## Artifact inventory

`L` is `/var/lib/constructicon-m8-launch`. `C` is one reviewed merge commit on
`main`. `$W` is the operator's private workspace for this set,
`$HOME/m8-launch`, separate from M8-D2's `$HOME/m8-host`.

| Destination | Owner:group, mode | Staged as | Provenance |
| --- | --- | --- | --- |
| `L` | root:root `0755`, exactly the six entries below | `install -d` | fixed |
| `L/bwrap` | root:root `0555` | host `/usr/bin/bwrap` | pinned digest `e3189038…30f71` (= `linux.py:37`) |
| `/etc/apparmor.d/constructicon-m8-launch` | root:root `0444`, loaded | `$W/staging/constructicon-m8-launch` | blob `C:scripts/ci/constructicon-m8-launch.apparmor` |
| `L/runtime/` | root:root; dirs and executables `0555`, other files `0444`, one symlink | `$W/staging/runtime/` | the closure rule at `C` applied to the host (next section) |
| `L/runtime.json` | root:root `0444` | `$W/staging/runtime.json` | computed from the four sources above plus the host ABI file |
| `L/native-codex/` | root:root; archive modes with group/other write and special bits cleared (`0755`/`0644`) | `$W/staging/native-codex/` | members of the tarball pinned `a822187e…ba1821` |
| `L/codex-models.json` | root:root `0444` | `$W/staging/codex-models.json` | pinned digest `d7136a41…ef6ee8` |
| `L/operator-stores` | root:`m8-service` `0750`, created empty | `install -d` | fixed; group = `m8-service`'s primary group |
| account `m8-service` | uid and gid non-zero, no supplementary group, locked password, no sudo | `useradd` in R10 if absent | observed |

Destinations and modes are constants in the script, held by tests equal to the
workflow's provisioning lines and to the fixture's store root
(`build_m8_store_fixture.py:18-19`, `:108-110`). **Values that already have one
reviewed home are derived from `C`'s tree, not mirrored:** the bubblewrap digest
(`BWRAP_SHA256`, `linux.py:37`), the in-runtime paths (`NAMESPACE_SCRIPT`,
`_supervisor.py:29`; `BRIDGE_SCRIPT`, `_egress_bridge.py:28`), and the Codex
tarball and catalog digests (`m8-containment.yml:185`, `:191`). The script reads
each blob at `C` through the same provenance chain and extracts the value with
one fixed pattern that must match exactly once; zero or two matches refuse. The
record names each value with its blob id. (M8-D2's qualification constant is
left as it is.)

The pinned Codex package holds exactly `bin/codex`, `bin/codex-code-mode-host`,
`codex-package.json`, `codex-path/rg`, `codex-resources/bwrap` and
`codex-resources/zsh/bin/zsh` plus their directories: only directories and
regular files, modes `0755` and `0644`, no link or special bit (read from the
downloaded archive on 2026-09-23, which hashed to the pin). Its
`codex-resources/bwrap` is a vendor bubblewrap build, executable by any local
account and unprofiled; under `apparmor_restrict_unprivileged_userns=1` it
cannot create a user namespace. CI installs the same file.

## Privilege boundary

The #94 ruling applies unchanged: root runs only stock tools; the reviewed
script runs unprivileged only, refuses effective uid 0, and is anchored by stock
git. This set adds one stock tool, `cp`, because two destinations are trees.

**Everything root runs** (a test pins the list, extending M8-D2's):

| Step | As root |
| --- | --- |
| R10 | `sudo -l -U m8-service`, `/usr/bin/passwd -S m8-service` (both reads), `/usr/bin/cat` of the profile list; only if R8 permits and R10 finds it absent, `/usr/sbin/useradd --create-home --shell /bin/sh m8-service` |
| R13 | `/usr/bin/cat` of the profile list, twice; `/usr/bin/install` six times; `/usr/bin/cp` twice; `/usr/sbin/apparmor_parser --add --skip-cache` once |
| On failure | `/usr/bin/cat`, `/usr/sbin/apparmor_parser -R` on the installed profile, `/usr/bin/rm -f`, `/usr/bin/rm -rf --one-file-system` on `L` only |

**Why `cp -R -P --preserve=mode --no-target-directory` is safe here.** GNU
coreutils 9.4 `cp -R` does not follow symbolic links in the source
(`doc/coreutils.texi:9165-9166`), and `-P` says so explicitly, so a link in
staging is copied as a link, never through. `--preserve=mode` preserves mode
bits and, if possible, ACLs (`:9060-9065`); it does not preserve ownership, so
root's copy is owned by root, and it does not preserve extended attributes, so
no file capability crosses. A POSIX ACL cannot grant more than its mask, which
the group bits show, so the exact-mode checks cover it (M8-D2's ACL argument).
`--no-target-directory` makes an existing destination directory fail instead
of nesting; the judge also proves absence. Special files are recreated by type
(`:9169-9170`), so the judge requires every staged entry to be a directory,
regular file or the one fixed symlink, and `verify` refuses anything else.

The destination side is M8-D2's argument: every ancestor of `L` and of the
profile is a real, root-owned directory no other account can write, so between
judgement and root's writes no other account can place or swap anything there.
The source side is M8-D2's custody proof of `$W`: only the operator and root can
change staging. `cp` traverses that operator-owned tree as root, so an operator
racing the copy could make root read a file the operator cannot; the operator
already holds sudo, so that is not an escalation, and `verify` compares the
installed tree with an expectation it recomputes, never with staging.

**The root tools' custody.** Before root's first write the judge proves that
`/usr/bin/install`, `/usr/bin/cat`, `/usr/bin/cp`, `/usr/sbin/apparmor_parser`
and `/usr/bin/bwrap` are root-owned regular files that group and others cannot
write, under root-only ancestors (M8-D2's `require_root_alone`). R10's and R13's
first `cat` run before that proof and only read, as in M8-D2.

**The dependency resolver's custody.** The closure's composition depends on the
program that resolves shared-library dependencies, which the stage, judge and
verify all run, so a replaceable resolver would corrupt all three alike. CI runs
bare `ldd` from `PATH` (`build_m8_runtime.py:50`). `ldd` is a bash script whose
work is to run the dynamic loader in trace mode, so the shared plan runs the
loader directly: `/lib64/ld-linux-x86-64.so.2 --list <binary>`, in the
script's fixed environment. It runs by that canonical path, as ldd does,
because the trace names the loader by the path it was started as. The links
along that path (`/lib64` on a merged-`/usr` host) sit in root-only directories.
That removes bash and the `ldd` script from the trusted set. It leaves one
executable, whose real path gets the same custody proof as the root tools,
together with `/etc/ld.so.cache`, which decides resolution. A bounded ELF resolver was rejected: it would reimplement the
loader's search order and could only diverge from CI. CI's builder makes the
same call through the shared plan, so every lane runs on a `--list`-resolved
runtime. That the switch changes nothing is shown separately: a foundation-lane
test requires the resolved path set from `--list` to equal `/usr/bin/ldd`'s for
every closure binary on the hosted image.

## Provenance: what is pinned and what is observed

| Input | Pinned in reviewed source at `C` | Observed on the host and recorded |
| --- | --- | --- |
| script, launch profile, supervisor, bridge | raw blobs, mode `100644`, `C` on `main`'s first-parent line (M8-D2's chain) | - |
| the whole reviewed tree | R8: `C`'s tree equals the reviewed PR head's tree | - |
| host bubblewrap | `BWRAP_SHA256`, read from the blob `C:…/linux.py` (`:37`) | - |
| Codex package | tarball sha256, read from the blob `C:.github/workflows/m8-containment.yml` (`:185`); member set, types and modes follow from the digest | - |
| models catalog | sha256, read from the same workflow blob (`:191`) | - |
| the closure's composition | the closure rule: which binaries, which library tree, which exclusions, loader `--list` resolution, fixed in-runtime entries and modes | the resolved file list |
| the closure's bytes | - | each file's sha256, its real source path, the owning package and version from dpkg's database, and whether dpkg's recorded digest matches |
| `runtime.json` | its keys and computation | `runtime_digest`, the ABI file digest |
| `m8-service` | name and required posture | uid, gid, groups |
| loaded profiles | the two required names | root's `cat`, operator-supplied (M8-D2's limit) |

**The closure problem, and the choice.** The closure has no reviewed digest:
it is the host's own Python, Git and libraries. It cannot come from git, and
root may not run the CI builder. Options considered:

1. **Chosen: an unprivileged stage with recomputation.** The reviewed script's
   `stage-launch` assembles the closure into `$W/staging` as the operator.
   `judge-launch` independently recomputes the expected tree from the host and
   from git and requires staging to equal it; root copies staging with two
   `cp` commands; `verify-launch` recomputes again and compares the installed
   tree. No manifest is trusted: every comparison is against a recomputation
   from the sources (git blobs, pinned digests, root-owned host files), which is
   how M8-D2's `verify` compares with git rather than with staging.
2. **Rejected: pin the closure digest in source.** The hosted image and the VM
   differ in package versions, and every Python, libc, OpenSSL or Git security
   update would need a pull request before the host could be reinstalled.
3. **Rejected: pin package versions in source.** The same churn. H3 already
   makes a change to the closure's Python or Git a requalification trigger; the
   record carries the versions, and a stale host fails `verify-launch`.
4. **Rejected: rebuild from signed `.deb` files.** Strongest provenance (apt's
   signed Release, then sha256, then the package), but it needs an apt keyring
   trust path in the script, and superseded security versions leave the
   archive, so a later `verify` could not refetch them.
5. **Rejected: a staging manifest** (consistency, not provenance, M8-D2:143-145)
   and **root extracting the vendor tarball** as CI does (`:187`): root would
   parse an archive. The script extracts it unprivileged instead.

**Package attribution.** For each host-derived file the script records the
owning package and version and compares the bytes with dpkg's recorded digest
(`/var/lib/dpkg/info/*.md5sums`, or the conffile digest in
`/var/lib/dpkg/status`), reading dpkg's database directly, with its custody
proved. `/usr`-merge aliases (`/lib` and `/usr/lib`, `/lib64`, `/bin`) are
matched in both spellings. A **mismatch refuses**: a package claims the file
and the bytes differ. A file no package claims is recorded as `unattributed`,
listed (bounded to 64 paths plus a count) and allowed, because some files are
created by maintainer scripts rather than shipped; which files these are on the
VM is not yet observed. The attribution is evidence, not the trust anchor. The
anchor is custody: every host source, resolved to its real path, is a regular
file owned by root that group and others cannot write, under root-only
ancestors, so no account but root can have changed it. MD5 is dpkg's own
format and serves only to detect a modified package file; a hostile root is
under the #73 ceiling.

## The closure rule, shared with CI

The rule moves out of `build_m8_runtime.py` into the stdlib-only script as one
function that returns a plan: an ordered list of entries, each with its
in-runtime path, kind, final mode and source (a host path, a blob, an empty
file, a directory or a link target). It is the current rule exactly
(`build_m8_runtime.py:38-75`): `/usr/bin/python3.12`, `/usr/bin/git`, the
`/usr/lib/python3.12` tree copied without `__pycache__`, `test`, `tests`,
`ensurepip` and `idlelib`, the dependency closure of the two binaries and of
every `*.so` under the **original, unfiltered** `/usr/lib/python3.12` tree
(CI copies the filtered tree at `:43-47` but enumerates `*.so` over the
unfiltered one at `:48`, so a library needed only by an excluded directory's
extension is still in the closure), the `usr/bin/python3 -> python3.12` link,
the supervisor and bridge at their fixed paths, the `proc`, `dev`, `tmp`,
`workspace` and `vendor-store` directories, the empty `vendor-egress.sock`, and
the final `0555`/`0444` modes. A portable test pins the unfiltered enumeration
with a fixture tree whose excluded directory holds the only extension needing a
given library.

`build_m8_runtime.py` keeps its guard bytes and its root writer, and takes its
entry list from that function, so every CI lane runs on a runtime built by the
host's rule. The host writer (`stage-launch` as the operator, then root's `cp`)
is the only difference, and the parity test below checks it on the hosted
image. The loader runs as a child of the script in the script's fixed
environment, so `LD_LIBRARY_PATH` and similar variables never reach it; CI's
`sudo` resets the environment likewise. The one behavioural change to CI's
builder is `ldd` → the loader's `--list`, which the parity test and every CI
lane then exercise.

`runtime.json` has CI's keys (`build_m8_runtime.py:79-87`): `runtime_digest`,
`entries`, `bubblewrap_sha256` (the pin), `apparmor_policy_sha256` (the blob's
digest) and `apparmor_abi_sha256` (`/etc/apparmor.d/abi/4.0` as observed). The
script computes `runtime_digest` with a stdlib copy of the identity law
(`core/identity.py:160-179`) over a stdlib copy of `runtime_inventory`
(`linux.py:72-102`); a portable test holds both equal to Constructicon's on the
same tree.

## Commands and verification order

One script, `scripts/ci/m8_host_artifacts.py`, extended. `judge` and `verify`
keep their command line and behaviour for the qualification set, with one
narrowing: `judge` now refuses only its own two profile names, so a loaded
launch profile does not block reinstalling the qualification set. New commands:

- **`stage-launch C W`** writes only under `$W/staging`, with
  `O_CREAT|O_EXCL|O_NOFOLLOW`, creating directories owner-only and setting
  their final modes after their contents. It refuses as root, requires custody
  and provenance, requires `$W/codex.tar.gz` and `$W/codex-models.json` to match
  their pins before reading them further, and extracts the archive itself,
  refusing any member that is not a directory or regular file, any absolute or
  `..` name, and any duplicate. It prints the plan's record.
- **`judge-launch C W`** never writes. In order: effective uid is not 0;
  custody of `$W` (M8-D2 check 2); provenance of the six blobs and the
  script's self-check; both pins; `m8-service` exists with non-zero uid and
  gid, its primary group named `m8-service` and no supplementary membership;
  every host source's custody and attribution; staging equals the recomputed
  expectation exactly (the same entry set, and for each entry its kind, mode,
  sha256 or link target), including `runtime.json`'s bytes; the custody of the
  root tools, bubblewrap, the loader and `/etc/ld.so.cache`, and the bubblewrap
  pin; `L` and the profile are
  absent (`ENOENT` only); their ancestors are root-only; the profile list is
  bounded and well formed and names neither `constructicon-m8-launch` nor
  `constructicon-m8-workload`. `ready` becomes `true` only as the last
  statement.
- **`verify-launch C W`** never writes and never reads staging. It repeats the
  uid, custody, provenance, pin, account and host-source checks, recomputes the
  expectation, then observes every destination freshly with `lstat` and
  `O_NOFOLLOW|O_NONBLOCK` opens: `L`'s exact listing; each tree entry's kind,
  uid 0, exact mode and content; `runtime.json`'s exact bytes (which, with the
  exact tree, implies its `runtime_digest` matches the installed tree, so no
  separate digest check exists); `operator-stores` as a directory owned by root with the
  `m8-service` gid and mode `0750` (its listing is recorded, not assessed);
  root-only ancestors; and both `constructicon-m8-launch (enforce)` and
  `constructicon-m8-workload (enforce)` in the saved list. `installed` becomes
  `true` only as the last statement.

Records keep M8-D2's shape: the verdict defaults to `false`, the exit status
follows it, and a failure itemizes fresh `observed` state. Trees are summarized
so the record stays bounded: entry count, inventory digest and at most 32
differing paths with their expected and observed facts.

## Root's sequence (R13)

```bash
sudo /usr/bin/install -d -o root -g root -m 0755 /var/lib/constructicon-m8-launch
sudo /usr/bin/install -o root -g root -m 0555 /usr/bin/bwrap /var/lib/constructicon-m8-launch/bwrap
sudo /usr/bin/install -o root -g root -m 0444 "$W/staging/constructicon-m8-launch" /etc/apparmor.d/constructicon-m8-launch
sudo /usr/bin/cp -R -P --preserve=mode --no-target-directory "$W/staging/runtime" /var/lib/constructicon-m8-launch/runtime
sudo /usr/bin/install -o root -g root -m 0444 "$W/staging/runtime.json" /var/lib/constructicon-m8-launch/runtime.json
sudo /usr/bin/cp -R -P --preserve=mode --no-target-directory "$W/staging/native-codex" /var/lib/constructicon-m8-launch/native-codex
sudo /usr/bin/install -o root -g root -m 0444 "$W/staging/codex-models.json" /var/lib/constructicon-m8-launch/codex-models.json
sudo /usr/bin/install -d -o root -g m8-service -m 0750 /var/lib/constructicon-m8-launch/operator-stores
sudo /usr/sbin/apparmor_parser --add --skip-cache /etc/apparmor.d/constructicon-m8-launch
```

The runbook runs it as one `&&` chain behind the judge (R13). Modes never depend
on the umask (`sudo` may widen it): `install` applies `-m` explicitly and `cp`
applies the staged modes, which the judge proved; a test runs the sequence
under umask `0277`. The profile loads last, as in M8-D2, so a refused load
leaves every file in place for `verify-launch` to itemize.

## Failure and recovery

No automatic rollback. A failing command's record carries the verdict `false`,
the error and fresh `observed` state, and exits 1; a rerun of `judge-launch`
refuses while any residue exists. Recovery is one of:

- the `pre-m8-runtime` checkpoint (R9), permitted because no vendor store
  exists yet (H2); or
- the fixed removal (runbook, "On failure"), after which `verify-launch` must
  itemize every destination as absent and no launch profile loaded.

The fixed removal deletes `L` recursively, including `operator-stores`. It is
valid only before the first vendor login. Once a binding exists, removing or
replacing the store is ADR 0021 maintenance under H2, never this runbook.

## How N4's lane consumes it

N4's controller constructs the production launcher exactly as the containment
fixture does (`test_linux_containment.py:51-63`), with pinned rather than
re-read values:

- `runtime_root = L/runtime`, `expected_runtime` = `runtime.json`'s
  `runtime_digest`, which `verify-launch` recomputed from the installed tree;
- `bubblewrap = L/bwrap`;
- `policy = /etc/apparmor.d/constructicon-m8-launch`, and
  `expected_policy_sha256` = the blob digest in the `verify-launch` record, not
  a digest read back from the file;
- `M8_OPERATOR_STORE_ROOT = L/operator-stores`, which satisfies
  `_open_trusted_directory` (`operator_store.py:305-330`).

`check_artifacts` (`linux.py:290-303`) re-proves custody and the runtime,
bubblewrap and policy digests before every launch, and the physical probe
(`linux.py:410-452`) requires the child attachment
`constructicon-m8-launch//&constructicon-m8-workload (enforce)`. That probe is
the behavioural proof of the loaded launch policy, as the qualification probe
is for M8-D2; it is N4's first action on the host. After a reboot or any H3
trigger, `verify-launch` and the probe run again under a new authorization.

`L/native-codex` and `L/codex-models.json` are the pinned vendor inputs, laid
out as CI lays them out. The production launcher can only execute what is
inside its runtime root (`linux.py:331`, the root bound read-only at `/`), and
CI builds a runtime containing the vendor only as a test fixture. The in-zone
production image is therefore N4's to define; when it is, it becomes one more
staged tree in this inventory, built by the same stage, judge and verify.

## What CI can and cannot prove

**Can, on the hosted `ubuntu-24.04` image:**

- that every lane's runtime is built by the host's closure rule (shared
  function);
- **parity**: in the foundation lane, as `m8-service`, a test stages the plan
  unprivileged (blobs read from the checkout), copies it with the real
  `/usr/bin/cp -R -P --preserve=mode --no-target-directory`, and requires the
  copy's inventory (names, modes, contents and links; the inventory has no
  owner field) and `runtime.json`'s values to equal CI's installed runtime and
  `runtime.json`. That makes the host path and the CI path produce the same
  runtime digest on the same image;
- every portable and Linux unit test and the mutation inventory (`verify.yml`
  runs it on Linux as a non-root user).

**Cannot:** that `C` is on the real `main` (tests use temporary repositories);
real root ownership through `sudo` (tests use M8-D2's uid view and drop
`-o root -g root`); the VM's package set, which differs from the image; dpkg
attribution on the VM, including which files are unattributed; the kernel's
profile list and `apparmor_parser` load on the VM; the launcher probe on the
VM; and boot-time profile loading. R13's and N4's first host run are their
first execution; the R9 checkpoint makes that recoverable.

## Test plan (as implemented)

In `tests/test_m8_host_runtime.py`, both directions from the first commit;
`tests/test_m8_host_artifacts.py` keeps M8-D2's suite.

**Portable (Windows and Linux).**
- Derived values: extraction from this repository's blobs yields exactly
  `linux.BWRAP_SHA256`, `NAMESPACE_SCRIPT`, `BRIDGE_SCRIPT`, and the workflow's
  two digests, the catalog's equal to `CATALOG_SHA256`. For every value, a blob
  that names it zero or two times refuses.
- The stdlib identity law and `runtime.json` equal Constructicon's
  `digest`/`runtime_digest` on the same tree and payload.
- The closure plan over a fixture host with a stand-in loader trace: the exact
  file, link and directory set, modes, first-source rule, and sort order.
  IGNORED names are never copied, but `libonly.so.1`, needed only by an
  extension under the excluded `test/` directory, is present, so enumeration
  runs over the unfiltered tree. A trace with `not found`, or a nonzero exit,
  refuses; a supervisor path that would replace a runtime file refuses.
- The vendor plan: the accepted member set, with implicit parents and CI's
  `go-w` masking. Each of a symlink, hard link, FIFO, character device,
  absolute name, `..`, a climbing path, a duplicate, a setuid member and a
  sticky directory refuses.
- dpkg attribution against a fixture database: the owned and matching file,
  the pre-merge spelling, the conffile, the unattributed file, the removed
  package ignored. A modified file refuses for each of the three attribution
  routes, and the unattributed list is bounded at 64.
- Tree comparison reports a mode, content, missing, extra and owner
  difference. The service account refuses uid 0, gid 0, a foreign primary
  group and a supplementary group.
- Assessment: the reviewed set is accepted; each of thirteen observed facts is
  required; both launch profiles must be loaded in enforce mode.
- The command record: each launch command reports its own verdict and exit
  status, and a verifier's own observation (with its tree differences)
  survives its failure.
- Repository pins: the launch layout equals CI's provisioning lines, the store
  fixture's root and mode, and the profile's and launcher's names. The CI
  builder takes the shared plan and no longer names `ldd`. The foundation
  lane runs both parity tests as `m8-service`. R13 is the inventory, in order.
  Every `sudo` in the runbook is an allowed stock tool. R11 lists the six
  blobs. Only `materialize` writes, only the stager calls it, and its open is
  `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW` (an AST walk).

**Linux only (skipped elsewhere).** This runs on a temporary host with a
stand-in loader (a shell script printing the loader's trace format), fixture
dpkg tables, M8-D2's uid view extended to group ids, and real coreutils
`install` and `cp` for root's sequence.
- Accepting: stage, judge, R13, verify; the same under umask `0277`; and the
  accepting control, where a valid installation verifies with staging deleted.
- The stager refuses an existing staging, and the writer never overwrites.
  Every launch command refuses to run as root.
- The judge refuses, each asserting its message, each of these staged faults:
  a runtime byte, a mode, an extra entry, a missing entry, a FIFO, a
  retargeted link, a vendor member, `runtime.json` and the profile. It also
  refuses sixteen preconditions: the tarball and catalog pins, the account, a
  host source's owner and parent, the loader and its cache, `cp` unsafe and
  missing, bubblewrap, an existing launch root or profile, an unsafe ancestor,
  a loaded launch or workload profile, and a dpkg mismatch.
- `verify-launch`: staging modified after judgement is caught, with the
  differing path itemized; every prefix of R13 is never installed and blocks a
  rerun; a refused profile load. Drift is refused for each of thirteen cases,
  among them a host package update, which leaves the installed closure intact
  and changes only the recomputed plan. With nothing installed, every
  destination is itemized as absent. Tree summaries are bounded. A host source
  resolving outside the root refuses.
- M8-D2's qualification `judge` accepts while the launch profiles are loaded.

**Linux, foundation lane as `m8-service` with `M8_CONTAINMENT_REQUIRED=1`:**
`test_the_host_writer_reproduces_the_ci_runtime` (the stager's writer, then the
real `cp`, equal CI's installed runtime inventory, and the recomputed
`runtime.json` equals CI's) and `test_the_loader_list_resolves_as_ldd_does`.
Both fail rather than skip when `M8_LINUX_ROOT` is absent.

## Mutation list (as implemented)

In `scripts/check_m8_host_artifact_mutations.py`; each must be killed by
assertion. Portable:

| Mutant | Killed by |
| --- | --- |
| a derived value accepts two matches | the two-match case |
| the account check always passes | the four refused accounts |
| an archive member of any type, with a special bit, duplicated, with an unplain name, or climbing `..` | the unsafe-member cases |
| archive modes not masked | the planned package's `0755`/`0644` |
| an unresolved dependency accepted | the `not found` trace |
| `*.so` enumerated over the filtered tree | `libonly.so.1` |
| IGNORED names copied | the closure plan |
| a dpkg mismatch accepted; merged-usr spelling not matched; unattributed list unbounded | the three attribution tests |
| tree owner or mode not compared | the difference cases |
| an installed tree, the store group, a destination owner, or the enforce-mode profiles not assessed | the fact and profile cases |
| identity-law separators changed | the digest equality |
| a verifier's observation overwritten on failure | the surviving-observation test |
| the three command-record mutants carried from M8-D2, re-anchored to `VERDICTS` and `observer` | the record tests |

Linux only (NOT PROVEN on Windows, killed only by the Linux `verify.yml` run):
staged trees not compared; `cp` dropped from the checked root tools; launch
destinations not required fresh; a loaded launch profile not refused; host
sources' custody skipped; the loader's custody skipped; the writer truncating
instead of `O_EXCL`; verify reading staging instead of recomputing (killed by
the staging-deleted accepting control); tree summaries unbounded; and M8-D2's
judge refusing every `constructicon-m8-*` again.

**One check per custody fact.** The first Linux run found the host-source and
loader custody mutants alive. The attribution's reads re-proved every source's
custody, the loader among them, so either check could be removed unobserved.
The attribution now proves custody only of dpkg's database. The loader test
also asserts that the loader never ran, because its custody must be proved
before it executes, not merely before the judge answers.

**Not mutated, with the reason.** There is no separate `runtime_digest` check,
because exact `runtime.json` bytes and the exact tree imply it. The launch
destinations' ancestor checks in `judge-launch` and `verify-launch` are kept,
but on this layout the host sources' custody walks the same ancestors (`/`,
`/etc`, `/var/lib` through dpkg's database) first, so removing them is
unobservable and a mutant would survive for that reason alone.

## Changes

- `scripts/ci/m8_host_artifacts.py`: the launch inventory, derived values, the
  shared closure plan with the loader's `--list`, dpkg attribution, the vendor
  plan, the stdlib identity law and inventory, the one writer, the three
  commands, and the narrowed qualification profile check.
- `scripts/ci/build_m8_runtime.py`: entries from the shared plan through the
  same writer; guard and output keys unchanged.
- `scripts/ci/constructicon-m8-launch.apparmor`: the header comment now names
  the private host (owner decision 3). Its digest changes; nothing pins it.
- `tests/test_m8_host_runtime.py` (new), `tests/test_m8_host_artifacts.py`
  (the writer pin and the narrowed judge), `tests/test_m8_containment_workflow.py`
  (the foundation step's inventory), `scripts/check_m8_host_artifact_mutations.py`.
- `.github/workflows/m8-containment.yml`: the two parity tests in the
  foundation lane's `m8-service` step. No provisioning line changes.

**Local evidence (Windows, before any Linux run).** `uv run verify`: ruff,
mypy and import-linter passed. Pytest gave 2,974 passed and 618 skipped; the
one failure was this document's manifest digest before its refresh. The
inventory killed all 41 portable mutants (M8-D2's 19 and this change's 22).
The 28 Linux-only mutants (M8-D2's 19, including the narrowed judge, and this
change's 9) report NOT PROVEN here, which is not evidence. **Unexecuted until
Linux CI runs:** every Linux-only test in both files, both foundation-lane
parity tests, the CI builder on the shared plan, and those 28 mutants.

## Limits

- **Stage, judge and verify share one reviewed file.** Their independence comes
  from their inputs (git, pinned digests, root-owned host files), not from
  separate code. R11's stock-git facts anchor that file, as in M8-D2. Unlike
  M8-D2, stock git does not extract the staged blobs; the script does.
- **The closure is observed, not pinned.** Its trust is "the host's
  root-owned, package-attributed userspace at install time". Unattributed files
  are allowed and listed.
- **`verify-launch` recomputes from the host**, so after any package update to
  the closure's inputs it reports a mismatch. That is H3's trigger working;
  the remedy is removal and a fresh install under a new authorization. The
  installed closure itself is frozen and does not follow host updates.
- **The loaded policy is shown behaviourally only** by the launcher probe in
  N4, not by `verify-launch`; the kernel exposes no profile source.
- **The profile list is operator-supplied** (M8-D2's limit).
- **`L/bwrap` carries a profile granting `userns`, `capability` and `mount`**
  (`constructicon-m8-launch.apparmor:5-17`) and any local account can execute
  it; its child is confined to the workload profile, which denies both. The
  host has one human account (H4).
- **Disk:** staging and the installed copy each hold about 340 MB of vendor
  package plus the closure. R10 checks free space.

## Owner decisions (relayed 2026-09-24)

Relayed to the implementing session by the orchestrator; not yet linked from a
GitHub comment, and the PR should link them.

1. **Store-bundle publication runs as root, as the root boundary's single
   named exception.** The #94 ruling (root executes no repository code)
   governs provisioning, where root is avoidable. Store custody is not: N3a's
   law makes the bundle root-owned so the runtime uid cannot alter descriptors
   (`operator_store.py:805-816`), and the #73 decision names "a vendor login
   under the maintenance/lock procedure" for the credential role. So the N3c
   offline helpers (`publish_descriptor_offline`, `maintain_offline`,
   `activate_offline`) may run as root, and nothing else of the repository
   may. They run only from provenance-verified blobs of `C` (the same stock-git
   proof as R11), through `/usr/bin/python3 -I`, never from a checkout. That
   procedure belongs to N4's runbook; this runbook runs none of them. The N4
   design at `a2b2004` (`M8-N4-state-review.md`, "Host-runtime interface
   required", item 4) still says the service user runs every offline helper.
   The two must be reconciled in N4's amendment.
2. **The controller environment is its own reviewed slice.** Repository code
   runs as `m8-service`, unprivileged: C's tree with hash-pinned dependencies
   from `uv.lock`, built unprivileged into staging, installed read-only and
   root-owned by stock `cp`, recomputed by a verifier, and needing no network
   at run time. It is split out of this change because a virtual environment
   is not relocatable (`pyvenv.cfg` and script shebangs carry absolute paths),
   the pinned tool (`uv` or pip) must itself be obtained and pinned on the
   host, and the wheels must match the host's Python 3.12 while CI uses 3.11.
   Its interface to this set is the same: a destination under root-only
   ancestors, a staged tree the judge compares, and a verifier that
   recomputes. **Preferred shape for that slice (orchestrator, 2026-09-24):** a
   flat, hash-pinned `--target` layout rather than a virtual environment, so
   no absolute path has to be relocated. The service user's interpreter runs
   it as `python3 -I` with one explicit `sys.path` entry. The host's pins for
   Python 3.12 are derived from `uv.lock` at `C`, not mirrored from CI's 3.11
   environment.
3. **The launch profile's header** is updated in this change. It no longer
   says "Provisioned only on the disposable Linux proof runner … No host-wide
   change"; it names this document. Nothing in the qualification or
   containment tests pinned that text.
4. **The in-zone vendor image follows N4's design, not this one.** N4's
   design at `a2b2004` ("Host-runtime interface required", item 1) requires
   these in the runtime root: the pinned `codex` binary (SHA-256
   `56ef98ab…62da`), the bridge, the supervisor, `/usr/bin/python3`, and the
   fixed model catalog at one fixed absolute path named by
   `model_catalog_json`. It forbids `/etc/codex`. It does not yet fix the two
   in-runtime paths, or whether the catalog is the pinned bytes or a derived
   form. **Marked interface:** when N4 fixes them, they become entries of
   `runtime_plan` (its docstring says so), sourced from the verified archive
   member and catalog that this set already stages. CI's builder then gains
   them through the same shared plan, and the parity test covers them.
   Nothing is invented here: the runtime this change installs carries no
   vendor file, and `L/native-codex` and `L/codex-models.json` hold the pinned
   inputs as CI lays them out.

## Addendum: the controller environment (owner decision 2)

Status: design for the follow-on slice. Base: `e26f438` (#105 merged). The
same authority and ruling apply. Root runs one stock command, and the
reviewed script stages, judges and verifies unprivileged.

**What it is.** One tree, `/opt/constructicon-m8-controller` (`K` below),
which is the service user's single `sys.path` entry. It holds the
`constructicon` package from `C`'s tree and its runtime dependency closure
from `uv.lock` at `C`, unpacked flat, as `pip --target` would lay it out, with
no virtual environment, launcher script or absolute path inside. Owned by
root; directories `0555`, files `0555` if the source is executable and `0444`
otherwise (the runtime closure's rule). The ancestors `/opt` and `/` are
root-only (the qualification set already proves `/opt`).

**No installer tool on the host.** A wheel is a zip archive in a fixed layout
(PEP 427). Once its digest is pinned, installing it `--target` style means
unpacking it. So the reviewed script unpacks it with stdlib `zipfile`, and no
`pip` or `uv` has to be obtained, pinned or custody-checked on the host.
Considered and rejected:
- the distribution's `python3-pip`, which is one more package to require and
  a far larger unpacker than needed;
- a pinned `uv` binary, one more vendor artifact under the tarball discipline
  for a job `zipfile` does.

The unpack rules, each refusing:
- a member that is not a regular file or a directory. A zip symlink is
  `external_attr >> 16` of type `S_IFLNK`. A member with no type bits is a
  regular file, because some writers store only permission bits.
- more than 4,096 members; a member name over 255 bytes; a declared
  uncompressed total over 64 MiB, which is checked from the central
  directory before any byte is extracted and again while streaming; or a
  ZIP64 archive. None of the five wheels uses ZIP64.
- a name that is not plain and relative (the vendor plan's pattern, no `..`);
- a duplicate name inside the wheel, or across wheels and the package;
- any `*.data/` directory (scripts, headers, data; none exists in today's
  closure, so none is mapped);
- a wheel whose members differ from its own `RECORD`, in set or in any
  file's `sha256`. `RECORD` itself is the one unhashed entry.

**Selection from `uv.lock` at `C`** (stdlib `tomllib`, Python 3.11+):
- **Closure.** It starts at the package named `constructicon` with
  `source = { editable = "." }` and follows only `dependencies`: no
  `optional-dependencies` (the `mcp` extra) and no `dev-dependencies`. Today
  that is `pydantic`, `pydantic-core`, `annotated-types`, `typing-extensions`
  and `typing-inspection`.
- **Fail-closed rules.** A dependency entry with a `marker`, `version` or
  `source` qualifier refuses, and so does a name listed more than once in the
  lock. None occurs in today's closure, so no PEP 508 evaluator is written;
  the first conditional dependency makes the build refuse until one is
  reviewed.
- **Wheels.** Each package's `wheels` entries are parsed by filename (PEP 427).
  A compressed tag set expands to every (interpreter, abi, platform) triple,
  and a wheel is compatible if any expanded triple is. The accepted triples
  are an explicit subset of CPython 3.12's `sys_tags()` on this platform,
  never a product of independent lists:
  - `cp312-cp312-P`, `cp312-abi3-P`, and `cp3X-abi3-P` for 2 ≤ X ≤ 11, with P a
    platform tag below;
  - `cp312-none-P`, `py312-none-P` and `py3-none-P` for the platform tags;
  - `cp312-none-any`, `py312-none-any` and `py3-none-any`.

  The platform tags P are `manylinux_2_Y_x86_64` for 5 ≤ Y ≤ the host's glibc
  minor, plus the legacy aliases `manylinux1_x86_64` (2_5),
  `manylinux2010_x86_64` (2_12) and `manylinux2014_x86_64` (2_17), each
  admitted only when its glibc is within that bound. Anything else refuses,
  for example `py3-cp312-any`, `cp311-cp311-…`, `musllinux` and macOS.
- **The glibc minor is observed** (`os.confstr("CS_GNU_LIBC_VERSION")`,
  2.39 on Ubuntu 24.04) and recorded, and the major must be 2.
- **Exactly one compatible wheel per package, or refuse.** Today
  `pydantic-core` has exactly one, `cp312-cp312-manylinux_2_17_x86_64`, and
  the other four are `py3-none-any`.
- **Digest.** The wheel's `hash` in the lock (`sha256:…`) is the pin.
- **Interpreter.** The script requires that it runs as CPython 3.12
  (`sys.implementation.name`, `sys.version_info[:2]`), because it runs as the
  same `/usr/bin/python3` that will run the controller. The cp312 tags are
  therefore a statement about that interpreter, not a mirror of CI's 3.11.

**The package from `C`.** Every blob under `src/constructicon/` at `C`
(`git ls-tree -r`, mode `100644` only; any other mode refuses), extracted raw
by `cat-file`, lands at `constructicon/…`. No `dist-info` is written for it,
so `constructicon.__version__` reads `0+unknown` (`__init__.py:18-21`). Only
the MCP server's version string uses it (`api/mcp/server.py:52`), and N4 does
not.

**Acquisition (operator, stock `curl`).** A read-only command,
`controller-wheels C W`, prints one `sha256 url` line per selected wheel,
taken from the lock at `C`. The operator fetches each URL into `$W/wheels/`
with the same `curl -q --proto =https` as R11. The transport is untrusted; the
lock's digest is the authority.

**Commands** (the launch set's pattern, workspace `$HOME/m8-controller`):
- `stage-controller C W` writes `$W/staging/controller` through
  `materialize`.
- `judge-controller C W` recomputes the plan and compares staging exactly
  (names, modes, contents, owner = operator). It proves `cp`'s custody and
  that `K` is absent with root-only ancestors.
- `verify-controller C W` recomputes the plan from `C` and `$W/wheels/`,
  never from staging, and compares the installed tree exactly (owner root).

What they recompute is the lock at `C`, the package blobs at `C`, and each
wheel file matched against its pin. The unpacked tree is a pure function of
those three.

**Root's sequence** is one command:
`sudo /usr/bin/cp -R -P --preserve=mode --no-target-directory "$W/staging/controller" /opt/constructicon-m8-controller`.
The `cp` argument is the launch set's (see "Privilege boundary").

**How the service user runs it (the interface for N4).** One fixed command
shape, a constant in the script and pinned by a test:

```
/usr/bin/python3 -I -S -B -c 'import sys; sys.path.insert(0, "/opt/constructicon-m8-controller"); import runpy; runpy.run_module(sys.argv[1], run_name="__main__", alter_sys=True)' <module> <arguments>
```

- `-I` drops the user site, `PYTHON*` and the script directory.
- `-S` also drops the system `dist-packages`, so no distribution package can
  shadow a pinned one.
- `-B` stops the interpreter trying to write `__pycache__` into the
  read-only tree.
- `sys.argv[1]` names the module to run.

The remaining `sys.path` is the interpreter's standard library and `K`.

**Behavioural proof on the host.** After `verify-controller`, the runbook
runs a fixed import check as `m8-service` (`sudo -u m8-service`, never root)
with the shape above. The module is `constructicon.substrate.executors.linux`
plus `pydantic_core`. The check prints each imported module's `__file__` and
requires every one to be under `K` or the interpreter's standard library.

**CI proof (verify lane, Linux, unprivileged).** A test gated on
`M8_CONTROLLER_REQUIRED=1` does the following on `ubuntu-latest`, which has
`/usr/bin/python3.12`:
1. It selects the wheels from this checkout's `uv.lock` for 3.12 and the
   runner's glibc, and downloads them with `urllib`. The download is test
   code, not the script.
2. It verifies them and materializes the plan through the script's writer,
   then copies the tree with the real `cp` flags.
3. It runs the fixed command shape under `/usr/bin/python3.12` to import
   every module in the script's `PROOF_MODULES`. Today these are
   `constructicon.api`, `constructicon.substrate.executors.linux`,
   `constructicon.substrate.executors.codex` (the production adapter) and
   `pydantic_core._pydantic_core`. When N4 lands its lane module, the same
   change adds it to `PROOF_MODULES`, so this proof and the host check run
   the exact module N4 runs. A lane that needed a dependency outside the
   closure (the `mcp` extra, for example) would then fail here, closed.
4. It requires every module file to resolve under the copy or the standard
   library.

A new `verify.yml` step runs it after `uv run verify`, so it is the first
execution of the tree under the host's interpreter version.

**Failure and recovery.** Before the first vendor login:
- the `pre-m8-controller` checkpoint; or
- `sudo /usr/bin/rm -rf --one-file-system /opt/constructicon-m8-controller`,
  then `verify-controller` itemizes it as absent.

`K` holds no credential, so removing it later is not store maintenance.
Replacing it for a new `C` is removal plus a fresh install under a new
authorization, and it changes nothing in the launch set.

**What this slice does not do.** It adds no runtime network: every file is
local after R-acquisition. It builds no sdist, compiles nothing and runs no
wheel's code. It writes no `.pth` or entry-point script. It pre-compiles no
bytecode. And it does not decide N4's lane module, which is N4's
(`codex_lane` in N4's design); the command shape takes the module as an
argument.

**Test plan.**
- **Portable:**
  - lock parsing and the closure: the exact set; the extra and dev excluded;
    a marker, `version` or `source` qualifier refused; a duplicate name
    refused;
  - tag selection: each accepted tag, and a refusal for each of musllinux,
    macOS, `cp311`, `cp313`, a glibc too new, two compatible wheels, and no
    compatible wheel;
  - a digest mismatch;
  - the unpack rules, one test per refusal, and the `RECORD` set and digest;
  - the package extraction's mode refusal;
  - the command shape's constant;
  - the runbook's root command and every `sudo`;
  - the record's verdicts.
- **Linux:** stage, judge, cp and verify accept; a staged or installed drift
  is refused (a byte, a mode, an extra, a missing file); staging deleted
  still verifies; refusal as root.
- **Verify lane:** the import proof.

**Mutants:**
- the marker refusal, the duplicate-name refusal and the extra exclusion;
- each tag rule and the glibc bound;
- the one-compatible-wheel rule and the digest check;
- the symlink, `.data`, duplicate and `RECORD` checks;
- the source mode rule;
- the judge's comparison and verify's recomputation (killed by the
  staging-deleted control).

**Limits.**
- The closure is the lock's, as evaluated for 3.12 on x86_64 Linux. A lock
  change is a new `C`.
- `-S` is part of the interface: a controller that needed a system package
  would fail closed, not fall back.
- The glibc bound is observed, not pinned.
- `constructicon.__version__` is `0+unknown` on the host.

**The five wheels, as measured.** Measured on 2026-09-24 from the lock's URLs;
each file hashed to its lock digest:
- no `.data` directory, symlink, ZIP64, `.pth` file, directory entry or
  duplicate name;
- each `RECORD` lists exactly the other members;
- every member is `0644` except the `pydantic_core` extension module, which
  is `0755`;
- some members carry permission bits with no file type.

This is why the rules above refuse `.data` rather than map it, and why they
create parent directories implicitly.

**Design review (Codex, `gpt-5.6-terra`, high, job `job_c753c483b3f6`, the one
pass).** Each premise was reproduced before disposition.
- **Adopted.**
  (P2) The tag rule read as independent interpreter, abi and platform lists,
  so `py3-cp312-any` would have passed. It is now an explicit triple set,
  with compressed tags expanded.
  (P2) Extraction had no bounds. It now has member-count, name-length and
  64 MiB uncompressed caps from the central directory, streaming
  enforcement, and ZIP64 refusal.
  (P2) The import proof named modules other than the one N4 will run. It now
  imports `PROOF_MODULES`, which N4 extends with its lane module in the same
  change that adds it; the production adapter is imported already.
- **Rejected, with reasons.**
  (P1) "The commands and the CI proof do not exist at this commit." The
  commit was design-only, so this is the next step, not a defect in the
  design.
  (P1) "`cp --preserve=mode` can carry an ACL that grants `m8-service` write
  while the mode still reads `0555`." The premise is false for POSIX ACLs.
  Named-user and named-group entries are effective only up to the mask, and
  when a mask exists `st_mode`'s group bits are the mask (acl(5)). A `0555`
  mode therefore means no named entry can write, and the exact-mode check
  refuses anything wider. This is M8-D2's recorded ACL argument, which the
  launch set inherits unchanged. A default ACL on an installed directory
  affects only entries created in it later, and only root can create them.
- **Not verified by the review** and measured here instead: the wheels'
  contents (above). The host's ACL state, glibc and interpreter are observed
  by R-steps.

## Review dispositions

**Codex (`gpt-5.6-terra`, high, job `job_1e950b173db9`)**, one pass on the
design at `a8c8473`, the only round. Every premise was reproduced against source
before disposition. Codex could not reach GitHub, so its issue and PR facts were
unverified; none of its findings rests on one.

- **Adopted (introduced).**
  (P1) R8's diff fence listed six paths and omitted law-carrying files
  (`linux.py`, `core/identity.py`, the workflow's pins, the store contract), so
  a change merged into `C` outside the fence would pass R8. R8 now diffs the
  entire tree with no pathspec, and the values that already live in reviewed
  source (the bubblewrap digest, the in-runtime paths, the vendor digests) are
  derived from `C`'s blobs instead of mirrored.
  (P2) Bare `ldd` (`build_m8_runtime.py:50`) was outside every custody check,
  and stage, judge and verify would all trust the same replaceable resolver.
  The shared plan now runs the loader's `--list` by absolute path, with the
  loader and `/etc/ld.so.cache` custody-checked; bash and the `ldd` script
  leave the trusted set.
  (P2) Mutation 20 errored rather than failed an assertion. It is now killed by
  an accepting control: a valid installation with staging deleted must verify.
  (P3) Mutation 18 was masked by the inventory's own uid-0 check and mutation
  21 by the exact `runtime.json` comparison. The separate digest check is
  removed as implied; 18 now targets the single ownership check; 21 is replaced.
  (P3) R10's preconditions were printed, not tested. R10 is now one fail-fast
  chain with a numeric free-space test and an exact loaded-profile set.
  (P3) "The current rule exactly" was ambiguous about which tree the `*.so`
  enumeration walks. It is now specified as the unfiltered tree, as CI does
  (`:43-48`), with a test and a mutant.
- **Checked and not found.** The runtime inventory has no owner field
  (`linux.py:72-102`); the listed runtime components match the builder; the
  exclusions match their CI-only uses; `root:m8-service 0750` satisfies
  `_open_trusted_directory`; the store-publication question (now owner decision 1) was correctly framed; the narrowed
  qualification judge is safe at source level (distinct profile names). No
  non-operator bypass of root's `cp` was found, conditional on the judge being
  implemented as specified.
- **Not verified by the review.** Multi-profile `apparmor_parser --add`
  behaviour on Ubuntu 24.04, and whether the inventory suffices for N4's future
  production image.

---

# Operator runbook (R8-R14)

This extends M8-D2's R0-R7, which stay as written. Run only under R8's
authorization, in order, after #73's qualification evidence is recorded. On any
unexpected output, stop, do not retry, post the output to #77, then recover.
Commands run in the guest as the operator account, in one bash shell, unless
marked PowerShell.

## R8 — Separate authorization (required)

The N4 authorization on #77 covers login and startup, not this installation. A
written authorization on #77 must name:

- the VM `constructicon-m8`, the commit `C`, its PR, and that PR's green M8
  checks; `C` must be the PR's recorded merge commit;
- the workstation output of `git diff --exit-code <headRefOid> <C>` over the
  **entire tree, with no pathspec**, which must exit 0 and print nothing. The
  script, the launcher's laws (`linux.py`, `core/identity.py`), the workflow's
  pins and the store contract all bear on what the host accepts, and a fence
  listing some of them would have to be maintained as the set grows. An
  up-to-date PR merged by squash yields `C`'s tree identical to the reviewed
  head's (for example #95, AGENT_HANDOFF "N2 WRITE"). If the trees differ,
  stop: the PR must be updated and re-verified, and a new merge commit named;
- the permitted actions: `Start-VM`, `Stop-VM`; one checkpoint
  `pre-m8-runtime`; the operator's anonymous fetches from github.com and
  raw.githubusercontent.com; `useradd m8-service` if R10 finds it absent; R10 to
  R13 exactly as written, including every root command they name; and the
  recovery below. Deleting a checkpoint is not included;
- what stays forbidden: vendor login, running the Codex binary, inspecting a
  vendor credential or account, model calls, publishing an operator-store
  bundle, any checkout or clone with a working tree, git or any repository file
  run as root, the CI scripts, setting `RUNNER_ENVIRONMENT`, sysctl changes,
  `Save-VM`, and any change to M8-D2's installed set. The root boundary's one
  named exception, the N3c offline helpers run from provenance-verified blobs
  (owner decision 1), belongs to N4's runbook; this runbook runs none of them;
- how long the evidence is kept.

## R9 — Checkpoint, then start (PowerShell)

```powershell
Get-VM constructicon-m8 | Select-Object Name, State            # Off
Checkpoint-VM -Name constructicon-m8 -SnapshotName pre-m8-runtime
Start-VM constructicon-m8
```

Taken while the VM is off, before any vendor login (H2). It and
`pre-m8-artifacts`, if still present, must be deleted before N4's first login,
under a separate authorization.

## R10 — Preconditions (read-only, plus the account if absent)

One fail-fast chain: every stated precondition is a test, and R10 passes only if
it prints `R10 passed`. The informational lines (tool listing, package
versions, ancestor ownership) are evidence; the judge proves the ownership facts
again before any root write.

```bash
Q='constructicon-m8-bwrap (enforce)
constructicon-m8-payload (enforce)'
test "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns)" = 1 \
  && . /etc/os-release && test "$ID $VERSION_ID" = "ubuntu 24.04" && test "$(uname -m)" = x86_64 \
  && echo "e318903862396f96de3df57264e0158682b952fd3fb53ac23d876413e7b30f71  /usr/bin/bwrap" \
       | sha256sum --check --strict \
  && ls -lL /usr/bin/git /usr/bin/curl /usr/bin/python3 /usr/bin/python3.12 \
       /lib64/ld-linux-x86-64.so.2 /etc/ld.so.cache /usr/bin/install /usr/bin/cat /usr/bin/cp \
       /usr/bin/rm /usr/bin/chmod /usr/sbin/apparmor_parser /etc/apparmor.d/abi/4.0 \
  && dpkg-query -W -f='${Package} ${Version}\n' python3.12 libpython3.12-stdlib git libc6 \
  && id m8-service && test "$(id -Gn m8-service)" = m8-service \
  && test "$(id -u m8-service)" -ne 0 && test "$(id -g m8-service)" -ne 0 \
  && P=$(sudo /usr/bin/passwd -S m8-service) && echo "$P" && test "$(echo "$P" | cut -d' ' -f2)" = L \
  && S=$(sudo -l -U m8-service 2>&1 || true) && echo "$S" \
  && case "$S" in *"is not allowed to run sudo"*) true;; *) false;; esac \
  && stat -c '%U %a %n' "$HOME" /home / /var /var/lib /etc /etc/apparmor.d \
  && test "$(df --output=avail -B1 "$HOME" | tail -n 1)" -ge 2000000000 \
  && test "$(df --output=avail -B1 /var/lib | tail -n 1)" -ge 2000000000 \
  && test ! -e /var/lib/constructicon-m8-launch && test ! -L /var/lib/constructicon-m8-launch \
  && test ! -e /etc/apparmor.d/constructicon-m8-launch && test ! -L /etc/apparmor.d/constructicon-m8-launch \
  && test ! -e "$HOME/m8-launch" && test ! -L "$HOME/m8-launch" \
  && A=$(sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles) \
  && test "$(printf '%s\n' "$A" | grep '^constructicon-m8-' | LC_ALL=C sort)" = "$Q" \
  && echo "R10 passed"
```

The last test requires exactly the two qualification profiles, both in enforce
mode, and no other `constructicon-m8-*` profile. If `id m8-service` fails and R8
permits it: `sudo /usr/sbin/useradd --create-home --shell /bin/sh m8-service`,
then rerun R10. If any tool path differs from the paths above, stop.

## R11 — Provenance and pinned inputs (operator, stock tools only, no sudo)

Every step is chained and ends by printing `R11 complete`. `curl -q` ignores
`~/.curlrc`, and `env -i` drops proxy variables; the pinned digests, not the
transport, are the authority.

```bash
umask 077
C=<40-hex merge commit named in R8>
W="$HOME/m8-launch"
U=https://github.com/sushiHex/constructicon.git
T=https://github.com/openai/codex/releases/download/rust-v0.153.4/codex-package-x86_64-unknown-linux-musl.tar.gz
M=https://raw.githubusercontent.com/openai/codex/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/models-manager/models.json
E=(/usr/bin/env -i PATH=/usr/bin:/bin HOME=/nonexistent LANG=C.UTF-8 GIT_CONFIG_NOSYSTEM=1 GIT_GRAFT_FILE=/nonexistent)
G=("${E[@]}" /usr/bin/git --no-replace-objects "--git-dir=$W/source.git")
K=("${E[@]}" /usr/bin/curl -q --fail --location --proto =https --silent --show-error)
test "${#C}" -eq 40 && /usr/bin/mkdir "$W" \
  && "${E[@]}" /usr/bin/git init -q --bare "$W/source.git" \
  && "${G[@]}" fetch -q --no-tags "$U" +refs/heads/main:refs/heads/main \
  && "${G[@]}" rev-parse refs/heads/main && "${E[@]}" /usr/bin/git ls-remote "$U" refs/heads/main \
  && "${G[@]}" rev-list --first-parent refs/heads/main | grep -qxF "$C" && echo first-parent \
  && "${G[@]}" ls-tree "$C" -- scripts/ci/m8_host_artifacts.py scripts/ci/constructicon-m8-launch.apparmor \
       src/constructicon/substrate/executors/_supervisor.py src/constructicon/substrate/executors/_egress_bridge.py \
       src/constructicon/substrate/executors/linux.py .github/workflows/m8-containment.yml \
  && "${G[@]}" cat-file blob "$C:scripts/ci/m8_host_artifacts.py" > "$W/m8_host_artifacts.py" \
  && "${K[@]}" --output "$W/codex.tar.gz" "$T" \
  && "${K[@]}" --output "$W/codex-models.json" "$M" \
  && sha256sum "$W/m8_host_artifacts.py" "$W/codex.tar.gz" "$W/codex-models.json" \
  && echo "R11 complete"
```

The `rev-parse` and `ls-remote` SHAs must be equal; each of the six `ls-tree`
lines must read `100644 blob <oid>`, a tab, then its path. The tarball must hash
to `a822187e1a2420c61c5926721bfbd878701ed95547c9bb0d4de4498a16ba1821` and the
catalog to `d7136a413cfac1b5b1686d9e0dcc5c80ca05bebed5e9fc3911376561d0ef6ee8`.

## R12 — Stage (operator, no sudo)

```bash
J=(/usr/bin/python3 -I "$W/m8_host_artifacts.py")
test "${#C}" -eq 40 && "${J[@]}" stage-launch "$C" "$W" < /dev/null > "$W/stage.json"
echo "stage exit $?"; cat "$W/stage.json"
```

It must exit 0 with `"staged": true`, the package versions, and the
unattributed list, which is recorded as observed.

## R13 — Judge, install as root, verify

```bash
test "${#C}" -eq 40 \
  && sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$W/profiles-judge" \
  && "${J[@]}" judge-launch "$C" "$W" < "$W/profiles-judge" > "$W/judge.json" \
  && sudo /usr/bin/install -d -o root -g root -m 0755 /var/lib/constructicon-m8-launch \
  && sudo /usr/bin/install -o root -g root -m 0555 /usr/bin/bwrap /var/lib/constructicon-m8-launch/bwrap \
  && sudo /usr/bin/install -o root -g root -m 0444 "$W/staging/constructicon-m8-launch" /etc/apparmor.d/constructicon-m8-launch \
  && sudo /usr/bin/cp -R -P --preserve=mode --no-target-directory "$W/staging/runtime" /var/lib/constructicon-m8-launch/runtime \
  && sudo /usr/bin/install -o root -g root -m 0444 "$W/staging/runtime.json" /var/lib/constructicon-m8-launch/runtime.json \
  && sudo /usr/bin/cp -R -P --preserve=mode --no-target-directory "$W/staging/native-codex" /var/lib/constructicon-m8-launch/native-codex \
  && sudo /usr/bin/install -o root -g root -m 0444 "$W/staging/codex-models.json" /var/lib/constructicon-m8-launch/codex-models.json \
  && sudo /usr/bin/install -d -o root -g m8-service -m 0750 /var/lib/constructicon-m8-launch/operator-stores \
  && sudo /usr/sbin/apparmor_parser --add --skip-cache /etc/apparmor.d/constructicon-m8-launch \
  && echo "R13 installed"
echo "exit $?"; cat "$W/judge.json"
sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$W/profiles-verify" \
  && "${J[@]}" verify-launch "$C" "$W" < "$W/profiles-verify" > "$W/verify.json"
echo "verify exit $?"; cat "$W/verify.json"
```

The judge must exit 0 with `"ready": true`, `"first_parent": true` and
`"script_matches_commit": true`, and the chain must print `R13 installed`.
`verify-launch` must exit 0 with `"installed": true`. It runs even after a
failed chain and itemizes the residue.

## R14 — Stop (PowerShell)

```powershell
Stop-VM constructicon-m8     # clean shutdown; never Save-VM (H1)
```

## On failure

Stop and do not retry. Post the failing command's full output to #77.

If R11 or R12 failed, or the judge refused, `R13 installed` was never printed
and root wrote nothing: `/usr/bin/chmod -R u+w "$W" && /usr/bin/rm -rf "$W"` as
the operator (staged directories are `0555`), then rerun R10's absence loop.
Otherwise choose one:

- in PowerShell, `Stop-VM constructicon-m8`, then
  `Restore-VMCheckpoint -VMName constructicon-m8 -Name pre-m8-runtime -Confirm:$false`
  (permitted: no vendor store exists, H2); or
- the fixed removal, in the same shell, so `$C`, `$W` and `$J` are set. Valid
  only before the first vendor login:

  ```bash
  sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$W/profiles-recovery" \
    && { ! grep -qE '^constructicon-m8-(launch|workload) ' "$W/profiles-recovery" \
         || sudo /usr/sbin/apparmor_parser -R /etc/apparmor.d/constructicon-m8-launch; } \
    && sudo /usr/bin/rm -f /etc/apparmor.d/constructicon-m8-launch \
    && sudo /usr/bin/rm -rf --one-file-system /var/lib/constructicon-m8-launch \
    && sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$W/profiles-recovery" \
    && "${J[@]}" verify-launch "$C" "$W" < "$W/profiles-recovery"
  ```

  The final `verify-launch` exits 1 and must show every destination as
  `{"state": "absent"}` and no launch profile loaded, with the qualification
  profiles untouched. Then remove `$W` as above.

## Evidence that completes the host runtime

Posted on #77, all of it:

1. The R8 authorization link, `C`, its PR, the green M8 checks and the empty
   `git diff --exit-code` output.
2. The R10 output ending in `R10 passed`, including the package versions, the
   account line, `passwd -S` and `sudo -l`.
3. The R11 output: `main`, the matching `ls-remote` line, `first-parent`, the
   six `ls-tree` lines, the three sha256 lines and `R11 complete`.
4. `stage.json`, `judge.json` (`ready: true`), the `R13 installed` line, and
   `verify.json` (`installed: true`, `runtime_digest`, the blob digests, the
   package versions and the unattributed list).
5. N4's first launcher probe on this host, when N4 runs it: the child attachment
   `constructicon-m8-launch//&constructicon-m8-workload (enforce)`.

A CI run for `C` is context only. It never qualifies this host's runtime.
