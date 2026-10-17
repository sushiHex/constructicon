"""The procedure packager: exact assembly, pinned sources and closed refusals."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import m8_procedure_package as package

HANDOFFS = Path(__file__).parents[1] / "docs" / "plans" / "handoffs"
REAL_LANE_BLOCKS = package.LANE_BLOCKS
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
wait "$H"
```

### Notes

```text
not a command
```
"""
SELF_BLOCKS = """## L1: qualification boundary

```bash
lane_capture "$LANES/s4" "${ROOT_STORE[@]}" maintain -- \\
  "${LANE[@]}" startup --evidence "$W/s4.json"
```

## Unreviewed

```bash
lane_capture "$OUT" true; "${LANE[@]}" startup
```

## Split

```bash
"${LA\\
NE[@]}" startup
```
"""


def reviewed(document: str, heading: str) -> str:
    body = package.fences(package.section(document, heading))[0][1]
    return hashlib.sha256(body.encode()).hexdigest()


@pytest.fixture(autouse=True)
def fixture_allowlist(monkeypatch):
    monkeypatch.setattr(package, "LANE_BLOCKS", {
        reviewed(SELF_BLOCKS, "L1: qualification boundary"): "L1",
        reviewed(FROZEN, "Setup"): "Setup", reviewed(FROZEN, "S6a. Held"): "S6a",
    })


def procedure(tmp_path: Path, steps: str, frozen: str = FROZEN, extra: str = "") -> Path:
    (tmp_path / "frozen.md").write_bytes(frozen.encode())
    digest = hashlib.sha256(frozen.encode()).hexdigest()
    document = f"""# Procedure

{SELF_BLOCKS}
## Composition

```toml
labels = {{current = ["g11", "q12"], historical = ["g10", "q11"]}}
{extra}
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


def test_build_writes_exact_step_bytes_and_a_manifest_atomically(tmp_path):
    out = tmp_path / "package"
    digest = package.build(procedure(tmp_path, QUALIFICATION), out)
    script = (out / "c3-qualification.sh").read_bytes().decode()
    assert script.startswith("W=/home/m8-service/m8-maint-q12\nset -Eeuo pipefail\n")
    assert 'lane_capture "$LANES/s4"' in script and 'wait "$H"' in script
    assert (out / "c3-qualification.stdout").read_bytes() == b"lane-boundary-checked\n"
    manifest = (out / "MANIFEST.sha256").read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == digest
    for line in manifest.decode().splitlines():
        expected, name = line.split("  ")
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == expected
    assert "\r" not in script
    with pytest.raises(package.Refused, match="already exists"):
        package.build(procedure(tmp_path, QUALIFICATION), out)
    # An empty directory that appeared first is never replaced.
    claimed = tmp_path / "claimed"
    claimed.mkdir()
    with pytest.raises(package.Refused, match="already exists"):
        package.build(procedure(tmp_path, QUALIFICATION), claimed)
    assert list(claimed.iterdir()) == []


@pytest.mark.parametrize("change", [
    # The g11 S4 stop: the frozen, unwrapped lane call.
    ('{source = "self", heading = "L1: qualification boundary", fences = [0]}',
     '{source = "oc", heading = "S4. Qualification", fences = [0]}'),
    # A capture on the line does not make another call on it captured.
    ('{source = "self", heading = "L1: qualification boundary", fences = [0]}',
     '{source = "self", heading = "Unreviewed", fences = [0]}'),
    # Splitting the name with a line continuation does not hide it.
    ('{source = "self", heading = "L1: qualification boundary", fences = [0]}',
     '{source = "self", heading = "Split", fences = [0]}'),
    # Literals never name the lane.
    ('{literal = "W=/home/m8-service/m8-maint-q12"}',
     "{literal = 'OTHER=(\"${LANE[@]}\")'}"),
    # #220: the module invoked directly, by name or by path, without the array.
    ('{literal = "W=/home/m8-service/m8-maint-q12"}',
     '{literal = "/usr/bin/python3 -I -m constructicon.substrate.executors.codex_lane startup"}'),
    ('{literal = "W=/home/m8-service/m8-maint-q12"}',
     '{literal = "\\"${PY[@]}\\" \\"$LANE_MODULE\\" startup"}'),
    ('{literal = "W=/home/m8-service/m8-maint-q12"}',
     '{literal = "/usr/bin/python3 /opt/c/constructicon/substrate/executors/codex_lane.py"}'),
    # #220: OC's runpy wrapper takes the module name as a plain argument.
    ('{literal = "W=/home/m8-service/m8-maint-q12"}',
     '{literal = "\\"${PY[@]}\\" constructicon.substrate.executors.codex_lane startup"}'),
])
def test_only_reviewed_lane_boundary_blocks_may_invoke_the_lane(tmp_path, change):
    with pytest.raises(package.Refused, match="only a reviewed lane-boundary block"):
        package.assemble(procedure(tmp_path, QUALIFICATION.replace(*change)))


def accepted(path: Path) -> list[package.Step]:
    """An accepting claim, stated as an assertion so a wrong refusal is a failure."""
    try:
        return package.assemble(path)
    except package.Refused as error:
        pytest.fail(f"refused: {error}")


def test_an_even_run_of_trailing_backslashes_is_literal(tmp_path):
    """Two backslashes are one literal backslash; the newline still ends the command."""
    even = QUALIFICATION.replace('{literal = "W=/home/m8-service/m8-maint-q12"}',
                                 '{literal = "printf %s x\\\\\\\\"}')
    assert "printf %s x\\\\\nset -Eeuo" in accepted(procedure(tmp_path, even))[0].text


@pytest.mark.parametrize("splice", [
    # A name spliced from two parts.
    '{literal = "OTHER=${LA\\\\"}, {literal = "NE[@]}"}',
    # A reviewed fence's first command swallowed into an assignment (S1, #220).
    '{literal = "IGNORED=\\\\"}',
    # An odd run of trailing backslashes still escapes the newline.
    '{literal = "IGNORED=x\\\\\\\\\\\\"}',
])
def test_a_part_ending_in_a_line_continuation_refuses(tmp_path, splice):
    spliced = QUALIFICATION.replace('{literal = "W=/home/m8-service/m8-maint-q12"}', splice)
    with pytest.raises(package.Refused, match="ends in a line continuation"):
        package.assemble(procedure(tmp_path, spliced))


@pytest.mark.parametrize("text", [
    # A quoted or escaped hash is a word, not a comment (connector review of #222).
    '\\"#\\" || \\"${LANE[@]}\\" startup',
    "\\\\# x; \\\"${LANE[@]}\\\" startup",
    # A hash line that continues the previous word, or sits inside an open quote.
    'echo a\\\\\\n#; \\"${LANE[@]}\\" startup',
    'echo \\"\\n#\\"; \\"${LANE[@]}\\" startup',
    # So a real comment naming the lane is refused too: lines are never classified.
    "# see the LANE array",
    "# codex_lane.py prints its summary",
], ids=["quoted-hash", "escaped-hash", "continued-hash", "open-quote-hash", "comment-lane",
        "comment-module"])
def test_hash_lines_are_checked_like_any_text(tmp_path, text):
    with pytest.raises(package.Refused, match="only a reviewed lane-boundary block"):
        package.assemble(procedure(tmp_path, _with_literal(text)))


def _with_literal(text: str) -> str:
    return QUALIFICATION.replace(
        '{literal = "W=/home/m8-service/m8-maint-q12"}',
        '{literal = "W=/home/m8-service/m8-maint-q12"}, {literal = "' + text + '"}')


@pytest.mark.parametrize("text", [
    "from constructicon.substrate.executors.codex_lane import EVIDENCE_DOMAIN",
    # Legal whitespace and a constant list are still a constants import.
    "from\tconstructicon.substrate.executors.codex_lane import EVIDENCE_DOMAIN",
    "from  constructicon.substrate.executors.codex_lane  import  (EVIDENCE_DOMAIN, LANE_SCHEMA)",
    "x = 1; from constructicon.substrate.executors.codex_lane import QUALIFICATION_PLANS; y = 2",
    # A parenthesized import across lines is the same statement.
    "from constructicon.substrate.executors.codex_lane import (\\n    EVIDENCE_DOMAIN,"
    "\\n    LANE_SCHEMA,\\n)",
])
def test_constant_imports_are_not_invocations(tmp_path, text):
    """The evidence checkers import constants from codex_lane."""
    built = accepted(procedure(tmp_path, _with_literal(text)))[0].text
    assert text.replace("\\n", "\n").replace("\\t", "\t") in built


@pytest.mark.parametrize("text", [
    # An imported entry point runs the CLI (connector review of #222).
    "from constructicon.substrate.executors.codex_lane import main; main()",
    "import constructicon.substrate.executors.codex_lane as lane; lane.main()",
    "import constructicon.substrate.executors.codex_lane",
    "from constructicon.substrate.executors.codex_lane import EVIDENCE_DOMAIN, main",
    "from constructicon.substrate.executors.codex_lane import (EVIDENCE_DOMAIN,",
    # Any other mention of the module, however imported or named.
    "from constructicon.substrate.executors import codex_lane; codex_lane.main([])",
    "from constructicon.substrate.executors import codex_lane as lane",
    "importlib.import_module(constructicon.substrate.executors.codex_lane)",
    "from other.codex_lane import EVIDENCE_DOMAIN",
    "from constructicon.substrate.executors.codex_lane import (\\n    EVIDENCE_DOMAIN,"
    "\\n    main,\\n)",
])
def test_importing_anything_that_can_dispatch_the_lane_refuses(tmp_path, text):
    with pytest.raises(package.Refused, match="only a reviewed lane-boundary block"):
        package.assemble(procedure(tmp_path, _with_literal(text)))


def test_stale_generation_paths_are_refused_like_the_h7_composition_gap(tmp_path):
    stale = QUALIFICATION.replace('"W=/home/m8-service/m8-maint-q12"',
                                  '"ACTIVE=$W/h7-q11-active.json"')
    with pytest.raises(package.Refused, match=r"undeclared or historical labels \['q11'\]"):
        package.assemble(procedure(tmp_path, stale))
    allowed = stale.replace('stdout = ["lane-boundary-checked"]',
                            'stdout = ["lane-boundary-checked"]\nhistorical = true')
    assert package.assemble(procedure(tmp_path, allowed))[0].name == "c3-qualification"
    with pytest.raises(package.Refused, match=r"\['q13'\]"):
        package.assemble(procedure(tmp_path, QUALIFICATION.replace("q12", "q13")))


def test_a_changed_or_crlf_frozen_source_is_refused(tmp_path):
    path = procedure(tmp_path, QUALIFICATION)
    (tmp_path / "frozen.md").write_bytes(FROZEN.replace("90", "91").encode())
    with pytest.raises(package.Refused, match="source oc does not match its pinned SHA-256"):
        package.assemble(path)
    crlf = FROZEN.replace("\n", "\r\n")
    with pytest.raises(package.Refused, match="source oc is not LF-only"):
        package.assemble(procedure(tmp_path, QUALIFICATION, frozen=crlf))


@pytest.mark.parametrize(("change", "message"), [
    (('heading = "Setup"', 'heading = "Absent"'), "heading 'Absent' occurs 0 times"),
    (('"Setup", fences = [0]', '"Setup", fences = [9]'), "has no fence 9"),
    (('"Setup", fences = [0]', '"Setup", fences = []'), "non-empty list of integers"),
    (('"Setup", fences = [0]', '"Setup", fences = ["0"]'), "non-empty list of integers"),
    (('heading = "Setup"', 'heading = "Notes"'), "is not bash"),
    (('source = "oc", heading = "Setup"', 'source = "other", heading = "Setup"'),
     "unknown source 'other'"),
    (('name = "c3-qualification"', 'name = "C3 Bad"'), "step name 'C3 Bad' is invalid"),
    (('stdout = ["lane-boundary-checked"]', 'stdout = "ok"'), "stdout must be a list"),
    (('stdout = ["lane-boundary-checked"]', 'stdout = ["ok\\r"]'), "not be LF-only"),
    (('stdout = ["lane-boundary-checked"]', 'stdout = ["two\\nlines"]'), "not be LF-only"),
    (('stdout = ["lane-boundary-checked"]', 'stdout = ["x"]\nhistorical = "false"'),
     "historical must be a boolean"),
    (('stdout = ["lane-boundary-checked"]', 'stdout = ["x"]\nextra = 1'), "a step has exactly"),
    (('{literal = "W=/home/m8-service/m8-maint-q12"}',
      '{literal = "W=x", source = "oc", heading = "Setup", fences = [0]}'),
     "exactly a literal or a fence selection"),
    (('{literal = "W=/home/m8-service/m8-maint-q12"}', '{literal = "true\\r\\n"}'),
     "not be LF-only"),
    (('{literal = "W=/home/m8-service/m8-maint-q12"}', '{literal = "  \\n"}'),
     "a literal part is empty"),
])
def test_unresolvable_or_ambiguous_compositions_refuse(tmp_path, change, message):
    with pytest.raises(package.Refused, match=message):
        package.assemble(procedure(tmp_path, QUALIFICATION.replace(*change, 1)))


def test_empty_parts_unknown_keys_and_oversized_stdout_refuse(tmp_path):
    empty = QUALIFICATION.split("parts = [", 1)[0] + "parts = []\n"
    with pytest.raises(package.Refused, match="parts must be a non-empty list"):
        package.assemble(procedure(tmp_path, empty))
    with pytest.raises(package.Refused, match="unknown composition keys"):
        package.assemble(procedure(tmp_path, QUALIFICATION, extra='procedure = "g12"'))
    big = QUALIFICATION.replace('stdout = ["lane-boundary-checked"]',
                                f'stdout = ["{"x" * 65_536}"]')
    with pytest.raises(package.Refused, match="exceeds 65536 bytes"):
        package.assemble(procedure(tmp_path, big))


def test_repeated_steps_and_assigned_placeholders_refuse_sentinels_do_not(tmp_path):
    with pytest.raises(package.Refused, match="invalid or repeated"):
        package.assemble(procedure(tmp_path, QUALIFICATION * 2))
    unreviewed = QUALIFICATION.replace("m8-maint-q12", "m8-maint-q12\\nRUN_ID=UNREVIEWED")
    path = procedure(tmp_path, unreviewed)
    with pytest.raises(package.Refused, match="unreviewed placeholder"):
        package.assemble(path)
    assert package.assemble(path, template=True)[0].text.count("=UNREVIEWED") == 1
    sentinel = QUALIFICATION.replace(
        "m8-maint-q12", "m8-maint-q12\\ntest \\\"$B\\\" != /h/UNPREPARED.bundle")
    assert "UNPREPARED.bundle" in package.assemble(procedure(tmp_path, sentinel))[0].text
    for quoted in ('RUN_ID=\\\"UNREVIEWED\\\"', "RUN_ID='UNPREPARED'"):
        assigned = QUALIFICATION.replace("m8-maint-q12", f"m8-maint-q12\\n{quoted}")
        with pytest.raises(package.Refused, match="unreviewed placeholder"):
            package.assemble(procedure(tmp_path, assigned))


def test_review_standing_follows_exact_bytes_not_file_or_heading_names(tmp_path):
    """#220: a sibling under the reviewed name and heading, with other bytes, is not
    reviewed; the reviewed bytes are, wherever they are pinned from."""
    changed = FROZEN.replace('wait "$H"', 'wait "$H"; "${LANE[@]}" startup')
    with pytest.raises(package.Refused, match="only a reviewed lane-boundary block"):
        package.assemble(procedure(tmp_path, QUALIFICATION, frozen=changed))
    (tmp_path / "copy").mkdir()
    (tmp_path / "copy" / "frozen.md").write_bytes(FROZEN.encode())
    path = procedure(tmp_path, QUALIFICATION)
    path.write_bytes(path.read_bytes().replace(b'path = "frozen.md"', b'path = "copy/frozen.md"'))
    assert package.assemble(path)[0].name == "c3-qualification"


def test_wrong_container_and_selector_types_refuse_without_a_traceback(tmp_path):
    scalar = tmp_path / "scalar.md"
    scalar.write_bytes(b"# P\n\n## Composition\n\n```toml\nsteps = 1\n```\n")
    with pytest.raises(package.Refused, match="steps must be a list"):
        package.assemble(scalar)
    listed = QUALIFICATION.replace('{source = "oc", heading = "Setup"',
                                   '{source = ["oc"], heading = "Setup"')
    with pytest.raises(package.Refused, match="unknown source"):
        package.assemble(procedure(tmp_path, listed))


@pytest.mark.parametrize("spelling", [
    "RUN_ID=$'UNREVIEWED'", "RUN_ID=UNRE\\\\VIEWED", 'RUN_ID=\\"UNRE\\"\\"VIEWED\\"',
    "--run UNREVIEWED", "C=UNPREPARED", "RUN_ID=UNPREPARED.bundle.old",
    "RUN_ID=UNPREPARED.bundlex",
])
def test_every_shell_spelling_of_a_placeholder_refuses(tmp_path, spelling):
    escaped = QUALIFICATION.replace("m8-maint-q12", f"m8-maint-q12\\n{spelling}")
    with pytest.raises(package.Refused, match="unreviewed placeholder"):
        package.assemble(procedure(tmp_path, escaped))


def test_literals_keep_their_exact_trailing_newlines(tmp_path):
    exact = QUALIFICATION.replace('{literal = "W=/home/m8-service/m8-maint-q12"}',
                                  '{literal = "W=/home/m8-service/m8-maint-q12\\n\\n\\n"}')
    text = package.assemble(procedure(tmp_path, exact))[0].text
    assert text.startswith("W=/home/m8-service/m8-maint-q12\n\n\nset -Eeuo pipefail\n")


def test_split_placeholders_empty_fences_and_double_labels_refuse(tmp_path):
    split = QUALIFICATION.replace("m8-maint-q12", "m8-maint-q12\\nRUN_ID=UNRE\\\\\\nVIEWED")
    with pytest.raises(package.Refused, match="unreviewed placeholder"):
        package.assemble(procedure(tmp_path, split))
    empty = FROZEN + "\n### Empty\n\n```bash\n\n```\n"
    selected = QUALIFICATION.replace('heading = "Setup"', 'heading = "Empty"')
    with pytest.raises(package.Refused, match="'Empty' fence 0 is empty"):
        package.assemble(procedure(tmp_path, selected, frozen=empty))
    path = procedure(tmp_path, QUALIFICATION)
    path.write_bytes(path.read_bytes().replace(b'historical = ["g10", "q11"]',
                                               b'historical = ["g10", "q12"]'))
    with pytest.raises(package.Refused, match=r"\['q12'\] are both current and historical"):
        package.assemble(path)


def test_a_label_split_by_shell_quoting_is_still_seen(tmp_path):
    quoted = QUALIFICATION.replace('"W=/home/m8-service/m8-maint-q12"',
                                   "\"W=/home/m8-service/m8-maint-q'1'1\"")
    with pytest.raises(package.Refused, match=r"\['q11'\]"):
        package.assemble(procedure(tmp_path, quoted))


def test_a_label_split_by_a_line_continuation_is_still_seen(tmp_path):
    split = QUALIFICATION.replace('"W=/home/m8-service/m8-maint-q12"',
                                  '"W=/home/m8-service/m8-maint-q\\\\\\n11"')
    with pytest.raises(package.Refused, match=r"\['q11'\]"):
        package.assemble(procedure(tmp_path, split))


@pytest.mark.parametrize("sources", [
    "sources = []",
    '[sources.oc]\npath = 7\nsha256 = "x"',
    '[sources.self]\npath = "frozen.md"\nsha256 = "x"',
])
def test_malformed_sources_refuse_without_a_traceback(tmp_path, sources):
    document = (f"# P\n\n## Composition\n\n```toml\n{sources}\n"
                '[[steps]]\nname = "s"\nstdout = []\nparts = [{literal = "true"}]\n```\n')
    path = tmp_path / "procedure.md"
    path.write_bytes(document.encode())
    with pytest.raises(package.Refused, match=r"sources must be a table|string path and sha256"):
        package.assemble(path)


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
    assert package.section(document, "B") == "b\n### C\nc\n"
    assert package.section(document, "C") == "c\n"


def test_fences_follow_commonmark_indent_length_and_exact_closers():
    document = ("## B\n\n```bash\n# D\nx=1\n## C\n```\n\n"
                "  ```bash\n  indented\n  ```\n\n"
                "````text\n```bash\ninner example\n```\n````\n\n"
                "```bash\nnot closed by\n```suffix\nstill inside\n```\n\n## C\nc\n")
    assert package.fences(package.section(document, "B")) == [
        ("bash", "# D\nx=1\n## C\n"), ("bash", "indented\n"),
        ("text", "```bash\ninner example\n```\n"),
        ("bash", "not closed by\n```suffix\nstill inside\n"),
    ]
    assert package.section(document, "C") == "c\n"
    with pytest.raises(package.Refused, match="'D' occurs 0 times"):
        package.section(document, "D")
    with pytest.raises(package.Refused, match="never closed"):
        package.fences("```bash\nopen\n")


def test_cli_is_strict_unless_template_and_runs_isolated(tmp_path):
    path = procedure(tmp_path, QUALIFICATION.replace(
        "m8-maint-q12", "m8-maint-q12\\nRUN_ID=UNREVIEWED"))
    script = str(Path(package.__file__))

    def run(*args):
        return subprocess.run([sys.executable, "-I", "-S", "-B", script, *args],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=30, check=False)

    # The isolated CLI uses the real allowlist; this fixture's L1 is not on it.
    refused = run("check", str(path), "--template")
    assert refused.returncode == 1 and "lane-boundary block" in refused.stderr
    assert run("bogus").returncode == 1


def test_every_allowlisted_digest_is_the_named_block_at_current_bytes():
    for digest, (name, heading, index) in REAL_LANE_BLOCKS.items():
        document = (HANDOFFS / name).read_bytes().decode("utf-8")
        lang, body = package.fences(package.section(document, heading))[index]
        assert lang == "bash" and hashlib.sha256(body.encode()).hexdigest() == digest, heading
        assert package.LANE_INVOCATION.search(package._normalized(body)), heading


def test_real_frozen_and_reviewed_blocks_are_classified(tmp_path, monkeypatch):
    """The allowlist against actual repository bytes: L1-L3 and frozen S6a pass;
    frozen OC S4 and ER R1, which print the lane summary unwrapped, refuse."""
    monkeypatch.setattr(package, "LANE_BLOCKS", REAL_LANE_BLOCKS)
    names = ("M8-N4-operator-commands.md", "M8-N5-explicit-refresh.md",
             "M8-maintenance-lane-output.md", "M8-N4-host-runtime.md")
    for name in names:
        shutil.copyfile(HANDOFFS / name, tmp_path / name)
    sources = "\n".join(
        f'[sources.s{index}]\npath = "{name}"\nsha256 = "'
        f'{hashlib.sha256((HANDOFFS / name).read_bytes()).hexdigest()}"'
        for index, name in enumerate(names))

    def step(source: str, heading: str) -> Path:
        document = (f"# P\n\n## Composition\n\n```toml\nlabels = {{current = []}}\n{sources}\n"
                    f'[[steps]]\nname = "s"\nstdout = []\nparts = [{{source = "{source}", '
                    f'heading = "{heading}", fences = [0]}}]\n```\n')
        path = tmp_path / "procedure.md"
        path.write_bytes(document.encode())
        return path

    for source, heading in (("s0", "S4. Qualification"),
                            ("s1", "R1: one explicit-refresh attempt")):
        with pytest.raises(package.Refused, match="lane-boundary block"):
            package.assemble(step(source, heading), template=True)
    for source, heading in (("s2", "L1: qualification boundary"), ("s2", "L2: H7 controls"),
                            ("s3", "R19 — Import check as `m8-service`"),
                            ("s2", "L3: explicit refresh"),
                            ("s0", "S6a. Maintenance-lock positive control")):
        try:
            package.assemble(step(source, heading), template=True)
        except package.Refused as error:
            assert "lane-boundary" not in str(error), heading
