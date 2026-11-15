# Operator preparation coverage (Refs #308)

This is a census of the current repository-owned preparation entries, not an
execution procedure or a grant. Source provenance, an independently selected
procedure and explicit owner authorization remain prerequisites. Host absence,
custody and current boot are host observations, not facts established offline.
See [operator instructions](../scripts/ops/README.md) for the complete contracts.

| Consumer | Entry and locations | Coverage and limit |
| --- | --- | --- |
| Claude READ, including controller and launch verification and prepared withdrawal | `python -I -B scripts/ops/claude_read_session.py describe` exposes preparation fields, phase checks and readback names, with selected evidence slots. `claude_read_window.py describe` lists the fixed sequence. `prepare-bindings` derives role-named paths from installation facts and a fresh namespace; the window keeps `work/<phase>/package`, checked receipts and next bindings, except precompiled withdrawal at `evidence/cleanup-package`. Each transport claims a remote directory named from namespace, phase and package manifest; `readback_spec` maps each output to its declared source and local evidence slot. | The generated READ Linux rehearsal exercises the sequence, actual shell, readbacks and receipt gates with fake external boundaries. Controller verification is a READ phase, not a general controller installer/preparer. An uncertain withdrawal still requires the separately reviewed recovery disposition. |
| Codex M9 READ qualification | `scripts/ops/m9_native_read.py` takes a reviewed selection and digest; `QualificationBoundary` stages cleanup first and then its fixed qualification phases. Local packages live under `work/<phase>`; each remote directory is named from that phase's manifest. D2 verification reads the record from the same staged directory. | The fake transport exercises the whole qualification sequence, live checks, withdrawal and park. The output-ownership assertions cover distinct claimed staging directories, matching execution and D2 readback, plus refusal before copy/execution when a later path is occupied. Only the selected fixture helper runs as a shell: the remaining fake phase responses are not proof of arbitrary shell semantics. Schema 1 selections remain explicitly legacy-unverified; schema 2 literal contracts are source-only. |
| READ metadata observation | `read_metadata_session.py describe`, `compile`, `transport` and `check` provide a separate single-package read-only inspection. It uses a fresh namespace and the shared exclusive staging transport; package, captures and historical inputs are explicit. | This observes retained metadata; it is not the broader OBSERVE preparation sequence or proof of a READ, and does not authorize retry. |
| Historical Claude staging | [Host-session Composition](plans/handoffs/M8-N6-host-session.md#composition) selects S0 drift guards and S1 fetching/staging. Its [transport](plans/handoffs/M8-N6-host-session.md#fixed-private-input-and-package-transport) supplies its own fixed remote directories. | This is a staging composition, not an OBSERVE or recovery sequence. Generic packaging preserves its selected source; it does not establish phase-owned execution/readback for a successor composition. |
| Historical OBSERVE acquisition | [One command per acquisition](plans/handoffs/M8-N6-maintenance-operator-procedure.md#one-command-per-acquisition) gives login/observe/reload command shapes; [Observation and reload](plans/handoffs/M8-N6-maintenance-operator-procedure.md#observation-and-reload) specifies separate acquisitions and stop rules. | The document explicitly calls these command shapes, not copy-and-paste host commands. There is no OBSERVE preparation entry in the supported executable consumers above. Metadata observation and READ qualification do not establish that coverage. |
| Uncertain-withdrawal recovery | [Evidence and stop rules](plans/handoffs/M8-N6-maintenance-operator-procedure.md#evidence-and-stop-rules) and [the READ withdrawal prerequisite](plans/handoffs/M8-N6-first-read-session.md#affirm-withdrawal-publish-and-activate-one-generation) require a separately reviewed recovery check/inventory when remote process or lock ownership is uncertain. | These references do not supply a canonical public recovery package to the preparation entries above. Precompiled READ withdrawal covers its declared cleanup path; it does not prove an uncertain remote process has terminated or authorize another acquisition. |
| Standalone controller preparation and installation | [Controller runbook](plans/handoffs/M8-N4-host-runtime.md#r15--separate-authorization-required), R17-R19 (source lines 1174, 1208 and 1225), specifies provenance/wheels, stage/judge/install/verify and the service import check. | The historical shell owns its workspace and records and requires its separate installation authorization. READ controller verification does not compose or prove this installation sequence. |
| Historical controller verification and replacement | [LR8. Controller](plans/handoffs/M8-N4-launch-replacement.md#lr8-controller) and [LR9. Controller replacement after login](plans/handoffs/M8-N4-launch-replacement.md#lr9-controller-replacement-after-login) (source lines 261 and 299) distinguish verification from separately authorized replacement using R17-R19. | These are historical producer fences with their own workspace handling. A passing verification, source-contract check or READ rehearsal does not prove replacement output isolation or grant replacement authority. |

The distinct remote staging roots do not imply every output lives there: READ
also writes named artifacts under independently bound workspace, run and service
roots. `readback_spec` and the producer's declared output table are the source
of those locations. The session `check` validates an already captured phase receipt;
`readback` is a separate transport operation and retains exclusive captures.

For these historical sources, `scripts/m8_procedure_package.py check` / `build`
assemble pinned fences into exclusive local package files; `check-contract`
checks selected literal caller/helper bindings. These are source/package checks,
not whole-composition execution proofs. They establish neither disjoint mutable
outputs nor that repeated checking cannot acquire. Selected fence bytes and
Bash options remain unchanged; historical transports are not silently replaced.

The next executable consumer must first identify one independently reviewed
caller and its actual producer fences, supported phase sequence, mutating outputs
and readback locations. The command-shape OBSERVE draft and recovery references
alone do not supply that contract. Extend an existing preparation/transport entry
only where that concrete caller and producer establish compatible ownership;
exercise the complete sequence with a closed fake platform, including permitting
paths, occupied-output refusal, changed-cwd execution/readback agreement and
repeatable read-only checks that perform no acquisition. This census adds no
executor, adapter or approval. Until those consumers have that evidence, the
universal phase-output ownership outcome in #308 remains open.
