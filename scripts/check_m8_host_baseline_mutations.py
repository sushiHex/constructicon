"""Assertion-only mutations for the source-only complete-inventory proposal."""

from _mutations import run

MODULE = "scripts.m8_host_baseline_contract:"
TESTS = "tests/test_m8_host_baseline_contract.py::"

MUTANTS = (
    ("incomplete inventory has a deliberate fixed refusal", MODULE + "_facts",
     "if set(values) != set(KEYS):", "if False:",
     TESTS + "test_missing_inventory_has_fixed_refusal_not_incidental_lookup_error"),
    ("duplicate rows are not silently overwritten", MODULE + "decode_baseline",
     'len(parts) != 2 or parts[0] in values', 'len(parts) != 2',
     TESTS + "test_reject_incomplete_or_ambiguous_baseline"),
    ("digest domains are exact", MODULE + "_valid_scalar",
     're.fullmatch(r"[0-9a-f]{64}", value) is not None', 'True',
     TESTS + "test_scalar_domains_refuse_in_both_directions"),
    ("valid scalar does not hide failed query", MODULE + "decode_observation",
     'result.returncode != 0 or ', '',
     TESTS + "test_each_query_must_complete_even_if_valid_value_matches_baseline"),
    ("query output bound binds", MODULE + "decode_observation",
     'not 1 <= len(result.stdout) <= MAX_QUERY_BYTES', 'len(result.stdout) < 1',
     TESTS + "test_query_byte_bound_precedes_scalar_interpretation"),
    ("positive comparison is truthful", MODULE + "compare",
     '"drifted" if changed else "unchanged"', '"unchanged"',
     TESTS + "test_accept_complete_and_compare_exact_surface"),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
