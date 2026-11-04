"""Offline checks for the local Pi smoke acceptance contract."""

import pytest

from tests.substrate.test_real_pi_local_read import answer_matches, tool_text_matches


@pytest.mark.parametrize("answer", ["abc123", "  abc123\n", "```\nabc123\n```",
                                    "```text\r\nabc123\r\n```"])
def test_answer_accepts_only_value_or_one_fence(answer):
    assert answer_matches(answer, "abc123")


@pytest.mark.parametrize("answer", ["", "Here: abc123", "abc123 xyz",
                                    "```\nabc123\n```\nxyz",
                                    "```\nabc123\n```\n```\nxyz\n```",
                                    "```\nabc123\nxyz\n```", "`abc123`"])
def test_answer_rejects_prose_conflicts_and_partial_fences(answer):
    assert not answer_matches(answer, "abc123")


def test_tool_result_requires_exact_fixture_text():
    assert tool_text_matches([{"type": "text", "text": "abc123"}], "abc123")
    assert not tool_text_matches([{"type": "text", "text": "prefix abc123"}], "abc123")
    assert not tool_text_matches([{"type": "text", "text": "abc123"},
                                  {"type": "text", "text": "extra"}], "abc123")
    assert not tool_text_matches(None, "abc123")
