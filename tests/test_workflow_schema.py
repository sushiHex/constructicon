"""Every workflow file is shaped the way GitHub loads it.

GitHub voids a whole workflow for one invalid key, scope or expression and
shows only a jobless failed run attributed to ``push``; no required check
fails (issue #218, PR #212). ``tests/test_workflow_triggers.py`` pins the event
names. This file pins the rest of the load-time surface that a stdlib reader
can check without a YAML dependency or a network fetch: the top-level keys,
job keys, step keys, ``permissions`` scopes and levels, tabs, and the
contexts and functions inside every ``${{ }}`` expression. It reads the
repository's own workflow text, so it runs offline inside ``uv run verify``.
It is not a full linter: shell errors in ``run:`` blocks and expression
typing stay unchecked.
"""

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).parents[1] / ".github" / "workflows").glob("*.y*ml"))

# https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
# as read on 2026-10-17.
TOP_KEYS = frozenset({
    "name", "run-name", "on", "permissions", "env", "defaults", "concurrency", "jobs",
})
JOB_KEYS = frozenset({
    "name", "permissions", "needs", "if", "runs-on", "environment", "concurrency", "outputs",
    "env", "defaults", "steps", "timeout-minutes", "strategy", "continue-on-error",
    "container", "services", "uses", "with", "secrets",
})
STEP_KEYS = frozenset({
    "id", "if", "name", "uses", "run", "working-directory", "shell", "with", "env",
    "continue-on-error", "timeout-minutes",
})
PERMISSION_SCOPES = frozenset({
    "actions", "attestations", "checks", "contents", "deployments", "discussions", "id-token",
    "issues", "models", "packages", "pages", "pull-requests", "repository-projects",
    "security-events", "statuses",
})
PERMISSION_LEVELS = frozenset({"read", "write", "none"})
# https://docs.github.com/en/actions/reference/workflows-and-actions/contexts
CONTEXTS = frozenset({
    "github", "env", "vars", "job", "jobs", "steps", "runner", "secrets", "strategy", "matrix",
    "needs", "inputs",
})
FUNCTIONS = frozenset({
    "contains", "startsWith", "endsWith", "format", "join", "toJSON", "fromJSON", "hashFiles",
    "success", "always", "cancelled", "failure",
})

KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*(?=:(?: |$))")


def keys(lines: list[str], width: int) -> list[str]:
    """The mapping keys written at exactly ``width`` spaces; deeper lines (block
    scalars, nested mappings) and comments are skipped."""
    found = []
    for line in lines:
        body = line.lstrip()
        if body and not body.startswith("#") and len(line) - len(body) == width:
            key = KEY.match(body)
            if key:
                found.append(key[0])
    return found


def children(lines: list[str], key: str, width: int) -> list[str]:
    """The lines nested under the ``key:`` line written at ``width`` spaces."""
    out, inside = [], False
    for line in lines:
        indent = len(line) - len(line.lstrip())
        if inside and line.strip() and not line.lstrip().startswith("#") and indent <= width:
            break
        if inside:
            out.append(line)
        elif re.fullmatch(" " * width + re.escape(key) + r": *(#.*)?", line):
            inside = True
    return out


def structure(text: str) -> list[str]:
    """Every problem found in one workflow's text."""
    problems = []
    lines = text.splitlines()
    if "\t" in text:
        problems.append("tab character")
    top = keys(lines, 0)
    problems += [f"top-level key {k!r}" for k in top if k not in TOP_KEYS]
    problems += [f"missing top-level {k!r}" for k in ("on", "jobs") if k not in top]

    def permissions(scope_lines: list[str], width: int, where: str) -> None:
        for line in children(scope_lines, "permissions", width - 2):
            pair = re.fullmatch(" " * width + r"([\w-]+): *(\S+?) *(#.*)?", line)
            if pair is None:
                continue
            if pair[1] not in PERMISSION_SCOPES:
                problems.append(f"{where} permission scope {pair[1]!r}")
            if pair[2] not in PERMISSION_LEVELS:
                problems.append(f"{where} permission level {pair[2]!r} for {pair[1]!r}")

    permissions(lines, 2, "workflow")
    jobs = children(lines, "jobs", 0)
    names = keys(jobs, 2)
    if not names:
        problems.append("no jobs")
    for name in names:
        body = children(jobs, name, 2)
        job_keys = keys(body, 4)
        problems += [f"job {name!r} key {k!r}" for k in job_keys if k not in JOB_KEYS]
        if "runs-on" not in job_keys and "uses" not in job_keys:
            problems.append(f"job {name!r} has neither runs-on nor uses")
        permissions(body, 6, f"job {name!r}")
        steps = children(body, "steps", 4)
        # A step's first key follows "- "; blank that marker so all keys share width 8.
        flat = [re.sub(r"^      - ", "        ", line) for line in steps]
        problems += [f"job {name!r} step key {k!r}" for k in keys(flat, 8) if k not in STEP_KEYS]

    if text.count("${{") != text.count("}}"):
        problems.append("unbalanced ${{ }}")
    for expression in re.findall(r"\$\{\{(.*?)\}\}", text, re.S):
        bare = re.sub(r"'(?:[^']|'')*'", "''", expression)
        for name, after in re.findall(r"(?<![\w.-])([A-Za-z_][\w-]*)\s*([.(\[]?)", bare):
            if name in {"true", "false", "null"}:
                continue
            if after == "(" and name not in FUNCTIONS:
                problems.append(f"unknown function {name!r}")
            elif after != "(" and name not in CONTEXTS:
                problems.append(f"unknown context {name!r}")
    return problems


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_every_workflow_loads(workflow: Path) -> None:
    assert structure(workflow.read_text(encoding="utf-8")) == []


GOOD = """name: x
on:
  push:
permissions:
  contents: read
jobs:
  a:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - name: n
        if: always() && github.event_name == 'push'
        run: |
          echo ${{ github.sha }}
          echo "bad: key"
"""


def test_a_valid_workflow_is_accepted() -> None:
    assert structure(GOOD) == []


@pytest.mark.parametrize(
    ("old", "new", "expect"),
    [
        ("name: x\n", "name: x\nrun_name: y\n", "top-level key 'run_name'"),
        ("  contents: read", "  content: read", "permission scope 'content'"),
        ("  contents: read", "  contents: reed", "permission level 'reed'"),
        ("    runs-on: ubuntu-24.04", "    runs_on: ubuntu-24.04", "key 'runs_on'"),
        ("    runs-on: ubuntu-24.04", "    runs-on: ubuntu-24.04\n    step: x", "key 'step'"),
        ("      - uses: actions/checkout@v4",
         "      - uses: actions/checkout@v4\n        wiht:\n          a: b", "step key 'wiht'"),
        ("      - name: n\n", "      - nmae: n\n", "step key 'nmae'"),
        ("${{ github.sha }}", "${{ github.sha }", "unbalanced"),
        ("${{ github.sha }}", "${{ githb.sha }}", "unknown context 'githb'"),
        ("${{ github.sha }}", "${{ alwayz() }}", "unknown function 'alwayz'"),
        ("run: |", "run:\t|", "tab character"),
        ("jobs:\n", "jobz:\n", "missing top-level 'jobs'"),
        ("on:\n  push:\n", "", "missing top-level 'on'"),
        ("    runs-on: ubuntu-24.04\n", "    permissions:\n      contnts: read\n",
         "job 'a' permission scope 'contnts'"),
    ],
)
def test_each_invalid_shape_is_refused(old: str, new: str, expect: str) -> None:
    assert old in GOOD
    assert any(expect in p for p in structure(GOOD.replace(old, new, 1))), expect
