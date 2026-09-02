"""L3 — authoring sugar compiling immediately to the canonical Graph IR.

No SDK object reaches admission or execution. ``@task`` produces a canonical
atomic ``ComponentDef`` plus its process-local implementation; combinators
produce only ``Ref``, ``Graph``, and ``Loop`` values wrapped for registration.
"""

from constructicon.sdk.combinators import component, flow, harness, loop, panel
from constructicon.sdk.task import TASK_ADAPTER_REVISION, task
from constructicon.sdk.types import DefinitionBundle, PortType, port_type

__all__ = [
    "TASK_ADAPTER_REVISION",
    "DefinitionBundle",
    "PortType",
    "component",
    "flow",
    "harness",
    "loop",
    "panel",
    "port_type",
    "task",
]
