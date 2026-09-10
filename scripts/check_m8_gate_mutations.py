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
        'raise ContractViolation("contained gate runtime identification failed")', "pass",
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
        'elif result.bound_exceeded:\n        status = "infrastructure_error"',
        'elif result.bound_exceeded:\n        status = "passed"',
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
    (
        "cooperative cancellation waits for a check to finish", BOUND + "verify",
        "self.provider._control(self)", "pass",
        "tests/substrate/test_gate_lifecycle.py::"
        "test_running_gate_heartbeats_and_quiesces_without_authority[cancel]",
    ),
    (
        "a locally closed gate still mints", GATE + "_control",
        "if handle._phase.closed:", "if False:",
        TEST + "test_local_close_observed_at_mint_boundary_prevents_authority",
    ),
    (
        "gate and effect can use different authority objects",
        "constructicon.api.system:Constructicon.__init__",
        "or not merge.is_assembled_from(journal, resource.authority)", "",
        TEST + "test_gate_and_merge_effect_share_one_exact_world[same-path]",
    ),
    (
        "mirrored objects confer authority over another repository",
        "constructicon.substrate.effects.git:MergeVerifiedEffect._subject",
        "if subject.repository != self._authority.repository_id:", "if False:",
        "tests/e2e/test_merge_effect.py::"
        "test_mirrored_objects_never_authorize_another_repository[execute]",
    ),
    (
        "recovery reports the wrong storage root reaped", GATE + "reconcile",
        "or reference.storage_root != str(self.root)", "",
        TEST + "test_recovery_never_reports_the_wrong_storage_root_reaped[root]",
    ),
    (
        "recovery closes a different repository's fence", GATE + "reconcile",
        "or reference.repository != self.closure.authority.repository_id", "",
        TEST + "test_recovery_never_reports_the_wrong_storage_root_reaped[repository]",
    ),
    (
        "recovery mutates before validating the complete batch", GATE + "reconcile",
        "pending.append((acquired, row.resource_ref))",
        "await dispose_acquisition(self.closure, AcquisitionPaths(self.root, acquired))\n"
        "        pending.append((acquired, row.resource_ref))",
        TEST + "test_recovery_validates_the_whole_batch_before_closing_any_row",
    ),
    (
        "reserved check exit is guessed to be infrastructure failure", GATE + "_check",
        "elif result.payload_returncode is None or result.returncode != result.payload_returncode:",
        "elif result.returncode in (125, 126, 127) or result.payload_returncode is None "
        "or result.returncode != result.payload_returncode:",
        TEST + "test_native_nonpassing_checks_remain_typed_data[exit125]",
    ),
    (
        "a missing private exit fact is accepted", GATE + "_check",
        "elif result.payload_returncode is None or result.returncode != result.payload_returncode:",
        "elif False:",
        TEST + "test_missing_or_contradictory_private_exit_is_not_a_pass[None]",
    ),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
