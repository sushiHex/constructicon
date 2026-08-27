"""M6 actor identity comes from the transport, never from tool arguments."""

from __future__ import annotations

import pytest
from mcp.server.auth.provider import AccessToken

from constructicon.api.mcp import auth as auth_module
from constructicon.api.mcp.auth import OAuthActorSource, StaticActorSource
from constructicon.core.control import (
    OPERATE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
)


@pytest.mark.asyncio
async def test_static_actor_source_returns_the_trusted_launcher_identity() -> None:
    expected = AuthenticatedActor(
        actor_id="static:test-operator",
        auth_method="static",
        scopes=frozenset({READ_SCOPE}),
    )
    assert await StaticActorSource(expected).actor() == expected


@pytest.mark.asyncio
async def test_oauth_actor_is_stable_and_discards_unknown_token_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = AccessToken(
        token="opaque",
        client_id="client-7",
        scopes=[READ_SCOPE, OPERATE_SCOPE, "unrelated:scope"],
        subject="alice",
        claims={"iss": "https://issuer.example/"},
    )
    monkeypatch.setattr(auth_module, "get_access_token", lambda: token)

    first = await OAuthActorSource().actor()
    second = await OAuthActorSource().actor()
    assert first == second
    assert first.actor_id.startswith("oauth:")
    assert first.auth_method == "oauth"
    assert first.scopes == frozenset({READ_SCOPE, OPERATE_SCOPE})
    assert first.display_name == "alice"
    assert first.issuer == "https://issuer.example/"
    assert first.subject == "alice"
    assert first.client_id == "client-7"


@pytest.mark.asyncio
async def test_oauth_actor_refuses_an_http_request_without_verified_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "get_access_token", lambda: None)
    with pytest.raises(RuntimeError, match="no verified access token"):
        await OAuthActorSource().actor()
