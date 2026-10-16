"""Lane-boundary lint mutations for the procedure packager (#210, #220).

Each mutant removes one part of the lint: the continuation refusal, an invocation
form, the content-keyed allowlist or shell normalization. Only assertion failures
count as kills.
"""

from _mutations import run

MODULE = "scripts.m8_procedure_package:"
TESTS = "tests/test_m8_procedure_package.py::"
INVOKE = TESTS + "test_only_reviewed_lane_boundary_blocks_may_invoke_the_lane"
SEARCH = "if any(LANE_INVOCATION.search("

MUTANTS = (
    ("a part may not end in a line continuation", MODULE + "assemble",
     'if any(body.endswith("\\\\\\n") for body, _ in pieces):', "if False:",
     TESTS + "test_a_part_ending_in_a_line_continuation_refuses[{literal = \"IGNORED=\\\\\\\\\"}]"),
    ("the module name is a command word under OC's runpy wrapper", MODULE + "assemble",
     SEARCH, "if any(re.compile(r'\\bLANE\\b|\\bLANE_MODULE\\b|codex_lane\\.py\\b').search(",
     INVOKE + "[change7]"),
    ("the module variable is an invocation", MODULE + "assemble",
     SEARCH, "if any(re.compile(r'\\bLANE\\b|codex_lane\\.py\\b"
     "|constructicon\\.substrate\\.executors\\.codex_lane\\b').search(",
     INVOKE + "[change5]"),
    ("review standing is the fence's exact bytes", MODULE + "_part",
     'hashlib.sha256(body.encode("utf-8")).hexdigest() in LANE_BLOCKS', "True",
     TESTS + "test_review_standing_follows_exact_bytes_not_file_or_heading_names"),
    ("shell normalization joins continued lines", MODULE + "_normalized",
     'SHELL_QUOTING.sub("", text.replace("\\\\\\n", ""))', "text",
     INVOKE + "[change2]"),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
