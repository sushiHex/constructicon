"""The procedure packager: exact assembly, pinned sources, and refusals that name the step."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import m8_procedure_package as package

HANDOFFS = Path(__file__).parents[1] / "docs" / "plans" / "handoffs"
FROZEN = """# Frozen

## Setup

```bash
set -Eeuo pipefail
LANE=(python lane)
```

### S4. Qualification

```bash
"${ROOT_STORE[@]}" maintain -- \\
  "${LANE[@]}" startup --evidence "$W/s4.json" < /dev/null
```

### S6a. Held

```bash
"${ROOT_STORE[@]}" maintain -- \\
  "${LANE[@]}" startup --hold 90 \\
  < /dev/null > /dev/null 2> /dev/null &
```
"""


def procedure(tmp_path: Path, steps: str, frozen: str = FROZEN, labels: str = "") -> Path:
    (tmp_path / "frozen.md").write_bytes(frozen.encode())
    digest = hashlib.sha256(frozen.encode()).hexdigest()
    document = f"""# Procedure

## L1: qualification boundary

```bash
lane_capture "$LANES/s4" "${{ROOT_STORE[@]}}" maintain -- \\
  "${{LANE[@]}}" startup --evidence "$W/s4.json"
```

## Composition

```toml
procedure = "g12"
labels = {{current = ["g12", "q12"], historical = ["g11", "q11"]}}
{labels}
[sources.oc]
path = "frozen.md"
sha256 = "{digest}"
{steps}
```
"""
    path = tmp_path / "procedure.md"
    path.write_bytes(document.encode())
    return path


QUALIFICATION = """
[[steps]]
name = "c3-qualification"
stdout = ["lane-boundary-checked"]
parts = [
  {literal = "W=/home/m8-service/m8-maint-q12"},
  {source = "oc", heading = "Setup", fences = [0]},
  {source = "self", heading = "L1: qualification boundary", fences = [0]},
  {source = "oc", heading = "S6a. Held", fences = [0]},
]
"""


def test_build_writes_exact_step_bytes_and_a_manifest(tmp_path):
    out = tmp_path / "package"
    digest = package.build(procedure(tmp_path, QUALIFICATION), out)
    script = (out / "c3-qualification.sh").read_text(encoding="utf-8")
    assert script.startswith("W=/home/m8-service/m8-maint-q12\nset -Eeuo pipefail\n")
    assert 'lane_capture "$LANES/s4"' in script and "--hold 90" in script
    assert (out / "c3-qualification.stdout").read_bytes() == b"lane-boundary-checked\n"
    manifest = (out / "MANIFEST.sha256").read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == digest
    for line in manifest.decode().splitlines():
        expected, name = line.split("  ")
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == expected
    assert b"\r" not in script.encode()
    with pytest.raises(FileExistsError):
        package.build(procedure(tmp_path, QUALIFICATION), out)


def test_frozen_unwrapped_lane_call_is_refused_like_the_g11_s4_stop(tmp_path):
    steps = QUALIFICATION.replace(
        '{source = "self", heading = "L1: qualification boundary", fences = [0]}',
        '{source = "oc", heading = "S4. Qualification", fences = [0]}')
    with pytest.raises(package.Refused, match="c3-qualification: a lane CLI call is not inside"):
        package.assemble(procedure(tmp_path, steps))


def test_stale_generation_paths_are_refused_like_the_h7_composition_gap(tmp_path):
    stale = QUALIFICATION.replace('"W=/home/m8-service/m8-maint-q12"',
                                  '"ACTIVE=$W/h7-g11-active.json"')
    with pytest.raises(package.Refused, match=r"undeclared or historical labels \['g11'\]"):
        package.assemble(procedure(tmp_path, stale))
    allowed = stale.replace('stdout = ["lane-boundary-checked"]',
                            'stdout = ["lane-boundary-checked"]\nhistorical = true')
    assert package.assemble(procedure(tmp_path, allowed))[0].name == "c3-qualification"
    undeclared = QUALIFICATION.replace("q12", "q13")
    with pytest.raises(package.Refused, match=r"\['q13'\]"):
        package.assemble(procedure(tmp_path, undeclared))


def test_a_changed_frozen_source_is_refused(tmp_path):
    path = procedure(tmp_path, QUALIFICATION)
    (tmp_path / "frozen.md").write_bytes(FROZEN.replace("90", "91").encode())
    with pytest.raises(package.Refused, match="source oc does not match its pinned SHA-256"):
        package.assemble(path)


@pytest.mark.parametrize(("change", "message"), [
    (('heading = "Setup"', 'heading = "Absent"'), "heading 'Absent' occurs 0 times"),
    (("fences = [0]}", "fences = [3]}"), "has no fence 3"),
    (('source = "oc", heading = "Setup"', 'source = "other", heading = "Setup"'),
     "unknown source 'other'"),
    (('name = "c3-qualification"', 'name = "C3 Bad"'), "step name 'C3 Bad' is invalid"),
    (('stdout = ["lane-boundary-checked"]', 'stdout = ["two\\nlines"]'), "contains a newline"),
])
def test_unresolvable_compositions_refuse(tmp_path, change, message):
    with pytest.raises(package.Refused, match=message):
        package.assemble(procedure(tmp_path, QUALIFICATION.replace(*change, 1)))


def test_repeated_steps_and_placeholders_refuse(tmp_path):
    with pytest.raises(package.Refused, match="invalid or repeated"):
        package.assemble(procedure(tmp_path, QUALIFICATION * 2))
    unreviewed = QUALIFICATION.replace("m8-maint-q12", "m8-maint-q12\\nRUN_ID=UNREVIEWED")
    path = procedure(tmp_path, unreviewed)
    with pytest.raises(package.Refused, match="unreviewed placeholder"):
        package.assemble(path)
    assert package.assemble(path, template=True)[0].text.count("UNREVIEWED") == 1


def test_crlf_document_and_missing_composition_refuse(tmp_path):
    path = procedure(tmp_path, QUALIFICATION)
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(package.Refused, match="not LF-only"):
        package.assemble(path)
    path.write_bytes(b"# Procedure\n\n## Other\n")
    with pytest.raises(package.Refused, match="heading 'Composition' occurs 0 times"):
        package.assemble(path)


def test_section_ends_at_the_next_heading_of_the_same_or_higher_level():
    document = "# A\n## B\nb\n### C\nc\n## D\nd\n"
    assert package.section(document, "B") == "\nb\n### C\nc\n"
    assert package.section(document, "C") == "\nc\n"


def test_cli_checks_and_builds_with_isolated_python(tmp_path):
    path = procedure(tmp_path, QUALIFICATION)
    script = str(Path(package.__file__))

    def run(*args):
        return subprocess.run([sys.executable, "-I", "-S", "-B", script, *args],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=30, check=False)

    checked = run("check", str(path))
    assert (checked.returncode, checked.stdout) == (0, "composition-checked 1 steps\n")
    built = run("build", str(path), str(tmp_path / "out"))
    assert built.returncode == 0 and len(built.stdout.strip()) == 64
    refused = run("build", str(path), str(tmp_path / "out"))
    assert refused.returncode == 1 and refused.stderr.startswith("composition refused:")
    assert run("bogus").returncode == 1


def test_the_real_frozen_lane_calls_are_classified_correctly():
    """The lint against the actual frozen bytes: OC S4 and ER R1 refuse, S6a passes."""
    operator = (HANDOFFS / "M8-N4-operator-commands.md").read_text(encoding="utf-8")
    refresh = (HANDOFFS / "M8-N5-explicit-refresh.md").read_text(encoding="utf-8")
    lane_output = (HANDOFFS / "M8-maintenance-lane-output.md").read_text(encoding="utf-8")
    for heading, document in (("S4. Qualification", operator), ("R1: one explicit-refresh attempt",
                                                                refresh)):
        block = "".join(body for _, body in package.fences(package.section(document, heading)))
        with pytest.raises(package.Refused, match="not inside lane_capture"):
            package._lane_calls_are_captured("frozen", block)
    held = "".join(body for _, body in package.fences(
        package.section(operator, "S6a. Maintenance-lock positive control")))
    package._lane_calls_are_captured("held", held)
    for heading in ("L1: qualification boundary", "L2: H7 controls", "L3: explicit refresh"):
        block = "".join(body for _, body in package.fences(package.section(lane_output, heading)))
        package._lane_calls_are_captured(heading, block)
