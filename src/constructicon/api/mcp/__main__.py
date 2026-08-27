"""`constructicon-mcp`: local stdio or authenticated Streamable HTTP server."""

from __future__ import annotations

import argparse
import importlib
import inspect
from pathlib import Path
from typing import Any, cast

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings

from constructicon.api.control import ControlPlane
from constructicon.api.mcp.auth import OAuthActorSource, StaticActorSource
from constructicon.api.mcp.server import create_mcp_server
from constructicon.api.system import Constructicon
from constructicon.core.control import (
    ADMIN_SCOPE,
    APPROVE_SCOPE,
    OPERATE_SCOPE,
    PROMOTE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
)
from constructicon.substrate.journal.sqlite import SqliteJournal

DEFAULT_SCOPES = (READ_SCOPE, OPERATE_SCOPE, APPROVE_SCOPE, PROMOTE_SCOPE)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Constructicon's M6 MCP control plane")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(".constructicon/constructicon.db"),
        help="authoritative SQLite database",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--actor-id", default="static:local-operator")
    parser.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        choices=(READ_SCOPE, OPERATE_SCOPE, APPROVE_SCOPE, PROMOTE_SCOPE, ADMIN_SCOPE),
        help="stdio actor scope; repeat as needed",
    )
    parser.add_argument(
        "--token-verifier",
        help="HTTP-only import reference module:qualname yielding a TokenVerifier",
    )
    parser.add_argument("--issuer-url", help="HTTP OAuth issuer URL")
    parser.add_argument("--resource-server-url", help="public MCP resource URL")
    parser.add_argument(
        "--required-scope",
        action="append",
        dest="required_scopes",
        default=[],
        help="scope required by HTTP middleware; repeat as needed",
    )
    return parser


def _load_token_verifier(reference: str) -> TokenVerifier:
    module_name, separator, qualname = reference.partition(":")
    if not separator or not module_name or not qualname:
        raise ValueError("token verifier must be module:qualname")
    target: Any = importlib.import_module(module_name)
    for segment in qualname.split("."):
        target = getattr(target, segment)
    value = target() if inspect.isclass(target) else target
    if not callable(getattr(value, "verify_token", None)):
        raise TypeError(f"{reference!r} does not yield a TokenVerifier")
    return cast(TokenVerifier, value)


def main() -> None:
    args = _parser().parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    journal = SqliteJournal(args.database)
    system = Constructicon(journal=journal)
    control = ControlPlane(system=system, store=journal)

    if args.transport == "stdio":
        actor = AuthenticatedActor(
            actor_id=args.actor_id,
            auth_method="static",
            scopes=frozenset(args.scopes or DEFAULT_SCOPES),
            display_name=args.actor_id,
        )
        server = create_mcp_server(control, StaticActorSource(actor))
        server.run(transport="stdio")
        return

    missing = [
        name
        for name, value in (
            ("--token-verifier", args.token_verifier),
            ("--issuer-url", args.issuer_url),
            ("--resource-server-url", args.resource_server_url),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            "streamable-http is authenticated or unavailable; missing " + ", ".join(missing)
        )
    verifier = _load_token_verifier(args.token_verifier)
    auth = AuthSettings(
        issuer_url=args.issuer_url,
        resource_server_url=args.resource_server_url,
        required_scopes=args.required_scopes,
    )
    server = create_mcp_server(
        control,
        OAuthActorSource(),
        token_verifier=verifier,
        auth=auth,
    )
    server.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
