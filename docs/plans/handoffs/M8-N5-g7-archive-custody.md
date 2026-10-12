# M8 N5 g7: preserve historical records under directory custody

Status: additive archive-step successor for separate owner review. This
document authorizes no host action. The controller target remains
`C=f6cd85a6ed247fdcbb44dc002b8a99fdf18f1324`; no production-code change or
new controller pin is introduced. The existing resume still reinstalls `C`.

This continues [#78](https://github.com/sushiHex/constructicon/issues/78).
It replaces only the archive block in
[the retention resume](M8-N5-g7-retention-resume.md), whose frozen source
revision is `d2753f1a5f3d64c8a496360e43e37365b09b6565` (PR #161).
That document and all other frozen sources retain their bytes.

The leaf-mode predicate was an introduced runbook defect: separate frozen
R11 and LR4 shells do not establish one inherited file-creation mask. These
three inputs are public historical records, not installed qualification
authorizations. Their protection comes from canonical operator-owned 0700
workspace directories and trusted root/operator-owned ancestors that nobody
else can write. There is **no leaf mode whitelist** for `retire.json`,
`vendor.json` or `m8_host_artifacts.py`. Each must still be a regular,
current-operator-owned, single-linked file. The installed authorization
reader's separate 0640 law is unchanged.

## Scope, custody and source map

Require fresh owner authorization naming this exact successor revision and
the unchanged retention-resume route. Approval to run the old archive guard
does not authorize this replacement. Require the exact same boot
`d8d9e311-6b35-4d6a-aaeb-cb11c86c5084`, affirmative continuous exclusive
custody/no intervening acquisition, and repeated sudo/drift checks before
any write. Root and the operator are trusted; neither another administrator
nor another process acting as either may mutate these paths during the
checks or move. This is not a concurrent-writer or hostile-root defense.
Changed boot, uncertain custody, drift or any read refusal stops; no R6,
permission repair, recapture or fallback is authorized.

Compose a fresh reviewed archive script as literal
`C=f6cd85a6ed247fdcbb44dc002b8a99fdf18f1324`, followed by the sole block below.
It replaces the retention resume's **Complete LR3 workspace-resume override**
block, not its boot check or any later command. No chmod, copy, normalization
or deletion is permitted. The same-filesystem assertion excludes EXDEV copy
as an apparently successful archive; the guarded same-parent move preserves
the historical bytes, modes and inodes under the custody premise.

| Step | Unchanged source and fresh-shell declarations |
| --- | --- |
| Resume-check | Retention resume at PR #161: literal `C=O`, OC setup at `O`, same-boot check, HS H2 and g7 LR1 anchor override |
| Resume-archive | This document's sole block, with literal exact `C` above; it declares `P`, `O`, `W` and `ARCHIVE` |
| Preconditions/R11 | Retention resume's selected LR3 suffix, then LR3's R11 variant at `C` into absent canonical `W`; never replay the old `O` archive operation |
| LR4/LR5/LR6 | Frozen LR4 / HR R12 / LR6 at `C`; each shell declares exact `C`, `W="$HOME/m8-launch"`, and required `J` (LR4/R12 declare `J` in their blocks; LR6 needs it prefixed) |
| LR8/LR9/R17-R19/LR7 | Frozen route at `C`, original `O` for controller archive; prefix `C/W/J` where needed, including controller `W` for R19; LR7 uses OC setup at `C` and preflight only |
| H2-H8/W0-W4 | Retention resume's g7 overrides and WS blocks at `C`, with unchanged evidence and pin-review pauses |

Here `O=585df33eb196cd4afd10d5c12cb1efb37fd5a6e1` and
`D=8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3` remain the recorded installed
inputs; they are not fresh observations. Audit every script's source revision,
heading, block selection, declarations and bytes. Keep LF/hash verification,
strict noninteractive SSH and execution stdin `/dev/null`. Upload steps into
a fresh package directory, never overwrite historical home step files.
Referenced home common files must be absent or independently byte-identical
to reviewed copies. No N5 common or added `pipefail` enters LR/HR installers.

## Complete archive-custody override

```bash
umask 077
: "${C:?Reviewed merged retention-fix commit required}"
P=d22bff86e8695a7efef04dc3f47c6d4b0847599c
O=585df33eb196cd4afd10d5c12cb1efb37fd5a6e1
W="$HOME/m8-launch"
ARCHIVE="$HOME/m8-launch-refused-$P"
[[ "$C" =~ ^[0-9a-f]{40}$ ]] && test "$C" != "$P" && test "$C" != "$O" \
  && /usr/bin/python3 -I -S -B -c 'import hashlib, json, os, stat, sys
from pathlib import Path
home, p, o = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
w = home / "m8-launch"
archive = home / ("m8-launch-refused-" + p)
uid = os.getuid()
def ancestors(path):
    for parent in path.parents:
        info = os.lstat(parent)
        assert stat.S_ISDIR(info.st_mode) and info.st_uid in (0, uid)
        assert stat.S_IMODE(info.st_mode) & 0o022 == 0
def directory(path):
    info = os.lstat(path)
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == uid
    assert stat.S_IMODE(info.st_mode) == 0o700 and path.resolve(strict=True) == path
    ancestors(path)
def regular(path):
    info = os.lstat(path)
    assert stat.S_ISREG(info.st_mode) and info.st_uid == uid and info.st_nlink == 1
    return path.read_bytes()
directory(w)
directory(home / ("m8-launch-" + o))
directory(home / "m8-controller")
assert w.lstat().st_dev == home.lstat().st_dev
assert not os.path.lexists(archive)
assert not os.path.lexists(home / ("m8-controller-" + o))
assert not os.path.lexists(w / "staging")
r = json.loads(regular(w / "retire.json"))
assert r["schema_version"] == 2 and r["command"] == "judge-retire" and r["commit"] == p
assert r["ready"] is False and r["first_parent"] is True and r["script_matches_commit"] is True
assert r["failure"] == "ValueError: /var/lib/constructicon-m8-launch holds entries the retirement does not name: [\u0027qualification\u0027]"
sha = "f0aa7b3a6e904f04c504e243114ce4b3a9ca99c48326c9c7259c1f9623399ded"
assert r["blobs"]["scripts/ci/m8_host_artifacts.py"]["sha256"] == sha
assert hashlib.sha256(regular(w / "m8_host_artifacts.py")).hexdigest() == sha
v = json.loads(regular(w / "vendor.json"))
assert v["schema_version"] == 2 and v["command"] == "vendor-inputs" and v["commit"] == p
assert v["listed"] is True and v["first_parent"] is True and v["script_matches_commit"] is True
assert v["blobs"]["scripts/ci/m8_host_artifacts.py"]["sha256"] == sha
print("paused-workspace-checked")' "$HOME" "$P" "$O" < /dev/null \
  | /usr/bin/grep -qxF paused-workspace-checked \
  && test ! -e "$ARCHIVE" && test ! -L "$ARCHIVE" \
  && /usr/bin/mv -n -- "$W" "$ARCHIVE" \
  && test ! -e "$W" && test ! -L "$W" \
  && test -d "$ARCHIVE" && test ! -L "$ARCHIVE" \
  && echo paused-workspace-preserved
```

## Stop, continuation and evidence

Require status zero and `paused-workspace-preserved`. Unreadable input, unsafe
ancestor, alias, non-regular or multi-linked file, wrong owner, different
filesystem, missing/contradictory recorded fact, changed source bytes, occupied
archive or later failure stops. No error is recast as a passing provenance
check. Preserve the source history and the old controller workspace; never
alter an input to make the check pass. After a successful move, a later failure
does not authorize replay or overwrite of the archive.

Then continue only the unchanged retention-resume sequence: fresh LR3
preconditions/provenance at `C`, LR4-6, LR8, LR9 only on affirmative installed
tree difference, then LR7. Require all positive records, not merely the final
exit. All H7 controls remain mandatory; H8 stays separately conditional and
at most one attempt. Owner review of complete H7/H8 evidence precedes WRITE;
W4 requires review of actual pins and smoke verdict before any W5. This
successor supplies no W5/W6, retry, READ/T6, credential access or state reset.

Record reviewed source/package hashes, custody and bounded archive result on
#78. Keep private seals and locator-bearing authorization state private.
Tests and offline syntax checks are not host execution or vendor qualification.
