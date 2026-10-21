"""Exact pinned native framing exception shared by maintenance and diagnostics.

UI notifications are inert byte framing. They never constitute mode, refresh,
startup or completion evidence. Callers own complete-record parsing and count.
"""

from __future__ import annotations


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
