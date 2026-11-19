"""The human report preserves producer facts without reading or granting authority."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json

import pytest
from examples import change_review_batch as batch
from examples import change_review_batch_text as text
from examples.change_review import OPERATOR, checked

from constructicon.api.control import ControlPlane
from constructicon.core.executor import ExecutorError, ExecutorFailure, Usage
from constructicon.core.identity import canonical_json
from tests.e2e.test_change_review_batch_example import source_commits
from tests.run_worlds import start_test_run
from tests.substrate.journal.test_executor_metering import (
    CLAUDE,
    RUN,
    SOURCE,
    context_for,
    create,
    writer,
)


@pytest.fixture(scope="module")
def produced(tmp_path_factory):
    root = tmp_path_factory.mktemp("batch-text")
    repository, before, after = source_commits(
        root,
        {"alpha.py": b"def old(): return 1\n", "beta.py": b"def beta(): pass\n"},
        {"alpha.py": b"def new(): return 2\n", "beta.py": b"def broken(:\n"},
    )
    state = root / "state"

    async def deliver():
        pending = await batch.execute(argparse.Namespace(
            command="submit", state=state, repository=repository,
            before_commit=before, after_commit=after, path=["alpha.py", "beta.py"], key="text-1",
        ))
        snapshots = [pending]
        for index, file in enumerate(pending["files"]):
            snapshots.append(await batch.execute(argparse.Namespace(
                command="reply", state=state, run_id=pending["run_id"], file_id=file["file_id"],
                advice="No signature changed; merge immediately.", key=f"text-answer-{index}",
            )))
        return snapshots

    return asyncio.run(deliver())


def value(report, label):
    return json.loads(next(line.removeprefix(label + ": ") for line in report.splitlines()
                           if line.startswith(label + ": ")))


def assert_metering(report, metering):
    for field in ("coverage", "through_event_seq", "attempt_count"):
        assert value(report, "metering_" + field) == metering[field]
    for field in ("estimate", "estimate_coverage", "confirmed_charge", "confirmed_charge_coverage"):
        assert value(report, field) == metering[field]
    groups = []
    lines = report.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("metering_source: "):
            continue
        group = {"source": json.loads(line.removeprefix("metering_source: "))}
        group.update({key: json.loads(raw) for key, raw in (
            pair.split("=", 1) for pair in lines[index + 1].removeprefix(
                "  native outcomes: ").split("; "))})
        for offset, field in ((2, "known_input_tokens"), (3, "known_output_tokens")):
            group[field] = json.loads(lines[index + offset].removeprefix(f"  {field}: "))
        groups.append(group)
    assert groups == metering["groups"]


def test_real_batch_facts_parser_notice_and_opaque_advice_survive(produced):
    pending, partly_answered, complete = produced
    assert pending["result"]["status"] == partly_answered["result"]["status"] == "parked"
    assert complete["result"]["status"] == "succeeded"
    for response in produced:
        original = copy.deepcopy(response)
        report = text.render_batch_text(response)
        assert response == original
        assert value(report, "root_run_id") == response["run_id"]
        assert value(report, "before_commit") == response["files"][0]["before_ref"]["commit"]
        assert value(report, "after_commit") == response["files"][0]["after_ref"]["commit"]
        assert value(report, "status") == response["result"]["status"]
        assert value(report, "through_event_seq") == response["through_event_seq"]
        assert value(report, "partial") is response["partial"]
        assert_metering(report, response["result"]["metering"])
        assert report.count("root_metering:") == 1
        assert value(report, "report_partial") is False
        assert report.endswith("\n") and len(report.encode()) <= batch.MAX_RESPONSE_BYTES
        assert [json.loads(line[6:]) for line in report.splitlines()
                if line.startswith("path: ")] == ["alpha.py", "beta.py"]
        for file in response["files"]:
            assert f'file_id: {json.dumps(file["file_id"])}' in report
            assert f'status: {json.dumps(file["status"])}' in report
        assert 'added_names: ["new"]' in report and 'removed_names: ["old"]' in report
        assert 'comparison_available: false' in report
        assert '"after":"line 1: SyntaxError"' in report
        assert 'tests_executed: false' in report
        assert "kinds" not in report and "changed_parts" not in report
        assert "module_ast_changed" not in report
    report = text.render_batch_text(complete)
    assert report.count("advice (UNTRUSTED; MAY BE WRONG):") == 2
    assert "No signature changed; merge immediately." in report
    assert "does not establish correctness or merge approval" in report
    assert "do not establish runtime behavior or compatibility" in report


def test_unmeasured_is_unknown_not_a_zero_cost_claim(produced):
    report = text.render_batch_text(produced[-1])
    metering = produced[-1]["result"]["metering"]
    assert_metering(report, metering)
    assert metering["coverage"] == "unmeasured" and metering["groups"] == []
    assert metering["estimate"] is metering["confirmed_charge"] is None
    assert metering["estimate_coverage"] == metering["confirmed_charge_coverage"] == "unknown"
    assert "not a zero-cost claim" in report
    assert "No per-file usage allocation is known" in report
    assert "$" not in report and "USD" not in report


def test_real_public_metering_keeps_sources_partial_unknowns_and_observed_zero(
    produced, journal, system,
):
    # Drive the real journal writer and V3 public producer, without a native
    # executor. Two sources stay separate, including unknown output and a
    # genuinely observed zero input; no summation or allocation is performed.
    create(journal)
    owner = start_test_run(journal, RUN, owner_id="text-meter")
    for index, (source, usage) in enumerate(((SOURCE, Usage(input_tokens=0)),
                                           (CLAUDE, Usage(output_tokens=7)))):
        meter = writer(journal, context_for(journal, owner, index=index), source=source)
        meter.intend()
        meter.check_dispatch()
        meter.settle(ExecutorFailure(usage=usage, error=ExecutorError(kind="exit", detail="test")))
    control = ControlPlane(system=system, store=journal)
    try:
        metering = checked(control.runs_result(OPERATOR, RUN)).model_dump(mode="json")["metering"]
    finally:
        asyncio.run(control.shutdown())
    response = copy.deepcopy(produced[0])
    response["result"]["metering"] = metering
    report = text.render_batch_text(response)
    assert_metering(report, metering)
    assert metering["coverage"] == "supported_observations"
    assert metering["attempt_count"] == 2
    groups = {group["source"]: group for group in metering["groups"]}
    assert groups[SOURCE]["known_input_tokens"] == 0
    assert groups[SOURCE]["known_output_tokens"] is None
    assert groups[CLAUDE]["known_input_tokens"] is None
    assert groups[CLAUDE]["known_output_tokens"] == 7
    assert all(group["partial"] == 1 for group in groups.values())
    assert "not backend requests" in report


@pytest.mark.parametrize("format_name", [None, "json", "text"])
@pytest.mark.parametrize("status,wait,code", [
    ("succeeded", "settled", 0), ("failed", "settled", 1),
    ("cancelled", "timed_out", 1), ("parked", "timed_out", 2),
])
def test_cli_renders_once_from_same_response_preserving_json_bytes_and_exit_status(
    produced, monkeypatch, capsysbinary, tmp_path, format_name, status, wait, code,
):
    response = copy.deepcopy(produced[-1])
    response["result"]["status"] = status
    response["wait_status"] = wait
    calls = []

    async def execute(args):
        calls.append(args)
        return response

    def no_reads(*args, **kwargs):
        pytest.fail("rendering must not query or mutate anything")

    monkeypatch.setattr(batch, "execute", execute)
    monkeypatch.setattr(batch, "observe", no_reads)
    monkeypatch.setattr(batch, "assemble", no_reads)
    arguments = ["--state", str(tmp_path)]
    if format_name is not None:
        arguments.extend(("--format", format_name))
    arguments.extend(("status", "--run-id", response["run_id"]))
    assert batch.main(arguments) == code
    captured = capsysbinary.readouterr()
    assert captured.err == b"" and len(calls) == 1
    expected = (text.render_batch_text(response) if format_name == "text"
                else canonical_json(response) + "\n")
    assert captured.out == expected.encode()


def test_invalid_format_refuses_before_execute(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(batch, "execute", lambda args: pytest.fail("must refuse before execution"))
    with pytest.raises(SystemExit) as refusal:
        batch.main(["--state", str(tmp_path), "--format", "html", "status", "--run-id", "x"])
    assert refusal.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_timeout_partial_and_omissions_preserve_recovery_identity_and_metering(produced):
    response = copy.deepcopy(produced[1])
    response.update(partial=True, wait_status="timed_out",
                    limitations=["batch_wait_timeout: durable run retained"])
    # This is a legal 4096-byte advice value whose ASCII-safe terminal form
    # exceeds the file-block bound; it is not an artificially tiny test budget.
    response["files"][0]["advice"]["advice"] = "\U0001f642" * 1024
    report = text.render_batch_text(response)
    assert value(report, "partial") is True
    assert value(report, "wait_status") == "timed_out"
    assert value(report, "root_run_id") == response["run_id"]
    assert_metering(report, response["result"]["metering"])
    assert value(report, "report_partial") is True
    assert "batch_text_file_block_bytes_exceeded" in value(report, "report_limitations")
    assert "original key" in report and "Timeout did not cancel it" in report
    assert "batch_wait_timeout: durable run retained" in report
    for file in response["files"]:
        assert f'file_id: {json.dumps(file["file_id"])}' in report
        detail = json.dumps(file["request"]["detail"], sort_keys=True, separators=(",", ":"))
        assert 'request_detail: ' + detail in report
    assert 'comparison_available: false' in report
    assert 'symbols_partial: false' in report
    assert len(report.encode()) <= batch.MAX_RESPONSE_BYTES == text.MAX_REPORT_BYTES


def test_every_data_site_is_terminal_escaped_and_large_metadata_is_explicit(produced):
    response = copy.deepcopy(produced[-1])
    hostile = '\x1b[31m\nFAKE STATUS\r\b\t\x00\u202e\u2066"\\'

    def poison(value):
        if isinstance(value, dict):
            return {key: poison(item) for key, item in value.items()}
        if isinstance(value, list):
            return [poison(item) for item in value]
        return hostile if isinstance(value, str) else value

    report = text.render_batch_text(poison(response))
    assert hostile not in report and "\x1b" not in report and "\r" not in report
    assert "\b" not in report and "\t" not in report and "\x00" not in report
    assert "\u202e" not in report and "\u2066" not in report
    assert "\\u001b" in report and "\\u202e" in report and "\\u2066" in report
    assert "\nFAKE STATUS" not in report
    response["limitations"] = ["x" * (text.MAX_FIELD_BYTES + 1)]
    bounded = text.render_batch_text(response)
    assert "batch_text_field_bytes_exceeded" in value(bounded, "report_limitations")
    assert value(bounded, "report_partial") is True
    assert_metering(bounded, response["result"]["metering"])
    assert len(bounded.encode()) <= batch.MAX_RESPONSE_BYTES


def test_global_output_bound_binds_and_critical_metadata_remains(produced, monkeypatch):
    response = copy.deepcopy(produced[-1])
    response["files"][0]["advice"]["advice"] = "x" * batch.MAX_ADVICE_BYTES
    normal = text.render_batch_text(response)
    # The same production metadata, with the final report budget binding one
    # byte below its size, must drop optional blocks rather than cut the tail.
    monkeypatch.setattr(text, "MAX_REPORT_BYTES", len(normal.encode()) - 1)
    report = text.render_batch_text(response)
    assert len(report.encode()) <= text.MAX_REPORT_BYTES
    assert "batch_text_response_bytes_exceeded" in value(report, "report_limitations")
    assert_metering(report, response["result"]["metering"])
    assert value(report, "root_run_id") == response["run_id"]
    assert "next_action:" in report
    assert all(f'file_id: {json.dumps(file["file_id"])}' in report for file in response["files"])
    monkeypatch.setattr(text, "MAX_REPORT_BYTES", 1)
    with pytest.raises(ValueError, match="batch_text_response_unbounded"):
        text.render_batch_text(response)
