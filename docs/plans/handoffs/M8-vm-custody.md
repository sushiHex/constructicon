# M8 VM custody and usage preflight

Additive coordination rules (#209). They change no frozen runbook; a procedure
adopts them by naming this document. They add no scheduler, daemon or lock service.

## Three distinct things

- **Observation** is a fact at one instant: `scripts/m8_vm_usage.py` reports whether
  `constructicon-m8` is Off with operational status exactly `Ok`, zero uptime, zero
  checkpoints and no local `vmconnect` process.
- **Cooperative custody** is a claim among agents over hardline: who holds the VM
  for which work.
- **Owner authorization** is the owner's current approval of the session's exact work.

None substitutes for another. `idle-observed` proves no running guest, no disk merge
or import, and no local console at that instant. It does not observe a remote
VMConnect or Hyper-V Manager session on another machine. It does not prove
exclusive custody, the absence of another administrator's intent, or authorization.

## Preflight

Before any VM session, run:

    python -I -S -B scripts/m8_vm_usage.py < /dev/null

| Verdict | Exit | Meaning | Action |
| --- | --- | --- | --- |
| `idle-observed` | 0 | Off, status `Ok`, uptime 0, 0 checkpoints, no local vmconnect | Check custody, then proceed if authorized |
| `in-use` | 1 | Anything else well-formed, including Running, Saved, Paused, merging | Stop and escalate to the owner |
| `unknown` | 2 | Query failed, timed out, or output was not exactly the record | Stop and escalate to the owner |

A running VM is never silently classified idle. The record is closed
(`schema_version`, `vm`, `verdict`, then `state`, `operational`, `uptime_seconds`,
`checkpoints`, `vmconnect`, or `reason` for `unknown`) and carries no raw query output.

## Maintenance window without asking

An agent may take the window without asking the owner when all hold:

1. the preflight printed `idle-observed` in this session, just before the start notice;
2. hardline shows no conflicting custody claim; and
3. the owner's current authorization covers the session's work.

If any condition is missing or doubtful, ask the owner. The owner is not asked
routinely when all three are positively established.

## Custody over hardline

- **Start notice**, sent to the peers before touching the VM: the session, the boot
  (the planned start) and the scope of work.
- **Release notice**, sent only after an affirmative park measurement: a fresh
  helper run printing `idle-observed`. Stopping the VM is not itself the release.
- Between the two notices peers stay hands-off: no start, stop, checkpoint or
  console connection.

## No stale-claim stealing

An unreleased claim whose holder's liveness is unknown escalates to the owner. Do not
take the VM over, and do not infer release from a missing file, a missing message, a
quiet inbox or an Off VM. Absence is not release.

## Limits

The helper never starts, stops or connects to the VM, and takes no lock. It makes one
query with a 60 second timeout and no retry. It is not authority to resume any
interrupted procedure; resumption needs its own owner authorization.
