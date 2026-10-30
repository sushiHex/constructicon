"""A mutation kill needs an affirmative passing, isolated unmutated control."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import _mutations as mutations

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ("guard", "subject:value", "return 1", "return 2", "test_subject.py")


def inventory(
    tmp_path: Path, test: str, entries: list[tuple] | None = None, *,
    subject_source: str = "def value():\n    return 1\n",
):
    (tmp_path / "subject.py").write_text(subject_source, encoding="utf-8")
    (tmp_path / "test_subject.py").write_text(test, encoding="utf-8")
    script = tmp_path / "inventory.py"
    script.write_text(
        "from scripts._mutations import run\n"
        f"raise SystemExit(run({entries or [ENTRY]!r}))\n",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(ROOT), str(tmp_path))),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    return subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, env=environment,
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
        check=False,
    )


def test_passing_baseline_then_assertion_mutant_is_a_kill(tmp_path):
    result = inventory(
        tmp_path, "import subject\ndef test_value():\n    assert subject.value() == 1\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BASELINE PASSED" in result.stdout
    assert "guard: KILLED" in result.stdout


@pytest.mark.parametrize(
    "test",
    [
        "def test_value():\n    assert False\n",
        "def test_value():\n    raise RuntimeError('baseline broke')\n",
        "raise RuntimeError('collection broke')\n",
        "import pytest\n@pytest.mark.skip\ndef test_value():\n    pass\n",
        "import pytest\n@pytest.mark.xfail\ndef test_value():\n    assert False\n",
        "import pytest\n@pytest.mark.xfail\ndef test_value():\n    pass\n",
        "# No test collected.\n",
        "import pytest\n@pytest.fixture\ndef fixture():\n    yield\n    assert False\n"
        "def test_value(fixture):\n    pass\n",
        "import pytest\ndef test_good():\n    pass\n"
        "@pytest.mark.skip\ndef test_skipped():\n    pass\n",
    ],
    ids=["already-failing", "call-error", "collection-error", "skip-only", "xfail",
         "xpass", "uncollected", "teardown-error", "passing-plus-skip"],
)
def test_nonpassing_or_unexecuted_baseline_cannot_credit_a_kill(tmp_path, test):
    result = inventory(tmp_path, test)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "guard: NOT PROVEN (baseline did not pass)" in result.stdout
    assert "KILLED" not in result.stdout
    assert "BASELINE PASSED" not in result.stdout


def test_assertion_only_mutant_rule_is_preserved(tmp_path):
    entry = (*ENTRY[:3], "raise RuntimeError('mutant broke')", ENTRY[4])
    result = inventory(
        tmp_path, "import subject\ndef test_value():\n    assert subject.value() == 1\n", [entry],
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "BASELINE PASSED" in result.stdout
    assert "guard: NOT PROVEN" in result.stdout
    assert "KILLED" not in result.stdout


def test_a_new_mutant_nodeid_has_no_passing_baseline(tmp_path):
    result = inventory(
        tmp_path,
        "import pytest, subject\n"
        "@pytest.mark.parametrize('value', [subject.value()])\n"
        "def test_value(value):\n    assert value == 1\n",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "guard: NOT PROVEN" in result.stdout
    assert "KILLED" not in result.stdout


def test_conditional_xfail_is_collected_before_the_body_is_mutated(tmp_path):
    result = inventory(
        tmp_path,
        "import pytest, subject\n"
        "values = [pytest.param(1, marks=pytest.mark.xfail(\n"
        "    condition=subject.value() != 1, reason='conditional control'))]\n"
        "if subject.value() != 1:\n    values.append(2)\n"
        "@pytest.mark.parametrize('value', values)\n"
        "def test_value(value):\n    assert subject.value() == value == 1\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BASELINE PASSED" in result.stdout
    assert "guard: KILLED" in result.stdout


@pytest.mark.parametrize("replace", [False, True], ids=["insert-before", "same-count-replacement"])
def test_opaque_positional_ids_cannot_manufacture_a_controlled_case(tmp_path, replace):
    collection = (
        "values = [retained if subject.value() == 1 else object()]\n" if replace else
        "values = [retained]\nif subject.value() != 1:\n    values.insert(0, object())\n"
    )
    result = inventory(
        tmp_path, "import pytest, subject\nretained = object()\n" + collection
        + "@pytest.mark.parametrize('value', values)\n"
        "def test_value(value):\n    assert value is retained\n",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "BASELINE PASSED" in result.stdout
    assert "guard: NOT PROVEN" in result.stdout
    assert "KILLED" not in result.stdout


def test_mutation_is_active_before_fixture_setup(tmp_path):
    result = inventory(
        tmp_path, "import pytest, subject\n"
        "@pytest.fixture\ndef observed():\n    return subject.value()\n"
        "def test_value(observed):\n    assert observed == 1\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "guard: KILLED" in result.stdout


def test_mutation_children_leave_the_ordinary_failure_cache_untouched(tmp_path):
    """A deliberate mutant failure must not masquerade as a real last failure (#280)."""

    cache = tmp_path / ".pytest_cache" / "v" / "cache" / "lastfailed"
    cache.parent.mkdir(parents=True)
    sentinel = b'{\n  "test_real.py::test_interrupted": true\n}'
    cache.write_bytes(sentinel)
    result = inventory(
        tmp_path, "import subject\ndef test_value():\n    assert subject.value() == 1\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BASELINE PASSED" in result.stdout
    assert "guard: KILLED" in result.stdout
    assert cache.read_bytes() == sentinel
    assert sorted(path.name for path in cache.parent.iterdir()) == ["lastfailed"]


def test_a_closure_bearing_target_is_diagnosed_before_pytest(tmp_path):
    """Zero-argument super() needs a __class__ cell a recompiled body lacks (#290)."""

    entry = ("guard", "subject:Child.value", "return super().value()",
             "return super().value() + 1", "test_subject.py")
    result = inventory(
        tmp_path, "import subject\ndef test_value():\n    assert subject.Child().value() == 1\n",
        [entry],
        subject_source="class Base:\n    def value(self):\n        return 1\n"
        "class Child(Base):\n    def value(self):\n        return super().value()\n",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "BASELINE PASSED" in result.stdout
    assert "MUTATION_UNSUPPORTED subject:Child.value free variables" in result.stdout
    assert "guard: NOT PROVEN" in result.stdout
    assert "KILLED" not in result.stdout
    assert "INTERNALERROR" not in result.stdout + result.stderr


def test_all_collection_hooks_return_before_mutation_activation(tmp_path):
    (tmp_path / "conftest.py").write_text(
        "import pytest, subject\nsubject.collection_events = []\n"
        "def pytest_collection_finish(session):\n"
        "    assert subject.value() == 1\n"
        "    subject.collection_events.append('finish')\n"
        "@pytest.hookimpl(wrapper=True, tryfirst=True)\n"
        "def pytest_collection(session):\n"
        "    result = yield\n"
        "    assert subject.value() == 1\n"
        "    subject.collection_events.append('wrapper')\n"
        "    return result\n",
        encoding="utf-8",
    )
    result = inventory(
        tmp_path, "import subject\ndef test_value():\n"
        "    assert subject.collection_events == ['finish', 'wrapper']\n"
        "    assert subject.value() == 1\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "guard: KILLED" in result.stdout


def test_preparing_unused_target_does_not_execute_its_default(tmp_path):
    result = inventory(
        tmp_path, "import subject\ndef test_value():\n    assert subject.events == ['default']\n",
        subject_source="events = []\ndef touch():\n    events.append('default')\n"
        "def value(argument=touch()):\n    return 1\n",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "BASELINE PASSED" in result.stdout
    assert "guard: NOT PROVEN" in result.stdout
    assert "KILLED" not in result.stdout


def test_missing_activation_cannot_emit_assertion_credit(monkeypatch, capsys):
    def original():
        return 1

    monkeypatch.setattr(mutations.sys, "argv", ["inventory.py", "0"])
    monkeypatch.setattr(
        mutations, "mutated",
        lambda *_args: (original, ast.parse("def original():\n    return 2\n")),
    )

    def no_test_loop(_args, plugins):
        evidence = plugins[0]
        evidence.assertions.add("test::case")
        evidence.failed_calls.add("test::case")
        return 1

    monkeypatch.setattr(pytest, "main", no_test_loop)
    assert mutations.run([ENTRY]) == 1
    assert "MUTATION_ASSERTION_FAILURE" not in capsys.readouterr().out
    assert original() == 1


def fake_invocation(monkeypatch, results, *, snapshots=(b"source", b"source")):
    monkeypatch.setattr(mutations.sys, "argv", ["inventory.py"])
    source = iter(snapshots)
    monkeypatch.setattr(mutations, "source_snapshot", lambda: next(source))
    replies = iter(results)
    calls = []

    def run_child(command, **kwargs):
        calls.append((command, kwargs))
        result = next(replies)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(mutations.subprocess, "run", run_child)
    return calls


COLLECTION = 'MUTATION_COLLECTION ["test::case"]\n'
PASS = subprocess.CompletedProcess(
    [], 0, COLLECTION + 'MUTATION_BASELINE_PASSED ["test::case"]\n', "",
)
KILL = subprocess.CompletedProcess(
    [], 1, COLLECTION + 'MUTATION_ASSERTION_FAILURE ["test::case"]\n', "",
)


@pytest.mark.parametrize("phase", ["baseline", "mutant"])
@pytest.mark.parametrize("collection", [
    "", "MUTATION_COLLECTION {}\n", "MUTATION_COLLECTION []\n", COLLECTION + COLLECTION,
], ids=["missing", "malformed", "empty", "duplicate"])
def test_missing_or_invalid_collection_receipt_refuses_credit(
    monkeypatch, capsys, phase, collection,
):
    marker = 'MUTATION_BASELINE_PASSED ["test::case"]\n' if phase == "baseline" else (
        'MUTATION_ASSERTION_FAILURE ["test::case"]\n'
    )
    bad = subprocess.CompletedProcess([], 0 if phase == "baseline" else 1, collection + marker, "")
    calls = fake_invocation(monkeypatch, [bad, KILL] if phase == "baseline" else [PASS, bad])
    assert mutations.run([ENTRY]) == 1
    assert len(calls) == (1 if phase == "baseline" else 2)
    assert "KILLED" not in capsys.readouterr().out


def test_ordered_collection_drift_refuses_credit(monkeypatch, capsys):
    baseline = subprocess.CompletedProcess(
        [], 0, 'MUTATION_COLLECTION ["test::case", "test::other"]\n'
        'MUTATION_BASELINE_PASSED ["test::case", "test::other"]\n', "",
    )
    mutant = subprocess.CompletedProcess(
        [], 1, 'MUTATION_COLLECTION ["test::other", "test::case"]\n'
        'MUTATION_ASSERTION_FAILURE ["test::case"]\n', "",
    )
    fake_invocation(monkeypatch, [baseline, mutant])
    assert mutations.run([ENTRY]) == 1
    assert "KILLED" not in capsys.readouterr().out


@pytest.mark.parametrize("phase", ["baseline", "mutant"])
@pytest.mark.parametrize("payload", ["", " {}", " []", ' ["test::case"]\n{marker} []'])
def test_missing_malformed_or_duplicate_child_evidence_refuses_credit(
    monkeypatch, capsys, phase, payload,
):
    marker = "MUTATION_BASELINE_PASSED" if phase == "baseline" else "MUTATION_ASSERTION_FAILURE"
    bad = subprocess.CompletedProcess(
        [], 0 if phase == "baseline" else 1,
        COLLECTION + marker + payload.replace("{marker}", marker), "",
    )
    calls = fake_invocation(monkeypatch, [bad] if phase == "baseline" else [PASS, bad])
    assert mutations.run([ENTRY]) == 1
    assert len(calls) == (1 if phase == "baseline" else 2)
    assert "KILLED" not in capsys.readouterr().out


def test_duplicate_selection_reuses_control_but_each_mutant_is_isolated(monkeypatch, capsys):
    calls = fake_invocation(monkeypatch, [PASS, KILL, KILL])
    assert mutations.run([ENTRY, ENTRY]) == 0
    assert [call[0][-2:] for call in calls] == [
        ["0", "--baseline"], [str(Path("inventory.py").resolve()), "0"],
        [str(Path("inventory.py").resolve()), "1"],
    ]
    assert all(call[1] == calls[0][1] for call in calls)
    assert capsys.readouterr().out.count("BASELINE PASSED") == 1


@pytest.mark.parametrize("changed", ["test", "module"])
def test_selection_or_preimport_change_needs_a_distinct_control(monkeypatch, changed):
    other = list(ENTRY)
    other[4 if changed == "test" else 1] = "other_test.py" if changed == "test" else "other:value"
    calls = fake_invocation(monkeypatch, [PASS, KILL, PASS, KILL])
    assert mutations.run([ENTRY, tuple(other)]) == 0
    assert [call[0][-1] for call in calls] == ["--baseline", "0", "--baseline", "1"]


def test_cache_does_not_cross_invocations(monkeypatch):
    calls = fake_invocation(monkeypatch, [PASS, KILL, PASS, KILL], snapshots=(b"s",) * 4)
    assert mutations.run([ENTRY]) == 0
    assert mutations.run([ENTRY]) == 0
    assert sum(call[0][-1] == "--baseline" for call in calls) == 2


@pytest.mark.parametrize(
    "result",
    [subprocess.CompletedProcess([], 0, "", ""),
     subprocess.CompletedProcess([], 1, 'MUTATION_BASELINE_PASSED ["test::case"]\n', ""),
     subprocess.TimeoutExpired([], 60)],
    ids=["no-affirmative-pass", "wrong-exit", "timeout"],
)
def test_baseline_refusal_never_starts_mutant_and_is_cached(monkeypatch, capsys, result):
    calls = fake_invocation(monkeypatch, [result])
    assert mutations.run([ENTRY, ENTRY]) == 1
    assert len(calls) == 1
    output = capsys.readouterr().out
    assert output.count("NOT PROVEN (baseline did not pass)") == 2
    assert "KILLED" not in output


def test_source_drift_invalidates_all_pending_kills(monkeypatch, capsys):
    fake_invocation(monkeypatch, [PASS, KILL], snapshots=(b"before", b"after"))
    assert mutations.run([ENTRY]) == 1
    output = capsys.readouterr().out
    assert "source changed during invocation" in output
    assert "guard: NOT PROVEN" in output
    assert "KILLED" not in output


@pytest.mark.parametrize("stage", ["before", "after"])
def test_unreadable_source_refuses_proof(monkeypatch, capsys, stage):
    calls = fake_invocation(monkeypatch, [PASS, KILL])
    count = 0

    def snapshot():
        nonlocal count
        count += 1
        if count == (1 if stage == "before" else 2):
            raise OSError("cannot read source")
        return b"source"

    monkeypatch.setattr(mutations, "source_snapshot", snapshot)
    assert mutations.run([ENTRY]) == 1
    assert len(calls) == (0 if stage == "before" else 2)
    output = capsys.readouterr().out
    assert "NOT PROVEN (source snapshot:" in output
    assert "KILLED" not in output


@pytest.mark.parametrize("timeout", [False, True])
def test_failed_baseline_retains_bounded_diagnostics(monkeypatch, capsys, timeout):
    output, error = "discarded-prefix" + "o" * 3000, "discarded-prefix" + "e" * 3000
    result = (
        subprocess.TimeoutExpired([], 60, output.encode(), error.encode()) if timeout
        else subprocess.CompletedProcess([], 1, output, error)
    )
    fake_invocation(monkeypatch, [result])
    assert mutations.run([ENTRY]) == 1
    captured = capsys.readouterr().out
    assert "o" * 3000 in captured and "e" * 3000 in captured
    assert "discarded-prefix" not in captured
    assert len(captured) < 6200


def test_baseline_launch_error_refuses_credit(monkeypatch, capsys):
    calls = fake_invocation(monkeypatch, [OSError("cannot start child")])
    assert mutations.run([ENTRY]) == 1
    assert len(calls) == 1
    output = capsys.readouterr().out
    assert "baseline child failed to start" in output
    assert "KILLED" not in output


def test_snapshot_binds_dirty_and_untracked_bytes_and_ignores_list_order(tmp_path, monkeypatch):
    monkeypatch.setattr(mutations, "__file__", str(tmp_path / "scripts" / "_mutations.py"))
    tracked, untracked = tmp_path / "tracked.py", tmp_path / "new.py"
    tracked.write_text("original", encoding="utf-8")
    untracked.write_text("new", encoding="utf-8")
    listings = iter((b"tracked.py\0new.py\0", b"new.py\0tracked.py\0",
                     b"tracked.py\0new.py\0", b"tracked.py\0new.py\0"))
    calls = []

    def listed(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, next(listings), b"")

    monkeypatch.setattr(mutations.subprocess, "run", listed)
    original = mutations.source_snapshot()
    assert mutations.source_snapshot() == original
    tracked.write_text("dirty", encoding="utf-8")
    dirty = mutations.source_snapshot()
    assert dirty != original
    untracked.write_text("changed", encoding="utf-8")
    assert mutations.source_snapshot() != dirty
    assert all(call[0] == ["git", "-c", f"safe.directory={tmp_path.resolve().as_posix()}",
                           "ls-files", "--cached", "--others",
                           "--exclude-standard", "-z"] for call in calls)
    assert all(call[1]["stdin"] == subprocess.DEVNULL for call in calls)


def test_snapshot_reads_an_exact_checkout_with_different_ownership(tmp_path, monkeypatch):
    created = subprocess.run(
        ["git", "init", str(tmp_path)], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, check=False,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    (tmp_path / "input.py").write_text("input bytes", encoding="utf-8")
    monkeypatch.setattr(mutations, "__file__", str(tmp_path / "scripts" / "_mutations.py"))
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
    monkeypatch.setenv("LC_ALL", "C")
    refused = subprocess.run(
        ["git", "-c", "safe.directory=", "ls-files"], cwd=tmp_path,
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
    )
    assert refused.returncode != 0
    assert "dubious ownership" in refused.stderr
    first = mutations.source_snapshot()
    (tmp_path / "input.py").write_text("changed input", encoding="utf-8")
    assert mutations.source_snapshot() != first
