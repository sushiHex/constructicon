"""One trusted, finite data-vector exam for the plan-manifest parser.

Candidate bytes are JSON data. Only SHA-pinned authority source is compiled.
The independent oracle describes the ASCII CPython 3.11/3.12 parser profile;
logical paths, including NUL, are never materialized as filesystem names.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


class VectorRefusal(ValueError):
    """A bounded reason, without candidate-controlled diagnostic content."""

    def __init__(self, code: str, case_index: int | None = None) -> None:
        self.code = code
        self.case_index = case_index
        super().__init__(code if case_index is None else f"{code}:{case_index}")


@dataclass(frozen=True)
class PlanPathCase:
    path: str


@dataclass(frozen=True)
class EntriesCase:
    blob: bytes


@dataclass(frozen=True)
class PlanManifestVectors:
    cases: tuple[PlanPathCase | EntriesCase, ...]


@dataclass(frozen=True)
class RunCounts:
    tests_run: int
    failures: int
    errors: int
    skips: int


@dataclass(frozen=True)
class MutantRun:
    name: str
    counts: RunCounts
    distinguished: bool


@dataclass(frozen=True)
class VectorRunReport:
    passed: bool
    baseline: RunCounts
    mutants: tuple[MutantRun, ...]
    input_sha256: str
    target_sha256: str
    reference_sha256: str
    render_sha256: str
    mutants_sha256: str


# These are authority-owned exact-once changes to the pinned target, never JSON.
_MUTANTS = (
    ("path_absolute", "not parsed.is_absolute() and ", ""),
    ("path_noncanonical", "parsed.as_posix() == path\n            and ", ""),
    ("path_parent", '".." not in parsed.parts and ', ""),
    ("path_unsafe_characters", 'and "\\\\" not in path\n'
     '            and ":" not in path and "\\n" not in path and "\\r" not in path\n'
     '            ', ""),
    ("path_any_suffix", 'parsed.suffix == ".md"', "True"),
    ("digest_relaxed", 'r"[0-9a-f]{64}"', 'r"[0-9a-fA-F]{1,64}"'),
    ("entries_duplicate_overwrite", "if path in found:", "if False:"),
    ("entries_conflict_skip",
     'raise ValueError("resolve manifest conflicts explicitly before refresh")', "continue"),
)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise VectorRefusal("duplicate_key")
        result[key] = value
    return result


def _nonfinite(_value: str) -> object:
    raise VectorRefusal("nonfinite")


def _check_depth(text: str) -> None:
    quoted = escaped = False
    depth = 0
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 4:
                raise VectorRefusal("json_depth")
        elif char in "]}":
            depth -= 1


def parse_vectors(blob: bytes) -> PlanManifestVectors:
    if type(blob) is not bytes or len(blob) > 32768:
        raise VectorRefusal("wire_bound")
    try:
        text = blob.decode("utf-8")
        _check_depth(text)
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except VectorRefusal:
        raise
    except (ValueError, RecursionError, OverflowError) as exc:
        raise VectorRefusal("json_invalid") from exc
    if (type(value) is not dict or set(value) != {"version", "cases"}
            or type(value["version"]) is not int or value["version"] != 1):
        raise VectorRefusal("wire_shape")
    cases = value["cases"]
    if type(cases) is not list or not 1 <= len(cases) <= 64:
        raise VectorRefusal("case_count")
    parsed: list[PlanPathCase | EntriesCase] = []
    for index, case in enumerate(cases):
        if type(case) is not dict:
            raise VectorRefusal("case_shape", index)
        if case.get("kind") == "plan_path" and set(case) == {"kind", "path"}:
            path = case["path"]
            if type(path) is not str or len(path) > 256 or not path.isascii():
                raise VectorRefusal("path_domain", index)
            parsed.append(PlanPathCase(path))
        elif case.get("kind") == "entries" and set(case) == {"kind", "blob_hex"}:
            encoded = case["blob_hex"]
            if (type(encoded) is not str or len(encoded) > 2048 or len(encoded) % 2
                    or any(char not in "0123456789abcdef" for char in encoded)):
                raise VectorRefusal("blob_domain", index)
            content = bytes.fromhex(encoded)
            try:
                decoded = content.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                if not decoded.isascii():
                    raise VectorRefusal("blob_domain", index)
            parsed.append(EntriesCase(content))
        else:
            raise VectorRefusal("case_shape", index)
    return PlanManifestVectors(tuple(parsed))


def reference_path(path: str) -> bool:
    """Lexical ASCII law, without pathlib or any target helper."""
    if type(path) is not str or len(path) > 256 or not path.isascii():
        raise VectorRefusal("path_domain")
    return _path_lexical(path)


def _path_lexical(path: str) -> bool:
    if not path or path.startswith("/") or any(char in path for char in "\\:\n\r"):
        return False
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    name = parts[-1]
    return name.endswith(".md") and name.rfind(".") > 0


def _ascii_lines(text: str) -> list[str]:
    lines: list[str] = []
    start = index = 0
    while index < len(text):
        if text[index] in "\n\r\v\f\x1c\x1d\x1e":
            lines.append(text[start:index])
            if text[index:index + 2] == "\r\n":
                index += 1
            start = index + 1
        index += 1
    if start < len(text):
        lines.append(text[start:])
    return lines


def reference_entries(blob: bytes) -> dict[str, str]:
    """Explicit line, delimiter, digest and duplicate semantics."""
    if type(blob) is not bytes or len(blob) > 1024:
        raise VectorRefusal("blob_domain")
    text = blob.decode("utf-8")
    if not text.isascii():
        raise VectorRefusal("blob_domain")
    found: dict[str, str] = {}
    for line in _ascii_lines(text):
        if any(line.startswith(marker) for marker in ("<<<<<<<", "|||||||", "=======", ">>>>>>>")):
            raise ValueError("manifest conflict")
        if all(char in " \t\n\r\v\f\x1c\x1d\x1e\x1f" for char in line):
            continue
        delimiter = line.find("  ")
        if delimiter < 0:
            raise ValueError("manifest delimiter")
        digest, path = line[:delimiter], line[delimiter + 2:]
        if (len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)
                or not _path_lexical(path) or path in found):
            raise ValueError("manifest entry")
        found[path] = digest
    if len(found) > 16:
        raise VectorRefusal("entries_bound")
    return found


def _validated(vectors: PlanManifestVectors) -> PlanManifestVectors:
    if type(vectors) is not PlanManifestVectors or type(vectors.cases) is not tuple:
        raise VectorRefusal("case_shape")
    wire: list[dict[str, str]] = []
    for case in vectors.cases:
        if type(case) is PlanPathCase and type(case.path) is str:
            wire.append({"kind": "plan_path", "path": case.path})
        elif type(case) is EntriesCase and type(case.blob) is bytes:
            wire.append({"kind": "entries", "blob_hex": case.blob.hex()})
        else:
            raise VectorRefusal("case_shape")
    try:
        encoded = json.dumps({"version": 1, "cases": wire},
                             ensure_ascii=False, separators=(",", ":")).encode()
    except UnicodeEncodeError as exc:
        raise VectorRefusal("path_domain") from exc
    return parse_vectors(encoded)


def _expected(case: PlanPathCase | EntriesCase) -> tuple[str, object]:
    try:
        value = (reference_path(case.path) if isinstance(case, PlanPathCase)
                 else reference_entries(case.blob))
    except UnicodeDecodeError:
        return ("raises", "UnicodeDecodeError")
    except VectorRefusal:
        raise
    except ValueError:
        return ("raises", "ValueError")
    return ("returns", value)


def render_unittest(
    vectors: PlanManifestVectors, target_source: bytes, *, trusted_target_sha256: str,
    mutant: str | None = None,
) -> bytes:
    vectors = _validated(vectors)
    if (type(target_source) is not bytes or len(target_source) > 65536
            or type(trusted_target_sha256) is not str
            or hashlib.sha256(target_source).hexdigest() != trusted_target_sha256):
        raise VectorRefusal("target_hash")
    try:
        source = target_source.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise VectorRefusal("target_encoding") from exc
    if mutant is not None and type(mutant) is not str:
        raise VectorRefusal("mutant_name")
    selected = next((item for item in _MUTANTS if item[0] == mutant), None)
    if mutant is not None:
        if type(mutant) is not str or selected is None:
            raise VectorRefusal("mutant_name")
        _, before, after = selected
        if source.count(before) != 1:
            raise VectorRefusal("mutant_target")
        source = source.replace(before, after)
    data = [("plan_path", case.path, _expected(case)) if isinstance(case, PlanPathCase)
            else ("entries", case.blob, _expected(case)) for case in vectors.cases]
    # SHA checking happens before trusted source execution in the private driver too.
    header = f'''import hashlib, json, types, unittest
source = {target_source!r}
if hashlib.sha256(source).hexdigest() != {trusted_target_sha256!r}:
    raise RuntimeError("target hash mismatch")
target = types.ModuleType("trusted_plan_manifest")
target.__file__ = "/trusted/scripts/regen_plan_manifest.py"
exec(compile({source!r}, target.__file__, "exec"), target.__dict__)
data = {data!r}
def observe(kind, value):
    try:
        result = getattr(target, kind)(value)
    except UnicodeDecodeError:
        return ("raises", "UnicodeDecodeError")
    except ValueError:
        return ("raises", "ValueError")
    except AssertionError as exc:
        raise RuntimeError("target assertion is an execution error") from exc
    if kind == "plan_path" and type(result) is not bool:
        raise TypeError("target output shape")
    if kind == "entries" and (type(result) is not dict or len(result) > 16 or
            any(type(k) is not str or type(v) is not str or len(k) > 1024 or
                len(v) > 1024 or not k.isascii() or not v.isascii()
                for k, v in result.items())):
        raise TypeError("target output shape")
    return ("returns", result)
class Vectors(unittest.TestCase):
'''
    tests = "".join(f'''    def test_vector_{index:03d}(self):
        kind, value, expected = data[{index}]
        if observe(kind, value) != expected:
            raise AssertionError("vector disagrees with reference")
''' for index in range(len(data)))
    footer = '''result = unittest.TestResult()
unittest.defaultTestLoader.loadTestsFromTestCase(Vectors).run(result)
print(json.dumps({"tests_run": result.testsRun, "failures": len(result.failures),
                  "errors": len(result.errors), "skips": len(result.skipped)}, sort_keys=True))
'''
    rendered = (header + tests + footer).encode("utf-8")
    if len(rendered) > 262144:
        raise VectorRefusal("render_bound")
    return rendered


def _run(rendered: bytes, expected_count: int) -> RunCounts:
    try:
        with tempfile.TemporaryDirectory(prefix="constructicon-plan-vectors-") as scratch:
            driver = Path(scratch) / "trusted_vectors.py"
            driver.write_bytes(rendered)
            result = subprocess.run(
                [sys.executable, "-I", str(driver)], stdin=subprocess.DEVNULL,
                capture_output=True, timeout=10, check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VectorRefusal("driver_unavailable") from exc
    if result.returncode or result.stderr or len(result.stdout) + len(result.stderr) > 65536:
        raise VectorRefusal("driver_failed")
    try:
        value = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VectorRefusal("driver_protocol") from exc
    names = {"tests_run", "failures", "errors", "skips"}
    if (type(value) is not dict or set(value) != names
            or any(type(number) is not int or not 0 <= number <= expected_count
                   for number in value.values()) or value["tests_run"] != expected_count
            or value["failures"] + value["errors"] + value["skips"] > expected_count):
        raise VectorRefusal("driver_protocol")
    return RunCounts(**value)


def run_vectors(blob: bytes, target_source: bytes, pinned_sha256: str) -> VectorRunReport:
    vectors = parse_vectors(blob)
    coverage = set()
    for case in vectors.cases:
        kind, value = _expected(case)
        if isinstance(case, PlanPathCase):
            coverage.add("path_true" if value is True else "path_false")
        elif kind == "raises":
            coverage.add(str(value))
        elif value:
            coverage.add("entries_nonempty")
    required = {"path_true", "path_false", "entries_nonempty", "ValueError", "UnicodeDecodeError"}
    if not required <= coverage:
        raise VectorRefusal("baseline_coverage")
    rendered = render_unittest(vectors, target_source, trusted_target_sha256=pinned_sha256)
    baseline = _run(rendered, len(vectors.cases))
    baseline_ok = baseline.failures == baseline.errors == baseline.skips == 0
    mutants = []
    for name, _, _ in _MUTANTS:
        counts = _run(render_unittest(vectors, target_source,
                                     trusted_target_sha256=pinned_sha256, mutant=name),
                      len(vectors.cases))
        mutants.append(MutantRun(name, counts, baseline_ok and counts.failures > 0
                                and counts.errors == counts.skips == 0))
    reference_source = "".join(inspect.getsource(function) for function in
                               (reference_path, _path_lexical, _ascii_lines,
                                reference_entries, _expected)).replace("\r\n", "\n")
    mutants_source = json.dumps(_MUTANTS, separators=(",", ":")).encode()
    return VectorRunReport(
        passed=baseline_ok and all(item.distinguished for item in mutants), baseline=baseline,
        mutants=tuple(mutants), input_sha256=hashlib.sha256(blob).hexdigest(),
        target_sha256=pinned_sha256,
        reference_sha256=hashlib.sha256(reference_source.encode()).hexdigest(),
        render_sha256=hashlib.sha256(rendered).hexdigest(),
        mutants_sha256=hashlib.sha256(mutants_source).hexdigest(),
    )
