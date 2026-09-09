"""PR A's policy, identity, and materialization proofs; no Linux claim.

Run with ``uv run python scripts/check_m8_mutations.py``. The shared runner
mutates only child-process code objects and requires an assertion failure.
"""

from _mutations import run

POLICY = "constructicon.core.executor:ExecutorProfile.grant_faults"
COHERENCE = "constructicon.runtime.registry:CapabilityDescriptor.executor_incoherence"
CORE = "tests/core/test_executor_policy.py::"
API = "tests/api/test_executor_admission.py::"
LIFECYCLE = "tests/runtime/test_materialization.py::"

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
        "                    await acquisition.materialize()",
        "if acquisition.materialize is not None:\n"
        "                    await acquisition.materialize()\n"
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
)

if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
