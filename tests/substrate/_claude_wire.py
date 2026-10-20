"""Credential-free source-derived CLI 2.1.296 settings/hooks wire bodies.

Tmt B@233045214 supplies summaries; JLo B@233062267 publishes all 33 rows
in insertion order and adds FileChanged's matcher support. These are source
fixtures, not a vendor recording, complete tool inventory or qualification.
"""

from __future__ import annotations

from copy import deepcopy

MODEL = "claude-sonnet-4-6"
_EVENTS = (
    ("PreToolUse", "Before tool execution", True),
    ("PostToolUse", "After tool execution", True),
    ("PostToolUseFailure", "After tool execution fails", True),
    ("PostToolBatch", "After a batch of tool calls resolves", False),
    ("PermissionDenied", "After auto mode classifier denies a tool call", True),
    ("Notification", "When notifications are sent", True),
    ("UserPromptSubmit", "When the user submits a prompt", False),
    ("UserPromptExpansion", "When a user-typed slash command expands into a prompt", True),
    ("SessionStart", "When a new session is started", True),
    ("Stop", "Right before Claude concludes its response", False),
    ("StopFailure", "When the turn ends due to an API error", True),
    ("SubagentStart", "When a subagent (Agent tool call) is started", True),
    ("SubagentStop", "Right before a subagent (Agent tool call) concludes its response", True),
    ("PreCompact", "Before conversation compaction", True),
    ("PostCompact", "After conversation compaction", True),
    ("PreModelSwitch", "Before a requested model switch (/model, model picker, set_model)", True),
    ("PostModelSwitch", "After the session model changes (any cause)", True),
    ("SessionEnd", "When a session is ending", True),
    ("PermissionRequest", "When a permission dialog is displayed", True),
    ("Setup", "Repo setup hooks for init and maintenance", True),
    ("TeammateIdle", "When a teammate is about to go idle", False),
    ("TaskCreated", "When a task is being created", False),
    ("TaskCompleted", "When a task is being marked as completed", False),
    ("Elicitation", "When an MCP server requests user input (elicitation)", True),
    ("ElicitationResult", "After a user responds to an MCP elicitation", True),
    ("ConfigChange", "When configuration files change during a session", True),
    ("InstructionsLoaded", "When an instruction file (CLAUDE.md or rule) is loaded", True),
    ("WorktreeCreate", "Create an isolated worktree for VCS-agnostic isolation", False),
    ("WorktreeRemove", "Remove a previously created worktree", False),
    ("CwdChanged", "After the working directory changes", False),
    ("FileChanged", "When a watched file changes", True),
    ("DirectoryAdded", "After a working directory is added mid-session", True),
    ("MessageDisplay", "While assistant message text is displayed", False),
)


def settings_body(*, model=MODEL, effort="high"):
    policy = {"forceRemoteSettingsRefresh": True,
              "deniedMcpServers": [{"serverUrl": "*"}]}
    return {"effective": deepcopy(policy), "sources": [
        {"source": "policySettings", "settings": deepcopy(policy)}],
        "applied": {"model": model, "effort": effort, "advisor": None,
                    "ultracode": False, "ultracodeRequested": False,
                    "ultracodeAvailable": False}}


def hooks_body():
    return {"events": [], "hooks": [], "eventCatalog": [
        {"name": name, "summary": summary, "supportsMatcher": matcher}
        for name, summary, matcher in _EVENTS],
        "policy": {"disabledByPolicy": False, "managedOnly": False,
                   "pluginOnly": False, "allDisabled": False, "policyHookCount": 0},
        "safeMode": {"managedHooksStillApply": True,
                     "exitHint": "restart without --safe-mode"}}
