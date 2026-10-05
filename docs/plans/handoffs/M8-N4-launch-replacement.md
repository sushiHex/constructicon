# M8 N4 launch-set replacement after the first login

Status: reviewed runbook. Nothing here authorizes a host action; each run
needs a written owner authorization on #77 naming `C` and these commands.
`M8-N4-host-runtime.md` and `M8-D2-host-installation.md` keep their bytes, and
this document is their successor for one case.

## Why

The launch set's store, `L/operator-stores`, holds the vendor login. Its fixed
removal deletes `L` recursively, so it is valid only before the first login
(`M8-N4-host-runtime.md`, "Failure and recovery"). Security updates stay
enabled on the host (`docs/AGENT_HANDOFF.md`, "Drift is visible rather than
frozen"), and every update to a file the runtime image copied makes
`verify-launch` fail. Without this runbook, each such update would cost a new
login.

**The store is never removed.** A replacement removes only the launch profile
and the five disposable entries (`m8_host_artifacts.DISPOSABLE`): `bwrap`,
`codex-models.json`, `native-codex`, `runtime` and `runtime.json`. It then
installs them again into the kept `L`. Everything else is the reviewed install
as it already is: R11 provenance, R12 staging, R13's file commands and
`verify-launch`.

**Premises.**
- Root is trusted, and no other administrator acts during the run (`M8-D2-host-installation.md`, threat model).
- Quiescence rests on a controlled fresh boot, not on a process scan.
- Every judge and verifier reads the mount table of its own mount namespace, which is root's.

## LR0. Authorization

The owner's authorization on #77 names:
- `C`;
- this runbook;
- the session it continues;
- that M8-D2 requalification and its baseline run under their own authorization when drift requires them.

## LR1. Fresh boot

Clean `Stop-VM`, then `Start-VM`. Never `Save-VM` and never a checkpoint after
login. Record `/proc/sys/kernel/random/boot_id`. From this boot until LR8
passes, run no `maintain`, `activate`, lane or `codex_lane` command, and no
second session. As the service user, with the N4 runbook's common block, the
newest sealed descriptor must refuse for the boot-bound anchor:

```bash
binding_check "$W/<newest>.sealed.json" reboot-anchor -
```

This is the store's own law. It shows no binding can be acquired on this boot;
maintenance later repairs the anchor.

## LR2. Host qualification on this boot

Run M8-D2's R4 `verify` line and R5 probe on this boot, as
`M8-D2-host-installation.md` requires after a reboot ("What `m8-host-drift`
does not cover"). They run in D2's own workspace, at the commit the
qualification set was installed at, and in a fresh shell:

```bash
D=<40-hex commit the qualification set was installed at>
V="$HOME/m8-host"
Y=(/usr/bin/python3 -I "$V/m8_host_artifacts.py")
cat /proc/sys/kernel/random/boot_id
test "${#D}" -eq 40 \
  && sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$V/profiles-verify" \
  && "${Y[@]}" verify "$D" "$V" < "$V/profiles-verify" > "$V/verify.json"
echo "verify exit $?"; cat "$V/verify.json"
cd / && test "${#D}" -eq 40 && sudo -u m8-probe env -i PATH=/usr/bin:/bin HOME=/home/m8-probe LANG=C.UTF-8 \
  /usr/bin/python3 /opt/constructicon-m8-qualification/probe.py \
  --commit "$D" --image local-hyperv/ubuntu-24.04.5 > "$V/qualification.json"
echo "probe exit $?"; cat "$V/qualification.json"
```

- Both must pass as D2's R4 and R5 define.
- If a fact the drift check covers changed (the kernel, for example), take the R6 baseline under its own authorization.
- The bare `/usr/local/bin/m8-host-drift < /dev/null` must then exit 0 with no drift.
- Do not reboot again before LR8 passes.

## LR3. Preconditions and provenance

Archive the old launch workspace, then run R10 with three differences. Its
destination checks move into `judge-retire`. The launch pair may still be
loaded. The service account must already exist, so there is no `useradd`
fallback. Then run the R11 variant below at `C`.

```bash
O=<40-hex commit the old launch workspace was installed at>
test ! -e "$HOME/m8-launch-$O" && /usr/bin/mv -n "$HOME/m8-launch" "$HOME/m8-launch-$O"
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
  && test ! -e "$HOME/m8-launch" && test ! -L "$HOME/m8-launch" \
  && A=$(sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles) \
  && test "$(printf '%s\n' "$A" | grep -E '^constructicon-m8-(bwrap|payload) ' | LC_ALL=C sort)" = "$Q" \
  && echo "LR3 passed"
```

The service account's uid and gid must be the ones the store was provisioned
for. The judges hold the store's group to the service gid, and the store law
holds the rest.

**The R11 variant.** Frozen R11 names the vendor package and catalog by literal
URLs, and its expected digests in prose. Those are the release it was written
for. Here both come from the commit instead: `vendor-inputs` reads them from
the workflow's one acquisition step at `C`, after stock git has proved and
extracted the script, and the downloads are checked against them. Every other
line is R11's, and a test holds the two equal apart from these differences:
- `T` and `M` are not declared;
- the listing and its four reads come after the script's extraction;
- the digest check replaces R11's printed hashes.

```bash
umask 077
C=<40-hex merge commit named in LR0>
W="$HOME/m8-launch"
U=https://github.com/sushiHex/constructicon.git
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
  && /usr/bin/python3 -I "$W/m8_host_artifacts.py" vendor-inputs "$C" "$W" < /dev/null > "$W/vendor.json" \
  && V=(/usr/bin/python3 -I -c 'import json, sys; print(json.load(sys.stdin)["vendor"][sys.argv[1]][sys.argv[2]])') \
  && T=$("${V[@]}" codex url < "$W/vendor.json") && TS=$("${V[@]}" codex sha256 < "$W/vendor.json") \
  && M=$("${V[@]}" catalog url < "$W/vendor.json") && MS=$("${V[@]}" catalog sha256 < "$W/vendor.json") \
  && "${K[@]}" --output "$W/codex.tar.gz" "$T" \
  && "${K[@]}" --output "$W/codex-models.json" "$M" \
  && printf '%s  %s\n%s  %s\n' "$TS" "$W/codex.tar.gz" "$MS" "$W/codex-models.json" | sha256sum --check --strict \
  && sha256sum "$W/m8_host_artifacts.py" "$W/codex.tar.gz" "$W/codex-models.json" \
  && echo "R11 complete"
cat "$W/vendor.json"
```

It must print `R11 complete`. `vendor.json` records the commit, the derived
values, and the pinned URLs and digests, and is posted with the R11 output. A
failed listing stops the chain before any download.

## LR4. Retire (judge, then root)

```bash
J=(/usr/bin/python3 -I "$W/m8_host_artifacts.py")
test "${#C}" -eq 40 \
  && sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$W/profiles-retire" \
  && "${J[@]}" judge-retire "$C" "$W" < "$W/profiles-retire" > "$W/retire.json" \
  && { grep -qE '^constructicon-m8-(launch|workload) ' "$W/profiles-retire"; case $? in
       0) sudo /usr/sbin/apparmor_parser -R /etc/apparmor.d/constructicon-m8-launch ;;
       1) ;; *) false ;; esac; } \
  && sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$W/profiles-unloaded" \
  && { grep -qE '^constructicon-m8-(launch|workload) ' "$W/profiles-unloaded"; test $? -eq 1; } \
  && sudo /usr/bin/rm -f /etc/apparmor.d/constructicon-m8-launch \
  && sudo /usr/bin/rm -rf --one-file-system /var/lib/constructicon-m8-launch/native-codex /var/lib/constructicon-m8-launch/runtime \
  && sudo /usr/bin/rm -f /var/lib/constructicon-m8-launch/bwrap /var/lib/constructicon-m8-launch/codex-models.json /var/lib/constructicon-m8-launch/runtime.json \
  && echo "LR4 retired"
echo "exit $?"; cat "$W/retire.json"
sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$W/profiles-retired" \
  && "${J[@]}" verify-retired "$C" "$W" < "$W/profiles-retired" > "$W/retired.json"
echo "verify exit $?"; cat "$W/retired.json"
```

**`judge-retire`** proves every precondition before root's first write, then records the store's identity (device, inode, service gid) in `retire.json`:
- `L` is a real root-owned 0755 directory, and nothing is mounted at or beneath it, so no removal under it reaches another file system's store.
- The store is a real root-owned 0750 directory of the service group. It is never listed.
- `L` holds no entry the retirement does not name.
- `rm`, `cat` and the parser are root's alone, and so are the ancestors.
- A loaded launch profile still has its root-owned file, which unloading reads.

**`verify-retired`** must exit 0 with `"retired": true`:
- `L` holds only its store;
- the store is the one `judge-retire` recorded;
- the profile file is gone;
- neither launch profile is loaded.

`verify-launch` later holds the replacement to the same identity.

`grep` decides absence only by status 1. An error (status 2) stops the chain;
it is never read as "not loaded".

**Interruptions.** Every stopped state is unavailable, never half-active, because each launch checks its artifacts before a vendor process runs.

| Stopped at | State | Next |
| --- | --- | --- |
| `judge-retire` | nothing written | stop; post the record |
| the unload | profiles loaded, file kept | rerun LR4 |
| the unloaded check | still loaded, file kept | stop |
| a removal | profiles unloaded, some entries left | rerun LR4; removing an absent name succeeds |
| loaded with no file (an outside change) | `judge-retire` refuses | stop for a separate decision |

Never remove `L` or the store. Never run the original fixed removal or restore a
checkpoint. Post every record to #77; a rerun overwrites `retire.json`, so the
posted record is the history.

## LR5. Stage

R12 verbatim.

## LR6. Judge and install into the kept root

R13 without its two `install -d` commands, since `L` and the store are kept.
The judge must report `"replacement": true`. It accepts an existing `L` only
when it holds exactly the store `retire.json` names.

```bash
test "${#C}" -eq 40 \
  && sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$W/profiles-judge" \
  && "${J[@]}" judge-launch "$C" "$W" < "$W/profiles-judge" > "$W/judge.json" \
  && sudo /usr/bin/install -o root -g root -m 0555 /usr/bin/bwrap /var/lib/constructicon-m8-launch/bwrap \
  && sudo /usr/bin/install -o root -g root -m 0444 "$W/staging/constructicon-m8-launch" /etc/apparmor.d/constructicon-m8-launch \
  && sudo /usr/bin/cp -R -P --preserve=mode --no-target-directory "$W/staging/runtime" /var/lib/constructicon-m8-launch/runtime \
  && sudo /usr/bin/install -o root -g root -m 0444 "$W/staging/runtime.json" /var/lib/constructicon-m8-launch/runtime.json \
  && sudo /usr/bin/cp -R -P --preserve=mode --no-target-directory "$W/staging/native-codex" /var/lib/constructicon-m8-launch/native-codex \
  && sudo /usr/bin/install -o root -g root -m 0444 "$W/staging/codex-models.json" /var/lib/constructicon-m8-launch/codex-models.json \
  && sudo /usr/sbin/apparmor_parser --add --skip-cache /etc/apparmor.d/constructicon-m8-launch \
  && echo "LR6 installed"
echo "exit $?"; cat "$W/judge.json"
sudo /usr/bin/cat /sys/kernel/security/apparmor/profiles > "$W/profiles-verify" \
  && "${J[@]}" verify-launch "$C" "$W" < "$W/profiles-verify" > "$W/verify.json"
echo "verify exit $?"; cat "$W/verify.json"
```

`verify-launch` must exit 0 with `"installed": true` and `"replacement": true`.
The second shows it held the store to `retire.json`; a workspace that lost
that record cannot pass.

A failed chain leaves residue that the judge refuses on a rerun. Recovery is
LR4 again, which removes only disposable entries, then LR6 again with the same
staging. The judge proves staging against the recomputed plan, so it is
rejudged, never restaged.

## LR7. Probe

As the service user, with the N4 runbook's common block, run S3's preflight
line. It must print `"launch_ready": true`. It runs the artifact checks and the
benign physical probe, including the
`constructicon-m8-launch//&constructicon-m8-workload (enforce)` attachment.

## LR8. Controller

The controller does not hold the store and changes only with its own inputs.
Verify the installed one at `C` in a fresh workspace. This is R17 without its
`test ! -e /opt/constructicon-m8-controller` (the controller is kept), then R18's
final line. Run R19 after it.

```bash
umask 077
O=<40-hex commit the old controller workspace was made at>
C=<40-hex merge commit named in LR0>
W="$HOME/m8-controller"
U=https://github.com/sushiHex/constructicon.git
E=(/usr/bin/env -i PATH=/usr/bin:/bin HOME=/nonexistent LANG=C.UTF-8 GIT_CONFIG_NOSYSTEM=1 GIT_GRAFT_FILE=/nonexistent)
G=("${E[@]}" /usr/bin/git --no-replace-objects "--git-dir=$W/source.git")
K=("${E[@]}" /usr/bin/curl -q --fail --location --proto =https --silent --show-error)
J=(/usr/bin/python3 -I "$W/m8_host_artifacts.py")
test ! -e "$HOME/m8-controller-$O" && /usr/bin/mv -n "$W" "$HOME/m8-controller-$O" \
  && test "${#C}" -eq 40 && /usr/bin/mkdir "$W" "$W/wheels" \
  && "${E[@]}" /usr/bin/git init -q --bare "$W/source.git" \
  && "${G[@]}" fetch -q --no-tags "$U" +refs/heads/main:refs/heads/main \
  && "${G[@]}" rev-parse refs/heads/main && "${E[@]}" /usr/bin/git ls-remote "$U" refs/heads/main \
  && "${G[@]}" rev-list --first-parent refs/heads/main | grep -qxF "$C" && echo first-parent \
  && "${G[@]}" ls-tree "$C" -- scripts/ci/m8_host_artifacts.py uv.lock \
  && "${G[@]}" cat-file blob "$C:scripts/ci/m8_host_artifacts.py" > "$W/m8_host_artifacts.py" \
  && "${J[@]}" controller-wheels "$C" "$W" < /dev/null > "$W/wheels.json" \
  && /usr/bin/grep -o '"url": "https://files.pythonhosted.org/[^"]*"' "$W/wheels.json" \
       | /usr/bin/cut -d'"' -f4 > "$W/wheels.txt" \
  && test -s "$W/wheels.txt" \
  && ( set -e; while read -r u; do "${K[@]}" --output "$W/wheels/${u##*/}" "$u"; done < "$W/wheels.txt" ) \
  && sha256sum "$W/m8_host_artifacts.py" "$W"/wheels/*.whl && echo "LR8 fetched"
"${J[@]}" verify-controller "$C" "$W" < /dev/null > "$W/verify.json"
echo "verify exit $?"; cat "$W/verify.json"
```

`verify-controller` must exit 0 with `"installed": true` and `different: 0`.
If it refuses, the controller replacement (its removal, then R17 to R19) needs
its own authorization.

Then the N4 session resumes at S0 at `C`.

## Evidence (posted on #77)

- The authorization, `boot_id`, the LR1 refusal, and the LR2 records.
- `LR3 passed`, and the R11 output.
- `retire.json`, the `LR4 retired` line, and `retired.json`.
- `stage.json`, `judge.json`, the `LR6 installed` line, and `verify.json`.
- The LR7 line, and the LR8 records.
- The continuity facts: the old and new `C`, the old and new `runtime_digest`, the store identity, and which N4 steps rerun.

## What this does not establish

- **The binding's contents.** The store directory is shown to be the one `judge-retire` found (device and inode, same boot). The binding inside it is judged by the store's own law at the next maintenance, not here.
- **Physical behaviour beyond the host's own records.** The fake-root tests prove the commands' logic as a non-root user. Real root ownership, real mounts and real AppArmor removal are observed only by this runbook's records on the host.
- **A hostile root, a concurrent administrator, or another mount namespace.**
- **A correction to an accepted plan.** `M8-N4-host-runtime.md` says `cp --no-target-directory` makes an existing destination fail. It does not; it only prevents nesting. Absence and custody are the premises, as here.
