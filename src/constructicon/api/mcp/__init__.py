"""Lazy optional MCP adapter for Constructicon's durable control plane."""

from __future__ import annotations

from typing import Any

__all__ = ["OAuthActorSource", "StaticActorSource", "create_mcp_server"]


def __getattr__(name: str) -> Any:
    if name in {"OAuthActorSource", "StaticActorSource"}:
        from constructicon.api.mcp.auth import OAuthActorSource, StaticActorSource

        return {
            "OAuthActorSource": OAuthActorSource,
            "StaticActorSource": StaticActorSource,
        }[name]
    if name == "create_mcp_server":
        from constructicon.api.mcp.server import create_mcp_server

        return create_mcp_server
    raise AttributeError(name)
