"""M5 task decorators lower Python signatures into durable component contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.component import PythonRef
from constructicon.core.graph import Graph, GraphNode
from constructicon.core.identity import digest
from constructicon.sdk import DefinitionBundle, port_type, task
from tests.sdk.fixture_tasks import EchoInput, echo


class Item(BaseModel):
    value: int


class Result(BaseModel):
    total: int


@task("sdk/source", output="item")
def source() -> Annotated[Item, port_type("sdk/Item")]:
    return Item(value=1)


@task("sdk/sink")
def sink(item: Annotated[Item, port_type("sdk/Item")]) -> None:
    assert item.value >= 0


@task("sdk/collect", output="result")
async def collect(
    items: list[Annotated[Item, port_type("sdk/Item")]],
    optional: Annotated[Item | None, port_type("sdk/Item")],
) -> Annotated[Result, port_type("sdk/Result")]:
    return Result(
        total=sum(item.value for item in items)
        + (optional.value if optional else 0)
    )


def test_task_contracts_are_canonical_and_complete() -> None:
    assert isinstance(source, DefinitionBundle)
    assert source.definition.inputs == ()
    assert source.definition.outputs[0].name == "item"
    assert sink.definition.outputs == ()
    assert collect.definition.inputs[0].cardinality == "many"
    assert collect.definition.inputs[1].cardinality == "optional"
    assert collect.definition.capability_requirements == ()
    for port in (*collect.definition.inputs, *collect.definition.outputs):
        assert port.json_schema is not None
        assert port.schema_hash == str(digest("json-schema", 1, port.json_schema))


async def test_registered_task_executes_through_the_ordinary_walker(
    system: Constructicon,
) -> None:
    version = system.register(echo)
    system.promote_initial(component=echo.name, version=version)
    definition = echo.definition
    graph = Graph(
        name="sdk-echo-run",
        nodes=(GraphNode(id="echo", body=echo.ref()),),
        inputs=definition.inputs,
        outputs=definition.outputs,
    )
    result = await system.start(
        graph,
        {"value": EchoInput(text="hello").model_dump(mode="json")},
        run_id=RunId("sdk-echo"),
    )
    assert result.outputs == {"echo": {"text": "hello"}}


def test_decorated_adapter_reloads_in_a_fresh_process() -> None:
    body = echo.definition.body
    assert isinstance(body, PythonRef)
    expected = str(body.source_digest)
    code = """
import json
import importlib
from tests.sdk.fixture_tasks import echo
from constructicon.runtime.registry import source_digest_for
body = echo.definition.body
module = importlib.import_module(body.module)
target = getattr(module, body.qualname)
print(json.dumps({"callable": callable(target), "digest": str(source_digest_for(target))}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=True,
    )
    observed = json.loads(completed.stdout)
    assert observed == {"callable": True, "digest": expected}
