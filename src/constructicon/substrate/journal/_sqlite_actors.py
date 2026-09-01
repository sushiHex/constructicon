"""Exact durable actor decoding with one named historical compatibility rule."""

from __future__ import annotations

from pydantic import ValidationError

from constructicon.core.control import CONTROL_SCOPES, AuthenticatedActor
from constructicon.core.identity import JsonValue, canonical_json
from constructicon.substrate.journal._sqlite_base import _lossless_model


def durable_authenticated_actor(
    raw: JsonValue,
    *,
    fact: str,
) -> AuthenticatedActor:
    """Decode an actor, permitting only the pre-sort scope-array ordering.

    Schema-5/6 writers serialized ``frozenset`` iteration order.  Those exact
    historical bytes may therefore carry a unique array of known scopes in any
    order.  No scalar, duplicate, unknown scope, field, or value normalization
    is accepted; current writers always emit the sorted form.
    """

    try:
        return _lossless_model(AuthenticatedActor, raw)
    except (TypeError, ValueError, ValidationError) as exact_error:
        if not isinstance(raw, dict):
            raise exact_error
        scopes = raw.get("scopes")
        if (
            not isinstance(scopes, list)
            or any(type(scope) is not str for scope in scopes)
            or len(scopes) != len(set(scopes))
            or any(scope not in CONTROL_SCOPES for scope in scopes)
            or scopes == sorted(scopes)
        ):
            raise exact_error
        normalized = dict(raw)
        normalized["scopes"] = sorted(scopes)
        actor = _lossless_model(AuthenticatedActor, normalized)
        historical = actor.model_dump(mode="json")
        historical["scopes"] = scopes
        if canonical_json(raw) != canonical_json(historical):
            raise exact_error
        return actor
