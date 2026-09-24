"""Load-bearing mutations for N3c maintenance, activation and overage.

Run with ``uv run python scripts/check_m8_n3c_mutations.py``. The shared runner
mutates only child-process code objects and requires an assertion failure; a
collection, runtime, or harness error does not prove a mutant was killed.
Every killing test is portable or a Linux unit test, never a provisioned lane.
The Linux unit mutants (9, 10, 11, 15, 24, 27) report NOT PROVEN on Windows,
where their tests skip; that is expected and is not a kill.
"""

from _mutations import run

STORE = "constructicon.substrate.executors.operator_store:"
CODEX = "constructicon.substrate.executors.codex:"
MAINTAIN = STORE + "maintain_offline.__wrapped__"
S = "tests/substrate/test_operator_store_maintenance.py::"
U = "tests/substrate/test_operator_store_replace.py::"
C = "tests/substrate/test_codex_matrix.py::"
K = "tests/substrate/test_operator_store_credential.py::"
I = "tests/substrate/test_operator_store_inheritance.py::"  # noqa: E741
INHERIT = STORE + "inherit_maintenance.__wrapped__"
HOLD = STORE + "_require_inherited_hold"
SPAWN = STORE + "run_under_maintenance"
REANCHOR = (
    "            if not anchored:\n"
    "                anchor_raw = canonical_json({\n"
    '                    "schema_version": 1, "key": key,\n'
    '                    "bundle": opened.bundle_identity.model_dump(),\n'
    "                }).encode()\n"
    "                _anchor(anchor_raw)\n"
    '                _replace_metadata(opened.bundle_fd, "anchor.json", anchor_raw)\n'
)

MUTANTS = (
    (
        "1 maintenance exposes the store only after its withdrawal returns",
        MAINTAIN,
        '_replace_metadata(opened.bundle_fd, "active.json", raw)',
        "yield StoreMaintenance(opened.store_path, floor, opened.lock_fd, opened, root, key)\n"
        '            _replace_metadata(opened.bundle_fd, "active.json", raw)',
        S + "test_maintenance_withdraws_durably_before_it_exposes_the_store",
    ),
    (
        "2 maintenance writes the withdrawal record",
        MAINTAIN,
        '_replace_metadata(opened.bundle_fd, "active.json", raw)',
        "pass",
        S + "test_every_provider_refuses_inside_maintenance",
    ),
    (
        "3 an offline helper waits for the retained lock",
        STORE + "_hold_offline",
        "while not _flock(opened.lock_fd):",
        "while False:",
        S + "test_a_held_lock_or_a_failed_withdrawal_never_runs_the_body[held]",
    ),
    (
        "4 an offline helper re-proves the objects under the lock",
        STORE + "_hold_offline",
        "_require_same_objects(current, opened)",
        "pass",
        S + "test_objects_replaced_during_the_lock_wait_refuse_with_nothing_written"
        "[store-maintain]",
    ),
    (
        "5 the floor is the inventory maximum, not the previous selection",
        MAINTAIN,
        'floor = int(names[-1].removesuffix(".json")) if names else 0',
        'floor = _active(_read_metadata(opened, "active.json")).generation',
        S + "test_a_descriptor_published_before_maintenance_cannot_be_activated",
    ),
    (
        "6 activation refuses an active current state",
        STORE + "_current_withdrawal",
        "withdrawal = _withdrawal(raw)",
        'withdrawal = _withdrawal(raw) if b"generation_floor" in raw else _Withdrawal(key, 0)',
        S + "test_activation_requires_a_durable_withdrawal_for_this_key[active]",
    ),
    (
        "7 activation refuses an absent current state",
        STORE + "_current_withdrawal",
        'raise ContractViolation("native store withdrawal is unavailable") from exc',
        "return _Withdrawal(key, 0)",
        S + "test_activation_requires_a_durable_withdrawal_for_this_key[absent]",
    ),
    (
        "8 the floor itself is never activated",
        STORE + "activate_offline",
        "if generation <= withdrawal.generation_floor:",
        "if generation < withdrawal.generation_floor:",
        S + "test_a_generation_at_or_below_the_floor_is_never_activated[1-1]",
    ),
    (
        "9 the replace persists its directory",
        STORE + "_replace_metadata",
        "os.fsync(directory_fd)",
        "pass",
        U + "test_replace_writes_seals_syncs_replaces_then_syncs_the_directory",
    ),
    (
        "10 the replace never writes the live file in place",
        STORE + "_replace_metadata",
        "temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_CLOEXEC | _O_NOFOLLOW, 0o600,",
        "name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _O_CLOEXEC | _O_NOFOLLOW, 0o600,",
        U + "test_a_failed_replace_leaves_the_previous_file_and_no_temporary[replace]",
    ),
    (
        "11 the replaced record carries the metadata ownership law",
        STORE + "_replace_metadata",
        "_seal_metadata_fd(fd, directory_fd)",
        "pass",
        U + "test_replace_writes_seals_syncs_replaces_then_syncs_the_directory",
    ),
    (
        "12 activation compares the descriptor with the qualified identity",
        STORE + "_check_descriptor",
        "or descriptor.binding_digest != sealed.operator_binding_digest",
        "or False",
        S + "test_activation_checks_the_descriptor_against_qualification_and_live_objects"
        "[previous-sealed]",
    ),
    (
        "13 the descriptor must match the live store identity",
        STORE + "_check_descriptor",
        "or not _same_store_identity(descriptor.store, opened.store_identity)",
        "or False",
        S + "test_activation_checks_the_descriptor_against_qualification_and_live_objects"
        "[live-store]",
    ),
    (
        "14 another mount at the store root is refused",
        STORE + "_mounts_below",
        "if point == prefix and int(fields[0]) != mount_id:",
        "if False:",
        S + "test_a_mount_at_or_below_the_store_is_refused[other-at-root]",
    ),
    (
        "15 the store shares its root's mount",
        STORE + "_open_bundle",
        "or store_identity.mount_id != root_identity.mount_id",
        "or False",
        U + "test_a_child_on_another_mount_than_its_root_is_refused[store]",
    ),
    (
        "16 a mount below the store is refused",
        STORE + "_mounts_below",
        'if point.startswith(prefix.rstrip("/") + "/"):',
        "if False:",
        S + "test_a_mount_at_or_below_the_store_is_refused[below]",
    ),
    (
        "17 an unrecognised descriptor name disables the inventory",
        STORE + "_descriptor_names",
        'raise ContractViolation("native store descriptor inventory is unavailable")',
        "continue",
        S + "test_an_orphaned_publication_temporary_disables_everything_until_removed",
    ),
    (
        "18 maintenance exit releases the retained lock",
        MAINTAIN,
        "_close_opened(opened)",
        "pass",
        S + "test_maintenance_exit_releases_the_lock_and_activates_nothing",
    ),
    (
        "19 recovery refuses another generation's reference",
        CODEX + "CodexOperatorProvider.reconcile",
        "or binding_digest != self.identity.store.operator_binding_digest",
        "or False",
        S + "test_a_new_generation_provider_refuses_an_old_reference_without_disposal",
    ),
    (
        "20 an overages-forbidden profile is forced unavailable",
        CODEX + "CodexOperatorProvider.__init__",
        'if profile.subscription_overage == "forbidden" and OVERAGE_NOT_ENFORCED not in reasons:',
        "if False:",
        C + "test_only_the_overage_literal_forces_unavailability"
        "[forbidden-unbound-pro-read]",
    ),
    (
        "21 the forced overage reason spares an authorized profile",
        CODEX + "CodexOperatorProvider.__init__",
        'profile.subscription_overage == "forbidden"',
        'profile.subscription_overage in ("forbidden", "operator_authorized")',
        C + "test_only_the_overage_literal_forces_unavailability"
        "[operator_authorized-unbound-pro-read]",
    ),
    (
        "22 the forced overage reason reads the overage literal, not a label",
        CODEX + "CodexOperatorProvider.__init__",
        'profile.subscription_overage == "forbidden"',
        'profile.authentication == "vendor_managed_subscription"',
        C + "test_only_the_overage_literal_forces_unavailability"
        "[operator_authorized-unbound-pro-read]",
    ),
    (
        "23 publication holds the retained lock",
        STORE + "publish_descriptor_offline",
        "_hold_offline(opened, root, token, wait_s)",
        "pass",
        S + "test_publication_waits_for_every_holder_and_publishes_after_it[handle]",
    ),
    (
        "24 a published descriptor carries the metadata ownership law",
        STORE + "_publish_new",
        "_seal_metadata_fd(fd, directory_fd)",
        "pass",
        U + "test_publication_seals_a_new_descriptor_by_the_same_law",
    ),
    (
        "25 activation requires this key's withdrawal",
        STORE + "_current_withdrawal",
        "if withdrawal.key != key:",
        "if False:",
        S + "test_activation_requires_a_durable_withdrawal_for_this_key[other-key]",
    ),
    (
        "26 the descriptor's own key must be the requested one",
        STORE + "_check_descriptor",
        "if descriptor.key != key or descriptor.generation != generation:",
        "if descriptor.generation != generation:",
        S + "test_activation_checks_the_descriptor_against_qualification_and_live_objects"
        "[key]",
    ),
    (
        "27 a failed directory sync is never treated as durable",
        STORE + "_replace_metadata",
        "os.fsync(directory_fd)",
        "try:\n        os.fsync(directory_fd)\n    except OSError:\n        pass",
        U + "test_a_directory_sync_failure_after_the_replace_never_exposes_the_store",
    ),
    (
        "28 an invalid wait is refused",
        STORE + "_require_wait",
        'raise ContractViolation("native store maintenance wait is invalid")',
        "pass",
        S + "test_an_invalid_wait_refuses_before_any_lock_attempt[bool-maintain]",
    ),
    (
        "29 the descriptor's own generation must be the requested one",
        STORE + "_check_descriptor",
        "if descriptor.key != key or descriptor.generation != generation:",
        "if descriptor.key != key:",
        S + "test_activation_checks_the_descriptor_against_qualification_and_live_objects"
        "[generation]",
    ),
    (
        "30 the floor is the inventory maximum, not its count",
        MAINTAIN,
        'floor = int(names[-1].removesuffix(".json")) if names else 0',
        "floor = len(names)",
        S + "test_the_floor_is_the_numeric_maximum_of_the_inventory[gapped]",
    ),
    (
        "31 the descriptor inventory is ordered numerically",
        STORE + "_descriptor_names",
        'return tuple(sorted(names, key=lambda value: int(value.removesuffix(".json"))))',
        "return tuple(sorted(names))",
        S + "test_the_floor_is_the_numeric_maximum_of_the_inventory[numeric-order]",
    ),
    (
        "32 mountinfo space and tab escapes are decoded",
        STORE + "_mounts_below",
        'fields[4].replace(r"\\040", " ").replace(r"\\011", "\\t")',
        "fields[4]",
        S + "test_mountinfo_escapes_are_decoded_before_comparison[other-at-escaped-root]",
    ),
    (
        "33 the mountinfo backslash escape is decoded",
        STORE + "_mounts_below",
        '.replace(r"\\012", "\\n").replace(r"\\134", "\\\\")',
        '.replace(r"\\012", "\\n")',
        S + "test_mountinfo_escapes_are_decoded_before_comparison[backslash]",
    ),
    (
        "34 the mountinfo size bound binds at its limit",
        STORE + "_mounts_below",
        "if len(raw) > MAX_MOUNTINFO_BYTES:",
        "if len(raw) > MAX_MOUNTINFO_BYTES + 1:",
        S + "test_the_mountinfo_bound_binds_at_its_limit",
    ),
    (
        "35 a malformed mountinfo line is refused",
        STORE + "_mounts_below",
        "if len(fields) < 5 or not fields[0].isdigit():",
        "if False:",
        S + "test_a_malformed_mountinfo_line_is_refused[non-digit-id]",
    ),
    (
        "36 the offline helpers require this binding's anchor key",
        STORE + "_anchor_is_current",
        "if anchor.key != key:",
        "if False:",
        S + "test_offline_helpers_require_this_bindings_anchor[other-key-maintain]",
    ),
    (
        "37 a different bundle in the same boot is not a reboot to repair",
        STORE + "_anchor_is_current",
        "if after_reboot and _across_reboot(anchor.bundle, opened.bundle_identity):",
        "if True:",
        S + "test_offline_helpers_require_this_bindings_anchor[other-bundle-activate]",
    ),
    (
        "38 the withdrawal record's schema version is checked",
        STORE + "_withdrawal",
        'or body["schema_version"] != 1',
        "or False",
        S + "test_activation_refuses_a_malformed_withdrawal_record[schema-2]",
    ),
    (
        "39 the withdrawal record's shape is exact",
        STORE + "_withdrawal",
        'set(body) != {"schema_version", "key", "generation_floor"}',
        "False",
        S + "test_activation_refuses_a_malformed_withdrawal_record[extra-key]",
    ),
    (
        "40 activation refuses a non-generation before filesystem entry",
        STORE + "activate_offline",
        "type(generation) is not int or generation < 1",
        "False",
        S + "test_activation_refuses_a_non_generation_before_filesystem_entry[bool]",
    ),
    (
        "41 activation accepts only the sealed identity contract",
        STORE + "activate_offline",
        "or not isinstance(qualified, NativeOperatorStoreIdentityV1)",
        "or False",
        S + "test_activation_refuses_a_look_alike_of_the_sealed_identity",
    ),
    (
        "42 a re-anchor requires the boot to have changed",
        STORE + "_across_reboot",
        "anchored.boot_id != live.boot_id",
        "True",
        S + "test_maintenance_re_anchors_only_the_same_physical_bundle[same-boot]",
    ),
    *(
        (
            f"{number} a re-anchor requires an equal {field}",
            STORE + "_across_reboot",
            f"and anchored.{field} == live.{field}",
            "and True",
            S + f"test_maintenance_re_anchors_only_the_same_physical_bundle[{field}]",
        )
        for number, field in enumerate(
            ("handle_type", "handle_hex", "dev", "ino", "mode", "uid", "nlink"), start=43,
        )
    ),
    (
        "50 maintenance re-anchors the same bundle after a reboot",
        MAINTAIN,
        '_replace_metadata(opened.bundle_fd, "anchor.json", anchor_raw)',
        "pass",
        S + "test_after_a_reboot_only_maintenance_restores_the_binding",
    ),
    (
        "51 maintenance re-anchors only after the withdrawal is recorded",
        MAINTAIN,
        "            _withdrawal(raw)\n"
        '            _replace_metadata(opened.bundle_fd, "active.json", raw)\n'
        + REANCHOR,
        REANCHOR
        + "            _withdrawal(raw)\n"
        '            _replace_metadata(opened.bundle_fd, "active.json", raw)\n',
        S + "test_a_failed_re_anchor_leaves_the_withdrawal_and_a_rerun_completes",
    ),
    (
        "52 the reboot decision is made again under the lock",
        MAINTAIN,
        "anchored = _anchor_is_current(opened, key, after_reboot=True)",
        'anchored = _anchor(_read_metadata(opened, "anchor.json")).bundle'
        " == opened.bundle_identity",
        S + "test_an_anchor_substituted_during_the_lock_wait_is_refused_under_the_lock",
    ),
    (
        "53 publication refuses a lock replaced across a reboot",
        STORE + "publish_descriptor_offline",
        "if _same_object_across_boots(old.store, descriptor.store) and (",
        "if False and (",
        S + "test_a_lock_replaced_across_a_reboot_is_refused_under_the_same_store"
        "[replaced-publish]",
    ),
    (
        "54 activation refuses a lock replaced across a reboot",
        STORE + "_check_descriptor",
        "if _same_object_across_boots(old.store, descriptor.store) and (",
        "if False and (",
        S + "test_a_lock_replaced_across_a_reboot_is_refused_under_the_same_store"
        "[replaced-activate]",
    ),
    # --- N4 maintenance-held launches (M8-N4-state-review.md, section 5) ---
    (
        "N4-M1 a maintenance check requires the same floor",
        STORE + "StoreMaintenance.check",
        "if withdrawal.generation_floor != self.generation_floor:",
        "if False:",
        K + "test_a_maintenance_check_refuses_once_its_selection_or_objects_moved[other-floor]",
    ),
    (
        "N4-M2 a maintenance check re-proves the objects",
        STORE + "StoreMaintenance.check",
        "_require_same_objects(current, self._opened)",
        "pass",
        K + "test_a_maintenance_check_refuses_once_its_selection_or_objects_moved[substituted]",
    ),
    (
        "N4-M3 a maintenance check requires this key's withdrawal",
        STORE + "StoreMaintenance.check",
        "withdrawal = _current_withdrawal(current, self._key)",
        "withdrawal = _Withdrawal(self._key, self.generation_floor)",
        K + "test_a_maintenance_check_refuses_once_its_selection_or_objects_moved[activated]",
    ),
    (
        "N4-M4 a closed maintenance checks nothing",
        STORE + "StoreMaintenance.check",
        "if self.closed or self._opened.closed:",
        "if False:",
        K + "test_a_maintenance_check_is_positive_inside_the_context_and_never_a_binding",
    ),
    # --- N4 inherited maintenance (host-runtime interface item 4) ---
    (
        "N4-M5 the inherited descriptor is the bundle's retained lock",
        INHERIT,
        "if _identity(lock_fd) != opened.lock_identity:",
        "if False:",
        I + "test_custody_that_is_not_proven_refuses_before_anything_is_exposed[wrong-identity]",
    ),
    (
        "N4-M6 the inherited description must hold the lock",
        INHERIT,
        "_require_inherited_hold(lock_fd, opened.lock_identity, parent)",
        "pass",
        I + "test_custody_that_is_not_proven_refuses_before_anything_is_exposed[stranger]",
    ),
    (
        "N4-M7 the anchor names this bundle",
        INHERIT,
        "_anchor_is_current(opened, key, after_reboot=False)",
        "pass",
        I + "test_custody_that_is_not_proven_refuses_before_anything_is_exposed[other-anchor]",
    ),
    (
        "N4-M8 this key's withdrawal is the current state",
        INHERIT,
        "withdrawal = _current_withdrawal(opened, key)",
        "withdrawal = _Withdrawal(key, generation_floor)",
        I + "test_custody_that_is_not_proven_refuses_before_anything_is_exposed[active]",
    ),
    (
        "N4-M9 the recorded floor is compared",
        INHERIT,
        "if not withdrawal.generation_floor == highest == generation_floor:",
        "if not highest == generation_floor:",
        I + "test_custody_that_is_not_proven_refuses_before_anything_is_exposed[record-floor]",
    ),
    (
        "N4-M10 the inventory's highest generation is compared",
        INHERIT,
        "if not withdrawal.generation_floor == highest == generation_floor:",
        "if not withdrawal.generation_floor == generation_floor:",
        I + "test_custody_that_is_not_proven_refuses_before_anything_is_exposed"
        "[inventory-floor]",
    ),
    (
        "N4-M11 the helper's floor is compared",
        INHERIT,
        "if not withdrawal.generation_floor == highest == generation_floor:",
        "if not withdrawal.generation_floor == highest:",
        I + "test_the_helpers_floor_must_be_the_recorded_one[higher]",
    ),
    (
        "N4-M12 the helper's floor is an integer",
        INHERIT,
        "or type(generation_floor) is not int or generation_floor < 0",
        "or False",
        I + "test_malformed_custody_arguments_refuse_before_any_open",
    ),
    (
        "N4-M13 exactly one lock is reported",
        HOLD,
        "if len(locks) == 1 else None",
        "if locks else None",
        I + "test_custody_that_is_not_proven_refuses_before_anything_is_exposed[two-locks]",
    ),
    (
        "N4-M14 the lock was taken by the parent",
        HOLD,
        "int(match[1]) != parent",
        "False",
        I + "test_custody_that_is_not_proven_refuses_before_anything_is_exposed[self-taken]",
    ),
    (
        "N4-M15 the lock is on the retained lock's inode",
        HOLD,
        "int(match[2]) != lock.ino",
        "False",
        I + "test_custody_that_is_not_proven_refuses_before_anything_is_exposed[other-inode]",
    ),
    (
        "N4-M16 the kernel report is bounded",
        HOLD,
        "if len(raw) > MAX_FDINFO_BYTES:",
        "if False:",
        I + "test_custody_that_is_not_proven_refuses_before_anything_is_exposed[oversized]",
    ),
    (
        "N4-M17 only an exclusive flock is a hold",
        HOLD,
        "_FLOCK_LINE.fullmatch(locks[0])",
        're.search(rb"([0-9]+) [0-9a-f]+:[0-9a-f]+:([0-9]+)", locks[0])',
        I + "test_custody_that_is_not_proven_refuses_before_anything_is_exposed[shared]",
    ),
    (
        "N4-M18 the lane runs as the service user and group",
        SPAWN,
        "user=uid, group=gid,",
        "user=None, group=None,",
        I + "test_the_helper_starts_the_lane_as_the_service_with_only_the_lock",
    ),
    (
        "N4-M19 the lane's supplementary groups are cleared",
        SPAWN,
        "extra_groups=[]",
        "extra_groups=None",
        I + "test_the_helper_starts_the_lane_as_the_service_with_only_the_lock",
    ),
    (
        "N4-M20 the lane's environment is the fixed one",
        SPAWN,
        "env=dict(LANE_ENVIRONMENT)",
        "env=None",
        I + "test_the_helper_starts_the_lane_as_the_service_with_only_the_lock",
    ),
    (
        "N4-M21 every other descriptor is closed",
        SPAWN,
        "close_fds=True",
        "close_fds=False",
        I + "test_the_helper_starts_the_lane_as_the_service_with_only_the_lock",
    ),
    (
        "N4-M22 exactly the lock is passed",
        SPAWN,
        "pass_fds=(withdrawn.lock_fd,)",
        "pass_fds=(withdrawn.lock_fd, 0)",
        I + "test_the_helper_starts_the_lane_as_the_service_with_only_the_lock",
    ),
    (
        "N4-M23 maintenance lasts until the lane exits",
        SPAWN,
        "return child.wait()",
        "return 0",
        I + "test_the_helper_starts_the_lane_as_the_service_with_only_the_lock",
    ),
    (
        "N4-M24 an interrupted helper stops the lane first",
        SPAWN,
        "child.kill()",
        "pass",
        I + "test_an_interrupted_helper_stops_the_lane_before_leaving_maintenance",
    ),
    (
        "N4-M25 the lane never runs as the root user",
        SPAWN,
        "if uid == 0 or gid == 0:",
        "if gid == 0:",
        I + "test_the_helper_never_starts_a_root_lane[root-user]",
    ),
    (
        "N4-M26 the lane never runs as the root group",
        SPAWN,
        "if uid == 0 or gid == 0:",
        "if uid == 0:",
        I + "test_the_helper_never_starts_a_root_lane[root-group]",
    ),
    (
        "N4-M28 a closed maintenance creates no credential",
        STORE + "StoreMaintenance.create_credential",
        "if self.closed or self._opened.closed:",
        "if False:",
        I + "test_a_closed_maintenance_creates_nothing",
    ),
    (
        "N4-M29 the first credential is exactly 0600 whatever the umask",
        STORE + "StoreMaintenance.create_credential",
        "_fchmod(fd, _CREDENTIAL_MODE)",
        "pass",
        I + "test_maintenance_creates_the_first_credential_exclusively",
    ),
    (
        "N4-M30 the store directory is synced after the create",
        STORE + "StoreMaintenance.create_credential",
        "os.fsync(self._opened.store_fd)",
        "pass",
        I + "test_maintenance_creates_the_first_credential_exclusively",
    ),
    (
        "N4-M27 only the helper sets the store, key and custody",
        STORE + "main",
        "argument == name or argument.startswith(name + \"=\")",
        "False",
        I + "test_only_the_helper_sets_the_store_the_key_and_the_custody",
    ),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
