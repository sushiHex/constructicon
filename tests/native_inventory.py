"""What a real model request offers the model, and the production recipe that asks.

The measurement behind the N5 native tool inventory: the production configuration,
pointed only at the placement fixture's fake provider, and every tool name its
first model request declares.
"""

from __future__ import annotations

import re
from typing import Any

from constructicon.substrate.executors.codex_lane import RUNTIME_CATALOG, production_configuration

SOURCE_CATALOG = "/opt/native-startup/source-catalog.json"
"""The placement image's copy of the unchanged pinned catalog."""

PROBE_PROVIDER = (
    '[model_providers.probe]\nname = "Credential-free placement fixture"\n'
    'base_url = "http://127.0.0.1:1/v1"\nwire_api = "responses"\n'
    "requires_openai_auth = false\nrequest_max_retries = 0\nstream_max_retries = 0\n"
    "stream_idle_timeout_ms = 10000\n"
    # Production runs the OpenAI provider with ChatGPT auth, which opens the image
    # generation gate; on loopback this fixture header opens the same gate
    # (``model-provider-info/src/lib.rs:621-629`` at rust-v0.160.1).
    'http_headers = { "x-openai-actor-authorization" = "fixture" }\n'
)


def probe_recipe(*, catalog: str = SOURCE_CATALOG) -> str:
    """The production configuration with only its provider and catalog path swapped."""

    production = production_configuration()
    assert production.count(RUNTIME_CATALOG) == 1
    swapped = production.replace(RUNTIME_CATALOG, catalog)
    return 'model_provider = "probe"\n' + swapped + PROBE_PROVIDER


NESTED = re.compile(r"^### `([^`]+)`", re.MULTILINE)
"""A code-mode heading (``code-mode-protocol/src/description.rs:482-488``)."""


def tool_inventory(request: dict[str, Any]) -> list[str]:
    """Every tool name a model request offers, sorted.

    Namespaces are dotted (``collaboration.spawn_agent``). Code mode's ``exec``
    lists the tools it can call as headed sections of its description, and those
    are offered too (``exec>apply_patch``). Both the request's ``tools`` and any
    ``additional_tools`` input item are read (``core/src/client.rs:902-933``).
    """

    declared = list(request.get("tools", []))
    for item in request.get("input", []):
        if isinstance(item, dict) and item.get("type") == "additional_tools":
            declared += item["tools"]
    return sorted(_names(declared, ""))


def _names(tools: list[dict[str, Any]], prefix: str) -> list[str]:
    names: list[str] = []
    for tool in tools:
        name = prefix + tool["name"]
        if "tools" in tool:
            names += _names(tool["tools"], name + ".")
            continue
        names.append(name)
        if tool["name"] == "exec":
            names += [f"{name}>{nested}" for nested in NESTED.findall(tool.get("description", ""))]
    return names
