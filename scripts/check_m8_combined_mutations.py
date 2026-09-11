"""Targeted combined-proof assertion mutations, without writing source files."""

from _mutations import run

MODULE = "tests.native_combined:"
TEST = "tests/test_native_combined.py::"
NEGATIVE = TEST + "test_conversation_refuses_uncontrolled_context_and_outputs"

MUTANTS = (
    ("full conversation check omitted", MODULE + "CombinedScenario.__call__",
     'raise ValueError("unexpected native context or conversation")', "pass",
     NEGATIVE + "[gpt-5.5-earlier-user]"),
    ("root history carriers admitted", MODULE + "CombinedScenario.__call__",
     "set(request) != expected_keys", "False",
     NEGATIVE + "[gpt-5.5-previous-response]"),
    ("base instructions unchecked", MODULE + "CombinedScenario.__call__",
     'request.get("instructions") != BASE_INSTRUCTIONS', "False",
     NEGATIVE + "[gpt-5.5-changed-instructions]"),
    ("tool declarations unchecked", MODULE + "CombinedScenario.__call__",
     "canonical(tools_for(images=self.images, restricted=self.restricted, mcp=self.mcp))",
     'canonical(request.get("tools"))',
     NEGATIVE + "[gpt-5.5-changed-tool-schema]"),
    ("request ordinal unbounded", MODULE + "CombinedScenario.__call__",
     "ordinal not in (1, 2)", "False",
     NEGATIVE + "[gpt-5.5-third-request]"),
    ("item identity unchecked", MODULE + "without_ids",
     'or not isinstance(item.get("id"), str) or not item["id"]', "",
     NEGATIVE + "[gpt-5.5-missing-id]"),
    ("endpoint ignores full assertion", "tests.native_provider:Peer.respond",
     "self.request_check(request, len(self.requests))", "pass",
     TEST + "test_endpoint_applies_full_check_before_sending_the_fixed_script[tcp-gpt-5.5]"),
    ("failed callback discards evidence", "tests.substrate.test_native_combined:worker_result",
     'observations.append(result.model_dump(mode="json"))', "pass",
     TEST + "test_failed_worker_keeps_complete_evidence_before_refusal"),
    ("patch elapsed window unbounded", MODULE + "CombinedScenario.__call__",
     "not 0 <= float(elapsed[1]) <= 20", "False",
     TEST + "test_positive_patch_control_excludes_only_bounded_elapsed_text[gpt-5.5-0]"),
    ("refusal conceals patch side effect",
     "tests.substrate.test_native_combined:assert_patch_effect",
     'assert ("inert" in names) is positive', "pass",
     TEST + "test_refusal_message_cannot_hide_a_patch_side_effect"),
    *((f"peer {field} detached from native RPC", MODULE + "assert_native_identity",
       f'assert request["client_metadata"]["{field}_id"] == protocol["{field}"]', "pass",
       TEST + f"test_peer_metadata_must_correlate_with_the_same_native_rpc[{field}]")
      for field in ("thread", "turn")),
    ("failed untrusted hook attempt accepted",
     "tests.substrate.test_combined_startup_origins:assert_hook_attempt",
     'assert [item["method"] for item in events] == (', 'assert True or (',
     TEST + "test_failed_untrusted_hook_attempt_is_not_a_disable_proof"),
    ("untrusted observation never inspected",
     "tests.substrate.test_combined_startup_origins:"
     "test_user_hook_discovery_trust_and_disable_have_execution_controls",
     "assert_hook_attempt(record, False)", "pass",
     TEST + "test_native_origin_test_inspects_the_untrusted_attempt[json]"),
    ("plugin context becomes ambient", MODULE + "CombinedScenario.prefix",
     "if self.plugins else [PERMISSIONS]", "if True else [PERMISSIONS]",
     TEST + "test_plugin_positive_context_never_becomes_ambient[gpt-5.5]"),
    ("agent context survives catalog restriction", MODULE + "CombinedScenario.prefix",
     "self.model == MODELS[1] and not self.restricted", "self.model == MODELS[1]",
     TEST + "test_original_sol_agent_context_is_absent_from_the_restricted_recipe"),
    *((f"hook execution proof loses {name}",
       "tests.substrate.test_combined_startup_origins:assert_hook_attempt", old, "pass",
       TEST + f"test_successful_hook_proof_requires_execution_and_correlated_events[{name}]")
      for name, old in (
          ("status", 'assert ends["run"]["status"] == "completed"'),
          ("entries", 'assert ends["run"]["entries"] == []'),
          ("thread", 'assert item["threadId"] == record["protocol"]["thread"]'),
          ("turn", 'assert item["turnId"] == record["protocol"]["turn"]'),
          ("pair", 'assert starts["run"]["id"] == ends["run"]["id"] and ends["run"]["id"]'),
          ("source", 'assert item["run"]["sourcePath"] == hook["sourcePath"]'),
          ("missing-marker",
           'assert marker(record) == ("hook" if enabled and completed else "absent")'),
      )),
    ("packaged shell becomes ambient context", MODULE + "environment",
     "'zsh' if packaged_shell else 'sh'", "'zsh'",
     TEST + "test_shell_selection_is_an_exact_context_variant[gpt-5.5]"),
    ("packaged shell selection is ignored", MODULE + "controlled_configuration",
     "str(packaged_shell).lower()", "'false'",
     TEST + "test_shell_selection_is_an_exact_context_variant[gpt-5.5]"),
    *((f"native hook matrix skips {phase}",
       "tests.substrate.test_combined_startup_origins:"
       "test_user_hook_discovery_trust_and_disable_have_execution_controls",
       old, "pass", TEST + f"test_native_hook_matrix_cannot_skip_a_phase[{phase}]")
      for phase, old in (
          ("untrusted", "assert_hook_attempt(record, False)"),
          ("trusted", "assert_hook_attempt(checked, enabled, completed=packaged_shell)"),
          ("disabled", "assert_hook_attempt(checked, enabled, completed=packaged_shell)"),
      )),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
