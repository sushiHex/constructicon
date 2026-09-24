"""Reviewed-artifact judge and verifier mutations (#94); assertion failures only count as kills.

Provenance, profile-list, assessment and command-record mutants run on every
platform. The custody, staging, ownership and destination mutants target
Linux-only tests and report NOT PROVEN elsewhere; ``verify.yml`` runs this
inventory on Linux as a non-root user. The regular-file mutant is a message pin:
without the check an unfed staged FIFO reads as empty and still differs from its
blob, so its kill shows which check refuses, not a lost refusal.
"""

from _mutations import run

MODULE = "scripts.ci.m8_host_artifacts:"
TESTS = "tests/test_m8_host_artifacts.py::"
RUNTIME = "tests/test_m8_host_runtime.py::"

# The launch set (M8-N4-host-runtime.md). Each fact has one check, so no mutant
# here is masked by an earlier guard. The launch destinations' ancestor checks
# are not mutated: on this layout the host sources' custody walks the same
# ancestors first, so their removal is unobservable (recorded in the design).
LAUNCH_PORTABLE = (
    ("derived value named exactly once", MODULE + "derive", "len(found) == 1", "len(found) >= 1",
     RUNTIME + "test_a_value_named_zero_or_two_times_refuses"),
    ("service account unprivileged and alone", MODULE + "service_account",
     "uid != 0 and gid != 0 and group == SERVICE and not others", "True",
     RUNTIME + "test_the_service_account_is_unprivileged_and_alone"),
    ("archive members are files or directories", MODULE + "vendor_plan",
     "member.isdir() or member.isreg()", "True",
     RUNTIME + "test_an_unsafe_archive_member_refuses"),
    ("archive members carry no special bit", MODULE + "vendor_plan",
     "not member.mode & 0o7000", "True", RUNTIME + "test_an_unsafe_archive_member_refuses"),
    ("archive members are unique", MODULE + "vendor_plan", "name not in entries", "True",
     RUNTIME + "test_an_unsafe_archive_member_refuses"),
    ("archive member names are plain", MODULE + "vendor_plan",
     're.fullmatch(r"[\\w.+-]+(/[\\w.+-]+)*", name) is not None', "True",
     RUNTIME + "test_an_unsafe_archive_member_refuses"),
    ("archive member names never climb", MODULE + "vendor_plan",
     'and ".." not in PurePosixPath(name).parts', "and True",
     RUNTIME + "test_an_unsafe_archive_member_refuses"),
    ("group and other write cleared as CI clears them", MODULE + "vendor_plan",
     "mode = member.mode & 0o755", "mode = member.mode",
     RUNTIME + "test_the_pinned_package_is_planned_as_ci_extracts_it"),
    ("an unresolved dependency refuses", MODULE + "resolve", '"not found" not in output', "True",
     RUNTIME + "test_the_loader_trace_refuses_an_unresolved_dependency"),
    ("extensions enumerated over the unfiltered tree", MODULE + "runtime_plan",
     'sorted(library.rglob("*.so"))',
     'sorted(p for p in library.rglob("*.so") if not IGNORED & set(p.parts))',
     RUNTIME + "test_the_closure_plan_is_the_ci_rule"),
    ("excluded library names are not copied", MODULE + "runtime_plan",
     "if child.name in IGNORED:", "if False:", RUNTIME + "test_the_closure_plan_is_the_ci_rule"),
    ("a package's digest must match", MODULE + "attribution",
     "require(not candidates or actual in candidates,", "require(True,",
     RUNTIME + "test_a_file_that_differs_from_its_packages_digest_refuses"),
    ("merged-usr spellings are matched", MODULE + "attribution",
     "wanted[new + host.removeprefix(old)] = host", "pass",
     RUNTIME + "test_attribution_names_each_package_and_lists_the_unattributed"),
    ("the unattributed list is bounded", MODULE + "attribution",
     '"unattributed": unattributed[:UNATTRIBUTED_LIMIT],', '"unattributed": unattributed,',
     RUNTIME + "test_the_unattributed_list_is_bounded"),
    ("tree owner compared", MODULE + "compare", " or found[2] != owner", "",
     RUNTIME + "test_every_difference_in_a_tree_is_reported"),
    ("tree mode compared", MODULE + "compare", "found[:2] != reviewed",
     "found[1] != reviewed[1]", RUNTIME + "test_every_difference_in_a_tree_is_reported"),
    ("installed trees equal the plan", MODULE + "assess_launch",
     'entry.get("state") == "tree" and entry.get("different") == 0', "True",
     RUNTIME + "test_each_launch_fact_is_required"),
    ("operator-stores group", MODULE + "assess_launch", 'entry.get("gid") == content', "True",
     RUNTIME + "test_each_launch_fact_is_required"),
    ("launch destination owner", MODULE + "assess_launch", 'entry.get("uid") == ROOT_UID', "True",
     RUNTIME + "test_each_launch_fact_is_required"),
    ("both launch profiles in enforce mode", MODULE + "assess_launch",
     'all(f"{name} (enforce)" in profiles for name in LAUNCH_PROFILE_NAMES)', "True",
     RUNTIME + "test_both_launch_profiles_must_be_loaded_in_enforce_mode"),
    ("identity law separators", MODULE + "identity_digest", 'separators=(",", ":"), ', "",
     RUNTIME + "test_the_stdlib_identity_digest_is_constructicons"),
    ("a verifier's own observation survives", MODULE + "main", 'if "observed" not in record:',
     "if True:", RUNTIME + "test_a_verifiers_own_observation_survives_its_failure"),
)  # fmt: skip

# Linux-only: NOT PROVEN on other platforms is expected, never a kill.
LAUNCH_LINUX = (
    ("staged trees equal the plan", MODULE + "judge_launch",
     'require(not differences, f"the staged {tree} is not the reviewed plan")', "pass",
     RUNTIME + "test_staging_must_equal_the_recomputed_plan"),
    ("cp is a checked root tool", MODULE + "judge_launch", "(BWRAP_SOURCE, *LAUNCH_ROOT_TOOLS)",
     "(BWRAP_SOURCE, INSTALL, CAT, PARSER)",
     RUNTIME + "test_each_launch_precondition_refuses_judgement"),
    ("launch destinations are fresh", MODULE + "judge_launch", "absent(root / destination)", "True",
     RUNTIME + "test_each_launch_precondition_refuses_judgement"),
    ("no launch profile already loaded", MODULE + "judge_launch",
     "not loaded_among(listing, LAUNCH_PROFILE_NAMES)", "True",
     RUNTIME + "test_each_launch_precondition_refuses_judgement"),
    ("host sources are root's alone", MODULE + "launch_expectation",
     "        require_root_alone(source)", "        pass",
     RUNTIME + "test_each_launch_precondition_refuses_judgement"),
    ("the loader is root's alone", MODULE + "launch_expectation",
     "for path in (loader, root / LOADER_CACHE, root / ABI):",
     "for path in (root / LOADER_CACHE, root / ABI):",
     RUNTIME + "test_each_launch_precondition_refuses_judgement"),
    ("the writer never overwrites", MODULE + "materialize", "os.O_CREAT | os.O_EXCL | ",
     "os.O_CREAT | os.O_TRUNC | ", RUNTIME + "test_the_writer_never_overwrites"),
    ("verify recomputes, never reads staging", MODULE + "verify_launch",
     'record["observed"] = observe_launch(root, listing, expected)',
     'record["observed"] = observe_launch(root, listing, {'
     '"runtime": [e[:3] for e in tree_inventory(workspace / STAGING / "runtime")], '
     '"vendor": [e[:3] for e in tree_inventory(workspace / STAGING / "native-codex")]})',
     RUNTIME + "test_a_valid_installation_verifies_with_staging_deleted"),
    ("tree summaries are bounded", MODULE + "observe_launch",
     'entry["differences"] = differences[:TREE_SUMMARY]', 'entry["differences"] = differences',
     RUNTIME + "test_a_tree_summary_is_bounded"),
)  # fmt: skip

MUTANTS = (
    *(
        (label, MODULE + "prove", before, after, TESTS + test)
        for label, before, after, test in (
            (
                "exact commit syntax before git runs",
                're.fullmatch("[0-9a-f]{40}", commit) is not None',
                "True",
                "test_commit_must_be_exact_hex_before_git_runs",
            ),
            (
                "fetched main exists",
                "main.returncode == 0",
                "True",
                "test_a_repository_without_main_is_refused",
            ),
            (
                "first-parent line of the fetched main",
                'require(record["first_parent"],',
                "require(True,",
                "test_a_merged_branch_commit_off_the_first_parent_line_is_refused",
            ),
            (
                "regular non-executable tree mode",
                'entry[1] == b"100644"',
                "True",
                "test_each_artifact_must_be_a_regular_non_executable_blob",
            ),
            (
                "running script is the reviewed blob",
                "blobs[SCRIPT] == Path(__file__).read_bytes()",
                "True",
                "test_a_running_script_that_is_not_the_reviewed_blob_is_refused",
            ),
        )
    ),
    (
        "replacement refs ignored",
        MODULE + "git",
        '"--no-replace-objects", ',
        "",
        TESTS + "test_a_replacement_ref_cannot_substitute_an_artifact",
    ),
    (
        "grafts file disabled",
        MODULE + "run",
        "env=ENVIRONMENT,",
        'env={k: v for k, v in ENVIRONMENT.items() if k != "GIT_GRAFT_FILE"},',
        TESTS + "test_a_grafts_file_cannot_move_a_commit_onto_the_first_parent_line",
    ),
    (
        "profile list is non-empty and in the kernel's format",
        MODULE + "loaded_profiles",
        'bool(lines) and all(re.fullmatch(r"\\S.* \\([a-z]+\\)", line) for line in lines)',
        "True",
        TESTS + "test_an_empty_or_malformed_profile_list_proves_nothing",
    ),
    *(
        (label, MODULE + "assess", before, "True", TESTS + test)
        for label, before, test in (
            ("entry kind", 'entry.get("state") == kind', "test_each_observed_fact_is_required"),
            ("entry owner", 'entry.get("uid") == ROOT_UID', "test_each_observed_fact_is_required"),
            ("entry mode", 'entry.get("mode") == oct(mode)', "test_each_observed_fact_is_required"),
            ("entry content", "found == content", "test_each_observed_fact_is_required"),
            (
                "fixed inventory count",
                "checked == 4",
                "test_a_shrunken_inventory_is_never_assessed_installed",
            ),
            (
                "profiles loaded in enforce mode",
                "isinstance(profiles, list)\n"
                '        and all(f"{name} (enforce)" in profiles for name in PROFILE_NAMES)',
                "test_both_profiles_must_be_loaded_in_enforce_mode",
            ),
        )
    ),
    *(
        (label, MODULE + "main", before, after, TESTS + test)
        for label, before, after, test in (
            (
                "exit status follows the verdict",
                "return 0 if record[verdict] is True else 1",
                "return 0",
                "test_the_exit_status_follows_the_verdict",
            ),
            (
                "the verdict defaults to false",
                "verdict: False,",
                "verdict: True,",
                "test_a_command_that_records_nothing_reports_false",
            ),
            (
                "each command reports its own verdict",
                "VERDICTS[args.command]",
                '"installed"',
                "test_the_exit_status_follows_the_verdict",
            ),
            (
                "the profile list ends within its bound",
                "len(raw) <= LISTING_LIMIT",
                "True",
                "test_a_profile_list_beyond_its_bound_refuses_before_the_command",
            ),
            (
                "failure itemizes fresh residue",
                'record["observed"] = observer(ROOT, listing)',
                "pass",
                "test_the_exit_status_follows_the_verdict",
            ),
        )
    ),
    *LAUNCH_PORTABLE,
    # Linux-only below: NOT PROVEN on other platforms is expected, never a kill.
    (
        "never runs as root",
        MODULE + "require_unprivileged",
        "os.geteuid() != 0",
        "True",
        TESTS + "test_the_script_refuses_to_run_as_root",
    ),
    *(
        (label, MODULE + "require_custody", before, "True", TESTS + test)
        for label, before, test in (
            (
                "workspace is an absolute path",
                'workspace.is_absolute() and ".." not in workspace.parts',
                "test_the_workspace_must_be_private_to_this_account",
            ),
            (
                "workspace is private to this account",
                "stat.S_ISDIR(info.st_mode) and info.st_uid == owner and not info.st_mode & 0o077",
                "test_the_workspace_must_be_private_to_this_account",
            ),
            (
                "source repository is a real directory",
                "stat.S_ISDIR(os.lstat(repository).st_mode)",
                "test_the_workspace_must_be_private_to_this_account",
            ),
        )
    ),
    (
        "owned, unwritable, real ancestors",
        MODULE + "require_ancestors",
        "stat.S_ISDIR(info.st_mode) and info.st_uid in owners and not info.st_mode & 0o022",
        "True",
        TESTS + "test_every_destination_ancestor_is_a_root_owned_unwritable_directory",
    ),
    (
        "regular files read without following links",
        MODULE + "read_regular",
        "os.O_NOFOLLOW | ",
        "",
        TESTS + "test_each_staged_copy_must_be_the_blob_at_commit",
    ),
    (
        "staged copies are regular files",
        MODULE + "read_regular",
        "stat.S_ISREG(os.fstat(descriptor).st_mode)",
        "True",
        TESTS + "test_each_staged_copy_must_be_the_blob_at_commit",
    ),
    *(
        (label, MODULE + "require_root_alone", before, after, TESTS + test)
        for label, before, after, test in (
            (
                "a root input or tool is a root-owned unwritable file",
                "stat.S_ISREG(info.st_mode) and info.st_uid == ROOT_UID"
                " and not info.st_mode & 0o022",
                "True",
                "test_what_root_copies_or_runs_is_roots_alone",
            ),
            (
                "a root input or tool has root-only ancestors",
                '    require_ancestors(path, (ROOT_UID,), "root")',
                "    pass",
                "test_what_root_copies_or_runs_is_roots_alone",
            ),
        )
    ),
    (
        "only ENOENT is absence",
        MODULE + "absent",
        "except FileNotFoundError:",
        "except OSError:",
        TESTS + "test_an_unsearchable_destination_parent_is_not_absence",
    ),
    *(
        (label, MODULE + "judge", before, after, TESTS + test)
        for label, before, after, test in (
            (
                "staging is a real directory",
                "stat.S_ISDIR(os.lstat(staging).st_mode)",
                "True",
                "test_a_symlinked_staging_directory_is_refused",
            ),
            (
                "staged copies are the blobs at commit",
                "read_regular(staging / name) == blobs[source]",
                "read_regular(staging / name) is not None",
                "test_each_staged_copy_must_be_the_blob_at_commit",
            ),
            (
                "host bubblewrap pin",
                "sha256(bwrap) == BWRAP_SHA256",
                "True",
                "test_unpinned_host_bubblewrap_is_refused",
            ),
            (
                "fresh-only destinations",
                "absent(root / destination)",
                "True",
                "test_any_existing_destination_refuses_judgement",
            ),
            (
                "destination ancestors are root's alone",
                '(ROOT_UID,), "root")',
                '(ROOT_UID, os.geteuid()), "root")',
                "test_every_destination_ancestor_is_a_root_owned_unwritable_directory",
            ),
            (
                "bubblewrap and every root tool are checked",
                "        require_root_alone(root / path)",
                "        pass",
                "test_what_root_copies_or_runs_is_roots_alone",
            ),
            (
                "no qualification profile already loaded",
                "not loaded_among(listing, PROFILE_NAMES)",
                "True",
                "test_an_already_loaded_profile_refuses_judgement",
            ),
            (
                "only the qualification profiles block the qualification judge",
                "not loaded_among(listing, PROFILE_NAMES)",
                "not loaded_profiles(listing)",
                "test_loaded_launch_profiles_do_not_block_the_qualification_judge",
            ),
        )
    ),
    (
        "verified ancestors",
        MODULE + "verify",
        '        require_ancestors(root / destination, (ROOT_UID,), "root")',
        "        pass",
        TESTS + "test_verify_refuses_drift_after_installation",
    ),
    *LAUNCH_LINUX,
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
