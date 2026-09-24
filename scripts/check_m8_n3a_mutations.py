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
PUBLISH_FAULT_TEST = "tests/substrate/test_operator_store_publish_faults.py::"
METADATA_TEST = "tests/substrate/test_operator_store_metadata.py::"
CREDENTIAL_TEST = "tests/substrate/test_operator_store_credential.py::"
LAYOUT_TEST = TEST + "test_the_native_layout_binds_two_descriptors_into_a_disposable_codex_home"

MUTANTS = (
    (
        "initial metadata I/O refusal does not publish the private locator",
        STORE + "BindingStore.open_candidate",
        "except OSError as exc:\n"
        "        self.close_candidate(opened)\n"
        '        raise ContractViolation("native store binding is unavailable") from exc',
        "except OSError:\n"
        "        self.close_candidate(opened)\n"
        "        raise",
        STORE_TEST + "test_metadata_io_refusal_never_exposes_the_private_locator[candidate]",
    ),
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
        "native store layout is present",
        LAUNCHER + "LinuxLauncher.argv",
        "if native_store is not None:",
        "if False:",
        TEST + "test_the_native_layout_binds_two_descriptors_into_a_disposable_codex_home",
    ),
    (
        "the credential is bound by its descriptor, never a path",
        LAUNCHER + "LinuxLauncher.argv",
        '"--bind-fd", str(native_store.credential_fd)',
        '"--bind", str(native_store.credential_fd)',
        TEST + "test_the_native_layout_binds_two_descriptors_into_a_disposable_codex_home",
    ),
    (
        "native store does not replace disposable HOME",
        LAUNCHER + "LinuxLauncher.argv",
        '"--setenv", "HOME", "/tmp/home"',
        '"--setenv", "HOME", "/tmp/home/.codex"',
        TEST + "test_the_native_layout_binds_two_descriptors_into_a_disposable_codex_home",
    ),
    (
        "native store launch keeps networking unshared",
        LAUNCHER + "LinuxLauncher.argv",
        '"--unshare-net"',
        '"--share-net"',
        TEST + "test_the_native_layout_binds_two_descriptors_into_a_disposable_codex_home",
    ),
    (
        "native layout descriptors are distinct",
        LAUNCHER + "NativeStoreMount.__post_init__",
        "or len(set(fds)) != len(fds)",
        "or False",
        TEST + "test_the_native_layout_requires_three_distinct_descriptors",
    ),
    (
        "absent native store cannot be made available by empty reasons",
        CODEX + "CodexOperatorProvider.__init__",
        "if binding_store is None and STORE_NOT_ESTABLISHED not in reasons:",
        "if False:",
        CODEX_STORE_TEST + "test_empty_reasons_cannot_claim_an_absent_store_is_available",
    ),
    (
        "a mutable acquisition alias is refused before it can target the native store",
        CODEX + "CodexOperatorProvider.__init__",
        "if acquisition_root != acquisition_locator:",
        "if False:",
        CODEX_STORE_TEST
        + "test_binding_refuses_an_acquisition_locator_that_differs_from_its_resolution",
    ),
    (
        "initial readiness requires a sealed binding observation",
        CODEX + "CodexOperatorHandle._checked_binding",
        "if not isinstance(value, BindingCheck) or value.binding_digest != expected:",
        "if False:",
        CODEX_STORE_TEST + "test_an_absent_initial_check_never_mints_readiness",
    ),
    (
        "initial readiness rereads durable closure after the final awaited observation",
        CODEX + "CodexOperatorHandle._materialize_owned",
        "self._require_open_sync()",
        "self._check_control()",
        CODEX_STORE_TEST + "test_durable_closure_after_final_await_never_mints_readiness",
    ),
    (
        "pre-launch check records a fresh positive observation",
        CODEX + "CodexOperatorHandle._converse",
        'check = self._checked_binding(store.check_held(held), "pre-launch")',
        "check = None",
        CODEX_STORE_TEST
        + "test_materialization_retains_one_store_lock_and_records_three_checks",
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
        "(self._materialization, self.active, self.worker_active)",
        "(self._materialization, self.worker_active)",
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
        "a well-typed check must match the expected binding digest",
        CODEX + "CodexOperatorHandle._checked_binding",
        "expected = self.provider.identity.store.operator_binding_digest",
        "expected = value.binding_digest",
        CODEX_STORE_TEST + "test_a_well_typed_check_for_another_binding_never_mints_readiness",
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
        STORE + "_check_descriptor",
        "or descriptor.binding_digest != sealed.operator_binding_digest",
        "or False",
        STORE_TEST + "test_active_generation_never_falls_back_to_an_old_matching_descriptor",
    ),
    (
        "same-instance historical root or lock remap is refused",
        STORE + "_check_descriptor",
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
        "descriptor.descriptor_digest != active.descriptor_digest",
        "False",
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
        STORE + "_check_descriptor",
        "descriptor.generation != generation",
        "False",
        SELECTION_TEST
        + "test_selected_descriptor_generation_must_match_active_generation",
    ),
    (
        "historical lock identity cannot be remapped",
        STORE + "_check_descriptor",
        "or old.lock != descriptor.lock",
        "or False",
        SELECTION_TEST + "test_historical_same_instance_lock_remap_is_refused",
    ),
    (
        "binding digest is derived from key generation and store instance",
        STORE + "_check_descriptor",
        "descriptor.binding_digest != expected_binding",
        "False",
        SELECTION_TEST
        + "test_binding_digest_is_derived_from_selected_key_generation_and_instance",
    ),
    (
        "current layout law is independently enforced",
        STORE + "_check_descriptor",
        "or descriptor.layout_law_digest != BINDING_LAYOUT_LAW",
        "or False",
        STORE_TEST + "test_selection_requires_the_current_runtime_law_not_only_matching_"
        "configuration[layout_law_digest]",
    ),
    (
        "current mount-lock law is independently enforced",
        STORE + "_check_descriptor",
        "or descriptor.mount_lock_law_digest != BINDING_MOUNT_LOCK_LAW",
        "or False",
        STORE_TEST + "test_selection_requires_the_current_runtime_law_not_only_matching_"
        "configuration[mount_lock_law_digest]",
    ),
    (
        "publisher instance is rederived from the opened physical store",
        STORE + "_check_descriptor",
        "or descriptor.store_instance_id != _identity_instance(opened.store_identity)",
        "or False",
        STORE_TEST + "test_selection_rederives_the_publisher_instance_from_the_live_store",
    ),
    (
        "anchor schema version rejects bool and float impostors",
        STORE + "_anchor",
        "or type(body[\"schema_version\"]) is not int",
        "or False",
        STORE_TEST + "test_schema_version_requires_an_exact_integer",
    ),
    (
        "descriptor schema version rejects bool and float impostors",
        STORE + "_descriptor",
        "or type(body[\"schema_version\"]) is not int",
        "or False",
        STORE_TEST + "test_schema_version_requires_an_exact_integer",
    ),
    (
        "active schema version rejects bool and float impostors",
        STORE + "_active",
        "if type(body[\"schema_version\"]) is not int or body[\"schema_version\"] != 1:",
        "if body[\"schema_version\"] != 1:",
        STORE_TEST + "test_schema_version_requires_an_exact_integer",
    ),
    (
        "mutable store-directory link count is excluded from restart identity",
        STORE + "_same_store_identity",
        "and left.uid == right.uid",
        "and left.uid == right.uid and left.nlink == right.nlink",
        STORE_TEST + "test_store_directory_link_count_is_not_a_restart_identity_component",
    ),
    (
        "existing immutable metadata name is never acknowledged as published",
        STORE + "_publish_new",
        "raise ContractViolation(\n"
        '                "native store descriptor publication is unavailable"\n'
        "            ) from exc",
        "pass",
        PUBLISH_FAULT_TEST
        + "test_existing_descriptor_name_refuses_and_cleans_its_private_temporary",
    ),
    (
        "metadata byte bound rejects an input one byte over the inclusive limit",
        STORE + "_metadata",
        "if not raw or len(raw) > MAX_METADATA_BYTES:",
        "if not raw:",
        PUBLISH_FAULT_TEST + "test_metadata_enforces_inclusive_size_limit[1]",
    ),
    (
        "deep malformed metadata becomes a bounded contract refusal",
        STORE + "_metadata",
        "except (UnicodeDecodeError, ValueError, RecursionError) as exc:",
        "except (UnicodeDecodeError, ValueError) as exc:",
        METADATA_TEST + "test_deep_metadata_is_a_bounded_refusal_not_a_parser_exception",
    ),
    (
        "metadata opens nonblocking before checking regular-file type",
        STORE + "_read_metadata",
        "target, os.O_RDONLY | _O_CLOEXEC | _O_NOFOLLOW | _O_NONBLOCK,",
        "target, os.O_RDONLY | _O_CLOEXEC | _O_NOFOLLOW,",
        METADATA_TEST + "test_metadata_open_cannot_block_before_nonregular_file_refusal",
    ),
    (
        "invalid publisher keys are refused before filesystem entry",
        STORE + "publish_descriptor_offline",
        "key = _require_token(key, field=\"key\")",
        "key = key",
        PUBLICATION_TEST + "test_invalid_key_refuses_before_filesystem_entry",
    ),
    (
        "both exact publisher byte strings pass strict reader validation before write",
        STORE + "publish_descriptor_offline",
        "_anchor(anchor_raw)\n            _descriptor(descriptor_raw)",
        "pass",
        PUBLICATION_TEST
        + "test_oversized_publisher_metadata_refuses_before_any_immutable_write",
    ),
    (
        "existing provisioned directories retain their exact fixed mode",
        STORE + "_provision_directory",
        "or stat.S_IMODE(info.st_mode) != mode",
        "or False",
        PUBLICATION_TEST + "test_existing_directory_requires_its_exact_fixed_mode",
    ),
    (
        "existing retained lock retains its exact fixed mode",
        STORE + "_provision_lock",
        "or stat.S_IMODE(info.st_mode) != _LOCK_MODE",
        "or False",
        PUBLICATION_TEST + "test_existing_lock_requires_its_exact_fixed_mode",
    ),
    (
        "reader enforces the fixed bundle mode",
        STORE + "_open_bundle",
        "bundle_identity.mode != _BUNDLE_MODE",
        "False",
        PUBLICATION_TEST + "test_reader_refuses_a_wrong_fixed_child_mode_or_store_lock_owner",
    ),
    (
        "reader requires store and retained lock to have one runtime owner",
        STORE + "_open_bundle",
        "or store_identity.uid != lock_identity.uid",
        "or False",
        PUBLICATION_TEST + "test_reader_refuses_a_wrong_fixed_child_mode_or_store_lock_owner",
    ),
    (
        "zero metadata write cannot be treated as one byte of progress",
        STORE + "_publish_new",
        'raise OSError("short write while publishing native store metadata")',
        "count = 1",
        PUBLICATION_TEST + "test_short_metadata_write_refuses_and_removes_its_private_temporary",
    ),
    # --- the N4 narrow layout (M8-N4-state-review.md, section 1) ---
    (
        "L1 the credential must be a regular file",
        STORE + "check_credential",
        "not stat.S_ISREG(mode) or ",
        "",
        CREDENTIAL_TEST + "test_an_unqualified_credential_refuses_and_closes_what_it_opened",
    ),
    (
        "L2 the credential has exactly one name",
        STORE + "check_credential",
        "links != 1 or ",
        "",
        CREDENTIAL_TEST
        + "test_an_unqualified_credential_refuses_and_closes_what_it_opened[second-name]",
    ),
    (
        "L3 the credential belongs to the store owner",
        STORE + "check_credential",
        "uid != owner_uid",
        "False",
        CREDENTIAL_TEST
        + "test_an_unqualified_credential_refuses_and_closes_what_it_opened[other-owner]",
    ),
    (
        "L4 the credential mode is exactly 0600",
        STORE + "check_credential",
        "or stat.S_IMODE(mode) != _CREDENTIAL_MODE",
        "or False",
        CREDENTIAL_TEST + "test_only_mode_0600_passes",
    ),
    (
        "L5 the owner compared is the store directory's",
        STORE + "open_credential",
        "check_credential(fd, opened.store_identity.uid)",
        "check_credential(fd, 1000)",
        CREDENTIAL_TEST + "test_the_owner_is_the_store_directorys_not_a_process_uid",
    ),
    (
        "L6 a refused credential descriptor is closed",
        STORE + "open_credential",
        "        _close(fd)\n        raise",
        "        raise",
        CREDENTIAL_TEST
        + "test_an_unqualified_credential_refuses_and_closes_what_it_opened[group-readable]",
    ),
    (
        "L7 the credential is opened without following a link",
        STORE + "_open_credential_fd",
        "_O_PATH | _O_NOFOLLOW | _O_CLOEXEC",
        "_O_PATH | _O_CLOEXEC",
        CREDENTIAL_TEST + "test_the_real_open_is_path_only_no_follow_and_relative_to_the_store",
    ),
    (
        "L8 the credential is opened path-only, so it can never be read",
        STORE + "_open_credential_fd",
        "_O_PATH | _O_NOFOLLOW | _O_CLOEXEC",
        "_O_NOFOLLOW | _O_CLOEXEC",
        CREDENTIAL_TEST + "test_the_real_open_is_path_only_no_follow_and_relative_to_the_store",
    ),
    (
        "L9 the credential is opened relative to the checked store descriptor",
        STORE + "_open_credential_fd",
        "dir_fd=store_fd",
        "dir_fd=None",
        CREDENTIAL_TEST + "test_the_real_open_is_path_only_no_follow_and_relative_to_the_store",
    ),
    (
        "L10 a closed hold opens no credential",
        STORE + "BindingStore.open_credential",
        "if held.closed or held._opened.closed:",
        "if False:",
        CREDENTIAL_TEST + "test_a_closed_hold_opens_nothing",
    ),
    (
        "L11 the configuration is bound read-only",
        LAUNCHER + "LinuxLauncher.argv",
        '"--ro-bind-data", str(native_store.configuration_fd)',
        '"--bind-data", str(native_store.configuration_fd)',
        LAYOUT_TEST,
    ),
    (
        "L12 the vendor home is named explicitly",
        LAUNCHER + "LinuxLauncher.argv",
        '"--setenv", "CODEX_HOME", NATIVE_HOME,',
        "",
        LAYOUT_TEST,
    ),
    (
        "L13 a mount descriptor can never double as a guard",
        LAUNCHER + "LinuxLauncher._run",
        "if set(native_store.mount_fds) & set(guard_fds):",
        "if False:",
        TEST + "test_a_mount_descriptor_that_is_also_a_guard_never_reaches_the_check",
    ),
    (
        "L14 the supervisor is told which descriptors bwrap receives",
        LAUNCHER + "LinuxLauncher._run",
        "*mount_argument, *args,",
        "*args,",
        TEST + "test_the_supervisor_alone_is_told_which_descriptors_bwrap_receives",
    ),
    (
        "L15 the supervisor inherits the mount descriptors",
        LAUNCHER + "LinuxLauncher._run",
        "*guard_fds, *mount_fds),",
        "*guard_fds),",
        TEST + "test_the_supervisor_alone_is_told_which_descriptors_bwrap_receives",
    ),
    (
        "L16 the handle releases both mount descriptors after the exchange",
        CODEX + "CodexOperatorHandle._converse",
        "os.close(fd)",
        "pass",
        CODEX_STORE_TEST + "test_materialization_retains_one_store_lock_and_records_three_checks",
    ),
    (
        "L17 the handle refuses an unqualified credential before any launch",
        CODEX + "CodexOperatorHandle._converse",
        "mount_fds.append(store.open_credential(held))",
        "mount_fds.append(os.open(os.devnull, os.O_RDONLY))",
        CODEX_STORE_TEST + "test_an_unqualified_credential_file_refuses_before_any_launch",
    ),
    (
        "L18 the zone receives this provider's own configuration bytes",
        CODEX + "CodexOperatorHandle._converse",
        'sealed_data_fd(provider.configuration.encode("utf-8"))',
        'sealed_data_fd(b"")',
        CODEX_STORE_TEST + "test_materialization_retains_one_store_lock_and_records_three_checks",
    ),
    (
        "L19 the sealed configuration is rewound for bwrap's read (Linux)",
        LAUNCHER + "sealed_data_fd",
        "os.lseek(fd, 0, os.SEEK_SET)",
        "pass",
        CREDENTIAL_TEST + "test_the_sealed_configuration_is_immutable_and_positioned_for_bwrap",
    ),
    (
        "L20 the sealed configuration refuses later writes (Linux)",
        LAUNCHER + "sealed_data_fd",
        "fcntl.F_SEAL_WRITE | ",
        "",
        CREDENTIAL_TEST + "test_the_sealed_configuration_is_immutable_and_positioned_for_bwrap",
    ),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
