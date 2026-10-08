"""M8 N5 host assembly: one mutant per check; each must fail an assertion.

Run as the service on the provisioned lane, where the Linux assembly tests run.
"""

from _mutations import run

HOST = "constructicon.substrate.executors.codex_host:"
TEST = "tests/substrate/test_codex_host.py::"
CLOSED = TEST + "test_a_sealed_record_that_is_not_a_passing_startup_is_refused"

MUTANTS = (
    ("the evidence must be the one the generation sealed",
     HOST + "sealed_account",
     "if q != store.subscription_mode_adapter_revision or q != store.store_conformance_revision:",
     "if False:",
     TEST + "test_evidence_the_generation_did_not_seal_is_refused"),
    ("a sealed qualification has no faults",
     HOST + "sealed_account", 'and record.get("faults") == []', "and True", CLOSED + "[faults]"),
    ("a sealed qualification is a maintenance startup",
     HOST + "sealed_account",
     'and (record.get("custody") or {}).get("kind") == "maintenance"', "and True",
     CLOSED + "[custody]"),
    ("a sealed qualification names an approved plan",
     HOST + "sealed_account",
     'and gate.get("plan") in codex_lane.QUALIFICATION_PLANS', "and True", CLOSED + "[plan]"),
    ("a sealed qualification's gate completed",
     HOST + "sealed_account", 'and gate.get("completed") is True', "and True", CLOSED + "[gate]"),
    ("the session runs the production configuration",
     HOST + "operator_provider",
     'if (host.session / "config.toml").read_text(encoding="utf-8") != configuration:',
     "if False:",
     TEST + "test_a_session_configuration_other_than_production_is_refused"),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
