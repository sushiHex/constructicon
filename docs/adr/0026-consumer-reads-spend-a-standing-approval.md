# 0026 — A consumer READ spends a standing owner approval

**Status:** proposed, 2026-11-17. Refs
[#442](https://github.com/sushiHex/constructicon/issues/442). It refines
accepted [ADR 0025](0025-consumer-runs-earn-a-permit.md) and supersedes
exactly the clauses listed under "Superseded".

Accepted [ADR 0018](0018-live-executors-are-leased-contained-processes.md),
[ADR 0021](0021-subscription-executors-bind-operator-stores.md) and
[ADR 0024](0024-retain-native-executor-metering.md) keep governing. This
record changes none of their clauses and no invariant. It authorizes no live
window, permit, credential or model call.

Source references are to `main` at `6bd6d57` unless they name a symbol
added by this change. Paths start at the repository root.

## Context

ADR 0025 admits the change-review advice consumer only as an owner-permitted
run. The operator tooling implemented that approval as a human step inside
the live window. After qualification, the supervisor published the actual
pins and a challenge (`scripts/ops/m9_read_window.py:237-260`). It then
waited up to `MAX_PIN_WAIT`, fifteen minutes (`:28`, `:234`), for a trusted
operator to record the owner's decision on that challenge
(`scripts/ops/m9_owner_approval.py:92-156`;
`scripts/ops/README.md:24-43`).

The owner's direction (2026-11-17): per-run human approval inside a pin wait
of at most fifteen minutes is too fragile. A missed or late decision spends
a host start, a startup qualification, a withdrawal and a park for nothing.
Never put a human on a timer. Consumer READs must spend a standing,
conditioned owner approval instead, and the supervisor must check it
mechanically.

## Decision

### 1. The record

A `StandingApproval` (`scripts/ops/m9_owner_approval.py`) is one canonical
JSON record: sorted keys, one trailing LF, with a closed key set. It lives
directly in the private custody directory. The CLI names it by
`--approval PATH --approval-sha256 DIGEST`, exactly as `--selection` and
`--selection-sha256` name the selection
(`scripts/ops/m9_native_read.py:151-152`).

Each of these keys is matched by exact equality against the actual pins:

- `consumer`: only `change-review-advice`;
- `controller` (the installed commit) and `runtime`;
- `source_graph`, `component`, `guard`, `capability`, `actor`, `scope`;
- the whole `grants` object: model, effort, tools, timeout, posture,
  network and env allowlist;
- `host_key_alias`: the host's stable identity (below).

These keys bound the record:

- the **instruction class** is the `guard` pin together with
  `instruction_max_bytes`, which may never exceed the route's
  `INSTRUCTION_MAX_BYTES` of 8,192
  (`src/constructicon/api/change_review_advice.py:110`). Any instruction
  that the pinned guard builds and that fits the bound is in the class;
- `max_runs`, an integer of at least 1. The tooling scans at most 100;
- `not_after`, in UTC ISO 8601;
- `exposure`, the exact literal `subscription; backend requests unknown; no
  enforced monetary ceiling`;
- `schema_version`, 1.

Keys that are fresh per window are **forbidden**, and each is refused by
name: `boot`, `generation`, `provider_revision`, `operator_binding_digest`
and `candidate`. The tooling also forbids `target` (below). Any other
unknown key refuses.

**Host identity.** The stable identity is the strict host-key alias, not the
DHCP target. The target is `user@IPv4`, checked only for shape, and changes
with every boot (`scripts/ops/claude_read_session.py:75-78`). The alias is
checked by `_target` (`:79-81`). Every SSH and SCP passes it as
`HostKeyAlias=<alias>` with `StrictHostKeyChecking=yes` and `BatchMode=yes`
(`:84-96`). So the transport accepts only a peer whose host key matches the
known-hosts entry that the alias names. The selection must name the same
alias as the CLI (`scripts/ops/m9_qualification_boundary.py:389`). Fresh
transport discovery and the selection's per-boot target are validated as
they are today.

### 2. Two check points

- **(a) Before any process.** The record parses and its digest matches. It
  is unexpired, unrevoked and unsuspended, and it has a free slot. It fits
  everything the reviewed selection already fixes:
  `QualificationBoundary.selected_pins()` exposes the consumer, controller,
  runtime and alias. It also exposes the consumer's fixed pins
  (`_advice_fixed`, `m9_qualification_boundary.py:239-255`, selected at
  `:528`). The window then holds `active`
  (`scripts/ops/m9_read_window.py:190-191`) and creates
  `suspended-<record digest>` exclusively. A refusal here raises its code,
  unlinks `active` and leaves nothing behind.
- **(b) After qualification.** The same field comparison runs against the
  checked packet's actual bytes: the consumer's printed pins, its alias,
  controller and runtime. Expiry, revocation and suspension are checked
  again, and only this window's own admission marker may be present.

A mismatch is a named refusal, `approval-<field>`. It is never an
escalation: there is no in-window human step and no manual fallback.

### 3. Runs are counted and never refunded

The decision digest is H(record digest, slot *k*). Here *k* is the lowest
slot no greater than `max_runs` whose marker is absent. The claim reuses the
existing exclusive `selection-<decision_sha256>` marker
(`m9_read_window.py:305-311`), created with `open(..., "xb")`. Two racers
cannot take one slot: the loser's create fails and it moves to the next
slot. A crash after the create leaves the slot spent. A spent slot is never
refunded, including when the window refuses after its claim or replays a
physical qualification. The `active` marker still serializes windows.

### 4. Suspension and revocation

- **Suspension.** A window writes `suspended-<record digest>` at admission
  and removes it only when it ends accepted and clean, meaning an accepted
  READ digest with custody released (`m9_read_window.py:421-445`). Any
  other end leaves it in place, and so does a crash. Every later window
  refuses with `approval-suspended` until the owner issues a new record.
  A failed removal keeps the approval suspended, never the reverse.
- **Revocation** is the owner's act. The owner deletes or replaces the
  record, or creates `revoked-<record digest>` in custody. The marker needs
  no content, and nothing removes it.
  - Before load, a deleted or replaced record refuses with
    `approval-unreadable` or `approval-digest`.
  - After load, both check points re-read the record's file. If it is gone,
    or no longer holds the loaded bytes, they refuse with
    `approval-revoked`, as the marker does.

Expiry, suspension and revocation are checked at both check points.

### 5. Retired

- `ManualApproval` and its `approval.json` exchange
  (`m9_owner_approval.py:92-156`; `scripts/ops/README.md:24-43`).
  `private_directory` (`:18-89`) stays. `StandingApproval` replaces it, so
  the noun count does not grow.
- `MAX_PIN_WAIT` (`m9_read_window.py:28`, `:234`). The pin cutoff is now
  `cutoff - route_reserve`.
- The challenge's `approval_not_after` (`:245-248`) and its restated card
  literals for model, effort, epochs, turns, executor seconds and exposure
  (`:251-256`). The record carries them as `grants` and `exposure`. The
  challenge and result schema becomes 2: the challenge names
  `approval_sha256`, and the result names the approval, its spent slot and
  whether the approval is suspended.
- The two-method owner boundary, `await_owner` and `check_owner_decision`
  (`m9_native_read.py:59-66`; `m9_read_window.py:131-134`). One pure
  `selected_pins` replaces them, and `place` receives the spent slot's
  decision.

The per-run permit's wire format and law do not change. Nothing under
`src/` changes. Each window still mints, reviews mechanically and places
one fresh READ permit, which names that window's binding and generation.

### 6. M9

M9 has no standing record and cannot be issued one. The record's `consumer`
must be `change-review-advice`, and issuance refuses an M9 selection. Every
M9 window therefore refuses at check point (a) with `approval-consumer`,
before any process. This is the minimal choice. M9's selector ran its one
live window (ADR 0025, "One consumer already runs this way"), and a new M9
window would need its own decision.

### 7. Issuance

`m9_owner_approval.py` builds the record from a reviewed schema 3
selection's fixed pins. Its `issue` function is pure, and its CLI writes the
record exclusively and prints the digest (`scripts/ops/README.md`, "The
standing approval"). The owner records issuance as that digest in an owner
issue comment. There is no signing key, and the record's authority is its
reviewed digest and private custody, as for a selection.

### 8. Metering

Metering does not change. ADR 0024's journal metering already reaches the
public result (ADR 0025, section 6). Shared-quota deltas are not run spend,
and the record carries no monetary field because none is enforceable.

## Superseded

Each clause below is superseded only for consumer READs that spend a
standing approval under this record:

- **ADR 0025:87-91 (fact 4).** "The owner's approval of each exact dispatch
  is the only bound on task data and cost". The bound on task data becomes
  the instruction class: the pinned guard and summary builder plus
  `instruction_max_bytes`. In place of a per-run decision, spend is bounded
  by dispatch count and duration: at most `max_runs` dispatches of one
  turn, each at most 120 seconds (`READ_GRANTS.timeout_s`,
  `src/constructicon/substrate/executors/codex_host.py:95-103`), under
  `not_after`. Money and backend requests stay unknown, as the exposure
  statement says. Fact 4's conclusion stands: an *available* executor has no
  such step, and executors stay unavailable.
- **ADR 0025:113-116.** "Root placement is the owner's act." Root placement
  becomes the supervisor's act, performed only after both check points and
  one spent slot of the owner's standing approval.
- **ADR 0025:151-152.** "The owner approves the digest by approving the
  permit." For class-mode consumers, the owner approves the instruction
  class and does not approve each digest. The node and the provider still
  bind the run to the exact instruction digest (ADR 0025, section 2).
- **The one-approval-per-run lines:** ADR 0025:322-324 ("one owner
  approval" per run), :426-427 ("One window can carry N exact permits
  approved in one step") and :457-458 ("A live run needs its own permit
  and its own owner approval"). A live consumer run still needs its own
  permit. Its owner approval is one slot of a standing record.

Distinguished, not superseded: **ADR 0025:275-292, the rejection of option
(a)**, a standing availability authorization. That rejection stands: a
permit must name the provider's binding, and the binding dies at
withdrawal. Here the *approval* is standing and the *permit* is not. The
record forbids every binding-, generation- and boot-scoped key, and each
window mints and places its own per-run permit under the unchanged permit
law. No family, budget or ledger enters `core/permit.py` or `codex.py`, and
no adapter revision moves.

## Guarantees lost

Two guarantees are traded, stated at their real strength:

- **The owner no longer sees each run's exact instruction text before it
  is sent.** The text is still bound: the run's identity commits to its
  digest, and the summary is a selected, digest-checked file. The owner
  approves its class, not the text.
- **There is no same-hour positive consent.** The consent is the issuance,
  up to `not_after` before the run.

What is bounded is the dispatch count and duration: at most `max_runs`
one-turn dispatches, each at most 120 seconds, which is three for the
recommended issuance. That is not a monetary bound. Money and backend
requests stay unknown, there is no enforced monetary ceiling, and the record
carries no monetary field because none is enforceable. Every window still
pays its host start, startup qualification, withdrawal and park.

## What does not change

- Every window still qualifies its own fresh boot and state. This record
  does not claim "no requalification".
- Adapter and application identities are unchanged, because `src/` is
  unchanged. Only operator tooling under `scripts/ops/` moves.
- The permit wire, schema and law; the published unavailability reasons;
  the default route; metering.

## The owner's choices taken

- One consumer: `change-review-advice`.
- Instruction class, not instruction digest.
- Recommended issuance of seven days and three runs. These are the CLI
  defaults.
- Refuse on any deviation, naming the field, with no manual fallback.
- Suspend after any run that does not end accepted and clean.
- Record issuance as the record digest in an owner issue comment, with no
  signing key.

## Refusals

| Refusal | Where |
| --- | --- |
| `approval-location`, `approval-unreadable`, `approval-digest` | loading the record named on the CLI |
| `approval-shape`, `approval-canonical`, `approval-unknown-key`, `approval-missing-<key>`, `approval-forbidden-<key>`, `approval-<key>` for a malformed value | loading |
| `approval-expired`, `approval-revoked`, `approval-suspended`, `approval-exhausted` | check points (a) and (b) |
| `approval-consumer`, `approval-controller`, `approval-runtime`, `approval-host_key_alias`, `approval-pins`, `approval-<pinned key>`, `approval-instruction_max_bytes` | check points (a) and (b) |
| `approval-exhausted` at the claim | the slot scan finds no free slot |

## Proof

The tests are credential-free (`tests/test_m9_owner_approval.py`,
`tests/test_m9_read_window.py`, `tests/test_change_review_read.py`). They
show:

- the full chain reaches the READ with a valid record and no human step;
- each fixed field, forbidden key, unknown key, wrong digest, expiry,
  suspension, revocation and exhaustion refuses by name, with zero
  transport calls at check point (a);
- slots are spent at claim and never refunded, a crash after the claim
  spends the slot, and two concurrent claimers cannot take one slot;
- suspension is written after a run that is not accepted and clean, and
  the next run honors it;
- a changed DHCP target with the same strict alias is accepted, and a
  different alias is refused;
- M9 refuses before any process.

They cannot prove that the owner's issue comment, the custody directory's
contents or the installed host match.

## Not verified

- No live window has spent a standing record.
- That the Windows custody ACL check and exclusive-create semantics hold on
  the operator's real custody volume. The tests run on a temporary
  directory.
