"""Load-bearing mutations for the N3a native-store launcher seam.

Run with ``uv run python scripts/check_m8_n3a_mutations.py``. The shared runner
mutates only child-process code objects and requires an assertion failure; a
collection, runtime, or harness error does not prove a mutant was killed.
"""

from _mutations import run

LAUNCHER = "constructicon.substrate.executors.linux:"
TEST = "tests/substrate/test_native_store_launch.py::"
CODEX = "constructicon.substrate.executors.codex:"
STORE = "constructicon.substrate.executors.operator_store:"
CODEX_STORE_TEST = "tests/substrate/test_codex_store.py::"
CODEX_ADAPTER_TEST = "tests/substrate/test_codex_adapter.py::"
STORE_TEST = "tests/substrate/test_operator_store.py::"
SELECTION_TEST = "tests/substrate/test_operator_store_selection.py::"
PUBLICATION_TEST = "tests/substrate/test_operator_store_publication.py::"

MUTANTS = (
    (
        "missing binding check reaches no spawn",
        LAUNCHER + "LinuxLauncher._run",
        "if not isinstance(checked, BindingCheck):",
        "if False:",
        TEST + "test_only_a_positive_post_probe_check_reaches_spawn[missing]",
    ),
    (
        "native store lock is one of the supervisor guards",
        LAUNCHER + "LinuxLauncher._run",
        "if native_store.lock_fd not in guard_fds:",
        "if False:",
        TEST + "test_a_native_mount_without_its_retained_lock_never_reaches_the_check",
    ),
    (
        "store and workspace cannot share the namespace",
        LAUNCHER + "LinuxLauncher.argv",
        "if native_store is not None and workspace is not None:",
        "if False:",
        TEST + "test_native_store_and_worker_workspace_are_mutually_exclusive",
    ),
    (
        "native store mount is present",
        LAUNCHER + "LinuxLauncher.argv",
        "if native_store is not None:",
        "if False:",
        TEST + "test_native_store_has_one_fixed_destination_and_keeps_home_disposable",
    ),
    (
        "native store destination is fixed",
        LAUNCHER + "LinuxLauncher.argv",
        '"/vendor-store"',
        '"/changed-store"',
        TEST + "test_native_store_has_one_fixed_destination_and_keeps_home_disposable",
    ),
    (
        "native store does not replace disposable HOME",
        LAUNCHER + "LinuxLauncher.argv",
        '"--setenv", "HOME", "/tmp/home"',
        '"--setenv", "HOME", "/vendor-store"',
        TEST + "test_native_store_has_one_fixed_destination_and_keeps_home_disposable",
    ),
    (
        "native store launch keeps networking unshared",
        LAUNCHER + "LinuxLauncher.argv",
        '"--unshare-net"',
        '"--share-net"',
        TEST + "test_native_store_has_one_fixed_destination_and_keeps_home_disposable",
    ),
    (
        "native store locator is absolute",
        LAUNCHER + "NativeStoreMount.__post_init__",
        "if not self.path.is_absolute():",
        "if False:",
        TEST + "test_native_store_requires_an_absolute_private_locator",
    ),
    (
        "absent native store cannot be made available by empty reasons",
        CODEX + "CodexOperatorProvider.__init__",
        "if binding_store is None and STORE_NOT_ESTABLISHED not in reasons:",
        "if False:",
        CODEX_STORE_TEST + "test_empty_reasons_cannot_claim_an_absent_store_is_available",
    ),
    (
        "initial readiness requires a sealed binding receipt",
        CODEX + "CodexOperatorHandle._checked_binding",
        "if not isinstance(value, BindingCheck) or value.binding_digest != expected:",
        "if False:",
        CODEX_STORE_TEST + "test_an_absent_initial_receipt_never_mints_readiness",
    ),
    (
        "pre-launch check records a fresh positive receipt",
        CODEX + "CodexOperatorHandle._converse",
        'check = self._checked_binding(store.check_held(held), "pre-launch")',
        "check = None",
        CODEX_STORE_TEST
        + "test_materialization_retains_one_store_lock_and_publishes_three_receipts",
    ),
    (
        "terminal phase rechecks the retained binding",
        CODEX + "CodexOperatorHandle._converse",
        'terminal = self._checked_binding(store.check_held(held), "terminal")',
        "terminal = self.launch_check",
        CODEX_STORE_TEST + "test_terminal_binding_drift_discards_the_completed_turn",
    ),
    (
        "cleanup cancels and joins the active exchange before releasing custody",
        CODEX + "CodexOperatorHandle._cleanup_owned",
        "task for task in (self._materialization, self.active) if task is not None",
        "task for task in (self._materialization,) if task is not None",
        CODEX_ADAPTER_TEST + "test_close_cancels_an_exchange_still_in_flight",
    ),
    (
        "recovery reference acquisition matches the stale lease epoch",
        CODEX + "CodexOperatorProvider.reconcile",
        "acquired != expected",
        "False",
        CODEX_ADAPTER_TEST + "test_reconciliation_refuses_a_row_that_contradicts_its_identity",
    ),
    (
        "complete stale batch validates its binding before any closure",
        CODEX + "CodexOperatorProvider.reconcile",
        "or row.binding_id != context.binding.binding",
        "or False",
        CODEX_STORE_TEST + "test_reconcile_validates_the_complete_batch_before_any_closure",
    ),
    (
        "a well-typed receipt must match the expected binding digest",
        CODEX + "CodexOperatorHandle._checked_binding",
        "expected = self.provider.identity.store.operator_binding_digest",
        "expected = value.binding_digest",
        CODEX_STORE_TEST + "test_a_well_typed_receipt_for_another_binding_never_mints_readiness",
    ),
    (
        "one acquisition cannot execute a second task",
        CODEX + "CodexOperatorHandle.execute",
        "if self.executed:",
        "if False:",
        CODEX_STORE_TEST + "test_one_acquisition_cannot_execute_a_second_task",
    ),
    (
        "candidate admission requires an active descriptor selection",
        STORE + "BindingStore.open_candidate",
        "self._check_selection(opened)",
        "pass",
        STORE_TEST + "test_no_absent_or_ambiguous_active_selection_is_accepted[missing]",
    ),
    (
        "active generation remains bound to the sealed generation",
        STORE + "BindingStore._check_selection",
        "or descriptor.binding_digest != self.sealed.operator_binding_digest",
        "or False",
        STORE_TEST + "test_active_generation_never_falls_back_to_an_old_matching_descriptor",
    ),
    (
        "same-instance historical root or lock remap is refused",
        STORE + "BindingStore._check_selection",
        "not _same_store_identity(old.store, descriptor.store)",
        "False",
        STORE_TEST + "test_same_instance_historical_root_or_lock_remap_refuses",
    ),
    (
        "active key matches the configured store binding",
        STORE + "BindingStore._check_selection",
        "if active.key != self.key:",
        "if False:",
        SELECTION_TEST + "test_active_key_must_match_the_configured_binding",
    ),
    (
        "active descriptor digest matches its descriptor",
        STORE + "BindingStore._check_selection",
        "or descriptor.descriptor_digest != active.descriptor_digest",
        "or False",
        SELECTION_TEST
        + "test_active_digests_must_match_the_selected_descriptor[descriptor_digest]",
    ),
    (
        "active binding digest matches its descriptor",
        STORE + "BindingStore._check_selection",
        "or descriptor.binding_digest != active.binding_digest",
        "or False",
        SELECTION_TEST
        + "test_active_digests_must_match_the_selected_descriptor[binding_digest]",
    ),
    (
        "descriptor generation matches the active generation",
        STORE + "BindingStore._check_selection",
        "descriptor.generation != active.generation",
        "False",
        SELECTION_TEST
        + "test_selected_descriptor_generation_must_match_active_generation",
    ),
    (
        "historical lock identity cannot be remapped",
        STORE + "BindingStore._check_selection",
        "or old.lock != descriptor.lock",
        "or False",
        SELECTION_TEST + "test_historical_same_instance_lock_remap_is_refused",
    ),
    (
        "binding digest is derived from key generation and store instance",
        STORE + "BindingStore._check_selection",
        "descriptor.binding_digest != expected_binding",
        "False",
        SELECTION_TEST
        + "test_binding_digest_is_derived_from_selected_key_generation_and_instance",
    ),
    (
        "zero metadata write cannot be treated as one byte of progress",
        STORE + "_publish_new",
        'raise OSError("short write while publishing native store metadata")',
        "count = 1",
        PUBLICATION_TEST + "test_short_metadata_write_refuses_and_removes_its_private_temporary",
    ),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
