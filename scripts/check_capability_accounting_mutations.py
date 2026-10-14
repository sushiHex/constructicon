"""Prove coherent accounting and truthful bounded previews by assertion."""

from _mutations import run

ACCOUNTING = "constructicon.substrate.journal._sqlite_accounting:capability_accounting_snapshot"
QUERY = "constructicon.api._control_queries:_ControlQueries.runs_result"
SNAPSHOT_TEST = "tests/substrate/journal/test_capability_accounting_snapshot.py::"
API_TEST = "tests/api/test_capability_accounting_result.py::"

MUTANTS = (
    (
        "public summary counts every pair rather than a bounded request batch",
        QUERY,
        'active_count=sum(item.state == "active" for item in accounting.items)',
        'active_count=sum(item.state == "active" for item in accounting.items[:100])',
        API_TEST + "test_result_summary_and_detail_are_complete_beyond_a_hundred",
    ),
    (
        "the v2 model itself requires an exact integer version",
        "constructicon.core.control:RunResultPreviewV2._exact_result_version",
        "if type(value) is not int or value != 2:",
        "if False:",
        "tests/core/test_capability_accounting_result.py::test_v2_model_itself_refuses_inexact_version[2.0]",
    ),
    (
        "accounting read keeps one SQLite snapshot",
        "constructicon.substrate.journal._sqlite_queries:_SqliteQueriesMixin.capability_accounting_snapshot",
        "with self._read() as connection:",
        "with self._connect() as connection:",
        SNAPSHOT_TEST + "test_accounting_snapshot_keeps_status_and_cut_before_concurrent_commit",
    ),
    (
        "accounting reverse inventory includes transition events",
        ACCOUNTING,
        "for row in selected_events:",
        "for row in ():",
        SNAPSHOT_TEST + "test_snapshot_scoped_reverse_edges_refuse_missing_pair[LeaseTransition]",
    ),
    (
        "batch prefetch retains foreign events naming the selected pair",
        ACCOUNTING,
        "for row in event_rows:\n        identity =",
        "for row in selected_events:\n        identity =",
        SNAPSHOT_TEST + "test_snapshot_retains_exact_foreign_pair_contradictions[LeaseTransition]",
    ),
    (
        "accounting compares its complete committed migration inventory",
        ACCOUNTING,
        "validate_accounting_run(connection, run_id, histories, through_event_seq=cut)",
        "pass  # missing legacy facts are not a complete empty inventory",
        SNAPSHOT_TEST + "test_snapshot_refuses_erased_eventless_history",
    ),
    (
        "accounting contains every pair rather than a request-sized preview",
        ACCOUNTING,
        "for history in sorted(histories, key=lambda h: (h.lease.lease_id, h.lease.acquisition_epoch)):",
        "for history in sorted(histories, key=lambda h: (h.lease.lease_id, h.lease.acquisition_epoch))[:100]:",
        SNAPSHOT_TEST + "test_accounting_snapshot_is_complete_beyond_a_hundred_pairs",
    ),
    (
        "failure item truncation is explicit",
        QUERY,
        " or len(failures) > 20",
        "",
        API_TEST + "test_result_failure_item_partiality_binds_at_twenty[21-True]",
    ),
    (
        "failure scan obtains affirmative evidence of omitted events",
        QUERY,
        "limit=1_001",
        "limit=1_000",
        API_TEST + "test_result_failure_scan_partiality_has_affirmative_extra_event[1001-True]",
    ),
    (
        "accounting detail resolves its immutable cut rather than latest state",
        "constructicon.api.detail:DetailResolver._resolve",
        "RunId(parts[0]), through_event_seq=cut,",
        "RunId(parts[0]), through_event_seq=None,",
        API_TEST + "test_accounting_chunks_keep_old_cut_after_close_resume_and_reopen",
    ),
    (
        "a clean missing run is proved before unrelated history is materialized",
        ACCOUNTING,
        "if projection is None:",
        "if projection is None:\n"
        '        connection.execute("SELECT * FROM capability_leases").fetchall()',
        "tests/substrate/journal/test_accounting_missing_run.py::"
        "test_missing_accounting_run_does_not_materialize_unrelated_history",
    ),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
