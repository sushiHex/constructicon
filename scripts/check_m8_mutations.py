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

MUTANTS = (
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
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
