"""N2's subscription-mode gate, framing, request builders, decoder and adapter.

Run with ``uv run python scripts/check_m8_n2_mutations.py``. The shared runner
mutates only child-process code objects and requires an assertion failure: a
mutant that merely errors is NOT PROVEN, never a kill.

Every fault of the gate has a mutant here, and so does the pre-acceptance
discard — the behaviour ADR 0021 calls "refuses ... result acceptance", which
is the single most important thing in this slice.
"""

import sys

from _mutations import run

GATE = "constructicon.substrate.executors.codex_protocol:account_faults"
CHANGE = "constructicon.substrate.executors.codex_protocol:account_change_faults"
STREAM = "constructicon.substrate.executors.codex_protocol:RecordStream.feed"
SEALED = "constructicon.substrate.executors.codex_protocol:_sealed"
INITIALIZE = "constructicon.substrate.executors.codex_protocol:initialize_request"
ACCOUNT_READ = "constructicon.substrate.executors.codex_protocol:account_read_request"
TURN = "constructicon.substrate.executors.codex_protocol:turn_request"
THREAD_START = "constructicon.substrate.executors.codex_protocol:thread_start_request"
OBSERVE = "constructicon.substrate.executors.codex_protocol:observe_turn"
DECODE = "constructicon.substrate.executors.codex_protocol:decode_turn"
REFUSAL = "constructicon.substrate.executors.codex_protocol:unavailable_outcome"
CONVERSE = "constructicon.substrate.executors.codex:CodexConversation._converse"
PREAMBLE = "constructicon.substrate.executors.codex:CodexConversation._drain_preamble"
CORRELATE = "constructicon.substrate.executors.codex:CodexConversation._request"
EXECUTE = "constructicon.substrate.executors.codex:CodexOperatorHandle.execute"
PROVIDER = "constructicon.substrate.executors.codex:CodexOperatorProvider.unavailable_reasons"
CONSTRUCTOR = "constructicon.substrate.executors.codex:CodexOperatorProvider.__init__"

PROTOCOL = "tests/substrate/test_codex_protocol.py::"
ADAPTER = "tests/substrate/test_codex_adapter.py::"

ERROR_REPLY = PROTOCOL + "test_an_error_or_missing_result_refuses"
NULL_ACCOUNT = PROTOCOL + "test_a_null_account_refuses_without_naming_a_cause"
WRONG_TYPE = PROTOCOL + "test_an_api_or_cloud_credential_refuses"
OVERRIDE = PROTOCOL + "test_a_provider_override_refuses_independently_of_the_account"
NO_PLAN = PROTOCOL + "test_a_missing_plan_fact_refuses"
WRONG_PLAN = PROTOCOL + "test_a_different_plan_refuses"
CHANGED = PROTOCOL + "test_a_reading_that_differs_from_the_pre_turn_one_refuses"
DISCARD = ADAPTER + "test_a_pre_acceptance_gate_fault_discards_a_successful_turn"

MUTANTS = (
    (
        "fault 1: an error or a missing result refuses",
        GATE,
        "return (NO_RESULT_FAULT,)",
        "return ()",
        ERROR_REPLY,
    ),
    (
        "fault 2: no usable account refuses",
        GATE,
        "if known is None:",
        "if False:",
        NULL_ACCOUNT,
    ),
    (
        "fault 3: an api or cloud account type refuses",
        GATE,
        "if known is not None and known.get(ACCOUNT_TYPE_KEY) != expected.account_type:",
        "if False:",
        WRONG_TYPE,
    ),
    (
        "fault 4: a provider override refuses",
        GATE,
        "if result.get(PROVIDER_FLAG_KEY) is not True:",
        "if False:",
        OVERRIDE,
    ),
    (
        "fault 4: only an exact true clears the provider check",
        GATE,
        "if result.get(PROVIDER_FLAG_KEY) is not True:",
        "if result.get(PROVIDER_FLAG_KEY) is False:",
        OVERRIDE,
    ),
    (
        "fault 5: a missing plan fact refuses",
        GATE,
        "if known is not None and plan is None:",
        "if False:",
        NO_PLAN,
    ),
    (
        "fault 6: a plan other than the provisioned one refuses",
        GATE,
        "if plan is not None and plan != expected.plan_type:",
        "if False:",
        WRONG_PLAN,
    ),
    (
        "fault 7: the two readings must agree",
        CHANGE,
        "if old != new",
        "if False",
        CHANGED,
    ),
    (
        "the pre-acceptance reading is actually taken",
        CONVERSE,
        "after = await self._account(io)",
        "after = before",
        DISCARD,
    ),
    (
        "a faulting pre-acceptance reading discards the turn",
        CONVERSE,
        "self.faults += account_faults(after, self._expected)",
        "self.faults += ()",
        DISCARD,
    ),
    (
        "a changed pre-acceptance reading discards the turn",
        CONVERSE,
        "self.faults += account_change_faults(before, after)",
        "self.faults += ()",
        ADAPTER + "test_a_pre_acceptance_reading_that_merely_changed_discards_the_turn",
    ),
    (
        "a refused pre-turn reading sends no turn",
        CONVERSE,
        "if faults:",
        "if False:",
        ADAPTER + "test_a_pre_turn_gate_fault_refuses_without_sending_a_turn",
    ),
    (
        "a reply must correlate with the request that earned it",
        CORRELATE,
        'if type(record["id"]) is not int or record["id"] != identifier:',
        "if False:",
        ADAPTER + "test_a_reply_that_does_not_correlate_with_its_request_is_refused",
    ),
    (
        "an executor call must match its sealed grants",
        EXECUTE,
        "if canonical_json(grants) != canonical_json(self.context.binding.effective_grants):",
        "if False:",
        ADAPTER + "test_grants_differing_from_the_sealed_set_are_refused",
    ),
    (
        "initialize never requests the experimental capability",
        INITIALIZE,
        '"capabilities": {},',
        '"capabilities": {"experimentalApi": True},',
        PROTOCOL + "test_initialize_never_requests_the_experimental_capability",
    ),
    (
        "the mode reading never causes a refresh",
        ACCOUNT_READ,
        '"params": {"refreshToken": False},',
        '"params": {"refreshToken": True},',
        PROTOCOL + "test_account_read_observes_and_never_causes_a_refresh",
    ),
    (
        "a provider override field is refused structurally",
        SEALED,
        "if overrides:",
        "if False:",
        PROTOCOL + "test_a_provider_override_field_is_refused_structurally",
    ),
    (
        "a thread never opts into an approval policy",
        THREAD_START,
        '"sandbox": "read-only",',
        '"sandbox": "read-only", "approvalPolicy": "never",',
        PROTOCOL + "test_a_thread_never_opts_into_an_approval_policy",
    ),
    (
        "a composed byte scope's preamble is drained",
        PREAMBLE,
        "for _ in range(self._preamble):",
        "for _ in range(0):",
        ADAPTER + "test_a_composed_byte_scope_preamble_is_drained_and_never_transcribed",
    ),
    (
        "a scope ending inside its preamble refuses before initialize",
        CONVERSE,
        "if not await self._drain_preamble(io):",
        "if False:",
        ADAPTER + "test_a_byte_scope_that_ends_inside_its_preamble_refuses",
    ),
    (
        "a turn requires the explicit sealed model",
        TURN,
        'if selection.kind != "explicit" or not (selection.model or "").strip():',
        "if False:",
        PROTOCOL + "test_a_turn_requires_the_explicit_sealed_model_even_though_it_never_sends_it",
    ),
    (
        "an oversized record is damage",
        STREAM,
        "if len(self.pending) >= RECORD_BYTES:",
        "if False:",
        PROTOCOL + "test_an_oversized_record_is_damage_rather_than_an_exception",
    ),
    (
        "a stream ending inside a record is refused",
        STREAM,
        "if self.pending:",
        "if False:",
        PROTOCOL + "test_a_stream_ending_inside_a_record_is_refused_not_accepted",
    ),
    (
        "a reply never reaches the transcript",
        OBSERVE,
        'if not isinstance(record, dict) or "id" in record or "method" not in record:',
        'if not isinstance(record, dict) or "method" not in record:',
        PROTOCOL + "test_a_reply_or_a_native_request_never_reaches_the_transcript",
    ),
    (
        "two terminal records are contradictory, not last-wins",
        OBSERVE,
        "if terminal:",
        "if False:",
        PROTOCOL + "test_two_terminal_records_are_contradictory_rather_than_last_wins",
    ),
    (
        "a timeout salvages rather than succeeding",
        DECODE,
        "if process.timed_out:",
        "if False:",
        PROTOCOL + "test_a_timeout_salvages_the_output_it_did_see",
    ),
    (
        "an incomplete private exit report is infrastructure",
        DECODE,
        "process.payload_returncode is None or process.payload_returncode != process.returncode",
        "False",
        PROTOCOL + "test_an_incomplete_private_exit_report_is_never_a_success_or_an_exit",
    ),
    (
        "a nonzero exit without a bound breach is an exit failure",
        DECODE,
        "if process.returncode and not (process.bound_exceeded or incomplete):",
        "if False:",
        PROTOCOL + "test_a_nonzero_exit_without_a_bound_breach_is_an_exit_failure",
    ),
    (
        "a turn with no terminal record demotes",
        DECODE,
        'or (None if observation.terminal else "no terminal turn record")',
        "or None",
        PROTOCOL + "test_a_turn_with_no_terminal_record_demotes_to_partial",
    ),
    (
        "a refused gate names its faults",
        REFUSAL,
        'detail="; ".join(faults),',
        'detail="",',
        PROTOCOL + "test_a_refused_gate_discards_the_result_and_still_reports_that_a_turn_ran",
    ),
    (
        "unavailability is published, not inferred",
        PROVIDER,
        "return self._unavailable",
        "return ()",
        ADAPTER + "test_the_provider_publishes_its_prerequisites_and_refuses_to_acquire",
    ),
    (
        "a published identity that drifts from actual content is refused",
        CONSTRUCTOR,
        "if getattr(identity, field) != expected:",
        "if False:",
        ADAPTER + "test_an_identity_that_drifts_from_the_actual_content_is_refused",
    ),
    (
        "this slice publishes no mediated callback catalog",
        CONSTRUCTOR,
        "if catalog:",
        "if False:",
        ADAPTER + "test_this_slice_publishes_no_mediated_callback_catalog",
    ),
)

if __name__ == "__main__":
    status = run(MUTANTS)
    if status == 0 and len(sys.argv) == 1:
        print(f"{len(MUTANTS)}/{len(MUTANTS)} mutants KILLED by assertion.")
    raise SystemExit(status)
