"""Isolated code-object mutations; assertion failures, never harness errors, count.

No file is rewritten. Each child imports the ordinary implementation and replaces
one function body in memory, so already-imported aliases observe the same mutant.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import subprocess
import sys
import textwrap
from pathlib import Path


def run(mutants) -> int:
    if len(sys.argv) == 2:
        import pytest

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        class Evidence:
            assertions = 0
            errors = 0

            def pytest_runtest_makereport(self, item, call):
                if call.excinfo is not None:
                    if call.when == "call" and call.excinfo.errisinstance(
                        (AssertionError, pytest.fail.Exception)
                    ):
                        self.assertions += 1
                    else:
                        self.errors += 1

            def pytest_collectreport(self, report):
                if report.failed:
                    self.errors += 1

        _, target, before, after, test = mutants[int(sys.argv[1])]
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
        namespace = dict(function.__globals__)
        exec(compile(tree, function.__code__.co_filename, "exec"), namespace)
        function.__code__ = namespace[function.__name__].__code__
        evidence = Evidence()
        status = int(pytest.main(["-q", "--tb=short", test], plugins=[evidence]))
        if status == 1 and evidence.assertions and not evidence.errors:
            print("MUTATION_ASSERTION_FAILURE")
        return status

    failed = False
    for index, (name, *_) in enumerate(mutants):
        try:
            result = subprocess.run(
                [sys.executable, sys.argv[0], str(index)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            print(f"{name}: NOT PROVEN (harness timeout)", flush=True)
            failed = True
            continue
        killed = result.returncode == 1 and "MUTATION_ASSERTION_FAILURE" in result.stdout
        print(f"{name}: {'KILLED' if killed else 'NOT PROVEN'}", flush=True)
        if not killed:
            print(result.stdout[-3000:], result.stderr[-3000:])
            failed = True
    return int(failed)
