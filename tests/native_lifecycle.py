"""Journal-owned native fixture. Not an ExecutorProvider or an auth route.

The ordinary lease owns the peer's filesystem root; the existing supervisor
owns native home and descendants. No protocol/session identifier is persisted.
"""

import asyncio
import inspect
import json
from contextlib import suppress
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from constructicon.api.system import Constructicon
from constructicon.core.component import CapabilityRequirement, ComponentDef
from constructicon.core.control import PromotionCommandResult, RegistrationCommandResult
from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.workspace import (
    AcquiredCapability,
    LeaseClosure,
    LeaseReconciliation,
    acquisition_id_for,
    lease_id_for,
)
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors.linux import ProcessExchangeError
from constructicon.substrate.git.acquisition import (
    AcquisitionPaths,
    acquisition_guard,
    dispose_acquisition,
)
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.contained import ContainedWorkspaceProvider
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import LOCAL_ADMIN
from tests.conftest import atomic
from tests.containedworld import decode
from tests.gitworld import EVALUATION, GOAL, WRITE_GRANTS
from tests.native_codex_probe import PROBE_PROMPT, conversation
from tests.native_combined import (
    BASE_INSTRUCTIONS,
    CombinedScenario,
    assert_native_identity,
    controlled_configuration,
)
from tests.native_startup import MODELS
from tests.substrate._gate_owner import installed_launcher
from tests.substrate.test_linux_duplex import line
from tests.substrate.test_native_codex_mediation import PROGRAM
from tests.substrate.test_native_startup import assert_outcome
from tests.substrate.test_provider_placement import observe, placement

# The child proves session changes do not escape the existing reaper. The pipe
# proves setsid finished before the parent reports readiness. No timing guess.
WORKER = """
import os, sys, time
read_fd, write_fd = os.pipe()
child = os.fork()
if child == 0:
    os.close(read_fd)
    os.setsid()
    os.write(write_fd, b'ready')
    os.close(write_fd)
    time.sleep(20)
    os._exit(0)
os.close(write_fd)
assert os.read(read_fd, 5) == b'ready'
os.close(read_fd)
print('worker-ready', flush=True)
assert sys.stdin.readline() == 'continue\\n'
""" + PROGRAM


class NativeFixture:
    def __init__(self, provider, context, paths):
        self.provider, self.context, self.paths = provider, context, paths
        self.entered = self.ready = self.closed = False

    async def materialize(self):
        if self.closed or self.entered:
            raise ContractViolation("native fixture is closed or already entered")
        self.entered = True
        async with acquisition_guard(self.paths):
            await finish_owned(asyncio.create_task(asyncio.to_thread(
                self.provider.closure.require_open, self.paths,
            )))
            self.paths.payload.mkdir(parents=True)
            await self.provider.at("during_materialization", self)
            self.ready = True

    async def require_open(self):
        if self.closed or not self.ready:
            raise ContractViolation("native fixture is not open")
        self.context.check_control()
        await finish_owned(asyncio.create_task(asyncio.to_thread(
            self.provider.closure.require_open, self.paths,
        )))
        self.context.check_control()

    async def run(self, workspace):
        await self.require_open()
        # This is the same cancellation-aware wait pattern used by contained
        # gates. The original error survives joined teardown, including failure.
        work = asyncio.create_task(self.exchange(workspace))

        async def stop():
            if not work.done():
                work.cancel()
            with suppress(asyncio.CancelledError):
                await work

        try:
            while not work.done():
                await asyncio.wait({work}, timeout=0.05)
                self.context.check_control()
            return work.result()
        finally:
            await finish_owned(asyncio.create_task(stop()))

    async def exchange(self, workspace):
        async with acquisition_guard(self.paths) as guard:
            await self.require_open()
            return await self.exchange_owned(workspace, guard)

    async def worker(self, view, native_guard, deadline, record):
        await self.require_open()
        record["worker"] = evidence = {"process": None, "decoded": None, "ready": False}
        result = None
        try:
            async with view.use() as guard:
                async def proceed(io):
                    assert await line(io, 8192) == b"worker-ready\n"
                    evidence["ready"] = True
                    await self.provider.at("during_active", self)
                    await self.require_open()
                    await io.write(b"continue\n")
                    await io.close_stdin()
                    while await io.read():
                        pass

                result = await self.provider.launcher.exchange(
                    ("/usr/bin/python3", "-I", "-c", WORKER), workspace=Path(view.path),
                    posture=Posture.READ, guard_fds=(native_guard, guard), conversation=proceed,
                    timeout_s=max(0.001, deadline - asyncio.get_running_loop().time()),
                )
        except ProcessExchangeError as exc:
            result = exc.result
            raise
        finally:
            if result is not None:
                evidence["process"] = {**asdict(result), "stdout": result.stdout.hex(),
                                       "stderr": result.stderr.hex()}
                # Readiness is framing, not an executor result. Preserve damage
                # and failed outcomes before asserting the successful scenario.
                decoded = decode(replace(result, stdout=result.stdout.removeprefix(
                    b"worker-ready\n",
                )), self.provider.model)
                evidence["decoded"] = decoded.model_dump(mode="json")
        assert_outcome(result)
        assert result.stdout.startswith(b"worker-ready\n")
        assert decoded.status == "success" and decoded.output == {"contained": True}

    async def exchange_owned(self, workspace, native_guard):
        provider = self.provider
        view = provider.workspaces.owned_view(workspace, self.context)
        now = datetime.now(UTC)
        dates = tuple(dict.fromkeys((now.date().isoformat(),
                                    (now + timedelta(seconds=20)).date().isoformat())))
        output = json.dumps({"contained": True})
        scenario = CombinedScenario(provider.model, dates, "contained_python",
                                    {"program": PROGRAM}, output)
        async with placement(
            provider.image, model=provider.model, directory=self.paths.payload,
            scenario=PROBE_PROMPT, tool=scenario.tool, arguments=scenario.arguments,
            request_check=scenario,
        ) as (composed, peer, record):
            self.observation = record
            record["native_lifecycle"] = {
                "run_id": str(self.context.run_lease.run_id),
                "acquisition": self.paths.acquisition_id,
                "epoch": self.context.run_lease.epoch,
                "model": provider.model,
            }

            async def worker(program):
                assert program == PROGRAM
                await self.worker(view, native_guard, peer.deadline, record)
                return output

            async def query(wire, observed):
                observed["placement"] = (await wire.read())["placement"]
                observed["bootstrap"] = await wire.read()
                observed["protocol"] = await conversation(
                    wire, "/tmp/native-startup", worker, model=provider.model,
                    base_instructions=BASE_INSTRUCTIONS,
                )
                await wire.io.close_stdin()

            await self.require_open()
            observed, result = await observe(
                composed, peer, provider.root, query=query, record=record,
                config=controlled_configuration(provider.model), guard_fd=native_guard,
            )
        assert_outcome(result)
        assert len(peer.requests) == 2 and not peer.failures
        assert_native_identity(observed["protocol"], peer.requests)
        assert observed["protocol"]["calls"] == ["call_probe"]
        record["native_lifecycle"]["thread_id"] = observed["protocol"]["thread"]
        provider.completed.append(record["native_lifecycle"])
        await provider.at("before_checkpoint", self)
        return {"complete": True}


class NativeFixtureProvider:
    def __init__(self, root, workspaces, image, model):
        self.root, self.workspaces, self.image = root.resolve(), workspaces, image
        self.launcher, self.closure, self.model = workspaces.launcher, workspaces.closure, model
        assert model in MODELS
        self.handles, self.completed = [], []
        self.hook = None
        self.revision = str(digest("native-lifecycle-fixture", 1, {
            "source": inspect.getsource(inspect.getmodule(NativeFixture)),
            "image": str(image.expected_runtime), "model": model,
            "recipe": controlled_configuration(model),
        }))

    def reference(self, acquisition):
        return canonical_json({"root": str(self.root), "acquisition": acquisition})

    async def at(self, phase, handle):
        if self.hook is not None:
            await self.hook(phase, handle)

    async def acquire(self, context):
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        acquisition = acquisition_id_for(logical, context.run_lease.epoch)
        handle = NativeFixture(self, context, AcquisitionPaths(self.root, acquisition))
        self.handles.append(handle)
        return AcquiredCapability(handle, logical, acquisition, self.reference(acquisition),
                                  handle.materialize)

    async def close(self, acquired, disposition):
        handle = acquired.resource
        if not isinstance(handle, NativeFixture) or handle.provider is not self:
            raise ContractViolation("native fixture close requires its own handle")
        handle.closed = True
        if handle.entered:
            await dispose_acquisition(self.closure, handle.paths)
        return LeaseClosure("released" if disposition == "release" else "discarded")

    async def reconcile(self, context, stale):
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        reaped = []
        for item in stale:
            row = item.lease
            acquisition = acquisition_id_for(logical, row.acquisition_epoch)
            if (row.lease_id != logical or row.run_id != context.run_lease.run_id
                    or row.path != context.path or row.binding_id != context.binding.binding
                    or row.acquisition_epoch >= context.run_lease.epoch
                    or row.resource_ref != self.reference(acquisition)):
                raise ContractViolation("native fixture recovery contradicts its durable row")
            await dispose_acquisition(self.closure, AcquisitionPaths(self.root, acquisition))
            reaped.append(row.resource_ref)
        return LeaseReconciliation(reaped=tuple(reaped))


async def invoke_native(ctx, inputs):
    assert inputs["goal"] == {"message": "native fixture"}
    return {"evaluation": await ctx.capability("native").run(ctx.capability("workspace"))}


async def register_native(control):
    definition, _ = atomic("test/native-fixture", (GOAL,), (EVALUATION,), invoke_native)
    definition = ComponentDef.model_validate({
        **definition.model_dump(), "capability_requirements": (
            CapabilityRequirement(alias="native", kind="test.native-fixture"),
            CapabilityRequirement(alias="workspace", kind="workspace.contained"),
        ),
    })
    registered = await control.registry_register(LOCAL_ADMIN, definition=definition,
                                                 idempotency_key="register-native")
    assert isinstance(registered, RegistrationCommandResult), registered
    promoted = await control.registry_promote_initial(
        LOCAL_ADMIN, component=definition.name, version=registered.version,
        idempotency_key="promote-native",
    )
    assert isinstance(promoted, PromotionCommandResult), promoted
    return Graph(name="native", inputs=(GOAL,), outputs=(EVALUATION,), nodes=(
        GraphNode(id="probe", body=Ref(component=definition.name,
                                       bind={"native": "native", "workspace": "workspace"})),
    ))


def assemble(root, model=MODELS[0], owner="native-owner", *, launcher=None, image=None):
    import os

    launcher = installed_launcher() if launcher is None else launcher
    if image is None:
        runtime = Path(os.environ["M8_PLACEMENT_ROOT"])
        image = replace(launcher, runtime_root=runtime, expected_runtime=Digest(
            json.loads(runtime.with_suffix(".json").read_text())["runtime_digest"],
        ))
    journal = SqliteJournal(root / "control.sqlite")
    workspaces = ContainedWorkspaceProvider(
        GitAuthority(root / "authority.git", root / "legacy"), root=root / "w",
        target_ref="refs/heads/main", provider_id="native-fixture-workspace",
        posture=Posture.READ, launcher=launcher,
    )
    provider = NativeFixtureProvider(root / "n", workspaces, image, model)
    system = Constructicon(
        journal=journal, owner_id=owner, lease_ttl_s=2, heartbeat_interval_s=0.2,
        # Generic grants permit this fixture's route. The worker's existing
        # launcher still enforces its stronger, networkless namespace.
        root_grants=WRITE_GRANTS.model_copy(update={"posture": Posture.READ, "network": "allow"}),
        capabilities={"native": provider, "workspace": workspaces}, catalog={
            "native": CapabilityDescriptor(capability_id="native", kind="test.native-fixture",
                                           revision=provider.revision, leased=True),
            "workspace": CapabilityDescriptor(capability_id="workspace", kind="workspace.contained",
                                              revision="native-read-fixture-v1", leased=True),
        },
    )
    return system, journal, provider
