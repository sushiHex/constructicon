# M8 maintenance diagnosis continuation: address discovery

Continuation of the reviewed procedure in [M8-maintenance-diagnosis.md](M8-maintenance-diagnosis.md), refs #186. This note is additive; the accepted procedure remains unchanged. The prior session started from Off, then its local inline address command failed at the PowerShell/Git Bash quoting boundary before SSH. It parked Off. No guest package was installed and no capture was made, so the prior attempt did not occupy the procedure's fresh guest paths. This says nothing about any other state.

## Required order

1. Complete review and CI for the unchanged accepted procedure and the address helper; merge the reviewed head. Reconfirm fresh exclusive custody after those gates and send the start notice before starting the VM.
2. Check the local helper against the reviewed SHA-256 below before starting. Reuse the exact existing D0 file from the accepted procedure. Do not edit it or any D1–D4 file except the already specified measured-boot literal in `common.sh`.
3. From the checked repository root, invoke the reviewed helper through the known operator CPython executable, using the command below. Keep its private result local. Do not place PowerShell inside a shell command or invoke it through nested inline quoting. Python's single bounded readiness interval is only address discovery; it does not establish SSH readiness, host identity, or qualification.
4. Use the discovered address with the already configured private `SSH_TARGET` and `SSH_HOST_KEY_ALIAS`; preserve strict host-key checking. Then read and record the boot id over that fixed SSH transport, and continue with the exact existing D1–D4 sequence and reviewed pins. No edits to those bytes are permitted beyond the measured boot value already allowed by the procedure.

Any unexpected result stops the session under the existing stop rule: preserve state, park cleanly, and report. One start only; no automatic second start, R6, qualification, application/vendor action, or retry is authorized by this continuation.

Helper SHA-256: `9473d05e19e5d0e3161eafd172981e56bfabbb425df1f7aec0e7e7c1f8bdb059`

Run each fence as a non-interactive script file or tool call, never paste it
into an interactive Git Bash session: `exec </dev/null` closes shell input.
From the checked repository root, verify the local script before D0. These
commands read local bytes only; they do not start or query the VM:

```bash
exec </dev/null
printf '%s  %s\n' 9473d05e19e5d0e3161eafd172981e56bfabbb425df1f7aec0e7e7c1f8bdb059 scripts/m8_vm_address.py | sha256sum --check --strict
```

After the unchanged D0 start file succeeds, invoke the Python helper once:

```bash
exec </dev/null
/c/Python314/python.exe -I -S -B scripts/m8_vm_address.py
```

Require exit zero and exactly `status:ok`, `vm:constructicon-m8`,
`state:Running`, and the single validated private IPv4 `address`. A refusal,
unexpected output or timeout stops and parks; do not invoke discovery again.
Python observes metadata under one 60-second monotonic deadline and at most
60 queries. Each fixed read-only query receives the remaining budget;
only a valid response with no suitable address yet may
wait for another observation. The same Python address predicate decides both
readiness and acceptance. Identity/state changes, ambiguity, malformed data,
stderr and process failure refuse immediately; a response arriving past the
deadline cannot be accepted. These bounded observations are not application
retries or additional diagnostic sessions. Process-launch/cleanup overhead is
not claimed as a hard wall-clock bound. Metadata is size-checked after capture,
not streamed under a memory limit. No address is an SSH identity proof.

Set `SSH_TARGET` privately to the existing operator name and that address,
and retain the previously recorded `SSH_HOST_KEY_ALIAS`. Read the complete
boot UUID once with the established pinned transport:

```bash
exec </dev/null
: "${SSH_TARGET:?Private operator and discovered address required}"
: "${SSH_HOST_KEY_ALIAS:?Previously recorded host-key alias required}"
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes -o "HostKeyAlias=$SSH_HOST_KEY_ALIAS" \
  "$SSH_TARGET" /usr/bin/cat /proc/sys/kernel/random/boot_id
```

Require exactly one complete UUID and no extra output. Use it as the sole
permitted `common.sh` replacement, then execute the original reviewed transport
and D1–D4. Keep the target, address and raw local metadata private. Send the
peer a start notice and a release after fresh Off/zero-checkpoint confirmation.
