"""Finite startup-origin controls in the same owned, credential-free fixture."""

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest

from tests.native_codex_probe import PROBE_PROMPT, conversation
from tests.native_combined import (
    BASE_INSTRUCTIONS,
    CombinedScenario,
    assert_native_identity,
    controlled_configuration,
)
from tests.native_startup import MODELS
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_startup import assert_outcome
from tests.substrate.test_provider_placement import observe, placement
from tests.substrate.test_provider_placement import placement_image as placement_image

CWD = "/tmp/native-startup"
HOME_CONFIG = "/tmp/home/.codex"
MARKER = CWD + "/extension-marker"


def inert_mcp():
    return (
        "import json,sys; from pathlib import Path\n"
        f"Path({MARKER!r}).write_text('started')\n"
        "for line in sys.stdin:\n"
        " request=json.loads(line)\n"
        " if 'id' not in request: continue\n"
        " result={'protocolVersion':'2025-03-26','capabilities':{'tools':{}},"
        "'serverInfo':{'name':'inert-fixture','version':'0'}}\n"
        " if request['method']=='tools/list': result={'tools':[]}\n"
        " print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)\n"
    )


async def measure(image, guard_root, model, *, files=None, config=None, mcp=False, plugins=False):
    now = datetime.now(UTC)
    dates = tuple(dict.fromkeys([
        now.date().isoformat(), (now + timedelta(seconds=20)).date().isoformat(),
    ]))
    scenario = CombinedScenario(model, dates, "exec_command", {"cmd": "true"},
                                "unsupported call: exec_command", mcp=mcp, plugins=plugins)

    async def no_worker(_program):
        raise AssertionError("startup control must not dispatch a worker")

    async def query(wire, record):
        record["placement"] = (await wire.read())["placement"]
        record["bootstrap"] = await wire.read()

        async def inventory(wire):
            record["config"] = await wire.rpc("config/read", {"includeLayers": True, "cwd": CWD})
            record["requirements"] = await wire.rpc("configRequirements/read", {})
            record["account"] = await wire.rpc("account/read", {"refreshToken": False})
            record["skills"] = await wire.rpc("skills/list", {"cwds": [CWD], "forceReload": True})
            record["hooks"] = await wire.rpc("hooks/list", {"cwds": [CWD]})
            record["plugins"] = await wire.rpc("plugin/list", {
                "cwds": [CWD], "marketplaceKinds": ["local"],
            })

        record["protocol"] = await conversation(
            wire, CWD, no_worker, model=model, base_instructions=BASE_INSTRUCTIONS,
            before_thread=inventory,
        )
        record["mcp"] = await wire.rpc("mcpServerStatus/list", {})
        record["marker"] = await wire.rpc("fs/readFile", {"path": MARKER})
        await wire.io.close_stdin()

    async with placement(image, model=model, scenario=PROBE_PROMPT, tool=scenario.tool,
                         arguments=scenario.arguments, request_check=scenario) as fixture:
        composed, peer, record = fixture
        record["combined_startup"] = {"model": model, "dates": dates}
        observations, result = await observe(
            composed, peer, guard_root, query=query, record=record,
            config=controlled_configuration(model) if config is None else config,
            files={MARKER: "absent", **(files or {})},
        )
    assert_outcome(result)
    assert len(peer.requests) == 2 and not peer.failures
    assert_native_identity(observations["protocol"], peer.requests)
    assert not observations["protocol"]["calls"]
    assert all(observations["bootstrap"]["absent"].values())
    for family in ("skills", "hooks"):
        assert len(observations[family]["data"]) == 1
        assert observations[family]["data"][0]["cwd"] == CWD
        assert not observations[family]["data"][0]["errors"]
    assert not observations["plugins"]["marketplaceLoadErrors"]
    return observations


def marker(record):
    return base64.b64decode(record["marker"]["dataBase64"], validate=True).decode()


def assert_hook_attempt(record, enabled):
    events = [item["received"] for item in record["wire"] if item.get("received", {}).get(
        "method",
    ) in {"hook/started", "hook/completed"}]
    assert [item["method"] for item in events] == (
        ["hook/started", "hook/completed"] if enabled else []
    )
    if enabled:
        # The unchanged minimal image has no /bin/sh. Discovery and trust
        # are proven; successful command-hook execution remains blocked.
        run = events[-1]["params"]["run"]
        assert run["status"] == "failed"
        assert run["entries"] == [{"kind": "error", "text":
                                   "No such file or directory (os error 2)"}]


@pytest.mark.parametrize("model", MODELS)
async def test_fresh_recipe_has_no_external_startup_state(placement_image, tmp_path, model):
    record = await measure(placement_image, tmp_path, model)
    assert record["config"]["config"]["model"] == model
    assert record["requirements"] == {"requirements": None}
    assert record["account"] == {"account": None, "requiresOpenaiAuth": False}
    assert not [skill for row in record["skills"]["data"] for skill in row["skills"]]
    assert not [hook for row in record["hooks"]["data"] for hook in row["hooks"]]
    assert not record["plugins"]["marketplaces"]
    assert not record["plugins"]["marketplaceLoadErrors"]
    assert not record["mcp"]["data"] and marker(record) == "absent"
    assert record["bootstrap"]["bootstrap_environment"] == {
        "HOME": "/tmp/home", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PWD": "/tmp",
    }


async def test_unused_named_profile_is_not_ambient_configuration(placement_image, tmp_path):
    # An unused profile must not become ambient instructions or startup authority.
    record = await measure(
        placement_image, tmp_path, MODELS[0],
        files={HOME_CONFIG + "/fixture.config.toml": 'model = "gpt-5.6-sol"\n'},
    )
    assert record["config"]["config"]["model"] == MODELS[0]


async def test_app_server_refuses_named_profile_before_rpc(placement_image, tmp_path):
    async with placement(placement_image) as (composed, peer, record):
        _observations, result = await observe(
            composed, peer, tmp_path, record=record,
            files={HOME_CONFIG + "/fixture.config.toml": 'model = "gpt-5.6-sol"\n'},
            arguments=("--profile", "fixture"),
        )
    assert_outcome(result, status=1)
    assert b"Error: --profile only applies to runtime commands and `codex mcp`:" in result.stderr
    assert not peer.requests
    # The bridge already established its one startup connection, but no HTTP
    # request followed. Preserve that failure instead of calling it a clean turn.
    assert peer.budget.connections == 1 and peer.failures == ["ValueError('incomplete headers')"]


@pytest.mark.parametrize("trust", ["trusted", "untrusted"])
async def test_project_toml_and_mcp_startup_respect_project_trust(
    placement_image, tmp_path, trust,
):
    project = ('model = "gpt-5.6-sol"\n[mcp_servers.fixture]\ncommand = "/usr/bin/python3"\n'
               f'args = {json.dumps(["-I", "-u", "-c", inert_mcp()])}\nstartup_timeout_sec = 5\n')
    record = await measure(
        placement_image, tmp_path, MODELS[0],
        config=controlled_configuration(MODELS[0]) +
               f'\n[projects."{CWD}"]\ntrust_level = "{trust}"\n',
        files={CWD + "/.git/HEAD": "ref: refs/heads/main\n",
               CWD + "/.codex/config.toml": project},
        mcp=trust == "trusted",
    )
    assert record["config"]["config"]["model"] == (MODELS[1] if trust == "trusted" else MODELS[0])
    assert marker(record) == ("started" if trust == "trusted" else "absent")
    assert [server["name"] for server in record["mcp"]["data"]] == (
        ["fixture"] if trust == "trusted" else []
    )


@pytest.mark.parametrize("enabled", [True, False])
async def test_seeded_local_plugin_obeys_explicit_enablement(placement_image, tmp_path, enabled):
    # Pin the loader's existing cache layout; this is not an installation test.
    root = HOME_CONFIG + "/plugins/cache/fixture/inert-fixture/local"
    record = await measure(
        placement_image, tmp_path, MODELS[0],
        config=controlled_configuration(MODELS[0]) +
               f'\n[plugins."inert-fixture@fixture"]\nenabled = {str(enabled).lower()}\n',
        files={
            root + "/.codex-plugin/plugin.json": json.dumps({
                "name": "inert-fixture", "mcpServers": "./.mcp.json", "skills": "./skills",
            }),
            root + "/.mcp.json": json.dumps({"mcpServers": {"fixture": {
                "command": "/usr/bin/python3", "args": ["-I", "-u", "-c", inert_mcp()],
            }}}),
            root + "/skills/inert-plugin/SKILL.md":
                "---\nname: inert-plugin\ndescription: Public inert plugin marker.\n"
                "---\nNo action.\n",
        },
        mcp=enabled, plugins=enabled,
    )
    skills = [skill["name"] for row in record["skills"]["data"] for skill in row["skills"]]
    assert ("inert-fixture:inert-plugin" in skills) is enabled
    assert marker(record) == ("started" if enabled else "absent")
    assert len(record["mcp"]["data"]) == (1 if enabled else 0)


@pytest.mark.parametrize("root", [HOME_CONFIG + "/skills", CWD + "/.agents/skills"])
async def test_skill_discovery_and_prompt_inclusion_are_distinct(
    placement_image, tmp_path, root,
):
    record = await measure(placement_image, tmp_path, MODELS[0], files={
        root + "/inert-fixture/SKILL.md":
            "---\nname: inert-fixture\ndescription: Public inert discovery marker.\n"
            "---\nNo action.\n",
    })
    assert "inert-fixture" in [skill["name"] for row in record["skills"]["data"]
                               for skill in row["skills"]]
    # The peer's independent exact-context assertion already proved that this
    # discovered skill did not get appended to the controlled native prompt.
    assert marker(record) == "absent"


@pytest.mark.parametrize("origin", ["json", "toml"])
async def test_user_hook_discovery_trust_and_disable_have_execution_controls(
    placement_image, tmp_path, origin,
):
    command = ("/usr/bin/python3 -I -c \"from pathlib import Path; "
               f"Path('{MARKER}').write_text('hook')\"")
    hook = {"SessionStart": [{"hooks": [{"type": "command", "command": command, "timeout": 2}]}]}
    config = controlled_configuration(MODELS[0])
    files = {}
    if origin == "json":
        files[HOME_CONFIG + "/hooks.json"] = json.dumps({"hooks": hook})
    else:
        config += ('\n[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\ntype = "command"\n'
                   f'command = {json.dumps(command)}\ntimeout = 2\n')
    record = await measure(placement_image, tmp_path, MODELS[0], config=config, files=files)
    hooks = [hook for row in record["hooks"]["data"] for hook in row["hooks"]]
    assert len(hooks) == 1 and hooks[0]["trustStatus"] == "untrusted"
    assert hooks[0]["enabled"] is True
    assert marker(record) == "absent"
    assert_hook_attempt(record, False)
    for enabled in (True, False):
        # The controller explicitly trusts exactly the inert hook it just
        # inspected. This is an attempted-execution control, not the safe recipe.
        selected = config + (
            f'\n[hooks.state.{json.dumps(hooks[0]["key"])}]\n'
            f'trusted_hash = {json.dumps(hooks[0]["currentHash"])}\n'
            f'enabled = {str(enabled).lower()}\n'
        )
        checked = await measure(placement_image, tmp_path, MODELS[0],
                                config=selected, files=files)
        entries = [hook for row in checked["hooks"]["data"] for hook in row["hooks"]]
        assert len(entries) == 1 and entries[0]["trustStatus"] == "trusted"
        assert entries[0]["enabled"] is enabled
        assert_hook_attempt(checked, enabled)
        assert marker(checked) == "absent"
