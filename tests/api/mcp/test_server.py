"""M6 MCP is a typed adapter over the durable ControlPlane."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp import Client
from mcp.types import TextResourceContents
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


async def test_mcp_lists_typed_tools_without_caller_auth_arguments(system, journal) -> None:
    actor = AuthenticatedActor(
        actor_id="static:test-agent",
        auth_method="static",
        scopes=frozenset({READ_SCOPE, OPERATE_SCOPE}),
    )
    control = ControlPlane(system=system, store=journal)
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
            "channels_inbox",
            "channels_message",
            "channels_reply",
            "channels_ack",
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


async def test_retried_mcp_start_returns_one_run_and_stored_response(world, journal) -> None:
    system = world
    actor = AuthenticatedActor(
        actor_id="static:mcp-operator",
        auth_method="static",
        scopes=frozenset({READ_SCOPE, OPERATE_SCOPE}),
    )
    control = ControlPlane(system=system, store=journal)
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

        command = _structured(
            await client.call_tool(
                "commands_status", {"command_id": first["command"]["command_id"]}
            )
        )
        assert command["command_id"] == first["command"]["command_id"]
        assert command["state"] == "committed"
        assert command["actor_id"] == actor.actor_id
        assert command["detail"]["digest"].startswith("sha256:")
        assert "record" not in command
        assert "request" not in command
        assert "response" not in command

        for _ in range(100):
            status = _structured(
                await client.call_tool("runs_status", {"run_id": first["run_id"]})
            )
            if status["status"] != "pending" and status["liveness"] != "live":
                break
            if status["status"] in {"succeeded", "failed", "cancelled", "parked"}:
                break
            await asyncio.sleep(0.01)

        manifest_chunk = _structured(
            await client.call_tool(
                "details_read",
                {"reference": status["manifest_ref"], "max_bytes": 64_000},
            )
        )
        assert manifest_chunk["uri"] == status["manifest_ref"]["uri"]
        assert manifest_chunk["digest"] == status["manifest_ref"]["digest"]

        resource = await client.read_resource(
            f"constructicon://runs/{first['run_id']}/manifest"
        )
        assert len(resource.contents) == 1
        assert isinstance(resource.contents[0], TextResourceContents)
        assert "manifest_hash" in resource.contents[0].text

    assert len(journal.run_records(limit=100)) == 1


async def test_graph_schema_errors_remain_constructicon_repair_data(system, journal) -> None:
    actor = AuthenticatedActor(
        actor_id="static:mcp-reader",
        auth_method="static",
        scopes=frozenset({READ_SCOPE}),
    )
    server = create_mcp_server(
        ControlPlane(system=system, store=journal),
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
