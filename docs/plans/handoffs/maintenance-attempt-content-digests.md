# Maintenance attempt content digests: delivery record

This records what #407 item 2 delivered and the reviewed bytes it pins. It
authorizes nothing: no window, no package and no live attempt.

## What was delivered

A maintenance attempt's outcome facts carry `content_digests`: for each admitted
callback, the sha256 and byte length of the program handed to the worker and of
the worker's retained stdout, and the same for the outcome's output text. The
contract is `core/attempt_content.py`. The Codex adapter produces the block, and
only under a maintenance authorization. The installed diagnostic validates it
against the admitted callbacks beside it and projects it as
`attempt.content_digests`; the maintenance report packet carries it at
`diagnostic.attempt.content_digests`.

No program, output or reply text is retained. A record without the block reads
as `"unrecorded"`, and a block the producer could not state exactly reads as
`"unrecordable"`.

## Pinned bytes

The installed diagnostic's reviewed bytes are pinned per era. The channel
stored-reply era's pin stays as its own record wrote it
(`maintenance-channel-reply-delivery.md`). The bytes with the projection are
pinned here:

```text
CONTENT_DIGESTS_DIAGNOSTIC_SHA256=28a2c47d0b3199131d626181dd8da6b1a467efe2c432428b6c40fbab88781a77
```

`tests/test_m8_maintenance_diagnosis.py` checks the source against this pin and
checks that the earlier pins are unchanged.

## What this does not establish

- That a package built before this change can read the new record. Any package
  that pins the installed diagnostic must be rebuilt with this digest.
- Content. A length separates a short read from an edit, and a digest confirms
  a guess; neither says what a program did.
- The largest packet of every shape. The capture-unchanged packet with eight
  maximal entries measured 3,737 of 8,192 bytes.
