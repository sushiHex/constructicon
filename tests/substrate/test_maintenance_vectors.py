"""The bounded maintenance exam accepts data and records real assertion failures."""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from scripts import regen_plan_manifest

from constructicon.substrate.gates import maintenance
from tests.test_plan_manifest_contribution import contribution_result

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "scripts/regen_plan_manifest.py").read_bytes()
SHA = hashlib.sha256(SOURCE).hexdigest()
DIGEST = "a" * 64


def wire(cases: list[dict[str, object]]) -> bytes:
    return json.dumps({"version": 1, "cases": cases}, ensure_ascii=True).encode()


def path(value: str) -> dict[str, object]:
    return {"kind": "plan_path", "path": value}


def entries(value: bytes) -> dict[str, object]:
    return {"kind": "entries", "blob_hex": value.hex()}


def permitting_vectors() -> bytes:
    return wire([
        path("nested/new file.md"), path(".md"), path("..md"), path(".hidden.md"),
        path("a\0.md"), path("a\x1f.md"), path("/a.md"), path("./a.md"),
        path("a//b.md"), path("../a.md"), path("a\\b.md"), path("a:b.md"),
        path("a\n.md"), path("a\r.md"), path("a.txt"),
        entries(b""), entries(f"{DIGEST}  a.md\n".encode()),
        entries(f"{DIGEST}   a.md\r\n{DIGEST}  b.md\v\x1f\n".encode()),
        entries(f"{'A' * 64}  a.md\n".encode()), entries(b"a  a.md\n"),
        entries(f"{DIGEST}  a.md\n{DIGEST}  a.md\n".encode()),
        entries(f"<<<<<<< HEAD\n{DIGEST}  a.md\n".encode()),
        entries(b"malformed"), entries(b"\xff"),
    ])


def test_permitting_exam_runs_every_case_and_kills_each_named_mutant() -> None:
    report = maintenance.run_vectors(permitting_vectors(), SOURCE, SHA)
    assert report.passed
    assert report.baseline.tests_run == 24
    assert (report.baseline.failures, report.baseline.errors, report.baseline.skips) == (0, 0, 0)
    assert len(report.mutants) == 8
    for mutant in report.mutants:
        assert mutant.counts.tests_run == 24
        assert mutant.counts.failures > 0
        assert mutant.counts.errors == mutant.counts.skips == 0
        assert mutant.distinguished
    for value in (report.input_sha256, report.target_sha256, report.reference_sha256,
                  report.render_sha256, report.mutants_sha256):
        assert len(value) == 64 and set(value) <= set("0123456789abcdef")
    # Bound every published leaf, so a future output field enters this assertion too.
    def bounded(value: object) -> None:
        if type(value) is dict:
            for child in value.values():
                bounded(child)
        elif type(value) is tuple:
            assert len(value) <= 8
            for child in value:
                bounded(child)
        elif type(value) is bool:
            pass
        elif type(value) is int:
            assert 0 <= value <= 64
        elif type(value) is str:
            assert value.isascii() and len(value) <= 64
        else:
            raise AssertionError("unbounded public report field")
    bounded(asdict(report))
    assert "nested/new file.md" not in repr(report)
    assert len(json.dumps(asdict(report))) <= 4096


@pytest.mark.parametrize(("value", "expected"), [
    ("", False), (".", False), (".md", False), ("a/.md", False), ("..md", True),
    ("...md", True), (".hidden.md", True), (" a.md", True), ("a\0.md", True),
    ("a\x1f.md", True), ("a\t.md", True), ("a\x1c.md", True),
    ("a/./b.md", False), ("a/../b.md", False), ("a.md/", False), ("a.md ", False),
])
def test_reference_path_explicit_ascii_semantics(value: str, expected: bool) -> None:
    assert maintenance.reference_path(value) is expected


@pytest.mark.parametrize("separator", [b"\n", b"\r", b"\r\n", b"\v", b"\f",
                                       b"\x1c", b"\x1d", b"\x1e"])
def test_reference_entries_all_ascii_line_boundaries(separator: bytes) -> None:
    blob = f"{DIGEST}  a.md".encode() + separator + f"{DIGEST}  b.md".encode()
    assert maintenance.reference_entries(blob) == {"a.md": DIGEST, "b.md": DIGEST}


def test_reference_entries_spaces_nul_and_blank_control_lines() -> None:
    blob = f"{DIGEST}   a\0.md\n\t\x1f \n".encode()
    assert maintenance.reference_entries(blob) == {" a\0.md": DIGEST}
    with pytest.raises(UnicodeDecodeError):
        maintenance.reference_entries(b"\xff")
    assert maintenance.reference_entries(f"{DIGEST}  a.md\x1fb.md".encode()) == {
        "a.md\x1fb.md": DIGEST,
    }


@pytest.mark.parametrize("blob", [
    b"", b"{}", b'{"version":true,"cases":[]}',
    b'{"version":1,"version":1,"cases":[]}',
    b'{"version":1,"cases":[],"extra":0}', b'{"version":NaN,"cases":[]}',
    b'{"version":1,"cases":[]}',
    b'{"version":1,"cases":[{"kind":"plan_path","path":"x.md","expected":true}]}',
    b'{"version":1,"cases":[{"kind":"plan_path","path":"\\ud800"}]}',
    b'{"version":1,"cases":[[[[[[[[[[]]]]]]]]]]}',
])
def test_closed_wire_refuses_bad_shapes_and_candidate_expectations(blob: bytes) -> None:
    with pytest.raises(maintenance.VectorRefusal):
        maintenance.parse_vectors(blob)


@pytest.mark.parametrize("case", [path("é.md"), path("a" * 257), entries(b"a" * 1025),
                                entries("é".encode()), {"kind": "entries", "blob_hex": "FF"}])
def test_case_bounds_and_unsupported_valid_unicode(case: dict[str, object]) -> None:
    with pytest.raises(maintenance.VectorRefusal) as caught:
        maintenance.parse_vectors(wire([case]))
    assert len(str(caught.value)) <= 64
    assert caught.value.case_index == 0


def test_actual_wire_and_count_limits_bind() -> None:
    with pytest.raises(maintenance.VectorRefusal, match="wire_bound"):
        maintenance.parse_vectors(b" " * 32769)
    with pytest.raises(maintenance.VectorRefusal, match="case_count"):
        maintenance.parse_vectors(wire([path("a.md")] * 65))


def test_permitted_limits_and_logical_output_paths_are_exercised() -> None:
    vectors = maintenance.parse_vectors(wire([path("x" * 253 + ".md")] * 64))
    assert len(vectors.cases) == 64
    assert maintenance.reference_path("x" * 253 + ".md")
    assert maintenance.parse_vectors(wire([entries(b"\xff" * 1024)]))
    # A manifest's embedded path has the blob bound, rather than a path-case's bound.
    long_path = "x" * 954 + ".md"
    blob = f"{DIGEST}  {long_path}\n".encode()
    assert len(blob) == 1024
    assert maintenance.reference_entries(blob) == {long_path: DIGEST}
    base = permitting_vectors()
    assert maintenance.parse_vectors(base + b" " * (32768 - len(base)))
    maximum_entries = b"".join(f"{DIGEST}  {index}.md\n".encode() for index in range(14))
    assert len(maintenance.reference_entries(maximum_entries)) == 14


def test_reference_matches_actual_trusted_target_on_small_ascii_domain() -> None:
    alphabet = ("a", ".", "/", "\\", ":", "\0", "\n", "\r", " ", "\x1f")
    for width in range(4):
        for prefix in itertools.product(alphabet, repeat=width):
            value = "".join(prefix) + ".md"
            assert maintenance.reference_path(value) == regen_plan_manifest.plan_path(value)


def test_render_bound_binds_without_executing_the_oversized_source() -> None:
    padded = SOURCE + b"\n#" + b"\x7f" * (64000 - len(SOURCE))
    with pytest.raises(maintenance.VectorRefusal, match="render_bound"):
        maintenance.render_unittest(maintenance.parse_vectors(permitting_vectors()), padded,
                                    trusted_target_sha256=hashlib.sha256(padded).hexdigest())


def test_empty_or_refusal_only_suites_cannot_qualify() -> None:
    for blob in (wire([entries(b"")]), wire([path("/a.md"), entries(b"\xff")])):
        with pytest.raises(maintenance.VectorRefusal, match="baseline_coverage"):
            maintenance.run_vectors(blob, SOURCE, SHA)


def test_renderer_is_deterministic_and_revalidates_constructor_inputs() -> None:
    vectors = maintenance.parse_vectors(permitting_vectors())
    first = maintenance.render_unittest(vectors, SOURCE, trusted_target_sha256=SHA)
    assert first == maintenance.render_unittest(vectors, SOURCE, trusted_target_sha256=SHA)
    assert len(first) <= 262144
    forged = maintenance.PlanManifestVectors((maintenance.PlanPathCase("x" * 257),))
    with pytest.raises(maintenance.VectorRefusal):
        maintenance.render_unittest(forged, SOURCE, trusted_target_sha256=SHA)
    aliased: list[maintenance.PlanPathCase | maintenance.EntriesCase] = [
        maintenance.PlanPathCase("x.md"),
    ]
    with pytest.raises(maintenance.VectorRefusal):
        maintenance.render_unittest(maintenance.PlanManifestVectors(aliased), SOURCE,  # type: ignore[arg-type]
                                    trusted_target_sha256=SHA)
    forged_blob = maintenance.PlanManifestVectors((maintenance.EntriesCase(b"x" * 1025),))
    with pytest.raises(maintenance.VectorRefusal):
        maintenance.render_unittest(forged_blob, SOURCE, trusted_target_sha256=SHA)
    forged_surrogate = maintenance.PlanManifestVectors((maintenance.PlanPathCase("\ud800"),))
    with pytest.raises(maintenance.VectorRefusal, match="path_domain"):
        maintenance.render_unittest(forged_surrogate, SOURCE, trusted_target_sha256=SHA)
    with pytest.raises(maintenance.VectorRefusal, match="target_hash"):
        maintenance.render_unittest(vectors, SOURCE, trusted_target_sha256="0" * 64)
    with pytest.raises(maintenance.VectorRefusal, match="mutant_name"):
        maintenance.render_unittest(vectors, SOURCE, trusted_target_sha256=SHA,
                                    mutant="caller_code")


def test_compact_ascii_vectors_remain_accepted_when_renderer_revalidates() -> None:
    value = json.loads(permitting_vectors())
    value["cases"].extend([path("\x7f" * 253 + ".md")] * 40)
    blob = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(blob) == 13439
    vectors = maintenance.parse_vectors(blob)
    assert len(vectors.cases) == 64
    try:
        rendered = maintenance.render_unittest(vectors, SOURCE, trusted_target_sha256=SHA)
        report = maintenance.run_vectors(blob, SOURCE, SHA)
    except maintenance.VectorRefusal as exc:
        raise AssertionError("valid compact ASCII vectors refused during revalidation") from exc
    assert len(rendered) <= 262144
    assert report.passed
    assert report.baseline == maintenance.RunCounts(64, 0, 0, 0)
    assert len(report.mutants) == 8
    for mutant in report.mutants:
        assert mutant.distinguished
        assert mutant.counts.tests_run == 64 and mutant.counts.failures > 0
        assert mutant.counts.errors == mutant.counts.skips == 0


def test_surviving_mutants_are_reported_as_not_proven() -> None:
    blob = wire([path("a.md"), path(".md"), entries(f"{DIGEST}  a.md\n".encode()),
                 entries(b"bad"), entries(b"\xff")])
    report = maintenance.run_vectors(blob, SOURCE, SHA)
    assert not report.passed
    assert any(not mutant.distinguished for mutant in report.mutants)


@pytest.mark.parametrize("failure", [b'raise RuntimeError("broken")',
                                     b'raise AssertionError("broken")'])
def test_target_error_is_not_an_assertion_kill(failure: bytes) -> None:
    broken = SOURCE.replace(b'digest, path = line.split("  ", 1)', failure)
    report = maintenance.run_vectors(permitting_vectors(), broken,
                                     hashlib.sha256(broken).hexdigest())
    assert not report.passed
    assert report.baseline.errors > 0
    assert not any(mutant.distinguished for mutant in report.mutants)


def test_fixed_consumer_runs_a_retained_data_contribution(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/regen_plan_manifest.py").write_bytes(SOURCE)
    (tmp_path / "tests/vectors").mkdir(parents=True)
    (tmp_path / "tests/vectors/plan_manifest.json").write_bytes(permitting_vectors())
    report = contribution_result(tmp_path)
    assert report is not None and report.passed
    assert report.baseline.tests_run == 24
    assert all(mutant.distinguished for mutant in report.mutants)


def test_fixed_consumer_records_absence_explicitly(tmp_path: Path) -> None:
    assert contribution_result(tmp_path) is None


def test_fixed_consumer_refuses_malformed_retained_data(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/regen_plan_manifest.py").write_bytes(SOURCE)
    (tmp_path / "tests/vectors").mkdir(parents=True)
    (tmp_path / "tests/vectors/plan_manifest.json").write_bytes(b"{}")
    with pytest.raises(maintenance.VectorRefusal, match="wire_shape"):
        contribution_result(tmp_path)
