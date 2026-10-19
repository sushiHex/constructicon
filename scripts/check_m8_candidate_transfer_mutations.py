"""Assertion-only guard mutations for the independently verified q13 transfer."""

from _mutations import run

MODULE = "scripts.m8_candidate_transfer:"
TESTS = "tests/test_m8_candidate_transfer_guards.py::"
TRANSFER_TESTS = "tests/test_m8_candidate_transfer.py::"

MUTANTS = (
    ("raw commit identity is pinned", MODULE + "commit_tree",
     'object_oid("commit", raw) == pins.candidate', "True",
     TESTS + "test_commit_bytes_must_match_raw_candidate_oid"),
    ("candidate vector matches the input digest", MODULE + "artifact_bytes",
     'hashlib.sha256(vector).hexdigest() == pins.input_sha256', "True",
     TESTS + "test_artifact_vector_must_match_pinned_input_digest"),
    ("historical projection is exact", MODULE + "parse_artifact",
     'canonical(value["historical"]) == canonical(pins.historical())', "True",
     TESTS + "test_artifact_historical_projection_must_match_pins"),
    ("receiver reconstructs the pinned tree", MODULE + "verify_candidate",
     'tree == (commit_tree(commit, pins) + "\\n").encode()', "True",
     TRANSFER_TESTS + "test_receiver_independently_rejects_extra_tree_even_with_valid_objects"),
    ("receiver requires the pinned trusted exam", MODULE + "verify_candidate",
     'report.passed and report.input_sha256 == pins.input_sha256\n'
     '            and report.render_sha256 == pins.render_sha256', "True",
     TRANSFER_TESTS + "test_receiver_refuses_wrong_render_and_nonpassing_exam"),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
