# M8-D2: reviewed-artifact installation for private-host qualification

Status: design and bounded operator runbook for
[issue 94](https://github.com/sushiHex/constructicon/issues/94). Base: `6bc9500`.
Authority: the owner's
[three-role/two-host decision](https://github.com/sushiHex/constructicon/issues/73#issuecomment-5752858107)
on #73, and the owner's ruling below that root on the private host executes no
repository code. This record does not amend an accepted plan or ADR, and nothing
in it authorizes a host change: the runbook below runs only under the separate
authorization named in R0. #73 stays open until the evidence listed at the end
of the runbook is recorded there.

## Scope

The qualification set only: the probe, the qualification AppArmor profile, and
a copy of the host's pinned bubblewrap, installed at the layout the
[qualification workflow](../../../.github/workflows/m8-runner-qualification.yml)
builds on hosted runners (`:32-36`, `:50-53`). The launch profile, the runtime
closure under `/var/lib/constructicon-m8-launch` and `runtime.json` are an
[N4 (#77)](https://github.com/sushiHex/constructicon/issues/77) prerequisite and
are **carried, not built**: the closure is copied from the host's own `/usr` and
has no reviewed digest pin, so git provenance cannot cover it.

The CI paths are unchanged. The `RUNNER_ENVIRONMENT == "github-hosted"` guards
in `build_m8_runtime.py`, `build_m8_startup_fixture.py` and
`build_m8_store_fixture.py` keep their exact bytes, pinned by
`test_hosted_runner_guards_are_unchanged`; the only change there is the agreed
comment above the runtime guard naming this path. No host marker exists.

## Artifact contents

| Destination | Owner, mode | Source |
| --- | --- | --- |
| `/opt/constructicon-m8-qualification` | root, `0755`, holding exactly `bwrap` and `probe.py` | `install -d` |
| `/opt/constructicon-m8-qualification/probe.py` | root, `0444` | `$W/staging/probe.py`, the blob `C:scripts/ci/qualify_m8_runner.py` |
| `/opt/constructicon-m8-qualification/bwrap` | root, `0555` | host `/usr/bin/bwrap`, sha256 `e3189038…30f71` |
| `/etc/apparmor.d/constructicon-m8-bwrap` | root, `0444`, loaded with `apparmor_parser --add --skip-cache` | `$W/staging/constructicon-m8-bwrap`, the blob `C:scripts/ci/constructicon-m8-bwrap.apparmor` |

`C` is one reviewed commit on `main`. `$W` is the operator's private workspace,
`$HOME/m8-host`. The script,
[`scripts/ci/m8_host_artifacts.py`](../../../scripts/ci/m8_host_artifacts.py),
judges and verifies, unprivileged; it is executed, never installed, and never
writes. Bubblewrap cannot come from git, so the script holds its digest as a
constant that a test keeps equal to `linux.py:35` and `qualify_m8_runner.py:23`.
Destinations and modes are fixed in the script, and tests hold them equal to the
qualification workflow's `install` lines and to this runbook's root sequence.

## Privilege boundary: root executes no repository code

**Owner ruling.** Relayed to the implementing session on 2026-09-22, resolving
the implementation review's second finding; it is not yet linked from a GitHub
comment, and the PR should link it. Root on the private host executes no
repository code. For the installation, root runs only stock tools: `install`,
`apparmor_parser` and `cat`, and `rm` and `rmdir` for recovery. The reviewed
Python script runs unprivileged only, as a judge before root's writes and as a
verifier after them.

**Everything root runs.** Every `sudo` in this runbook is listed here, and
`test_root_runs_only_named_stock_tools_in_the_runbook` pins the list:

| Step | As root |
| --- | --- |
| R2 | `sudo -l -U m8-probe`, which is sudo's own policy listing, not a tool; `/usr/bin/cat` of the profile list; and only if R0 permits and R2 finds them absent, the host provisioning `/usr/bin/apt-get install -y git` and `/usr/sbin/useradd` |
| R4 | `/usr/bin/cat /sys/kernel/security/apparmor/profiles`, twice; `/usr/bin/install` four times; `/usr/sbin/apparmor_parser --add --skip-cache` once |
| On failure | `/usr/bin/cat` of the same list, `/usr/sbin/apparmor_parser -R` on the installed profile, `/usr/bin/rm -f`, `/usr/bin/rmdir` |

R5 runs the probe with `sudo -u m8-probe`, which is not root. Git never runs as
root. Every root command names its tool by absolute path, so sudo's
`secure_path` order does not choose the binary. An absolute path only removes
the lookup, so before root's first write the judge also proves that
`/usr/bin/install`, `/usr/bin/cat`, `/usr/sbin/apparmor_parser` and
`/usr/bin/bwrap` (which root's `install` reopens by path) are regular files
owned by root that group and others cannot write, under real, root-owned
ancestors that group and others cannot write. After that proof no other account
can swap a tool or bubblewrap before root uses it. R2's and R4's first `cat`
run before the judge, and they only read.

**Why provenance and staging run unprivileged.** The ruling allowed either the
operator or root to run the stock-git provenance. The operator does, in one
repository in `$W`. That removes root's git entirely, which gives the smaller
runbook. It is also the safer choice: the judge must read the repository, and
root running git inside a repository another account can write would let that
repository's local configuration run commands as root. That is the attack
git's `safe.directory` exists for. With no root git, no root process ever parses
a repository.

**Why stock `install` is safe without `O_NOFOLLOW`.** Before any root write the
judge proves that each destination is absent, and that every ancestor of each
destination up to `/` is a real directory (not a symlink), owned by root, with no
group or other write bit. It checks the ancestors of
`/opt/constructicon-m8-qualification` and `/etc/apparmor.d/constructicon-m8-bwrap`.
Creating, removing or renaming a directory entry needs write permission on
that directory, and changing a directory's mode or owner needs its ownership (or
`CAP_FOWNER`/`CAP_CHOWN`). So between the judgement and root's `install`, no
account but root can put a symlink or anything else at a destination, swap an
ancestor, or loosen one. A POSIX ACL cannot hide such a grant either: a
named-user or named-group entry is effective only up to the ACL mask, which
`st_mode` reports in its group bits, so a mask without write refuses that write
and a mask with write fails the check. How `install` treats an existing final
component therefore does not matter here. (For the record, coreutils 9.4
`install.c:258-288` sets `unlink_dest_before_opening` and `DEREF_ALWAYS` and
calls `umask(0)` before applying `-m`. `install -d` goes through
`make_dir_parents` and accepts an existing directory, which only root could
create here.) The one party this cannot exclude is root itself, which is under
the hostile-root ceiling on #73.

**The source side of root's `install`.** `install` follows a symlink given as
its source (`DEREF_ALWAYS` above), so whoever can change `$W/staging` could make
root copy a file into a world-readable destination. The judge proves custody of
`$W`: an absolute path to a real directory owned by the operator, with no group
or other permission bit. Its `source.git` and `staging` must be real
directories, each staged file a regular file opened with `O_NOFOLLOW`, and every
ancestor of `$W` up to `/` a real directory owned by root or the operator that
group and others cannot write. Only the operator and root can then change what
root reads. The operator already holds sudo, so a change the operator makes
after judgement is not an escalation. It is still caught: `verify` compares the
installed bytes with the blobs at `C`, never with staging.

**The loaded-profile list needs root.** `/sys/kernel/security/apparmor/profiles`
is created `0444` (`AA_SFS_FILE_FOPS("profiles", 0444, …)`,
`security/apparmor/apparmorfs.c:2422` in Linux v6.8). But `profiles_open`
(`:2286-2292`) returns `EACCES` unless `aa_current_policy_view_capable` holds,
which requires effective uid 0 or effective gid 0 in the caller's user namespace
(`security/apparmor/policy.c:814-832`). Ubuntu's kernel carries AppArmor
patches that were not read, so it is unknown whether Ubuntu relaxes this. The
runbook uses `sudo /usr/bin/cat` either way, as the qualification workflow does.
It saves the list to a file in `$W`, and the next command, chained with `&&` so
it runs only after `cat` succeeds, feeds that file to the script's standard
input. A pipe is not used, because a pipeline's status is its last command's,
so a `cat` that failed partway would go unnoticed. The script requires a
non-empty list in the kernel's `name (mode)` format that ends within 1 MiB. A
failed, empty or unterminated read therefore refuses and never reads as "no
profile loaded". The list's provenance is the operator's: an operator who typed
the two `constructicon-m8-* (enforce)` lines in by hand could make `verify`
pass. That operator already holds sudo, and the probe's exact child attachment
is the behavioural proof of what is loaded.

**The script's own guard.** The script refuses to run with effective uid 0, so a
mistaken `sudo python3` refuses instead of silently breaking the ruling.

## Provenance chain

There is no digest manifest. A manifest checked against bytes from the same
staging directory proves consistency, not provenance. Provenance comes from git
itself, run by the operator with stock tools only, with no working tree:

1. The operator names `C` as exactly 40 lowercase hex digits.
2. An anonymous bare fetch of `refs/heads/main` from github.com into
   `$W/source.git`, cross-checked against `git ls-remote`.
3. `C` is on the first-parent line of that `main` (`git rev-list
   --first-parent`). This implies ancestry, and only commits appear on that
   line, so no separate ancestry or object-type check exists; one would be an
   equivalent mutant.
4. `git ls-tree` shows each fixed path as mode `100644`: a regular,
   non-executable blob, never a symlink, tree or executable.
5. `git cat-file blob` extracts the raw bytes of the script to
   `$W/m8_host_artifacts.py`, and of the probe and profile into `$W/staging`.

R3 does steps 2 to 5 with stock git, which is what anchors trust in the script
before it runs. The script then repeats steps 1, 3 and 4 itself, and compares
each staged copy with its blob.

Raw blobs are required. On a `core.autocrlf=true` Windows checkout the profile's
working-tree bytes and `git archive HEAD` both hash to `0329b6e3…` while the
blob hashes to the pin `9375aeda…` (measured on 2026-09-22), so a working tree,
`git archive` or a copy from Windows would fail the probe's pin. Every git call
passes `--no-replace-objects`, so a replacement ref cannot substitute another
object for the one `C` names. That flag leaves `info/grafts` in force (measured
on Git 2.53: a graft put a merged branch's intermediate commit on the
first-parent line), so the fixed environment also sets
`GIT_GRAFT_FILE=/nonexistent`, both in R3 and in the script's children, and a
test pins the refusal. Whoever can write `$W/source.git` could still forge its
object store or commit-graph (reasoned, not reproduced). The custody proof above
limits that to the operator and root.

What "on `main`" proves: ruleset 23742805 (read 2026-09-22) is active with a
`pull_request` rule, 0 required approvals, required review-thread resolution, no
bypass actors and no status-check rule, and it allows merge, squash and rebase
merges. Ancestry alone is too weak. `main` already has five merge commits (#1,
#2, #3, #4 and #7) whose PR branches' intermediate commits are ancestors of
`main` without ever having been a merge result. The first-parent check refuses
those; a test pins it with a `--no-ff` merge. It cannot refuse the intermediate
commits of a *rebase* merge, which land on the first-parent line. Nothing on
`main` shows an approving review or passing CI. The runbook therefore requires
`C` to be the PR's recorded merge commit and records that PR's green M8 checks.

Accepted limit: git's object format here is SHA-1. A hostile GitHub or a hostile
host root is already under the ceiling recorded on #73.

## Trusted script boundary

The script no longer runs as root, but its verdicts still gate root's writes and
decide `installed`, so its bytes must be the reviewed ones. The anchor is R3:
stock git proves that `C` is on `main`'s first-parent line, and `cat-file`
extracts the script's blob at `C`; nothing is checked out. The script then runs
as `/usr/bin/python3 -I`, which excludes the script's directory and user
site-packages from `sys.path` and ignores `PYTHON*` variables. Its self-check
that its bytes equal `C:scripts/ci/m8_host_artifacts.py` catches accidental
drift, such as a stale or line-ending-converted copy. It cannot catch a
deliberately edited copy, which would simply omit the check; R3's printed facts
exclude that. A lying judge could not change what root installs, only whether
root proceeds: the staged bytes come from R3's stock-git extraction.

The script is stdlib only and imports no Constructicon code (test-enforced).
Its own code reads no environment variable and never writes: a test walks its
names and allows only one `os.open`, with `O_RDONLY`. Its only children are
`/usr/bin/git` calls, in a fixed environment. It uses no network and no marker
file. The production root `/` and every destination are constants; the command
line names only `C` and `$W`.

**Rejected as unnecessary.** A digest manifest (consistency, not provenance); a
push-to-main build with attestations (Actions artifacts and
`gh attestation verify` need a GitHub credential on the credential host); a
completion marker (cached truth, the flaw that withdrew the host marker);
rollback code; in-place reinstall or `--replace`; and script-managed packages or
accounts, which the probe already checks.

**Implementation choices not fixed by the decision.** `--no-replace-objects`
costs one flag and `GIT_GRAFT_FILE=/nonexistent` one variable. `verify`
re-proves provenance instead of trusting the judge's record. The judge refuses
an already loaded `constructicon-m8-*` profile, because `--add` would otherwise
fail after every file was written. The custody check on the root tools also
catches a missing `apparmor_parser` before any write, for the same reason. Only `ENOENT` counts as absence: a destination the
operator cannot look up (`EACCES`, `ENOTDIR`) refuses instead of reading as
absent. File group ownership is not checked, because exact modes already exclude
group write. A regular file is opened with `O_NONBLOCK`, so a FIFO in its place
is refused instead of blocking the open.

**Open question for the owner.** The qualification profile's own header says
"Disposable CI qualification only; not Constructicon's production policy". It
grants `userns`, `capability` and `mount` to the root-owned `0555`
`/opt/constructicon-m8-qualification/bwrap`, which any local account can
execute; the confined child stack then denies `userns` and `capability`. The
accepted #73 layout includes it. Once installed, it is expected to load at every
boot from `/etc/apparmor.d`, which is not yet observed on this VM. Whether it
stays loaded on the credential host after qualification, or is removed with the
fixed removal until each requalification, is the owner's decision. This change
does not decide it, but the success path acts on it in the meantime: after R5,
the profile, the `/opt` bubblewrap copy and the operator's `$W` all stay on the
host pending that decision, and every later rerun of `verify` or the probe needs
its own authorization.

## Verification order

`judge C $W`, unprivileged, reading root's `cat` of the profile list on standard
input. It checks, in order:

1. The effective uid is not 0.
2. `$W` is absolute with no `..`; it is a real directory owned by this account
   with no group or other permission bit (`lstat`, so a symlink refuses);
   `$W/source.git` is a real directory; and every ancestor of `$W` up to `/` is
   a real directory owned by root or this account that group and others cannot
   write.
3. Provenance as above, including the script's own bytes.
4. `$W/staging` is a real directory, and `probe.py` and `constructicon-m8-bwrap`
   in it are regular files (`O_NOFOLLOW|O_NONBLOCK`) equal to their blobs at
   `C`.
5. `/usr/bin/bwrap`, `/usr/bin/install`, `/usr/bin/cat` and
   `/usr/sbin/apparmor_parser` are each a regular file (`lstat`, so a symlink
   refuses), owned by root, not group or other writable, with every ancestor a
   real, root-owned directory that group and others cannot write.
6. `/usr/bin/bwrap` (`O_NOFOLLOW|O_NONBLOCK`) matches the pinned digest.
7. No destination exists, including as a dangling link; only `ENOENT` counts as
   absence.
8. Every ancestor of the directory and of the profile, up to `/`, is a real,
   root-owned directory that group and others cannot write.
9. The profile list ends within 1 MiB, is non-empty and in the kernel's format,
   and names no `constructicon-m8-*` profile.

`ready` defaults to `false` and becomes `true` only as the judge's last
statement; the exit status follows it. Only then does root run the fixed
sequence in R4: `install -d` for the directory, `install -o root -g root -m`
for each file in the table's order, then `apparmor_parser --add --skip-cache`.
The whole of R4 is one `&&` chain, so the first failure stops the rest.

`verify C $W`, unprivileged, recomputes everything from scratch and never reads
staging. It repeats checks 1 to 3, then re-extracts the expected probe and
profile digests from `C`. It observes each destination freshly with `lstat`,
hashing a regular file through the same `O_NOFOLLOW|O_NONBLOCK` open, and
assesses it: kind, owner uid 0, exact mode, exact bytes, and the directory's
exact listing. Exactly the four fixed entries must have been checked. It
re-checks every destination's ancestors and requires both
`constructicon-m8-bwrap (enforce)` and `constructicon-m8-payload (enforce)` in
the saved profile list. `installed` defaults to `false` and becomes `true` only
as `verify`'s last statement; the exit status follows it.

Because `verify` compares against git, it cannot report `installed: true` from
absence (the directory is not a directory), from partial state (a missing file,
a short listing or an unloaded profile), or from staging modified between
judgement and install (a digest that is not the blob's). Tests pin each case. A
command that raised `OSError`, `ValueError` or `SubprocessError`, or one that
recorded nothing, reports its verdict as `false` and exits 1. Two exits print no
record at all, and a test pins both: `-h` exits 0 with help, and any other
exception exits 1 with a traceback. Neither is a false success, because the
runbook requires the verdict `true` in the printed record.

`verify` cannot show that the loaded kernel policy equals the file's bytes: the
kernel exposes no profile source. The probe's exact child attachment is the
behavioural proof, which is why the probe runs after `verify`. The profile list
is whatever root's `cat` saved immediately before, in the same `&&` chain.

## Partial-install failure and recovery

There is no automatic rollback. On any failure the record carries the verdict
`false`, the error, and `observed`: every destination's state, owner, mode and
digest or listing, plus the loaded `constructicon-m8-*` profiles, observed
freshly at the moment of failure rather than remembered from the steps that ran.
An entry that cannot be read, or a regular file that changed kind between
`lstat` and its `O_NOFOLLOW|O_NONBLOCK` open, is recorded as
`unobservable: <error type>` and never as success. The exit status is 1. A
rerun of the judge refuses while any residue exists.

Recovery is either the `pre-m8-artifacts` checkpoint (R1), which law H2 of the
[host laws on #73](https://github.com/sushiHex/constructicon/issues/73#issuecomment-5672995964)
permits before the first vendor login, or the fixed removal in the runbook, after
which `verify` must itemize every destination as `absent` with no loaded
profile.

## Qualification handoff

After `verify` reports `installed: true`, the probe runs as `m8-probe` with the
qualification workflow's command (`:61-63`), `--commit C` and
`--image local-hyperv/ubuntu-24.04.5`. The probe's `commit` field is
caller-supplied (`qualify_m8_runner.py:278`); its link to `C` comes from pairing
it with the `verify` record, whose observed `probe.py` digest must equal the
record's `blobs` digest for `C:scripts/ci/qualify_m8_runner.py`. Only after
`qualified: true` is the `m8-host-drift` baseline captured.

## Evidence for this change

`tests/test_m8_host_artifacts.py` and
`scripts/check_m8_host_artifact_mutations.py`, which `verify.yml` runs on Linux
as a non-root user after `uv run verify`.

- **Portable, run on Windows and Linux (76 tests):** the repository pins
  (stdlib-only imports, no environment reads, no writes, fixed destinations, the
  bubblewrap digest equal to `linux.py`'s, the layout equal to the probe's and
  CI's, the three unchanged guards, the `verify.yml` step), and two runbook
  pins: R4's root sequence equals the fixed inventory in order, and every
  `sudo` in the runbook names a stock tool or `m8-probe`. Provenance against
  temporary git repositories covers the accepted commit, a commit off `main`, a
  merged branch's intermediate commit off the first-parent line, malformed and
  abbreviated names, a blob, an annotated tag and an unknown id, a missing
  `main`, mode `100755` and `120000` for each artifact, a tree or a missing
  path, a stale or CRLF copy of the running script, a replacement ref and an
  `info/grafts` file. The profile list refuses empty and malformed input, and a
  list one byte beyond its 1 MiB bound refuses while one exactly at it passes.
  Assessment of observed state covers each kind, owner, mode, digest, listing
  and profile fact, absence, and a shrunken inventory. The command record tests
  show that each command's exit status follows its own verdict, that absent
  evidence stays `false`, and that `-h` and an uncaught exception print no
  record.
- **Linux only, skipped elsewhere (114 tests):** judge, then root's sequence
  through the real coreutils `install`, then `verify`, in a temporary root;
  the sequence's modes under umask `0277`; `verify` with nothing installed;
  refusal as root for both commands; each judge refusal (workspace custody:
  group-readable, symlinked, foreign-owned, relative, symlinked `source.git`;
  every unsafe workspace ancestor; each staged copy altered by one byte or line
  endings, symlinked, a FIFO or missing; a symlinked staging directory; the
  bubblewrap pin; `/usr/bin/bwrap` and each root tool as a symlink, directory,
  FIFO, group-writable, foreign-owned or operator-owned file, or under a
  group-writable parent; each root tool missing; every existing or dangling
  destination; an unsearchable destination parent; every unsafe destination
  ancestor, including an operator-owned one and a symlinked root; an already
  loaded profile; an empty or failed profile list); staging
  modified after judgement caught by `verify`; `verify` accepting with staging
  deleted; each partial installation, never installed and blocking a rerun; a
  refused profile load; and `verify` refusing each post-install drift, each
  asserting which check refused. Ownership is observed through a uid view: the
  tests are not root, so the temporary host's files read as a stand-in root uid
  while the operator's home keeps the real one, and root's `-o root -g root` is
  dropped.

The inventory has 37 mutants. 19 are portable and all 19 were killed locally on
Windows. The 18 Linux-only mutants apply cleanly, but their tests are skipped on
Windows, so the runner reports them NOT PROVEN there. One Linux-only kill is a
message pin, not a lost refusal: without the regular-file check an unfed staged
FIFO reads as empty and still differs from its blob, so its
kill shows which check refuses.

**Unexecuted until Linux CI runs:** every Linux-only test and the 18 Linux-only
mutants. Locally on Windows they are skips and NOT PROVEN, which is not
evidence. **Never executed by CI:** a real root-owned install through `sudo`, a
real `apparmor_parser` load, the kernel's profile list and the probe on the
private host. The host's R4 and R5 output is their first execution; the R1
checkpoint makes that recoverable.

## Implementation review dispositions

**Round 1** (Opus, while Codex was paused). Every premise below was reproduced
against source or its probes before disposition.

- **Adopted.** R6 was outside any exact command, so R0 now authorizes R3 to R5
  only and R6 needs a second authorization citing the interface R2 records.
  `info/grafts` overrode `--no-replace-objects`, so `GIT_GRAFT_FILE` is now
  fixed, with a test and a mutant. The `rev-parse` commit check was an
  equivalent mutant (a blob or tag id is refused by the first-parent check
  without it), so it was removed and its test now expects that refusal. The
  regular-file kill is recorded as a message pin. The success path's retained
  files and each rerun's authorization are stated. R2 checks the workspace's
  absence, checkpoint deletion is a separate authorization, an R3 failure has
  its own recovery, and H1/H2 are linked. R0 shows that `C` and the tested head
  agree on the three paths. Git runs by absolute path in the fixed environment.
  R4 has the length guard, the no-record exits are stated and pinned, drift
  tests assert the refusing check, and R5 runs from `/`.
- **Resolved by the owner's ruling (round 2).** Whether root may execute the
  provenance-proved script. See below.
- **Rejected, with reasons.** The per-file existence checks for `probe.py` and
  `bwrap` are shadowed by the directory check, and `checked == 4` binds only if
  `FILES` changes; both are one expression over the fixed inventory, so removing
  them changes no behaviour and keeping them costs nothing. The script sits
  outside mypy's scope (`pyproject.toml`), which is pre-existing and shared with
  `qualify_m8_runner.py`. The review also checked and rejected an annotated tag
  (refused and now tested), the `ls-tree` regex, symlink, ACL and race attacks
  on destinations and ancestors, the assessment with missing keys, the
  runbook's shell, and all-skip mutation runs.

**Round 2: the owner's ruling, and the design it supersedes.** The first design
ran this script as root (`sudo /usr/bin/python3 -I /root/m8_host_artifacts.py
install C`). It argued that reviewed, provenance-proved merged code is not
"running repository code" in the #73 decision's sense, and left that reading for
the owner. The owner rejected it: root executes no repository code. **Superseded
and deleted:** the root-run `install` command and its effective-uid-0 check; the
root-owned `0700` `/root/constructicon-m8.git` and `/root/m8_host_artifacts.py`,
and root's git fetch and extraction; the script's own writes (`make_directory`,
`write_exclusive` with `O_CREAT|O_EXCL|O_NOFOLLOW`, `fchmod`, `fsync`) and their
tests and mutants (final directory and file modes, "install runs as root",
"profile load must succeed", "install is always verified"); and reading
`/sys/kernel/security/apparmor/profiles` directly. **Replaced by:**
the unprivileged workspace and custody proof, the staged-copy comparison, the
root-only destination ancestors, `ENOENT`-only absence, the refusal to run as
root, the saved, bounded and format-checked profile list, and root's fixed stock-tool
sequence. **Kept:** the grafts fix, the first-parent rule, the self-check, the
fixed destinations, and the unchanged `RUNNER_ENVIRONMENT` guards.

**Round 3: Codex (`gpt-5.6-terra`, high, job `job_82968031989a`)** attacked the
ruling's implementation, in the owner-limited single pass. Every premise was
reproduced against source before disposition.

- **Adopted (introduced).** (P1) `/usr/bin/bwrap` was hashed by the judge but
  reopened by path for root's `install` with no custody check, and (P1) the root
  tools were named by absolute path with no custody check either. The judge now
  proves bubblewrap and every root tool are root-owned regular files that group
  and others cannot write, under root-only ancestors, with a test over each
  file and each unsafe case, and three mutants. (P2) A pipe hid a `cat` that
  failed partway, and a 1 MiB read did not require the list to end. R4 now saves
  the list in an `&&` chain, and the script refuses a list beyond its bound, with
  a test at and beyond the bound and a mutant. (P2) Recovery made root parse the
  staged profile when the installed one was gone. It now uses only the installed
  root-owned file, and falls back to the checkpoint. (P3) `$G` and `$J` split a
  `$W` containing whitespace; they are now bash arrays.
- **Adopted (pre-existing).** (P2) Recovery was not chained, so a failed
  `apparmor_parser -R` still deleted the files. Every step is now chained. (P3)
  R0's "account inspection" wording contradicted R2's local-account checks, and
  the root-tool sentence omitted R2's provisioning; both are reworded.
- **Rejected, with reasons.** (P2, in part) An operator could hand-type a
  profile list to `verify`. The operator holds sudo, so this is not an
  escalation, and the probe's child attachment is the behavioural proof; the
  limit is stated above. (P3) The Linux tests emulate root ownership with a uid
  view and drop `-o root -g root`. That substitution is deliberate and already
  recorded as a limit: the real root install is first executed on the host, in
  R4. Group ownership remains unchecked by design, because exact modes exclude
  group write.
- **Not found.** Codex found no destination-side symlink, rename or hard-link
  bypass under the ancestor proof, no static error in the relative-path,
  `EACCES` or ancestor tests, and no mutant that obviously survives or errors.
  It also stated that none of this is Linux evidence.

---

# Operator runbook

Run only under R0's authorization, and in order. On any unexpected output, stop
and do not retry. Post the output to #73, then recover (see "On failure").
Commands run in the guest as the operator account, in one shell, unless marked
PowerShell. H1 and H2 are the
[host laws on #73](https://github.com/sushiHex/constructicon/issues/73#issuecomment-5672995964).

## R0 — Separate authorization (required)

#94 authorizes none of this. A written authorization on #73 must name:

- the VM `constructicon-m8`, the commit `C`, its PR, and that PR's green M8
  checks (verify, qualification and the containment lanes). `C` must be the
  PR's recorded merge commit (`gh pr view <PR> --json headRefOid,mergeCommit`,
  read on the workstation), never a commit of the PR branch;
- because those checks ran on the PR head
  (`m8-runner-qualification.yml:19-21`) and no ruleset rule requires the head
  to be up to date, the workstation output of
  `git diff --exit-code <headRefOid> C -- scripts/ci/m8_host_artifacts.py scripts/ci/qualify_m8_runner.py scripts/ci/constructicon-m8-bwrap.apparmor`,
  which must exit 0 and print nothing;
- the permitted actions: `Start-VM` and `Stop-VM`; one checkpoint
  `pre-m8-artifacts`; an anonymous fetch from github.com by the operator
  account; `apt-get install git` and `useradd m8-probe` if R2 finds either
  absent; R3 to R5 exactly as written, including every root command they name;
  and the recovery below. R6 and deleting the checkpoint are not included:
  each needs its own authorization;
- what stays forbidden: vendor login, inspecting a vendor credential or vendor
  account (R2's `id m8-probe` and `sudo -l -U m8-probe` read only the local
  service account), model calls, any checkout or `git clone` with a working tree, git or any repository
  file run as root, the CI scripts, setting `RUNNER_ENVIRONMENT`, sysctl
  changes, `--replace`, `Save-VM`, and any change to `m8-service` or the launch
  root;
- how long the evidence is kept.

## R1 — Checkpoint, then start (PowerShell)

```powershell
Get-VM constructicon-m8 | Select-Object Name, State            # Off
Checkpoint-VM -Name constructicon-m8 -SnapshotName pre-m8-artifacts
Start-VM constructicon-m8
```

The checkpoint is taken while the VM is off, so it holds no memory state and
does not depend on the guest's integration services. Law H2 permits it only
before the first vendor login. It must be deleted before N4 begins, by
`Remove-VMCheckpoint -VMName constructicon-m8 -Name pre-m8-artifacts` under a
separate authorization that R0 does not grant. The guest address is DHCP; read
it from `Get-VMNetworkAdapter` and never hardcode it.

## R2 — Preconditions (read-only)

```bash
cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns   # 1
cat /sys/module/apparmor/parameters/enabled                  # Y
. /etc/os-release && echo "$ID $VERSION_ID"                  # ubuntu 24.04
uname -m                                                      # x86_64
dpkg-query -W -f='${Version}\n' bubblewrap                    # 0.9.0-1ubuntu0.3
apt-mark showhold                                             # lists bubblewrap
sha256sum /usr/bin/bwrap    # e318903862396f96de3df57264e0158682b952fd3fb53ac23d876413e7b30f71
ls -l /usr/bin/git /usr/bin/python3 /usr/bin/install /usr/bin/cat /usr/bin/rm \
      /usr/bin/rmdir /usr/sbin/apparmor_parser                # all present
id m8-probe && sudo -l -U m8-probe                            # exists; no sudo rights
stat -c '%U %a %n' "$HOME" /home /                            # owner, no group/other write
for p in /opt/constructicon-m8-qualification /etc/apparmor.d/constructicon-m8-bwrap \
         "$HOME/m8-host"; do
  test ! -e "$p" && test ! -L "$p" || echo "EXISTS $p"; done
sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles | grep -c . # a count above 0
sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles | grep constructicon-m8- # prints nothing
m8-host-drift; echo "exit $?"                                 # exit 2, NO BASELINE
ls -l /usr/local/bin/m8-host-drift && sed -n 1,80p /usr/local/bin/m8-host-drift
```

The last line records the drift tool's interface, which this repository does
not hold; the R6 authorization cites it.

If git or `m8-probe` is absent and R0 permits it:
`sudo /usr/bin/apt-get install -y git`, or
`sudo /usr/sbin/useradd --create-home --shell /bin/sh m8-probe`. Rerun R2. The
absolute paths of `apparmor_parser` and the coreutils tools on this VM are not
yet observed; if any differs from the paths above, stop, because the runbook and
the script use those fixed paths.

## R3 — Provenance and staging (operator, stock git only, no sudo)

Every step is chained, so the first failure stops the rest, and the chain ends
by printing `R3 complete`. `umask 077` makes `$W` and its contents private. Git
runs by absolute path in the script's fixed environment: without `env -i` git
would read `/etc/gitconfig`, `~/.gitconfig` (a `url.insteadOf` there would
redirect both the fetch and the `ls-remote` cross-check) and `info/grafts`.

The shell is bash. `E`, `G` and `J` are arrays, so a `$W` containing
whitespace stays one argument.

```bash
umask 077
C=<40-hex merge commit named in R0>
W="$HOME/m8-host"
U=https://github.com/sushiHex/constructicon.git
E=(/usr/bin/env -i PATH=/usr/bin:/bin HOME=/nonexistent LANG=C.UTF-8 GIT_CONFIG_NOSYSTEM=1 GIT_GRAFT_FILE=/nonexistent)
G=("${E[@]}" /usr/bin/git --no-replace-objects "--git-dir=$W/source.git")
test "${#C}" -eq 40 && /usr/bin/mkdir "$W" "$W/staging" \
  && "${E[@]}" /usr/bin/git init -q --bare "$W/source.git" \
  && "${G[@]}" fetch -q --no-tags "$U" +refs/heads/main:refs/heads/main \
  && "${G[@]}" rev-parse refs/heads/main && "${E[@]}" /usr/bin/git ls-remote "$U" refs/heads/main \
  && "${G[@]}" rev-list --first-parent refs/heads/main | grep -qxF "$C" && echo first-parent \
  && "${G[@]}" ls-tree "$C" -- scripts/ci/m8_host_artifacts.py scripts/ci/qualify_m8_runner.py \
       scripts/ci/constructicon-m8-bwrap.apparmor \
  && "${G[@]}" cat-file blob "$C:scripts/ci/m8_host_artifacts.py" > "$W/m8_host_artifacts.py" \
  && "${G[@]}" cat-file blob "$C:scripts/ci/qualify_m8_runner.py" > "$W/staging/probe.py" \
  && "${G[@]}" cat-file blob "$C:scripts/ci/constructicon-m8-bwrap.apparmor" \
       > "$W/staging/constructicon-m8-bwrap" \
  && sha256sum "$W/m8_host_artifacts.py" "$W/staging/probe.py" \
       "$W/staging/constructicon-m8-bwrap" && echo "R3 complete"
```

The two SHAs printed by `rev-parse` and `ls-remote` must be equal. Each of the
three `ls-tree` lines must read `100644 blob <oid>`, then a tab, then its path.
`/usr/bin/mkdir` refuses an existing `$W`, so R3 starts only from R2's absence.

## R4 — Judge, install as root, verify

The first chain runs the judge and, only if it exits 0, root's fixed stock-tool
sequence. Root runs nothing else. The judge refuses unless every precondition in
"Verification order" holds, including that no other account can reach a
destination or the staged copies. As in R5, an empty or truncated `$C` stops the
chain before root runs anything.

```bash
J=(/usr/bin/python3 -I "$W/m8_host_artifacts.py")
test "${#C}" -eq 40 \
  && sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$W/profiles-judge" \
  && "${J[@]}" judge "$C" "$W" < "$W/profiles-judge" > "$W/judge.json" \
  && sudo /usr/bin/install -d -o root -g root -m 0755 /opt/constructicon-m8-qualification \
  && sudo /usr/bin/install -o root -g root -m 0444 "$W/staging/probe.py" /opt/constructicon-m8-qualification/probe.py \
  && sudo /usr/bin/install -o root -g root -m 0555 /usr/bin/bwrap /opt/constructicon-m8-qualification/bwrap \
  && sudo /usr/bin/install -o root -g root -m 0444 "$W/staging/constructicon-m8-bwrap" /etc/apparmor.d/constructicon-m8-bwrap \
  && sudo /usr/sbin/apparmor_parser --add --skip-cache /etc/apparmor.d/constructicon-m8-bwrap \
  && echo "R4 installed"
echo "exit $?"; cat "$W/judge.json"
sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$W/profiles-verify" \
  && "${J[@]}" verify "$C" "$W" < "$W/profiles-verify" > "$W/verify.json"
echo "verify exit $?"; cat "$W/verify.json"
```

The judge must exit 0 with `"ready": true`, `"first_parent": true` and
`"script_matches_commit": true`, and the chain must print `R4 installed`.
`verify` must exit 0 with `"installed": true` and every entry itemized under
`observed`. `verify` is read-only apart from root's `cat`, so it runs even after
a failed chain, and its record itemizes the residue.

## R5 — Qualify as `m8-probe`

R3 to R5 run in one shell, so `$C` stays set; the probe records whatever
`--commit` it is given, so the command refuses to start with an empty or
truncated `$C`. `cd /` first, because `m8-probe` cannot enter the operator's
home directory under Ubuntu's default `0750` home mode (not observed on this
VM).

```bash
cd / && test "${#C}" -eq 40 && sudo -u m8-probe env -i PATH=/usr/bin:/bin HOME=/home/m8-probe LANG=C.UTF-8 \
  /usr/bin/python3 /opt/constructicon-m8-qualification/probe.py \
  --commit "$C" --image local-hyperv/ubuntu-24.04.5 > "$W/qualification.json"
echo "probe exit $?"; cat "$W/qualification.json"
```

## R6 — Drift baseline

Not authorized by R0. The tool lives only on the host
(`docs/AGENT_HANDOFF.md:238`), so its baseline command and exit codes are not in
this repository and are unverified here. Only after R5 reports
`"qualified": true`, a second written authorization on #73 names the exact
baseline command, the exact no-drift command and its expected exit status,
citing the interface R2 recorded. Run exactly those two commands and record
their output.

## R7 — Stop (PowerShell)

```powershell
Stop-VM constructicon-m8     # clean shutdown; never Save-VM (H1)
```

## On failure

Stop and do not retry. Post the failing command's full output to #73. The
script's record already itemizes the fresh residue.

If R3 failed, or the judge refused, `R4 installed` was never printed and root
wrote nothing: `/usr/bin/rm -rf "$W"` as the operator, without sudo, and rerun
R2's absence loop to show it prints nothing. Otherwise choose one:

- in PowerShell, `Stop-VM constructicon-m8`, then
  `Restore-VMCheckpoint -VMName constructicon-m8 -Name pre-m8-artifacts -Confirm:$false`,
  which is permitted because no vendor store exists (H2); or
- the fixed removal, in the same shell as R3 and R4, so `$C`, `$W` and `$J` are
  still set:

  ```bash
  # apparmor_parser -R reads only the installed, root-owned profile and removes
  # both profiles it defines. Every step is chained: if the unload fails, for
  # example because that file is gone, nothing is removed and the checkpoint
  # is the recovery.
  sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$W/profiles-recovery" \
    && { ! grep -q '^constructicon-m8-' "$W/profiles-recovery" \
         || sudo /usr/sbin/apparmor_parser -R /etc/apparmor.d/constructicon-m8-bwrap; } \
    && sudo /usr/bin/rm -f /opt/constructicon-m8-qualification/probe.py \
         /opt/constructicon-m8-qualification/bwrap /etc/apparmor.d/constructicon-m8-bwrap \
    && { test ! -e /opt/constructicon-m8-qualification \
         || sudo /usr/bin/rmdir /opt/constructicon-m8-qualification; } \
    && sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$W/profiles-recovery" \
    && "${J[@]}" verify "$C" "$W" < "$W/profiles-recovery"
  ```

  The final `verify` exits 1 and must show every destination as
  `{"state": "absent"}` and `loaded_profiles: []`. Anything else is residue.
  Then `/usr/bin/rm -rf "$W"` as the operator, so a later authorized attempt
  starts from R2 with a fresh workspace.

## Evidence that completes #73

Posted on #73, all of it:

1. The R0 authorization link, `C`, its PR number, the PR's green M8 checks and
   the empty `git diff --exit-code <headRefOid> C` output for the three paths.
2. The R2 output, including `apt-mark showhold`, the bwrap digest, the
   ownership line and the drift tool's interface.
3. The R3 output: fetched `main`, the matching `ls-remote` line,
   `first-parent`, the three `ls-tree` lines, the three sha256 lines and
   `R3 complete`.
4. `judge.json` (`ready: true`), the `R4 installed` line, and `verify.json`
   (`installed: true`, `main`, `blobs`, and `observed` with every entry).
5. `qualification.json`: `qualified: true`, `production_available: false`,
   `commit` equal to `C`, `architecture` x86_64, Ubuntu 24.04,
   `userns_restriction` `"1"`, `bubblewrap_package` `0.9.0-1ubuntu0.3`,
   `bubblewrap_sha256` `e3189038…30f71`, `policy_sha256` `9375aeda…4590b`,
   `child.apparmor` exactly
   `constructicon-m8-bwrap//&constructicon-m8-payload (enforce)`, and a non-null
   `unprofiled_refusal_stage`.
6. The pairing: `observed["/opt/constructicon-m8-qualification/probe.py"].sha256`
   in the verify record equals `blobs["scripts/ci/qualify_m8_runner.py"].sha256`.
7. The R6 authorization link, the baseline capture and the following no-drift
   run.

A CI run for `C` is context only. It never qualifies this host.

## What `m8-host-drift` does not cover

Its nine facts are the kernel, the bwrap digest and version, the hold, AppArmor
enabled and its abi, the userns restriction, the OS version and the
architecture. It does not cover the installed probe's bytes, owner and mode, the
`/opt` bwrap copy, the profile file's bytes, whether both profiles are loaded in
enforce mode, the effective child attachment, the service accounts' uid, gid,
groups and sudo posture, or the ancestors' ownership and modes. A quiet drift
check is therefore not requalification. After any trigger (a kernel, AppArmor,
bubblewrap or service-account change, a checkpoint restore, or a reboot, since
reloading the profile at boot is expected but not yet observed here), rerun R4's
`verify` line and R5 under a new authorization, and post both.
