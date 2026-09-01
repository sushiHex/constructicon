"""The identity law: one domain-separated hash for every identity."""

from __future__ import annotations

from typing import cast

import pytest

from constructicon.core.identity import Digest, canonical_json, digest, parse_json_value


def test_digest_is_deterministic() -> None:
    assert digest("component", 1, {"a": 1, "b": [1, 2]}) == digest(
        "component", 1, {"b": [1, 2], "a": 1}
    )


def test_domain_separation() -> None:
    payload = {"same": "payload"}
    assert digest("component", 1, payload) != digest("graph", 1, payload)
    assert digest("component", 1, payload) != digest("component", 2, payload)


def test_canonical_json_is_sorted_and_compact() -> None:
    assert canonical_json({"b": 1, "a": [None, True]}) == '{"a":[null,true],"b":1}'


def test_canonical_json_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="NaN"):
        canonical_json({"x": float("nan")})


def test_durable_json_never_collapses_duplicate_object_keys() -> None:
    with pytest.raises(ValueError, match="repeats key 'authority'"):
        parse_json_value('{"authority":"first","authority":"second"}')


def test_json_identity_rejects_a_lone_utf16_surrogate_as_not_unicode() -> None:
    with pytest.raises(ValueError, match="Unicode scalar"):
        parse_json_value('"\\ud800"')


def test_durable_json_requires_text_instead_of_decoding_a_blob() -> None:
    with pytest.raises(ValueError, match="must be text"):
        parse_json_value(cast(str, b'{"authority":"blob"}'))


def test_digest_form_is_validated() -> None:
    with pytest.raises(ValueError):
        Digest("md5:abc")
    with pytest.raises(ValueError):
        Digest("sha256:XYZ")
    value = digest("t", 1, {})
    assert str(value).startswith("sha256:")
    assert len(str(value)) == len("sha256:") + 64
