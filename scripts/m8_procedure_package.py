"""Assemble a reviewed M8 operator procedure into exact step files; never run them.

A procedure document declares its composition in one TOML block under a heading
named ``Composition``. Steps are built from named fenced blocks, never copied by
hand::

    procedure = "g12"
    labels = {current = ["g12", "q12"], historical = ["g11", "q11"]}

    [sources.oc]                        # a frozen document, pinned by SHA-256
    path = "M8-N4-operator-commands.md"
    sha256 = "..."

    [[steps]]
    name = "c3-qualification"
    stdout = ["lane-boundary-checked"]  # the step's exact declared stdout lines
    historical = false                  # may this step name historical labels?
    parts = [
      {literal = "C=..."},
      {source = "oc", heading = "Setup: fixed controller and evidence checks", fences = [0, 1]},
      {source = "self", heading = "L1: qualification boundary", fences = [0]},
    ]

``self`` is the procedure document itself; its bytes are pinned by
``docs/plans/MANIFEST.sha256``. Usage, with isolated Python from the repository
root::

    python -I -S -B scripts/m8_procedure_package.py check DOC
    python -I -S -B scripts/m8_procedure_package.py build DOC OUT [--template]

``build`` writes ``<step>.sh`` and ``<step>.stdout`` files (LF only) and a
``MANIFEST.sha256`` into the absent directory ``OUT``, then prints the
manifest's own SHA-256. Every check below refuses with a message naming the
step; nothing is guessed or repaired:

- every source pin, heading and fence index resolves exactly;
- a lane CLI call (``"${LANE[@]}"``) appears only inside ``lane_capture`` (the
  #210 lane-output contract) or in the frozen held-startup form that discards its
  output to ``/dev/null``;
- generation and session labels (``g12``, ``q11``...) are declared, and a step
  names historical ones only if it says so;
- outside ``--template``, no ``UNREVIEWED``/``UNPREPARED`` placeholder remains.
"""

from __future__ import annotations

import hashlib
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

FENCE = re.compile(r"^```(?P<lang>[a-z]*)\n(?P<body>.*?)^```", re.MULTILINE | re.DOTALL)
HEADING = re.compile(r"^(?P<level>#{1,6}) (?P<title>.+?)\s*$", re.MULTILINE)
LABEL = re.compile(r"(?<![0-9A-Za-z])[gq][0-9]{1,3}(?![0-9A-Za-z])")
PLACEHOLDER = re.compile(r"\b(?:UNREVIEWED|UNPREPARED)\b")
LANE_CALL = '"${LANE[@]}"'
HELD_DISCARD = re.compile(r">\s*/dev/null\s+2>\s*/dev/null\s*&\s*$")
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


class Refused(ValueError):
    """The composition is not exactly reviewable; nothing is written."""


@dataclass(frozen=True)
class Step:
    name: str
    text: str
    stdout: tuple[str, ...]


def section(document: str, title: str) -> str:
    """The text under exactly one heading named ``title``, to the next heading at
    the same or a higher level."""
    matches = [match for match in HEADING.finditer(document) if match["title"] == title]
    if len(matches) != 1:
        raise Refused(f"heading {title!r} occurs {len(matches)} times")
    start, level = matches[0].end(), len(matches[0]["level"])
    for following in HEADING.finditer(document, start):
        if len(following["level"]) <= level:
            return document[start:following.start()]
    return document[start:]


def fences(text: str) -> list[tuple[str, str]]:
    return [(match["lang"], match["body"]) for match in FENCE.finditer(text)]


def composition(document: str) -> dict:
    blocks = [body for lang, body in fences(section(document, "Composition")) if lang == "toml"]
    if len(blocks) != 1:
        raise Refused("the Composition section needs exactly one toml block")
    try:
        return tomllib.loads(blocks[0])
    except tomllib.TOMLDecodeError as error:
        raise Refused(f"composition is not valid TOML: {error}") from None


def _lane_calls_are_captured(name: str, text: str) -> None:
    logical = re.sub(r"\\\n", " ", text)
    for line in logical.splitlines():
        if LANE_CALL not in line:
            continue
        command = line.strip()
        captured = command.startswith("lane_capture ")
        held = HELD_DISCARD.search(command) is not None
        if not (captured or held):
            raise Refused(f"step {name}: a lane CLI call is not inside lane_capture "
                          "(#210 lane-output contract)")


def _labels(name: str, text: str, labels: dict, historical: bool) -> None:
    current = set(labels.get("current", ()))
    allowed = current | (set(labels.get("historical", ())) if historical else set())
    stray = sorted({label for label in LABEL.findall(text) if label not in allowed})
    if stray:
        raise Refused(f"step {name}: undeclared or historical labels {stray}")


def assemble(path: Path, template: bool = False) -> list[Step]:
    # Raw bytes: text-mode reading would silently translate CRLF and hide it.
    document = path.read_bytes().decode("utf-8")
    if "\r" in document:
        raise Refused("the procedure document is not LF-only")
    spec = composition(document)
    sources = {"self": document}
    for key, source in spec.get("sources", {}).items():
        raw = (path.parent / source["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise Refused(f"source {key} does not match its pinned SHA-256")
        if b"\r" in raw:
            raise Refused(f"source {key} is not LF-only")
        sources[key] = raw.decode("utf-8")
    steps, names = [], set()
    for entry in spec.get("steps", ()):
        name = entry.get("name", "")
        if not NAME.fullmatch(name) or name in names:
            raise Refused(f"step name {name!r} is invalid or repeated")
        names.add(name)
        pieces = []
        for part in entry["parts"]:
            if "literal" in part:
                pieces.append(part["literal"].rstrip("\n") + "\n")
                continue
            if part.get("source") not in sources:
                raise Refused(f"step {name}: unknown source {part.get('source')!r}")
            found = fences(section(sources[part["source"]], part["heading"]))
            for index in part["fences"]:
                if not 0 <= index < len(found):
                    raise Refused(f"step {name}: {part['heading']!r} has no fence {index}")
                pieces.append(found[index][1])
        text = "".join(pieces)
        _lane_calls_are_captured(name, text)
        _labels(name, text, spec.get("labels", {}), bool(entry.get("historical", False)))
        if not template and PLACEHOLDER.search(text):
            raise Refused(f"step {name}: an unreviewed placeholder remains")
        stdout = tuple(entry["stdout"])
        if any("\n" in line for line in stdout):
            raise Refused(f"step {name}: a declared stdout line contains a newline")
        steps.append(Step(name, text, stdout))
    if not steps:
        raise Refused("the composition declares no steps")
    return steps


def build(path: Path, out: Path, template: bool = False) -> str:
    steps = assemble(path, template)
    out.mkdir()
    lines = []
    for step in steps:
        for suffix, body in ((".sh", step.text), (".stdout", "".join(
                line + "\n" for line in step.stdout))):
            raw = body.encode("utf-8")
            (out / (step.name + suffix)).write_bytes(raw)
            lines.append(f"{hashlib.sha256(raw).hexdigest()}  {step.name}{suffix}\n")
    manifest = "".join(lines).encode("utf-8")
    (out / "MANIFEST.sha256").write_bytes(manifest)
    return hashlib.sha256(manifest).hexdigest()


def main(argv: list[str]) -> int:
    try:
        if argv[1:2] == ["check"] and len(argv) == 3:
            steps = assemble(Path(argv[2]), template=True)
            print(f"composition-checked {len(steps)} steps")
        elif argv[1:2] == ["build"] and len(argv) in (4, 5):
            template = argv[4:] == ["--template"]
            if len(argv) == 5 and not template:
                raise Refused("unknown option")
            print(build(Path(argv[2]), Path(argv[3]), template))
        else:
            raise Refused("usage: check DOC | build DOC OUT [--template]")
    except (Refused, OSError, KeyError, TypeError) as error:
        print(f"composition refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
