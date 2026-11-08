# Maintenance WRITE compatibility audit

Investigation for [#392](https://github.com/sushiHex/constructicon/issues/392),
2026-11-08. This is offline source and scripted execution evidence, not a live
procedure, host qualification, authority placement, or permission to spend a
model attempt. No private SQLite file was opened, and no VM, vendor binary,
login, account request, or model service was run.

The compared Git objects are installed controller **C490**,
`490562a7f0f25b99187702a4342188cfa488e0f6`, and investigation baseline **main**,
`b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32`. Installed bytes and current host
state still require fresh observations; a Git-object comparison does not
establish them.

## Verdict

| Question | Concrete answer | Evidence strength |
| --- | --- | --- |
| Does unmodified C490 implement the fixed maintenance WRITE application? | Yes: `prepare`, `preflight`, `run`, and historical `inspect` already exist, with the same fixed task, grants and application contract as main. | Source, plus the C490 scripted execution below. |
| Is a reinstall required solely because main is newer? | No such source gate exists. Selecting C490 consistently preserves its own adapter identity and schema. Main's changed adapter bytes cannot be substituted under C490 pins. | Source only; no installed-host assertion. |
| Can that application contribute a new accepted file directly against current main? | **No. Both C490 and main already contain the sole allowed output file.** Preparation refuses such a base; the gate and result proof require a one-file addition. | Affirmative Git inventory and source predicates. |
| Can an eligible historical base still run? | Yes at the source-contract level. Historical `5793ef98` and `e38ebbce` contain the three exact installed exam sources and lack the vector file. A result on either is acceptance against that historical base, not current-main improvement. | Source and Git objects only. |
| Is another N5 model WRITE fixture required before maintenance? | No. The accepted maintenance route explicitly replaces that fixture with its own separately authorized application attempt. Fresh startup, installed artifact checks, controls, WRITE-provider preflight and actual pin review remain necessary. | Source and accepted maintenance/N4 procedure law. |
| Is live WRITE readiness established here? | No. Fresh boot/custody, installed artifacts, startup/controls, active binding, preflight and one separately approved application attempt were not observed. | Explicit limit. |

The smallest supported route therefore reuses C490 for an eligible **historical**
add-only task, if that historical result is the approved outcome. It does not
meet a requirement for a new useful current-main contribution. For that outcome,
the blocker is the fixed task's absent-output/addition contract, not a missing
maintenance launcher or an assumed obligation to reinstall. Recreating the
already retained vectors on a synthetic base would not discharge it.

A separately reviewed successor could authorize a baseline-pinned replacement
or extension of the existing data file, or select another useful fixed task and
output path. That requires corresponding preparation, scope, trusted exam and
result-proof changes. This audit implements none of them, removes no existing
file, and relaxes no guard. Changed controller/adapter inputs would then require
the applicable reviewed installation and fresh qualification; equality of the
old application digest cannot qualify that successor.

## Exact source contract

All seven files in `maintenance_application_revision()` compare byte-for-byte
equal in the two Git objects: `api/plan_manifest_application.py`,
`api/maintenance_entry.py`, `api/_maintenance_source.py`,
`api/_maintenance_identity.py`, `core/maintenance.py`,
`substrate/executors/maintenance.py`, and
`substrate/executors/qualification.py`. The digest's closure does **not** include
the Codex adapter, journal schema, or every containment dependency. The digest
alone therefore cannot prove complete runtime compatibility.
Sources: [C490 identity:11](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/api/_maintenance_identity.py#L11),
[main identity:11](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/api/_maintenance_identity.py#L11).

The host profile and assembly (`codex_host.py`), startup producer
(`codex_lane.py`), N5 authorization contract, qualification CLI and WRITE
assembly also positively compare equal. Both profiles fix `gpt-6.1-sol`, `low`,
WRITE workspace isolation, exactly `contained_python`, no allowed environment
names, network `allow` through vendor-session confinement, and 300 seconds.
The maintenance task permits only regular, nonexecutable UTF-8
`tests/vectors/plan_manifest.json`, at most 32768 bytes and 1–64 input cases,
with expected answers supplied by trusted code.
Sources: [C490 profile:106](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/substrate/executors/codex_host.py#L106),
[main profile:106](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/substrate/executors/codex_host.py#L106),
[C490 model:117](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/substrate/executors/codex_lane.py#L117),
[main model:117](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/substrate/executors/codex_lane.py#L117),
[C490 task:59](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/api/plan_manifest_application.py#L59),
[main task:59](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/api/plan_manifest_application.py#L59).

The CLI's supported operations are below. These are input-contract descriptions,
not host commands approved for execution.

| Operation | Inputs and behavior |
| --- | --- |
| `prepare` | `--root`, `--bundle`, `--bundle-sha256`, `--base`, optional `--target-ref` (default `refs/heads/maintenance`). Requires a fresh canonical private service-owned root and reviewed bundle; pins the base and three exam sources; refuses an existing vector. |
| `preflight` | `--root`, `--session`, `--store-key`, `--sealed`, `--qualification`, `--state`, `--launch-root`, `--authorization-id`, `--actor`, `--key`. Assembles actual resources and prints a proposed closed authorization with one-hour expiry; starts no run and dispatches no model. |
| `run` | The same host/root inputs plus `--authorization`. Reads installed root-custody authority, reassembles, verifies exact resources and any retained run before recovery, and drives the existing ControlPlane/RunHost/Graph. |
| `inspect` | Only `--result`. Reads a bounded retained result, explicitly labeled historical application acceptance; does not assemble or recover. |

Sources: [C490 CLI:325](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/api/maintenance_entry.py#L325),
[main CLI:325](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/api/maintenance_entry.py#L325),
[C490 preparation:104](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/api/_maintenance_source.py#L104),
[main preparation:104](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/api/_maintenance_source.py#L104).

Authority pins actor/key (and therefore RunId), graph hash, writer scope and
binding, executor capability/revision, operator binding, request/base/target,
application revision, workspace/gate descriptors, dedicated journal, exclusive
attempt-record path, exact grants, epoch one and expiry. Custody is a root-owned
single-linked `0640` file beneath root-owned directories unwritable by other
principals; service code reads it. Acquisition reserves the exclusive attempt
record before exposing a handle; a journal reset does not restore an attempt.
Published provider unavailability remains. Accepted publication follows joined
shutdown and positive manifest, attestation, sole-base-parent and one-file-addition
proof; it grants no installation, promotion, push or merge.
Sources: [C490 authority:63](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/core/maintenance.py#L63),
[main authority:63](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/core/maintenance.py#L63),
[C490 custody:40](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/substrate/executors/qualification.py#L40),
[main custody:40](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/substrate/executors/qualification.py#L40),
[C490 acquire:2466](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/substrate/executors/codex.py#L2466),
[main acquire:2497](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/substrate/executors/codex.py#L2497).

## Qualification and role boundary

`maintenance_operator_provider()` passes `qualification=None` and the separate
maintenance authorization. The provider refuses simultaneous qualification and
maintenance authorizations. `sealed_account()` checks a closed passing
maintenance startup, its sealed generation digest and exact installed artifact
facts. Its four startup methods are `initialize`, `initialized`, `account/read`
and `account/rateLimits/read`; these contain no model task. This is distinct from
the N5 `qualification-write` fixture, whose optional separately authorized route
is `prepare-write`, `smoke-write`, `mint --stage qualification-write`, then `run`
with its installed authority and dedicated fixture/journal/attempt.
The N4 startup lane itself launches READ with no workspace and an empty catalog;
there is no separate WRITE-startup switch. Fresh startup of the exact installed
artifacts/configuration/generation is followed by actual WRITE-profile assembly
and preflight, then the separately authorized application acquisition. Startup
alone cannot demonstrate WRITE execution.
Sources: [C490 factory:331](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/substrate/executors/codex_host.py#L331),
[main factory:331](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/substrate/executors/codex_host.py#L331),
[C490 startup check:134](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/substrate/executors/codex_host.py#L134),
[main startup check:134](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/substrate/executors/codex_host.py#L134),
[C490 N5 CLI:565](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/api/qualification.py#L565),
[main N5 CLI:565](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/api/qualification.py#L565).

This matches the preserved maintenance procedure: it continues the application
design, **not N5's additional WRITE fixture**, and its P8 explicitly assembles
the genuine installed WRITE provider without a model request. Fresh qualification
and controls, actual pin review and separate application authority remain. N4
startup permits no `turn/start`; interpreting “fresh WRITE qualification” as an
extra model turn would manufacture an additional hurdle and spending decision.
Historical M9 READ evidence cannot supply fresh current-profile startup or a
maintenance WRITE result.
Sources, unchanged at both revisions: [C490 procedure:11](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/docs/plans/handoffs/M8-maintenance-session.md#L11),
[main procedure:11](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/docs/plans/handoffs/M8-maintenance-session.md#L11),
[C490 P8:442](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/docs/plans/handoffs/M8-maintenance-session.md#L442),
[main P8:442](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/docs/plans/handoffs/M8-maintenance-session.md#L442),
[C490 N4:30](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/docs/plans/handoffs/M8-N4-state-review.md#L30),
[main N4:30](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/docs/plans/handoffs/M8-N4-state-review.md#L30).

Role separation remains operator/root/service: root is limited to the selected
procedure's reviewed stock tools and approved helpers; the unprivileged service
runs the application and owns its private application root, state and Git
authority. Root owns the separately installed attempt authorization. Fresh exclusive
custody includes other processes sharing that service identity. A process scan
alone cannot prove it. Quiescence, protected completion and physical cleanup
must be measured by the selected procedure before custody release. None is
inferred from an empty report or local process return. q13's frozen pins and stop
rules cannot be silently reused as permission for a C490 session.
Sources: [C490 roles:79](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/docs/plans/handoffs/M8-N4-host-runtime.md#L79),
[main roles:79](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/docs/plans/handoffs/M8-N4-host-runtime.md#L79),
[C490 custody:19](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/docs/plans/handoffs/M8-maintenance-session.md#L19),
[main custody:19](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/docs/plans/handoffs/M8-maintenance-session.md#L19),
[q13 limits](M8-maintenance-q13-continuation.md#q0-no-go-criteria).

## Existing-output and schema facts

`git ls-tree` positively reports the same `100644` blob
`2c5d088018920547ec2f0a051b6cc97d0223337b` at the vector path in C490 and
main. It has 64 cases and entered main in
`df4b032a5c6df49fd0cb7f50ad0d23bb9818d608` (#250). Its parent
`e38ebbcebd109644705617553055c5d9981cf4af`, and the preserved q13 base
`5793ef98ef5597c9ee9811a0d1f031554eb7f514`, positively lack that path.
For both historical bases, Git-object SHA-256 values match all three constants:

| Source | SHA-256 |
| --- | --- |
| `scripts/regen_plan_manifest.py` | `90015debcf777e1a0d23b8484f04f8781ce96d6766183edcd07c09ac86feaa19` |
| `tests/test_plan_manifest_contribution.py` | `2460fe133113aaf1f6b8756a624fb73e0765295d0912dc9402ac0fc2f396399c` |
| `src/constructicon/substrate/gates/maintenance.py` | `17cae803579f8ec4ebf1518a2beaa7533d0fc3cd16068c59cac55bbe92c7e28e` |

C490 creates schema **10**; main creates schema **11** and adds native metering.
The adapter revision hashes its entire module, so the metering change changes
the executor pin despite unchanged application files. Main's journal opener can
migrate schema 10; opening an original private journal with main is therefore
not a read-only compatibility check. C490 refuses a newer schema. The existing
read-only maintenance diagnostic also requires `user_version ==` its imported
`SCHEMA_VERSION`: using main's diagnostic on C490's schema-10 journal refuses.
Use a proven version-aware read-only consumer or the matching C490 diagnostic;
do not migrate the original to satisfy a report checker. Schema 10 cannot
produce schema-11 metering evidence, and missing historical metering is unknown.
Sources: [C490 schema:116](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/substrate/journal/_sqlite_schema.py#L116),
[main schema:123](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/substrate/journal/_sqlite_schema.py#L123),
[C490 adapter identity:2586](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/substrate/executors/codex.py#L2586),
[main adapter identity:2617](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/substrate/executors/codex.py#L2617),
[C490 diagnostic:244](https://github.com/sushiHex/constructicon/blob/490562a7f0f25b99187702a4342188cfa488e0f6/src/constructicon/substrate/journal/maintenance_diagnostic.py#L244),
[main diagnostic:244](https://github.com/sushiHex/constructicon/blob/b0d2c0b2aa12cb3653d58d6be902f0c1ab76fd32/src/constructicon/substrate/journal/maintenance_diagnostic.py#L244).

## Scripted execution and limits

The targeted C490 proof runs in its own detached checkout and Python 3.13.13
environment, with subprocess stdin closed. Its test node is
`tests/api/test_maintenance_entry.py::test_full_tree_entry_mediates_callback_and_runs_retained_consumer`
(contribution and successful-noop cases): **2 passed, no skips, 88.77 seconds,
child return code 0**. Both cases executed on the unchanged C490 source in a
dedicated detached checkout. The local receipt is retained privately. The checkout's
tracked files remained clean after execution. No result is attributed to main.
The receipt's SHA-256 is
`8aa207e8046e4862a2e0fe1220ef167c5d198c936c3fc2932aaeee32865be10e`.

The fixture imports the committed checkout tree into a disposable parentless
authority and **removes the vector path from that synthetic base**. A scripted
in-memory native peer replaces the vendor process. The real Codex adapter
mediates one callback; actual local Python, Git, capture, trusted gate, renderer,
ordinary retained consumer, SQLite, ControlPlane and joined shutdown execute.
Assertions require completed attempt facts, closed leases, cleared workspace and
gate payloads, unchanged target ref, a sole-base-parent candidate, and publication
only for the contribution. The successful no-op refuses before the checker.

That proves C490's scripted application path and teardown, not novelty, current-main
eligibility, host custody, physical containment, vendor behavior, installed
qualification or live compatibility. It does not call production
`assemble_maintenance()`/`codex_host._operator_provider()`; the existing genuine
host-assembly/preflight test needs the provisioned Linux lane and was not run on
Windows. No skipped test is counted as evidence. Actual preflight/assembly and
the selected host procedure remain distinct measured obligations.
