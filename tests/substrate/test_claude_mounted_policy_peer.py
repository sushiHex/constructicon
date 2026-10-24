"""Portable execution of the exact C file comparison; no isolation is claimed."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from constructicon.substrate.executors.claude_native import ClaudeNativeRecipe


@pytest.fixture(scope="module")
def policy_peer(tmp_path_factory):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("portable mounted-policy comparator proof needs a C compiler")
    directory = tmp_path_factory.mktemp("claude-policy-peer")
    peer = Path(__file__).parents[2] / "scripts/ci/m8_claude_peer.c"
    # Compile the actual comparator, substituting only the Linux mount path and
    # fixture input file. The full native peer remains a hosted physical proof.
    comparator = peer.read_text(encoding="utf-8").split(
        "static void policy_content(void) {", 1,
    )[1].split("static void persistence(void) {", 1)[0]
    source = directory / "policy.c"
    source.write_text(
        '#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n'
        'static const char *policy_path;\n#define POLICY policy_path\n'
        'static void require(int condition) { if (!condition) exit(90); }\n'
        'static void policy_content(void) {' + comparator
        + 'int main(int argc, char **argv) {\n'
        'require(argc == 3); policy_path = argv[1];\n'
        'require(freopen(argv[2], "rb", stdin) != NULL);\n'
        'policy_content(); return 0; }\n',
        encoding="utf-8",
    )
    binary = directory / ("policy.exe" if sys.platform == "win32" else "policy")
    compiled = subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
         str(source), "-o", str(binary)],
        stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=30,
    )
    assert compiled.returncode == 0, compiled.stderr.decode(errors="replace")
    return binary


@pytest.mark.parametrize("recipe", list(ClaudeNativeRecipe))
@pytest.mark.parametrize("case", [
    "exact", "changed", "empty", "missing", "trailing", "oversized",
    "empty-expectation", "long-expectation", "unterminated-expectation",
])
def test_actual_policy_comparator_requires_exact_bounded_file(
    policy_peer, tmp_path, recipe, case,
):
    canonical = json.dumps(recipe.policy, sort_keys=True).encode() + b"\n"
    assert 1 < len(canonical) < 4096
    expected = canonical
    observed = canonical
    if case == "changed":
        observed = canonical.replace(b"true", b"null", 1)
        assert observed != canonical and len(observed) == len(canonical)
    elif case == "empty":
        observed = b""
    elif case == "trailing":
        observed += b"private-policy-sentinel"
    elif case == "oversized":
        observed = canonical + b"x" * (4096 - len(canonical))
    elif case == "empty-expectation":
        expected = observed = b"\n"
    elif case == "long-expectation":
        expected = observed = b"x" * 4095 + b"\n"
    elif case == "unterminated-expectation":
        expected = observed = canonical.rstrip(b"\n")
    policy = tmp_path / "managed-settings.json"
    if case != "missing":
        policy.write_bytes(observed)
    expectation = tmp_path / "expected.json"
    expectation.write_bytes(expected)
    result = subprocess.run(
        [str(policy_peer), str(policy), str(expectation)],
        stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=5,
    )
    assert result.stderr == b""
    assert result.returncode == (0 if case == "exact" else 90)
    assert result.stdout.splitlines() == ([b"policy-content:exact"] if case == "exact" else [])
