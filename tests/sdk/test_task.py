"""M5 task decorators lower Python signatures into durable component contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any

import pytest
from pydantic import BaseModel

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.component import PythonRef
from constructicon.core.graph import Graph, GraphNode
from constructicon.core.identity import digest
from constructicon.sdk import DefinitionBundle, port_type, task
from constructicon.substrate.journal.sqlite import SqliteJournal
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


@task("sdk/list-output", output="items")
def list_output() -> list[Item]:
    return [Item(value=1)]


def defaulted(item: Item = Item(value=0)) -> Result:
    return Result(total=item.value)


def any_input(item: Any) -> Result:
    return Result(total=int(item))


def optional_many(items: list[Item] | None) -> Result:
    return Result(total=sum(item.value for item in items or []))


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


def test_list_output_is_one_list_payload_not_fanout() -> None:
    port = list_output.definition.outputs[0]
    assert port.cardinality == "one"
    assert port.json_schema is not None
    assert port.json_schema["type"] == "array"


@pytest.mark.parametrize(
    ("component_name", "function", "message"),
    [
        ("sdk/defaulted", defaulted, "Python default"),
        ("sdk/any", any_input, "may not use Any"),
        ("sdk/optional-many", optional_many, "list[T] | None"),
    ],
)
def test_unsupported_signature_semantics_are_rejected(
    component_name: str,
    function: Any,
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message.replace("[", r"\[").replace("]", r"\]")):
        task(component_name)(function)


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


def test_persisted_task_activates_and_runs_in_a_fresh_process(tmp_path: Path) -> None:
    database = tmp_path / "reload.db"
    journal = SqliteJournal(database)
    system = Constructicon(journal=journal)
    version = system.register(echo)
    system.promote_initial(component=echo.name, version=version)
    graph = Graph(
        name="fresh-process-echo",
        nodes=(GraphNode(id="echo", body=echo.ref()),),
        inputs=echo.definition.inputs,
        outputs=echo.definition.outputs,
    )
    code = f"""
import asyncio
import json
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.graph import Graph
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.sdk.fixture_tasks import echo
journal = SqliteJournal({str(database)!r})
system = Constructicon(journal=journal)
graph = Graph.model_validate_json({graph.model_dump_json()!r})
result = asyncio.run(system.start(
    graph,
    {{"value": {{"text": "fresh"}}}},
    run_id=RunId("fresh-process-task"),
))
print(json.dumps({{"status": result.status.value, "outputs": result.outputs}}, sort_keys=True))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=True,
    )
    observed = json.loads(completed.stdout)
    assert observed == {
        "outputs": {"echo": {"text": "fresh"}},
        "status": "succeeded",
    }
