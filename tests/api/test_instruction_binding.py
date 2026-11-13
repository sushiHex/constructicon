"""The instruction is pinned as the target is (docs/designs/INSTRUCTION_BINDING.md).

The exam stays installed code. The instruction is the base commit's file at a
path fixed by the task's purpose; its SHA-256 is in the request the owner
approves, and the writer refuses any other bytes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from constructicon.api import _maintenance_source as source_module
from constructicon.api._maintenance_source import CHANNEL_HELPER, base_instruction
from constructicon.api.plan_manifest_application import (
    INSTRUCTION,
    PLAN_MANIFEST,
    maintenance_definitions,
    maintenance_graph,
    maintenance_system,
    maintenance_writer,
    pinned_instruction,
    require_maintenance_resources,
)
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.envelope import GitRef
from constructicon.core.errors import ContractViolation
from constructicon.core.maintenance import (
    INSTRUCTION_BYTES,
    ChannelReplyRequest,
    PlanManifestRequest,
    instruction_path,
)
from constructicon.runtime.context import NodeContext
from constructicon.substrate.journal.maintenance_diagnostic import _FAILURES
from tests.api.test_plan_manifest_application import (
    BASE,
    INPUTS,
    REQUEST,
    Writer,
)
from tests.api.test_plan_manifest_application import (
    concrete_application as concrete_application,
)
from tests.captureworld import ControlledAsyncWorkspace
from tests.gitworld import WRITE_GRANTS
from tests.maintenance_instructions import (
    CHANNEL_INSTRUCTION,
    CHANNEL_PURPOSE,
    PLAN_PURPOSE,
    WRITE_INSTRUCTION,
    fast_import_entry,
    instruction_bytes,
    instruction_sha256,
    pinned,
)
from tests.substrate.test_codex_adapter import portable_binding as portable_binding

NO_DIGEST = "maintenance request carries no instruction digest"
DIFFERS = "maintenance instruction differs from its pinned digest"
ERA_ONE = {"repository": "authority", "target_ref": "refs/heads/main",
           "base_commit": "a" * 40, "target_sha256": "b" * 64,
           "check_set_hash": str(REQUEST.check_set_hash)}


@pytest.mark.parametrize("model", [PlanManifestRequest, ChannelReplyRequest])
def test_a_request_has_two_eras_and_only_the_second_pins_an_instruction(model):
    old = model.model_validate(ERA_ONE)
    # Era 1 names no instruction and keeps its exact wire: the key is absent, not null.
    assert old.schema_version == 1 and old.instruction_sha256 is None
    assert "instruction_sha256" not in old.model_dump(mode="json")
    assert "instruction_sha256" not in json.loads(old.model_dump_json())
    assert model.model_validate_json(old.model_dump_json()) == old
    new = model.model_validate({**ERA_ONE, "schema_version": 2, "instruction_sha256": "c" * 64})
    assert new.model_dump(mode="json")["instruction_sha256"] == "c" * 64
    assert model.model_validate_json(new.model_dump_json()) == new != old
    # The eras never blur: a digest belongs to version 2 and version 2 requires one.
    for mixed in ({**ERA_ONE, "instruction_sha256": "c" * 64},
                  {**ERA_ONE, "schema_version": 2},
                  {**ERA_ONE, "schema_version": 2, "instruction_sha256": None},
                  {**ERA_ONE, "schema_version": 2, "instruction_sha256": "C" * 64},
                  {**ERA_ONE, "schema_version": 3, "instruction_sha256": "c" * 64}):
        with pytest.raises(ValidationError):
            model.model_validate(mixed)


def test_the_instruction_lives_at_a_path_fixed_by_the_purpose_and_outside_installed_source():
    for purpose in (PLAN_PURPOSE, CHANNEL_PURPOSE):
        assert instruction_path(purpose) == f"maintenance/{purpose}.txt"
        assert instruction_bytes(purpose).endswith(b"\n")
    assert INSTRUCTION.name == "instruction"
    writer, checker = maintenance_definitions(PLAN_MANIFEST)
    # The writer declares the text as an input; the checker never sees it.
    assert INSTRUCTION in writer.definition.inputs and INSTRUCTION not in checker.definition.inputs
    graph = maintenance_graph(executor_id="executor", workspace_id="workspace", gate_id="gate",
                              writer_grants=WRITE_GRANTS)
    assert [port.name for port in graph.inputs] == ["request", "instruction"]


def show_of(entry: bytes, blob: bytes):
    calls = []

    async def show(*args):
        calls.append(args)
        return entry if args[0] == "ls-tree" else blob

    return show, calls


def entry(mode="100644", kind="blob", purpose=CHANNEL_PURPOSE):
    return f"{mode} {kind} {'1' * 40}\t{instruction_path(purpose)}\n".encode()


@pytest.mark.parametrize(("listed", "blob", "refusal"), [
    (entry(), instruction_bytes(CHANNEL_PURPOSE), None),
    (b"", b"", "maintenance base lacks its task instruction"),
    (entry("100755"), instruction_bytes(CHANNEL_PURPOSE),
     "maintenance base lacks its task instruction"),
    (entry("120000"), b"elsewhere", "maintenance base lacks its task instruction"),
    (entry("040000", "tree"), b"", "maintenance base lacks its task instruction"),
    (entry() + entry(), instruction_bytes(CHANNEL_PURPOSE),
     "maintenance base lacks its task instruction"),
    (entry(), b"", "maintenance instruction is not bounded UTF-8 text"),
    (entry(), b"\xff" + instruction_bytes(CHANNEL_PURPOSE),
     "maintenance instruction is not bounded UTF-8 text"),
    (entry(), instruction_bytes(CHANNEL_PURPOSE) + b" " * INSTRUCTION_BYTES,
     "maintenance instruction is not bounded UTF-8 text"),
    (entry(), instruction_bytes(CHANNEL_PURPOSE).replace(b"-> ChannelMessage | None", b"-> None"),
     "maintenance instruction omits the installed helper"),
    (entry(), instruction_bytes(PLAN_PURPOSE),
     "maintenance instruction omits the installed helper"),
], ids=["committed", "absent", "executable", "symlink", "directory", "two-entries", "empty",
        "not-utf8", "over-bound", "helper-edited", "other-task"])
async def test_the_base_instruction_is_read_exactly_or_refused_by_name(listed, blob, refusal):
    show, calls = show_of(listed, blob)
    if refusal is None:
        assert await base_instruction(show, "a" * 40, CHANNEL_PURPOSE) == CHANNEL_INSTRUCTION
        assert calls == [("ls-tree", "a" * 40, "--", "maintenance/channel-stored-reply.txt"),
                         ("show", "a" * 40 + ":maintenance/channel-stored-reply.txt")]
        return
    with pytest.raises(ContractViolation) as refused:
        await base_instruction(show, "a" * 40, CHANNEL_PURPOSE)
    assert str(refused.value) == refusal


async def test_the_bound_is_inclusive_and_the_helper_rule_is_the_channel_tasks_alone():
    exact = b"x" * INSTRUCTION_BYTES
    show, _calls = show_of(entry(purpose=PLAN_PURPOSE), exact)
    assert await base_instruction(show, "a" * 40, PLAN_PURPOSE) == exact.decode()
    show, _calls = show_of(entry(purpose=PLAN_PURPOSE), exact + b"x")
    with pytest.raises(ContractViolation, match="not bounded UTF-8 text"):
        await base_instruction(show, "a" * 40, PLAN_PURPOSE)
    assert CHANNEL_HELPER.startswith("    def _stored_reply(") and CHANNEL_HELPER.endswith("\n")


def test_only_the_text_the_request_pins_is_the_instruction():
    assert pinned_instruction(REQUEST, WRITE_INSTRUCTION) is WRITE_INSTRUCTION
    era_one = PlanManifestRequest.model_validate(ERA_ONE)
    for request, text, refusal in (
        (era_one, WRITE_INSTRUCTION, NO_DIGEST),
        (REQUEST, WRITE_INSTRUCTION + " ", DIFFERS),
        (REQUEST, WRITE_INSTRUCTION.rstrip("\n"), DIFFERS),
        (REQUEST, CHANNEL_INSTRUCTION, DIFFERS),
        (REQUEST, WRITE_INSTRUCTION.encode(), DIFFERS),
        (REQUEST, None, DIFFERS),
        (REQUEST, "\ud800", DIFFERS),
        # A surrogate is refused outright: it is never replaced and then matched.
        (REQUEST.model_copy(update={"instruction_sha256": hashlib.sha256(b"?").hexdigest()}),
         "\ud800", DIFFERS),
        # Nor can a request pin the empty text and so admit a missing instruction.
        (REQUEST.model_copy(update={"instruction_sha256": hashlib.sha256(b"").hexdigest()}),
         None, DIFFERS),
        (REQUEST.model_copy(update={"instruction_sha256": hashlib.sha256(b"").hexdigest()}),
         "", DIFFERS),
    ):
        with pytest.raises(ContractViolation) as refused:
            pinned_instruction(request, text)
        assert str(refused.value) == refusal
    # The installed diagnostic names both, so a refused writer is never "unknown".
    assert _FAILURES[NO_DIGEST] == _FAILURES[DIFFERS] == "writer-instruction"


@pytest.mark.parametrize(("inputs", "refusal"), [
    ({**INPUTS, "instruction": WRITE_INSTRUCTION + "Also do something else.\n"}, DIFFERS),
    ({"request": INPUTS["request"]}, DIFFERS),
    ({"request": {key: value for key, value in INPUTS["request"].items()
                  if key != "instruction_sha256"} | {"schema_version": 1},
      "instruction": WRITE_INSTRUCTION}, NO_DIGEST),
], ids=["other-text", "no-text", "era-one-request"])
async def test_the_writer_refuses_before_dispatch_unless_the_text_is_the_pinned_one(
    inputs, refusal,
):
    workspace = ControlledAsyncWorkspace(SimpleNamespace(check_control=lambda: None))
    workspace.reference = GitRef(repository=REQUEST.repository, commit=BASE, diff_against=BASE)
    workspace.ready = True
    executor = Writer()
    ctx = NodeContext(run_id=RunId("run-" + "1" * 32),
        path=ExecutionPath(scope=ScopePath(segments=("instruction", "writer"))),
        capabilities={"workspace": workspace, "executor": executor},
        grants=WRITE_GRANTS, effect=lambda *args, **kwargs: pytest.fail("unexpected effect"))
    with pytest.raises(ContractViolation) as refused:
        await maintenance_writer(ctx, inputs)
    assert str(refused.value) == refusal
    # Nothing was dispatched: the executor never saw a task.
    assert executor.calls == []


@pytest.mark.parametrize("concrete_application", ["channel-stored-reply", None], indirect=True,
                         ids=["channel", "plan"])
@pytest.mark.parametrize("change", ["other-text", "era-one", "other-digest"])
async def test_assembled_resources_must_hold_the_base_commits_own_instruction(
    concrete_application, change,
):
    resources, executor, _system, _control, _launch = concrete_application
    await require_maintenance_resources(resources)
    assert hashlib.sha256(resources.instruction.encode()).hexdigest() \
        == resources.request.instruction_sha256
    assert resources.inputs == {"request": resources.request.model_dump(mode="json"),
                                "instruction": resources.instruction}
    if change == "other-text":
        changed, refusal = replace(resources, instruction=resources.instruction + " "), DIFFERS
    elif change == "era-one":
        fields = resources.request.model_dump(mode="json")
        del fields["instruction_sha256"]
        changed = replace(resources, request=type(resources.request).model_validate(
            {**fields, "schema_version": 1}))
        refusal = NO_DIGEST
    else:
        # Text and digest agree with each other but not with the pinned base commit.
        text = resources.instruction + "Also do something else.\n"
        changed = replace(resources, instruction=text, request=resources.request.model_copy(
            update={"instruction_sha256": hashlib.sha256(text.encode()).hexdigest()}))
        refusal = DIFFERS
    with pytest.raises(ContractViolation) as refused:
        await require_maintenance_resources(changed)
    assert str(refused.value) == refusal
    with pytest.raises(ContractViolation):
        await maintenance_system(changed, executor_id="executor", executor=executor,
            executor_descriptor=executor.descriptor("executor"), writer_grants=WRITE_GRANTS)


@pytest.mark.parametrize(("purpose", "carried", "refusal"), [
    (CHANNEL_PURPOSE, CHANNEL_PURPOSE, None),
    (CHANNEL_PURPOSE, None, "maintenance base lacks its task instruction"),
    (CHANNEL_PURPOSE, PLAN_PURPOSE, "maintenance base lacks its task instruction"),
], ids=["carried", "absent", "other-task-only"])
async def test_preparation_refuses_a_base_without_its_instruction_before_any_pin(
    tmp_path, monkeypatch, purpose, carried, refusal,
):
    import shutil
    from pathlib import Path

    from constructicon.core.maintenance import CHANNEL_TARGET_PATH
    from constructicon.substrate.executors.linux import ProcessLimits
    from constructicon.substrate.git.process import GitProcess
    from tests.substrate.test_channel_reply_oracle import BASE as TARGET

    seed = tmp_path / "reviewed-source.git"
    seed.mkdir()
    await source_module.git(seed, "init", "--bare", "--template=", ".")
    commit = (b"commit refs/heads/reviewed\n"
              b"committer test <test@example.invalid> 1767225600 +0000\ndata 1\nx\n"
              + f"M 100644 inline {CHANNEL_TARGET_PATH}\ndata {len(TARGET)}\n".encode()
              + TARGET + b"\n" + (b"" if carried is None else fast_import_entry(carried))
              + b"\ndone\n")
    await GitProcess(str(Path(shutil.which("git")).resolve()), ProcessLimits()).run(
        "fast-import", "--quiet", cwd=seed, stdin=commit)
    bundle = tmp_path / "reviewed.bundle"
    await source_module.git(seed, "bundle", "create", str(bundle), "refs/heads/reviewed")
    base = (await source_module.git(seed, "rev-parse", "refs/heads/reviewed")).strip().decode()
    root = tmp_path / "maintenance"

    def portable_custody(path):
        assert path.resolve().is_relative_to(tmp_path.resolve()) and path.is_dir()

    monkeypatch.setattr(source_module, "private_root", portable_custody)
    prepare = source_module.prepare_source(root, bundle,
        bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
        base_commit=base, target_ref="refs/heads/maintenance", purpose=purpose)
    if refusal is None:
        pin = await prepare
        # The pin's wire is unchanged: the request, not the pin, names the instruction.
        assert set(pin.sources) == {CHANNEL_TARGET_PATH}
        text = await base_instruction(
            lambda *args: source_module.git(root / "authority.git", *args), base, purpose)
        assert hashlib.sha256(text.encode()).hexdigest() == instruction_sha256(purpose)
        assert pinned(purpose)["instruction_sha256"] == instruction_sha256(purpose)
        return
    with pytest.raises(ContractViolation) as refused:
        await prepare
    assert str(refused.value) == refusal
    assert not (root / "source-pin.json").exists()


