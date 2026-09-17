"""Tests for app.services.ai.assistant's tool-use loop, using a fake Anthropic client (no
network calls, no API key needed) so the orchestration logic is fully covered without hitting
the real Claude API. Tool execution itself is real (against the seeded SQLite `db_session`
fixture), so these tests also verify the loop wires real tool results back to the model
correctly, and that every tool call is audit-logged into `agent_actions`.
"""

import pytest

from app.models.agent_action import AgentAction
from app.models.user import User
from app.services.ai.assistant import (
    MAX_TOOL_ROUNDS,
    AssistantError,
    ask_assistant,
)


class FakeTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, id, name, input):  # noqa: A002
        self.id = id
        self.name = name
        self.input = input


class FakeResponse:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeMessages.create called more times than the test expected")
        return self._responses.pop(0)


class FakeAnthropicClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def _seed_user(db_session):
    user = User(name="Dana Analyst", email="dana-ai@example.com", department="Engineering")
    db_session.add(user)
    db_session.commit()
    return user


def test_ask_assistant_calls_tool_then_answers(db_session):
    _seed_user(db_session)
    fake = FakeAnthropicClient(
        [
            FakeResponse(
                content=[FakeToolUseBlock("tool_1", "get_team_metrics", {"department": "Engineering"})],
                stop_reason="tool_use",
            ),
            FakeResponse(
                content=[FakeTextBlock("Team efficiency looks steady this week.")],
                stop_reason="end_turn",
            ),
        ]
    )

    result = ask_assistant(db_session, "How is my team doing?", client=fake)

    assert result.answer == "Team efficiency looks steady this week."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_team_metrics"
    assert result.tool_calls[0].input == {"department": "Engineering"}
    # the tool actually ran against real data — the result is a real dict, not a stub
    assert "overall_efficiency_score" in result.tool_calls[0].result
    assert len(fake.messages.calls) == 2  # one round of tool use, one round of final answer


def test_ask_assistant_logs_agent_action(db_session):
    _seed_user(db_session)
    fake = FakeAnthropicClient(
        [
            FakeResponse(
                content=[FakeToolUseBlock("tool_1", "get_team_metrics", {})],
                stop_reason="tool_use",
            ),
            FakeResponse(content=[FakeTextBlock("Answer.")], stop_reason="end_turn"),
        ]
    )

    ask_assistant(db_session, "How is my team doing?", client=fake)

    logged = db_session.query(AgentAction).all()
    assert len(logged) == 1
    assert logged[0].agent_type == "performance_analyst"
    assert logged[0].action == "get_team_metrics"
    assert logged[0].approved is True
    assert "How is my team doing" in logged[0].reason


def test_ask_assistant_handles_parallel_tool_calls_in_one_round(db_session):
    _seed_user(db_session)
    fake = FakeAnthropicClient(
        [
            FakeResponse(
                content=[
                    FakeToolUseBlock("tool_1", "get_team_metrics", {}),
                    FakeToolUseBlock("tool_2", "get_overdue_tasks", {}),
                ],
                stop_reason="tool_use",
            ),
            FakeResponse(content=[FakeTextBlock("Combined answer.")], stop_reason="end_turn"),
        ]
    )

    result = ask_assistant(db_session, "Overview please", client=fake)

    assert result.answer == "Combined answer."
    assert {c.name for c in result.tool_calls} == {"get_team_metrics", "get_overdue_tasks"}
    assert db_session.query(AgentAction).count() == 2


def test_ask_assistant_unknown_tool_returns_error_without_crashing(db_session):
    _seed_user(db_session)
    fake = FakeAnthropicClient(
        [
            FakeResponse(
                content=[FakeToolUseBlock("tool_1", "delete_everything", {})],
                stop_reason="tool_use",
            ),
            FakeResponse(content=[FakeTextBlock("I can't do that.")], stop_reason="end_turn"),
        ]
    )

    result = ask_assistant(db_session, "Delete all tasks", client=fake)

    assert result.tool_calls[0].result == {"error": "Unknown tool: delete_everything"}
    assert result.answer == "I can't do that."


def test_ask_assistant_tool_exception_becomes_error_result(db_session):
    _seed_user(db_session)
    # get_employee_metrics requires employee_id; omitting it raises TypeError inside the tool,
    # which _execute_tool must catch and turn into an {"error": ...} dict, not propagate.
    fake = FakeAnthropicClient(
        [
            FakeResponse(
                content=[FakeToolUseBlock("tool_1", "get_employee_metrics", {})],
                stop_reason="tool_use",
            ),
            FakeResponse(content=[FakeTextBlock("Something went wrong.")], stop_reason="end_turn"),
        ]
    )

    result = ask_assistant(db_session, "Tell me about employee", client=fake)

    assert "error" in result.tool_calls[0].result


def test_ask_assistant_empty_question_raises(db_session):
    with pytest.raises(AssistantError):
        ask_assistant(db_session, "   ", client=FakeAnthropicClient([]))


def test_ask_assistant_refusal_raises(db_session):
    fake = FakeAnthropicClient([FakeResponse(content=[], stop_reason="refusal")])
    with pytest.raises(AssistantError):
        ask_assistant(db_session, "How is my team doing?", client=fake)


def test_ask_assistant_gives_up_after_max_rounds(db_session):
    _seed_user(db_session)
    responses = [
        FakeResponse(content=[FakeToolUseBlock(f"t{i}", "get_team_metrics", {})], stop_reason="tool_use")
        for i in range(MAX_TOOL_ROUNDS)
    ]
    fake = FakeAnthropicClient(responses)

    with pytest.raises(AssistantError):
        ask_assistant(db_session, "How is my team doing?", client=fake)

    assert len(fake.messages.calls) == MAX_TOOL_ROUNDS


def test_ask_assistant_no_final_text_falls_back_to_placeholder(db_session):
    fake = FakeAnthropicClient([FakeResponse(content=[], stop_reason="end_turn")])
    result = ask_assistant(db_session, "How is my team doing?", client=fake)
    assert result.answer == "I couldn't produce an answer."


def test_ask_assistant_missing_api_key_raises(db_session, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "ANTHROPIC_API_KEY", "")
    with pytest.raises(AssistantError, match="ANTHROPIC_API_KEY"):
        ask_assistant(db_session, "How is my team doing?")
