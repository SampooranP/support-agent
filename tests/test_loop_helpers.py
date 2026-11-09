import asyncio
from types import SimpleNamespace

from agent import store
from agent.loop import (
    EMPTY_REPLY,
    INTERRUPTED,
    Agent,
    _cited_sources,
    _close_dangling_tool_uses,
    _history_content,
    transcript,
)
from agent.pricing import cost_usd


async def _no_check(*_):
    pass


class Block(SimpleNamespace):
    def model_dump(self, **_):
        return {k: v for k, v in vars(self).items()}


def test_history_drops_declined_attempt_before_a_fallback():
    blocks = [
        Block(type="thinking", thinking="x"),
        Block(type="tool_use", id="t_old", name="get_order", input={}),
        Block(type="fallback"),
        Block(type="text", text="Hi"),
        Block(type="tool_use", id="t_new", name="get_order", input={}),
    ]
    content, tool_uses = _history_content(blocks)
    assert [b["type"] for b in content] == ["fallback", "text", "tool_use"]
    assert [t.id for t in tool_uses] == ["t_new"]


def test_dangling_tool_use_gets_an_error_result():
    conversation = {"status": "active", "messages": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}]},
    ]}
    _close_dangling_tool_uses(conversation)
    result = conversation["messages"][-1]["content"][0]
    assert result == {"type": "tool_result", "tool_use_id": "t1", "content": INTERRUPTED, "is_error": True}


def test_paused_conversation_is_left_alone():
    conversation = {"status": "awaiting_approval", "messages": [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "issue_refund", "input": {}}]},
    ]}
    _close_dangling_tool_uses(conversation)
    assert len(conversation["messages"]) == 1


def test_transcript_orders_text_tool_steps_and_sources():
    citation = {"type": "search_result_location", "title": "refund-policy.md - Return window", "source": "refund-policy.md"}
    conversation = {"messages": [
        {"role": "user", "content": "Can I return it?"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Let me check."},
            {"type": "tool_use", "id": "t1", "name": "issue_refund", "input": {}},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Yes, within 30 days.", "citations": [citation]}]},
    ]}
    approvals = [{"tool_use_id": "t1", "id": "a1", "status": "pending", "summary": "Refund 10.00"}]
    items = transcript(conversation, approvals)
    assert [i["role"] for i in items] == ["user", "assistant", "tool", "assistant"]
    assert items[2]["approval"]["status"] == "pending"
    assert items[3]["sources"] == ["refund-policy.md - Return window"]


def test_cited_sources_are_unique_and_ordered():
    blocks = [
        {"type": "text", "text": "a", "citations": [{"title": "B"}, {"title": "A"}]},
        {"type": "text", "text": "b", "citations": [{"title": "B"}]},
        {"type": "tool_use"},
    ]
    assert _cited_sources(blocks) == ["B", "A"]


def run_turn(monkeypatch, content, stop_reason):
    monkeypatch.setattr(store, "get_customer_by_email", lambda _: {"name": "Maya", "email": "maya@example.com"})
    monkeypatch.setattr(store, "save_conversation", lambda _: None)
    agent = Agent(None, None)

    async def reply(*_):
        return SimpleNamespace(content=content, stop_reason=stop_reason)

    agent._stream = reply
    events = []

    async def emit(event):
        events.append(event)

    conversation = {"status": "active", "customer_email": "maya@example.com", "created_at": "2026-11-09T00:00:00",
                    "messages": [{"role": "user", "content": "hi"}]}
    asyncio.run(agent._run(conversation, emit))
    return conversation["messages"][-1], events


def test_an_empty_or_thinking_only_reply_is_never_kept(monkeypatch):
    for content in ([], [Block(type="thinking", thinking="x")], [Block(type="text", text="  ")]):
        last, events = run_turn(monkeypatch, content, "end_turn")
        assert last == {"role": "assistant", "content": EMPTY_REPLY}
        assert {"type": "text", "delta": EMPTY_REPLY} in events


def test_a_cut_off_tool_call_keeps_no_thinking_only_reply(monkeypatch):
    content = [Block(type="thinking", thinking="x"), Block(type="tool_use", id="t1", name="get_order", input={})]
    last, _ = run_turn(monkeypatch, content, "max_tokens")
    assert last == {"role": "assistant", "content": EMPTY_REPLY}


def test_a_normal_reply_is_stored_unchanged(monkeypatch):
    monkeypatch.setattr(Agent, "_check_reply", _no_check)
    last, _ = run_turn(monkeypatch, [Block(type="text", text="Hello")], "end_turn")
    assert last == {"role": "assistant", "content": [{"type": "text", "text": "Hello"}]}


def test_cost_includes_cache_rates():
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_input_tokens": 1_000_000,
             "cache_creation_input_tokens": 1_000_000}
    # Opus 5.5: $4 in + $2 out + $0.20 cache read + $5 cache write (1.25x input)
    assert round(cost_usd("claude-opus-5-5", usage), 4) == 11.2
    assert cost_usd("unknown-model", usage) is None
