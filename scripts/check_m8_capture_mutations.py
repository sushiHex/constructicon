"""PR C laws: real Git/processes, isolated mutations, assertion failures only."""

from _mutations import run

CAPTURE = "constructicon.substrate.git.capture:ContainedWriteWorkspaceProvider."
CLOSURE = "constructicon.substrate.git.acquisition:AcquisitionClosure."
PACK = "constructicon.substrate.git.pack:import_pack"
PROCESS = "constructicon.substrate.git.process:GitProcess.run"
NATIVE = "tests/substrate/test_contained_capture.py::"
FACT = "tests/substrate/test_acquisition_closure.py::"
HANDOFF = "tests/substrate/test_git_pack.py::"

# Only the disposable test's hostile stage is interpreted by this deliberate
# regression. It executes the same fixed Git program with the boundary removed.
HOST_CAPTURE = """self._check(workspace)
    if posture is Posture.WRITE:
        child = await asyncio.create_subprocess_exec(
            *command, cwd=workspace.path, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        output, errors = await child.communicate(stdin)
        if child.returncode:
            raise ContractViolation(errors.decode(errors='replace'))
        return output"""

MUTANTS = (
    (
        "mutable capture executes on the host", CAPTURE + "_contained",
        "self._check(workspace)", HOST_CAPTURE,
        NATIVE + "test_hostile_git_metadata_cannot_execute_or_modify_a_host_sentinel[hook]",
    ),
    (
        "export has WRITE authority", CAPTURE + "capture",
        'posture=Posture.READ, stdin=f"{oid}\\n".encode(),',
        'posture=Posture.WRITE, stdin=f"{oid}\\n".encode(),',
        NATIVE + "test_export_is_physically_read_only_after_capture",
    ),
    (
        "publication omits its atomic closure fence", CLOSURE + "publish",
        'f"verify {paths.closure_ref} {\'0\' * len(self.sentinel)}",', "",
        FACT + "test_publication_cannot_follow_closure_even_after_its_last_open_check",
    ),
    (
        "closure does not verify candidate absence", CLOSURE + "commit",
        'commands.append(f"verify {candidate_ref} {observed}")',
        'commands.extend([f"verify {candidate_ref} {observed}"] if candidate else [])',
        FACT + "test_discard_verifies_even_candidate_absence_in_the_closure_transaction",
    ),
    (
        "discard retains a published candidate", CLOSURE + "commit",
        'if disposition == "discard" and candidate is not None:', "if False:",
        FACT + "test_publication_then_closure_obeys_disposition_and_never_reopens[discard]",
    ),
    (
        "release deletes a checkpointed candidate", CLOSURE + "commit",
        'if disposition == "discard" and candidate is not None:',
        'if candidate is not None:',
        FACT + "test_publication_then_closure_obeys_disposition_and_never_reopens[release]",
    ),
    (
        "capture ignores the invocation control check", CAPTURE + "_check",
        "control()", "pass",
        NATIVE + "test_capture_observes_control_loss_before_publication[OwnershipLost]",
    ),
    (
        "objects enter authority before quarantine proof", PACK,
        'quarantine = Path(tempfile.mkdtemp(prefix="quarantine-", dir=acquisition_root))',
        'await git.run("index-pack", "--stdin", cwd=authority.repository_id, '
        'stdin=pack, guard=guard)\n'
        '    quarantine = Path(tempfile.mkdtemp(prefix="quarantine-", dir=acquisition_root))',
        HANDOFF + "test_pack_must_carry_the_named_commit_not_an_object_in_the_authority",
    ),
    (
        "a tree may masquerade as a commit", PACK,
        'if kind != b"commit\\n":', "if False:",
        HANDOFF + "test_a_valid_tree_cannot_be_published_as_a_commit",
    ),
    (
        "object count is unbounded", PACK, "not 0 < count <= limits.objects", "not 0 < count",
        HANDOFF + "test_pack_resource_bounds_are_enforced_before_authority_import[objects]",
    ),
    (
        "expanded objects are unbounded", PACK,
        "if sum(int(row) for row in rows) > limits.expanded_bytes:", "if False:",
        HANDOFF + "test_pack_resource_bounds_are_enforced_before_authority_import[expanded]",
    ),
    (
        "Git parser loses its native resource limits", PROCESS,
        'if sys.platform == "linux":', "if False:",
        "tests/substrate/test_git_process.py::"
        "test_git_parser_limits_are_present_in_the_actual_child_before_parsing",
    ),
    (
        "repeated cancellation abandons the actual spawn", PROCESS,
        "await finish_owned(asyncio.create_task(cleanup()))", "await cleanup()",
        "tests/substrate/test_git_process.py::"
        "test_cancel_during_real_spawn_joins_before_repeated_cancellation_returns",
    ),
    (
        "the awaiting component checkpoints before capture", "tests.captureworld:capture_candidate",
        'await workspace.commit_all(inputs["goal"]["message"])',
        'workspace.commit_all(inputs["goal"]["message"])',
        "tests/runtime/test_async_workspace.py::"
        "test_real_walker_passes_control_and_awaits_capture_before_checkpoint",
    ),
    (
        "WRITE provider may use legacy host capture or gates",
        "constructicon.api.system:Constructicon.__init__",
        "and Posture.WRITE in resource.identity.profile.postures", "and False",
        "tests/api/test_capture_assembly.py::"
        "test_new_write_provider_refuses_legacy_resources_even_when_relabeled",
    ),
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
