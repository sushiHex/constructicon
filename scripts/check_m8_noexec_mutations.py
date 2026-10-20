"""Portable evidence/cleanup guard mutations, never AppArmor qualification."""

from _mutations import run

MODULE = "scripts.ci.prove_m8_noexec:"
TEST = "tests/test_m8_noexec_proof.py::"

MUTANTS = (
    ("exact exit", MODULE + "exact", "result.returncode == code", "True",
     TEST + "test_clean_exact_process_result_is_required"),
    ("exact evidence", MODULE + "exact", "result.stdout == output", "True",
     TEST + "test_every_published_observation_is_required"),
    ("empty stderr", MODULE + "exact", 'result.stderr == b""', "True",
     TEST + "test_clean_exact_process_result_is_required"),
    ("enforcing profiles and missing target", MODULE + "validate_profiles",
     "observed == (expected if present else set())", "True",
     TEST + "test_profile_absence_or_wrong_mode_never_qualifies"),
    ("exclusive owned root", MODULE + "prove", "ROOT.mkdir(mode=0o755)",
     "ROOT.mkdir(mode=0o755, exist_ok=True)",
     TEST + "test_preexisting_fixture_is_never_removed_or_overwritten"),
    ("partial load is cleaned", MODULE + "prove", "if load_attempted:", "if False:",
     TEST + "test_partial_profile_load_is_removed_before_owned_files"),
    ("owned files are removed", MODULE + "prove", "shutil.rmtree(ROOT)", "pass",
     TEST + "test_orchestration_publishes_only_after_its_owned_cleanup"),
    ("no production claim", MODULE + "prove", '"production_available": False',
     '"production_available": True',
     TEST + "test_orchestration_publishes_only_after_its_owned_cleanup"),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
