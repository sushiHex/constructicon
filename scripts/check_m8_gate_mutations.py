"""PR D: isolated gate mutations; only assertion failures count as evidence."""

from _mutations import run

GATE = "constructicon.substrate.gates.contained:ContainedGateRunner."
BOUND = "constructicon.substrate.gates.contained:BoundContainedGate."
TEST = "tests/substrate/test_contained_gates.py::"

MUTANTS = (
    (
        "runtime identification receives a repository mount", GATE + "create",
        "workspace=None, posture=Posture.READ", "workspace=root, posture=Posture.READ",
        TEST + "test_identification_is_mount_free_and_inert_even_without_a_target",
    ),
    (
        "failed runtime probe qualifies", GATE + "create",
        "if result.returncode or result.timed_out or result.bound_exceeded:", "if False:",
        TEST + "test_failed_runtime_identification_never_qualifies[exit]",
    ),
    (
        "runtime drift during identification qualifies", GATE + "create",
        "if after != before:", "if False:",
        TEST + "test_failed_runtime_identification_never_qualifies[drift]",
    ),
    (
        "checks mount the candidate writable", GATE + "_check",
        "workspace=snapshot, posture=Posture.READ", "workspace=snapshot, posture=Posture.WRITE",
        TEST + "test_hostile_repository_check_is_physically_confined",
    ),
    (
        "timeout is reported passed", GATE + "_check",
        'status = "timeout"', 'status = "passed"',
        TEST + "test_native_nonpassing_checks_remain_typed_data[timeout]",
    ),
    (
        "output overflow is reported passed", GATE + "_check",
        'status = "infrastructure_error"\n            detail =',
        'status = "passed"\n            detail =',
        TEST + "test_native_output_overflow_cannot_pass[stdout]",
    ),
    (
        "stderr avoids the hard output budget", GATE + "_check",
        '("/usr/bin/python3", "-I", "-c", _CHECK, *spec.argv)', "spec.argv",
        TEST + "test_native_output_overflow_cannot_pass[stderr]",
    ),
    (
        "snapshot integrity is ignored", GATE + "_verify",
        "if after != before:", "if False:",
        TEST + "test_integrity_failure_is_checked_after_launch_and_before_mint",
    ),
    (
        "exported tree equality is ignored", GATE + "_snapshot",
        "if observed != expected:", "if False:",
        TEST + "test_lossy_archive_cannot_claim_the_original_tree[export-ignore]",
    ),
    (
        "pre-mint control observation is absent", GATE + "_verify",
        "self._control(handle)", "pass",
        TEST + "test_explicit_control_check_immediately_before_mint_is_load_bearing",
    ),
    (
        "durable recovery skips revocation", GATE + "reconcile",
        "await dispose_acquisition(self.closure, AcquisitionPaths(self.root, acquired))", "pass",
        TEST + "test_recovery_before_verify_has_no_subject_or_current_base_dependency[False]",
    ),
    (
        "ready handles ignore permanent closure", GATE + "_require_open",
        "self.closure.require_open, handle.paths,", "lambda _: None, handle.paths,",
        TEST + "test_closed_marker_prevents_late_verify_even_on_a_ready_local_handle",
    ),
    (
        "close of an inert handle allocates a tombstone", GATE + "close",
        "if handle._phase.entered:", "if True:",
        TEST + "test_identification_is_mount_free_and_inert_even_without_a_target",
    ),
    (
        "gate resources can bind a different journal",
        "constructicon.api.system:Constructicon.__init__",
        "or not resource.is_assembled_from(journal)", "",
        TEST + "test_contained_gate_assembly_requires_exact_facts[journal]",
    ),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
