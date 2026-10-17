"""Pin the shell-selection rule the runbook tests share."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests import git_bash as selector

WSL = "C:/Windows/System32/bash.EXE"
GIT_EXE = "C:/Tools/Git/cmd/git.exe"
BESIDE_GIT = Path("C:/Tools/Git/cmd/git.exe").resolve().parent.parent / "bin" / "bash.exe"


def _which(table: dict[str, str]):
    return lambda name: table.get(name)


def _exists(*present: Path):
    wanted = {Path(p) for p in present}
    return lambda path: Path(path) in wanted


def test_windows_prefers_the_declared_install_over_a_wsl_shim_first_on_path() -> None:
    found = selector.find_bash(
        windows=True,
        which=_which({"bash": WSL, "git": GIT_EXE}),
        is_file=_exists(Path(selector.DECLARED), BESIDE_GIT),
    )
    assert found == selector.DECLARED


def test_windows_falls_back_to_the_bash_beside_git() -> None:
    found = selector.find_bash(
        windows=True,
        which=_which({"bash": WSL, "git": GIT_EXE}),
        is_file=_exists(BESIDE_GIT),
    )
    assert found == str(BESIDE_GIT)


def test_windows_never_selects_the_wsl_shim_when_git_bash_is_absent() -> None:
    assert selector.find_bash(
        windows=True, which=_which({"bash": WSL}), is_file=_exists(),
    ) is None
    assert selector.find_bash(
        windows=True, which=_which({"bash": WSL, "git": GIT_EXE}), is_file=_exists(),
    ) is None


def test_other_platforms_keep_normal_discovery() -> None:
    assert selector.find_bash(windows=False, which=_which({"bash": "/bin/bash"})) == "/bin/bash"
    assert selector.find_bash(windows=False, which=_which({})) is None


def test_an_absent_shell_skips_with_a_reason_and_never_returns(monkeypatch) -> None:
    monkeypatch.setattr(selector, "find_bash", lambda: None)
    with pytest.raises(pytest.skip.Exception, match="require Git Bash"):
        selector.git_bash()


@pytest.mark.skipif(os.name != "nt", reason="the live selection is pinned on Windows")
def test_the_live_windows_selection_executes_and_is_not_wsl() -> None:
    chosen = selector.git_bash()
    assert "system32" not in chosen.replace("\\", "/").lower()
    ran = subprocess.run(
        [chosen, "-c", "printf ok"], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert ran.returncode == 0 and ran.stdout == "ok"
