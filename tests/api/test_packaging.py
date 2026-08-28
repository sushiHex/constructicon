"""Distribution metadata and the optional MCP boundary have one truthful owner."""

from __future__ import annotations

import builtins
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest

from constructicon import __version__
from constructicon.api.mcp.__main__ import main
from constructicon.api.mcp.server import MCP_SERVER_VERSION

ROOT = Path(__file__).parents[2]


def test_distribution_package_and_mcp_versions_agree() -> None:
    assert __version__ == version("constructicon") == MCP_SERVER_VERSION


def test_unexpected_missing_adapter_dependency_is_not_mislabeled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def importing(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "mcp.server.auth.settings":
            raise ModuleNotFoundError("missing transitive dependency", name="adapter_dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importing)
    with pytest.raises(ModuleNotFoundError) as caught:
        main()
    assert caught.value.name == "adapter_dependency"


def test_base_wheel_cli_reports_missing_mcp_extra_without_traceback(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", os.fspath(dist)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(dist.glob("constructicon-*.whl"))
    environment = tmp_path / "base-only"
    subprocess.run(
        ["uv", "venv", os.fspath(environment)],
        check=True,
        capture_output=True,
        text=True,
    )
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--offline",
            "--python",
            os.fspath(python),
            os.fspath(wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    entrypoint = environment / (
        "Scripts/constructicon-mcp.exe" if sys.platform == "win32" else "bin/constructicon-mcp"
    )
    result = subprocess.run(
        [os.fspath(entrypoint), "--help"],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "install constructicon[mcp]" in output
    assert "Traceback" not in output
