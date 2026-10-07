"""The inventory reader and the probe recipe, portably."""

import tomllib

from constructicon.substrate.executors.codex_lane import RUNTIME_CATALOG, production_configuration
from tests.native_inventory import SOURCE_CATALOG, probe_recipe, tool_inventory

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


def test_a_request_offering_nothing_has_an_empty_inventory():
    assert tool_inventory({"input": [{"type": "additional_tools", "tools": []}]}) == []
    assert tool_inventory({"input": []}) == []


def test_the_probe_recipe_is_production_but_for_its_provider_and_catalog_path():
    probe = tomllib.loads(probe_recipe())
    production = tomllib.loads(production_configuration())
    assert probe.pop("model_provider") == "probe"
    assert set(probe.pop("model_providers")) == {"probe"}
    assert probe.pop("model_catalog_json") == SOURCE_CATALOG
    assert production.pop("model_catalog_json") == RUNTIME_CATALOG
    assert probe == production
