# M8 maintenance: continue after completed preservation

This additive procedure continues [#186](https://github.com/sushiHex/constructicon/issues/186)
and the frozen [maintenance session](M8-maintenance-session.md), merged by
[PR #188](https://github.com/sushiHex/constructicon/pull/188) at
`06d5bf6`. It changes only P1's capture and P2's preservation prerequisite.
The owner's continuation authorization covers recommended steps 1-4; record
this procedure's final revision with that authorization before host execution.
No historical procedure, source, runtime or vendor policy changes here.

The first session completed P1 at installed O and captured the private account
seal. P2 created all three archive members and emitted
`d2-prior-records-preserved` after byte comparisons. GNU `cp --no-clobber`
also emitted three warnings, so the operator stopped and parked the VM Off
with zero checkpoints before LR2. This was completed preservation with
unexpected diagnostics, not a failed or partial copy. That disposition covers
only those observed warnings; it creates no stderr allowlist. No LR2,
installation, store maintenance, vendor lane or application request ran.

Keep `$HOME/maintenance-g9-account.seal` and
`$HOME/maintenance-g9-d2-prior` intact. Do not rerun the original capture or
copy blocks, overwrite, normalize, repair, delete or recapture either. Retain
every old operator package; prepare fresh continuation packages with absent
names for every step. A package left by the first session is not reused.

## C0: unchanged pins, custody and one fresh start

Use P0's exact C/O/D/BASE/bundle declarations, deployment guard, source checks,
OC Setup and reviewed composition from the maintenance session. C remains
`01e816ea441ff8f0cee2fa7b82d83873357e6f51`; this documentation revision is
not a new deployment controller. Keep the same reviewed immutable bundle and
the still-unused g9 qualification/application/state/authority paths. Confirm
their absence before the corresponding unchanged step creates them.

Reconfirm exclusive operator/root/service-identity custody now, including
activity during the pause. Notify before starting. Repeat P1's exact native
Off/zero-checkpoint guard and Start-VM block once, then record the full new
boot id. The old boot record is historical. No checkpoint, R6 baseline,
drift repair, second start or reboot is authorized. Stop on uncertain custody
or any unexpected state, output or diagnostic; preserve evidence and park.

Apply P0's fresh LF common/step packages, source heading/hash records,
BatchMode/strict-host-key transports and closed stdin to this continuation.
Use distinct absent package names such as `maintenance-cont-c1-package` and
`maintenance-cont-c2-package`; keep P7's exact service-owned bundle destination
and all later data paths unchanged. Fresh packages hold verbatim delegated
steps with only their documented literal declarations. No runtime rewriting
or generated substitutions are part of the operator procedure.

## C1: repeat controller check, compare existing capture

First repeat prior common at O, HS H2, and P1's exact controller-verifier
block. Review fresh affirmative no drift and `installed:true`, controller
`state:tree`, `different:0` before this separate step. Historical observations
do not replace these fresh facts.

In a fresh prior-common shell at O with HS H2, run the following complete
replacement for P1's capture block. Its reboot-anchor check still requires
exactly `native store anchor is unavailable`; the frozen OC checker enforces
that refusal. Reload and check g8's historical S4/S6a and sealed identity,
then compare the existing private capture to the newly checked pro seal.
This reads no credential and does not qualify the current host runtime.

```bash
binding_check "$W/g8.sealed.json" reboot-anchor -
load_final_qualification
check_sealed "$W/g8.sealed.json" "$Q"
test "${SEAL%%/*}" = pro \
  || { echo 'historical g8 account is not the qualified pro plan; stop' >&2; exit 1; }
test -n "$SEAL"
/usr/bin/python3 -I -S -B -c 'import os, stat, sys
from pathlib import Path
path = Path(sys.argv[1])
info = path.lstat()
assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
assert info.st_uid == os.getuid() and info.st_mode & 0o077 == 0
assert 0 < info.st_size <= 256
fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
with os.fdopen(fd, "rb") as stream:
    opened = os.fstat(stream.fileno())
    assert (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino)
    raw = stream.read(257)
assert len(raw) == info.st_size and raw == (sys.argv[2] + "\n").encode("utf-8")
after = path.lstat()
assert all(getattr(after, field) == getattr(info, field) for field in
    ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid", "st_size", "st_mtime_ns", "st_ctime_ns"))
print("historical-account-capture-revalidated")' \
  "$HOME/maintenance-g9-account.seal" "$SEAL" < /dev/null
```

For this replacement block alone, require exit zero, stdout exactly
`historical-account-capture-revalidated` plus one LF, and empty stderr.
Review HS H2's separate affirmative no-drift output under its frozen contract;
it is not part of the marker-only output. Any unexpected diagnostic,
missing/nonregular/linked or nonprivate capture, bound violation, changed bytes
or failed checker stops
before C2. Do not print or publish the private seal. Single-operator custody
must keep it unchanged for P3's existing comparison.

## C2: validate completed archive before LR2

Run this complete read-only replacement for P2's preservation block after
the P0 deployment guard, without root or N5 common. The archive must be a
real private operator-owned directory containing exactly the three fixed
regular, nonlinked files. Its members must still equal the three unchanged
source records in the real `m8-host` directory. The 1 MiB per-record limit is
this continuation's conservative refusal bound, not a historical D2 contract.

```bash
set -Eeuo pipefail
umask 077
/usr/bin/python3 -I -S -B -c 'import os, stat, sys
from pathlib import Path
source, archive = map(Path, sys.argv[1:])
source_info, archive_info = source.lstat(), archive.lstat()
assert stat.S_ISDIR(source_info.st_mode) and stat.S_ISDIR(archive_info.st_mode)
assert archive_info.st_uid == os.getuid() and archive_info.st_mode & 0o077 == 0
assert (source_info.st_dev, source_info.st_ino) != (archive_info.st_dev, archive_info.st_ino)
names = ("profiles-verify", "verify.json", "qualification.json")
assert {path.name for path in archive.iterdir()} == set(names)
for name in names:
    contents = []
    identities = []
    for directory in (source, archive):
        path = directory / name
        info = path.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        assert 0 < info.st_size <= 1048576
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            assert (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino)
            raw = stream.read(1048577)
        after = path.lstat()
        assert len(raw) == info.st_size
        assert all(getattr(after, field) == getattr(info, field) for field in
            ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid", "st_size", "st_mtime_ns", "st_ctime_ns"))
        contents.append(raw)
        identities.append((info.st_dev, info.st_ino))
    assert identities[0] != identities[1] and contents[0] == contents[1]
for directory, info in ((source, source_info), (archive, archive_info)):
    after = directory.lstat()
    assert all(getattr(after, field) == getattr(info, field) for field in
        ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_mtime_ns", "st_ctime_ns"))
assert {path.name for path in archive.iterdir()} == set(names)
print("d2-prior-records-revalidated")' \
  "$HOME/m8-host" "$HOME/maintenance-g9-d2-prior" < /dev/null
```

Require exit zero, stdout exactly `d2-prior-records-revalidated` plus one LF,
and empty stderr before the separate LR2 step. Missing, partial, changed,
redirected, aliased, extra or oversized content stops without any copy or
repair. Retain both the sources and archive. This proves preservation remains
complete before LR2; it does not establish new physical qualification.
Equality establishes retention continuity, not independently hashed historical
authenticity: simultaneous trusted changes to both copies cannot be excluded
without earlier hashes. The existing trusted root/operator and fresh exclusive
custody/no-intervening-work premise applies. LR2's fresh verify/probe remain
mandatory.

## C3: unchanged LR2 onward and park

Only after both affirmative markers and clean diagnostics, execute the
maintenance session's P2 from LR2 onward and P3-P10 exactly as reviewed in
PR #188. Their common/delegates, source bundle/base/hash, g9 paths, strict floor
8, every H7 control and application pins remain unchanged. No R6, retry or
resume route is added. Use fresh continuation packages for the remaining
steps and preserve historical packages. P6 still permits at most one
conditional H8 request on this boot; P10 still permits one application attempt
under its exact reviewed authorization and limits.

Review stdout and stderr at every boundary, including otherwise successful
commands. Unexpected output or diagnostics stop the session; do not infer
permission from exit zero or a final marker alone. Preserve partial records,
notify and cleanly park with P10's Stop-VM rule. Report only bounded public
evidence on #186 under the session authority; keep the seal, private records
and locators private. Local tests prove these new guards with fake records;
fresh host facts and genuine execution retain the original separate proof
obligations.
