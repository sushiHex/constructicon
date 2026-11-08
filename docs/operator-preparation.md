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
| Historical OBSERVE, recovery and standalone controller preparation | `scripts/m8_procedure_package.py check` / `build` assemble selected pinned fenced source into exclusive local package files; `check-contract` checks selected literal caller/helper bindings. The historical procedure supplies its own transport and output locations. | These are source/package checks, not a supported universal phase executor or whole-composition proof. No claim is made that their mutable outputs are isolated, or that a read-only checker cannot acquire. Do not infer coverage from READ's controller verification or withdrawal phase. |

The distinct remote staging roots do not imply every output lives there: READ
also writes named artifacts under independently bound workspace, run and service
roots. `readback_spec` and the producer's declared output table are the source
of those locations. The session `check` validates an already captured phase receipt;
`readback` is a separate transport operation and retains exclusive captures.

For the remaining #308 work, inventory each actual OBSERVE, recovery and
standalone controller preparation caller and its reviewed producer fences;
identify which sequences are supported and their mutating outputs/readbacks.
Then extend their existing preparation/transport entry only where the producer
and caller establish compatible ownership, and exercise each complete supported
sequence with a closed fake platform, including occupied output refusal and
repeatable read-only checks. Preserve reviewed fence options and frozen bytes;
do not infer correctness from selected source literals or introduce a parallel
workflow. Until that evidence exists, #308 remains open.
