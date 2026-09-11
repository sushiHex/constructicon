"""Native PR B regressions; run only in the provisioned containment job.

No fake OS result and no rewrite of the immutable reaper. These mutations
replace the owning controller's code objects; the real boundary and children
still execute. Assertion failures alone count. Independently masked guards
are documented in the implementation record, never credited as killed.
"""

from _mutations import run

LAUNCH = "constructicon.substrate.executors.linux:LinuxLauncher."
WORKSPACE = "constructicon.substrate.git.contained:ContainedWorkspaceProvider."
OS = "tests/substrate/test_linux_containment.py::"
LEASE = "tests/substrate/test_contained_workspace.py::"
CLOSURE = "constructicon.substrate.git.acquisition:AcquisitionClosure."
FACT = "tests/substrate/test_acquisition_closure.py::"
OPEN_CHECK = (
    "await finish_owned(asyncio.create_task(asyncio.to_thread(\n"
    "            self.provider.closure.require_open, self.paths,\n        )))"
)
BASE_READ = (
    "await finish_owned(asyncio.create_task(asyncio.to_thread(\n"
    "        self.authority.resolve_ref, self.target_ref,\n    )))"
)
COMMIT = (
    "await finish_owned(asyncio.create_task(asyncio.to_thread(\n"
    "        closure.commit, paths, candidate_ref=candidate_ref, disposition=disposition,\n"
    "    )))"
)
METADATA = (
    ("acquire", WORKSPACE + "acquire", BASE_READ,
     "self.authority.resolve_ref(self.target_ref)"),
    ("materialize", "constructicon.substrate.git.contained:ContainedWorkspace.materialize",
     OPEN_CHECK, "self.provider.closure.require_open(self.paths)"),
    ("use", "constructicon.substrate.git.contained:ContainedWorkspace.use.__wrapped__",
     OPEN_CHECK, "self.provider.closure.require_open(self.paths)"),
    ("close", "constructicon.substrate.git.acquisition:dispose_acquisition",
     COMMIT, "closure.commit(paths)"),
)

MUTANTS = (
    (
        "TERM grace is skipped", "constructicon.substrate.executors._supervisor:_Shutdown.forced",
        "self.started + TERM_GRACE_S", "self.started",
        OS + "test_shutdown_has_one_nonrenewable_two_second_grace",
    ),
    (
        "repeated acknowledgements renew TERM grace",
        "constructicon.substrate.executors._supervisor:_Shutdown.acknowledge_term",
        "if self.started is None:", "if True:",
        OS + "test_shutdown_has_one_nonrenewable_two_second_grace",
    ),
    (
        "stop requests consume grace before TERM delivery",
        "constructicon.substrate.executors._supervisor:_Shutdown.request",
        "self._requested = True",
        "self._requested = True\n    self.acknowledge_term(time.monotonic())",
        OS + "test_shutdown_has_one_nonrenewable_two_second_grace",
    ),
    (
        "cooperative namespace shutdown sends KILL",
        "constructicon.substrate.executors._supervisor:_signal_namespace",
        "signal.SIGKILL if force else signal.SIGTERM", "signal.SIGKILL",
        OS + "test_namespace_signals_are_term_then_kill_and_never_host_wide",
    ),
    (
        "namespace teardown never escalates",
        "constructicon.substrate.executors._supervisor:_signal_namespace",
        "signal.SIGKILL if force else signal.SIGTERM", "signal.SIGTERM",
        OS + "test_namespace_signals_are_term_then_kill_and_never_host_wide",
    ),
    (
        "namespace signaling loses its PID guard",
        "constructicon.substrate.executors._supervisor:_signal_namespace",
        'if sys.platform != "linux" or os.getpid() != 1:', "if False:",
        OS + "test_namespace_signals_are_term_then_kill_and_never_host_wide",
    ),
    *(
        (
            f"{phase} metadata {'blocks the loop' if blocking else 'outlives its owner'}",
            target, before,
            synchronous if blocking else before.replace(
                "await finish_owned(asyncio.create_task(asyncio.to_thread(",
                "await asyncio.to_thread(",
            )[:-2],
            LEASE + f"test_trusted_metadata_yields_and_remains_owned_through_cancellation[{phase}]",
        )
        for phase, target, before, synchronous in METADATA for blocking in (True, False)
    ),
    (
        "READ extraction monopolizes the event loop", WORKSPACE + "populate",
        "await finish_owned(asyncio.create_task(asyncio.to_thread(extract)))", "extract()",
        LEASE + "test_read_extraction_yields_and_retains_its_guard_until_writes_finish",
    ),
    (
        "READ extraction outlives its guard", WORKSPACE + "populate",
        "await finish_owned(asyncio.create_task(asyncio.to_thread(extract)))",
        "await asyncio.to_thread(extract)",
        LEASE + "test_read_extraction_yields_and_retains_its_guard_until_writes_finish",
    ),
    (
        "artifact hashing monopolizes the event loop", LAUNCH + "probe",
        "await finish_owned(asyncio.create_task(asyncio.to_thread(self.check_artifacts)))",
        "self.check_artifacts()",
        OS + "test_artifact_verification_yields_and_joins_before_return",
    ),
    (
        "artifact hashing outlives its owner", LAUNCH + "probe",
        "await finish_owned(asyncio.create_task(asyncio.to_thread(self.check_artifacts)))",
        "await asyncio.to_thread(self.check_artifacts)",
        OS + "test_artifact_verification_yields_and_joins_before_return",
    ),
    (
        "availability gets an independent deadline", LAUNCH + "_launch",
        "await self.probe(deadline=deadline)", "await self.probe()",
        OS + "test_probe_reaper_uses_the_call_deadline_when_the_controller_stalls",
    ),
    (
        "buffered start survives observed owner death",
        "constructicon.substrate.executors._supervisor:_owner_closed",
        "return any(flags & (select.POLLHUP | select.POLLERR) for _, flags in events)",
        "return False",
        OS + "test_buffered_start_does_not_authorize_launch_after_observed_owner_death",
    ),
    (
        "recording changes behind its identity", "tests.containedworld:RecordedExecutor.execute",
        "if actual_program != self.provider.identity.configuration_digest:",
        "if False:",
        "tests/substrate/test_recorded_executor.py::"
        "test_recorded_program_cannot_change_after_its_identity_was_admitted",
    ),
    (
        "malformed counts are invented", "tests.containedworld:decode",
        "malformed_records=malformed", "malformed_records=1",
        "tests/substrate/test_recorded_executor.py::"
        "test_recorded_damage_counts_observed_malformed_records_only",
    ),
    (
        "supervisor from mutable checkout", LAUNCH + "_run",
        "str(self.root / SUPERVISOR_PATH)", "str(Path(__file__).with_name('_supervisor.py'))",
        OS + "test_supervisor_source_is_loaded_only_from_the_immutable_closure",
    ),
    (
        "workspace uses task-input bound", WORKSPACE + "_export",
        "GitProcess(self.git, self.launcher.limits)",
        "GitProcess(self.git, type(self.launcher.limits)("
        "artifact_bytes=self.launcher.limits.input_bytes))",
        LEASE + "test_export_has_an_artifact_bound_not_the_task_input_bound",
    ),
    (
        "probe outside call deadline", LAUNCH + "_launch",
        "async with asyncio.timeout_at(deadline):", "async with asyncio.timeout(10):",
        OS + "test_the_call_deadline_includes_probe_and_spawn[probe]",
    ),
    (
        "deadline never reaches the reaper", LAUNCH + "_run",
        "str(child_deadline)", "str(child_deadline + 100)",
        OS + "test_reaper_enforces_expiry_while_the_controller_event_loop_is_stalled",
    ),
    (
        "payload start before spawn ownership", LAUNCH + "_run",
        "spawn = asyncio.create_task(asyncio.create_subprocess_exec(",
        "if workspace is not None: os.write(owner_write, b'\\x01')"
        "\n        spawn = asyncio.create_task(asyncio.create_subprocess_exec(",
        OS + "test_payload_waits_for_controller_ownership_of_the_real_spawn_handle",
    ),
    (
        "READ snapshot becomes writable", LAUNCH + "argv",
        '"--ro-bind" if posture is Posture.READ else "--bind"', '"--bind"',
        OS + "test_read_writes_fail_physically_and_leave_the_snapshot_exact"
        "[p.write_text('changed')]",
    ),
    (
        "network namespace removed", LAUNCH + "argv",
        '"--unshare-uts", "--unshare-net",', '"--unshare-uts",',
        OS + "test_child_and_grandchild_cannot_reach_the_host_loopback_service",
    ),
    (
        "workspace mounts the host parent", LAUNCH + "argv",
        'str(workspace), "/workspace"', 'str(workspace.parent), "/workspace"',
        OS + "test_write_changes_only_its_explicit_workspace",
    ),
    (
        "runtime link targets escape the hashed closure",
        "constructicon.substrate.executors.linux:runtime_inventory",
        "if not path.resolve().is_relative_to(root.resolve()):", "if False:",
        OS + "test_runtime_cannot_execute_a_symlink_target_outside_its_hashed_closure",
    ),
    (
        "closed materializer can create again",
        "constructicon.substrate.git.contained:ContainedWorkspace.materialize",
        OPEN_CHECK, "pass",
        LEASE + "test_waiting_materializer_cannot_recreate_disposed_payload",
    ),
    (
        "literal sentinel accepts symbolic alias", CLOSURE + "is_closed",
        "if symbolic.returncode != 1:", "if False:",
        FACT + "test_wrong_or_symbolic_closure_is_damage_never_open_or_repaired[True]",
    ),
    (
        "durably closed view can be used",
        "constructicon.substrate.git.contained:ContainedWorkspace.use.__wrapped__",
        OPEN_CHECK, "pass",
        LEASE + "test_recovery_waits_for_started_materialization_then_removes_it",
    ),
    (
        "guard does not serialize physical work",
        "constructicon.substrate.git.acquisition:acquisition_guard.__wrapped__",
        "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)", "pass",
        LEASE + "test_reconciliation_commits_revocation_before_waiting_for_physical_quiescence",
    ),
    (
        "closure waits behind the producer",
        "constructicon.substrate.git.acquisition:dispose_acquisition",
        f"{COMMIT}\n    async with acquisition_guard(paths):",
        f"async with acquisition_guard(paths):\n        {COMMIT}",
        LEASE + "test_reconciliation_commits_revocation_before_waiting_for_physical_quiescence",
    ),
    (
        "absence means closed", CLOSURE + "is_closed",
        "return False", "return True",
        FACT + "test_closure_is_inert_until_committed_and_names_no_merge_subject",
    ),
    (
        "closed lookup accepts a commit", CLOSURE + "is_closed",
        "result.returncode != 0 or result.stdout.strip() != self.sentinel",
        "result.returncode != 0",
        FACT + "test_wrong_or_symbolic_closure_is_damage_never_open_or_repaired[False]",
    ),
    (
        "closure omits its durable transaction", CLOSURE + "commit",
        'actual = self.authority._run("hash-object", "-w", "--stdin", '
        'input_text="").stdout.strip()',
        "return",
        FACT + "test_closure_is_idempotent_and_different_epochs_never_reopen_one_another",
    ),
    (
        "elapsed observation omits availability", LAUNCH + "_launch",
        "return replace(result, elapsed_s=time.monotonic() - started)", "return result",
        OS + "test_successful_call_elapsed_time_includes_availability",
    ),
    (
        "deletion monopolizes the event loop",
        "constructicon.substrate.git.acquisition:dispose_acquisition",
        "await finish_owned(asyncio.create_task(asyncio.to_thread(shutil.rmtree, paths.payload)))",
        "shutil.rmtree(paths.payload)",
        LEASE + "test_deletion_yields_but_keeps_its_guard_through_repeated_cancellation",
    ),
    (
        "deletion abandons its guard on cancellation",
        "constructicon.substrate._lifetime:finish_owned",
        "await asyncio.shield(task)", "await task",
        LEASE + "test_deletion_yields_but_keeps_its_guard_through_repeated_cancellation",
    ),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
