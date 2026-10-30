"""Exact pinned inert native notifications shared by maintenance and READ.

Notifications are inert byte framing. They never constitute mode, refresh,
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
    INIT = "init"
    NOTIFICATION = "notification"
    API_RETRY = "api-retry"
    MODEL_REFUSAL_NO_FALLBACK = "model-refusal-no-fallback"
    MODEL_REFUSAL_FALLBACK = "model-refusal-fallback"
    MEMORY_RECALL = "memory-recall"
    THINKING_TOKENS = "thinking-tokens"
    COMPACT_BOUNDARY = "compact-boundary"
    MODEL_FALLBACK = "model-fallback"
    MODEL_CONSENT_FALLBACK = "model-consent-fallback"
    INFORMATIONAL = "informational"
    MISSING_SUBTYPE = "missing-subtype"
    INVALID_SUBTYPE = "invalid-subtype"
    OTHER = "other"


_SYSTEM_CATEGORIES = {
    "init": ClaudeSystemRecordCategory.INIT,
    "notification": ClaudeSystemRecordCategory.NOTIFICATION,
    "api_retry": ClaudeSystemRecordCategory.API_RETRY,
    "model_refusal_no_fallback": ClaudeSystemRecordCategory.MODEL_REFUSAL_NO_FALLBACK,
    "model_refusal_fallback": ClaudeSystemRecordCategory.MODEL_REFUSAL_FALLBACK,
    "memory_recall": ClaudeSystemRecordCategory.MEMORY_RECALL,
    "thinking_tokens": ClaudeSystemRecordCategory.THINKING_TOKENS,
    "compact_boundary": ClaudeSystemRecordCategory.COMPACT_BOUNDARY,
    "model_fallback": ClaudeSystemRecordCategory.MODEL_FALLBACK,
    "model_consent_fallback": ClaudeSystemRecordCategory.MODEL_CONSENT_FALLBACK,
    "informational": ClaudeSystemRecordCategory.INFORMATIONAL,
    "ui_invalidate": ClaudeSystemRecordCategory.UI_INVALIDATE,
    "commands_changed": ClaudeSystemRecordCategory.COMMANDS_CHANGED,
    "ui_panes": ClaudeSystemRecordCategory.UI_PANES,
    "status": ClaudeSystemRecordCategory.STATUS,
    "background_tasks_changed": ClaudeSystemRecordCategory.BACKGROUND_TASKS_CHANGED,
}


def read_system_record_category(value: object) -> ClaudeSystemRecordCategory:
    """Discard all values except exact, statically recognized system subtypes."""
    if type(value) is not dict or value.get("type") != "system":
        return ClaudeSystemRecordCategory.OTHER
    if "subtype" not in value:
        return ClaudeSystemRecordCategory.MISSING_SUBTYPE
    subtype = value.get("subtype")
    if type(subtype) is not str:
        return ClaudeSystemRecordCategory.INVALID_SUBTYPE
    return _SYSTEM_CATEGORIES.get(subtype, ClaudeSystemRecordCategory.OTHER)


def system_record_category(value: object) -> ClaudeSystemRecordCategory:
    """Preserve the existing maintenance projection's coarser closed catalog."""
    category = read_system_record_category(value)
    if category in (ClaudeSystemRecordCategory.UI_INVALIDATE,
                    ClaudeSystemRecordCategory.COMMANDS_CHANGED,
                    ClaudeSystemRecordCategory.UI_PANES,
                    ClaudeSystemRecordCategory.STATUS,
                    ClaudeSystemRecordCategory.BACKGROUND_TASKS_CHANGED):
        return category
    return ClaudeSystemRecordCategory.OTHER


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


def exact_commands_changed(value: object) -> bool:
    """Validate 2.1.296 mF/Vt framing, discarding its entire command catalog."""
    if type(value) is not dict:
        return False
    if (set(value) != {"type", "subtype", "commands", "uuid", "session_id"}
            or any(type(key) is not str for key in value)
            or any(type(value[key]) is not str for key in ("type", "subtype", "uuid", "session_id"))
            or value["type"] != "system" or value["subtype"] != "commands_changed"):
        return False
    commands = value["commands"]
    if type(commands) is not list:
        return False
    required = {"name", "description", "argumentHint"}
    for row in commands:
        if (type(row) is not dict
                or any(type(key) is not str for key in row)
                or not required <= set(row) or set(row) - required - {"aliases", "builtin"}
                or any(type(row[key]) is not str for key in required)):
            return False
        if "aliases" in row and (type(row["aliases"]) is not list
                                 or any(type(alias) is not str for alias in row["aliases"])):
            return False
        if "builtin" in row and type(row["builtin"]) is not bool:
            return False
    return True


def exact_inert_notification(value: object) -> bool:
    """One closed framing exception; validated metadata supplies no authority."""
    return exact_ui_invalidate(value) or exact_commands_changed(value)


def exact_permission_check_status(value: object) -> bool:
    """Pinned zF schema B@208364898 and q9e producer B@218905919."""
    if type(value) is not dict:
        return False
    required = {"type", "subtype", "tool_use_id", "status", "uuid", "session_id"}
    return (set(value) in (required, required | {"agent_id"})
            and value.get("type") == "system"
            and value.get("subtype") == "permission_check_status"
            and all(type(field) is str for field in value.values())
            and value.get("status") in ("checking", "done"))


def exact_session_title_changed(value: object) -> bool:
    """Pinned rF schema B@208342936 and aDo producer B@233017979."""
    return (type(value) is dict
            and set(value) == {"type", "subtype", "title", "uuid", "session_id"}
            and value.get("type") == "system" and value.get("subtype") == "session_title_changed"
            and all(type(field) is str for field in value.values()))


def exact_post_turn_summary(value: object) -> bool:
    """Pinned so schema B@208312584 and Xa producer B@224148252.

    summarizes_uuid is opaque display metadata, including the producer's empty
    fallback. Complete-record and cumulative bounds belong to the caller.
    """
    return (type(value) is dict
            and set(value) == {"type", "subtype", "summarizes_uuid", "status_category",
                              "status_detail", "needs_action", "uuid", "session_id"}
            and value.get("type") == "system" and value.get("subtype") == "post_turn_summary"
            and all(type(field) is str for field in value.values()))


def exact_task_summary(value: object) -> bool:
    """Pinned ro schema B@208312897; notifyMetadataChanged B@215553208.

    The idle transition emits detail null. This is never task settlement.
    """
    return (type(value) is dict
            and set(value) == {"type", "subtype", "detail", "uuid", "session_id"}
            and value.get("type") == "system" and value.get("subtype") == "task_summary"
            and all(type(value[key]) is str for key in ("type", "subtype", "uuid", "session_id"))
            and (value["detail"] is None or type(value["detail"]) is str))
