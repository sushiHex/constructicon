"""Accounting is published through the normal typed MCP vocabulary."""

from __future__ import annotations

import json

from mcp import Client
from mcp.types import TextResourceContents
from tests.api.mcp.test_server import _structured
from tests.api.test_capability_accounting_result import READER
from tests.run_worlds import create_test_run, start_test_run
from tests.substrate.journal.test_capability_accounting_snapshot import acquire

from constructicon.api.control import ControlPlane
from constructicon.api.mcp import StaticActorSource, create_mcp_server
from constructicon.core.address import RunId


async def test_mcp_result_v2_and_cut_accounting_resource(world, journal):
    run = RunId("run-mcp-accounting")
    create_test_run(journal, run)
    worker = start_test_run(journal, run, owner_id="mcp-accounting-worker")
    lease = acquire(journal, worker, 0)
    server = create_mcp_server(
        ControlPlane(system=world, store=journal),
        StaticActorSource(READER),
    )
    async with Client(server, raise_exceptions=True) as client:
        result = _structured(await client.call_tool("runs_result", {"run_id": str(run)}))
        assert result["result_schema_version"] == 2
        assert result["failures_partial"] is False
        accounting = result["capability_accounting"]
        assert accounting["active_count"] == 1
        assert accounting["through_event_seq"] == 2
        resource = await client.read_resource(accounting["detail"]["uri"])
        assert len(resource.contents) == 1
        assert isinstance(resource.contents[0], TextResourceContents)
        chunk = json.loads(resource.contents[0].text)
        assert chunk["digest"] == accounting["detail"]["digest"]
        assert json.loads(chunk["text"])["items"][0]["lease_id"] == lease.lease_id
