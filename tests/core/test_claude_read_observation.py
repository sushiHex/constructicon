"""The pinned static label inventory is diagnostic vocabulary, not admission."""

import pytest

from constructicon.core.claude_read_observation import (
    ClaudeReadRefusalFamily,
    read_system_observation_family,
)

# Native SHA24972e3b / paired SDK SHAfc2866df, inventoried separately from
# consumer code. 69 constructor labels plus three schema-only declarations.
PINNED_SYSTEM_SUBTYPES = frozenset({
    "agents_killed", "api_error", "api_retry",
    "away_summary", "background_tasks_changed", "bridge_state",
    "bridge_status", "cloud_session_delta", "cloud_session_status",
    "code_change_published", "commands_changed", "compact_boundary",
    "control_request_progress", "dev_intent", "elicitation_complete",
    "feedback_draft_queued", "file_attachments_missing", "file_snapshot",
    "files_persisted", "hook_progress", "hook_response",
    "hook_started", "informational", "init",
    "init_milestone", "instruction_size_warning", "local_command",
    "local_command_output", "memory_recall", "memory_saved",
    "mirror_error", "model_consent_fallback", "model_fallback",
    "model_refusal_fallback", "model_refusal_no_fallback", "notification",
    "peer_message_hold", "per_turn_effort_changed", "permission_check_status",
    "permission_denied", "permission_retry", "plugin_install",
    "post_turn_summary", "scheduled_task_fire", "session_metadata",
    "session_state_changed", "session_title_changed", "status",
    "stop_hook_summary", "task_notification", "task_progress",
    "task_started", "task_summary", "task_updated",
    "thinking", "thinking_tokens", "tool_host_result",
    "turn_duration", "turn_handoff_available", "turn_preempted",
    "turn_starting", "ui_focus", "ui_invalidate",
    "ui_log", "ui_panes", "ui_scroll",
    "ui_status", "ui_toast", "upgrade_relay_marker",
    "vcs_state_changed", "worker_shutting_down", "workflow_launch_result",
})


def test_pinned_closed_system_inventory_is_complete_and_not_a_normalizer():
    actual = {family.name.removeprefix("SYSTEM_").lower()
              for family in ClaudeReadRefusalFamily
              if family.name.startswith("SYSTEM_")
              and family not in (ClaudeReadRefusalFamily.SYSTEM_UNKNOWN_SUBTYPE,
                                 ClaudeReadRefusalFamily.SYSTEM_MISSING_SUBTYPE,
                                 ClaudeReadRefusalFamily.SYSTEM_INVALID_SUBTYPE)}
    assert actual == PINNED_SYSTEM_SUBTYPES and len(actual) == 72
    for subtype in PINNED_SYSTEM_SUBTYPES:
        family = read_system_observation_family({"type": "system", "subtype": subtype})
        assert family.value == "system-" + subtype.replace("_", "-")
        for unknown in (subtype.upper(), " " + subtype, subtype + "_future"):
            assert read_system_observation_family({"type": "system", "subtype": unknown}) is (
                ClaudeReadRefusalFamily.SYSTEM_UNKNOWN_SUBTYPE)


@pytest.mark.parametrize("value,expected", [
    ({}, ClaudeReadRefusalFamily.OTHER_RECORD),
    ({"type": "system"}, ClaudeReadRefusalFamily.SYSTEM_MISSING_SUBTYPE),
    ({"type": "system", "subtype": None}, ClaudeReadRefusalFamily.SYSTEM_INVALID_SUBTYPE),
    ({"type": "system", "subtype": []}, ClaudeReadRefusalFamily.SYSTEM_INVALID_SUBTYPE),
    ({"type": "system", "subtype": "private-unknown"},
     ClaudeReadRefusalFamily.SYSTEM_UNKNOWN_SUBTYPE),
])
def test_unknown_shape_has_only_a_fixed_fallback(value, expected):
    assert read_system_observation_family(value) is expected
