"""Actual maintenance entry with real Git, capture, journal and fixed exam."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sys
from argparse import Namespace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.api import _maintenance_identity as identity_module
from constructicon.api import _maintenance_source as source_module
from constructicon.api import maintenance_entry as entry
from constructicon.api.plan_manifest_application import maintenance_graph
from constructicon.core.envelope import utc_now
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorGrantPolicy
from constructicon.core.identity import digest
from constructicon.core.maintenance import MaintenanceAttemptAuthorization, MaintenanceCapabilityPin
from constructicon.core.manifest import source_graph_hash_for
from constructicon.core.run import RunStatus
from constructicon.substrate.executors.codex_host import WRITE_GRANTS
from constructicon.substrate.executors.linux import ProcessLimits
from constructicon.substrate.git.process import GitProcess
from tests.api import test_plan_manifest_application as application_tests
from tests.executorworld import launch_identity
from tests.substrate.test_codex_adapter import portable_binding as portable_binding

concrete_application = application_tests.concrete_application

AUTHORIZATION_LAW_CHANGES = (
    ("core/maintenance.py", b"type(epoch) is int and epoch == 1",
     b"type(epoch) is int and epoch <= 2"),
    ("substrate/executors/maintenance.py", b"record = parse_json_value(",
     b"record = dict("),
    ("substrate/executors/qualification.py", b"info.st_nlink != 1", b"info.st_nlink > 2"),
)


def change_authorization_law(monkeypatch, relative_path, before, after):
    target = (Path(identity_module.__file__).parents[1] / relative_path).resolve()
    original = Path.read_bytes
    raw = original(target)
    assert raw.count(before) == 1

    def read(path):
        if path.resolve() == target:
            return raw.replace(before, after, 1)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)


@pytest.mark.parametrize(("relative_path", "before", "after"), AUTHORIZATION_LAW_CHANGES,
                         ids=("core-law", "maintenance-reader", "root-custody-reader"))
def test_application_revision_pins_each_authorization_law(
    monkeypatch, relative_path, before, after,
):
    original = entry.maintenance_application_revision()
    change_authorization_law(monkeypatch, relative_path, before, after)
    assert entry.maintenance_application_revision() != original


def authorize(resources, executor):
    profile = executor.executor.profile.model_copy(update={
        "accepted_efforts": frozenset({WRITE_GRANTS.effort}),
        "grant_policy": ExecutorGrantPolicy(tool_sets=(("contained_python",),),
            network_modes=("allow",), network_access="none", environment_names=(),
            workspace_required=True),
    })
    executor.executor.profile = profile
    executor._identity = launch_identity(profile)
    graph = maintenance_graph(executor_id="executor", workspace_id=resources.workspace.provider_id,
        gate_id=resources.gate.provider_id, writer_grants=WRITE_GRANTS)
    auth = MaintenanceAttemptAuthorization(authorization_id="entry-double",
        actor_id="operator:test",
        idempotency_key="maintenance", scope=entry.WRITER_SCOPE, binding="executor",
        source_graph_hash=source_graph_hash_for(graph), capability_id="executor",
        revision=str(executor.identity.revision),
        operator_binding_digest=digest("fake-binding", 1, 0),
        journal=str(Path(resources.journal._db_path).resolve()), max_epoch=1,
        not_after=utc_now() + timedelta(hours=1), grants=WRITE_GRANTS,
        attempt_record=str(Path(resources.journal._db_path).resolve().parent / "attempt.json"),
        request=resources.request, application_revision=entry.maintenance_application_revision(),
        workspace=MaintenanceCapabilityPin(capability_id=resources.workspace.provider_id,
                                          revision=resources.workspace.revision),
        gate=MaintenanceCapabilityPin(capability_id=resources.gate.provider_id,
                                     revision=resources.gate.revision))
    executor.maintenance = auth
    return auth


async def test_real_entry_accepts_publishes_after_join_and_replays(
    concrete_application, monkeypatch,
):
    resources, executor, _system, control, _launch = concrete_application
    await control.shutdown()
    auth = authorize(resources, executor)
    original = entry.derive_maintenance_result
    shutdowns = []
    original_shutdown = entry.ControlPlane.shutdown

    async def shutdown(self):
        await original_shutdown(self)
        shutdowns.append(True)

    async def derive(*args):
        assert shutdowns, "accepted evidence cannot precede joined shutdown"
        return await original(*args)

    monkeypatch.setattr(entry.ControlPlane, "shutdown", shutdown)
    monkeypatch.setattr(entry, "derive_maintenance_result", derive)
    first = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth)
    assert first is not None and first.evaluation.ok
    assert resources.journal.run_state(auth.run_id).status is RunStatus.SUCCEEDED
    assert all(row.state == "closed" for row in resources.journal.capability_leases(auth.run_id))
    path = Path(auth.journal).parent / "maintenance-result.json"
    before = path.read_bytes()
    second = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth)
    assert second == first and len(executor.executor.calls) == 1
    assert path.read_bytes() == before
    assert entry.inspect_result(path)["meaning"] == "historical-application-acceptance"
    assert "repository" not in json.dumps(entry.inspect_result(path))


@pytest.mark.parametrize("concrete_application", ["committed-tree"], indirect=True)
@pytest.mark.parametrize("change", [True, False], ids=["contribution", "successful-noop"])
async def test_full_tree_entry_mediates_callback_and_runs_retained_consumer(
    concrete_application, portable_binding, tmp_path, monkeypatch, change,
):
    from tests.maintenance_task_world import exercise_task_entry

    resources, _executor, _system, control, launch = concrete_application
    await control.shutdown()
    await exercise_task_entry(resources, launch, portable_binding, tmp_path, monkeypatch,
                              change=change)


@pytest.mark.parametrize("contribution_exists", [False, True])
async def test_task_fixture_preserves_inventory_when_contribution_exists(
    tmp_path, contribution_exists,
):
    from constructicon.substrate.git.authority import GitAuthority
    from tests.gitworld import seed_authority
    from tests.maintenance_task_world import import_fixture_tree

    files = {"retained.txt": "unchanged\n", "tests/retained.txt": "also unchanged\n"}
    if contribution_exists:
        files["tests/vectors/plan_manifest.json"] = "old contribution\n"
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = GitAuthority(seed_authority(source_root), source_root / "workspaces")
    source._run("read-tree", "--empty")
    for name, content in files.items():
        oid = source._run("hash-object", "-w", "--stdin", input_text=content).stdout.strip()
        source._run("update-index", "--add", "--cacheinfo", f"100644,{oid},{name}")
    tree = source._run("write-tree").stdout.strip()
    commit = source._run("commit-tree", tree, input_text="inventory fixture\n").stdout.strip()
    source._run("update-ref", "refs/heads/main", commit)
    source_base = source.resolve_ref("refs/heads/main")
    source_tree = source.tree_of(source_base).encode()
    destination_root = tmp_path / "destination"
    destination_root.mkdir()
    destination = GitAuthority(seed_authority(destination_root), destination_root / "workspaces")
    base = await import_fixture_tree(destination, Path(source.repository_id), source_tree)
    assert destination.parents_of(base) == ()
    assert source.resolve_ref("refs/heads/main") == source_base
    assert source.tree_of(source_base).encode() == source_tree


async def test_task_fixture_trusts_only_its_exact_checkout_for_git_reads(tmp_path, monkeypatch):
    from constructicon.substrate.git import process as process_module
    from constructicon.substrate.git.authority import GitAuthority
    from tests.gitworld import seed_authority
    from tests.maintenance_task_world import import_fixture_tree

    repositories = []
    for name in ("checkout", "unrelated", "authority"):
        root = tmp_path / name
        root.mkdir()
        repositories.append(GitAuthority(seed_authority(root), root / "workspaces"))
    checkout, unrelated, authority = repositories
    tree = checkout.tree_of(checkout.resolve_ref("refs/heads/main")).encode()
    real_spawn = asyncio.create_subprocess_exec

    async def different_owner(*args, **kwargs):
        if Path(kwargs["cwd"]) in {Path(checkout.repository_id), Path(unrelated.repository_id)}:
            kwargs["env"] = {**kwargs["env"], "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}
        return await real_spawn(*args, **kwargs)

    monkeypatch.setattr(process_module.asyncio, "create_subprocess_exec", different_owner)
    git = GitProcess(authority.git_executable, ProcessLimits())
    with pytest.raises(ContractViolation, match="dubious ownership"):
        await git.run("rev-parse", "HEAD", cwd=checkout.repository_id)
    base = await import_fixture_tree(authority, Path(checkout.repository_id), tree)
    assert authority.tree_of(base).encode() == tree
    with pytest.raises(ContractViolation, match="dubious ownership"):
        await git.run("-c", f"safe.directory={Path(checkout.repository_id).as_posix()}",
                      "rev-parse", "HEAD", cwd=unrelated.repository_id)


@pytest.mark.parametrize(("relative_path", "before", "after"), AUTHORIZATION_LAW_CHANGES,
                         ids=("core-law", "maintenance-reader", "root-custody-reader"))
async def test_changed_authorization_law_refuses_old_authority_before_startup(
    concrete_application, monkeypatch, relative_path, before, after,
):
    resources, executor, _system, control, _launch = concrete_application
    await control.shutdown()
    authorization = authorize(resources, executor)
    descriptor = executor.descriptor("executor")
    change_authorization_law(monkeypatch, relative_path, before, after)
    entered = []

    async def forbidden(*args, **kwargs):
        entered.append(True)
        pytest.fail("changed authorization law reached startup or acquisition")

    monkeypatch.setattr(entry.ControlPlane, "startup", forbidden)
    monkeypatch.setattr(executor, "acquire", forbidden)
    with pytest.raises(ContractViolation, match="assembled resources"):
        await entry.run_maintenance(resources=resources, executor=executor,
            executor_descriptor=descriptor, authorization=authorization)
    assert entered == [] and executor.executor.calls == []
    assert resources.journal.run_state(authorization.run_id) is None
    assert not Path(authorization.attempt_record).exists()
    matching = authorization.model_copy(update={
        "application_revision": entry.maintenance_application_revision(),
    })
    executor.maintenance = matching
    await entry.require_maintenance_attempt(resources, executor, descriptor, matching)
    assert entered == [] and not Path(authorization.attempt_record).exists()


@pytest.mark.parametrize("changed", ["request", "graph", "workspace", "gate", "application",
                                     "journal", "executor"])
async def test_entry_refuses_mismatched_authority_before_startup(
    concrete_application, monkeypatch, changed,
):
    resources, executor, _system, control, _launch = concrete_application
    await control.shutdown()
    auth = authorize(resources, executor)
    if changed == "request":
        updates = {"request": auth.request.model_copy(update={"target_sha256": "0" * 64})}
    elif changed == "graph":
        updates = {"source_graph_hash": digest("foreign", 1, 0)}
    elif changed in {"workspace", "gate"}:
        updates = {changed: getattr(auth, changed).model_copy(update={
            "revision": digest("foreign", 1, 0)})}
    elif changed == "application":
        updates = {"application_revision": digest("foreign", 1, 0)}
    elif changed == "journal":
        updates = {"journal": str(Path(auth.journal).parent / "foreign.sqlite")}
    else:
        updates = {"revision": str(digest("foreign", 1, 0))}
    auth = auth.model_copy(update=updates)
    executor.maintenance = auth
    started = []

    async def startup(self):
        started.append(True)
        raise AssertionError("mismatched authority reached recovery")

    monkeypatch.setattr(entry.ControlPlane, "startup", startup)
    with pytest.raises(ContractViolation):
        await entry.run_maintenance(resources=resources, executor=executor,
            executor_descriptor=executor.descriptor("executor"), authorization=auth)
    assert started == [] and executor.executor.calls == []


async def test_inspect_never_assembles_recovers_or_writes(concrete_application, monkeypatch):
    resources, executor, _system, control, _launch = concrete_application
    await control.shutdown()
    auth = authorize(resources, executor)
    await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth)
    path = Path(auth.journal).parent / "maintenance-result.json"
    before = {p: p.read_bytes() for p in path.parent.rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        pytest.fail("read-only inspection reached assembly or constructor")

    for name in ("SqliteJournal", "GitAuthority", "assemble_maintenance", "run_maintenance"):
        monkeypatch.setattr(entry, name, forbidden)
    observed = await entry._command(Namespace(command="inspect", result=path))
    assert observed["input_sha256"] and observed["render_sha256"]
    assert len(json.dumps(observed).encode()) < 1024
    assert before == {p: p.read_bytes() for p in path.parent.rglob("*") if p.is_file()}
    raw = path.read_bytes()
    path.write_bytes(b'{"schema_version":1,' + raw[1:])
    with pytest.raises(ValueError, match="repeats key"):
        entry.inspect_result(path)
    path.write_bytes(b" " * (entry.MAX_RESULT_BYTES + 1))
    with pytest.raises(ContractViolation, match="bounded"):
        entry.inspect_result(path)


@pytest.mark.parametrize("field", ["run_id", "candidate.commit"])
def test_inspect_refuses_unbounded_or_private_text_identifiers(tmp_path, field):
    record = {"schema_version": 1, "meaning": "historical-application-acceptance",
        "authorization_digest": str(digest("historical-artifact", 1, 0)), "result": {
            "run_id": "run-" + "a" * 32,
            "candidate": {"repository": "private-path", "commit": "b" * 40},
            "evaluation": {"subject": None, "checks": [], "attestation_id": None},
            "input_sha256": "c" * 64, "render_sha256": "d" * 64,
        }}
    if field == "run_id":
        record["result"]["run_id"] = "private-text/" * 1000
    else:
        record["result"]["candidate"]["commit"] = "private-text/" * 1000
    # The underlying application contract deliberately carries nominal strings;
    # the public inspector must independently enforce its finite identifier shape.
    entry._StoredResult.model_validate(record)
    path = tmp_path / "historical.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    assert path.stat().st_size < entry.MAX_RESULT_BYTES
    refused = False
    try:
        entry.inspect_result(path)
    except ContractViolation:
        refused = True
    assert refused, "arbitrary stored strings must not become public identities"


def test_reviewed_consumer_hashes_match_fixed_bytes():
    root = Path(__file__).resolve().parents[2]
    assert set(source_module.SOURCE_HASHES) == set(source_module.SOURCE_FILES)
    assert all(hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
               == expected
               for name, expected in source_module.SOURCE_HASHES.items())


async def test_prepare_checks_digest_before_git_or_root_creation(tmp_path, monkeypatch):
    bundle = tmp_path / "reviewed.bundle"
    bundle.write_bytes(b"not the reviewed bytes")
    root = tmp_path / "fresh"
    called = []

    async def forbidden(*args):
        called.append(True)
        pytest.fail("unreviewed bundle reached Git")

    monkeypatch.setattr(source_module, "git", forbidden)
    with pytest.raises(ContractViolation, match="digest"):
        await source_module.prepare_source(root, bundle, bundle_sha256="0" * 64,
            base_commit="a" * 40, target_ref="refs/heads/maintenance")
    assert not root.exists() and called == []


async def test_prepare_accepts_only_new_reviewed_bundle_and_affirms_consumer(tmp_path, monkeypatch):
    repository = Path(__file__).resolve().parents[2]
    seed = tmp_path / "reviewed-source.git"
    seed.mkdir()
    await source_module.git(seed, "init", "--bare", "--template=", ".")
    commit = (b"commit refs/heads/reviewed\n"
              b"committer test <test@example.invalid> 1767225600 +0000\ndata 1\nx\n")
    for name in source_module.SOURCE_FILES:
        blob = await source_module.git(repository, "show", "HEAD:" + name)
        commit += f"M 100644 inline {name}\ndata {len(blob)}\n".encode() + blob + b"\n"
    commit += b"\ndone\n"
    await GitProcess(str(Path(shutil.which("git")).resolve()), ProcessLimits()).run(
        "fast-import", "--quiet", cwd=seed, stdin=commit,
    )
    bundle = tmp_path / "reviewed.bundle"
    await source_module.git(seed, "bundle", "create", str(bundle), "refs/heads/reviewed")
    base = (await source_module.git(seed, "rev-parse", "refs/heads/reviewed")).strip().decode()
    root = tmp_path / "maintenance"

    def portable_custody(path):
        # Substitute only POSIX ownership/mode predicate, retaining exact paths.
        assert path.is_absolute() and path.resolve() == path and path.is_dir()
        assert path.resolve().is_relative_to(tmp_path.resolve())

    monkeypatch.setattr(source_module, "private_root", portable_custody)
    initializations = []
    original_git = source_module.git

    async def observed_git(repo, *args):
        if repo == root / "authority.git" and args[:1] == ("init",):
            initializations.append(args)
        return await original_git(repo, *args)

    monkeypatch.setattr(source_module, "git", observed_git)
    pin = source_module.SourcePin.model_validate(await entry._command(Namespace(
        command="prepare", root=root, bundle=bundle,
        bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
        base=base, target_ref="refs/heads/maintenance")))
    assert initializations == [(
        "init", "--bare", "--shared=0600", "--template=", "--object-format=sha1", ".",
    )]
    assert (root / "authority.git/config").read_bytes() == source_module.CONFIG
    assert await source_module.inspect_source(root) == pin
    assert pin.sources == source_module.SOURCE_HASHES
    old_config = source_module.CONFIG.replace(b"\tsharedRepository = 0600\n", b"")
    (root / "authority.git/config").write_bytes(old_config)
    old_pin = pin.model_copy(update={
        "config_sha256": hashlib.sha256(old_config).hexdigest(),
    })
    (root / "source-pin.json").write_bytes(old_pin.model_dump_json().encode())
    with pytest.raises(ContractViolation) as legacy:
        await source_module.inspect_source(root)
    assert str(legacy.value) == "maintenance authority configuration differs"
    (root / "authority.git/config").write_bytes(source_module.CONFIG)
    (root / "source-pin.json").write_bytes(pin.model_dump_json().encode())
    assert await source_module.inspect_source(root) == pin
    with pytest.raises(ContractViolation, match="fresh"):
        await source_module.prepare_source(root, bundle, bundle_sha256=pin.bundle_sha256,
            base_commit=base, target_ref=pin.target_ref)
    (root / "authority.git/config").write_bytes(source_module.CONFIG + b"[alias]\n\tx = !exit 0\n")
    refused = False
    try:
        await source_module.inspect_source(root)
    except ContractViolation as error:
        assert "configuration" in str(error)
        refused = True
    assert refused, "unreviewed configuration must refuse"
    (root / "authority.git/config").write_bytes(source_module.CONFIG)
    for name in ("hooks/foreign", "info/grafts", "objects/info/alternates"):
        path = root / "authority.git" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"unreviewed")
        with pytest.raises(ContractViolation):
            await source_module.inspect_source(root)
        path.unlink()
    replace = root / "authority.git/refs/replace"
    replace.mkdir()
    with pytest.raises(ContractViolation, match="ancestry"):
        await source_module.inspect_source(root)
    replace.rmdir()
    sentinel = root / "sentinel"
    sentinel.write_bytes(b"read-only sentinel")
    os.link(sentinel, root / "maintenance.sqlite")
    def forbidden_constructor(*args, **kwargs):
        pytest.fail("aliased journal reached the SQLite constructor")
    monkeypatch.setattr(entry, "SqliteJournal", forbidden_constructor)
    with pytest.raises(entry._CommandFailure) as refusal:
        await entry._command(Namespace(command="preflight", root=root))
    assert refusal.value.stage is entry._PreflightStage.SOURCE
    assert isinstance(refusal.value.__cause__, ContractViolation)
    assert "redirected" in str(refusal.value.__cause__)
    assert sentinel.read_bytes() == b"read-only sentinel"
    (root / "maintenance.sqlite").unlink()
    pin_path = root / "source-pin.json"
    pin_path.write_bytes(b'{"schema_version":1,' + pin_path.read_bytes()[1:])
    async def forbidden_git(*args):
        pytest.fail("contradictory source pin reached Git")
    monkeypatch.setattr(source_module, "git", forbidden_git)
    with pytest.raises(ValueError, match="repeats key"):
        await source_module.inspect_source(root)


async def test_maintenance_git_requests_private_child_creation_without_global_mask(
    tmp_path, monkeypatch,
):
    calls = []

    class Child:
        def __init__(self, *args):
            pass

        async def run(self, *args, **kwargs):
            calls.append((args, kwargs))
            return b"checked"

    monkeypatch.setattr(source_module, "GitProcess", Child)
    assert await source_module.git(tmp_path, "rev-parse", "HEAD") == b"checked"
    assert calls == [(("rev-parse", "HEAD"), {"cwd": tmp_path, "creation_mask": 0o077})]
    assert b"\tsharedRepository = 0600\n" in source_module.CONFIG
    assert "os.umask(" not in Path(source_module.__file__).read_text(encoding="utf-8")


@pytest.mark.parametrize("stage", ("source", "assembly", "preview", "unknown"))
def test_cli_preflight_failure_publishes_only_actual_bounded_stage(
    tmp_path, monkeypatch, capsys, stage,
):
    calls = []
    sentinel = "PRIVATE:/credential/path:SUBPROCESS-TEXT"

    async def source(root):
        calls.append("source")
        if stage == "source":
            raise ContractViolation(sentinel)

    def journal(path):
        calls.append("journal")
        return None

    async def assemble(**kwargs):
        calls.append("assembly")
        if stage == "assembly":
            raise RuntimeError(sentinel)
        return SimpleNamespace(executor=SimpleNamespace(identity=SimpleNamespace(
            revision="sha256:" + "0" * 64, store=SimpleNamespace(
                operator_binding_digest="sha256:" + "0" * 64))),
            resources=SimpleNamespace(request=None,
                workspace=SimpleNamespace(revision="sha256:" + "0" * 64),
                gate=SimpleNamespace(revision="sha256:" + "0" * 64)))

    def preview(**kwargs):
        calls.append("preview")
        raise ValueError(sentinel)

    async def unknown(args):
        calls.append("unknown")
        raise OSError(sentinel)

    monkeypatch.setattr(entry, "inspect_source", source)
    monkeypatch.setattr(entry, "SqliteJournal", journal)
    monkeypatch.setattr(entry, "assemble_maintenance", assemble)
    monkeypatch.setattr(entry, "MaintenanceAttemptAuthorization", preview)
    if stage == "unknown":
        monkeypatch.setattr(entry, "_command", unknown)
    argv = ["maintenance-entry", "preflight"]
    for name in ("root", "session", "sealed", "qualification", "state", "launch-root"):
        argv.extend(("--" + name, str(tmp_path)))
    argv.extend(("--store-key", "fake", "--authorization-id", "fake",
                 "--actor", "operator:test", "--key", "fake"))
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exit:
        entry.main()
    captured = capsys.readouterr()
    assert exit.value.code == 1 and captured.err == ""
    assert json.loads(captured.out) == {
        "accepted": False, "error": "maintenance command refused or incomplete", "stage": stage,
    }
    expected = {"source": ["source"], "assembly": ["source", "journal", "assembly"],
                "preview": ["source", "journal", "assembly", "preview"], "unknown": ["unknown"]}
    assert calls == expected[stage]
    assert sentinel not in captured.out and len(captured.out.encode()) <= 128


@pytest.mark.parametrize("command", ("prepare", "run", "inspect"))
def test_other_cli_failure_bytes_remain_unchanged(tmp_path, monkeypatch, capsys, command):
    async def refused(args):
        raise entry._CommandFailure(entry._PreflightStage.SOURCE)

    monkeypatch.setattr(entry, "_command", refused)
    argv = ["maintenance-entry", command]
    if command == "inspect":
        argv.extend(("--result", str(tmp_path)))
    elif command == "prepare":
        argv.extend(("--root", str(tmp_path), "--bundle", str(tmp_path),
                     "--bundle-sha256", "0" * 64, "--base", "0" * 40))
    else:
        for name in ("root", "session", "sealed", "qualification", "state", "launch-root"):
            argv.extend(("--" + name, str(tmp_path)))
        argv.extend(("--store-key", "fake", "--authorization", str(tmp_path)))
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exit:
        entry.main()
    captured = capsys.readouterr()
    assert exit.value.code == 1 and captured.err == ""
    assert captured.out == (
        '{"accepted":false,"error":"maintenance command refused or incomplete"}\n'
    )


async def test_retained_run_inputs_and_manifest_are_checked_before_startup(
    concrete_application, monkeypatch,
):
    resources, executor, _system, control, _launcher = concrete_application
    await control.shutdown()
    auth = authorize(resources, executor)
    result = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth)
    assert result is not None
    record = resources.journal.run_record(auth.run_id)
    manifest_hash = resources.journal.run_manifest_hash(auth.run_id)
    raw = resources.journal.load_manifest_json(manifest_hash)
    for change in ("foreign-run", "inputs", "manifest"):
        with monkeypatch.context() as scoped:
            started = []
            async def forbidden_startup(self, started=started):
                started.append(True)
                raise AssertionError("foreign retained world reached recovery")
            scoped.setattr(entry.ControlPlane, "startup", forbidden_startup)
            if change == "foreign-run":
                scoped.setattr(resources.journal, "run_records", lambda **kwargs: (
                    record.model_copy(update={"run_id": "run-foreign"}),))
                scoped.setattr(resources.journal, "run_manifest_hash", lambda run_id: manifest_hash)
                scoped.setattr(resources.journal, "run_inputs", lambda run_id: {
                    "request": auth.request.model_dump(mode="json")})
            elif change == "inputs":
                scoped.setattr(resources.journal, "run_inputs", lambda run_id: {"request": {
                    **auth.request.model_dump(mode="json"), "target_sha256": "0" * 64}})
            else:
                payload = json.loads(raw)
                payload["capability_bindings"][0]["revision"] = str(digest("foreign", 1, 0))
                scoped.setattr(resources.journal, "load_manifest_json",
                               lambda hash_, payload=payload: json.dumps(payload))
            with pytest.raises((ContractViolation, ValueError)):
                await entry.run_maintenance(resources=resources, executor=executor,
                    executor_descriptor=executor.descriptor("executor"), authorization=auth)
            assert started == [] and len(executor.executor.calls) == 1


async def test_unavailable_qualification_cannot_authorize_application_assembly(
    concrete_application,
):
    resources, executor, _system, _control, _launcher = concrete_application
    graph = maintenance_graph(executor_id="executor", workspace_id=resources.workspace.provider_id,
        gate_id=resources.gate.provider_id, writer_grants=WRITE_GRANTS)
    executor.qualified_graph = source_graph_hash_for(graph)
    executor._unavailable_reasons = ("qualification only",)
    # Authorizing the graph through N5's shared admission question is insufficient
    # at the application assembly boundary: this is a distinct named purpose.
    with pytest.raises(ContractViolation, match="available, exact leased executor"):
        await entry.maintenance_system(resources, executor_id="executor", executor=executor,
            executor_descriptor=executor.descriptor("executor"), writer_grants=WRITE_GRANTS)


async def test_unavailable_application_assembly_requires_exact_companion_and_request_pins(
    concrete_application,
):
    resources, executor, _system, _control, _launcher = concrete_application
    auth = authorize(resources, executor)
    executor.qualified_graph = auth.source_graph_hash
    executor._unavailable_reasons = ("not generally available",)
    system = await entry.maintenance_system(resources, executor_id="executor", executor=executor,
        executor_descriptor=executor.descriptor("executor"), writer_grants=WRITE_GRANTS)
    capability = next(item for item in system.describe().capabilities
                      if item.capability_id == "executor")
    assert capability.available is False and capability.unavailable_reasons
    for field in ("request", "application_revision", "workspace", "gate"):
        if field == "request":
            updates = {field: auth.request.model_copy(update={"target_sha256": "0" * 64})}
        elif field == "application_revision":
            updates = {field: digest("foreign-application", 1, 0)}
        else:
            updates = {field: getattr(auth, field).model_copy(update={
                "revision": digest("foreign-companion", 1, 0)})}
        executor.maintenance = auth.model_copy(update=updates)
        refused = False
        try:
            await entry.maintenance_system(resources, executor_id="executor", executor=executor,
                executor_descriptor=executor.descriptor("executor"), writer_grants=WRITE_GRANTS)
        except ContractViolation:
            refused = True
        assert refused, f"unavailable application assembly must check its {field} pin"


async def test_cli_preflight_never_runs_and_run_delegates_exact_installed_authority(
    concrete_application, monkeypatch,
):
    resources, executor, _system, control, _launcher = concrete_application
    await control.shutdown()
    root = Path(resources.journal._db_path).resolve().parent
    authorization = authorize(resources, executor)
    assembled = entry.MaintenanceAssembly(resources, SimpleNamespace(identity=SimpleNamespace(
        revision=executor.identity.revision, store=SimpleNamespace(
            operator_binding_digest=authorization.operator_binding_digest))),
        executor.descriptor(entry.EXECUTOR))
    assemblies, executions = [], []

    async def inspect_source(path):
        assert path == root

    async def assemble(**kwargs):
        assemblies.append(kwargs["authorization"])
        return assembled

    async def run(**kwargs):
        executions.append(kwargs)
        return None

    monkeypatch.setattr(entry, "inspect_source", inspect_source)
    monkeypatch.setattr(entry, "assemble_maintenance", assemble)
    monkeypatch.setattr(entry, "SqliteJournal", lambda path: resources.journal)
    monkeypatch.setattr(entry, "run_maintenance", run)
    args = Namespace(command="preflight", root=root, session=root, store_key="fake-key",
        sealed=root, qualification=root, state=root, launch_root=root,
        authorization_id="owner-review", actor="operator:test", key="one-attempt")
    preview = await entry._command(args)
    installed = MaintenanceAttemptAuthorization.model_validate(preview)
    assert assemblies == [None] and executions == []
    assert installed.request == resources.request and installed.max_epoch == 1
    assert installed.source_graph_hash == source_graph_hash_for(maintenance_graph(
        executor_id=entry.EXECUTOR, workspace_id=entry.WORKSPACE,
        gate_id=entry.GATE, writer_grants=WRITE_GRANTS))
    reads = []
    def read(path):
        reads.append(path)
        return installed
    monkeypatch.setattr(entry, "read_maintenance_authorization", read)
    args.command, args.authorization = "run", root / "root-installed-authority.json"
    result = await entry._command(args)
    assert result == {"accepted": False, "run_id": str(installed.run_id)}
    assert reads == [args.authorization] and assemblies == [None, installed]
    assert len(executions) == 1 and executions[0]["authorization"] == installed
    huge = installed.model_copy(update={
        "journal": "/" + "j" * 4095, "attempt_record": "/" + "a" * 4095,
        "request": installed.request.model_copy(update={"repository": "r" * 4096}),
    })
    assert len(json.dumps(huge.model_dump(mode="json")).encode()) > entry.MAX_AUTHORIZATION_BYTES
    refused = False
    try:
        entry._authorization_preview(huge)
    except ContractViolation:
        refused = True
    assert refused, "an installable authorization must fit its root-owned reader"
    boundary = installed
    remaining = entry.MAX_AUTHORIZATION_BYTES - 1 - len(json.dumps(
        boundary.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
    ).encode())
    for field in ("journal", "attempt_record"):
        value = getattr(boundary, field)
        added = min(4096 - len(value), remaining)
        boundary = boundary.model_copy(update={field: value + "x" * added})
        remaining -= added
    assert remaining == 0
    MaintenanceAttemptAuthorization.model_validate_json(boundary.model_dump_json())
    preview = entry._authorization_preview(boundary)
    assert len(json.dumps(preview, sort_keys=True, separators=(",", ":")).encode()) + 1 \
        == entry.MAX_AUTHORIZATION_BYTES
    assert len(boundary.attempt_record) < 4096
    too_large = boundary.model_copy(update={"attempt_record": boundary.attempt_record + "x"})
    refused = False
    try:
        entry._authorization_preview(too_large)
    except ContractViolation:
        refused = True
    assert refused, "the printed LF is part of the root-owned authorization file"


async def test_real_entry_recovers_checker_checkpoint_without_second_writer(
    concrete_application, monkeypatch,
):
    resources, executor, _system, control, launcher = concrete_application
    await control.shutdown()
    auth = authorize(resources, executor)
    started = asyncio.Event()
    allowed = asyncio.Event()
    original_run = launcher.run

    async def run(command, **kwargs):
        if "expected_hash=" in " ".join(command):
            started.set()
            await allowed.wait()
        return await original_run(command, **kwargs)

    monkeypatch.setattr(launcher, "run", run)
    first = asyncio.create_task(entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth))
    try:
        async with asyncio.timeout(60):
            await started.wait()
    except BaseException:
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        raise
    assert len(executor.executor.calls) == 1
    assert resources.journal.run_state(auth.run_id).status is RunStatus.RUNNING
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not (Path(auth.journal).parent / "maintenance-result.json").exists()
    allowed.set()
    # Any second writer acquisition is rejected affirmatively, not inferred
    # from a terminal result. The real durable writer checkpoint must carry it.
    async def no_second_acquire(context):
        pytest.fail("checker-only recovery attempted another writer acquisition")

    monkeypatch.setattr(executor, "acquire", no_second_acquire)
    result = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth)
    assert result is not None and result.evaluation.ok and len(executor.executor.calls) == 1


async def test_real_entry_uncertain_writer_has_no_second_authorized_epoch(concrete_application):
    resources, executor, _system, control, _launcher = concrete_application
    await control.shutdown()
    auth = authorize(resources, executor)
    dispatched = asyncio.Event()
    original_acquire = executor.acquire
    epochs = []

    async def acquire(context):
        epoch = context.run_lease.epoch
        epochs.append(epoch)
        if epoch != auth.max_epoch:
            raise ContractViolation("maintenance double refuses a second authorized epoch")
        return await original_acquire(context)

    async def execute(task, **kwargs):
        executor.executor.calls.append(task)
        dispatched.set()
        await asyncio.Event().wait()

    executor.acquire, executor.executor.execute = acquire, execute
    first = asyncio.create_task(entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth))
    try:
        async with asyncio.timeout(60):
            await dispatched.wait()
    finally:
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
    assert dispatched.is_set() and len(executor.executor.calls) == 1
    assert resources.journal.run_state(auth.run_id).status is RunStatus.RUNNING
    result = await entry.run_maintenance(resources=resources, executor=executor,
        executor_descriptor=executor.descriptor("executor"), authorization=auth)
    assert result is None and epochs == [1, 2] and len(executor.executor.calls) == 1
    assert resources.journal.run_state(auth.run_id).status is RunStatus.FAILED
    assert not (Path(auth.journal).parent / "maintenance-result.json").exists()
