"""Boundary lint mutations for the procedure packager (#210, #220, #226).

Each mutant removes one part of the lint: the continuation refusal and its odd-run
rule, an invocation form, the constants-only import exemption, checking hash lines,
the content-keyed allowlist or
shell normalization. Only assertion failures count as kills.
"""

from _mutations import run

MODULE = "scripts.m8_procedure_package:"
TESTS = "tests/test_m8_procedure_package.py::"
INVOKE = TESTS + "test_only_reviewed_lane_boundary_blocks_may_invoke_the_lane"
FORMS = "for match in LANE_INVOCATION.finditer(text):"
GUARDS = "tests/test_m8_private_output_guard.py::"

MUTANTS = (
    ("each guarded step declares its private expectation once", MODULE + "assemble",
     "if len(declaration.findall(text)) != 1:", "if len(declaration.findall(text)) < 1:",
     GUARDS + "test_guard_cannot_duplicate_a_private_declaration"),
    ("private declarations precede the first reviewed guard", MODULE + "assemble",
     "if not declaration.search(before_guard):", "if False:",
     GUARDS + "test_private_declarations_must_precede_the_first_guard[values-DRIFT_STDOUT_HEX]"),
    ("each guarded step declares its expectation", MODULE + "assemble",
     'for key in ("DRIFT_STDOUT_HEX", "DRIFT_TOOL_SHA256"):',
     'for key in ("DRIFT_TOOL_SHA256",):',
     GUARDS + "test_guarded_steps_cannot_borrow_or_duplicate_another_steps_private_fill"
     "[-DRIFT_STDOUT_HEX]"),
    ("each guarded step declares its tool digest", MODULE + "assemble",
     'for key in ("DRIFT_STDOUT_HEX", "DRIFT_TOOL_SHA256"):',
     'for key in ("DRIFT_STDOUT_HEX",):',
     GUARDS + "test_guarded_steps_cannot_borrow_or_duplicate_another_steps_private_fill"
     "[-DRIFT_TOOL_SHA256]"),
    ("a successor never invokes drift outside the approved guard", MODULE + "assemble",
     "if not legacy_drift and any(DRIFT_INVOCATION.search(_normalized(body))",
     "if False and any(DRIFT_INVOCATION.search(_normalized(body))",
     GUARDS + "test_reviewed_guard_does_not_authorize_an_extra_direct_call"),
    ("the legacy exception binds exact document bytes", MODULE + "assemble",
     'hashlib.sha256(document.encode("utf-8")).hexdigest() in LEGACY_DRIFT_PROCEDURES',
     "True", GUARDS + "test_historical_q12_assembly_exception_requires_exact_document_bytes"),
    ("drift guard standing binds exact fence bytes", MODULE + "assemble",
     'body.encode("utf-8")).hexdigest() not in DRIFT_BLOCKS',
     'body.encode("utf-8")).hexdigest() in set()',
     GUARDS + "test_guard_review_standing_is_its_exact_bytes"),
    ("drift invocation checks join shell fragments", MODULE + "assemble",
     "DRIFT_INVOCATION.search(_normalized(body))", "DRIFT_INVOCATION.search(body)",
     GUARDS + "test_shell_fragments_cannot_hide_an_unguarded_drift_call"),
    ("the private expectation includes its final LF", MODULE + "_checked",
     'not text.endswith("\\n")', "False",
     GUARDS + "test_guard_requires_an_exact_expected_lf"),
    ("the private expectation is one printable line", MODULE + "_checked",
     'not text[:-1].isprintable()', "False",
     GUARDS + "test_guard_requires_printable_text_without_extra_lines"),
    ("a part may not end in a line continuation", MODULE + "assemble",
     "if any(_continues(body) for body, _ in pieces):", "if False:",
     TESTS + "test_a_part_ending_in_a_line_continuation_refuses[{literal = \"IGNORED=\\\\\\\\\"}]"),
    ("only an odd run of trailing backslashes continues", MODULE + "_continues",
     "run % 2 == 1", "run > 0",
     TESTS + "test_an_even_run_of_trailing_backslashes_is_literal"),
    ("the module name is a command word under OC's runpy wrapper", MODULE + "_invokes",
     FORMS, "for match in re.finditer(r'\\bLANE\\b|\\bLANE_MODULE\\b|codex_lane\\.py\\b', text):",
     INVOKE + "[change7]"),
    ("the module variable is an invocation", MODULE + "_invokes",
     FORMS, "for match in re.finditer(r'\\bLANE\\b|\\bcodex_lane\\b', text):",
     INVOKE + "[change5]"),
    ("a package-level import of the lane module is a mention", MODULE + "_invokes",
     "FROM_BEFORE.search(before)", "True",
     TESTS + "test_importing_anything_that_can_dispatch_the_lane_refuses"
     "[from other.codex_lane import EVIDENCE_DOMAIN]"),
    ("a constants import with any whitespace is not an invocation", MODULE + "_invokes",
     "FROM_BEFORE.search(before)", "before.endswith('from ')",
     TESTS + "test_constant_imports_are_not_invocations"
     "[from\\tconstructicon.substrate.executors.codex_lane import EVIDENCE_DOMAIN]"),
    ("only uppercase constants may be imported from the lane", MODULE + "_invokes",
     "CONSTANTS_AFTER.match(after)", "True",
     TESTS + "test_importing_anything_that_can_dispatch_the_lane_refuses"
     "[from constructicon.substrate.executors.codex_lane import main; main()]"),
    ("hash lines are checked like any text", MODULE + "assemble",
     "_invokes(_normalized(body))",
     "_invokes(re.sub(r'(?m)^[ \\t]*#.*$', '', _normalized(body)))",
     TESTS + "test_hash_lines_are_checked_like_any_text[quoted-hash]"),
    ("review standing is the fence's exact bytes", MODULE + "_part",
     'hashlib.sha256(body.encode("utf-8")).hexdigest() in LANE_BLOCKS', "True",
     TESTS + "test_review_standing_follows_exact_bytes_not_file_or_heading_names"),
    ("an unfilled documented declaration is a placeholder", MODULE + "assemble",
     "PLACEHOLDER.search(joined) or DECLARATION.search(text)", "PLACEHOLDER.search(joined)",
     TESTS + "test_unfilled_or_unsafe_declarations_refuse[{source = \"oc\", "
     "heading = \"LR8. Controller\", fences = [0]}-unreviewed placeholder]"),
    ("only a 40-hex commit fills a declaration", MODULE + "_part",
     "isinstance(value, str) and COMMIT.fullmatch(value)", "isinstance(value, str)",
     TESTS + "test_unfilled_or_unsafe_declarations_refuse[{source = \"oc\", "
     "heading = \"LR8. Controller\", fences = [0], set = {O = \"$(id)\", C = \"x\"}}"
     "-40-hex commits]"),
    ("each name fills exactly one declaration", MODULE + "_part",
     "if len(where) != 1:", "if not where:",
     TESTS + "test_unfilled_or_unsafe_declarations_refuse[{source = \"oc\", "
     "heading = \"LR8. Controller\", fences = [0, 0], set = {O = "
     "\"e7d40b139c2a0205f37c7050295a3eca55af9d2c\", C = "
     "\"5793ef98ef5597c9ee9811a0d1f031554eb7f514\"}}-declares O 2 times]"),
    ("a session value has its name's exact shape", MODULE + "_checked",
     "and SESSION_VALUES[key].fullmatch(value)", "and True",
     TESTS + "test_session_values_are_only_the_three_names_in_their_shapes"
     "[RUN_ID = \"run-$(id)\"]"),
    ("values given directly are checked", MODULE + "assemble",
     "values = _checked(values)", "pass",
     TESTS + "test_values_given_directly_are_checked_like_the_file[given0]"),
    ("the serialized expectation fits the transport", MODULE + "assemble",
     'if len(step.expected().encode("utf-8")) > MAX_STDOUT:', "if False:",
     TESTS + "test_an_expectation_the_transport_cannot_read_refuses"),
    ("no unreviewed part may rebind a bash builtin", MODULE + "assemble",
     "if any(_rebinds_a_builtin(_normalized(body))", "if False and any(_rebinds_a_builtin(body)",
     TESTS + "test_no_unreviewed_part_may_rebind_a_bash_builtin[readonly() { :; }]"),
    ("a function named for a builtin rebinds it", MODULE + "_rebinds_a_builtin",
     "bool(names & (BUILTINS | HOOKS))", "False",
     TESTS + "test_no_unreviewed_part_may_rebind_a_bash_builtin[readonly() { :; }]"),
    ("a filled session value is readonly in bash", MODULE + "assemble",
     'filled = f"readonly {key}={value}"', 'filled = f"{key}={value}"',
     TESTS + "test_bash_refuses_any_later_write_to_a_filled_session_value[RUN_ID+=x]"),
    ("every bare mention of a session name is its filled line", MODULE + "assemble",
     "if line != filled and not reads:", "if False:",
     TESTS + "test_measured_session_values_fill_exact_unreviewed_lines"),
    ("session-name mentions are classified after bash joins words", MODULE + "assemble",
     'words = re.sub(r"[\\"\'\\\\]", "", unquoted)', "words = unquoted",
     TESTS + "test_measured_session_values_fill_exact_unreviewed_lines"),
    ("a $ before a quote is quoting syntax, not a read", MODULE + "assemble",
     'unquoted = re.sub(r"\\$(?=[\\"\'])", "", text.replace("\\\\\\n", ""))',
     'unquoted = text.replace("\\\\\\n", "")',
     TESTS + "test_measured_session_values_fill_exact_unreviewed_lines"),
    ("only a $ read of a session name is not a write", MODULE + "assemble",
     'reads = re.search(r"\\$\\{?[#!]?$"', 'reads = re.search(r"\\$?\\{?[#!]?$"',
     TESTS + "test_measured_session_values_fill_exact_unreviewed_lines"),
    ("a session value that fills no line refuses", MODULE + "assemble",
     "if set(values or {}) - used:", "if False:",
     TESTS + "test_measured_session_values_fill_exact_unreviewed_lines"),
    ("stdout alternatives are distinct, so at most one matches", MODULE + "_expectation",
     "if len(set(alternatives)) != len(alternatives):", "if False:",
     TESTS + "test_malformed_expectations_refuse[change0-alternatives must be distinct]"),
    ("a deferred step may wait only for session values", MODULE + "assemble",
     "if PLACEHOLDER.search(_normalized(pending)) or DECLARATION.search(text):",
     "if DECLARATION.search(text):",
     TESTS + "test_a_deferred_step_waits_only_for_session_values"),
    ("a record bound admits its shortest record", MODULE + "_expectation",
     'if spec["max_bytes"] < shortest:', "if False:",
     TESTS + "test_malformed_expectations_refuse"
     "[change2-below its shortest record \\\\(26 bytes\\\\)]"),
    ("shell normalization joins continued lines", MODULE + "_normalized",
     'SHELL_QUOTING.sub("", text.replace("\\\\\\n", ""))', "text",
     INVOKE + "[change2]"),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
