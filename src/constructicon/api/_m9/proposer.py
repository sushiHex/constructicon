"""One fixed Codex task selecting a reviewed catalog atom, never diagnostic quality."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from constructicon.api._m9.component import atomic
from constructicon.api._m9.evidence import CASE_POLICY, CHOICE, TRAIN, Exam
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.component import CapabilityRequirement, ComponentDef, PythonRef
from constructicon.core.control import OPERATE_SCOPE, AuthenticatedActor
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorSuccess, TaskSpec
from constructicon.core.grants import GrantRequest
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.journal import Journal
from constructicon.core.manifest import SELF_BINDING, SELF_CAPABILITY, parse_manifest_json
from constructicon.core.ports import Port
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.substrate.executors.codex import CodexOperatorHandle
from constructicon.substrate.executors.codex_host import READ_GRANTS

CAPABILITY = "m9-selector"
COMPONENT = "constructicon.m9/catalog-selector"
PATH = ExecutionPath(scope=ScopePath(segments=("m9-select", "select")))
ACTOR = AuthenticatedActor(
    actor_id="static:m9-trial-selector", auth_method="static",
    scopes=frozenset({OPERATE_SCOPE}),
)
CATALOG = (
    ("baseline", "Classify the observation as network or storage."),
    ("cite-evidence", "Classify the observation as network or storage. "
     "Cite the supplied evidence ID."),
)
OBSERVATION = Port(
    name="observation", type_id="constructicon.m9/SelectionObservation", schema_hash="v1",
)


class SelectorRefused(ValueError):
    """A fixed local refusal, containing no model or filesystem value."""


def source_revision() -> Digest:
    """Raw installed package bytes, independent of its private installation path.

    The reviewed Linux installation verifies these against the selected Git tree.
    This does not normalize line endings or equate a Windows copy with Linux.
    """
    try:
        package = Path(__file__).resolve().parents[2]
        paths: list[Path] = []
        for path in package.rglob("*.py"):
            if len(paths) == 512:
                raise SelectorRefused("M9_SELECTOR_SOURCE_INVENTORY_INVALID")
            paths.append(path)
        material = {}
        spent = 0
        for path in sorted(paths):
            if path.is_symlink():
                raise SelectorRefused("M9_SELECTOR_SOURCE_INVENTORY_INVALID")
            with path.open("rb") as stream:
                raw = stream.read(256 * 1024 + 1)
            spent += len(raw)
            name = path.relative_to(package).as_posix()
            if len(raw) > 256 * 1024 or spent > 8 * 1024 * 1024 or len(name) > 256:
                raise SelectorRefused("M9_SELECTOR_SOURCE_INVENTORY_INVALID")
            material[name] = hashlib.sha256(raw).hexdigest()
        if not {"__init__.py", "core/executor.py", "runtime/walker.py", "api/m9_trial.py"} <= (
            material.keys()
        ):
            raise SelectorRefused("M9_SELECTOR_SOURCE_INVENTORY_INVALID")
        return digest("m9-installed-source", 2, material)
    except OSError:
        raise SelectorRefused("M9_SELECTOR_SOURCE_UNAVAILABLE") from None


SOURCE = source_revision()


def training() -> str:
    return canonical_json(tuple({
        "case": case.model_dump(mode="json"), "expected": expected.model_dump(mode="json"),
    } for case, expected, split in CASE_POLICY if split == "train"))


def task() -> TaskSpec:
    return TaskSpec(instruction=(
        "Choose one instruction from this fixed catalog using only the training example. "
        "Reply with exactly one catalog ID, with no other text. "
        "This selects an instruction; it does not evaluate held-out cases.\n"
        f"Catalog: {canonical_json(CATALOG)}\nTraining: {training()}"
    ))


class Observation(BaseModel):
    """Bounded observed facts; absent provider telemetry stays absent."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    choice: Literal["baseline", "cite-evidence"]
    source: Digest
    task: Digest
    provider_revision: Digest
    requested_model: str = Field(min_length=1, max_length=128)
    served_model: str | None = Field(default=None, max_length=128)
    input_tokens: int | None = Field(default=None, ge=0, le=1_000_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=1_000_000_000)
    reply_bytes: int = Field(ge=1, le=64)
    elapsed_s: float = Field(ge=0, le=3600, allow_inf_nan=False)


def parse_choice(answer: object) -> Literal["baseline", "cite-evidence"]:
    # Bound the raw ASCII bytes before the sole permitted normalization.
    if type(answer) is not str or not answer.isascii() or not 0 < len(answer) <= 64:
        raise ValueError("M9_SELECTOR_INVALID_CHOICE")
    choice = answer.strip(" \t\r\n")
    if choice == "baseline":
        return "baseline"
    if choice == "cite-evidence":
        return "cite-evidence"
    raise ValueError("M9_SELECTOR_INVALID_CHOICE")


def checked_observation(payload: Any) -> Observation:
    try:
        return Observation.model_validate(payload)
    except ValidationError:
        raise SelectorRefused("M9_SELECTOR_INVALID_OBSERVATION") from None
    except TypeError:
        raise SelectorRefused("M9_SELECTOR_OBSERVATION_TYPE") from None


async def select(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    """Close both outcomes at one boundary before the walker can publish data."""
    try:
        return await _select(ctx, inputs)
    except ValidationError:
        raise SelectorRefused("M9_SELECTOR_INVALID_OBSERVATION") from None
    except TypeError:
        raise SelectorRefused("M9_SELECTOR_OBSERVATION_TYPE") from None
    except OSError:
        raise SelectorRefused("M9_SELECTOR_SOURCE_OR_PROVIDER_UNAVAILABLE") from None
    except ContractViolation:
        raise SelectorRefused("M9_SELECTOR_CONTRACT_REFUSED") from None


async def _select(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    if inputs != {"training": training()} or source_revision() != SOURCE:
        raise ValueError("M9_SELECTOR_INPUT_OR_SOURCE_DRIFT")
    executor = ctx.capability("executor")
    if not isinstance(executor, CodexOperatorHandle):
        raise ValueError("M9_SELECTOR_REQUIRES_CODEX_READ")
    revision = executor.provider.identity.revision
    if (executor.context.binding.revision != revision or ctx.grants != READ_GRANTS
            or executor.provider.profile.grant_faults(READ_GRANTS)):
        raise ValueError("M9_SELECTOR_PROVIDER_OR_GRANT_DRIFT")
    outcome = await executor.execute(task(), workspace=None, grants=ctx.grants)
    # codex.py:1946-1970 takes requested_model from the sealed grants and passes
    # it to codex_protocol.py:1623-1668; that producer copies output, served_model,
    # usage and elapsed_s into ExecutorSuccess, leaving unobserved fields None.
    # Only bounded ASCII transport whitespace may surround the literal ID.
    if (not isinstance(outcome, ExecutorSuccess)
            or outcome.requested_model != READ_GRANTS.model_selection.model):
        raise ValueError("M9_SELECTOR_INVALID_OUTCOME")
    choice = parse_choice(outcome.output)
    if (source_revision() != SOURCE or executor.provider.identity.revision != revision
            or not math.isfinite(outcome.elapsed_s)):
        raise ValueError("M9_SELECTOR_COMPLETION_DRIFT")
    observed = checked_observation(dict(
        choice=choice, source=SOURCE,
        task=digest("m9-selector-task", 1, task().model_dump(mode="json")),
        provider_revision=Digest(revision), requested_model=outcome.requested_model,
        served_model=outcome.served_model,
        input_tokens=None if outcome.usage is None else outcome.usage.input_tokens,
        output_tokens=None if outcome.usage is None else outcome.usage.output_tokens,
        elapsed_s=outcome.elapsed_s, reply_bytes=len(outcome.output),
    ))
    return {"choice": observed.choice, "observation": observed.model_dump(mode="json")}


select.__constructicon_adapter_revision__ = SOURCE  # type: ignore[attr-defined]


def definition() -> ComponentDef:
    component, _ = atomic(COMPONENT, (TRAIN,), (CHOICE, OBSERVATION), select)
    return component.model_copy(update={"capability_requirements": (
        CapabilityRequirement(alias="executor", kind="executor"),
    )})


def graph() -> Graph:
    return Graph(
        name="m9-select", inputs=(TRAIN,), outputs=(CHOICE, OBSERVATION),
        nodes=(GraphNode(id="select", body=Ref(
            component=COMPONENT, version=str(definition().content_hash()),
            bind={"executor": CAPABILITY}, grants=GrantRequest(
                posture=READ_GRANTS.posture, model=READ_GRANTS.model_selection.model,
                effort=READ_GRANTS.effort, allowed_tools=(), env_allowlist=(),
                network="allow", timeout_s=READ_GRANTS.timeout_s,
            ),
        )),),
    )


def retained(journal: Journal, run: RunId, *, exam: Exam | None = None) -> Observation:
    """Affirm provenance at replay/issuance, with no provider construction or I/O."""
    record = journal.run_record(run)
    checkpoint = journal.checkpoint(run, PATH)
    raw = None if record is None else journal.load_manifest_json(record.manifest_hash)
    if (record is None or record.status != RunStatus.SUCCEEDED or raw is None
            or checkpoint is None or record.origin is None
            or record.origin.kind != "start" or record.origin.effects != "live"
            or record.origin.capabilities != "normal"):
        raise ValueError("M9_SELECTOR_INCOMPLETE_PRESERVE_STORE_NO_RETRY")
    manifest = parse_manifest_json(raw)
    component = definition()
    body = component.body
    expected = {"training": training()}
    if exam is not None and canonical_json(exam.training_projection()) != training():
        raise ValueError("M9_SELECTOR_TRAINING_SEAL_MISMATCH")
    if (source_revision() != SOURCE or not isinstance(body, PythonRef)
            or manifest.source_graph != graph() or manifest.resolved_loops
            or manifest.manifest_hash != record.manifest_hash
            or record.input_hash != digest("inputs", 1, expected)
            or manifest.input_hash != record.input_hash or journal.run_inputs(run) != expected
            or len(manifest.resolved_components) != 1
            or len(manifest.capability_bindings) != 2
            or checkpoint.run_id != run or checkpoint.path != PATH
            or checkpoint.input_hash != record.input_hash
            or checkpoint.resolved_version != component.content_hash()
            or set(checkpoint.outputs) != {"choice", "observation"}):
        raise ValueError("M9_SELECTOR_RETAINED_IDENTITY_MISMATCH")
    (resolution,) = manifest.resolved_components
    if (resolution.scope != PATH.scope or resolution.component != COMPONENT
            or resolution.resolved_version != component.content_hash()
            or resolution.implementation_digest != body.source_digest):
        raise ValueError("M9_SELECTOR_RETAINED_IMPLEMENTATION_MISMATCH")
    for name, envelope in checkpoint.outputs.items():
        if envelope.run_id != run or envelope.path != PATH or envelope.port != name:
            raise ValueError("M9_SELECTOR_RETAINED_ENVELOPE_MISMATCH")
    observed = checked_observation(checkpoint.outputs["observation"].payload)
    bindings = {binding.binding: binding for binding in manifest.capability_bindings}
    executor = bindings.get("executor")
    own = bindings.get(SELF_BINDING)
    if (observed.source != SOURCE or observed.choice != checkpoint.outputs["choice"].payload
            or observed.task != digest("m9-selector-task", 1, task().model_dump(mode="json"))
            or observed.requested_model != READ_GRANTS.model_selection.model
            or executor is None or executor.scope != PATH.scope
            or executor.capability_id != CAPABILITY
            or executor.revision != str(observed.provider_revision)
            or executor.effective_grants != READ_GRANTS
            or own is None or own.scope != PATH.scope or own.capability_id != SELF_CAPABILITY):
        raise ValueError("M9_SELECTOR_RETAINED_OBSERVATION_MISMATCH")
    return observed
