# Operator helper/caller source contracts

Living implementation record; Refs [#308](https://github.com/sushiHex/constructicon/issues/308).
The broader phase-output/preparation issue remains open. This bounded slice
persists offline caller/helper checks in the existing procedure packager and
M9 qualification selection, without adding an execution language or scheduler.

## Boundary and use

The [stopped successor](https://github.com/sushiHex/constructicon/issues/45#issuecomment-6702703970)
changed a historical caller's parent while retaining a helper that pinned the
old parent, runtime and raw evidence hashes. Individual script/archive tests
did not execute that composition. The
[corrected private package](https://github.com/sushiHex/constructicon/issues/45#issuecomment-6702820405)
and its historical helper remain frozen and are not inputs executed by this
implementation.

The existing `scripts/m8_procedure_package.py check-contract SCRIPT CONTRACT.json`
entry checks one closed JSON object with `helper`, `caller` and `bindings`.
`helper` and `caller` are complete literal blocks, final LF included, each
present exactly once as whole lines. `bindings` maps reviewed shell declaration
names to their exact right-hand-side text; one canonical top-level declaration
per name must match. The helper block includes its static runtime/evidence
arguments. Select these expectations independently from the helper's accepted
contract, then check the proposed composition. Copying expectations from the
candidate itself would prove only self-consistency.

The repeatable JSON result binds script, contract, helper and caller digests
and declaration names. It explicitly says `selected-literal-source-only` and
`not-executed`. It does not parse shell, discover every call, prove input
semantics, detect indirect rebinding or establish host absence/custody. Source
review and an actual permitting/refusing execution fixture remain necessary.

M9 selection schema 2 requires a `helper_contracts` object with exactly the
existing phase names plus cleanup. Each phase supplies a list of these literal
contracts; an empty list explicitly declares no selected helper for that
phase. At least one contract must be present overall. The constructor checks
every selected contract before creating work paths or issuing any external
call. Per-phase source proofs are retained in the existing `SOURCE-PINS.json`
and package manifest. Schema 1 remains readable with explicit
`legacy-unverified` coverage. Neither coverage label claims inventory
completeness or semantic execution proof. Independent review still selects the
selection digest; this is not an approval generator.

The canonical READ compiler, transport and readback locations remain the
authority for their existing outputs. The new check does not relocate outputs,
turn repeatable read checks into acquisitions or change frozen shell fences.
The fake contract consumer and M9 selection exercise the same check (I6).

## Executed evidence and limits

Windows/Python 3.13 focused checks executed the literal Bash/Python fixture
caller and helper twice successfully, and executed the transplanted-parent
refusal. The fake filesystem is a closed mapping of historical role paths to
synthetic evidence; missing keys never fall back to the native filesystem.
Runtime/static hash/caller/declaration changes refuse source validation even
when the candidate script digest is updated.

The complete M9 fake transport runs qualification, live recheck, withdrawal and
park through the existing boundary, including real fixture caller/helper
execution. Every external call has exactly one of twelve explicit fake
classifications; unknown and ambiguous calls fail without native fallback.
Transplant and incomplete inventory selections refuse before any external call
or work-directory creation. CLI source checks are repeatable. Three added
mutants were assertion-killed: omit helper bytes, relax declaration equality,
and omit M9 contract checking.

Focused packager/contract/M9 tests passed 149 cases. Related READ session/window,
M9 and mutation-inventory regressions passed 130 cases. `ruff check src tests`,
changed-script byte compilation and staged-diff checks passed. These are focused
local results, not an executed full `verify` gate.

The delivery PR owns final-head CI and independent review evidence. These local
proofs establish no current private helper acceptance, vendor/model/account
behavior, physical Linux isolation or host qualification. No VM operation,
credential, vendor binary, paid call, frozen-plan edit or stopped-window resume
was performed. Broader OBSERVE/recovery/preparation consumers remain #308's
scope, not completion claims of this slice.
