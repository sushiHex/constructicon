"""The change-review advice route (ADR 0025): one mutant per guard; each must fail an assertion.

Portable: every target runs over the adapter suite's scripted native client.
The first two are the premortem's: an assembly that empties the published
reasons, and a route that would accept such a provider.
"""

from _mutations import run

ROUTE = "constructicon.api.change_review_advice:"
TEST = "tests/api/test_change_review_advice.py::"

MUTANTS = (
    ("the route's assembly passes no reason tuple",
     ROUTE + "host_provider", "return provider",
     "provider._unavailable = ()\n    return provider",
     TEST + "test_the_route_assembles_only_through_host_assembly_with_reasons_intact"),
    ("a provider without every published reason is refused",
     ROUTE + "require_provider",
     "or provider.unavailable_reasons != UNQUALIFIED_PREREQUISITES", "",
     TEST + "test_an_assembly_that_passes_a_reason_tuple_is_refused"),
    ("the entry compares the permit's key before runs_start",
     ROUTE + "require_permit",
     "if authorization.idempotency_key != bound.idempotency_key:", "if False:",
     TEST + "test_another_packet_under_the_permit_refuses_before_any_turn"),
    ("the node recomputes its run before execute",
     ROUTE + "advise_node", "if advice_run_id(instruction) != ctx.run_id:", "if False:",
     TEST + "test_a_packet_that_bypasses_the_entry_spends_no_turn_at_the_node"),
    ("the node accepts only a text success",
     ROUTE + "advise_node",
     "if not isinstance(outcome, ExecutorSuccess) or type(answer) is not str or not answer:",
     "if False:",
     TEST + "test_the_node_accepts_only_a_bounded_text_success[salvaged-failure]"),
    ("the reply is bounded",
     ROUTE + "advise_node", "if size > MODEL_ADVICE_MAX_BYTES:", "if False:",
     TEST + "test_a_reply_that_is_not_bounded_text_refuses_and_never_checkpoints[oversized]"),
    ("the instruction is bounded, never truncated",
     ROUTE + "instruction_for",
     'or len(instruction.encode("utf-8")) > INSTRUCTION_MAX_BYTES', "or False",
     TEST + "test_an_oversized_instruction_refuses_by_name_and_is_never_truncated"),
    ("structural facts that do not align with the summary refuse (ADR 0027)",
     ROUTE + "ChangeSummaryV2._aligned", "if not consistent:", "if False:",
     TEST + "test_an_inconsistent_structural_fact_refuses_at_the_node[multiple-with-parts]"),
    ("one permit, one journal",
     ROUTE + "_require_dedicated", "if (record.run_id != bound.run_id", "if (False",
     TEST + "test_a_journal_holding_another_run_is_refused_before_recovery"),
    ("a completed run replays before any permit read or provider",
     ROUTE + "run", "if journal.is_file() and", "if False and",
     TEST + "test_a_completed_run_replays_and_never_dispatches_again"),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
