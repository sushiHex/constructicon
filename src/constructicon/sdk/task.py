"""``@task``: Python signatures lowered into canonical atomic components.

The decorator creates an importable async ``NodeImpl`` adapter and returns a
``DefinitionBundle``. Every port contract is explicit and schema-hashed; the
runtime still sees only the ordinary ``ComponentDef``/``PythonRef`` contract.
"""

from __future__ import annotations

import functools
import inspect
import sys
import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, TypeVar, Union, get_args, get_origin, get_type_hints

from pydantic import TypeAdapter, ValidationError

from constructicon.core.component import CapabilityRequirement, ComponentDef, PythonRef
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest, json_value
from constructicon.core.ports import Port
from constructicon.runtime.context import NodeContext, NodeImpl
from constructicon.runtime.registry import source_digest_for
from constructicon.sdk.types import DefinitionBundle, PortType

TASK_ADAPTER_REVISION = "constructicon.sdk.task:v1"
F = TypeVar("F", bound=Callable[..., object])


@dataclass(frozen=True)
class _PortContract:
    port: Port
    runtime_adapter: TypeAdapter[Any]


def task(
    name: str,
    *,
    output: str = "result",
    outputs: Mapping[str, Any] | None = None,
    capabilities: tuple[CapabilityRequirement, ...] = (),
) -> Callable[[F], DefinitionBundle]:
    """Declare one reloadable atomic component from a typed Python function."""

    _require_component_name(name)
    _validate_requirements(capabilities)

    def decorate(function: F) -> DefinitionBundle:
        if "<locals>" in function.__qualname__ or function.__name__ == "<lambda>":
            raise TypeError(
                f"@task {name!r} requires a module-level named function; "
                "local functions and lambdas cannot be reloaded"
            )
        try:
            source = inspect.getsource(function)
        except (OSError, TypeError) as exc:
            raise TypeError(
                f"@task {name!r} cannot inspect the function source; persistent "
                "atomic components require observable source identity"
            ) from exc
        if not source.strip():
            raise TypeError(f"@task {name!r} has no observable source")
        try:
            hints = get_type_hints(function, include_extras=True)
        except Exception as exc:
            raise TypeError(f"@task {name!r} could not resolve annotations: {exc}") from exc

        signature = inspect.signature(function)
        input_contracts: dict[str, _PortContract] = {}
        inject_context = False
        for parameter in signature.parameters.values():
            if parameter.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                raise TypeError(
                    f"@task {name!r} parameter {parameter.name!r} uses unsupported "
                    f"kind {parameter.kind.description}; use ordinary or keyword-only "
                    "typed parameters"
                )
            annotation = hints.get(parameter.name, parameter.annotation)
            if parameter.name == "ctx":
                if annotation is not NodeContext:
                    raise TypeError(
                        f"@task {name!r} reserves parameter 'ctx' for NodeContext; "
                        "annotate it exactly as NodeContext or rename the data input"
                    )
                if parameter.default is not inspect.Parameter.empty:
                    raise TypeError("the reserved NodeContext parameter cannot have a default")
                inject_context = True
                continue
            if parameter.default is not inspect.Parameter.empty:
                raise TypeError(
                    f"@task {name!r} input {parameter.name!r} has a Python default; "
                    "defaults are not part of the Graph contract—use an explicit "
                    "optional input instead"
                )
            if annotation is inspect.Parameter.empty:
                raise TypeError(
                    f"@task {name!r} input {parameter.name!r} needs a type annotation"
                )
            input_contracts[parameter.name] = _input_contract(parameter.name, annotation)

        return_annotation = hints.get("return", signature.return_annotation)
        if return_annotation is inspect.Signature.empty:
            raise TypeError(f"@task {name!r} needs an explicit return annotation")
        output_contracts = _output_contracts(
            name,
            return_annotation,
            output=output,
            outputs=outputs,
        )
        input_ports = tuple(contract.port for contract in input_contracts.values())
        output_ports = tuple(contract.port for contract in output_contracts.values())

        @functools.wraps(function)
        async def adapter(
            ctx: NodeContext,
            values: Mapping[str, Any],
        ) -> Mapping[str, Any]:
            expected = set(input_contracts)
            extra = sorted(set(values) - expected)
            missing = sorted(expected - set(values))
            if extra or missing:
                raise ContractViolation(
                    f"task {name!r} received input keys missing={missing}, extra={extra}; "
                    "the admitted port contract and invocation disagreed"
                )
            kwargs: dict[str, Any] = {}
            for input_name, contract in input_contracts.items():
                try:
                    kwargs[input_name] = contract.runtime_adapter.validate_python(
                        values[input_name]
                    )
                except ValidationError as exc:
                    raise ContractViolation(
                        f"task {name!r} input {input_name!r} failed its annotation: {exc}"
                    ) from exc
            if inject_context:
                kwargs["ctx"] = ctx
            result = function(**kwargs)
            if inspect.isawaitable(result):
                result = await result
            return _validate_outputs(name, result, output_contracts)

        adapter_name = _adapter_name(name, function)
        adapter.__name__ = adapter_name
        adapter.__qualname__ = adapter_name
        adapter.__module__ = function.__module__
        setattr(adapter, "__constructicon_adapter_revision__", TASK_ADAPTER_REVISION)
        module = sys.modules.get(function.__module__)
        if module is None:
            raise TypeError(
                f"@task {name!r} module {function.__module__!r} is not loaded; "
                "the adapter cannot be installed for restart-safe import"
            )
        setattr(module, adapter_name, adapter)

        contract_hash = digest(
            "component-contract",
            1,
            {
                "inputs": [port.model_dump(mode="json") for port in input_ports],
                "outputs": [port.model_dump(mode="json") for port in output_ports],
            },
        )
        source_digest = source_digest_for(adapter)
        if source_digest is None:
            raise TypeError(
                f"@task {name!r} could not derive a persistent implementation digest"
            )
        definition = ComponentDef(
            name=name,
            role="node",
            body=PythonRef(
                package=function.__module__.split(".", 1)[0],
                module=function.__module__,
                qualname=adapter_name,
                contract_hash=contract_hash,
                source_digest=source_digest,
            ),
            inputs=input_ports,
            outputs=output_ports,
            capability_requirements=tuple(capabilities),
        )
        implementation: NodeImpl = adapter
        return DefinitionBundle(definition=definition, implementation=implementation)

    return decorate


def _require_component_name(name: str) -> None:
    if not name or "/" not in name:
        raise ValueError(
            "@task requires an explicit namespaced component name such as "
            "'example/triage'"
        )


def _validate_requirements(requirements: tuple[CapabilityRequirement, ...]) -> None:
    aliases = [requirement.alias for requirement in requirements]
    duplicates = sorted({alias for alias in aliases if aliases.count(alias) > 1})
    if duplicates:
        raise ValueError(f"duplicate capability requirement aliases: {duplicates}")
    for requirement in requirements:
        if not requirement.alias or not requirement.kind:
            raise ValueError("capability requirement alias and kind must be non-empty")


def _adapter_name(name: str, function: Callable[..., object]) -> str:
    identity = digest(
        "sdk-task-adapter",
        1,
        {
            "component": name,
            "module": function.__module__,
            "qualname": function.__qualname__,
        },
    )
    return "__constructicon_task_" + str(identity).removeprefix("sha256:")[:20]


def _input_contract(name: str, annotation: Any) -> _PortContract:
    runtime_adapter = _type_adapter(annotation, where=f"input {name!r}")
    base, explicit_type = _unwrap_annotated(annotation)
    optional_inner = _optional_inner(base)
    if optional_inner is not None:
        contract_annotation, inner_type = _unwrap_annotated(optional_inner)
        explicit_type = _merge_explicit_types(explicit_type, inner_type)
        cardinality = "optional"
    else:
        origin = get_origin(base)
        if origin is list:
            args = get_args(base)
            if len(args) != 1:
                raise TypeError(f"input {name!r} list annotation must have one item type")
            contract_annotation, inner_type = _unwrap_annotated(args[0])
            explicit_type = _merge_explicit_types(explicit_type, inner_type)
            cardinality = "many"
        else:
            contract_annotation = base
            cardinality = "one"
    _reject_any(contract_annotation, where=f"input {name!r}")
    schema = _type_adapter(contract_annotation, where=f"input {name!r}").json_schema()
    return _PortContract(
        port=Port(
            name=name,
            type_id=explicit_type or _derive_type_id(contract_annotation),
            schema_hash=str(digest("json-schema", 1, schema)),
            json_schema=schema,
            cardinality=cardinality,
        ),
        runtime_adapter=runtime_adapter,
    )


def _output_contracts(
    component_name: str,
    annotation: Any,
    *,
    output: str,
    outputs: Mapping[str, Any] | None,
) -> dict[str, _PortContract]:
    if outputs is not None:
        if not outputs:
            raise TypeError("explicit outputs must contain at least one named output")
        return {
            name: _output_contract(name, item_annotation)
            for name, item_annotation in outputs.items()
        }
    if annotation in (None, type(None)):
        return {}
    if not output:
        raise TypeError(f"@task {component_name!r} output name must be non-empty")
    return {output: _output_contract(output, annotation)}


def _output_contract(name: str, annotation: Any) -> _PortContract:
    _reject_any(annotation, where=f"output {name!r}")
    base, explicit_type = _unwrap_annotated(annotation)
    identity_annotation = _optional_inner(base) or base
    schema = _type_adapter(base, where=f"output {name!r}").json_schema()
    return _PortContract(
        port=Port(
            name=name,
            type_id=explicit_type or _derive_type_id(identity_annotation),
            schema_hash=str(digest("json-schema", 1, schema)),
            json_schema=schema,
            cardinality="one",
        ),
        runtime_adapter=_type_adapter(base, where=f"output {name!r}"),
    )


def _validate_outputs(
    component_name: str,
    result: object,
    contracts: Mapping[str, _PortContract],
) -> Mapping[str, Any]:
    if not contracts:
        if result is not None:
            raise ContractViolation(
                f"sink task {component_name!r} returned {type(result).__name__}; "
                "a -> None task must return None"
            )
        return {}
    if len(contracts) == 1:
        name, contract = next(iter(contracts.items()))
        try:
            value = contract.runtime_adapter.validate_python(result)
        except ValidationError as exc:
            raise ContractViolation(
                f"task {component_name!r} output {name!r} failed its annotation: {exc}"
            ) from exc
        return {name: json_value(value)}
    if not isinstance(result, Mapping):
        raise ContractViolation(
            f"multi-output task {component_name!r} must return a mapping, received "
            f"{type(result).__name__}"
        )
    expected = set(contracts)
    missing = sorted(expected - set(result))
    extra = sorted(set(result) - expected)
    if missing or extra:
        raise ContractViolation(
            f"multi-output task {component_name!r} returned keys missing={missing}, "
            f"extra={extra}"
        )
    normalized: dict[str, Any] = {}
    for name, contract in contracts.items():
        try:
            normalized[name] = json_value(
                contract.runtime_adapter.validate_python(result[name])
            )
        except ValidationError as exc:
            raise ContractViolation(
                f"task {component_name!r} output {name!r} failed its annotation: {exc}"
            ) from exc
    return normalized


def _unwrap_annotated(annotation: Any) -> tuple[Any, str | None]:
    if get_origin(annotation) is not Annotated:
        return annotation, None
    args = get_args(annotation)
    base = args[0]
    markers = [item.type_id for item in args[1:] if isinstance(item, PortType)]
    if len(set(markers)) > 1:
        raise TypeError(f"annotation carries conflicting port_type metadata: {markers}")
    return base, markers[0] if markers else None


def _merge_explicit_types(left: str | None, right: str | None) -> str | None:
    if left is not None and right is not None and left != right:
        raise TypeError(f"annotation carries conflicting port type ids {left!r} and {right!r}")
    return left or right


def _optional_inner(annotation: Any) -> Any | None:
    origin = get_origin(annotation)
    if origin not in (Union, types.UnionType):
        return None
    args = get_args(annotation)
    non_none = tuple(item for item in args if item is not type(None))
    if len(args) == 2 and len(non_none) == 1:
        return non_none[0]
    raise TypeError(
        "only T | None unions are supported in task signatures; use an explicit "
        "Pydantic model for richer unions"
    )


def _reject_any(annotation: Any, *, where: str) -> None:
    if annotation is Any:
        raise TypeError(f"{where} may not use Any; declare a concrete public contract")


def _type_adapter(annotation: Any, *, where: str) -> TypeAdapter[Any]:
    _reject_any(annotation, where=where)
    try:
        return TypeAdapter(annotation)
    except Exception as exc:
        raise TypeError(f"{where} annotation {annotation!r} is unsupported: {exc}") from exc


def _derive_type_id(annotation: Any) -> str:
    base, explicit = _unwrap_annotated(annotation)
    if explicit is not None:
        return explicit
    if inspect.isclass(base):
        return f"python/{base.__module__}:{base.__qualname__}"
    origin = get_origin(base)
    if origin is list:
        args = get_args(base)
        if len(args) == 1:
            return f"python/typing:list[{_derive_type_id(args[0])}]"
    raise TypeError(
        f"cannot derive a stable nominal type id for {base!r}; annotate it with "
        "Annotated[T, port_type('namespace/Type')]"
    )
