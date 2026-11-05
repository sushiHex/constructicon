"""Affirm the finite journal contents before any process-local worker starts."""

from typing import Literal

from constructicon.api._m9.evidence import CASE_POLICY, TrialIdentity, curator_graph, proposer_graph
from constructicon.api._m9.fixture import report_graph
from constructicon.core.address import RunId
from constructicon.core.control import command_id_for, run_id_for_command
from constructicon.core.manifest import parse_manifest_json
from constructicon.core.run import RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal


def selector_run(trial: TrialIdentity) -> RunId:
    return run_id_for_command(command_id_for(
        "static:m9-trial-selector", "runs_start", trial.key("select"),
    ))


def before_startup(
    journal: SqliteJournal, trial: TrialIdentity, *,
    role: Literal["evaluate", "select", "issue"] = "evaluate",
) -> None:
    # Lazy imports break the assembly cycle; these are fixed constructors,
    # never caller-provided recovery predicates or arbitrary graph hooks.
    from constructicon.api._m9.issuer import operator_issuer_graph
    from constructicon.api._m9.proposer import graph as selector_graph
    from constructicon.api._m9.proposer import retained

    if role not in ("evaluate", "select", "issue"):
        raise ValueError("M9_STARTUP_UNKNOWN_ASSEMBLY")
    expected = {}
    preparation = set()
    issuance = None
    for stage, operation, graph in (
        *((f"source-{case.evidence_id}", "runs_start", report_graph())
          for case, _, _ in CASE_POLICY),
        ("seal", "runs_start", curator_graph()),
        ("propose", "runs_start", proposer_graph()),
        *((f"{member}-{case.evidence_id}", "runs_counterfactual", report_graph())
          for case, _, split in CASE_POLICY if split == "held"
          for member in ("baseline", "candidate")),
        ("issue", "runs_start", operator_issuer_graph()),
    ):
        run = run_id_for_command(command_id_for(
            "static:m9-trial-operator", operation, trial.key(stage),
        ))
        expected[run] = graph
        if stage.startswith("source-") or stage == "seal":
            preparation.add(run)
        elif stage == "issue":
            issuance = run
    selected = selector_run(trial)
    expected[selected] = selector_graph()
    records = journal.run_records(limit=len(expected) + 1)
    if len(records) > len(expected):
        raise ValueError("M9_STARTUP_RUN_INVENTORY_EXCEEDED")
    for record in records:
        raw = journal.load_manifest_json(record.manifest_hash)
        if record.run_id not in expected or raw is None:
            raise ValueError("M9_STARTUP_UNALLOWLISTED_RUN")
        manifest = parse_manifest_json(raw)
        if (manifest.manifest_hash != record.manifest_hash
                or manifest.source_graph != expected[record.run_id]):
            raise ValueError("M9_STARTUP_RUN_GRAPH_DRIFT")
        if (record.run_id == issuance and role != "issue"
                and record.status in (RunStatus.PENDING, RunStatus.RUNNING, RunStatus.PARKED)):
            raise ValueError("M9_STARTUP_ISSUANCE_ASSEMBLY_REQUIRED")
        if record.run_id == selected:
            # Even a checkpoint-looking interrupted run is deliberately stopped:
            # cleanup and terminal success must have been affirmatively observed.
            retained(journal, record.run_id)
        if role == "select":
            if record.run_id not in preparation:
                raise ValueError("M9_SELECTOR_NONPREPARATION_RUN")
            if record.status != RunStatus.SUCCEEDED:
                raise ValueError("M9_SELECTOR_REQUIRES_COMPLETED_PREPARATION")
