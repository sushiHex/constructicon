"""MCP disposal derives its administrator once and exposes only public receipts."""

from __future__ import annotations

import json

from mcp import Client
from mcp.types import TextResourceContents
from tests.api.mcp.test_server import _structured
from tests.api.test_capability_disposal import ADMIN, OPERATOR, disposal_world

from constructicon.api.mcp import create_mcp_server
from constructicon.core.control import ControlCode


async def test_mcp_disposal_single_actor_and_delegate_with_public_receipt(tmp_path, monkeypatch):
    async with disposal_world(tmp_path) as world:
        derivations = []
        delegations = []

        class ActorSource:
            async def actor(self):
                derivations.append(ADMIN)
                return ADMIN

        original = world.control.runs_dispose_capabilities

        async def delegated(actor, **kwargs):
            delegations.append((actor, kwargs))
            return await original(actor, **kwargs)

        monkeypatch.setattr(world.control, "runs_dispose_capabilities", delegated)
        server = create_mcp_server(world.control, ActorSource())
        async with Client(server, raise_exceptions=True) as client:
            by_name = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert "runs_dispose_capabilities" in by_name
            properties = by_name["runs_dispose_capabilities"].input_schema.get("properties", {})
            assert not {"actor", "actor_id", "user", "authority"}.intersection(properties)
            arguments = {
                "run_id": str(world.run_id),
                "pairs": [pair.model_dump(mode="json") for pair in world.pairs],
                "reason": "private MCP administrative reason", "idempotency_key": "mcp-dispose",
            }
            result = _structured(await client.call_tool("runs_dispose_capabilities", arguments))
            assert derivations == [ADMIN]
            assert len(delegations) == 1 and delegations[0][0] is ADMIN
            assert result["status"] == "disposed" and result["count"] == 2
            assert result["physical_cleanup"] == "unverified"
            resource = await client.read_resource(result["receipt"]["uri"])
            assert len(resource.contents) == 1
            assert isinstance(resource.contents[0], TextResourceContents)
            chunk = json.loads(resource.contents[0].text)
            assert chunk["digest"] == result["receipt"]["digest"]
            public = json.loads(chunk["text"])
            assert public["command_id"] == result["command"]["command_id"]
            assert public["pairs"] == arguments["pairs"]
            assert arguments["reason"] not in json.dumps(public)
            assert "request_hash" not in public and "plan_hash" not in public
            assert len(delegations) == 1
            assert derivations == [ADMIN, ADMIN]


async def test_mcp_operator_disposal_refuses_before_lifecycle_or_claim(tmp_path, monkeypatch):
    async with disposal_world(tmp_path) as world:
        derivations = []
        touched = []

        class ActorSource:
            async def actor(self):
                derivations.append(OPERATOR)
                return OPERATOR

        server = create_mcp_server(world.control, ActorSource())
        async with Client(server, raise_exceptions=True) as client:
            listed = await client.list_tools()
            assert "runs_dispose_capabilities" in {tool.name for tool in listed.tools}

            async def admission():
                touched.append("admission")
                raise AssertionError("unauthorized MCP disposal started lifecycle admission")

            def claim(**kwargs):
                touched.append("claim")
                raise AssertionError("unauthorized MCP disposal claimed a command")

            monkeypatch.setattr(world.control, "_admit_mutation", admission)
            monkeypatch.setattr(world.journal, "claim_command", claim)
            result = _structured(await client.call_tool("runs_dispose_capabilities", {
                "run_id": str(world.run_id),
                "pairs": [pair.model_dump(mode="json") for pair in world.pairs],
                "reason": "not authorized", "idempotency_key": "mcp-denied",
            }))
            assert result["faults"][0]["code"] == ControlCode.AUTH_REQUIRED_SCOPE.value
            assert derivations == [OPERATOR]
            assert touched == []
