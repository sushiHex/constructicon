"""Load-bearing native lifetime instrument checks; no mutation writes files."""

from _mutations import run

MODULE = "tests.native_lifecycle:"
TEST = "tests/test_native_lifecycle.py::"

MUTANTS = (
    ("unentered close disposes", MODULE + "NativeFixtureProvider.close",
     "if handle.entered:", "if True:",
     TEST + "test_native_acquire_and_unentered_close_write_nothing"),
    ("durable absent resource not fenced", MODULE + "NativeFixtureProvider.reconcile",
     "await dispose_acquisition(self.closure, AcquisitionPaths(self.root, acquisition))", "pass",
     TEST + "test_native_recovery_disposes_durable_row_even_if_absent"),
    ("foreign root accepted", MODULE + "NativeFixtureProvider.reconcile",
     "row.resource_ref != self.reference(acquisition)", "False",
     TEST + "test_native_recovery_rejects_foreign_rows[root]"),
    ("current epoch reconciled", MODULE + "NativeFixtureProvider.reconcile",
     "row.acquisition_epoch >= context.run_lease.epoch", "False",
     TEST + "test_native_recovery_rejects_foreign_rows[epoch]"),
    ("foreign binding accepted", MODULE + "NativeFixtureProvider.reconcile",
     "row.binding_id != context.binding.binding", "False",
     TEST + "test_native_recovery_rejects_foreign_rows[binding]"),
    ("foreign path accepted", MODULE + "NativeFixtureProvider.reconcile",
     "row.path != context.path", "False",
     TEST + "test_native_recovery_rejects_foreign_rows[path]"),
    ("control not observed", MODULE + "NativeFixture.check_control",
     "self.context.check_control()", "pass",
     TEST + "test_native_work_observes_control_and_closure"),
    ("closure not observed", MODULE + "NativeFixture.require_open",
     "self.provider.closure.require_open, self.paths", "lambda _: None, self.paths",
     TEST + "test_native_work_observes_control_and_closure"),
    ("closure not checked under guard", MODULE + "NativeFixture.exchange",
     "await self.require_open()", "pass",
     TEST + "test_native_checks_closure_after_guard_before_endpoint"),
    ("borrowed guard not inherited", "tests.substrate.test_linux_duplex:exchange",
     "guard_fds=(guard,)", "guard_fds=()",
     TEST + "test_duplex_fixture_borrows_recorded_guard_without_relocking"),
    ("fixture route falsely granted network none", MODULE + "assemble",
     '"network": "allow"', '"network": "none"',
     TEST + "test_fixture_graph_admits_without_a_production_executor_profile"),
    ("failed worker process discarded", MODULE + "NativeFixture.worker",
     'evidence["process"] = {**asdict(result),', 'evidence["discarded"] = {**asdict(result),',
     TEST + "test_native_worker_retains_complete_failure_before_asserting"),
    ("failed exchange result discarded", MODULE + "NativeFixture.worker",
     "result = exc.result", "pass",
     TEST + "test_native_worker_retains_complete_failure_before_asserting[True]"),
    ("failed worker decoding discarded", MODULE + "NativeFixture.worker",
     'evidence["decoded"] = decoded.model_dump(mode="json")', 'pass',
     TEST + "test_native_worker_retains_complete_failure_before_asserting"),
    ("local closure missed across await", MODULE + "NativeFixture.require_open",
     ")))\n    self.check_control()", ")))\n    pass",
     TEST + "test_native_local_close_during_closure_check_refuses"),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
