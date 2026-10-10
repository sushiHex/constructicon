"""WRITE host arguments cannot quietly select legacy defaults or widen budgets."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.api import qualification
from constructicon.core.errors import ContractViolation
from constructicon.core.manifest import source_graph_hash_for
from tests.core.test_qualification_write import write

MINT = [
    "mint", "--session", "s", "--store-key", "k", "--sealed", "g",
    "--qualification", "q", "--state", "t", "--authorization-id", "a",
    "--actor", "operator:qualification", "--key", "k", "--journal", "/j",
]


@pytest.mark.parametrize(
    "extra",
    [[], ["--attempt-record", "/a"], ["--fixture", "/f"]],
)
def test_write_mint_requires_both_record_and_fixture_before_assembly(monkeypatch, extra):
    monkeypatch.setattr(qualification, "mint", lambda _: pytest.fail("minted"))
    with pytest.raises(SystemExit) as stopped:
        qualification.main([*MINT, "--stage", "qualification-write", *extra])
    assert stopped.value.code == 2


def test_write_mint_reaches_only_the_explicit_write_stage(monkeypatch, capsys):
    assert "qualification-write" in qualification.STAGES
    seen = []

    class Result:
        def model_dump_json(self):
            return '{"fixture":"pinned"}'

    def mint(arguments):
        seen.append(arguments)
        return Result()

    monkeypatch.setattr(qualification, "mint", mint)
    assert qualification.main([
        *MINT, "--stage", "qualification-write", "--fixture", "/f",
        "--attempt-record", "/a",
    ]) == 0
    assert len(seen) == 1 and seen[0].fixture == Path("/f")
    assert seen[0].stage == "qualification-write"
    assert capsys.readouterr().out == '{"fixture":"pinned"}\n'


@pytest.mark.parametrize("stage", ["qualification-read", "qualification-no-dispatch"])
def test_legacy_mint_never_accepts_write_fixture(monkeypatch, stage):
    monkeypatch.setattr(qualification, "mint", lambda _: pytest.fail("minted"))
    record = ["--attempt-record", "/a"] if stage == "qualification-read" else []
    with pytest.raises(SystemExit) as stopped:
        qualification.main([*MINT, "--stage", stage, "--fixture", "/f", *record])
    assert stopped.value.code == 2


@pytest.mark.parametrize("timeout", [0, -1, 600, 1201, float("inf"), float("nan")])
async def test_write_run_refuses_every_other_observation_budget(monkeypatch, timeout):
    monkeypatch.setattr(
        qualification, "read_authorization", lambda _: SimpleNamespace(stage="qualification-write"),
    )
    monkeypatch.setattr(
        qualification, "_require_coherent", lambda _: pytest.fail("bypassed the budget guard"),
    )
    with pytest.raises(ContractViolation, match="fixed 1200-second"):
        await qualification.run(SimpleNamespace(authorization="sealed", fixture=Path("/f"),
                                                timeout=timeout))


async def test_write_run_requires_the_fixture_before_any_assembly(monkeypatch):
    monkeypatch.setattr(
        qualification, "read_authorization", lambda _: SimpleNamespace(stage="qualification-write"),
    )
    monkeypatch.setattr(
        qualification, "_require_coherent", lambda _: pytest.fail("bypassed the fixture guard"),
    )
    with pytest.raises(ContractViolation, match="requires its fixture"):
        await qualification.run(SimpleNamespace(authorization="sealed", fixture=None, timeout=None))


@pytest.mark.parametrize("verdict", ["passed", "not-qualified", "incomplete"])
def test_smoke_cli_emits_only_its_bounded_result(monkeypatch, capsys, verdict):
    seen = []

    class Report:
        def model_dump_json(self):
            return '{"verdict":"' + verdict + '"}'

    async def smoke(arguments):
        seen.append(vars(arguments))
        report = Report()
        report.verdict = verdict
        return report

    monkeypatch.setattr(qualification, "smoke_write", smoke)
    assert qualification.main(["smoke-write", "--fixture", "/f"]) == (
        0 if verdict == "passed" else 1
    )
    assert set(seen[0]) == {"command", "fixture", "launch_root"}
    assert capsys.readouterr().out == '{"verdict":"' + verdict + '"}\n'


def coherent_authorization(tmp_path):
    from constructicon.api._qualification_write_graph import WRITER_SCOPE, write_graph

    authorization = write(
        scope=WRITER_SCOPE, binding="executor", capability_id=qualification.CAPABILITY,
        journal=str(tmp_path / "run.sqlite"), attempt_record=str(tmp_path / "attempt"),
    )
    return authorization.model_copy(update={
        "source_graph_hash": source_graph_hash_for(
            write_graph(authorization.capability_id, authorization.write),
        ),
    })


@pytest.mark.parametrize("change", [
    {"binding": "workspace"}, {"capability_id": "other"},
    {"journal": "relative.sqlite"}, {"attempt_record": "relative.attempt"},
    {"source_graph_hash": "sha256:" + "0" * 64}, {"write": None},
])
async def test_write_run_checks_actual_coherence_before_constructing_journal(
    tmp_path, monkeypatch, change,
):
    authorization = coherent_authorization(tmp_path)
    qualification._require_coherent(authorization)
    monkeypatch.setattr(qualification, "read_authorization", lambda _: authorization.model_copy(
        update=change,
    ))
    reached = []

    def journal(_):
        reached.append(True)
        raise AssertionError("incoherent authority reached journal construction")

    monkeypatch.setattr(qualification, "SqliteJournal", journal)
    with pytest.raises(ContractViolation, match="does not name this WRITE"):
        await qualification.run(SimpleNamespace(
            authorization="sealed", fixture=tmp_path / "fixture", timeout=None,
        ))
    assert reached == []
