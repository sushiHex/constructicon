"""M8 N5 host assembly: one mutant per check; each must fail an assertion.

Run as the service on the provisioned lane, where the Linux assembly tests run.
The account's well-formedness has none: the returned seal validates it again,
so without the check a malformed account still cannot pass, only crash.
"""

from _mutations import run

HOST = "constructicon.substrate.executors.codex_host:"
TEST = "tests/substrate/test_codex_host.py::"
CLOSED = TEST + "test_a_sealed_record_that_is_not_closed_is_refused"
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
     'if set(record) != codex_lane.STARTUP_FIELDS | {"completed"} or any(',
     "if False and any(", CLOSED + "[extra]"),
    ("every nested object is closed",
     HOST + "sealed_account",
     "type(record[key]) is not dict or set(record[key]) != fields",
     "type(record[key]) is not dict", CLOSED + "[process-missing]"),
    passing('record["faults"] == [] and record["vendor_identity"] == "unverified",',
            "vendor-identity"),
    passing('record["vendor_conformance_qualified"] is False,', "conformance"),
    passing('custody["kind"] == "maintenance",', "custody"),
    passing(
        'record["methods_sent"] == [named_method(item) for item in codex_lane.STARTUP_METHODS],',
        "methods",
    ),
    passing('_zero(observation["malformed_records"]) and observation["first_error"] is False,',
            "observation"),
    passing('gate["completed"] is True and gate["plan"] in codex_lane.QUALIFICATION_PLANS,',
            "plan"),
    passing(
        'readback["spend_control_reached"] is False or readback["spend_control_reached"] is None,',
        "spend",
    ),
    passing('_zero(process["returncode"]) and _zero(process["payload_returncode"]),',
            "returncode"),
    passing(
        'all(process[key] is False for key in ("timed_out", "bound_exceeded", "exchange_failed")),',
        "timed-out",
    ),
    passing('relay["closed"] is True and relay["denied"] == {},', "relay-open"),
    passing('all(credential[key] is True for key in ("present", "regular_0600", "checked")),',
            "credential"),
    ("zero is an integer, never False",
     HOST + "_zero", "return type(value) is int and value == 0", "return value == 0",
     PASSING + "[returncode-bool]"),
    ("the sealed qualification ran the installed artifacts",
     HOST + "sealed_account",
     "if any(record[key] != value for key, value in installed.items()):", "if False:",
     TEST + "test_a_qualification_of_other_artifacts_is_refused"),
    ("the evidence has no duplicated key",
     HOST + "_unique", "if len(set(keys)) != len(keys):", "if False:",
     TEST + "test_evidence_that_is_not_one_bounded_unique_object_is_unavailable[duplicate-key]"),
    ("the state is prepared before it is touched",
     HOST + "operator_provider",
     "if not (closure.resolve() == closure and closure.is_dir()):",
     "if not (closure.resolve() == closure):",
     TEST + "test_an_unprepared_state_directory_is_refused_before_it_is_touched"),
    ("the state is reached through no link",
     HOST + "operator_provider",
     "if not (closure.resolve() == closure and closure.is_dir()):",
     "if not (closure.is_dir()):",
     TEST + "test_a_link_in_the_state_is_refused_before_anything_is_touched[state]"),
    ("the closure authority is no link",
     HOST + "operator_provider",
     "if not (closure.resolve() == closure and closure.is_dir()):",
     "if not (closure.is_dir()):",
     TEST + "test_a_link_in_the_state_is_refused_before_anything_is_touched[authority]"),
    ("the session runs the production configuration",
     HOST + "operator_provider",
     'if (host.session / "config.toml").read_text(encoding="utf-8") != configuration:',
     "if False:",
     TEST + "test_a_session_configuration_other_than_production_is_refused"),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
