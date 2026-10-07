"""What a real model request offers the model, and the production recipe that asks.

The measurement behind the native tool inventory (M8-N5-native-tool-inventory.md):
production's configuration, catalog seal and environment file, pointed only at
the placement fixture's fake provider, with any of the three layers removable
to show what it alone holds back.
"""

from __future__ import annotations

import re
from typing import Any

from constructicon.substrate.executors.codex_lane import (
    RUNTIME_CATALOG,
    TOOL_CONTROLS,
    production_configuration,
)
from constructicon.substrate.executors.linux import ENVIRONMENTS_MOUNT, NATIVE_ENVIRONMENTS

SOURCE_CATALOG = "/opt/native-startup/source-catalog.json"
SEALED_CATALOG = "/opt/native-startup/sealed-catalog.json"
"""The placement image's pinned catalog, and production's seal of it."""

LAYERS = frozenset({"catalog", "controls", "environment"})

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


def probe_setup(*without: str) -> tuple[str, dict[str, str]]:
    """Production's configuration and native files, less the named layers.

    Only the provider and the catalog path change: the catalog is the image's
    copy of production's seal, or of the pinned source without the catalog
    layer. Without the environment layer no ``environments.toml`` is written,
    so the vendor's local environment exists.
    """

    if not set(without) <= LAYERS:
        raise ValueError(f"unknown inventory layers: {sorted(set(without) - LAYERS)}")
    configuration = production_configuration()
    assert configuration.count(RUNTIME_CATALOG) == configuration.count(TOOL_CONTROLS) == 1
    if "controls" in without:
        configuration = configuration.replace(TOOL_CONTROLS, "")
    catalog = SOURCE_CATALOG if "catalog" in without else SEALED_CATALOG
    config = ('model_provider = "probe"\n' + configuration.replace(RUNTIME_CATALOG, catalog)
              + PROBE_PROVIDER)
    files = {} if "environment" in without else {ENVIRONMENTS_MOUNT: NATIVE_ENVIRONMENTS.decode()}
    return config, files


def offered_tools(request: dict[str, Any]) -> list[Any]:
    """The tool declarations a model request offers, as sent.

    Responses Lite carries them in one ``additional_tools`` input item
    (``core/src/client.rs:902-933``); otherwise they are the request's ``tools``.
    """

    declared = list(request.get("tools", []))
    for item in request.get("input", []):
        if isinstance(item, dict) and item.get("type") == "additional_tools":
            declared += item["tools"]
    return declared


NESTED = re.compile(r"^### `([^`]+)`", re.MULTILINE)
"""A code-mode heading (``code-mode-protocol/src/description.rs:482-488``)."""


def tool_inventory(request: dict[str, Any]) -> list[str]:
    """Every tool name a model request offers, sorted.

    Namespaces are dotted (``collaboration.spawn_agent``). Code mode's ``exec``
    lists the tools it can call as headed sections of its description, and those
    are offered too (``functions.exec>apply_patch``).
    """

    return sorted(_names(offered_tools(request), ""))


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
