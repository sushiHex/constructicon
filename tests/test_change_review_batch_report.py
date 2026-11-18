"""The batch view reuses the actual private reply collector, then adds known subtotals."""

from __future__ import annotations

import copy
import json

import pytest
from scripts.ops import change_review_batch_report as report
from scripts.ops import change_review_reply as reply

from tests.substrate.test_codex_adapter import portable_binding_world
from tests.substrate.test_codex_adapter import substituted_guard as substituted_guard
from tests.test_change_review_input import source_world as source_world
from tests.test_change_review_reply import checked as checked
from tests.test_change_review_reply import produced as produced
from tests.test_change_review_reply import window

CODEX = "codex_fresh_thread_total_v1"
CLAUDE = "claude_main_loop_v1"


def metering(coverage="supported_observations", *, source=CODEX, inp=4, out=2,
             kind="observed"):
    groups = [] if coverage != "supported_observations" else [{
        "source": source, "intent_only": int(kind == "intent_only"),
        "unavailable": int(kind == "unavailable"), "partial": int(kind == "partial"),
        "observed": int(kind == "observed"),
        "known_input_tokens": inp, "known_output_tokens": out,
    }]
    return {
        "coverage": coverage, "through_event_seq": 10, "attempt_count": len(groups),
        "groups": groups,
        "detail": {"uri": "constructicon://runs/run-fixture/metering/10/0",
                   "digest": "sha256:" + "a" * 64, "media_type": "application/json"},
        "estimate": None, "estimate_coverage": "unknown",
        "confirmed_charge": None, "confirmed_charge_coverage": "unknown",
    }


def delivered(nonce, usage=None):
    return {"status": "delivered", "window": nonce, "run_id": "run-fixture",
            "accepted_read_sha256": "a" * 64, "metering": usage or metering(),
            "advice": {"advice": "private advice must never enter the report"}}


def fake_entries(tmp_path, monkeypatch, outcomes):
    entries = []
    for index in range(len(outcomes)):
        work = tmp_path / str(index)
        record = work / ("a" * 31 + format(index % 16, "x"))
        record.mkdir(parents=True)
        entries.append((work, record, work))
    by_work = {work: value for (work, _, _), value in zip(entries, outcomes, strict=True)}
    monkeypatch.setattr(reply, "collect", lambda work, record, packet: by_work[work])
    monkeypatch.setattr(reply, "_read", lambda path, limit, code: b"same packet bytes")
    return entries


def test_real_producer_and_collector_count_separate_windows_with_the_same_run_id(
    tmp_path, monkeypatch, substituted_guard, produced, checked, capsys,
):
    packet, _, _ = produced
    entries = []
    for name in ("first", "second"):
        root = tmp_path / name
        root.mkdir()
        # A fresh native window owns a fresh journal and closure authority.
        # Reusing the first closure would correctly refuse the closed acquisition.
        with monkeypatch.context() as patch:
            binding = portable_binding_world(root / "binding", patch)
            platform, _, outcome = window(root, patch, binding, answer="private answer")
            assert outcome.reason == "read-settled" and outcome.cleanup == "clean"
        entries.append((platform.custody, outcome.record, packet))
    originals = [reply.collect(*entry) for entry in entries]
    assert originals[0]["run_id"] == originals[1]["run_id"]
    result = report.collect([*entries, entries[0]])
    assert result["window_count"] == 2 and result["duplicate_input_count"] == 1
    assert result["recorded_attempt_count"] == 2
    assert result["coverage_counts"] == {"supported_observations": 2, "unmeasured": 0,
                                         "legacy_unmeasured": 0, "unavailable": 0}
    # This existing pinned peer emits no usage update. Its two real native
    # attempts count, while the missing token observations remain unknown.
    assert all(original["metering"]["groups"][0]["known_input_tokens"] is None
               for original in originals)
    assert result["groups"][0]["known_input_tokens"] is None
    for index, row in enumerate(result["windows"]):
        assert row["first_input_index"] == index + 1
        assert row["window"] == entries[index][1].name
        assert row["run_id"] == originals[index]["run_id"]
        assert row["accepted_read_sha256"] == originals[index]["accepted_read_sha256"]
        assert row["metering"] == {key: value for key, value in originals[index]["metering"].items()
                                   if key != "detail"}
    wire = reply._wire(result)
    assert len(wire) <= report.REPORT_LIMIT
    assert b"private answer" not in wire and str(tmp_path).encode() not in wire
    assert b'"advice"' not in wire
    args = [value for entry in entries for value in ("--window", *(str(path) for path in entry))]
    assert report.main(args) == 0
    assert json.loads(capsys.readouterr().out) == report.collect(entries)


def test_mixed_coverage_preserves_partial_axes_zero_and_each_source(tmp_path, monkeypatch):
    outcomes = [
        delivered("a" * 32, metering(inp=0, out=None, kind="partial")),
        delivered("b" * 32, metering(inp=None, out=None, kind="intent_only")),
        delivered("c" * 32, metering(source=CLAUDE, inp=None, out=7, kind="partial")),
        delivered("d" * 32, metering("legacy_unmeasured")),
        delivered("e" * 32, metering("unmeasured")),
        {"status": "not-delivered", "window": "f" * 32,
         "result": {"reason": "private error must never enter the report"}},
    ]
    result = report.collect(fake_entries(tmp_path, monkeypatch, outcomes))
    assert result["recorded_attempt_count"] == 3
    assert result["coverage_counts"] == {"supported_observations": 3, "unmeasured": 1,
                                         "legacy_unmeasured": 1, "unavailable": 1}
    assert result["groups"] == [
        {"source": CLAUDE, "intent_only": 0, "unavailable": 0, "partial": 1, "observed": 0,
         "known_input_tokens": None, "known_output_tokens": 7},
        {"source": CODEX, "intent_only": 1, "unavailable": 0, "partial": 1, "observed": 0,
         "known_input_tokens": 0, "known_output_tokens": None},
    ]
    assert result["windows"][-1]["metering"] is None
    assert result["estimate"] is result["confirmed_charge"] is result["elapsed_s"] is None
    assert result["estimate_coverage"] == result["confirmed_charge_coverage"] == "unknown"
    assert result["timing_coverage"] == "unavailable"
    assert result["backend_request_count"] is None
    assert b"private" not in reply._wire(result)


def test_unknown_usage_is_not_invented_as_zero(tmp_path, monkeypatch):
    entries = fake_entries(tmp_path, monkeypatch, [delivered("a" * 32, metering(
        inp=None, out=None, kind="unavailable"))])
    result = report.collect(entries)
    assert result["recorded_attempt_count"] == 1
    assert result["groups"][0]["known_input_tokens"] is None
    assert result["groups"][0]["known_output_tokens"] is None


def test_legacy_coverage_does_not_discard_any_schema_valid_recorded_group(tmp_path, monkeypatch):
    # Coverage is the producer's declaration, not a locally inferred zero rule.
    usage = {**metering(), "coverage": "legacy_unmeasured"}
    result = report.collect(fake_entries(tmp_path, monkeypatch, [delivered("a" * 32, usage)]))
    assert result["coverage_counts"]["legacy_unmeasured"] == 1
    assert result["recorded_attempt_count"] == 1
    assert result["groups"][0]["known_input_tokens"] == 4
    assert result["windows"][0]["metering"]["coverage"] == "legacy_unmeasured"


def test_canonical_window_dedup_and_conflicting_packet_or_reply_refusal(tmp_path, monkeypatch):
    item = delivered("a" * 32)
    entries = fake_entries(tmp_path, monkeypatch, [item])
    work, record, packet = entries[0]
    (work / "child").mkdir()
    alias = work / "child" / ".."
    monkeypatch.setattr(reply, "collect", lambda *args: item)
    result = report.collect([entries[0], (alias, alias / record.name, packet)])
    assert result["window_count"] == 1 and result["duplicate_input_count"] == 1
    assert result["recorded_attempt_count"] == 1
    values = iter([item, {**item, "accepted_read_sha256": "b" * 64}])
    monkeypatch.setattr(reply, "collect", lambda *args: next(values))
    with pytest.raises(reply.ReplyRefused, match=report.CONFLICT):
        report.collect(entries * 2)
    monkeypatch.setattr(reply, "collect", lambda *args: item)
    monkeypatch.setattr(reply, "_read", lambda path, limit, code: path.parent.name.encode())
    with pytest.raises(reply.ReplyRefused, match=report.CONFLICT):
        report.collect([entries[0], (work, record, work / "changed-packet")])


def test_same_nonce_in_different_custodies_does_not_deduplicate(tmp_path, monkeypatch):
    entries = fake_entries(tmp_path, monkeypatch, [delivered("a" * 32)] * 2)
    result = report.collect(entries)
    assert result["window_count"] == result["recorded_attempt_count"] == 2
    assert result["groups"][0]["known_input_tokens"] == 8
    assert [row["first_input_index"] for row in result["windows"]] == [1, 2]


@pytest.mark.parametrize("change", [
    lambda value: value.update(estimate={"currency": "USD", "amount": "1"}),
    lambda value: value.update(attempt_count=True),
    lambda value: value.update(attempt_count=2),
    lambda value: value["groups"].append(copy.deepcopy(value["groups"][0])),
    lambda value: value["groups"][0].update(known_input_tokens=-1),
])
def test_unsupported_or_incoherent_metering_is_refused_not_relabelled(
    tmp_path, monkeypatch, change,
):
    usage = metering()
    change(usage)
    entries = fake_entries(tmp_path, monkeypatch, [delivered("a" * 32, usage)])
    with pytest.raises(reply.ReplyRefused, match=report.INVALID):
        report.collect(entries)


def test_input_and_output_bounds_and_named_cli_refusal(tmp_path, monkeypatch, capsys):
    entries = fake_entries(tmp_path, monkeypatch, [delivered("a" * 32)] * report.MAX_WINDOWS)
    assert report.collect(entries)["window_count"] == report.MAX_WINDOWS
    collector = reply.collect
    monkeypatch.setattr(reply, "collect", lambda *args: pytest.fail("bound must precede reads"))
    for refused in ([], [*entries, entries[0]]):
        with pytest.raises(reply.ReplyRefused, match=report.BOUND):
            report.collect(refused)
    monkeypatch.setattr(reply, "collect", collector)
    monkeypatch.setattr(report, "REPORT_LIMIT", len(reply._wire(report.collect(entries))) - 1)
    with pytest.raises(reply.ReplyRefused, match=report.BOUND):
        report.collect(entries)
    monkeypatch.setattr(reply, "collect", lambda *args: (_ for _ in ()).throw(
        reply.ReplyRefused(reply.PACKET)))
    assert report.main(["--window", *(str(path) for path in entries[0])]) == 1
    assert json.loads(capsys.readouterr().out) == {"status": "refused", "reason": reply.PACKET}


def test_absent_identity_is_a_named_refusal(tmp_path):
    with pytest.raises(reply.ReplyRefused, match=report.IDENTITY):
        report.collect([(tmp_path / "absent", tmp_path / "record", tmp_path / "packet")])
