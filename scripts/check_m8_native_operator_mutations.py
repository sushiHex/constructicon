"""N1's schema-3 predicate, decoder, identity and description laws.

Run with ``uv run python scripts/check_m8_native_operator_mutations.py``. The
shared runner mutates only child-process code objects and requires an assertion
failure: a mutant that merely errors is NOT PROVEN, never a kill.
"""

import sys

from _mutations import run

POLICY = "constructicon.core.native_operator:NativeOperatorExecutorProfileV3.grant_faults"
PROFILE_DISPATCH = "constructicon.core.native_operator:_select_profile"
LAUNCH_DISPATCH = "constructicon.core.native_operator:_select_launch_identity"
BINDING = "constructicon.core.native_operator:operator_binding_digest"
REVISION = "constructicon.core.native_operator:NativeOperatorLaunchIdentityV3.revision"
POSTURES = "constructicon.core.native_operator:offered_postures"
NETWORKS = "constructicon.core.native_operator:NativeOperatorGrantPolicyV3._networks"
DESCRIBE = "constructicon.api.introspection:build_system_description"
PROVIDER = "tests.native_operator_world:FakeNativeOperatorProvider.unavailable_reasons"

CORE = "tests/core/test_native_operator_contracts.py::"
API = "tests/api/test_native_operator_admission.py::"

SHARED = CORE + "test_adapter_and_profile_share_every_native_grant_refusal"
PHYSICAL = CORE + "test_complete_native_policy_requires_every_physical_declaration"
PROFILE_ROUTE = CORE + "test_a_declared_three_is_never_routed_to_the_unversioned_parser"
PROFILE_VERSIONS = CORE + "test_profile_dispatch_selects_by_the_declared_version"
LAUNCH_VERSIONS = CORE + "test_launch_dispatch_selects_by_the_declared_version"
INGRESS = API + "test_unestablished_ingress_is_described_and_refused"

MUTANTS = (
    *(
        (name, POLICY, before, after, test)
        for name, before, after, test in (
            (
                "single posture",
                "if grants.posture is not self.posture:",
                "if False:",
                SHARED,
            ),
            (
                "mechanical posture",
                "elif not self.isolation.satisfies(grants.posture):",
                "elif False:",
                PHYSICAL,
            ),
            (
                "exact tools",
                "if tuple(sorted(set(grants.allowed_tools))) not in policy.tool_sets:",
                "if False:",
                SHARED,
            ),
            (
                "network allow is required",
                'if grants.network != "allow":',
                "if False:",
                SHARED,
            ),
            (
                "network enforcement",
                "if not self.isolation.network_enforced:",
                "if False:",
                PHYSICAL,
            ),
            (
                "environment",
                "if unsupported:",
                "if False:",
                SHARED,
            ),
            (
                "explicit listed effort",
                "if grants.effort is None or grants.effort not in self.accepted_efforts:",
                "if False:",
                SHARED,
            ),
            (
                "explicit model",
                'if selection.kind != "explicit" or not (selection.model or "").strip():',
                "if False:",
                SHARED,
            ),
            (
                "finite model inventory",
                "elif selection.model not in policy.model_ids:",
                "elif False:",
                SHARED,
            ),
        )
    ),
    (
        "native adapter uses the one predicate",
        "constructicon.substrate.executors.fake_native_operator:"
        "FakeNativeOperatorExecutor.validate_grants",
        "return self._profile.grant_faults(grants)",
        "return ()",
        SHARED,
    ),
    (
        "declared three reaches the native record",
        PROFILE_DISPATCH,
        "return NativeOperatorExecutorProfileV3.model_validate(value)",
        "return ExecutorProfile.model_validate(value)",
        PROFILE_ROUTE,
    ),
    (
        "unsupported version has no compatibility fallback",
        PROFILE_DISPATCH,
        "raise ValueError(refusal)",
        "return ExecutorProfile.model_validate(value)",
        PROFILE_VERSIONS,
    ),
    (
        "a string version is not an integer version",
        PROFILE_DISPATCH,
        "if type(version) is int and version == 3:",
        'if version == 3 or version == "3":',
        CORE + "test_a_string_version_never_selects_the_native_profile",
    ),
    (
        "an absent launch version is not schema one",
        LAUNCH_DISPATCH,
        "if type(version) is int and version == 1:",
        "if version is None or (type(version) is int and version == 1):",
        LAUNCH_VERSIONS,
    ),
    (
        "a schema-one identity refuses a hybrid profile",
        LAUNCH_DISPATCH,
        'if isinstance(raw_profile, Mapping) and "schema_version" in raw_profile:',
        "if False:",
        CORE + "test_a_schema_one_launch_identity_refuses_a_hybrid_native_profile",
    ),
    (
        "maintenance generation is bound",
        BINDING,
        '"generation": maintenance_generation,',
        '"generation": 1,',
        CORE + "test_operator_binding_digest_binds_key_generation_and_instance",
    ),
    (
        "native law identity",
        REVISION,
        '"law": NATIVE_OPERATOR_LAW_REVISION,',
        '"law": "unversioned",',
        CORE + "test_native_law_is_bound_into_every_published_revision",
    ),
    (
        "one posture is published as one posture",
        POSTURES,
        "return frozenset({profile.posture})",
        "return frozenset()",
        CORE + "test_one_profile_offers_exactly_one_posture",
    ),
    (
        "network inventory is exactly allow",
        NETWORKS,
        'if values != ("allow",):',
        "if False:",
        CORE + "test_policy_inventory_is_an_exact_normalized_set",
    ),
    (
        "described availability follows the reasons",
        DESCRIBE,
        "available=not unavailability[capability_id],",
        "available=True,",
        INGRESS,
    ),
    (
        "described reasons are published",
        DESCRIBE,
        "unavailable_reasons=tuple(unavailability[capability_id]),",
        "unavailable_reasons=(),",
        INGRESS,
    ),
    (
        "ingress establishment is an assembly fact",
        PROVIDER,
        "if self._ingress_established:",
        "if True:",
        INGRESS,
    ),
)

if __name__ == "__main__":
    status = run(MUTANTS)
    if status == 0 and len(sys.argv) == 1:
        print(f"{len(MUTANTS)}/{len(MUTANTS)} mutants KILLED by assertion.")
    raise SystemExit(status)
