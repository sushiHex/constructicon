# M9 operator guide: fixed catalog selection

The installed entry `constructicon.api.m9_trial` connects the existing Codex READ path to a finite catalog choice, then uses the fixed scripted diagnostic exam, owner approval, promotion, replay and rollback. The model chooses `baseline` or `cite-evidence` using only the sealed training input. The recorded `scripted-diagnostic-exam` measures local scripted behavior, not prompt quality on real model answers. Use a trusted, serialized local store: the operator controls its directory and records the synthetic owner's decision; these actors do not authenticate separate OS users.

## Credential-free installed-package rehearsal

Run from this checkout in Bash/Git Bash with its project environment. Choose a fresh store directory. These commands use only the shipped fake executor:

```bash
uv run --python 3.13 python -m constructicon.api.m9_trial rehearse --trial demo --store ../m9-demo </dev/null
uv run --python 3.13 python -m constructicon.api.m9_trial approve --trial demo --store ../m9-demo </dev/null
uv run --python 3.13 python -m constructicon.api.m9_trial promote --trial demo --store ../m9-demo </dev/null
uv run --python 3.13 python -m constructicon.api.m9_trial promote --trial demo --store ../m9-demo </dev/null
uv run --python 3.13 python -m constructicon.api.m9_trial rollback --trial demo --store ../m9-demo </dev/null
```

The first command returns `awaiting-owner`, not a completed promotion. Repeat it in a fresh process to obtain the same pending request. Review the exact edge before `approve`; use `reject` instead to terminate that trial. Approval mints proof without moving stable. The next commands exercise one promotion, replay and rollback. A replay describes the original receipt and does not certify the current pointer. Source stamps bind actual installed package bytes; preserve the source, trial key and store across restart. A different source or independent trial needs a fresh directory.

## Stage map

The entry point is `python -m constructicon.api.m9_trial`. Every stage requires `--trial` and `--store`.

- `seed`: initialize the fixed evaluator baseline.
- `rehearse`: run the fake-backed local rehearsal.
- `pins`: print the current source, task, input, graph, component, provider revision/binding digest, fixed grants, run identity, actor/key, and evaluation label.
- `mint`: print a candidate `qualification-read` authorization bound to those current pins. It does not install authority.
- `propose`: execute or replay the one Codex-backed catalog selection.
- `prepare`: start the scripted diagnostic/issuance path; returns the owner approval request.
- `approve` or `reject`: record the owner decision against that parked request.
- `promote`: promote only the exact attested candidate after successful approved issuance.
- `rollback`: roll back that exact promotion.

`pins` and `mint` require host metadata arguments: `--session`, `--store-key`, `--sealed`, `--qualification`, and `--state`. `mint` also requires `--authorization-id` and an absolute, canonical, not-yet-existing `--attempt-record` path. `propose` additionally requires `--authorization` plus the same host metadata. `--store-key` is a value, not a path. The package does not expose a provider or model selection switch.

The READ lease fixes `gpt-6.1-sol`, effort `low`, no tools or inherited environment names, the restricted native-vendor route and a 120-second executor timeout. The outer selection wait is 180 seconds. The trial requires exact source, task, input, graph, component, provider revision, operator binding, READ grants and one epoch. Tokens are observational, backend request count is unknown, and no finite monetary ceiling is enforced. Historical profiles are not current availability.

## Authority and stop rules

`mint` prints a candidate document only. Root placement of reviewed authorization bytes is a separate privileged act; the existing root-file reader verifies its custody. The host provider assembles `GitAuthority` and its trusted Git checks, service-owned state directories and deny-push hook. Pinning/minting may therefore write service-owned state; it is not literal read-only metadata inspection.

An incomplete or failed selection is terminal for that attempt. Preserve the store and attempt record; do not retry it or create a fresh identity to get another model answer. A completed selection replays from its retained journal evidence before provider construction. A `baseline` result is a successful no-promotion outcome and cannot proceed to preparation or promotion. For a `cite-evidence` result, continue only through the fixed scripted exam and explicit owner decision; the learner cannot define its exam.

## Live boundary

No live command is authorized by this guide. Before any live invocation, require a separately approved exact authorization and fresh gates for the selected installation, current source/pins, trusted host metadata, attempt-record custody, and owner-controlled authorization placement. The following is a notation-only shape: replace every angle-bracket field using that separate approval; it is intentionally not executable as written.

```text
python -m constructicon.api.m9_trial pins --trial <approved-trial> --store <private-store> --session <approved-session> --store-key <approved-key> --sealed <sealed-metadata> --qualification <qualification-metadata> --state <service-state>
python -m constructicon.api.m9_trial mint --trial <approved-trial> --store <private-store> --session <approved-session> --store-key <approved-key> --sealed <sealed-metadata> --qualification <qualification-metadata> --state <service-state> --authorization-id <approved-id> --attempt-record <absolute-new-attempt-path>
python -m constructicon.api.m9_trial propose --trial <approved-trial> --store <private-store> --session <approved-session> --store-key <approved-key> --sealed <sealed-metadata> --qualification <qualification-metadata> --state <service-state> --authorization <owner-authorized-file>
```

Do not infer that these placeholders, old profiles or a printed candidate satisfy a live gate. The separately authorized session retains cleanup, generation withdrawal, VM parking and custody release obligations.


## Delivery evidence

Refs #45. The owner directed this bounded successor to the scripted trial.
The preserved M9 plan and original runbook are unchanged. The fixed application
ships in the controller's runtime-only package; old test imports and rehearsal
command delegate to it. The MCP adapter cannot import this entry. This is a
local experiment, not a new provider or production approval surface.

The installed rehearsal ran the actual CLI with runtime dependencies only,
without tests, scripts or pytest. Scripted native peers exercised the existing
Codex adapter, exact training task, bounded observation, durable attempt and
retained checkpoint. A selected candidate went through the scripted exam, owner
approval, promotion, replay and rollback. Baseline selection did not promote.
Process deaths at intent and after reply but before checkpoint did not permit
another dispatch; registration-only death recovered the keyed command before
one attempt. A surviving attempt denied a restored pre-selection journal.

Mutations implicitly start their host (api/control.py:254-255), so role guards
precede these calls as well as explicit startup. Only the pinned approval
assembly can recover active or parked issuance. The source move exposed a
nonexistent lease acquisition field in the old fixture. Reconciliation now uses
the existing acquisition_id_for producer, with an exercised return-value check.
The fixed case text "TCP connection refused" remains data; the census records
its one reasoned fixture exception, not new unnamed refusal debt.

On M9 source 7a0f8b5007fa8fd41e4a51a4764a0a95a1aae1da, 42 focused cases passed.
Independent Astra review of the native budget, startup, replay, evidence and
refusal boundaries ran 38 focused cases and found no reproduced blocker. Four
distinct mutants in the existing N5 host inventory were assertion-killed:
training task, startup role, terminal proposal and observation bounds. The
review also checked that proof delta. Six composed cases passed on the schema-10
base at f8bf377, including both selections, death/recovery and the installed
entry. Final broad CI receipts belong in the delivery PR.

No live host qualification, vendor binary or model dispatch was performed by
these checks. Scripted evaluation does not measure real prompt improvement.
