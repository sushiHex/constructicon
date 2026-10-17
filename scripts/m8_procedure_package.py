"""Assemble a reviewed M8 operator procedure into exact step files; never run them.

A procedure document declares its composition in one TOML block under a heading
named ``Composition``. Steps are built from named fenced blocks, never copied by
hand::

    labels = {current = ["g11", "q12"], historical = ["g10", "q11"]}

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
      {source = "lr", heading = "LR8. Controller", fences = [0], set = {O = "...", C = "..."}},
      {source = "lane", heading = "L1: qualification boundary", fences = [0]},
    ]

``self`` is the procedure document itself, pinned by ``docs/plans/MANIFEST.sha256``.
Usage, with isolated Python from the repository root::

    python -I -S -B scripts/m8_procedure_package.py check DOC [--template]
    python -I -S -B scripts/m8_procedure_package.py build DOC OUT [--values FILE] [--template]

``--values`` fills values measured mid-session (``PREVIEW_SHA256``, ``RUN_ID``,
``EXPECTED_BOOT``) into exact ``NAME=UNREVIEWED`` lines, each checked against its
shape; a value that fills no line refuses. A step marked ``deferred = true`` may wait
only for those values: without ``--values`` it is checked but not written, and the CLI
names it. Once the values are measured and reviewed, everything is built again into a
fresh ``OUT``, where no placeholder may remain.

A step's ``stdout`` is one list of exact lines or a list of distinct alternative
lists (a reviewed branch such as a measured or unmeasured refresh), and an optional
``record = {keys = [...], max_bytes = N}`` declares one closed JSON record line after
them. The transport checks framing only; a record's values are a typed checker's and
a reviewer's job.

``build`` writes ``<step>.sh``, ``<step>.expected.json`` (LF only) and ``MANIFEST.sha256``
(``sha256sum --check`` format) into ``OUT``, which it claims with an exclusive
``mkdir``. The manifest is written last, so a package without one is incomplete. It
prints the manifest's own SHA-256. It never guesses; its one repair is supplying a
literal's missing final newline. Refusal messages are diagnostics: many name the
step, source or heading, some do not. It refuses:

- **schema:** unknown keys, wrong types, empty parts or selections, a part that
  is not exactly a literal or exactly a fence selection;
- **sources:** a changed pin, a CRLF source, an absent or repeated heading, a
  missing fence, a fence that is not ``bash``;
- **lane boundary (#210, #220):** a step whose text outside reviewed lane-boundary
  fences names the lane CLI (``LANE``, ``LANE_MODULE``, or any mention of
  ``codex_lane`` other than importing uppercase constants from the fully qualified
  module), and a part ending in a line continuation.
  Each unreviewed part is checked after shell normalization, comments included: a
  `#` may be quoted or continued from the line before, so prose that names the lane
  is refused too. With no trailing continuation, no word spans two parts. A fence is reviewed
  only when its exact bytes are on the allowlist, wherever it is read from. Bytes
  do not freeze shell context: an earlier unreviewed part can still redefine a
  function or variable a reviewed fence uses, which is the review's job;
- **labels:** an undeclared generation/session label, or a historical one in a
  step not marked historical. This is a spelling check, not proof of fresh paths;
- **placeholders:** ``UNREVIEWED`` or ``UNPREPARED`` (other than the
  ``UNPREPARED.bundle`` sentinel) in any shell spelling, or a frozen fence's
  documented ``NAME=<...>`` declaration left unfilled, unless ``--template``. A fence
  selection fills declarations with ``set = {NAME = "<40-hex commit>"}``; each name
  must match exactly one declaration line in the selection;
- **bytes:** any CR in a built file, a declared stdout over 65,536 bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

HEADING = re.compile(r"^(?P<level>#{1,6}) (?P<title>.+?)[ \t]*$")
OPEN_FENCE = re.compile(r"^(?P<indent> {0,3})(?P<ticks>`{3,})(?P<lang>[A-Za-z]*)[ \t]*$")
LABEL = re.compile(r"(?<![0-9A-Za-z])[gq][0-9]{1,3}(?![0-9A-Za-z])")
# Matched after removing quotes, backslashes and `$`, so ordinary shell
# concatenation and escaping ($'X', "UNRE""VIEWED", UNRE\VIEWED) cannot hide a
# placeholder or a label. The exact `UNPREPARED.bundle` refusal sentinel is a
# comparison target, not a value. These lints catch honest composition mistakes
# in reviewed documents; deliberate obfuscation (ANSI-C hex escapes, eval,
# indirection) is the review's job, not a shell interpreter's here.
PLACEHOLDER = re.compile(r"\bUNREVIEWED\b|\bUNPREPARED\b(?!\.bundle(?:$|[\s;)|&]))",
                         re.MULTILINE)
SHELL_QUOTING = re.compile(r"[\"'\\$]")
# Ways a step can reach the lane CLI: the array, its module variable, or any
# mention of the module (`-m`, OC's runpy wrapper, `from ... import codex_lane`, an
# alias, its file, `import_module`). Enumerating spellings never ends, so every
# mention is refused except one exact form: importing uppercase constants from
# the fully qualified module, as the evidence checkers do. A name assembled from
# pieces at run time remains the review's job.
LANE_INVOCATION = re.compile(r"\bLANE\b|\bLANE_MODULE\b|\bcodex_lane\b")
# `from constructicon.substrate.executors.codex_lane import CONSTANT, ...`, any
# whitespace, ending its statement. `import <module>` or a lowercase name (`main`)
# hands over something that can dispatch the CLI.
FROM_BEFORE = re.compile(r"(?:^|[\s;(])from\s+constructicon\.substrate\.executors\.$")
_NAMES = r"[A-Z][A-Z0-9_]*(?:\s*,\s*[A-Z][A-Z0-9_]*)*"
CONSTANTS_AFTER = re.compile(
    rf"\s+import\s+(?:\(\s*{_NAMES}\s*,?\s*\)|{_NAMES})\s*(?:;|$)")


def _invokes(text: str) -> bool:
    """Whether normalized text names the lane CLI other than as the module of a
    `from` statement that imports only uppercase constants."""
    for match in LANE_INVOCATION.finditer(text):
        if match.group(0) == "codex_lane":
            start = text.rfind("\n", 0, match.start()) + 1
            end = text.find("\n", match.end())
            before = text[start:match.start()]
            after = text[match.end():len(text) if end < 0 else end]
            if re.match(r"\s+import\s+\($", after):
                # A parenthesized import runs to its closing parenthesis's line.
                close = text.find(")", match.end())
                close_end = text.find("\n", close) if close >= 0 else -1
                after = text[match.end():len(text) if close_end < 0 else close_end]
            if FROM_BEFORE.search(before) and CONSTANTS_AFTER.match(after):
                continue
        return True
    return False


def _continues(body: str) -> bool:
    """Whether bash joins the next line to this one: an odd run of backslashes before
    the final newline (an even run is literal backslashes)."""
    run = len(body) - 1 - len(body[:-1].rstrip("\\"))
    return body.endswith("\n") and run % 2 == 1


# A frozen fence's documented placeholder declaration, such as
# `D=<40-hex commit the qualification set was installed at>`. Only a fence
# selection's `set` fills one, and only with a 40-hex commit (every documented
# placeholder is one); an unfilled one in a built step is refused.
DECLARATION = re.compile(r"^(?P<name>[A-Z_][A-Z0-9_]*)=<[^<>\n]+>$", re.MULTILINE)
COMMIT = re.compile(r"[0-9a-f]{40}")
# Values measured mid-session (C8's preview and run, this boot's UUID). A
# `--values` file fills only these names, only on an exact `NAME=UNREVIEWED` line,
# and only with a value of the name's own shape.
SESSION_VALUES = {
    "PREVIEW_SHA256": re.compile(r"[0-9a-f]{64}"),
    "RUN_ID": re.compile(r"run-[0-9a-f]{32}"),
    "EXPECTED_BOOT": re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
}


def session_values(path: Path) -> dict[str, str]:
    """A TOML file of measured session values, each checked against its shape."""
    try:
        values = tomllib.loads(path.read_bytes().decode("utf-8"))
    except tomllib.TOMLDecodeError:
        raise Refused("the values file is not valid TOML") from None
    return _checked(values)


def _checked(values: object) -> dict[str, str]:
    """Session values in their exact shapes, wherever they come from (the CLI's
    file or a caller of `assemble` or `build`)."""
    if not isinstance(values, dict) or not values or not set(values) <= set(
            SESSION_VALUES) or not all(isinstance(value, str) and isinstance(key, str)
                                       and SESSION_VALUES[key].fullmatch(value)
                                       for key, value in values.items()):
        raise Refused(f"values are only {sorted(SESSION_VALUES)}, each in its exact shape")
    return values


NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
MAX_STDOUT = 65_536
# The only reviewed fences that may invoke the lane CLI, keyed by the SHA-256 of
# their exact bytes, so a same-named heading in another file is not reviewed.
# Startup boundaries are wrapped by lane_capture (#210 L1-L3); OC Setup defines
# the array, S1 prepare prints a declared record, and S6a discards its held lane's
# output then checks `wait` and its evidence.
LANE_BLOCKS = {
    "05c3714b695c84a7f122a5b3be79ba1f4d279865a816510ec960ac1a3156184b":
        ("M8-maintenance-lane-output.md", "L1: qualification boundary", 0),
    "dc1295ebc58160fee43dc53f2c0f1e5275c765a594610104c83e28a5786750cb":
        ("M8-maintenance-lane-output.md", "L2: H7 controls", 0),
    "c25ab6d03e4966d08b576f429c1079afcc2e1483467ba04e046fb1c7ef25d03b":
        ("M8-maintenance-lane-output.md", "L3: explicit refresh", 0),
    "3028af29aa54f1e50f990308fff20733bb7eecfae0e80c14d3f42bfdee39c442":
        ("M8-N4-operator-commands.md", "Setup: fixed controller and evidence checks", 0),
    # Imports the lane's constants in one multi-line statement; it runs no lane.
    "e404d62f08ce8cc07e1384db9a71a97b04b931ead6356bb0ceb872f37184c361":
        ("M8-N4-operator-commands.md", "Setup: fixed controller and evidence checks", 1),
    "1e0049b134c40dc8044dc9ad58c8f97700f56d6440eeb7a8b182bdc732417e45":
        ("M8-N4-operator-commands.md", "S1. Prepare", 0),
    "cbeff595f802b4576cc663dd8fbf7f1deba139831a2754c8fd9891ab759f5eae":
        ("M8-N4-operator-commands.md", "S6a. Maintenance-lock positive control", 0),
    # The physical preflight: OC S3's preflight line, whose readiness record goes to
    # grep and which returns before the lane's summary path (codex_lane.py:757-765).
    "8e63ea22469943d003a0a8c17e19ada2f33df12acae49544285c32b4efe90e9f":
        ("M8-maintenance-q12-continuation.md", "Q5: new and renamed VM fences", 1),
    # Names the module only in its import check; it never runs the CLI.
    "f7dc20309ff8bc803def1d9e808a573ffa59e4c0b2a5c1dc592ef684a3a7d429":
        ("M8-N4-host-runtime.md", "R19 — Import check as `m8-service`", 0),
}
TOP_KEYS = {"labels", "sources", "steps"}
STEP_KEYS = {"name", "stdout", "record", "historical", "deferred", "parts"}
RECORD_KEY = re.compile(r"[a-z_][a-z0-9_]{0,63}")


class Refused(ValueError):
    """The composition is not exactly reviewable; nothing is written."""


@dataclass(frozen=True)
class Fence:
    lang: str
    body: str
    start: int
    end: int


@dataclass(frozen=True)
class Step:
    name: str
    text: str
    alternatives: tuple[tuple[str, ...], ...]
    record: tuple[tuple[str, ...], int] | None = None
    waiting: bool = False  # deferred, and built only with measured session values

    def expected(self) -> str:
        """The transport's declared expectation: exactly one alternative's lines, then
        the record line when one is declared."""
        record = None if self.record is None else {
            "keys": list(self.record[0]), "max_bytes": self.record[1]}
        return json.dumps({"alternatives": [list(lines) for lines in self.alternatives],
                           "record": record}, sort_keys=True) + "\n"


def fence_blocks(document: str) -> list[Fence]:
    """CommonMark-style backtick fences: up to three spaces of indent, a closing
    run at least as long as the opening and nothing after it."""
    lines = document.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    blocks, index = [], 0
    while index < len(lines):
        opening = OPEN_FENCE.match(lines[index].rstrip("\n"))
        if opening is None:
            index += 1
            continue
        indent, ticks = len(opening["indent"]), len(opening["ticks"])
        closer = re.compile(rf"^ {{0,3}}`{{{ticks},}}[ \t]*$")
        body, cursor = [], index + 1
        while cursor < len(lines) and not closer.match(lines[cursor].rstrip("\n")):
            line = lines[cursor]
            body.append(line[min(indent, len(line) - len(line.lstrip(" "))):])
            cursor += 1
        if cursor == len(lines):
            raise Refused("a fenced block is never closed")
        blocks.append(Fence(opening["lang"], "".join(body), starts[index], starts[cursor + 1]))
        index = cursor + 1
    return blocks


@dataclass(frozen=True)
class Heading:
    start: int  # the heading line's first character
    end: int  # just after the heading line
    level: int
    title: str


def headings(document: str) -> list[Heading]:
    """Markdown headings, never a ``# comment`` line inside a fenced block."""
    spans = [(block.start, block.end) for block in fence_blocks(document)]
    found, offset = [], 0
    for line in document.splitlines(keepends=True):
        match = HEADING.match(line.rstrip("\n"))
        if match and not any(start <= offset < end for start, end in spans):
            found.append(Heading(offset, offset + len(line), len(match["level"]),
                                 match["title"]))
        offset += len(line)
    return found


def section(document: str, title: str) -> str:
    """The text under exactly one heading named ``title``, to the next heading at
    the same or a higher level."""
    found = headings(document)
    matches = [heading for heading in found if heading.title == title]
    if len(matches) != 1:
        raise Refused(f"heading {title!r} occurs {len(matches)} times")
    chosen = matches[0]
    following = (heading.start for heading in found
                 if heading.start > chosen.start and heading.level <= chosen.level)
    return document[chosen.end:next(following, len(document))]


def fences(text: str) -> list[tuple[str, str]]:
    return [(block.lang, block.body) for block in fence_blocks(text)]


def composition(document: str) -> dict:
    blocks = [body for lang, body in fences(section(document, "Composition")) if lang == "toml"]
    if len(blocks) != 1:
        raise Refused("the Composition section needs exactly one toml block")
    try:
        spec = tomllib.loads(blocks[0])
    except tomllib.TOMLDecodeError as error:
        raise Refused(f"composition is not valid TOML: {error}") from None
    if not set(spec) <= TOP_KEYS:
        raise Refused(f"unknown composition keys {sorted(set(spec) - TOP_KEYS)}")
    return spec


def _strings(value: object, what: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise Refused(f"{what} must be a list of strings")
    return value


def _part(name: str, part: object, sources: dict) -> list[tuple[str, bool]]:
    """(text, reviewed lane block?) for each piece of one part, after strict shape
    checks. A literal is one piece and never reviewed."""
    if not isinstance(part, dict):
        raise Refused(f"step {name}: a part must be a table")
    if set(part) == {"literal"} and isinstance(part["literal"], str):
        literal = part["literal"]
        if not literal.strip():
            raise Refused(f"step {name}: a literal part is empty")
        # Exact bytes: only a missing final newline is supplied.
        return [(literal if literal.endswith("\n") else literal + "\n", False)]
    if not {"source", "heading", "fences"} <= set(part) <= {"source", "heading", "fences", "set"}:
        raise Refused(f"step {name}: a part is exactly a literal or a fence selection")
    source, heading, selected = part["source"], part["heading"], part["fences"]
    filled = part.get("set", {})
    if not isinstance(filled, dict) or not all(
            isinstance(value, str) and COMMIT.fullmatch(value) for value in filled.values()):
        raise Refused(f"step {name}: set fills documented declarations with 40-hex commits")
    if not isinstance(source, str) or source not in sources or not isinstance(heading, str):
        raise Refused(f"step {name}: unknown source {source!r}")
    if not isinstance(selected, list) or not selected or not all(
            type(index) is int for index in selected):
        raise Refused(f"step {name}: fences must be a non-empty list of integers")
    found = fences(section(sources[source], heading))
    pieces = []
    for index in selected:
        if not 0 <= index < len(found):
            raise Refused(f"step {name}: {heading!r} has no fence {index}")
        lang, body = found[index]
        if lang != "bash":
            raise Refused(f"step {name}: {heading!r} fence {index} is not bash")
        if not body.strip():
            raise Refused(f"step {name}: {heading!r} fence {index} is empty")
        pieces.append((body, hashlib.sha256(body.encode("utf-8")).hexdigest() in LANE_BLOCKS))
    # Review standing was decided on the reviewed bytes; filling replaces only the
    # declared line, with a value that cannot be a shell word other than itself.
    for declared, value in filled.items():
        where = [index for index, (body, _) in enumerate(pieces)
                 for match in DECLARATION.finditer(body) if match["name"] == declared]
        if len(where) != 1:
            raise Refused(f"step {name}: {heading!r} declares {declared} {len(where)} times")
        body, reviewed = pieces[where[0]]
        line = re.compile(rf"^{declared}=<[^<>\n]+>$", re.MULTILINE)
        pieces[where[0]] = (line.sub(f"{declared}={value}", body, count=1), reviewed)
    return pieces


def _normalized(text: str) -> str:
    """Bash joins continued lines and adjacent quoted fragments into one word."""
    return SHELL_QUOTING.sub("", text.replace("\\\n", ""))


def _expectation(name: str, entry: dict) -> tuple[tuple[tuple[str, ...], ...],
                                                  tuple[tuple[str, ...], int] | None]:
    """Declared stdout: one list of lines, or a list of distinct alternative lists,
    plus an optional closed record line (`record = {keys, max_bytes}`)."""
    declared = entry["stdout"]
    if isinstance(declared, list) and declared and all(isinstance(x, list) for x in declared):
        alternatives = tuple(tuple(_strings(lines, f"step {name}: stdout")) for lines in declared)
    else:
        alternatives = (tuple(_strings(declared, f"step {name}: stdout")),)
    if len(set(alternatives)) != len(alternatives):
        raise Refused(f"step {name}: stdout alternatives must be distinct")
    if any("\n" in line or "\r" in line for lines in alternatives for line in lines):
        raise Refused(f"step {name}: a built file would not be LF-only")
    record = None
    if "record" in entry:
        spec = entry["record"]
        if (not isinstance(spec, dict) or set(spec) != {"keys", "max_bytes"}
                or type(spec["max_bytes"]) is not int or not 2 <= spec["max_bytes"] <= 8192):
            raise Refused(f"step {name}: record is exactly keys and max_bytes (2-8192)")
        keys = tuple(_strings(spec["keys"], f"step {name}: record keys"))
        if not keys or len(set(keys)) != len(keys) or not all(map(RECORD_KEY.fullmatch, keys)):
            raise Refused(f"step {name}: record keys must be distinct identifiers")
        # The shortest record T5 could accept: compact, every value a digit, and LF.
        shortest = len(json.dumps(dict.fromkeys(keys, 0), separators=(",", ":"))) + 1
        if spec["max_bytes"] < shortest:
            raise Refused(f"step {name}: record max_bytes is below its shortest record "
                          f"({shortest} bytes)")
        record = (tuple(sorted(keys)), spec["max_bytes"])
    largest = max(len("".join(line + "\n" for line in lines).encode("utf-8"))
                  for lines in alternatives) + (record[1] if record else 0)
    if largest > MAX_STDOUT:
        raise Refused(f"step {name}: declared stdout exceeds {MAX_STDOUT} bytes")
    return alternatives, record


def assemble(path: Path, template: bool = False,
             values: dict[str, str] | None = None) -> list[Step]:
    # Raw bytes: text-mode reading would silently translate CRLF and hide it.
    document = path.read_bytes().decode("utf-8")
    if "\r" in document:
        raise Refused("the procedure document is not LF-only")
    spec = composition(document)
    sources = {"self": document}
    declared = spec.get("sources", {})
    if not isinstance(declared, dict):
        raise Refused("sources must be a table")
    for key, source in declared.items():
        if (not isinstance(source, dict) or set(source) != {"path", "sha256"}
                or not all(isinstance(source[field], str) for field in ("path", "sha256"))
                or key == "self"):
            raise Refused(f"source {key} needs exactly a string path and sha256")
        raw = (path.parent / source["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise Refused(f"source {key} does not match its pinned SHA-256")
        if b"\r" in raw:
            raise Refused(f"source {key} is not LF-only")
        sources[key] = raw.decode("utf-8")
    labels = spec.get("labels", {})
    if not isinstance(labels, dict) or not set(labels) <= {"current", "historical"}:
        raise Refused("labels has only current and historical lists")
    current = set(_strings(labels.get("current", []), "labels.current"))
    historical_labels = set(_strings(labels.get("historical", []), "labels.historical"))
    if current & historical_labels:
        raise Refused(f"labels {sorted(current & historical_labels)} are both current "
                      "and historical")
    if values is not None:
        values = _checked(values)
    steps, names, used = [], set(), set()
    declared_steps = spec.get("steps", [])
    if not isinstance(declared_steps, list):
        raise Refused("steps must be a list of tables")
    for entry in declared_steps:
        if not isinstance(entry, dict) or not set(entry) <= STEP_KEYS or not {
                "name", "stdout", "parts"} <= set(entry):
            raise Refused("a step has exactly name, stdout, parts and optional record "
                          "and historical")
        name = entry["name"]
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in names:
            raise Refused(f"step name {name!r} is invalid or repeated")
        names.add(name)
        historical, deferred = entry.get("historical", False), entry.get("deferred", False)
        if type(historical) is not bool or type(deferred) is not bool:
            raise Refused(f"step {name}: historical and deferred must be booleans")
        parts = entry["parts"]
        if not isinstance(parts, list) or not parts:
            raise Refused(f"step {name}: parts must be a non-empty list")
        pieces = [piece for part in parts for piece in _part(name, part, sources)]
        # A piece ending in a line continuation would splice into the next piece,
        # rewriting a reviewed fence's first command (`IGNORED=\` before S1).
        if any(_continues(body) for body, _ in pieces):
            raise Refused(f"step {name}: a part ends in a line continuation")
        # Every piece then ends at a line break, so no word spans two pieces and each
        # is checked alone, comments included (deciding what is a comment would need
        # bash's quote state across lines).
        if any(_invokes(_normalized(body))
               for body, reviewed in pieces if not reviewed):
            raise Refused(f"step {name}: only a reviewed lane-boundary block may invoke "
                          "the lane CLI (#210 lane-output contract)")
        text = "".join(body for body, _ in pieces)
        for key, value in (values or {}).items():
            text, count = re.subn(rf"^{key}=UNREVIEWED$", f"{key}={value}", text,
                                  flags=re.MULTILINE)
            if count:
                used.add(key)
            # Writing a variable takes its bare name; reading it takes `$`. So every
            # bare mention of a measured name is the exact filled line, and any other
            # mention is a read: no export, +=, [i]=, read or printf -v can replace the
            # session value, and a stale literal is never vouched for by another fill.
            # Bash joins quoted and escaped pieces into one word (`RUN_"ID"`), so the
            # mentions are classified after that joining; `$` is kept to tell reads.
            # `$'...'` is ANSI-C quoting, not a read: its `$` goes with the quote.
            words = re.sub(r"[\"'\\]", "", text.replace("\\\n", "").replace("$'", "'"))
            for mention in re.finditer(rf"\b{key}\b", words):
                start = words.rfind("\n", 0, mention.start()) + 1
                end = words.find("\n", mention.end())
                line = words[start:len(words) if end < 0 else end]
                reads = re.search(r"\$\{?[#!]?$", words[start:mention.start()])
                if line != f"{key}={value}" and not reads:
                    raise Refused(f"step {name}: {key} is assigned other than its "
                                  "session value")
        allowed = current | (historical_labels if historical else set())
        joined = _normalized(text)
        stray = sorted({label for label in LABEL.findall(joined) if label not in allowed})
        if stray:
            raise Refused(f"step {name}: undeclared or historical labels {stray}")
        if deferred and values is None and not template:
            # Built later, with measured session values: only those may remain.
            pending = re.sub(rf"^(?:{'|'.join(SESSION_VALUES)})=UNREVIEWED$", "", text,
                             flags=re.MULTILINE)
            if PLACEHOLDER.search(_normalized(pending)) or DECLARATION.search(text):
                raise Refused(f"step {name}: a deferred step may wait only for session values")
        elif not template and (PLACEHOLDER.search(joined) or DECLARATION.search(text)):
            raise Refused(f"step {name}: an unreviewed placeholder remains")
        alternatives, record = _expectation(name, entry)
        if "\r" in text:
            raise Refused(f"step {name}: a built file would not be LF-only")
        step = Step(name, text, alternatives, record,
                    waiting=deferred and values is None and not template)
        # The transport reads at most 65,536 bytes of expectation (Q6's T5).
        if len(step.expected().encode("utf-8")) > MAX_STDOUT:
            raise Refused(f"step {name}: its expectation exceeds {MAX_STDOUT} bytes")
        steps.append(step)
    if not steps:
        raise Refused("the composition declares no steps")
    if set(values or {}) - used:
        raise Refused(f"values {sorted(set(values or {}) - used)} fill no line")
    return steps


def build(path: Path, out: Path, template: bool = False,
          values: dict[str, str] | None = None) -> str:
    steps = assemble(path, template, values)
    try:
        out.mkdir()  # an exclusive claim: refuses an existing path, never replaces one
    except FileExistsError:
        raise Refused("the output directory already exists") from None
    lines = []
    for step in steps:
        if step.waiting:
            continue
        for suffix, body in ((".sh", step.text), (".expected.json", step.expected())):
            raw = body.encode("utf-8")
            with open(out / (step.name + suffix), "xb") as stream:
                stream.write(raw)
            lines.append(f"{hashlib.sha256(raw).hexdigest()}  {step.name}{suffix}\n")
    manifest = "".join(lines).encode("utf-8")
    # Written last: a package without its manifest is visibly incomplete.
    with open(out / "MANIFEST.sha256", "xb") as stream:
        stream.write(manifest)
    return hashlib.sha256(manifest).hexdigest()


def main(argv: list[str]) -> int:
    try:
        arguments = argv[1:]
        template = arguments[-1:] == ["--template"]
        if template:
            arguments = arguments[:-1]
        values = None
        if arguments[:1] == ["build"] and len(arguments) == 5 and arguments[3] == "--values":
            values = session_values(Path(arguments[4]))
            arguments = arguments[:3]
        if arguments[:1] == ["check"] and len(arguments) == 2:
            steps = assemble(Path(arguments[1]), template)
            print(f"composition-checked {len(steps)} steps")
        elif arguments[:1] == ["build"] and len(arguments) == 3:
            print(build(Path(arguments[1]), Path(arguments[2]), template, values))
            waiting = [step.name for step in assemble(Path(arguments[1]), template, values)
                       if step.waiting]
            if waiting:
                print("deferred until session values: " + " ".join(waiting))
        else:
            raise Refused("usage: check DOC [--template] | "
                          "build DOC OUT [--values FILE] [--template]")
    except (Refused, OSError, UnicodeDecodeError) as error:
        print(f"composition refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
