"""The import contracts that name api modules cover every api module (I8).

import-linter has no "every child except" form, so two contracts enumerate
children of ``constructicon.api`` by hand. These tests derive the children from
the package directory, so a new entry there fails here until a contract names it.

What they do not cover: imports written in ``constructicon/api/__init__.py``
itself (it is the package, not a child, and naming the package as a source would
include the adapter), and anything import-linter's own semantics decide, such as
how a listed package covers its descendants. ``lint-imports`` in ``uv run verify``
is the enforcement; this file only keeps its lists complete.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "src" / "constructicon" / "api"

CONTROL_SURFACE = frozenset({
    "_control_commands", "_control_queries", "_metered_native", "control", "cursor",
    "detail", "introspection", "run_host", "system",
})
"""What the MCP adapter may reach: the typed control plane, the assembled system
and the modules those two import. A module is added here only when the control
plane itself comes to depend on it; everything else is a fixed-task entry."""

WEAKENING_OPTIONS = ("allow_indirect_imports", "ignore_imports", "as_packages")


def api_children() -> frozenset[str]:
    """Every entry of the ``constructicon.api`` directory except the MCP adapter.

    Any file by its stem and any directory by its name, whether or not it holds
    an ``__init__.py``: a namespace package, an extension module or a data file
    is a child here, so nothing importable can appear without being named.
    """
    children = {
        path.name if path.is_dir() else path.name.split(".", 1)[0]
        for path in API.iterdir()
        if path.name not in ("__init__.py", "__pycache__")
    }
    assert "mcp" in children and "system" in children and "_m9" in children
    return frozenset(children - {"mcp"})


def contract(name: str) -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        contracts = tomllib.load(stream)["tool"]["importlinter"]["contracts"]
    found, = (entry for entry in contracts if entry["name"] == name)
    # A forbidden contract with its defaults: descendants and indirect imports count.
    assert found["type"] == "forbidden"
    assert not [option for option in WEAKENING_OPTIONS if option in found]
    return found


def named_api_children(modules: object) -> list[str]:
    assert isinstance(modules, list)
    prefix = "constructicon.api."
    named = [module[len(prefix):] for module in modules if module.startswith(prefix)]
    # Direct children only, each once: a deeper name would hide its siblings.
    assert all("." not in name and "*" not in name for name in named)
    assert len(named) == len(set(named))
    return named


def test_every_api_child_but_the_adapter_is_forbidden_from_importing_mcp():
    found = contract("Only the MCP adapter imports mcp")
    assert set(named_api_children(found["source_modules"])) == api_children()
    assert found["forbidden_modules"] == ["mcp"]


def test_the_adapter_is_forbidden_every_api_child_outside_the_control_surface():
    found = contract("The MCP adapter never reaches the qualification entry")
    assert found["source_modules"] == ["constructicon.api.mcp"]
    named = named_api_children(found["forbidden_modules"])
    assert len(named) == len(found["forbidden_modules"])
    assert api_children() > CONTROL_SURFACE
    assert set(named) == api_children() - CONTROL_SURFACE
