# Cloud fix candidate: CheckResult status/ok consistency (issue #370)

Base: `b22581ac2922b27f35b0a83b528a25a2cb279073`. Branch: `fix/cloud-check-result`.
Scope: `CheckResult` only; not the cross-run attestation collision.

## Reproduction (confirmed at base)

`CheckResult.model_validate({'name':'n','ok':'false','detail':'','elapsed_s':0})`
returned `status='passed', ok=False`. `_sync_status_and_ok` (before-validator in
`src/constructicon/core/effect.py`) derived `status` from raw truthiness of `ok`
(`"false"` is truthy) while the `ok: bool` field later coerced it to `False`.
`Attestation.ok` reads `check.ok`, so no false authorization resulted, but the
class contract ("status and ok stay in lockstep") was violated. The validator
also mutated the caller's dict in place.

## Final design

In the before-validator, `ok` is first coerced with the same Pydantic lax `bool`
rule the field uses (`TypeAdapter(bool)`), and the coerced value drives
derivation and the contradiction check. Policy: **accept coherently** — legacy
bool and bool-like strings/ints (`"false"`, `0`, `"true"`, `1`, …) are kept
(they were already accepted by the field); uncoercible `ok` is left to field
validation, which refuses it. The input mapping is copied before any write.
Unchanged: omitted `status` or `ok` derivation, `ok != (status == "passed")`
contradiction refusal, the status Literal, field set, and no attestation
identity/schema/authority change.

## Test evidence

`tests/core/test_check_result_status_ok.py` (new, fake-free pure model tests):
accepting — legacy truthy/falsy `ok` without status (bool, str, int); status-only
for every variant; agreeing both-field pairs for every status x
`{True,False,"true","false"}`; dump/validate round trip. Refusing — contradictory
both-field pairs (including string `ok`), uncoercible `ok`, unknown status,
omitting both. Caller input not mutated.

Observed passing: that file plus `tests/runtime/test_registry.py`,
`tests/substrate/journal/test_effect_preparation.py`,
`test_request_attestation_provenance.py`, `test_run_projection.py` (180 passed),
and `tests/e2e/test_merge_effect.py` (see run result below in the task report).
`uv run ruff check` on the two changed files: clean. `uv run mypy
src/constructicon/core/effect.py`: no issues.

## Checks not run

Full suite / `uv run verify`, CI (none observed), platform and physical lanes.
`scripts/check_m8_gate_mutations.py` has no target referencing `core/effect.py`
or `_sync_status_and_ok`; nothing there was run.

## Remaining limitations

Lax coercion of `ok` (`"yes"`, `1`) remains accepted as before; making it strict
would be a public-contract change left to the owner. The cross-run attestation
collision is untouched.
