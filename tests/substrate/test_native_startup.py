"""Pinned-release startup observations inside the unchanged networkless launcher."""

import hashlib
import json
import os
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from constructicon.core.identity import Digest
from constructicon.substrate.executors.linux import ProcessExchangeError
from tests.native_startup import BOOTSTRAP, MODELS, DuplexWire, configuration, initialize
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_linux_duplex import exchange
from tests.substrate.test_native_codex_mediation import fake_provider, write_evidence


@pytest.fixture
def startup_launcher(launcher):
    location = os.environ.get("M8_STARTUP_ROOT")
    if not location:
        if os.environ.get("M8_STARTUP_REQUIRED"):
            pytest.fail("required immutable native startup fixture missing")
        pytest.skip("native startup fixture not provisioned")
    root = Path(location)
    pinned = json.loads(root.with_suffix(".json").read_text())["runtime_digest"]
    return replace(launcher, runtime_root=root, expected_runtime=Digest(pinned))


async def observe(launcher, guard_root, model, *, files=None, extra="", arguments=(), query=None):
    observations = {}
    setup = {
        "config": configuration(model) + extra, "files": files or {},
        "arguments": list(arguments),
    }
    setup_bytes = (json.dumps(setup) + "\n").encode()
    probe = os.environ.get("PYTEST_CURRENT_TEST", "startup")
    observation_name = "codex-startup-observation-" + hashlib.sha256(
        probe.encode() + setup_bytes,
    ).hexdigest()[:16] + ".json"

    async def conversation(io):
        await io.write(setup_bytes)
        wire = DuplexWire(io)
        observations["warnings"] = wire.warnings
        observations["bootstrap"] = await wire.read()
        observations["initialize"] = await initialize(wire)
        observations["config"] = await wire.rpc("config/read", {
            "includeLayers": True, "cwd": "/tmp/native-startup",
        })
        if query is not None:
            await query(wire, observations)
    try:
        result = await exchange(
            launcher, guard_root, conversation,
            command=("/usr/bin/python3", "-I", BOOTSTRAP), timeout=20,
        )
    except ProcessExchangeError as exc:
        evidence(observation_name, launcher, observations, exc.result)
        raise
    evidence(observation_name, launcher, observations, result)
    return observations, result


def evidence(name, launcher, observations, result):
    if not os.environ.get("M8_EVIDENCE_DIRECTORY"):
        return
    write_evidence(name, {
        "launch_revision": str(launcher.revision),
        "observations": observations,
        "process": {**asdict(result), "stdout": result.stdout.hex(), "stderr": result.stderr.hex()},
        "scope": "startup only; no provider or durable native lifecycle qualification",
    })


@pytest.mark.parametrize("model", MODELS)
async def test_native_starts_with_private_configuration(startup_launcher, tmp_path, model):
    async def inventory(wire, observations):
        observations["skills"] = await wire.rpc("skills/list", {
            "cwds": ["/tmp/native-startup"], "forceReload": True,
        })
        observations["hooks"] = await wire.rpc("hooks/list", {"cwds": ["/tmp/native-startup"]})
        observations["requirements"] = await wire.rpc("configRequirements/read", {})

    observations, result = await observe(startup_launcher, tmp_path, model, query=inventory)
    evidence(f"codex-startup-{model}.json", startup_launcher, observations, result)
    assert result.returncode == result.payload_returncode == 0
    assert not result.timed_out and result.bound_exceeded is None
    assert observations["config"]["config"]["model"] == model
    assert all(observations["bootstrap"]["absent"].values())
    assert observations["bootstrap"]["bootstrap_environment"] == {
        "HOME": "/tmp/home", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PWD": "/tmp",
    }
    assert observations["config"]["layers"]
    assert [warning["params"] for warning in observations["warnings"]] == [{
        "details": None,
        "summary": (
            "Codex could not find bubblewrap on PATH. Install bubblewrap with your OS package "
            "manager. See the sandbox prerequisites: "
            "https://developers.openai.com/codex/concepts/sandboxing#prerequisites. "
            "Codex will use the bundled bubblewrap in the meantime."
        ),
    }]


async def test_ambient_environment_cannot_select_configuration(
    startup_launcher, monkeypatch, tmp_path,
):
    poisoned = tmp_path / "outside-home"
    poisoned.mkdir()
    (poisoned / "config.toml").write_text('model = "outside-startup-canary"\n')
    monkeypatch.setenv("CODEX_HOME", str(poisoned))
    monkeypatch.setenv("OPENAI_BASE_URL", "http://192.0.2.1:1/never")
    monkeypatch.setenv("CODEX_APP_SERVER_TEST_USER_CONFIG_FILE", str(poisoned / "config.toml"))
    observations, result = await observe(startup_launcher, tmp_path, MODELS[0])
    evidence("codex-startup-ambient.json", startup_launcher, observations, result)
    assert result.payload_returncode == 0 and not result.timed_out
    assert observations["config"]["config"]["model"] == MODELS[0]
    assert set(observations["bootstrap"]["bootstrap_environment"]) == {
        "HOME", "PATH", "LANG", "PWD",
    }
    assert "outside-startup-canary" not in json.dumps(observations)


async def test_explicit_session_configuration_is_a_positive_control(startup_launcher, tmp_path):
    observations, result = await observe(
        startup_launcher, tmp_path, MODELS[0], arguments=("-c", f'model="{MODELS[1]}"'),
    )
    evidence("codex-startup-session.json", startup_launcher, observations, result)
    assert result.payload_returncode == 0 and not result.timed_out
    assert observations["config"]["config"]["model"] == MODELS[1]


@pytest.mark.parametrize("extra", [
    "\nunknown_startup_feature = true\n", "\n[unknown_startup]\nx=1\n",
], ids=["feature", "table"])
async def test_unknown_configuration_refuses_before_native_rpc(startup_launcher, tmp_path, extra):
    with pytest.raises(ProcessExchangeError) as refused:
        await observe(startup_launcher, tmp_path, MODELS[0], extra=extra)
    result = refused.value.result
    evidence("codex-startup-strict-" + str(len(extra)) + ".json", startup_launcher, {}, result)
    assert result.payload_returncode != 0 and not result.timed_out
    assert "unknown_startup" in result.stderr.decode()


@pytest.mark.parametrize("root", ["/tmp/home/.codex/skills", "/tmp/native-startup/.agents/skills"])
async def test_skill_origin_has_a_native_positive_and_absent_control(
    startup_launcher, tmp_path, root,
):
    async def skills(wire, observations):
        observations["skills"] = await wire.rpc("skills/list", {
            "cwds": ["/tmp/native-startup"], "forceReload": True,
        })

    baseline, before = await observe(startup_launcher, tmp_path, MODELS[0], query=skills)
    marked, after = await observe(startup_launcher, tmp_path, MODELS[0], query=skills, files={
        root + "/startup-canary/SKILL.md": (
            "---\nname: startup-canary\ndescription: Inert startup discovery fixture.\n---\n"
            "Public inert marker. This fixture performs no operation.\n"
        ),
    })
    evidence("codex-startup-skill-" + ("user" if "home" in root else "project") + ".json",
             startup_launcher, {"baseline": baseline, "marked": marked}, after)
    assert before.payload_returncode == after.payload_returncode == 0
    assert "startup-canary" not in json.dumps(baseline["skills"])
    assert "startup-canary" in json.dumps(marked["skills"])


async def test_provider_connectivity_is_a_named_refusal(startup_launcher, tmp_path):
    async def turn(wire, observations):
        thread = await wire.rpc("thread/start", {
            "model": MODELS[0], "modelProvider": "probe", "cwd": "/tmp/native-startup",
            "approvalPolicy": "never", "sandbox": "danger-full-access", "ephemeral": True,
        })
        observations["thread"] = thread
        started = await wire.rpc("turn/start", {
            "threadId": thread["thread"]["id"],
            "input": [{"type": "text", "text": "Inert fixture: no provider exists on this route."}],
        })
        observations["started"] = started
        observations["turn_events"] = []
        while True:
            message = await wire.read()
            observations["turn_events"].append(message)
            assert "id" not in message, "no native operation is authorized by this probe"
            if message.get("method") == "turn/completed":
                assert message["params"]["threadId"] == thread["thread"]["id"]
                assert message["params"]["turn"]["id"] == started["turn"]["id"]
                observations["turn"] = message["params"]["turn"]
                break

    async with fake_provider("contained_python", {"program": "pass"}, model=MODELS[0]) as peer:
        endpoint, requests, failures = peer
        observations, result = await observe(
            startup_launcher, tmp_path, MODELS[0], query=turn,
            arguments=("-c", f'model_providers.probe.base_url="{endpoint}"'),
        )
        assert not requests and not failures
        assert endpoint in json.dumps(observations["turn"]["error"])
        observations["external_fixture"] = {"endpoint": endpoint, "requests": requests}
    evidence("codex-startup-provider-refusal.json", startup_launcher, observations, result)
    assert result.payload_returncode == 0 and not result.timed_out
    assert observations["turn"]["status"] == "failed"
    assert observations["turn"]["error"]
