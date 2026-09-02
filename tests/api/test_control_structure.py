"""Executable ownership boundaries for the compressed L4 control plane."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
API = ROOT / "src" / "constructicon" / "api"

MUTATIONS = {
    "runs_start",
    "runs_cancel",
    "runs_resume",
    "runs_reproduce",
    "runs_counterfactual",
    "runs_approve",
    "channels_reply",
    "channels_ack",
    "registry_register",
    "registry_promote_initial",
    "registry_promote",
    "registry_rollback",
}


def _class(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def test_public_facade_mutations_delegate_once_to_the_command_executor() -> None:
    facade = _class(API / "control.py", "ControlPlane")
    methods = {
        node.name: node
        for node in facade.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for name in MUTATIONS:
        method = methods[name]
        assert isinstance(method, ast.AsyncFunctionDef)
        assert len(method.body) == 1
        statement = method.body[0]
        assert isinstance(statement, ast.Return)
        assert isinstance(statement.value, ast.Await)
        call = statement.value.value
        assert isinstance(call, ast.Call)
        assert isinstance(call.func, ast.Attribute) and call.func.attr == name
        owner = call.func.value
        assert isinstance(owner, ast.Attribute) and owner.attr == "_commands"


def test_command_and_query_storage_responsibilities_are_disjoint() -> None:
    command_source = (API / "_control_commands.py").read_text(encoding="utf-8")
    query_source = (API / "_control_queries.py").read_text(encoding="utf-8")
    for operation in (
        "claim_command(",
        "store_command_plan(",
        "complete_command(",
        "reject_command(",
    ):
        assert operation in command_source
        assert operation not in query_source
    assert "def _decode_cursor(" in query_source
    assert "def _decode_cursor(" not in command_source
    assert "system.journal" not in command_source + query_source
    assert "system.registry" not in command_source + query_source


def test_transports_cannot_reach_local_assembly_or_private_services() -> None:
    mcp_source = (API / "mcp" / "server.py").read_text(encoding="utf-8")
    for forbidden in (
        "registry_register",
        "registry_promote_initial",
        "SqliteJournal",
        "RunHost",
        "CursorCodec",
        "DetailResolver",
        "._prepare_run",
        "._run_prepared",
        "._request_cancel",
        "._promote_version",
    ):
        assert forbidden not in mcp_source


def test_only_command_executor_and_run_host_call_private_domain_mutators() -> None:
    allowed = {"_control_commands.py", "run_host.py", "system.py"}
    private_calls = {
        "_prepare_run",
        "_run_prepared",
        "_request_cancel",
        "_promote_version",
    }
    violations: list[str] = []
    for path in API.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in private_calls
                and path.name not in allowed
            ):
                violations.append(f"{path.relative_to(API)}:{node.lineno}:{node.func.attr}")
    assert violations == []
