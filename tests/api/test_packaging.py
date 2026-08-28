"""Distribution metadata and the optional MCP boundary have one truthful owner."""

from __future__ import annotations

import builtins
import os
import subprocess
import zipfile
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


def test_base_wheel_ships_the_cli_and_requires_mcp_only_under_its_extra(tmp_path: Path) -> None:
    """The distribution itself carries the optional boundary.

    Read the built metadata rather than installing it: an install resolves
    `pydantic>=2.7` against a registry, so it passes or fails on whatever the
    runner's package cache happens to hold. The wheel's own `Requires-Dist`
    and `entry_points.txt` state the packaging contract exactly, and reading
    them needs no network, no cache, and no second interpreter.
    """

    dist = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", os.fspath(dist)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(dist.glob("constructicon-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        info = next(
            name.rsplit("/", 1)[0] for name in archive.namelist() if name.endswith("/METADATA")
        )
        metadata = archive.read(f"{info}/METADATA").decode("utf-8")
        entry_points = archive.read(f"{info}/entry_points.txt").decode("utf-8")

    requirements = [
        line.removeprefix("Requires-Dist:").strip()
        for line in metadata.splitlines()
        if line.startswith("Requires-Dist:")
    ]
    unconditional = [line for line in requirements if ";" not in line]
    under_mcp_extra = [line for line in requirements if 'extra == "mcp"' in line.replace("'", '"')]

    assert any(line.startswith("pydantic") for line in unconditional)
    assert not any(line.startswith("mcp") for line in unconditional)
    assert [line for line in requirements if line.startswith("mcp")] == under_mcp_extra
    assert "Provides-Extra: mcp" in metadata
    assert "constructicon-mcp = constructicon.api.mcp.__main__:main" in entry_points


def test_missing_mcp_extra_exits_with_repair_and_without_chaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A base install names its repair and never surfaces an import traceback."""

    real_import = builtins.__import__

    def importing(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "mcp.server.auth.settings":
            raise ModuleNotFoundError("No module named 'mcp'", name="mcp")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importing)
    with pytest.raises(SystemExit) as caught:
        main()
    assert "install constructicon[mcp]" in str(caught.value)
    # ``raise ... from None``: nothing chains, so no traceback reaches the user.
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
