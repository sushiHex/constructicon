# Operator helper/caller source contracts

Living implementation record; Refs [#308](https://github.com/sushiHex/constructicon/issues/308).
The broader phase-output/preparation issue remains open. This bounded slice
persists offline caller/helper checks in the existing procedure packager and
M9 qualification selection, without adding an execution language or scheduler.

## Boundary and use

The [stopped successor](https://github.com/sushiHex/constructicon/issues/45#issuecomment-6702703970)
changed a historical caller's parent while retaining a helper that pinned the
old parent, runtime and raw evidence hashes. Individual script/archive tests
did not execute that composition. The
[corrected private package](https://github.com/sushiHex/constructicon/issues/45#issuecomment-6702820405)
and its historical helper remain frozen and are not inputs executed by this
implementation.

The existing `scripts/m8_procedure_package.py check-contract SCRIPT CONTRACT.json`
entry checks one closed JSON object with `helper`, `caller` and `bindings`.
`helper` and `caller` are complete literal blocks, final LF included, each
present exactly once as whole lines. `bindings` maps reviewed shell declaration
names to their exact right-hand-side text; one canonical top-level declaration
per name must match. The helper block includes its static runtime/evidence
arguments. Select these expectations independently from the helper's accepted
contract, then check the proposed composition. Copying expectations from the
candidate itself would prove only self-consistency.

The repeatable JSON result binds script, contract, helper and caller digests
and declaration names. It explicitly says `selected-literal-source-only` and
`not-executed`. It does not parse shell, discover every call, prove input
semantics, detect indirect rebinding or establish host absence/custody. Source
review and an actual permitting/refusing execution fixture remain necessary.

M9 selection schema 2 requires a `helper_contracts` object with exactly the
existing phase names plus cleanup. Each phase supplies a list of these literal
contracts; an empty list explicitly declares no selected helper for that
phase. At least one contract must be present overall. The constructor checks
every selected contract before creating work paths or issuing any external
call. Per-phase source proofs are retained in the existing `SOURCE-PINS.json`
and package manifest. Schema 1 remains readable with explicit
`legacy-unverified` coverage. Neither coverage label claims inventory
completeness or semantic execution proof. Independent review still selects the
selection digest; this is not an approval generator.

The canonical READ compiler, transport and readback locations remain the
authority for their existing outputs. The new check does not relocate outputs,
turn repeatable read checks into acquisitions or change frozen shell fences.
The fake contract consumer and M9 selection exercise the same check (I6).

## Executed evidence and limits

Windows/Python 3.13 focused checks executed the literal Bash/Python fixture
caller and helper twice successfully, and executed the transplanted-parent
refusal. The fake filesystem is a closed mapping of historical role paths to
synthetic evidence; missing keys never fall back to the native filesystem.
Runtime/static hash/caller/declaration changes refuse source validation even
when the candidate script digest is updated.

The complete M9 fake transport runs qualification, live recheck, withdrawal and
park through the existing boundary, including real fixture caller/helper
execution. Every external call has exactly one of twelve explicit fake
classifications; unknown and ambiguous calls fail without native fallback.
Transplant and incomplete inventory selections refuse before any external call
or work-directory creation. CLI source checks are repeatable. Three added
mutants were assertion-killed: omit helper bytes, relax declaration equality,
and omit M9 contract checking.

Focused packager/contract/M9 tests passed 149 cases. Related READ session/window,
M9 and mutation-inventory regressions passed 130 cases. `ruff check src tests`,
changed-script byte compilation and staged-diff checks passed. These are focused
local results, not an executed full `verify` gate.

The delivery PR owns final-head CI and independent review evidence. These local
proofs establish no current private helper acceptance, vendor/model/account
behavior, physical Linux isolation or host qualification. No VM operation,
credential, vendor binary, paid call, frozen-plan edit or stopped-window resume
was performed. Broader OBSERVE/recovery/preparation consumers remain #308's
scope, not completion claims of this slice.

## Closed history with ordinary producer modes

A later private stop measured service-owned `0700` source roots, with ordinary
Git/trial descendants at `0775`/`0664`. The private archive's flat rejection of
group-write bits refused these before its first mutation. The selected private
archive and captures remain frozen; the correction is a shared source core for
a future independently reviewed package, not a modification or replay of them.

`private_tree_facts(path, root)` requires an explicit canonical, same-owner,
unprivileged `0700` directory root and a canonical contained descendant on the
same filesystem. Every node must be same-owner directory/regular file; regular
files must have one hard link. Symlinks (including ancestors), special nodes
and Windows reparse points refuse. All descendant modes are observed and
retained, not normalized: a `0777`/`0666` descendant is accepted behind the same
private boundary, while a `0777` root refuses. Sidecar readers must use this
same root-bound facts function;
replacing only inventory would leave the old flat guard on DB/WAL/SHM reads.
Trusted common-parent/archive guards remain separate and strict.

The inference supporting this policy is limited: Linux pathname resolution
requires search permission through the private root
([path_resolution(7)](https://man7.org/linux/man-pages/man7/path_resolution.7.html)).
For Linux POSIX ACLs the group bits reflect the access mask, which also bounds
named-user/group grants, so root mode `0700` does not leave those grants effective
([acl(5)](https://www.man7.org/linux/man-pages/man5/acl.5.html)). This assumes trusted
administrators and owner, trusted ancestry, existing exclusive/quiescent custody,
and no hostile retained handles or exports outside the checked namespace. It
does not prove arbitrary filesystem ACL semantics, inspect ACL/xattr bytes, or
discover aliases exported in another namespace. Same-owner/hardlink checks alone
would not establish those assumptions.
Non-bind exposures through overlay lower/upper directories, FUSE daemon data
sources or NFS exports are also caller-custody assumptions. This check neither
parses those mechanisms nor proves they are absent.

The inventory reads a bounded nonempty `/proc/self/mountinfo` snapshot, validates
its rows and affirmative root mount, and passes that exact snapshot to the
existing `m8_host_artifacts.mounts_beneath` matcher. Its added optional `listing`
keyword leaves existing default callers unchanged. Query failures, malformed or
empty results, and mounts at/below the source refuse. Mount checks run before
and after inventory; no absence is inferred from an unexecuted query. Exported
aliases in other namespaces remain an explicit limit.

A narrow review follow-up checks mount **sources** in that same validated
snapshot too. The initial core documented alias absence as an assumption; no
host alias was observed. This follow-up checks its current-namespace part.
The unique longest canonical mount-point ancestor must match
the private root's `st_dev`; an absent, ambiguous or device-inconsistent mapping
refuses. The containing mount's filesystem root plus the private path relative
to its mount point gives the private in-filesystem path. Any same-device mount
source at/below that path refuses, including an alias exported to an unrelated
namespace pathname. Ancestor/whole-filesystem aliases still traverse the `0700`
root and are permitted. Filesystem-root strings use lexical `PurePosixPath`,
never namespace resolution. This uses the kernel's
[mountinfo field definitions](https://www.kernel.org/doc/html/latest/filesystems/proc.html#proc-pid-mountinfo-information-about-mounts),
including major/minor as the `st_dev` identity. No mount syscall is introduced.

`private_tree_inventory_source()` emits the exact shared facts/inventory and
pure mount-matcher function sources with fixed stdlib globals. The guest never
imports or executes a CI module/entry. A future private compiler embeds and
pins these bytes in its existing package; it must bind every sidecar call to
the correct root. This changes no native account-store/credential policy.

Linux tests run actual bare Git creation under umask `0002`, assert native
`0775`/`0664` descendants behind `0700`, compare imported/emitted inventory,
and verify exact inode/device/owner/group/mode/bytes across rename. The complete
fake archive checks both source roots and every synthetic `0664` DB/WAL/SHM
sidecar through the emitted core before any mutation. Root, owner, symlink,
hardlink, FIFO, out-of-root and kernel-query refusals are covered. Only the
foreign-descendant ownership case substitutes unavailable cross-user chown;
mount-failure cases substitute kernel-query bytes, not permission observations.

Local Windows results: 17 focused cases passed, 20 physical Linux cases skipped.
The emitted source ran in isolated stdlib Python and truthfully refused physical
inventory on Windows. Broader packager/host/mutation-inventory regressions passed
177 cases with 19 skips before the final isolated-entry test was added. Three
additional physical mutants are wired into the existing inventory but have not
been measured locally. Native Linux CI must execute the permitting/refusing
cases and mutants before this correction can support a new package. No host
chmod, normalization, frozen-private-byte change, vendor binary or VM operation
occurred. A further host start still requires a fresh owner go-ahead.

The source-alias follow-up keeps 17 portable passes and adds eight Linux cases
(28 physical skips locally): root/descendant export refusal, parent/whole-FS
export acceptance, octal-escaped paths, device mismatch and ambiguous mapping,
each through imported and emitted source. One additional mutation removes this
source-alias guard. Those native cases and its kill remain unmeasured until CI.

A further review reproduced an introduced source-format assumption: Linux v6.8
[`fs/nsfs.c:nsfs_show_path`](https://github.com/torvalds/linux/blob/v6.8/fs/nsfs.c#L235-L247)
emits roots such as `net:[inode]`, which are not absolute paths. The prior
whole-snapshot root-path guard rejected these even on unrelated devices.
Only roots on the private tree's `st_dev` now need canonical absolute filesystem
paths. Every device's mount point remains validated and participates in choosing
the containing mount; a more specific wrong-device mapping explicitly reports
`containing mount device mismatch` rather than falling back to a shorter one.
Imported/emitted regressions accept an unrelated nsfs root and refuse nested or
malformed nsfs mount points, a non-path root on the relevant device, and a wrong-
device nsfs containing mount. Focused Windows results: 17 passed, 33 physical
Linux skips. No broad suite was repeated for this correction; native results
remain the final-head CI's responsibility.
