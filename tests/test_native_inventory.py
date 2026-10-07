"""The inventory reader and the probe recipe, portably."""

import json
import tomllib
from pathlib import Path

import pytest

from constructicon.substrate.executors.codex_lane import (
    RUNTIME_CATALOG,
    TOOL_CONTROLS,
    production_configuration,
)
from constructicon.substrate.executors.codex_protocol import (
    CONTAINED_PYTHON_TOOL,
    thread_start_request,
)
from constructicon.substrate.executors.linux import ENVIRONMENTS_MOUNT, NATIVE_ENVIRONMENTS
from tests.native_inventory import (
    SEALED_CATALOG,
    SOURCE_CATALOG,
    offered_tools,
    probe_setup,
    tool_inventory,
)

EXEC_DESCRIPTION = (
    "Run JavaScript.\n\n### `apply_patch`\nEdit files.\n\n"
    "### `clock.sleep` (`sleep`)\nWait.\n\nNot a heading: ### `inline`"
)


def test_every_offered_name_is_read_from_both_framings_and_from_code_mode():
    request = {
        "tools": [{"type": "function", "name": "exec", "description": EXEC_DESCRIPTION}],
        "input": [
            {"type": "message", "role": "user", "content": []},
            {"type": "additional_tools", "role": "developer", "tools": [
                {"type": "function", "name": "wait"},
                {"type": "namespace", "name": "collaboration", "tools": [
                    {"type": "function", "name": "spawn_agent"},
                    {"type": "function", "name": "close_agent"},
                ]},
            ]},
        ],
    }
    assert tool_inventory(request) == [
        "collaboration.close_agent", "collaboration.spawn_agent",
        "exec", "exec>apply_patch", "exec>clock.sleep", "wait",
    ]
    assert len(offered_tools(request)) == 3


def test_a_request_offering_nothing_has_an_empty_inventory():
    assert tool_inventory({"input": [{"type": "additional_tools", "tools": []}]}) == []
    assert tool_inventory({"input": []}) == []


def parsed(*without):
    config, files = probe_setup(*without)
    return tomllib.loads(config), files


def test_the_sealed_probe_is_production_but_for_its_provider_and_catalog_path():
    probe, files = parsed()
    production = tomllib.loads(production_configuration())
    assert probe.pop("model_provider") == "probe"
    assert set(probe.pop("model_providers")) == {"probe"}
    assert probe.pop("model_catalog_json") == SEALED_CATALOG
    assert production.pop("model_catalog_json") == RUNTIME_CATALOG
    assert probe == production
    assert files == {ENVIRONMENTS_MOUNT: NATIVE_ENVIRONMENTS.decode()}


def test_each_layer_is_removed_alone():
    sealed, files = parsed()
    without_catalog, catalog_files = parsed("catalog")
    assert without_catalog.pop("model_catalog_json") == SOURCE_CATALOG
    assert {**without_catalog, "model_catalog_json": SEALED_CATALOG} == sealed
    assert catalog_files == files

    without_controls, control_files = parsed("controls")
    controls = tomllib.loads("[features]\n" + TOOL_CONTROLS)
    assert "agents" not in without_controls and "tools" not in without_controls
    assert set(sealed["features"]) - set(without_controls["features"]) == set(controls["features"])
    assert control_files == files

    without_environment, environment_files = parsed("environment")
    assert without_environment == sealed and environment_files == {}


def test_the_measured_write_offer_is_the_adapters_declaration():
    """The golden the lane compares against is the adapter's own tool, as the
    vendor frames it: one ``functions`` namespace, nothing else."""

    golden = json.loads(Path(__file__).with_name("fixtures").joinpath(
        "native_production_inventory.json").read_text())["sealed"]
    (declared,) = thread_start_request(0, cwd="/tmp", dynamic_tools=(CONTAINED_PYTHON_TOOL,))[
        "params"]["dynamicTools"]
    assert golden["read"] == []
    assert golden["write"] == [{"type": "namespace", "name": "functions", "description": "",
                                "tools": [{
                                    "type": "function", "name": declared["name"],
                                    "description": declared["description"],
                                    "parameters": declared["inputSchema"], "strict": False,
                                }]}]


def test_an_unknown_layer_is_refused():
    with pytest.raises(ValueError, match="unknown inventory layers"):
        probe_setup("network")
