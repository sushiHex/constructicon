"""Closed pinned Claude READ observation vocabulary, never admission authority.

Labels cover the audited native constructor/schema union. Unknown input is
projected to a fixed fallback; arbitrary native strings never become evidence.
"""

from __future__ import annotations

from enum import StrEnum


class ClaudeReadRefusalFamily(StrEnum):
    """Finite received-frame families; no private subtype is retained."""

    UNPARSED = "unparsed"
    OTHER_RECORD = "other-record"
    SYSTEM_INIT = "system-init"
    SYSTEM_NOTIFICATION = "system-notification"
    SYSTEM_API_RETRY = "system-api-retry"
    SYSTEM_MODEL_REFUSAL_NO_FALLBACK = "system-model-refusal-no-fallback"
    SYSTEM_MODEL_REFUSAL_FALLBACK = "system-model-refusal-fallback"
    SYSTEM_MEMORY_RECALL = "system-memory-recall"
    SYSTEM_THINKING_TOKENS = "system-thinking-tokens"
    SYSTEM_COMPACT_BOUNDARY = "system-compact-boundary"
    SYSTEM_MODEL_FALLBACK = "system-model-fallback"
    SYSTEM_MODEL_CONSENT_FALLBACK = "system-model-consent-fallback"
    SYSTEM_INFORMATIONAL = "system-informational"
    SYSTEM_STATUS = "system-status"
    SYSTEM_UI_INVALIDATE = "system-ui-invalidate"
    SYSTEM_COMMANDS_CHANGED = "system-commands-changed"
    SYSTEM_UI_PANES = "system-ui-panes"
    SYSTEM_BACKGROUND_TASKS_CHANGED = "system-background-tasks-changed"
    SYSTEM_AGENTS_KILLED = "system-agents-killed"
    SYSTEM_API_ERROR = "system-api-error"
    SYSTEM_AWAY_SUMMARY = "system-away-summary"
    SYSTEM_BRIDGE_STATE = "system-bridge-state"
    SYSTEM_BRIDGE_STATUS = "system-bridge-status"
    SYSTEM_CLOUD_SESSION_DELTA = "system-cloud-session-delta"
    SYSTEM_CLOUD_SESSION_STATUS = "system-cloud-session-status"
    SYSTEM_CODE_CHANGE_PUBLISHED = "system-code-change-published"
    SYSTEM_CONTROL_REQUEST_PROGRESS = "system-control-request-progress"
    SYSTEM_DEV_INTENT = "system-dev-intent"
    SYSTEM_ELICITATION_COMPLETE = "system-elicitation-complete"
    SYSTEM_FEEDBACK_DRAFT_QUEUED = "system-feedback-draft-queued"
    SYSTEM_FILE_ATTACHMENTS_MISSING = "system-file-attachments-missing"
    SYSTEM_FILE_SNAPSHOT = "system-file-snapshot"
    SYSTEM_FILES_PERSISTED = "system-files-persisted"
    SYSTEM_HOOK_PROGRESS = "system-hook-progress"
    SYSTEM_HOOK_RESPONSE = "system-hook-response"
    SYSTEM_HOOK_STARTED = "system-hook-started"
    SYSTEM_INIT_MILESTONE = "system-init-milestone"
    SYSTEM_INSTRUCTION_SIZE_WARNING = "system-instruction-size-warning"
    SYSTEM_LOCAL_COMMAND = "system-local-command"
    SYSTEM_LOCAL_COMMAND_OUTPUT = "system-local-command-output"
    SYSTEM_MEMORY_SAVED = "system-memory-saved"
    SYSTEM_MIRROR_ERROR = "system-mirror-error"
    SYSTEM_PEER_MESSAGE_HOLD = "system-peer-message-hold"
    SYSTEM_PER_TURN_EFFORT_CHANGED = "system-per-turn-effort-changed"
    SYSTEM_PERMISSION_CHECK_STATUS = "system-permission-check-status"
    SYSTEM_PERMISSION_DENIED = "system-permission-denied"
    SYSTEM_PERMISSION_RETRY = "system-permission-retry"
    SYSTEM_PLUGIN_INSTALL = "system-plugin-install"
    SYSTEM_POST_TURN_SUMMARY = "system-post-turn-summary"
    SYSTEM_SCHEDULED_TASK_FIRE = "system-scheduled-task-fire"
    SYSTEM_SESSION_METADATA = "system-session-metadata"
    SYSTEM_SESSION_STATE_CHANGED = "system-session-state-changed"
    SYSTEM_SESSION_TITLE_CHANGED = "system-session-title-changed"
    SYSTEM_STOP_HOOK_SUMMARY = "system-stop-hook-summary"
    SYSTEM_TASK_NOTIFICATION = "system-task-notification"
    SYSTEM_TASK_PROGRESS = "system-task-progress"
    SYSTEM_TASK_STARTED = "system-task-started"
    SYSTEM_TASK_SUMMARY = "system-task-summary"
    SYSTEM_TASK_UPDATED = "system-task-updated"
    SYSTEM_THINKING = "system-thinking"
    SYSTEM_TOOL_HOST_RESULT = "system-tool-host-result"
    SYSTEM_TURN_DURATION = "system-turn-duration"
    SYSTEM_TURN_HANDOFF_AVAILABLE = "system-turn-handoff-available"
    SYSTEM_TURN_PREEMPTED = "system-turn-preempted"
    SYSTEM_TURN_STARTING = "system-turn-starting"
    SYSTEM_UI_FOCUS = "system-ui-focus"
    SYSTEM_UI_LOG = "system-ui-log"
    SYSTEM_UI_SCROLL = "system-ui-scroll"
    SYSTEM_UI_STATUS = "system-ui-status"
    SYSTEM_UI_TOAST = "system-ui-toast"
    SYSTEM_UPGRADE_RELAY_MARKER = "system-upgrade-relay-marker"
    SYSTEM_VCS_STATE_CHANGED = "system-vcs-state-changed"
    SYSTEM_WORKER_SHUTTING_DOWN = "system-worker-shutting-down"
    SYSTEM_WORKFLOW_LAUNCH_RESULT = "system-workflow-launch-result"
    SYSTEM_UNKNOWN_SUBTYPE = "system-unknown-subtype"
    SYSTEM_MISSING_SUBTYPE = "system-missing-subtype"
    SYSTEM_INVALID_SUBTYPE = "system-invalid-subtype"



_SYSTEM_FAMILIES = {
    family.name.removeprefix("SYSTEM_").lower(): family
    for family in ClaudeReadRefusalFamily
    if family.name.startswith("SYSTEM_")
    and family not in (ClaudeReadRefusalFamily.SYSTEM_UNKNOWN_SUBTYPE,
                       ClaudeReadRefusalFamily.SYSTEM_MISSING_SUBTYPE,
                       ClaudeReadRefusalFamily.SYSTEM_INVALID_SUBTYPE)
}


def read_system_observation_family(value: object) -> ClaudeReadRefusalFamily:
    """Project only exact pinned labels; this mapping does not accept records."""
    if type(value) is not dict or value.get("type") != "system":
        return ClaudeReadRefusalFamily.OTHER_RECORD
    if "subtype" not in value:
        return ClaudeReadRefusalFamily.SYSTEM_MISSING_SUBTYPE
    subtype = value["subtype"]
    if type(subtype) is not str:
        return ClaudeReadRefusalFamily.SYSTEM_INVALID_SUBTYPE
    return _SYSTEM_FAMILIES.get(subtype, ClaudeReadRefusalFamily.SYSTEM_UNKNOWN_SUBTYPE)
