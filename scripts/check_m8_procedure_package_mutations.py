"""Lane-boundary lint mutations for the procedure packager (#210, #220).

Each mutant removes one part of the lint: the continuation refusal and its odd-run
rule, an invocation form, the constants-only import exemption, the content-keyed allowlist or
shell normalization. Only assertion failures count as kills.
"""

from _mutations import run

MODULE = "scripts.m8_procedure_package:"
TESTS = "tests/test_m8_procedure_package.py::"
INVOKE = TESTS + "test_only_reviewed_lane_boundary_blocks_may_invoke_the_lane"
FORMS = "for match in LANE_INVOCATION.finditer(text):"

MUTANTS = (
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
     FORMS, "for match in re.finditer(r'\\bLANE\\b|codex_lane\\.py\\b"
     "|\\bconstructicon\\.substrate\\.executors\\.codex_lane\\b', text):",
     INVOKE + "[change5]"),
    ("a constants import with any whitespace is not an invocation", MODULE + "_invokes",
     "FROM_BEFORE.search(before)", "before.endswith('from ')",
     TESTS + "test_constant_imports_and_comments_are_not_invocations"
     "[from\\tconstructicon.substrate.executors.codex_lane import EVIDENCE_DOMAIN]"),
    ("only uppercase constants may be imported from the lane", MODULE + "_invokes",
     "CONSTANTS_AFTER.match(after)", "True",
     TESTS + "test_importing_anything_that_can_dispatch_the_lane_refuses"
     "[from constructicon.substrate.executors.codex_lane import main; main()]"),
    ("review standing is the fence's exact bytes", MODULE + "_part",
     'hashlib.sha256(body.encode("utf-8")).hexdigest() in LANE_BLOCKS', "True",
     TESTS + "test_review_standing_follows_exact_bytes_not_file_or_heading_names"),
    ("shell normalization joins continued lines", MODULE + "_normalized",
     'SHELL_QUOTING.sub("", text.replace("\\\\\\n", ""))', "text",
     INVOKE + "[change2]"),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
