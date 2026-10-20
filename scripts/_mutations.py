"""Isolated code-object mutations; assertion failures, never harness errors, count.

No file is rewritten. Each child imports the ordinary implementation and replaces
one function body in memory, so already-imported aliases observe the same mutant.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path


def source_snapshot() -> bytes:
    """Working-tree bytes, including dirty and nonignored untracked inputs.

    Check only at invocation boundaries, not for every mutant. This is a drift
    check for a fixed checkout, not protection against concurrent hostile edits
    that change and restore files between the two snapshots.
    """
    root = Path(__file__).resolve().parents[1]
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=60,
    )
    digest = hashlib.sha256()
    for name in sorted(set(listed.stdout.split(b"\0")) - {b""}):
        path = root / os.fsdecode(name)
        content = path.read_bytes() if not path.is_symlink() else os.fsencode(os.readlink(path))
        digest.update(len(name).to_bytes(8, "big") + name)
        digest.update(len(content).to_bytes(8, "big") + content)
    return digest.digest()


def diagnostic_tail(output) -> str:
    """TimeoutExpired retains bytes even when the child requested text mode."""
    if isinstance(output, bytes):
        return output[-3000:].decode("utf-8", errors="replace")
    return (output or "")[-3000:]


def evidence_nodeids(output: str, marker: str) -> set[str]:
    """Accept exactly one affirmative, structured child report."""
    prefix = marker + " "
    reports = [line[len(prefix):] for line in output.splitlines() if line.startswith(prefix)]
    if len(reports) != 1:
        return set()
    try:
        nodes = json.loads(reports[0])
    except (ValueError, RecursionError):
        return set()
    if not isinstance(nodes, list) or not nodes or any(
        not isinstance(node, str) or not node for node in nodes
    ):
        return set()
    return set(nodes)


def mutated(target: str, before: str, after: str):
    """The function a mutant names and its mutated tree, or why there is none.

    ``before`` must occur exactly once in the dedented source. The harness and
    tests/test_mutation_inventories.py share this, so a refactor that moves a
    target fails the suite instead of surfacing only when the inventory runs.
    """
    module_name, attribute = target.split(":")
    function = importlib.import_module(module_name)
    for part in attribute.split("."):
        function = getattr(function, part)
    if isinstance(function, property):
        function = function.fget
    if inspect.ismethod(function):
        function = function.__func__
    source = textwrap.dedent(inspect.getsource(function))
    if source.count(before) != 1:
        raise RuntimeError(f"mutation must match exactly once: {target}")
    tree = ast.parse(source.replace(before, after, 1))
    tree.body[0].decorator_list = []
    return function, tree


def run(mutants) -> int:
    if len(sys.argv) in (2, 3):
        import pytest

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        class Evidence:
            def __init__(self):
                self.assertions = set()
                self.failed_calls = set()
                self.errors = 0
                self.passed = set()
                self.nonpassing = 0

            def pytest_runtest_makereport(self, item, call):
                if call.excinfo is not None:
                    if call.when == "call" and call.excinfo.errisinstance(
                        (AssertionError, pytest.fail.Exception)
                    ):
                        self.assertions.add(item.nodeid)
                    else:
                        self.errors += 1

            def pytest_collectreport(self, report):
                if report.failed:
                    self.errors += 1
                if report.skipped:
                    self.nonpassing += 1

            def pytest_runtest_logreport(self, report):
                if report.when == "call" and report.failed and not hasattr(report, "wasxfail"):
                    self.failed_calls.add(report.nodeid)
                if not report.passed or hasattr(report, "wasxfail"):
                    self.nonpassing += 1
                elif report.when == "call":
                    self.passed.add(report.nodeid)

        _, target, before, after, test = mutants[int(sys.argv[1])]
        baseline = len(sys.argv) == 3 and sys.argv[2] == "--baseline"
        if baseline:
            # Match the mutant's pre-pytest import; different modules cannot
            # share baseline evidence even when they select the same test.
            importlib.import_module(target.split(":")[0])
        else:
            function, tree = mutated(target, before, after)
            namespace = dict(function.__globals__)
            exec(compile(tree, function.__code__.co_filename, "exec"), namespace)
            function.__code__ = namespace[function.__name__].__code__
        evidence = Evidence()
        status = int(pytest.main(["-q", "--tb=short", test], plugins=[evidence]))
        assertions = evidence.assertions & evidence.failed_calls
        if baseline and status == 0 and evidence.passed and not (
            evidence.errors or evidence.nonpassing
        ):
            print("MUTATION_BASELINE_PASSED", json.dumps(sorted(evidence.passed)))
        elif not baseline and status == 1 and assertions and not evidence.errors:
            print("MUTATION_ASSERTION_FAILURE", json.dumps(sorted(assertions)))
        return status

    # Cache belongs to this invocation only. Every child uses these same
    # execution inputs, and final success also requires unchanged source bytes.
    environment = os.environ.copy()
    directory = Path.cwd()
    executable, inventory = sys.executable, str(Path(sys.argv[0]).resolve())
    try:
        source = source_snapshot()
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"inventory: NOT PROVEN (source snapshot: {str(exc)[-3000:]})", flush=True)
        return 1
    baselines = {}
    outcomes = []
    failed = False
    for index, (name, target, _before, _after, test) in enumerate(mutants):
        selection = (test, target.split(":")[0])
        if selection not in baselines:
            started = time.monotonic()
            try:
                baseline = subprocess.run(
                    [executable, inventory, str(index), "--baseline"],
                    cwd=directory, env=environment, stdin=subprocess.DEVNULL,
                    capture_output=True, text=True, timeout=60,
                )
                passed = (
                    evidence_nodeids(baseline.stdout, "MUTATION_BASELINE_PASSED")
                    if baseline.returncode == 0 else set()
                )
                diagnostics = (baseline.stdout[-3000:], baseline.stderr[-3000:])
            except subprocess.TimeoutExpired as exc:
                passed = set()
                diagnostics = (
                    "baseline harness timeout", diagnostic_tail(exc.stdout),
                    diagnostic_tail(exc.stderr),
                )
            except OSError as exc:
                passed = set()
                diagnostics = ("baseline child failed to start", str(exc)[-3000:])
            elapsed = time.monotonic() - started
            baselines[selection] = passed, diagnostics
            if passed:
                print(f"{name}: BASELINE PASSED ({elapsed:.3f}s)", flush=True)
        passed, diagnostics = baselines[selection]
        if not passed:
            print(f"{name}: NOT PROVEN (baseline did not pass)", flush=True)
            print(*diagnostics)
            failed = True
            continue
        started = time.monotonic()
        try:
            result = subprocess.run(
                [executable, inventory, str(index)],
                cwd=directory, env=environment, stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started
            print(f"{name}: NOT PROVEN (harness timeout; {elapsed:.3f}s)", flush=True)
            failed = True
            continue
        elapsed = time.monotonic() - started
        killed = result.returncode == 1 and bool(
            passed & evidence_nodeids(result.stdout, "MUTATION_ASSERTION_FAILURE")
        )
        outcomes.append((name, killed, elapsed))
        if not killed:
            print(result.stdout[-3000:], result.stderr[-3000:])
            failed = True
    source_stable = False
    try:
        source_stable = source_snapshot() == source
        if not source_stable:
            print("inventory: NOT PROVEN (source changed during invocation)", flush=True)
            failed = True
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"inventory: NOT PROVEN (source snapshot: {str(exc)[-3000:]})", flush=True)
        failed = True
    # Do not publish kill credit before the source check can invalidate it.
    for name, killed, elapsed in outcomes:
        verdict = "KILLED" if killed and source_stable else "NOT PROVEN"
        print(f"{name}: {verdict} ({elapsed:.3f}s)", flush=True)
    return int(failed)
