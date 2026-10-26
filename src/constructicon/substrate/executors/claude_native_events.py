"""Exact pinned native framing exception shared by maintenance and diagnostics.

UI notifications are inert byte framing. They never constitute mode, refresh,
startup or completion evidence. Callers own complete-record parsing and count.
"""

from __future__ import annotations

from enum import StrEnum


class ClaudeSystemRecordCategory(StrEnum):
    """Closed source-backed labels, never native strings or admission decisions."""

    UI_INVALIDATE = "ui-invalidate"
    COMMANDS_CHANGED = "commands-changed"
    UI_PANES = "ui-panes"
    STATUS = "status"
    BACKGROUND_TASKS_CHANGED = "background-tasks-changed"
    OTHER = "other"


_SYSTEM_CATEGORIES = {
    "ui_invalidate": ClaudeSystemRecordCategory.UI_INVALIDATE,
    "commands_changed": ClaudeSystemRecordCategory.COMMANDS_CHANGED,
    "ui_panes": ClaudeSystemRecordCategory.UI_PANES,
    "status": ClaudeSystemRecordCategory.STATUS,
    "background_tasks_changed": ClaudeSystemRecordCategory.BACKGROUND_TASKS_CHANGED,
}


def system_record_category(value: object) -> ClaudeSystemRecordCategory:
    """Discard all values except exact, statically recognized system subtypes."""
    if type(value) is not dict or value.get("type") != "system":
        return ClaudeSystemRecordCategory.OTHER
    subtype = value.get("subtype")
    if type(subtype) is not str:
        return ClaudeSystemRecordCategory.OTHER
    return _SYSTEM_CATEGORIES.get(subtype, ClaudeSystemRecordCategory.OTHER)


def exact_ui_invalidate(value: object) -> bool:
    """Accept only the observed 2.1.296 UI-invalidate object shape."""
    if type(value) is not dict:
        return False
    required = {"type", "subtype", "event", "uuid", "session_id"}
    if (set(value) not in (required, required | {"instances"})
            or value.get("type") != "system"
            or value.get("subtype") != "ui_invalidate"
            or value.get("event") != "ui.render"
            or type(value.get("uuid")) is not str
            or type(value.get("session_id")) is not str):
        return False
    if "instances" in value:
        instances = value["instances"]
        if type(instances) is not list or any(
            type(item) is not dict
            or set(item) != {"surface", "component", "instance_id"}
            or any(type(field) is not str for field in item.values())
            for item in instances
        ):
            return False
    return True
