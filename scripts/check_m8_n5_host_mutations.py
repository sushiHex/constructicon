"""M8 N5 host assembly: one mutant per check; each must fail an assertion.

Run as the service on the provisioned lane, where the Linux assembly tests run.
The account's well-formedness has none: the returned seal validates it again,
so without the check a malformed account still cannot pass, only crash.
"""

from _mutations import run

HOST = "constructicon.substrate.executors.codex_host:"
TEST = "tests/substrate/test_codex_host.py::"
PASSING = TEST + "test_a_sealed_record_that_is_not_a_passing_startup_is_refused"


def passing(check: str, case: str):
    """Remove one affirmative fact from the passing-startup predicate."""
    return (f"a sealed qualification requires: {check}", HOST + "sealed_account",
            check, "True,", f"{PASSING}[{case}]")


MUTANTS = (
    ("the evidence must be the one the generation sealed",
     HOST + "sealed_account",
     "if q != store.subscription_mode_adapter_revision or q != store.store_conformance_revision:",
     "if False:",
     TEST + "test_evidence_the_generation_did_not_seal_is_refused"),
    ("the sealed record is closed",
     HOST + "sealed_account",
     'if set(record) != codex_lane.STARTUP_FIELDS | {"completed"}:', "if False:",
     TEST + "test_a_sealed_record_that_is_not_closed_is_refused"),
    passing('record["faults"] == [] and record["vendor_conformance_qualified"] is False,',
            "faults"),
    passing(
        'custody.get("kind") == "maintenance" and set(custody) == {"kind", "generation_floor"},',
        "custody",
    ),
    passing(
        'record["methods_sent"] == [named_method(item) for item in codex_lane.STARTUP_METHODS],',
        "methods",
    ),
    passing('record["observation"] == {"malformed_records": 0, "first_error": False},',
            "observation"),
    passing(
        'gate.get("completed") is True and gate.get("plan") in codex_lane.QUALIFICATION_PLANS,',
        "plan",
    ),
    passing('readback.get("spend_control_reached", True) in (False, None),', "spend"),
    passing('process.get("returncode") == 0 and process.get("payload_returncode") == 0,',
            "returncode"),
    ("a sealed qualification neither timed out nor failed its exchange",
     HOST + "sealed_account",
     'process.get(key, True) for key in ("timed_out", "bound_exceeded", "exchange_failed")',
     "False for key in ()", PASSING + "[timed-out]"),
    passing('relay.get("closed") is True and relay.get("denied") == {},', "relay-open"),
    passing('all(credential.get(key) is True for key in ("present", "regular_0600", "checked")),',
            "credential"),
    ("the sealed qualification ran the installed artifacts",
     HOST + "sealed_account",
     "if any(record[key] != value for key, value in installed.items()):", "if False:",
     TEST + "test_a_qualification_of_other_artifacts_is_refused"),
    ("the evidence has no duplicated key",
     HOST + "_unique", "if len(set(keys)) != len(keys):", "if False:",
     TEST + "test_evidence_that_is_not_one_bounded_unique_object_is_unavailable[duplicate-key]"),
    ("the state directory is checked before it is touched",
     HOST + "operator_provider",
     "if not (state.is_absolute() and state.resolve() == state"
     ' and (state / "closure.git").is_dir()):',
     "if False:",
     TEST + "test_an_unprepared_state_directory_is_refused_before_it_is_touched"),
    ("the session runs the production configuration",
     HOST + "operator_provider",
     'if (host.session / "config.toml").read_text(encoding="utf-8") != configuration:',
     "if False:",
     TEST + "test_a_session_configuration_other_than_production_is_refused"),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
