# M9 fixed operator trial

This repo-local rehearsal uses the reviewed scripted catalog, not a live model.
It writes only a new isolated local store. It is not an installed CLI or a
production approval surface. Run serially as the trusted local operator from
the reviewed checkout. The local account controls the directory and invokes the
owner decision; the synthetic actors do not authenticate separate OS users.
Do not share the store with other processes or edit its contents.

Run from the repository root. Choose a directory that does not yet exist and a
trial key of 1–48 lowercase letters, digits or hyphens, beginning with a letter
or digit. Keep the same key, store and source revision for the whole trial.

```text
uv run python -m tests.e2e.m9_operator_trial prepare --trial demo --store ../m9-demo
```

Expect `awaiting-owner` with the sealed exam, issuance run, exact candidate edge
and durable request identity. You can close the terminal and repeat the command
to read the same pending request. Stable still points to the baseline.

After reviewing that exact edge, choose one of the following commands:

```text
uv run python -m tests.e2e.m9_operator_trial approve --trial demo --store ../m9-demo
uv run python -m tests.e2e.m9_operator_trial reject --trial demo --store ../m9-demo
```

Run only the selected decision. Approval wakes the parked issuance through its
recorded reply. The issuer verifies the retained evidence and owner decision
before minting proof; no stable move occurs. Rejection is terminal for this
trial. Its failed issuance must record the issuer's exact
`M9_OPERATOR_REJECTED` cause; another execution failure is not an owner rejection.

If a process dies during any stage, rerun the same command with the original
key and store. The normal run and command leases must expire before a dead
claimant can be recovered. An immediate retry can report `COMMAND_IN_PROGRESS`
or `M9_WAIT_TIMEOUT`. The latter names the stage, run, durable status and
read-time liveness; it does not cancel the run or imply that its owner died.
Preserve the store, inspect recorded owner liveness, and retry the same command
only when its run/command lease permits recovery. Never replace the key or
submit a different decision to recover.

After approval succeeds, exercise promotion, its replay, then rollback:

```text
uv run python -m tests.e2e.m9_operator_trial promote --trial demo --store ../m9-demo
uv run python -m tests.e2e.m9_operator_trial promote --trial demo --store ../m9-demo
uv run python -m tests.e2e.m9_operator_trial rollback --trial demo --store ../m9-demo
```

Expect one baseline-to-candidate move, the same promotion with `replayed: true`,
then the exact reverse edge. The original runs and candidate remain retained.
A replay describes the original command result; it does not reinstall a
version after rollback. Use a new directory for an independent trial. If a
command refuses, inspect the reason and preserve the store for diagnosis.

The executable regression covers fresh process restart at the real mailbox,
exact evidence verification, no stable move before promotion, exact command
replay and rollback. A separate process-death test verifies recovery from a
committed mailbox reply before approval retry; it stubs the held-out evaluator
and does not claim to prove prompt quality. The earlier fixture covers
independent stale-proof refusal and adverse evidence. This trial does not
measure live model improvement or support free-form prompt bytes.
