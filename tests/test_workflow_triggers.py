"""Every workflow trigger is a GitHub Actions event.

GitHub rejects a whole workflow file for one unknown event, and the rejection
shows only as a failed run with no jobs: PR #212's public-text workflow never
ran because ``commit_comment`` is a webhook event, not an Actions trigger.
"""

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).parents[1] / ".github" / "workflows").glob("*.y*ml"))

# From https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
# as read on 2026-10-16.
ACTIONS_EVENTS = frozenset({
    "branch_protection_rule", "check_run", "check_suite", "create", "delete",
    "deployment", "deployment_status", "discussion", "discussion_comment", "fork",
    "gollum", "image_version", "issue_comment", "issues", "label", "merge_group",
    "milestone", "page_build", "public", "pull_request", "pull_request_review",
    "pull_request_review_comment", "pull_request_target", "push", "registry_package",
    "release", "repository_dispatch", "schedule", "status", "watch", "workflow_call",
    "workflow_dispatch", "workflow_run",
})


def triggers(text: str) -> list[str]:
    """The event names of a workflow written in the mapping form, ``on:`` alone."""
    block = re.search(r"^on:\n((?:[ #].*\n|\n)*)", text, re.M)
    assert block is not None, "write triggers in the mapping form: `on:` on its own line"
    return re.findall(r"^  ([A-Za-z_]+):", block[1], re.M)


def test_the_workflow_set_is_not_empty() -> None:
    assert len(WORKFLOWS) >= 4


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_every_trigger_is_an_actions_event(workflow: Path) -> None:
    events = triggers(workflow.read_text(encoding="utf-8"))
    assert events, "no triggers found"
    assert set(events) <= ACTIONS_EVENTS, set(events) - ACTIONS_EVENTS


def test_an_unknown_event_and_the_scalar_form_are_refused() -> None:
    assert triggers("on:\n  commit_comment:\n  push:\n\njobs:\n") == ["commit_comment", "push"]
    with pytest.raises(AssertionError):
        triggers("on: push\n")
