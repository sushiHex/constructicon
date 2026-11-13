# Maintenance instruction binding: delivery record

This records what the instruction-binding change for #407 delivered and the
reviewed bytes it pins. It authorizes nothing: no window, no package and no
live attempt.

## What was delivered

A maintenance instruction is no longer installed code. It is the reviewed base
commit's file at `maintenance/<purpose>.txt`, and its SHA-256 is
`instruction_sha256` in the request the owner approves. The design, its review
record and the owner's decision of 2026-11-12 are in
[`docs/designs/INSTRUCTION_BINDING.md`](../../designs/INSTRUCTION_BINDING.md).

The writer refuses before dispatch unless the instruction it was given is the
text the request pins. The installed diagnostic names those two refusals with
one new cause:

| Writer refusal | Cause |
| --- | --- |
| `maintenance request carries no instruction digest` | `writer-instruction` |
| `maintenance instruction differs from its pinned digest` | `writer-instruction` |

## Superseded statements

`maintenance-channel-reply-task.md` and `maintenance-channel-reply-delivery.md`
describe the instruction as a fixed constant that is never caller-selected.
They are unchanged and describe the guarantee as it was. The guarantee now is:
the exam is never caller-selected; the instruction is the base commit's file at
a path fixed by the task's purpose, named by digest in the approved request,
and the writer refuses any other bytes.

## Pinned bytes

The installed diagnostic's reviewed bytes are pinned per era. Earlier pins stay
as their own records wrote them. The bytes with the new cause are pinned here:

```text
INSTRUCTION_BINDING_DIAGNOSTIC_SHA256=6e34e61291431447a2164c4a0043f65cff88baef89f2a10ba34244b5215e2697
```

`tests/test_m8_maintenance_diagnosis.py` checks the source against this pin and
checks that the earlier pins are unchanged.

## What a later package must do

- Show `instruction_sha256` in the operator's review record and in the posted
  scope. The preview is the whole authorization, so approving its hash binds
  the digest, but the abbreviated record in `maintenance-channel-reply-session.md`
  selects its own keys and omits it.
- Accept `writer-instruction` in its diagnostic cause list. The g11 package's
  frozen list does not.
- Pin the installed diagnostic by the digest above.
- Build its reviewed bundle from a commit that holds the task's instruction
  file. Preparation refuses a base without it.

## What this does not establish

- That a model heeds either instruction. No real model has run them.
- That a package built before this change can run. The application revision,
  the component versions and the source graph hash all changed.
- A specific cause at preparation or preflight. Those commands still report a
  coarse stage; only the writer's refusals reach the diagnostic by name.
