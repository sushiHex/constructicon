"""Exact source-derived inert framing, never a native command catalog."""

from copy import deepcopy

import pytest

from constructicon.substrate.executors.claude_native_events import (
    exact_commands_changed,
    exact_inert_notification,
    exact_ui_invalidate,
)
from tests.substrate._claude_wire import commands_changed


class DictSubclass(dict):
    pass


class ListSubclass(list):
    pass


class StrSubclass(str):
    pass


@pytest.mark.parametrize("optional", [(), ("aliases",), ("builtin",), ("aliases", "builtin")])
@pytest.mark.parametrize("empty", [False, True])
def test_exact_commands_notification_accepts_only_data_and_returns_a_boolean(optional, empty):
    value = commands_changed()
    row = value["commands"][0]
    for key in ("aliases", "builtin"):
        if key not in optional:
            del row[key]
    if "aliases" in optional:
        row["aliases"] = []
    if "builtin" in optional:
        row["builtin"] = False
    if empty:
        value["commands"] = []
    before = deepcopy(value)
    assert exact_commands_changed(value) is True
    assert exact_inert_notification(value) is True
    assert exact_ui_invalidate(value) is False
    assert value == before  # No retained projection, normalization or repair.


@pytest.mark.parametrize("field", ["type", "subtype", "commands", "uuid", "session_id"])
def test_commands_envelope_requires_every_exact_field(field):
    value = commands_changed()
    del value[field]
    assert not exact_commands_changed(value)
    assert not exact_inert_notification(value)


@pytest.mark.parametrize("field", ["name", "description", "argumentHint"])
def test_commands_rows_require_every_exact_field(field):
    value = commands_changed()
    del value["commands"][0][field]
    assert not exact_commands_changed(value)


@pytest.mark.parametrize("damage", [
    "object", "object-subclass", "envelope-extension", "envelope-key-subclass",
    "type", "subtype", "commands", "commands-subclass", "row", "row-subclass",
    "row-extension", "row-key-subclass", "aliases", "aliases-subclass", "alias",
    "alias-subclass", "builtin-int", "builtin-null",
])
def test_commands_notification_refuses_malformed_closed_shape(damage):
    value = commands_changed()
    row = value["commands"][0]
    if damage == "object":
        value = []
    elif damage == "object-subclass":
        value = DictSubclass(value)
    elif damage == "envelope-extension":
        value["private-extension"] = "private-value"
    elif damage == "envelope-key-subclass":
        value[StrSubclass("uuid")] = value.pop("uuid")
    elif damage in {"type", "subtype"}:
        value[damage] = "unknown"
    elif damage == "commands":
        value["commands"] = {}
    elif damage == "commands-subclass":
        value["commands"] = ListSubclass(value["commands"])
    elif damage == "row":
        value["commands"] = [None]
    elif damage == "row-subclass":
        value["commands"] = [DictSubclass(row)]
    elif damage == "row-extension":
        row["private-extension"] = "private-value"
    elif damage == "row-key-subclass":
        row[StrSubclass("name")] = row.pop("name")
    elif damage == "aliases":
        row["aliases"] = "private-alias"
    elif damage == "aliases-subclass":
        row["aliases"] = ListSubclass(row["aliases"])
    elif damage == "alias":
        row["aliases"] = [None]
    elif damage == "alias-subclass":
        row["aliases"] = [StrSubclass("private-alias")]
    elif damage == "builtin-int":
        row["builtin"] = 1
    else:
        row["builtin"] = None
    assert not exact_commands_changed(value)
    assert not exact_inert_notification(value)


@pytest.mark.parametrize("field", ["type", "subtype", "uuid", "session_id",
                                   "name", "description", "argumentHint"])
@pytest.mark.parametrize("invalid", [None, True, 1, [], {}, StrSubclass("private-value")])
def test_commands_notification_strings_are_exact(field, invalid):
    value = commands_changed()
    target = value if field in value else value["commands"][0]
    target[field] = invalid
    assert not exact_commands_changed(value)
    assert not exact_inert_notification(value)


def test_shared_notification_classifier_keeps_ui_and_unknown_discriminators_exact():
    ui = {"type": "system", "subtype": "ui_invalidate", "event": "ui.render",
          "uuid": "opaque", "session_id": ""}
    assert exact_inert_notification(ui)
    assert exact_ui_invalidate(ui)
    assert not exact_commands_changed(ui)
    assert not exact_inert_notification({**ui, "private-extension": "private-value"})
    assert not exact_inert_notification({**commands_changed(), "subtype": "private-other"})
