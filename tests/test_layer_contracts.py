"""The import contracts that name api modules cover every api module (I8).

import-linter has no "every child except" form, so two contracts enumerate
children of ``constructicon.api`` by hand. These tests derive the children from
the package directory, so a new module fails here until a contract names it.
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


def api_children() -> frozenset[str]:
    """Every direct child of ``constructicon.api`` except the MCP adapter."""
    children = {
        path.stem if path.is_file() else path.name
        for path in API.iterdir()
        if (path.suffix == ".py" and path.stem != "__init__")
        or (path.is_dir() and (path / "__init__.py").is_file())
    }
    assert "mcp" in children and "system" in children
    return frozenset(children - {"mcp"})


def contract(name: str) -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        contracts = tomllib.load(stream)["tool"]["importlinter"]["contracts"]
    found, = (entry for entry in contracts if entry["name"] == name)
    return found


def named_api_children(modules: object) -> list[str]:
    assert isinstance(modules, list)
    prefix = "constructicon.api."
    return [module[len(prefix):] for module in modules if module.startswith(prefix)]


def test_every_api_module_but_the_adapter_is_forbidden_from_importing_mcp():
    found = contract("Only the MCP adapter imports mcp")
    named = named_api_children(found["source_modules"])
    assert len(named) == len(set(named))
    assert set(named) == api_children()
    assert found["forbidden_modules"] == ["mcp"]


def test_the_adapter_is_forbidden_every_api_module_outside_the_control_surface():
    found = contract("The MCP adapter never reaches the qualification entry")
    assert found["source_modules"] == ["constructicon.api.mcp"]
    named = named_api_children(found["forbidden_modules"])
    assert len(named) == len(found["forbidden_modules"]) == len(set(named))
    assert api_children() > CONTROL_SURFACE
    assert set(named) == api_children() - CONTROL_SURFACE
    # Indirect imports stay forbidden: the contract must not opt out of them.
    assert "allow_indirect_imports" not in found and "ignore_imports" not in found
