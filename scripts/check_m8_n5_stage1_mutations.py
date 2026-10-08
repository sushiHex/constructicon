"""M8 N5 Stage 1: one mutant per qualification gate; each must fail an assertion."""

from _mutations import run

CORE = "constructicon.core.qualification:QualificationAuthorization."
CODEX = "constructicon.substrate.executors.codex:"
CORE_TEST = "tests/core/test_qualification.py::"
CODEX_TEST = "tests/substrate/test_codex_qualification.py::"
ENTRY_TEST = "tests/api/test_qualification_entry.py::"
ADMISSION_TEST = "tests/api/test_executor_admission.py::"

MUTANTS = (
    ("admission omits the reasons only for an authorizing provider",
     "constructicon.runtime.validator:_admitted_unavailability",
     "        return ()\n", "        return reasons\n",
     ADMISSION_TEST
     + "test_a_qualification_authorization_admits_only_its_graph_and_publishes_every_reason"),
    ("a locked admission is never exempt",
     "constructicon.runtime.validator:_admitted_unavailability",
     "and comp.resolution_lock is None", "and True",
     ADMISSION_TEST + "test_a_locked_admission_of_the_authorized_graph_is_never_exempt"),
    ("the journal holds no other run",
     "constructicon.api.qualification:_require_dedicated",
     "if record.run_id != authorization.run_id or", "if",
     ENTRY_TEST + "test_a_journal_holding_another_run_is_refused_before_recovery"),
    ("the authorized run carries the authorized graph",
     "constructicon.api.qualification:_require_dedicated",
     "or _stored_graph(", "and _stored_graph(",
     ENTRY_TEST + "test_the_same_run_id_carrying_another_graph_is_refused_before_recovery"),
    ("the provider answers admission only for its authorization",
     CODEX + "CodexOperatorProvider.authorizes_admission",
     "return self.qualification is not None and", "return True or",
     CODEX_TEST + "test_admission_is_answered_only_for_the_authorized_graph"),
    ("admission is asked about the exact graph",
     CORE + "admits", "source_graph_hash == self.source_graph_hash", "True",
     CORE_TEST + "test_admission_is_timeless_and_names_graph_capability_and_revision"),
    ("acquisition is pinned to the run",
     CORE + "acquisition_faults", "(run_id == self.run_id,", "(True,",
     CORE_TEST + "test_every_other_acquisition_is_refused_for_its_reason"),
    ("acquisition is pinned to the graph, recovery included",
     CORE + "acquisition_faults",
     "(source_graph_hash == self.source_graph_hash,", "(True,",
     CORE_TEST + "test_every_other_acquisition_is_refused_for_its_reason"),
    ("acquisition is bounded by max_epoch",
     CORE + "acquisition_faults", "(epoch <= self.max_epoch,", "(True,",
     ENTRY_TEST + "test_a_successor_reconciles_and_acquires_only_within_the_budget"),
    ("acquisition is bounded by expiry",
     CORE + "acquisition_faults", "(now < self.not_after,", "(True,",
     ENTRY_TEST + "test_an_expired_authorization_admits_but_never_acquires"),
    ("the provider enforces the authorization at acquire",
     CODEX + "CodexOperatorProvider.acquire",
     "if qualification is not None and (faults :=", "if False and (faults :=",
     CODEX_TEST + "test_an_epoch_beyond_the_authorization_mints_nothing"),
    ("an unauthorized unavailable provider still cannot acquire",
     CODEX + "CodexOperatorProvider.acquire",
     "if self.unavailable_reasons and qualification is None:", "if False:",
     CODEX_TEST + "test_an_ordinary_provider_still_dispatches_and_still_refuses_unavailable"),
    ("a qualification handle is minted without dispatch",
     CODEX + "CodexOperatorProvider.acquire",
     "dispatch=qualification is None or qualification.dispatches,", "dispatch=True,",
     CODEX_TEST + "test_the_authorized_acquisition_materializes_and_never_dispatches"),
    ("execute refuses a qualification handle first",
     CODEX + "CodexOperatorHandle.execute", "if not self.dispatch:", "if False:",
     CODEX_TEST + "test_the_authorized_acquisition_materializes_and_never_dispatches"),
    ("assembly refuses an authorization for another provider",
     CODEX + "CodexOperatorProvider.__init__",
     "if qualification is not None and (\n", "if False and (\n",
     CODEX_TEST + "test_an_authorization_naming_another_provider_is_refused_at_assembly"),
    ("the entry runs only its own fixed invocation",
     "constructicon.api.qualification:_require_coherent",
     "or authorization.source_graph_hash != graph", "or False",
     ENTRY_TEST + "test_an_unauthorized_provider_or_invocation_is_refused_before_any_journal"),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
