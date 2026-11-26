# 0028 — The launcher publishes a staged Codex credential

Decision status is recorded in the [ADR index](README.md), for
[#476](https://github.com/sushiHex/constructicon/pull/476). This document is
**proposed**. It authorizes nothing: no code, no pin change, no host update,
no credential handling and no live window. Source references are to main at
`8a7cef5` unless stated otherwise.

## Context

The Codex executor's credential custody rests on one mechanism. The zone's
`CODEX_HOME` is a tmpfs, and the operator store's `auth.json` is bound into
it as a single writable file (`src/constructicon/substrate/executors/linux.py:703-709`).
The [N4 state review](../plans/handoffs/M8-N4-state-review.md) chose that
bind because `rename` and `unlink` over a bind mount fail with `EBUSY`, so a
zone can never replace, delete or symlink the credential, and because the
pinned client saved in place. `tests/substrate/test_operator_store_containment.py:175-176`
and `tests/substrate/test_operator_store_persistence.py:244` hold that
premise. After a run the lane measures the bound descriptor's link count,
mode and modification time (`src/constructicon/substrate/executors/codex_lane.py:263-314`).

The owner's rule is the latest installed client. The latest client, 0.172.0,
no longer saves in place. As read in the vendor's source at the release
commit `3d86e43b`:

- A save resolves the symlink chain, writes a `0600` temporary file beside
  the resolved target and renames it over the target. There is no in-place
  fallback (`login/src/auth/storage.rs:274-295`).
- Every save and delete takes a lock file beside the target, and write paths
  take `$CODEX_HOME/auth.lock` (`login/src/auth/storage_commit.rs:29-67`).
- Logout removes `$CODEX_HOME/auth.json` itself (`login/src/auth/storage.rs:171-178`),
  and `codex login` still logs out first (`cli/src/login.rs:135`).

Under the single-file bind the rename meets the mount and fails. The client
cannot persist a token refresh or a login. Draft PR #476 pins 0.172.0. Its
containment run fails earlier, on a test-side cause (the scripted provider
refuses the new request shape), so no run has yet exercised a credential
save under 0.172.0.

**Unverified.** The vendor facts above are one reader's reading of the
vendor source. The independent design review could not reach that source and
marked all four as unverified. A proof run against the pinned client must
establish them before this decision is accepted.

## Proposed decision

For the Codex executor only, the credential reaches the client through a
per-run staging directory, and the launcher publishes it back.

1. **Stage.** Before spawn, under the retained store lock and after the
   existing binding checks, the launcher creates a private `0700` directory
   on the supervisor's tmpfs and pins it by descriptor. It copies the store's
   `auth.json` into it as opaque bytes. The sealed configuration is laid over
   it read-only, as today.
2. **Run.** The zone's `CODEX_HOME` is that directory. The canonical store is
   not mounted into the zone at all.
3. **Publish.** After every native process is reaped, still under the lock,
   the launcher re-checks custody and opens `auth.json` relative to the
   pinned descriptor without following links. It publishes only a regular
   file with one link, the expected owner, mode exactly `0600` and a nonzero
   bounded size. Publication is a host-created temporary file in the store
   directory, `fsync`, `rename` over the canonical file, then `fsync` of the
   store directory.
4. **Refuse.** Anything else in the staged credential's place (absent, a
   link, a directory, another mode or owner, out of bound) publishes nothing.
   The canonical file keeps its bytes and the run fails closed. Lock files
   and orphaned temporary files in the stage are discarded, never promoted.
5. **Dispose.** The stage is removed with the run. A stage found at startup
   is discarded, never reconciled. There is no recovery owner and no journal
   record, as ADR 0021 requires.

Durable publication is reported separately from run success.

## What changes hands

| Guarantee today | Under this decision |
| --- | --- |
| Constructicon never copies a credential ([ADR 0021](0021-subscription-executors-bind-operator-stores.md), "never ... copies a desktop login, exports a store"; "close/reconcile neither ... copies ... the persistent store") | **Given up.** The launcher copies the credential in and out as opaque bytes. It still never parses it. |
| A refresh is in the operator store the moment the client writes it | **Given up.** It reaches the store only at publication. A crash after the vendor rotates the token and before publication loses it; the operator signs in again under maintenance. |
| The zone cannot replace, delete or symlink the credential (`EBUSY`) | **Replaced.** The zone can do all three to its staged copy. The launcher's publication check refuses the result instead. |
| The zone holds a writable handle on the canonical credential inode | **Strengthened.** The zone never sees the canonical store, its siblings or its lock. |
| Everything else in the client's home is tmpfs and dies with the run | Kept. The stage is tmpfs. |
| Store identity is the binding, not the credential inode or content | Kept. |
| The vendor client owns creation, refresh, provider TLS and logout | Kept. |
| One retained lock serializes local custody through reap | Kept, and held through publication. |

This is a traded guarantee, not a free upgrade. It is the owner's to accept.

## Supersession

If accepted, this supersedes, for the Codex executor only:

- ADR 0021's two clauses quoted in the first table row, and its statement
  that refresh writes to the store are the sole persistent native write;
- the N4 state review's section "Why a single-file bind".

Both documents keep their bytes. The Claude Code lane and every other clause
of ADR 0021 are unchanged.

## Consequences

Acceptance would require, in later separately reviewed changes:

- the layout, checked-object, in-place persistence, disposable-home,
  device-login and lane verdict tests rewritten to the new premise
  (`tests/substrate/test_native_store_launch.py`, `test_operator_store_containment.py`,
  `test_operator_store_persistence.py`, `test_native_egress_bridge.py`, `test_codex_lane.py`);
- the mutation anchors retargeted in `scripts/check_m8_n3a_mutations.py`,
  `check_m8_n3c_mutations.py` and `check_m8_n4_bridge_mutations.py`;
- the operator instructions for login and maintenance superseded;
- physical proof on the target of the publication's atomicity and
  durability, of both launch paths, and of the directory bind under the
  host's confinement profile;
- a new host qualification before any live window.

## Alternatives

- **Stay on 0.160.1.** Keeps every guarantee and needs no decision. It
  breaks the latest-client rule and ages. It is the fallback if this is
  declined.
- **A durable stage with recovery.** Would survive a crash between rotation
  and publication. It puts the client's home on disk and adds a recovery
  owner, which ADR 0021 forbids. Rejected as larger; reconsider only if lost
  tokens prove frequent.
- **A dedicated writable store directory bound into the zone.** Keeps direct
  writes and byte opacity. The zone can then create persistent siblings and
  replace the credential by pathname in the canonical location. Ranked
  second.
- **A symlink from the client's home into a directory mount.** Rejected by
  the N4 state review, and still: the pre-login logout removes the link and
  the new login is lost.
- **A vendor setting that restores in-place saves.** Would rank first. None
  is known; its existence is unverified.

## Before acceptance

1. A proof run that shows, against the pinned 0.172.0 client, the save by
   rename, the two locks and the logout removal.
2. A run under the current layout in which the 0.172.0 client attempts a
   credential save, showing the failure this decision exists to remove.
3. The owner's explicit acceptance of the first two rows of the table.
