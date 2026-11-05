"""Construct the existing core atomic definition for installed trial functions."""

from constructicon.core.component import ComponentDef, PythonRef
from constructicon.core.identity import digest
from constructicon.core.ports import Port
from constructicon.runtime.context import NodeImpl
from constructicon.runtime.registry import source_digest_for


def atomic(
    name: str, inputs: tuple[Port, ...], outputs: tuple[Port, ...], impl: NodeImpl,
) -> tuple[ComponentDef, NodeImpl]:
    return ComponentDef(
        name=name, role="node", inputs=inputs, outputs=outputs,
        body=PythonRef(
            package="constructicon", module=impl.__module__, qualname=impl.__qualname__,
            contract_hash=digest("component-contract", 1, {
                "inputs": [port.model_dump(mode="json") for port in inputs],
                "outputs": [port.model_dump(mode="json") for port in outputs],
            }), source_digest=source_digest_for(impl),
        ),
    ), impl
