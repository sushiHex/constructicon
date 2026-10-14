"""Prove administrative disposal boundaries with assertion failures only."""

from _mutations import run

CORE = "constructicon.core.control:"
CONTROL_STORE = "constructicon.substrate.journal._sqlite_control:_SqliteControlMixin."
DISPOSAL_STORE = "constructicon.substrate.journal._sqlite_capability_disposal:"
API_TEST = "tests/api/test_capability_disposal.py::"
STORE_TEST = "tests/substrate/journal/test_sqlite_capability_disposal.py::"

MUTANTS = (
    (
        "disposal pairs retain canonical ordering",
        CORE + "CapabilityDisposalRequest._canonical_pairs",
        "return tuple(sorted(value, key=lambda pair: (pair.lease_id, pair.acquisition_epoch)))",
        "return value",
        "tests/core/test_capability_disposal.py::test_disposal_request_canonicalizes_pair_order_without_repairing_members",
    ),
    (
        "duplicate pairs are refused rather than coalesced",
        CORE + "CapabilityDisposalRequest._canonical_pairs",
        "if len(set(identities)) != len(identities):",
        "if False:",
        "tests/core/test_capability_disposal.py::test_disposal_request_canonicalizes_pair_order_without_repairing_members",
    ),
    (
        "receipt extent is refused before any range expansion",
        CORE + "CapabilityDisposalRecorded._complete_contiguous_batch",
        "if self.audit_event_seq - self.before_event_seq != len(self.pairs) + 1:",
        "if False:",
        "tests/core/test_capability_disposal.py::test_disposal_receipt_rejects_an_extent_larger_than_its_bounded_batch",
    ),
    (
        "administrative disposal refuses operators before startup and command claim",
        CORE + "scope_refusal",
        "if actor.allows(required):",
        "if required == ADMIN_SCOPE or actor.allows(required):",
        API_TEST + "test_disposal_admin_gate_precedes_startup_and_claim[actor0]",
    ),
    (
        "a positive disposal receipt wins before fresh baseline comparison",
        CONTROL_STORE + "capability_disposal_apply",
        "return previous",
        "return CapabilityDisposalSuperseded()",
        STORE_TEST + "test_admin_disposal_is_one_atomic_batch_with_historical_receipt",
    ),
    (
        "supersession rejection requires positively advanced durable fences",
        "constructicon.substrate.journal._sqlite_commands:_require_disposal_command",
        'or (run["owner_epoch"] == plan.owner_epoch\n'
        '                    and run["next_event_seq"] == plan.baseline_event_seq)',
        "or False",
        STORE_TEST + "test_disposal_refusal_needs_positive_drift_not_just_missing_receipt",
    ),
    (
        "public disposal detail never forwards the private administrative reason",
        "constructicon.api.detail:DetailResolver._resolve",
        'return receipt.model_dump(mode="json")',
        'return {**receipt.model_dump(mode="json"), '
        '"reason": self._store.command(receipt.command_id).request["reason"]}',
        API_TEST + "test_public_disposal_bytes_and_hashes_cannot_enumerate_private_reasons",
    ),
    (
        "a bounded disposal batch shares one whole-journal history proof",
        DISPOSAL_STORE + "DisposalReadProofs.run_histories",
        "if run_id not in self.histories:",
        "if True:",
        STORE_TEST + "test_disposed_batch_accounting_prefetches_whole_journal_only_once",
    ),
    (
        "disposal reasons reject scalar control characters",
        CORE + "CapabilityDisposalRequest._administrative_text",
        "if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):",
        "if False:",
        "tests/core/test_capability_disposal.py::test_disposal_request_refuses_invalid_input[change6]",
    ),
    (
        "expired non-null run ownership receives a typed admission refusal",
        "constructicon.api._control_commands:_CommandExecutor.runs_dispose_capabilities",
        "elif snapshot.run.owner_id is not None or snapshot.run.lease_expires_at is not None:",
        "elif False:",
        API_TEST + "test_disposal_refuses_even_an_expired_nonnull_worker_owner",
    ),
    (
        "a worker release never reverses epoch-based disposal supersession",
        CONTROL_STORE + "capability_disposal_apply",
        "if (current.owner_epoch > plan.owner_epoch\n"
        "                or current.event_seq > plan.baseline_event_seq):",
        "if current.event_seq > plan.baseline_event_seq:",
        API_TEST + "test_superseded_disposal_comparison_crash_uses_plan_refusal_after_later_release",
    ),
    (
        "point receipt proof permits a lawful staged terminal-event transaction",
        DISPOSAL_STORE + "_project_disposal_receipt",
        "run = capability_run_world_row(connection, plan.run_id)",
        "run = accounting_run_row(connection, plan.run_id)",
        STORE_TEST + "test_disposed_acquisitions_permit_a_lawful_terminal_transition",
    ),
    (
        "receipt point reads prove the private disposal relationship hash",
        DISPOSAL_STORE + "_project_disposal_receipt",
        "require_durable_fact_seal(\n"
        "        connection,\n"
        "        family=DISPOSAL_FAMILY,\n"
        "        fact_key=command_id,\n"
        "        selector=event_fact_key(plan.run_id, expected_seq),\n"
        "        fact_hash=disposal_relationship_hash(command_row, audit_row, tuple(transitions)),\n"
        "    )",
        "pass",
        STORE_TEST + "test_disposal_damage_refuses_every_independent_public_projection"
        "[receipt-receipt_hash]",
    ),
    (
        "a coherently resealed disposal plan still binds the claimed private reason",
        CORE + "validated_capability_disposal_command",
        "or plan.run_id != request.run_id or plan.reason != request.reason",
        "or plan.run_id != request.run_id",
        STORE_TEST + "test_disposal_relationship_rejects_resealed_primary_fact_contradictions"
        "[reason]",
    ),
    (
        "receipt baseline is reconstructed rather than trusted from resealed plan bytes",
        DISPOSAL_STORE + "_project_disposal_receipt",
        "if canonical_json(baseline) != canonical_json(planned.fact):",
        "if False:",
        STORE_TEST + "test_disposal_relationship_rejects_resealed_primary_fact_contradictions"
        "[row_baseline]",
    ),
    (
        "a retained disposal relationship independently refuses an erased command",
        "constructicon.substrate.journal._sqlite_commands:command_for_id",
        '"capability_disposal",',
        '"not_a_disposal_family",',
        STORE_TEST + "test_erased_disposal_command_and_phase_seals_are_not_absence"
        "[command-relationship]",
    ),
    (
        "a retained public disposal audit independently refuses an erased command",
        "constructicon.substrate.journal._sqlite_commands:command_for_id",
        "if not isinstance(owner, str) or owner == command_id:",
        "if not isinstance(owner, str):",
        STORE_TEST + "test_erased_disposal_command_and_phase_seals_are_not_absence"
        "[command-audit]",
    ),
    (
        "an erased disposal plan cannot return before positive receipt projection",
        "constructicon.substrate.journal._sqlite_commands:_require_disposal_command",
        "receipt = project_disposal_receipt(connection, record.command_id)",
        "if record.plan is None:\n"
        "        return\n"
        "    receipt = project_disposal_receipt(connection, record.command_id)",
        STORE_TEST + "test_disposal_damage_refuses_every_independent_public_projection"
        "[command-plan_and_seal]",
    ),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
