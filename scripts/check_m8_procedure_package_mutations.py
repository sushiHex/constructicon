"""Lane-boundary lint mutations for the procedure packager (#210, #220).

Each mutant removes one part of the lint: the joined-text check, an invocation
form, the content-keyed allowlist or shell normalization. Only assertion failures
count as kills.
"""

from _mutations import run

MODULE = "scripts.m8_procedure_package:"
TESTS = "tests/test_m8_procedure_package.py::"
INVOKE = TESTS + "test_only_reviewed_lane_boundary_blocks_may_invoke_the_lane"

MUTANTS = (
    ("a name spliced across two parts is one bash word", MODULE + "assemble",
     "if LANE_INVOCATION.search(_normalized(unreviewed)):",
     "if any(LANE_INVOCATION.search(_normalized(body)) for body, ok in pieces if not ok):",
     INVOKE + "[change7]"),
    ("a direct module invocation is an invocation", MODULE + "assemble",
     "if LANE_INVOCATION.search(_normalized(unreviewed)):",
     "if re.search(r'\\bLANE\\b', _normalized(unreviewed)):",
     INVOKE + "[change4]"),
    ("review standing is the fence's exact bytes", MODULE + "_part",
     'hashlib.sha256(body.encode("utf-8")).hexdigest() in LANE_BLOCKS', "True",
     TESTS + "test_review_standing_follows_exact_bytes_not_file_or_heading_names"),
    ("shell normalization joins continued lines", MODULE + "_normalized",
     'SHELL_QUOTING.sub("", text.replace("\\\\\\n", ""))', "text",
     INVOKE + "[change2]"),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
