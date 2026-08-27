"""Transport-derived actor identity for the M6 MCP adapter.

Only this package imports MCP.  The control plane receives an already verified
``AuthenticatedActor`` and never accepts caller identity as tool data.
"""

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.auth.middleware.auth_context import get_access_token

from constructicon.core.control import CONTROL_SCOPES, ActorSource, AuthenticatedActor
from constructicon.core.identity import digest


@dataclass(frozen=True)
class StaticActorSource(ActorSource):
    """The trusted-launcher identity used by stdio."""

    value: AuthenticatedActor

    async def actor(self) -> AuthenticatedActor:
        return self.value


class OAuthActorSource(ActorSource):
    """Derive one stable Constructicon principal from the verified bearer token."""

    async def actor(self) -> AuthenticatedActor:
        token = get_access_token()
        if token is None:
            raise RuntimeError("authenticated HTTP request has no verified access token")
        issuer_value = (token.claims or {}).get("iss")
        issuer = str(issuer_value) if issuer_value is not None else None
        principal = {
            "issuer": issuer,
            "subject": token.subject,
            "client_id": token.client_id,
        }
        identity = digest("oauth-actor", 1, principal)
        actor_id = f"oauth:{str(identity).removeprefix('sha256:')[:32]}"
        return AuthenticatedActor(
            actor_id=actor_id,
            auth_method="oauth",
            scopes=frozenset(token.scopes) & CONTROL_SCOPES,
            display_name=token.subject or token.client_id,
            issuer=issuer,
            subject=token.subject,
            client_id=token.client_id,
        )
