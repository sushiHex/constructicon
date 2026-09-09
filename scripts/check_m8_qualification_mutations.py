"""Portable refusal-law mutations; no mutation is credited as a Linux proof."""

from _mutations import run

MODULE = "scripts.ci.qualify_m8_runner:"
TESTS = "tests/test_m8_runner_qualification.py::"

MUTANTS = (
    *(
        (label, MODULE + "validate_child", condition, "True", TESTS + test)
        for label, condition, test in (
            (
                "namespace separation",
                'all(child["namespaces"][n] != host[n] for n in NAMESPACES)',
                "test_every_namespace_must_be_distinct",
            ),
            (
                "UID/GID",
                'child["uid"] == uid and child["gid"] == gid',
                "test_each_observed_boundary_is_required",
            ),
            (
                "read-only errno",
                'child["write_errno"] == 30',
                "test_each_observed_boundary_is_required",
            ),
            (
                "host visibility",
                'not child["host_home_visible"] and not child["sys_visible"]',
                "test_each_observed_boundary_is_required",
            ),
            (
                "privilege reduction",
                '"NoNewPrivs:\\t1" in child["status"] and '
                '"CapEff:\\t0000000000000000" in child["status"]',
                "test_each_observed_boundary_is_required",
            ),
            (
                "identity mapping",
                'child["uid_map"].split() == [str(uid), "0", "1"]',
                "test_each_observed_boundary_is_required",
            ),
            (
                "policy attachment",
                'child["apparmor"] == CHILD_PROFILE',
                "test_each_observed_boundary_is_required",
            ),
            (
                "nested denial",
                'namespace_refused(child["nested_returncode"], child["nested_stderr"])',
                "test_each_observed_boundary_is_required",
            ),
            (
                "network interface",
                'interfaces == ["lo"]',
                "test_each_observed_boundary_is_required",
            ),
        )
    ),
    *(
        (
            label,
            MODULE + "artifact_digest",
            condition,
            "True",
            TESTS + "test_artifacts_require_ownership_mode_and_reviewed_bytes",
        )
        for label, condition in (
            ("artifact owner", "metadata.st_uid == 0"),
            ("artifact mode", "metadata.st_mode & 0o6022 == 0"),
            ("artifact bytes", "digest == expected"),
        )
    ),
    *(
        (label, MODULE + "qualify", condition, "True", TESTS + test)
        for label, condition, test in (
            (
                "root refusal",
                "uid != 0 and gid != 0",
                "test_root_is_never_a_qualification_fallback",
            ),
            (
                "sudo refusal",
                'run(["/usr/bin/sudo", "-n", "/usr/bin/true"]).returncode != 0',
                "test_host_refusals_precede_namespace_launch",
            ),
            (
                "AppArmor prerequisite",
                'evidence["apparmor_enabled"] == "Y"',
                "test_host_refusals_precede_namespace_launch",
            ),
            (
                "restriction prerequisite",
                'evidence["userns_restriction"] == "1"',
                "test_host_refusals_precede_namespace_launch",
            ),
            (
                "package pin",
                "package.returncode == 0 and package.stdout == PACKAGE",
                "test_host_refusals_precede_namespace_launch",
            ),
        )
    ),
    (
        "permission error is the namespace operation",
        MODULE + "namespace_refused",
        "stderr.strip() in (",
        '"Permission denied" in stderr or stderr.strip() in (',
        TESTS + "test_namespace_refusal_names_the_operation",
    ),
    (
        "truthful exit status",
        MODULE + "main",
        'return 0 if evidence["qualified"] else 1',
        "return 0",
        TESTS + "test_report_cannot_claim_production_availability",
    ),
    (
        "no production availability",
        MODULE + "main",
        '"production_available": False',
        '"production_available": True',
        TESTS + "test_report_cannot_claim_production_availability",
    ),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
