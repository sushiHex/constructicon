"""Native PR B regressions; run only in the provisioned containment job.

No fake OS result and no rewrite of the immutable reaper. These mutations
replace the owning controller's code objects; the real boundary and children
still execute. Assertion failures alone count. This is an expanding inventory,
not yet the complete PR B physical proof matrix.
"""

from _mutations import run

LAUNCH = "constructicon.substrate.executors.linux:LinuxLauncher."
WORKSPACE = "constructicon.substrate.git.contained:ContainedWorkspaceProvider."
OS = "tests/substrate/test_linux_containment.py::"
LEASE = "tests/substrate/test_contained_workspace.py::"

MUTANTS = (
    (
        "supervisor from mutable checkout", LAUNCH + "_run",
        "str(self.root / SUPERVISOR_PATH)", "str(Path(__file__).with_name('_supervisor.py'))",
        OS + "test_supervisor_source_is_loaded_only_from_the_immutable_closure",
    ),
    (
        "workspace uses task-input bound", WORKSPACE + "_export",
        "self.launcher.limits.artifact_bytes", "self.launcher.limits.input_bytes",
        LEASE + "test_export_has_an_artifact_bound_not_the_task_input_bound",
    ),
    (
        "probe outside call deadline", LAUNCH + "run",
        "async with asyncio.timeout_at(deadline):", "async with asyncio.timeout(10):",
        OS + "test_the_call_deadline_includes_probe_and_spawn[probe]",
    ),
    (
        "spawn outside call deadline", LAUNCH + "_run",
        "async with asyncio.timeout_at(deadline):\n"
        "                process = await asyncio.shield(spawn)",
        "async with asyncio.timeout(10):\n"
        "                process = await asyncio.shield(spawn)",
        OS + "test_the_call_deadline_includes_probe_and_spawn[spawn]",
    ),
    (
        "elapsed observation omits availability", LAUNCH + "run",
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
