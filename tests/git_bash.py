"""The one shell the runbook tests execute scripts with.

On Windows `shutil.which("bash")` can return `C:/Windows/System32/bash.exe`,
the WSL launcher, which fails before any script runs when no distribution is
installed. So on Windows only Git Bash is accepted: the declared installation,
then the one beside the `git` on PATH. PATH is never searched for `bash` there.
Elsewhere the normal discovery applies. An absent shell skips with a reason; it
is never reported as a passing execution.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

DECLARED = "C:/Program Files/Git/bin/bash.exe"


def find_bash(
    *,
    windows: bool | None = None,
    which: Callable[[str], str | None] = shutil.which,
    is_file: Callable[[Path], bool] = Path.is_file,
) -> str | None:
    """The bash to execute scripts with, or None when no supported one exists."""

    if not (os.name == "nt" if windows is None else windows):
        return which("bash")
    if is_file(Path(DECLARED)):
        return DECLARED
    git = which("git")
    if git is not None:
        beside = Path(git).resolve().parent.parent / "bin" / "bash.exe"
        if is_file(beside):
            return str(beside)
    return None


def git_bash() -> str:
    """The selected bash, or skip the test with the reason it cannot execute."""

    found = find_bash()
    if found is None:
        pytest.skip("the runbook tests require Git Bash on Windows, or bash elsewhere")
    return found
