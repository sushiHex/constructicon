"""M6 MCP is a typed adapter over the durable ControlPlane."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp import Client
from tests.conftest import pipeline_graph

from constructicon.api.control import ControlPlane
from constructicon.api.mcp import StaticActorSource, create_mcp_server
from constructicon.core.control import (
    OPERATE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
)


def _structured(result: Any) -> dict[str, Any]:
    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    payload = result.structured_content
    wrapped = payload.get("result")
    if len(payload) == 1 and isinstance(wrapped, dict):
        return wrapped
    return payload


async def test_mcp_lists_typed_tools_without_caller_auth_arguments(system) -> None:
    actor = AuthenticatedActor(
        actor_id="static:test-agent",
        auth_method="static",
        scopes=frozenset({READ_SCOPE, OPERATE_SCOPE}),
    )
    control = ControlPlane(system=system, store=system.journal)
    server = create_mcp_server(control, StaticActorSource(actor))

    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        by_name = {tool.name: tool for tool in listed.tools}
        assert {
            "whoami",
            "system_describe",
            "graphs_validate",
            "runs_start",
            "runs_status",
            "runs_events",
            "runs_cancel",
            "runs_resume",
            "runs_reproduce",
            "runs_counterfactual",
            "runs_approve",
            "registry_promote",
            "registry_rollback",
            "details_read",
        } <= set(by_name)
        for tool in by_name.values():
            properties = tool.input_schema.get("properties", {})
            assert "actor" not in properties
            assert "actor_id" not in properties

        identity = _structured(await client.call_tool("whoami", {}))
        assert identity["actor_id"] == "static:test-agent"
        described = _structured(await client.call_tool("system_describe", {}))
        assert described["schema_version"] == 1


async def test_retried_mcp_start_returns_one_run_and_stored_response(world) -> None:
    system = world
    actor = AuthenticatedActor(
        actor_id="static:mcp-operator",
        auth_method="static",
        scopes=frozenset({READ_SCOPE, OPERATE_SCOPE}),
    )
    control = ControlPlane(system=system, store=system.journal)
    server = create_mcp_server(control, StaticActorSource(actor))
    graph = pipeline_graph()
    arguments = {
        "proposal": graph.model_dump(mode="json"),
        "inputs": {"issue": {"title": "mcp"}},
        "idempotency_key": "mcp-start-1",
    }

    async with Client(server, raise_exceptions=True) as client:
        first = _structured(await client.call_tool("runs_start", arguments))
        second = _structured(await client.call_tool("runs_start", arguments))
        assert first["run_id"] == second["run_id"]
        assert first["command"]["replayed"] is False
        assert second["command"]["replayed"] is True

        for _ in range(100):
            status = _structured(
                await client.call_tool("runs_status", {"run_id": first["run_id"]})
            )
            if status["status"] != "pending" and status["liveness"] != "live":
                break
            if status["status"] in {"succeeded", "failed", "cancelled", "parked"}:
                break
            await asyncio.sleep(0.01)

    assert len(system.journal.run_records(limit=100)) == 1


async def test_graph_schema_errors_remain_constructicon_repair_data(system) -> None:
    actor = AuthenticatedActor(
        actor_id="static:mcp-reader",
        auth_method="static",
        scopes=frozenset({READ_SCOPE}),
    )
    server = create_mcp_server(
        ControlPlane(system=system, store=system.journal),
        StaticActorSource(actor),
    )
    async with Client(server, raise_exceptions=True) as client:
        result = _structured(
            await client.call_tool(
                "graphs_validate",
                {
                    "proposal": {
                        "schema_version": 1,
                        "name": "bad",
                        "nodes": [],
                        "invented": True,
                    },
                    "inputs": {},
                },
            )
        )
        assert result["status"] == "rejected"
        assert result["faults"][0]["code"] == "graph.schema.invalid_value"
