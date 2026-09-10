"""Native WRITE capture: hostile stage -> immutable bytes -> exact candidate."""

from __future__ import annotations

import asyncio
import inspect
import json
import shlex
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.envelope import GitRef
from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import digest
from constructicon.core.run import OwnershipLost
from constructicon.core.workspace import AsyncWriteWorkspace
from constructicon.substrate.executors.linux import ProcessLimits
from constructicon.substrate.git import capture as capture_module
from constructicon.substrate.git.capture import ContainedWriteWorkspaceProvider
from tests.substrate.test_contained_workspace import context, stale_row
from tests.substrate.test_contained_workspace import provider as provider
from tests.substrate.test_linux_containment import launcher as launcher


def write_provider(original, launch):
    return ContainedWriteWorkspaceProvider(
        original.authority,
        root=original.root,
        target_ref=original.target_ref,
        provider_id="capture",
        posture=Posture.WRITE,
        launcher=launch,
    )


def write_context(provider, *, epoch=1, check=lambda: None):
    original = context(posture=Posture.WRITE, epoch=epoch)
    return replace(
        original,
        binding=original.binding.model_copy(update={"revision": provider.revision}),
        check_control=check,
    )


@pytest.fixture
async def capture(provider, launcher):
    provider = write_provider(provider, launcher)
    ctx = write_context(provider)
    acquired = await provider.acquire(ctx)
    await acquired.materialize()
    try:
        yield provider, ctx, acquired
    finally:
        if not acquired.resource.closed:
            await provider.close(acquired, "discard")


async def child(provider, view, source):
    async with view.use() as guard:
        result = await provider.launcher.run(
            ("/usr/bin/python3", "-I", "-c", source),
            workspace=Path(view.path),
            posture=Posture.WRITE,
            guard_fds=(guard,),
            timeout_s=10,
        )
    assert result.returncode == 0, result.stderr
    return result.stdout


async def test_async_capture_is_a_distinct_inert_capability_and_requires_run_control(provider):
    launch = SimpleNamespace(
        revision=digest("fake-launch", 1, "unavailable"), limits=ProcessLimits()
    )
    provider = write_provider(provider, launch)
    ctx = write_context(provider)
    with pytest.raises(ContractViolation, match="control check"):
        await provider.acquire(replace(ctx, check_control=None))
    acquired = await provider.acquire(ctx)
    assert not provider.root.exists()
    assert provider.kind == "workspace.contained"
    assert isinstance(acquired.resource, AsyncWriteWorkspace)
    assert inspect.iscoroutinefunction(acquired.resource.commit_all)
    assert inspect.iscoroutinefunction(acquired.resource.reset_to)
    await provider.close(acquired, "discard")
    assert not provider.root.exists() and not provider.closure.is_closed(acquired.resource.paths)


async def test_capture_preserves_agent_history_and_exact_candidate_without_installing(capture):
    provider, _, acquired = capture
    view = acquired.resource
    base = view.base
    agent = await child(
        provider,
        view,
        """
import os, subprocess
os.environ.update(GIT_AUTHOR_NAME='agent', GIT_AUTHOR_EMAIL='agent@test.invalid',
                  GIT_COMMITTER_NAME='agent', GIT_COMMITTER_EMAIL='agent@test.invalid')
open('agent.txt','w').write('first agent commit')
subprocess.run(['/usr/bin/git','add','--all'],check=True)
subprocess.run(['/usr/bin/git','commit','-qm','agent authored'],check=True)
subprocess.run(['/usr/bin/git','rev-parse','HEAD'],check=True)
open('pending.txt','w').write('uncommitted change')
""",
    )
    oid = await view.commit_all("--message with 'quotes'\nand a second line")
    assert provider.authority.parents_of(oid) == (agent.decode().strip(),)
    assert provider.authority.parents_of(provider.authority.parents_of(oid)[0]) == (base,)
    assert provider.authority._run("show", f"{oid}:pending.txt").stdout == "uncommitted change"
    assert view.git_ref().commit == oid and view.git_ref().diff_against == base
    assert provider.closure.candidate(provider._candidate_ref(view)) == oid
    assert provider.authority.resolve_ref("refs/heads/main") == base
    assert not list(view.paths.payload.glob("quarantine-*"))
    with pytest.raises(ContractViolation, match="after candidate"):
        await view.reset_to(GitRef(repository=provider.authority.repository_id, commit=base))
    await provider.close(acquired, "release")
    assert provider.closure.candidate(provider._candidate_ref(view)) == oid
    assert not view.paths.payload.exists()


async def test_reset_uses_a_trusted_pack_then_captures_inside_the_same_boundary(capture):
    provider, _, acquired = capture
    view = acquired.resource
    await child(provider, view, "open('calc.py','w').write('broken'); open('extra','w').write('x')")
    await view.reset_to(GitRef(repository=provider.authority.repository_id, commit=view.base))
    assert not Path(view.path, "extra").exists()
    assert Path(view.path, "calc.py").read_text().startswith("def add")
    assert await view.commit_all("nothing changed") == view.base


async def test_response_loss_replays_the_candidate_without_reopening_the_stage(
    capture, monkeypatch
):
    provider, _, acquired = capture
    view = acquired.resource
    await child(provider, view, "open('answer.txt','w').write('one candidate')")
    publish = provider.closure.publish

    def lose_response(*args):
        publish(*args)
        raise ConnectionError("lost after candidate publication")

    monkeypatch.setattr(provider.closure, "publish", lose_response)
    with pytest.raises(ConnectionError):
        await view.commit_all("candidate")
    retained = provider.closure.candidate(provider._candidate_ref(view))
    assert retained is not None

    async def forbidden(*args, **kwargs):
        pytest.fail("response-loss replay reopened mutable Git")

    monkeypatch.setattr(provider, "_contained", forbidden)
    assert await view.commit_all("candidate") == retained


@pytest.mark.parametrize(
    "damage",
    ["hook", "include", "filter", "fsmonitor", "helper", "alternates", "git-symlink", "stale-lock"],
)
async def test_hostile_git_metadata_cannot_execute_or_modify_a_host_sentinel(
    capture, tmp_path, damage
):
    provider, _, acquired = capture
    view = acquired.resource
    stage = Path(view.path)
    sentinel = tmp_path / "host-sentinel"
    sentinel.write_text("untouched")
    hostile = "from pathlib import Path; Path(" + repr(str(sentinel)) + ").write_text('escaped')"
    shell = "/usr/bin/python3 -c " + shlex.quote(hostile)
    config = stage / ".git/config"
    with config.open("a") as stream:
        if damage == "include":
            included = tmp_path / "host-only-config"
            included.write_text("[core]\nfsmonitor = " + json.dumps(shell) + "\n")
            stream.write(f"\n[include]\npath = {included}\n")
        elif damage == "filter":
            stream.write(
                '\n[filter "attack"]\nclean = ' + json.dumps(shell) + "\nrequired = true\n"
            )
            (stage / ".gitattributes").write_text("*.txt filter=attack\n")
        elif damage == "fsmonitor":
            stream.write("\n[core]\nfsmonitor = " + json.dumps(shell) + "\n")
        elif damage == "helper":
            stream.write("\n[credential]\nhelper = " + json.dumps("!" + shell) + "\n")
    if damage == "hook":
        hook = stage / ".git/hooks/pre-commit"
        hook.parent.mkdir()
        hook.write_text("#!/usr/bin/python3\n" + hostile + "\n")
        hook.chmod(0o700)
    elif damage == "alternates":
        (stage / ".git/objects/info/alternates").write_text(
            str(Path(provider.authority.repository_id) / "objects") + "\n",
        )
    elif damage == "git-symlink":
        (stage / ".git").rename(stage / "old-git")
        (stage / ".git").symlink_to(provider.authority.repository_id, target_is_directory=True)
    elif damage == "stale-lock":
        (stage / ".git/index.lock").write_text("stale")
    (stage / "changed.txt").write_text("candidate change")
    try:
        oid = await view.commit_all("hostile capture")
    except ContractViolation:
        assert provider.closure.candidate(provider._candidate_ref(view)) is None
    else:
        assert provider.closure.candidate(provider._candidate_ref(view)) == oid
    assert sentinel.read_text() == "untouched", "mutable staging metadata escaped onto the host"


@pytest.mark.parametrize("error", [OwnershipLost, asyncio.CancelledError])
async def test_capture_observes_control_loss_before_publication(
    provider, launcher, monkeypatch, error
):
    provider = write_provider(provider, launcher)
    lost = False

    def check():
        if lost:
            raise error("invocation stopped")

    acquired = await provider.acquire(write_context(provider, check=check))
    await acquired.materialize()
    imported = capture_module.import_pack

    async def lose_after_import(*args, **kwargs):
        nonlocal lost
        await imported(*args, **kwargs)
        lost = True

    monkeypatch.setattr(capture_module, "import_pack", lose_after_import)
    try:
        with pytest.raises(error):
            await acquired.resource.commit_all("lost")
        assert lost
        assert provider.closure.candidate(provider._candidate_ref(acquired.resource)) is None
    finally:
        await provider.close(acquired, "discard")


async def test_disposal_finishes_before_a_paused_old_publisher_resumes(capture, monkeypatch):
    provider, ctx, acquired = capture
    view = acquired.resource
    entered, release = threading.Event(), threading.Event()
    publish = provider.closure.publish

    def paused(*args):
        entered.set()
        assert release.wait(15), "test did not release old publication"
        publish(*args)

    monkeypatch.setattr(provider.closure, "publish", paused)
    task = asyncio.create_task(view.commit_all("late"))
    try:
        async with asyncio.timeout(15):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        async with asyncio.timeout(5):
            await provider.reconcile(write_context(provider, epoch=2), (stale_row(acquired, ctx),))
        assert not view.paths.payload.exists()
        assert provider.closure.is_closed(view.paths)
    finally:
        release.set()
    with pytest.raises(ContractViolation, match="permanently closed"):
        await task
    assert provider.closure.candidate(provider._candidate_ref(view)) is None


async def test_export_is_physically_read_only_after_capture(capture, monkeypatch):
    provider, _, acquired = capture
    view = acquired.resource
    run = provider.launcher.run
    observed = False

    async def probe(command, **kwargs):
        nonlocal observed
        if command[:2] == ("/usr/bin/git", "pack-objects"):
            observed = True
            command = (
                "/usr/bin/python3",
                "-I",
                "-c",
                """
import os
try:
    open('export-wrote', 'w').write('wrong authority')
except OSError:
    pass
else:
    raise SystemExit('export could mutate staging')
os.execv('/usr/bin/git', ['/usr/bin/git', 'pack-objects', '--stdout', '--revs'])
""",
            )
        return await run(command, **kwargs)

    # Instrument the production launch request; no OS operation or result is
    # mocked. A WRITE export makes the real filesystem mutation succeed.
    monkeypatch.setattr(type(provider.launcher), "run", lambda self, *a, **kw: probe(*a, **kw))
    try:
        candidate = await view.commit_all("read-only handoff")
    except ContractViolation as exc:
        pytest.fail(f"the handoff did not enforce its READ grant: {exc}")
    assert observed and candidate == view.base
    assert not Path(view.path, "export-wrote").exists()


async def test_detached_capture_writer_is_reaped_before_export_or_reset(capture):
    provider, _, acquired = capture
    view = acquired.resource
    hook = Path(view.path, ".git/hooks/pre-commit")
    hook.parent.mkdir()
    hook.write_text("""#!/usr/bin/python3
import os, signal
ready_r, ready_w = os.pipe()
if os.fork() == 0:
    os.close(ready_r)
    os.setsid()
    def finish(*args):
        open('writer-quiesced', 'w').write('TERM reached detached writer')
        os._exit(0)
    signal.signal(signal.SIGTERM, finish)
    os.write(ready_w, b'R')
    signal.pause()
else:
    os.close(ready_w)
    assert os.read(ready_r, 1) == b'R'
""")
    hook.chmod(0o700)
    Path(view.path, "candidate.txt").write_text("before hook")
    oid = await view.commit_all("detached writer")
    assert oid != view.base
    assert Path(view.path, "writer-quiesced").read_text() == "TERM reached detached writer"
    # The teardown write was not staged in the candidate. Host publication
    # preserves the captured commit, never invents a worktree-only replacement.
    absent = provider.authority._run("cat-file", "-e", f"{oid}:writer-quiesced", check=False)
    assert absent.returncode != 0
