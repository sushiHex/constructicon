"""Verification retains child status without changing gate execution or outcome."""

from __future__ import annotations

import subprocess

import pytest

from constructicon import _verify


@pytest.mark.parametrize(
    ("returncodes", "summary"),
    [
        ((0, 0, 0, 0), "verify OK: lint, types, layer contract, tests"),
        ((1, 0, 0, 0), "verify FAILED: ruff (returncode=1)"),
        ((0, 2, 0, 0), "verify FAILED: mypy (returncode=2)"),
        ((0, 0, 3, 0), "verify FAILED: import-linter (returncode=3)"),
        ((0, 0, 0, 1), "verify FAILED: pytest (returncode=1)"),
        ((0, 0, 0, -9), "verify FAILED: pytest (returncode=-9)"),
        ((0, 0, 0, -1073741819), "verify FAILED: pytest (returncode=-1073741819)"),
        ((0, 0, 0, 3221225477), "verify FAILED: pytest (returncode=3221225477)"),
        (
            (1, -15, 0, 3221225477),
            "verify FAILED: ruff (returncode=1), mypy (returncode=-15), "
            "pytest (returncode=3221225477)",
        ),
    ],
)
def test_verify_retains_failed_child_status_and_runs_every_stage_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    returncodes: tuple[int, ...],
    summary: str,
) -> None:
    calls: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...], *, check: bool) -> subprocess.CompletedProcess[str]:
        assert check is False
        status = returncodes[len(calls)]
        calls.append(command)
        return subprocess.CompletedProcess(command, status)

    monkeypatch.setattr(_verify.subprocess, "run", run)
    if any(returncodes):
        with pytest.raises(SystemExit) as stopped:
            _verify.main()
        assert stopped.value.code == 1
    else:
        assert _verify.main() is None

    assert calls == [
        ("ruff", "check", "src", "tests"),
        ("mypy",),
        ("lint-imports",),
        ("pytest", "-q"),
    ]
    assert capsys.readouterr().out.splitlines() == [
        "== ruff: ruff check src tests",
        "== mypy: mypy",
        "== import-linter: lint-imports",
        "== pytest: pytest -q",
        summary,
    ]
