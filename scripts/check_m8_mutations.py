"""M8 policy, identity, materialization and plan-manifest proofs; no Linux claim.

Run with ``uv run python scripts/check_m8_mutations.py``. The shared runner
mutates only child-process code objects and requires an assertion failure.
"""

from _mutations import run

POLICY = "constructicon.core.executor:ExecutorProfile.grant_faults"
COHERENCE = "constructicon.runtime.registry:CapabilityDescriptor.executor_incoherence"
CORE = "tests/core/test_executor_policy.py::"
API = "tests/api/test_executor_admission.py::"
LIFECYCLE = "tests/runtime/test_materialization.py::"
CONTROL = "tests/runtime/test_materialization_control.py::"
CLEANUP = "tests/runtime/test_cleanup_obligations.py::"
MANIFEST = "scripts.regen_plan_manifest:main"
PLAN_TESTS = "tests/test_regen_plan_manifest.py::"
MAINTENANCE = "constructicon.substrate.gates.maintenance:"
VECTOR_TESTS = "tests/substrate/test_maintenance_vectors.py::"
EVIDENCE_MODULE = "constructicon.substrate.journal.maintenance_evidence:"
EVIDENCE_TESTS = "tests/substrate/journal/test_maintenance_evidence.py::"
DIAGNOSTIC_MODULE = "constructicon.substrate.journal.maintenance_diagnostic:"
DIAGNOSTIC_TESTS = "tests/substrate/journal/test_maintenance_diagnostic.py::"
VM_ADDRESS_MODULE = "scripts.m8_vm_address:"
VM_ADDRESS_TESTS = "tests/test_m8_vm_address.py::"
WRITER = "constructicon.api.plan_manifest_application:maintenance_writer"
WRITER_TESTS = "tests/api/test_plan_manifest_application.py::"

MUTANTS = (
    *(
        ("installed diagnostic recognizes " + reason, DIAGNOSTIC_MODULE + "_journal",
         '_FAILURES.get(error, "unknown")',
         '_FAILURES.get(None if error == ' + repr(message) + ' else error, "unknown")',
         DIAGNOSTIC_TESTS
         + "test_reader_keeps_grouped_history_and_classifies_only_exact_capture_reasons")
        for reason, message in (
            ("capture-return", "maintenance captured candidate differs from capture return"),
            ("capture-unchanged", "maintenance captured candidate equals the pinned base"),
            ("capture-repository", "maintenance captured candidate has another repository"),
            ("capture-paths", "maintenance captured candidate has path restrictions"),
            ("capture-base", "maintenance captured candidate has another comparison base"),
        )
    ),
    *(
        ("maintenance capture preserves " + name, WRITER, condition, "if False:",
         WRITER_TESTS + "test_writer_capture_guards_keep_acceptance_and_first_failure["
         + name + "]")
        for name, condition in (
            ("commit", "if candidate.commit != captured:"),
            ("base", "if candidate.commit == request.base_commit:"),
            ("repository", "if candidate.repository != request.repository:"),
            ("paths", "if candidate.paths:"),
            ("comparison-base", "if candidate.diff_against != request.base_commit:"),
        )
    ),
    ("maintenance capture diagnoses first comparison before base", WRITER,
     'if candidate.commit != captured:\n'
     '        raise ContractViolation('
     '"maintenance captured candidate differs from capture return")\n'
     '    if candidate.commit == request.base_commit:\n'
     '        raise ContractViolation("maintenance captured candidate equals the pinned base")',
     'if candidate.commit == request.base_commit:\n'
     '        raise ContractViolation("maintenance captured candidate equals the pinned base")\n'
     '    if candidate.commit != captured:\n'
     '        raise ContractViolation('
     '"maintenance captured candidate differs from capture return")',
     WRITER_TESTS + "test_writer_capture_guards_keep_acceptance_and_first_failure[commit-first]"),
    ("maintenance capture diagnosis never includes candidate values", WRITER,
     'ContractViolation("maintenance captured candidate equals the pinned base")',
     'ContractViolation(str(candidate))',
     WRITER_TESTS + "test_writer_capture_guards_keep_acceptance_and_first_failure[base]"),
    ("VM address requires exact identity", VM_ADDRESS_MODULE + "_parse",
     'if value["name"] != VM_NAME:', "if False:",
     VM_ADDRESS_TESTS + "test_source_refusals_are_closed"),
    ("VM address requires fresh Running state", VM_ADDRESS_MODULE + "_parse",
     'if value["state"] != "Running":', "if False:",
     VM_ADDRESS_TESTS + "test_source_refusals_are_closed"),
    ("VM address refuses ambiguous suitable targets", VM_ADDRESS_MODULE + "_parse",
     "if len(suitable) != 1:", "if False:",
     VM_ADDRESS_TESTS + "test_source_refusals_are_closed"),
    ("VM address deduplicates after filtering", VM_ADDRESS_MODULE + "_parse",
     "if len(suitable) != 1:", "if len(suitable) != 1 or len(addresses) != 1:",
     VM_ADDRESS_TESTS + "test_filter_then_deduplicate"),
    ("VM address selects only RFC1918 IPv4", VM_ADDRESS_MODULE + "_parse",
     "parsed in network for network in PRIVATE_NETWORKS", "True for network in PRIVATE_NETWORKS",
     VM_ADDRESS_TESTS + "test_source_refusals_are_closed"),
    ("VM address post-capture source bound binds", VM_ADDRESS_MODULE + "discover",
     "if len(completed.stdout) > MAX_SOURCE_BYTES:", "if False:",
     VM_ADDRESS_TESTS + "test_post_capture_source_bound_binds"),
    ("VM address nonzero query exit refuses", VM_ADDRESS_MODULE + "discover",
     "if completed.returncode != 0:", "if False:",
     VM_ADDRESS_TESTS + "test_process_faults_refuse_without_retry_or_private_details"),
    ("VM address any query stderr refuses", VM_ADDRESS_MODULE + "discover",
     "if completed.stderr:", "if False:",
     VM_ADDRESS_TESTS + "test_process_faults_refuse_without_retry_or_private_details"),
    ("VM address closes query stdin", VM_ADDRESS_MODULE + "discover",
     "stdin=subprocess.DEVNULL", "stdin=None",
     VM_ADDRESS_TESTS + "test_acceptance_uses_only_fixed_argv_and_closed_stdin"),
    ("VM address query never uses an outer shell", VM_ADDRESS_MODULE + "discover",
     "shell=False", "shell=True",
     VM_ADDRESS_TESTS + "test_acceptance_uses_only_fixed_argv_and_closed_stdin"),
    ("VM address uses the fixed PowerShell executable", VM_ADDRESS_MODULE + "powershell_argv",
     "[POWERSHELL,", '["powershell.exe",',
     VM_ADDRESS_TESTS + "test_acceptance_uses_only_fixed_argv_and_closed_stdin"),
    ("VM address retains its bounded process timeout", VM_ADDRESS_MODULE + "discover",
     "timeout=remaining", "timeout=None",
     VM_ADDRESS_TESTS + "test_acceptance_uses_only_fixed_argv_and_closed_stdin"),
    ("VM address readiness waits through IPv6-only observations", VM_ADDRESS_MODULE + "discover",
     'if report.get("reason") != "no_suitable_address":', "if True:",
     VM_ADDRESS_TESTS + "test_ipv6_pending_then_dhcp_accepts_in_one_invocation"),
    ("VM address readiness never waits through invalid observations", VM_ADDRESS_MODULE + "discover",
     'if report.get("reason") != "no_suitable_address":',
     'if report.get("status") == "ok":',
     VM_ADDRESS_TESTS + "test_pending_then_invalid_observation_stops_immediately"),
    ("VM address readiness has at most sixty observations", VM_ADDRESS_MODULE + "discover",
     "range(MAX_OBSERVATIONS)", "range(MAX_OBSERVATIONS + 1)",
     VM_ADDRESS_TESTS + "test_observation_limit_binds_even_when_clock_does_not_advance"),
    ("VM address checks deadline before each query", VM_ADDRESS_MODULE + "discover",
     "if remaining <= 0:\n            break\n        try:",
     "if False:\n            break\n        try:",
     VM_ADDRESS_TESTS + "test_deadline_checked_before_query_and_sleep_is_remaining_bounded"),
    ("VM address refuses late completion before parsing", VM_ADDRESS_MODULE + "discover",
     "if time.monotonic() >= deadline:", "if False:",
     VM_ADDRESS_TESTS + "test_late_query_is_not_parsed"),
    ("VM address never accepts when parsing exhausts deadline", VM_ADDRESS_MODULE + "discover",
     'if remaining <= 0:\n            break\n        if report.get("reason")',
     'if False:\n            break\n        if report.get("reason")',
     VM_ADDRESS_TESTS + "test_deadline_expiring_during_parse_cannot_accept"),
    ("VM address child timeout uses the remaining single budget", VM_ADDRESS_MODULE + "discover",
     "timeout=remaining", "timeout=READINESS_SECONDS",
     VM_ADDRESS_TESTS + "test_query_timeout_shrinks_to_remaining_budget"),
    ("VM address sleep cannot exceed remaining budget", VM_ADDRESS_MODULE + "discover",
     "time.sleep(min(1, remaining))", "time.sleep(1)",
     VM_ADDRESS_TESTS + "test_deadline_checked_before_query_and_sleep_is_remaining_bounded"),
    ("VM address sleep cannot exceed one second", VM_ADDRESS_MODULE + "discover",
     "time.sleep(min(1, remaining))", "time.sleep(remaining)",
     VM_ADDRESS_TESTS + "test_ipv6_pending_then_dhcp_accepts_in_one_invocation"),
    ("VM address exhaustion does not assert an absent address", VM_ADDRESS_MODULE + "discover",
     'return _refused("readiness_exhausted")', 'return _refused("no_suitable_address")',
     VM_ADDRESS_TESTS + "test_pending_predicate_is_distinct_from_public_exhaustion"),
    ("safe original read bits remain acceptable behind private containers", EVIDENCE_MODULE + "_custody",
     "and not info.st_mode & 0o022", "and not info.st_mode & (0o077 if private else 0o022)",
     EVIDENCE_TESTS + "test_owner_and_private_mode_predicate_is_closed"),
    ("destination parent is ancestry not a private capture container", EVIDENCE_MODULE + "capture_evidence",
     "chains.append((destination.parent, False, _directories(destination.parent, private=False)))",
     "chains.append((destination.parent, True, _directories(destination.parent, private=True)))",
     EVIDENCE_TESTS + "test_safe_destination_ancestry_is_distinct_from_private_containers"),
    ("source and capture containers still require exact private mode", EVIDENCE_MODULE + "_directories",
     'if private and entry == path and stat.S_IMODE(info.st_mode) != 0o700 and os.name == "posix":',
     "if False:", EVIDENCE_TESTS + "test_directory_mode_boundary_preserves_private_source_and_capture_guards"),
    ("protected originals remain service-owned not merely trusted-owner", EVIDENCE_MODULE + "_custody",
     "info.st_uid == uid if private else info.st_uid in {0, uid}", "info.st_uid in {0, uid}",
     EVIDENCE_TESTS + "test_owner_and_private_mode_predicate_is_closed"),
    ("completed callback responses are positive", DIAGNOSTIC_MODULE + "_attempt",
     "or callbacks.responses_complete)", "or True)",
     DIAGNOSTIC_TESTS + "test_successful_attempt_cannot_claim_incomplete_callback_responses"),
    ("invalid identity cannot claim a capture", DIAGNOSTIC_MODULE + "main",
     '_require(re.fullmatch(r"run-[0-9a-f]{32}", args.run_id) is not None)', "pass",
     DIAGNOSTIC_TESTS + "test_invalid_run_identity_refuses_before_claiming_capture_destination"),
    ("WAL included in fixed capture", EVIDENCE_MODULE + "capture_evidence",
     "paths = {name: root / name for name in NAMES}",
     'paths = {name: root / name for name in NAMES if name != "maintenance.sqlite-wal"}',
     EVIDENCE_TESTS + "test_fixed_capture_preserves_originals_and_records_absences"),
    ("source byte limit before capture", EVIDENCE_MODULE + "_source",
     "if not 0 <= info.st_size <= MAX_FILE_BYTES:", "if False:",
     EVIDENCE_TESTS + "test_real_bounds_bind[file]"),
    ("aggregate source byte limit", EVIDENCE_MODULE + "capture_evidence",
     "if sum(info.st_size for info in initial.values() if info is not None) > MAX_TOTAL_BYTES:",
     "if False:", EVIDENCE_TESTS + "test_real_bounds_bind[total]"),
    ("hardlinked evidence refused", EVIDENCE_MODULE + "_source",
     "info.st_nlink != 1", "False",
     EVIDENCE_TESTS + "test_unsafe_fixed_source_refuses[hardlink-maintenance.sqlite]"),
    ("source second byte comparison", EVIDENCE_MODULE + "capture_evidence",
     '_read(path, info, None) != files[name].get("sha256")', "False",
     EVIDENCE_TESTS + "test_final_source_bytes_are_compared_even_if_metadata_repeats"),
    ("absence is observed not omitted", EVIDENCE_MODULE + "capture_evidence",
     'files[name] = {"present": False} if info is None else {',
     'files[name] = {} if info is None else {',
     EVIDENCE_TESTS + "test_missing_database_and_command_report_are_explicit_facts"),
    ("pending attempt retained", EVIDENCE_MODULE + "capture_evidence",
     "paths = {name: root / name for name in NAMES}",
     'paths = {name: root / name for name in NAMES if not name.endswith(".next")}',
     EVIDENCE_TESTS + "test_pending_attempt_is_preserved_not_promoted"),
    ("WAL is not hidden by immutable", DIAGNOSTIC_MODULE + "_connection",
     '"?mode=ro"', '"?mode=ro&immutable=1"',
     DIAGNOSTIC_TESTS + "test_real_committed_wal_only_failure_is_observed"),
    ("event bound binds", DIAGNOSTIC_MODULE + "_journal",
     "_require(len(rows) <= MAX_EVENTS)", "pass",
     DIAGNOSTIC_TESTS + "test_journal_damage_or_bound_exhaustion_refuses_instead_of_reporting_missing[event-bound]"),
    ("attempt authorization matches", DIAGNOSTIC_MODULE + "_attempt",
     '_require(record["authorization_id"] == authorization_id and record["run_id"] == run_id)',
     "pass", DIAGNOSTIC_TESTS + "test_identity_mismatch_and_pending_record_never_promoted"),
    ("command false is boolean", DIAGNOSTIC_MODULE + "_command",
     ' and type(record["accepted"]) is bool', "",
     DIAGNOSTIC_TESTS + "test_command_report_preserves_checker_ambiguity_without_raw_text[record3-None]"),
    ("whole report is bounded", DIAGNOSTIC_MODULE + "analyze_snapshot",
     '_require(len(json.dumps(report).encode("utf-8")) <= MAX_REPORT_BYTES)', "pass",
     DIAGNOSTIC_TESTS + "test_output_bound_binds_and_orphan_sidecars_are_not_silently_ignored"),
    ("query instruction budget binds", DIAGNOSTIC_MODULE + "_connection",
     "return int(steps > MAX_SQL_STEPS)", "return 0",
     DIAGNOSTIC_TESTS + "test_sql_budget_binds_and_connection_refuses_writes"),
    ("unknown errors stay closed", DIAGNOSTIC_MODULE + "_journal",
     '_FAILURES.get(error, "unknown")', "error",
     DIAGNOSTIC_TESTS + "test_selected_failure_facts_and_attempt_are_private_and_originals_unchanged"),
    ("checkpoints are positive observations", DIAGNOSTIC_MODULE + "_journal",
     'nodes[name]["checkpoint"] = "validated"',
     'nodes[name]["checkpoint"] = "missing"',
     DIAGNOSTIC_TESTS + "test_writer_checkpoint_and_failed_gate_attestation_are_distinct"),
    (
        "maintenance Git seals its child creation mask",
        "constructicon.api._maintenance_source:git",
        "creation_mask=0o077", "creation_mask=None",
        "tests/api/test_maintenance_entry.py::"
        "test_maintenance_git_requests_private_child_creation_without_global_mask",
    ),
    (
        "private Git creation mask reaches the POSIX child",
        "constructicon.substrate.git.process:GitProcess.run",
        'umask=creation_mask if os.name == "posix" and creation_mask is not None else -1',
        "umask=-1",
        "tests/substrate/test_git_process.py::"
        "test_private_creation_mask_reaches_only_the_posix_child[private]",
    ),
    (
        "maintenance authority configuration retains private future writes",
        "constructicon.api._maintenance_source:prepare_source",
        'write_once(root / "authority.git/config", CONFIG)',
        'write_once(root / "authority.git/config", '
        'CONFIG.replace(b"\\tsharedRepository = 0600\\n", b""))',
        "tests/api/test_maintenance_entry.py::"
        "test_prepare_accepts_only_new_reviewed_bundle_and_affirms_consumer",
    ),
    (
        "preflight failure preserves its actual stage",
        "constructicon.api.maintenance_entry:_command",
        "with _failure_stage(_PreflightStage.ASSEMBLY):",
        "with _failure_stage(_PreflightStage.SOURCE):",
        "tests/api/test_maintenance_entry.py::"
        "test_cli_preflight_failure_publishes_only_actual_bounded_stage[assembly]",
    ),
    (
        "stage diagnostics leave other command failure bytes unchanged",
        "constructicon.api.maintenance_entry:main",
        'if args.command == "preflight":', "if True:",
        "tests/api/test_maintenance_entry.py::test_other_cli_failure_bytes_remain_unchanged[run]",
    ),
    (
        "preflight failure never publishes private exception text",
        "constructicon.api.maintenance_entry:main",
        '"accepted": False, "error": "maintenance command refused or incomplete",',
        '"accepted": False, "error": str(error),',
        "tests/api/test_maintenance_entry.py::"
        "test_cli_preflight_failure_publishes_only_actual_bounded_stage[unknown]",
    ),
    (
        "maintenance init applies private policy before creating Git metadata",
        "constructicon.api._maintenance_source:prepare_source",
        '"--shared=0600", ', "",
        "tests/api/test_maintenance_entry.py::"
        "test_prepare_accepts_only_new_reviewed_bundle_and_affirms_consumer",
    ),
    *(
        (
            "maintenance entry binds " + label,
            "constructicon.api.maintenance_entry:require_maintenance_attempt",
            before, "True",
            "tests/api/test_maintenance_entry.py::"
            "test_entry_refuses_mismatched_authority_before_startup[" + label + "]",
        )
        for label, before in (
            ("request", "authorization.request == resources.request"),
            ("application", "authorization.application_revision == maintenance_application_revision()"),
            ("graph", "authorization.source_graph_hash == source_graph_hash_for(graph)"),
            ("executor", "authorization.revision == str(executor.identity.revision)"),
            ("journal", "journal_path == Path(journal._db_path).resolve()"),
        )
    ),
    *(
        (
            "maintenance recovery proves retained " + label,
            "constructicon.api.maintenance_entry:require_maintenance_attempt",
            before, "False",
            "tests/api/test_maintenance_entry.py::"
            "test_retained_run_inputs_and_manifest_are_checked_before_startup",
        )
        for label, before in (
            ("inputs", "canonical_json(journal.run_inputs(record.run_id)) != canonical_json(inputs)"),
            ("manifest", "canonical_json(parse_manifest_json(raw)) != canonical_json(expected)"),
        )
    ),
    (
        "maintenance source configuration is fixed rather than merely self-hashed",
        "constructicon.api._maintenance_source:inspect_source",
        "config != CONFIG or hashlib.sha256(config).hexdigest() != pin.config_sha256",
        "False",
        "tests/api/test_maintenance_entry.py::"
        "test_prepare_accepts_only_new_reviewed_bundle_and_affirms_consumer",
    ),
    (
        "maintenance reviewed bundle digest precedes Git",
        "constructicon.api._maintenance_source:prepare_source",
        "hashlib.sha256(raw).hexdigest() != bundle_sha256", "False",
        "tests/api/test_maintenance_entry.py::test_prepare_checks_digest_before_git_or_root_creation",
    ),
    *(
        (label, target, before, "if False:", test)
        for label, target, before, test in (
            (
                "maintenance epoch wire is an exact integer",
                "constructicon.core.maintenance:MaintenanceAttemptAuthorization._exact_epoch",
                "if type(value) is not int or value != 1:",
                "tests/core/test_maintenance_authorization.py::"
                "test_shape_refuses_missing_weak_or_foreign_authority",
            ),
            (
                "maintenance and qualification authority remain exclusive",
                "constructicon.substrate.executors.codex:CodexOperatorProvider.__init__",
                "if qualification is not None and maintenance is not None:",
                "tests/substrate/test_codex_maintenance_authorization.py::"
                "test_maintenance_and_qualification_are_exclusive_and_not_interchangeable",
            ),
            (
                "maintenance attempt records its distinct purpose",
                "constructicon.substrate.executors.codex:CodexOperatorProvider.acquire",
                "if self.maintenance is not None:",
                "tests/substrate/test_codex_maintenance_authorization.py::"
                "test_one_maintenance_turn_records_purpose_and_completed_dispatch",
            ),
            (
                "maintenance attempt is exclusive before handle publication",
                "constructicon.substrate.executors.codex:CodexOperatorProvider.acquire",
                "if authorization is not None and authorization.attempt_record is not None:",
                "tests/substrate/test_codex_maintenance_authorization.py::"
                "test_a_preexisting_attempt_refuses_before_a_handle_exists",
            ),
            (
                "maintenance expiry gates both sides of durable intent",
                "constructicon.substrate.executors.codex:CodexOperatorHandle._expired",
                "if maintenance is not None and datetime.now(UTC) >= maintenance.not_after:",
                "tests/substrate/test_codex_maintenance_authorization.py::"
                "test_expiry_on_either_side_of_intent_dispatches_nothing_but_cleanup_still_works",
            ),
        )
    ),
    (
        "maintenance retains the fixed native deadline",
        "constructicon.core.maintenance:MaintenanceAttemptAuthorization._write_grants",
        "or grants.timeout_s != 300", "or False",
        "tests/core/test_maintenance_authorization.py::test_grants_keep_the_bounded_write_shape",
    ),
    *(
        (
            "maintenance acquisition proves " + label,
            "constructicon.core.maintenance:MaintenanceAttemptAuthorization.acquisition_faults",
            before,
            after,
            "tests/core/test_maintenance_authorization.py::test_every_other_acquisition_refuses",
        )
        for label, before, after in (
            ("run", "run_id == self.run_id", "True"),
            ("invocation", "path == ExecutionPath(scope=self.scope)", "True"),
            ("binding", "binding == self.binding", "True"),
            ("graph", "source_graph_hash == self.source_graph_hash", "True"),
            ("capability", "capability_id == self.capability_id", "True"),
            ("revision", "revision == self.revision", "True"),
            ("store", "operator_binding_digest == self.operator_binding_digest", "True"),
            ("grants", "canonical_json(grants) == canonical_json(self.grants)", "True"),
            ("epoch", "type(epoch) is int and epoch == 1", "True"),
            ("expiry", "now < self.not_after", "True"),
        )
    ),
    (
        "maintenance target source stays pinned",
        MAINTENANCE + "render_unittest",
        "or hashlib.sha256(target_source).hexdigest() != trusted_target_sha256",
        "or False",
        VECTOR_TESTS + "test_renderer_is_deterministic_and_revalidates_constructor_inputs",
    ),
    (
        "maintenance runs every fixed mutant",
        MAINTENANCE + "run_vectors",
        "for name, _, _ in _MUTANTS:",
        "for name, _, _ in ():",
        VECTOR_TESTS + "test_permitting_exam_runs_every_case_and_kills_each_named_mutant",
    ),
    (
        "maintenance requires baseline coverage",
        MAINTENANCE + "run_vectors",
        "if not required <= coverage:",
        "if False:",
        VECTOR_TESTS + "test_empty_or_refusal_only_suites_cannot_qualify",
    ),
    (
        "maintenance candidate cannot supply expectations",
        MAINTENANCE + "parse_vectors",
        'and set(case) == {"kind", "path"}',
        "",
        VECTOR_TESTS + "test_closed_wire_refuses_bad_shapes_and_candidate_expectations",
    ),
    (
        "maintenance preserves valid compact ASCII vectors during revalidation",
        MAINTENANCE + "_validated",
        'ensure_ascii=False, separators=(",", ":")',
        "ensure_ascii=True",
        VECTOR_TESTS + "test_compact_ascii_vectors_remain_accepted_when_renderer_revalidates",
    ),
    (
        "maintenance application rejects intermediate candidate history",
        "constructicon.api.plan_manifest_application:derive_maintenance_result",
        "if candidate_parents != [request.base_commit.encode()]:",
        "if False:",
        "tests/api/test_plan_manifest_application.py::"
        "test_application_refuses_history_despite_passing_generic_tree_gate",
    ),
    *(
        (name, POLICY, before, after, CORE + test)
        for name, before, after, test in (
            (
                "posture",
                "if grants.posture not in self.postures:",
                "if False:",
                "test_adapter_and_profile_share_every_grant_refusal",
            ),
            (
                "mechanical posture",
                "elif not self.isolation.satisfies(grants.posture):",
                "elif False:",
                "test_complete_policy_requires_every_physical_declaration",
            ),
            (
                "exact tools",
                "if tuple(sorted(set(grants.allowed_tools))) not in policy.tool_sets:",
                "if False:",
                "test_adapter_and_profile_share_every_grant_refusal",
            ),
            (
                "network selection",
                "if grants.network not in policy.network_modes:",
                "if False:",
                "test_adapter_and_profile_share_every_grant_refusal",
            ),
            (
                "network enforcement",
                "if not self.isolation.network_enforced:",
                "if False:",
                "test_complete_policy_requires_every_physical_declaration",
            ),
            (
                "environment",
                "if unsupported:",
                "if False:",
                "test_adapter_and_profile_share_every_grant_refusal",
            ),
            (
                "effort",
                "if grants.effort is not None and grants.effort not in self.accepted_efforts:",
                "if False:",
                "test_adapter_and_profile_share_every_grant_refusal",
            ),
            (
                "explicit model",
                'if selection.kind == "explicit" and (',
                "if False and (",
                "test_adapter_and_profile_share_every_grant_refusal",
            ),
        )
    ),
    (
        "adapter uses the one policy",
        "constructicon.substrate.executors.fake:FakeExecutor.validate_grants",
        "return self._profile.grant_faults(grants)",
        "return ()",
        CORE + "test_adapter_and_profile_share_every_grant_refusal",
    ),
    (
        "legacy absence",
        "constructicon.core.executor:ExecutorProfile._serialize",
        'value.pop("grant_policy", None)',
        "pass",
        CORE + "test_legacy_profile_keeps_its_exact_bytes_and_incompleteness",
    ),
    (
        "content identity",
        "constructicon.core.executor:ExecutorLaunchIdentity.revision",
        '"identity": self.model_dump(mode="json"),',
        '"identity": self.profile.name,',
        CORE + "test_each_launch_fact_changes_revision",
    ),
    (
        "shared law identity",
        "constructicon.core.executor:ExecutorLaunchIdentity.revision",
        '"law": EXECUTOR_LAW_REVISION,',
        '"law": "unversioned",',
        CORE + "test_shared_law_is_bound_without_a_factory_remembering_to_stamp_it",
    ),
    (
        "complete descriptor cannot hide",
        COHERENCE,
        '"an executor provider requires a complete descriptor profile" if provider else None',
        "None",
        API + "test_assembly_refuses_incoherent_or_hidden_executor_authority",
    ),
    (
        "leased identity",
        COHERENCE,
        'if self.kind != "executor" or not self.leased:',
        'if self.kind != "executor":',
        API + "test_assembly_refuses_incoherent_or_hidden_executor_authority",
    ),
    (
        "exact provider profile",
        COHERENCE,
        "if canonical_json(identity.profile) != canonical_json(profile):",
        "if False:",
        API + "test_assembly_compares_the_actual_complete_profile_and_provider_contract",
    ),
    (
        "actual provider revision",
        COHERENCE,
        "if identity.revision != self.revision:",
        "if False:",
        API + "test_assembly_refuses_incoherent_or_hidden_executor_authority",
    ),
    (
        "missing provider",
        "constructicon.runtime.registry:CapabilityDescriptor.executor_unavailability",
        'return ("no executor provider is assembled",)',
        "return ()",
        API + "test_known_unavailable_provider_is_described_and_refused",
    ),
    (
        "cached availability",
        "constructicon.runtime.registry:CapabilityDescriptor.executor_unavailability",
        "return capability.unavailable_reasons",
        "return ()",
        API + "test_cached_availability_change_is_observed_without_reassembly",
    ),
    (
        "admission calls the pure law",
        "constructicon.runtime.validator:_register_atomic",
        "for reason in profile.grant_faults(node_grants):",
        "for reason in ():",
        API + "test_public_admission_uses_the_shared_pure_grant_predicate",
    ),
    (
        "materialization is awaited",
        "constructicon.runtime.walker:Walker._invoke",
        "await acquisition.materialize()",
        "pass",
        LIFECYCLE + "test_materialization_observes_its_durable_row_before_resource_exposure",
    ),
    (
        "durable row precedes materialization",
        "constructicon.runtime.walker:Walker._acquire_invocation_capability",
        "self._journal.record_capability_lease(lease, durable)",
        "if acquisition.materialize is not None:\n"
        "            await acquisition.materialize()\n"
        "        self._journal.record_capability_lease(lease, durable)",
        LIFECYCLE + "test_materialization_observes_its_durable_row_before_resource_exposure",
    ),
    (
        "cleanup enrollment precedes materialization",
        "constructicon.runtime.walker:Walker._invoke",
        "acquired.append((capability, acquisition))\n"
        "                if acquisition.materialize is not None:\n"
        "                    await acquisition.materialize()\n"
        "                    self._check_run_control(lease, lost)",
        "if acquisition.materialize is not None:\n"
        "                    await acquisition.materialize()\n"
        "                    self._check_run_control(lease, lost)\n"
        "                acquired.append((capability, acquisition))",
        LIFECYCLE + "test_materialization_failure_discards_the_enrolled_acquisition",
    ),
    (
        "inert close writes no external fact",
        "tests.executorworld:FakeExecutorProvider.close",
        "if handle.entered:",
        "if True:",
        LIFECYCLE + "test_recording_failure_keeps_close_inert_and_forbids_late_entry",
    ),
    (
        "local close forbids later entry",
        "tests.executorworld:FakeExecutorHandle.materialize",
        "if self.closed:",
        "if False:",
        LIFECYCLE + "test_recording_failure_keeps_close_inert_and_forbids_late_entry",
    ),
    (
        "entered before the first await",
        "tests.executorworld:FakeExecutorHandle.materialize",
        "self.entered = True",
        "pass",
        LIFECYCLE + "test_materialization_failure_discards_the_enrolled_acquisition",
    ),
    (
        "reconcile fences even absence",
        "tests.executorworld:FakeExecutorProvider.reconcile",
        "if self.ledger.close(key):",
        "if key in self.ledger.resources and self.ledger.close(key):",
        LIFECYCLE + "test_recovery_fences_a_recorded_acquisition_even_if_it_never_started",
    ),
    (
        "control is rechecked after materialization",
        "constructicon.runtime.walker:Walker._invoke",
        "await acquisition.materialize()\n                    self._check_run_control(lease, lost)",
        "await acquisition.materialize()",
        CONTROL + "test_control_changed_during_materialization_prevents_invocation",
    ),
    (
        "recorded cleanup joins the cancellation barrier",
        "constructicon.runtime.walker:Walker._close_acquired",
        "await self._finish_cleanup(close_all())",
        "await close_all()",
        CONTROL + "test_repeated_cancellation_finishes_recorded_cleanup",
    ),
    (
        "cancellation cannot reach the cleanup task",
        "constructicon.runtime.walker:Walker._finish_cleanup",
        "await asyncio.shield(close_task)",
        "await close_task",
        CONTROL + "test_repeated_cancellation_finishes_recorded_cleanup",
    ),
    (
        "cleanup is joined after every cancellation",
        "constructicon.runtime.walker:Walker._finish_cleanup",
        "while not close_task.done():",
        "if not close_task.done():",
        CONTROL + "test_repeated_cancellation_finishes_recorded_cleanup",
    ),
    (
        "cancellation propagates after cleanup",
        "constructicon.runtime.walker:Walker._finish_cleanup",
        "raise cancellation",
        "return",
        CONTROL + "test_repeated_cancellation_finishes_recorded_cleanup",
    ),
    (
        "cleanup retains every enrolled sibling",
        "constructicon.runtime.walker:Walker._close_acquired",
        "for index, (capability, acquisition) in enumerate(acquired):",
        "for index, (capability, acquisition) in enumerate(acquired[:1]):",
        CONTROL + "test_repeated_cancellation_finishes_recorded_cleanup",
    ),
    (
        "cleanup failure outranks pending cancellation",
        "constructicon.runtime.walker:Walker._finish_cleanup",
        "close_task.result()",
        "pass",
        CONTROL + "test_cleanup_failure_is_not_laundered_into_cancellation",
    ),
    (
        "plan manifest baseline comes from committed HEAD",
        MANIFEST,
        'entries(git("show", "HEAD:docs/plans/MANIFEST.sha256"))',
        "entries(MANIFEST.read_bytes())",
        PLAN_TESTS + "test_refuses_unnamed_staged_drift_against_committed_baseline"
        "[matching-digest]",
    ),
    (
        "every staged new plan document is named",
        MANIFEST,
        "if staged != wanted:",
        "if False:",
        PLAN_TESTS + "test_refuses_unnamed_staged_new_document[False]",
    ),
    (
        "unnamed committed entries cannot be omitted",
        MANIFEST,
        "path not in current or current[path] != digest",
        "current.get(path, digest) != digest",
        PLAN_TESTS + "test_refuses_manifest_edits_and_deletions_of_unnamed_paths[omitted]",
    ),
    (
        "unresolved manifest conflicts refuse",
        "scripts.regen_plan_manifest:entries",
        'raise ValueError("resolve manifest conflicts explicitly before refresh")',
        "continue",
        PLAN_TESTS + "test_refuses_each_manifest_conflict_marker[<<<<<<<]",
    ),
    (
        "unmerged manifest index refuses even without textual markers",
        MANIFEST,
        'if git("ls-files", "--unmerged", "--", "docs/plans/MANIFEST.sha256"):',
        "if False:",
        PLAN_TESTS + "test_refuses_manifest_index_conflict_without_markers[other]",
    ),
    (
        "every terminal status accounts for active cleanup",
        "constructicon.substrate.journal._sqlite_execution:_SqliteExecutionMixin.transition_run",
        "if target in TERMINAL_STATUS_EVENTS:", "if False:",
        CLEANUP + "test_active_rows_refuse_every_terminal_transition",
    ),
    (
        "an active acquisition refuses terminalization",
        "constructicon.substrate.journal._sqlite_execution:_SqliteExecutionMixin.transition_run",
        "if active:", "if False:",
        CLEANUP + "test_active_rows_refuse_every_terminal_transition",
    ),
    (
        "cleanup guard uses the canonical lease selector",
        "constructicon.substrate.journal._sqlite_execution:_SqliteExecutionMixin.transition_run",
        "rows = _capability_lease_rows(conn, run_id=lease.run_id)",
        'rows = conn.execute("SELECT * FROM capability_leases WHERE run_id = ?", '
        '(lease.run_id,)).fetchall()',
        CLEANUP + "test_terminal_cleanup_guard_preserves_ownership_and_projection_fences",
    ),
    (
        "provider failure does not stop sibling cleanup",
        "constructicon.runtime.walker:Walker._close_acquired",
        "errors.append(exc)", "raise _CleanupFailure(exc, node_error)",
        CLEANUP + "test_failed_close_escapes_its_site_and_releases_every_sibling",
    ),
    (
        "a failed close relinquishes its local custody",
        "constructicon.runtime.walker:Walker._close_acquired",
        "[(capability, acquisition)], loss=lost[0] if lost else None,",
        "[], loss=lost[0] if lost else None,",
        CLEANUP + "test_failed_close_escapes_its_site_and_releases_every_sibling",
    ),
    (
        "failed close observes a successor before another physical close",
        "constructicon.runtime.walker:Walker._close_acquired",
        "raise lost[0]\n                    self._journal.heartbeat(lease, "
        "ttl_s=self._lease_ttl_s)",
        "raise lost[0]\n                    None",
        CLEANUP + "test_last_failed_close_observes_successor_without_latched_heartbeat",
    ),
    (
        "settle ownership observation failure releases unenrolled custody",
        "constructicon.runtime.walker:Walker._acquire_invocation_capability",
        "[(capability, acquisition)],\n"
        "                        loss=observation_error",
        "[],\n                        loss=observation_error",
        CLEANUP + "test_settle_heartbeat_failure_releases_unenrolled_custody",
    ),
    (
        "shared close and relinquish errors appear once",
        "constructicon.runtime.walker:_cleanup_error",
        "elif id(error) not in seen:", "else:",
        CLEANUP + "test_shared_release_errors_are_deduplicated_without_walking_context",
    ),
    (
        "original invocation failure is carried explicitly",
        "constructicon.runtime.walker:Walker._execute_or_restore",
        "original = cleanup.node_error", "original = None",
        CLEANUP + "test_failed_close_escapes_its_site_and_releases_every_sibling[node-failed]",
    ),
    (
        "cancellation observed during cleanup remains an explicit fact",
        "constructicon.runtime.walker:Walker._finish_cleanup",
        "cleanup.cancellation = cancellation", "pass",
        CLEANUP + "test_failed_close_preserves_explicit_cancellation_intent[checkpointed-cancel]",
    ),
    (
        "cleanup failure still records user cancellation durably",
        "constructicon.runtime.walker:Walker._finish_run",
        'if cancellation == "cancel" and cancelled is not None and loss is None:', "if False:",
        CLEANUP + "test_failed_close_preserves_explicit_cancellation_intent[invoking-cancel]",
    ),
    (
        "abandonment never invents user cancellation",
        "constructicon.runtime.walker:Walker._finish_run",
        'cancellation == "cancel" and cancelled is not None and loss is None',
        "cancelled is not None and loss is None",
        CLEANUP + "test_failed_close_preserves_explicit_cancellation_intent[checkpointed-abandon]",
    ),
    (
        "ordinary shutdown failures still release run ownership",
        "constructicon.runtime.walker:Walker._finish_run",
        "self._release_quietly(lease)", "None",
        CLEANUP + "test_failed_cancel_request_still_stops_heartbeat_and_releases",
    ),
    (
        "a failed cancellation request still stops its heartbeat",
        "constructicon.runtime.walker:Walker._finish_run",
        "await self._stop_heartbeat(heartbeat)", "None",
        CLEANUP + "test_cancel_request_hard_death_stops_the_heartbeat_without_releasing",
    ),
    (
        "background heartbeat failure cannot replace ownership loss",
        "constructicon.runtime.walker:Walker._finish_run",
        "if loss is not None:", "if False:",
        CLEANUP + "test_background_heartbeat_failure_releases_without_replacing_loss"
        "[ownership-lost]",
    ),
    (
        "cleanup errors bypass node-failure containment",
        "constructicon.runtime.walker:Walker._execute_or_restore",
        "except _CleanupFailure as cleanup:", "except _CancelRequested as cleanup:",
        CLEANUP + "test_failed_close_escapes_its_site_and_releases_every_sibling[checkpointed]",
    ),
    (
        "unknown ownership releases remaining custody without another close",
        "constructicon.runtime.walker:Walker._close_acquired",
        "except Exception as observation:\n                    errors.append(observation)",
        "except ContractViolation as observation:\n                    errors.append(observation)",
        CLEANUP + "test_failed_close_observes_ownership_before_any_later_close[failed]",
    ),
    (
        "grouped hard death retains crash semantics",
        "constructicon.runtime.walker:_is_hard_death",
        "return not isinstance(error, (Exception, asyncio.CancelledError))", "return False",
        CLEANUP + "test_hard_death_during_close_retains_crash_semantics[grouped]",
    ),
    (
        "unrecorded ownership loss relinquishes eager custody",
        "constructicon.runtime.walker:Walker._discard_unrecorded_acquisition",
        "[(capability, acquisition)], loss=loss or close_loss,",
        "[], loss=loss or close_loss,",
        CLEANUP + "test_unrecorded_close_loss_relinquishes_eager_custody",
    ),
    (
        "unrecorded release retains observed task cancellation",
        "constructicon.runtime.walker:Walker._discard_unrecorded_acquisition",
        "await Walker._finish_cleanup(discard())", "await discard()",
        CLEANUP + "test_unenrolled_release_retains_observed_cancellation[cancel-unrecorded]",
    ),
    (
        "settled unenrolled release retains observed task cancellation",
        "constructicon.runtime.walker:Walker._acquire_invocation_capability",
        "await self._finish_cleanup(release_unenrolled(observation, record_error))",
        "await release_unenrolled(observation, record_error)",
        CLEANUP + "test_unenrolled_release_retains_observed_cancellation[cancel-settled]",
    ),
    (
        "unrecorded cleanup cannot replace the original ownership loss",
        "constructicon.runtime.walker:Walker._acquire_invocation_capability",
        "except OwnershipLost as cleanup:", "except CheckpointConflict as cleanup:",
        CLEANUP + "test_unrecorded_close_loss_relinquishes_eager_custody[record-lost]",
    ),
    (
        "failed diagnostics cannot erase cleanup or cancellation facts",
        "constructicon.runtime.walker:Walker._execute_or_restore",
        "except Exception as diagnostic:", "except CheckpointConflict as diagnostic:",
        CLEANUP + "test_failed_node_diagnostic_preserves_cleanup_failure_and_cancellation[error]",
    ),
    (
        "ownership loss while recording diagnostics remains primary",
        "constructicon.runtime.walker:Walker._execute_or_restore",
        "except OwnershipLost as loss:", "except CheckpointConflict as loss:",
        CLEANUP + "test_failed_node_diagnostic_preserves_cleanup_failure_and_cancellation[lost]",
    ),
    (
        "normal relinquishment preserves hard death instead of releasing ownership",
        "constructicon.runtime.walker:Walker._relinquish_acquired",
        "if loss is None and _is_hard_death(exc):", "if False:",
        CLEANUP + "test_relinquishment_hard_death_preserves_the_known_loss_boundary"
        "[normal-grouped]",
    ),
    (
        "known ownership loss remains primary over relinquishment hard death",
        "constructicon.runtime.walker:Walker._relinquish_acquired",
        "loss is None and _is_hard_death(exc)", "_is_hard_death(exc)",
        CLEANUP + "test_relinquishment_hard_death_preserves_the_known_loss_boundary[lost-grouped]",
    ),
    (
        "relinquishment preserves mixed hard-death groups on supported runtimes",
        "constructicon.runtime.walker:Walker._relinquish_acquired",
        "try:  # noqa: SIM105 - suppress rewrites exception groups on Python 3.12+.\n"
        "            await asyncio.shield(batch)\n"
        "        except asyncio.CancelledError:\n"
        "            pass",
        "with contextlib.suppress(asyncio.CancelledError):\n"
        "            await asyncio.shield(batch)",
        CLEANUP + "test_mixed_relinquishment_hard_death_preserves_group_and_custody[group-aware]",
    ),
    (
        "worker cancellation cannot bypass its atomic lease fence",
        "constructicon.substrate.journal._sqlite_execution:_SqliteExecutionMixin.request_cancel",
        "if lease is None:", "if True:",
        CLEANUP + "test_successor_interposed_at_cancel_write_is_not_cancelled",
    ),
    (
        "cancellation lease must name the selected run",
        "constructicon.substrate.journal._sqlite_execution:_SqliteExecutionMixin.request_cancel",
        "if lease is not None and lease.run_id != run_id:", "if False:",
        CLEANUP + "test_cancel_request_optional_lease_fence_preserves_authority_and_sequence"
        "[run-id]",
    ),
    (
        "worker cancellation fences the owner identity",
        "constructicon.substrate.journal._sqlite_execution:_SqliteExecutionMixin.request_cancel",
        "AND owner_id = ?", "AND ? IS NOT NULL",
        CLEANUP + "test_cancel_request_optional_lease_fence_preserves_authority_and_sequence"
        "[owner]",
    ),
    (
        "worker cancellation fences the owner epoch",
        "constructicon.substrate.journal._sqlite_execution:_SqliteExecutionMixin.request_cancel",
        "AND owner_epoch = ?", "AND ? IS NOT NULL",
        CLEANUP + "test_cancel_request_optional_lease_fence_preserves_authority_and_sequence"
        "[epoch]",
    ),
    (
        "a refused worker cancellation reports ownership loss",
        "constructicon.substrate.journal._sqlite_execution:_SqliteExecutionMixin.request_cancel",
        "if updated.rowcount == 0:", "if False:",
        CLEANUP + "test_cancel_request_optional_lease_fence_preserves_authority_and_sequence"
        "[stale]",
    ),
    (
        "latched loss is rechecked after the heartbeat join",
        "constructicon.runtime.walker:Walker._finish_run",
        "if lost:", "if False:",
        CLEANUP + "test_loss_latched_while_stopping_heartbeat_skips_cancellation_write",
    ),
    (
        "atomic cancellation refusal outranks earlier cleanup failure",
        "constructicon.runtime.walker:Walker._finish_run",
        "intent_recorded = True\n        except OwnershipLost as exc:",
        "intent_recorded = True\n        except CheckpointConflict as exc:",
        CLEANUP + "test_successor_interposed_at_cancel_write_is_not_cancelled[close-failed]",
    ),
    (
        "each physical close positively observes ownership first",
        "constructicon.runtime.walker:Walker._close_acquired",
        "self._journal.heartbeat(lease, ttl_s=self._lease_ttl_s)\n"
        "            except OwnershipLost as loss:",
        "None\n            except OwnershipLost as loss:",
        CLEANUP + "test_second_settle_observation_failure_relinquishes_earlier_siblings"
        "[persistent]",
    ),
    (
        "preflight ownership loss retains the known-loss relinquishment law",
        "constructicon.runtime.walker:Walker._close_acquired",
        "except OwnershipLost as loss:\n"
        "                failure = await self._relinquish_acquired(acquired[index:], loss=loss)",
        "except CheckpointConflict as loss:\n"
        "                failure = await self._relinquish_acquired(acquired[index:], loss=loss)",
        CLEANUP + "test_close_batch_observes_latched_loss_before_its_first_close[release-crash]",
    ),
    (
        "preflight observation failure relinquishes every remaining acquisition",
        "constructicon.runtime.walker:Walker._close_acquired",
        "failure = await self._relinquish_acquired(acquired[index:])", "failure = None",
        CLEANUP + "test_second_settle_observation_failure_relinquishes_earlier_siblings"
        "[persistent]",
    ),
    (
        "maintenance preflight proposal fits the installed reader bound",
        "constructicon.api.maintenance_entry:_authorization_preview",
        "len(raw) + 1 > MAX_AUTHORIZATION_BYTES", "False",
        "tests/api/test_maintenance_entry.py::"
        "test_cli_preflight_never_runs_and_run_delegates_exact_installed_authority",
    ),
    (
        "maintenance preflight counts the emitted newline",
        "constructicon.api.maintenance_entry:_authorization_preview",
        "len(raw) + 1 > MAX_AUTHORIZATION_BYTES", "len(raw) > MAX_AUTHORIZATION_BYTES",
        "tests/api/test_maintenance_entry.py::"
        "test_cli_preflight_never_runs_and_run_delegates_exact_installed_authority",
    ),
    (
        "maintenance historical inspection bounds identifier shapes",
        "constructicon.api.maintenance_entry:inspect_result",
        'if re.fullmatch(r"run-[0-9a-f]{32}", result.run_id) is None or (',
        "if False and (",
        "tests/api/test_maintenance_entry.py::"
        "test_inspect_refuses_unbounded_or_private_text_identifiers",
    ),
    *(
        (
            "maintenance unavailable assembly binds " + label,
            "constructicon.api.plan_manifest_application:maintenance_system",
            before, "False",
            "tests/api/test_maintenance_entry.py::"
            "test_unavailable_application_assembly_requires_exact_companion_and_request_pins",
        )
        for label, before in (
            ("request", "authorization.request != resources.request"),
            ("application", "authorization.application_revision != maintenance_application_revision()"),
            (
                "workspace",
                "authorization.workspace != MaintenanceCapabilityPin(\n"
                "                capability_id=resources.workspace.provider_id,\n"
                "                revision=resources.workspace.revision)",
            ),
            (
                "gate",
                "authorization.gate != MaintenanceCapabilityPin(\n"
                "                capability_id=resources.gate.provider_id, revision=resources.gate.revision)",
            ),
        )
    ),
    *(
        (
            "maintenance application pins " + label,
            "constructicon.api._maintenance_identity:maintenance_application_revision",
            '"' + source + '",', "",
            "tests/api/test_maintenance_entry.py::"
            "test_application_revision_pins_each_authorization_law[" + label + "]",
        )
        for label, source in (
            ("core-law", "core/maintenance.py"),
            ("maintenance-reader", "substrate/executors/maintenance.py"),
            ("root-custody-reader", "substrate/executors/qualification.py"),
        )
    ),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
