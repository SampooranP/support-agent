import yaml

from agent.loop import (
    REFUSAL_REPLY,
    REFUSED_MESSAGE,
    _close_dangling_tool_uses,
    _mark_refused_turn,
    _request_messages,
    transcript,
)
from agent.router import ROUTER_SYSTEM, customer_messages
from agent.specialists import SPECIALISTS, handoff_note
from evals.route_eval import ADVERSARIAL_ROUTES, grid_route
from evals.run_evals import CASES, GENERATED

NOTE = handoff_note(SPECIALISTS["billing"])
HISTORY = [
    {"role": "user", "content": "My tent arrived damaged."},
    {"role": "system", "content": NOTE},
    {"role": "assistant", "content": [{"type": "text", "text": "Sorry to hear that."}]},
    {"role": "user", "content": "Photos attached."},
]


def test_models_with_system_messages_get_the_history_unchanged():
    assert _request_messages(HISTORY, "claude-opus-5-5") is HISTORY


def test_haiku_gets_each_note_on_the_customer_message_before_it():
    out = _request_messages(HISTORY, "claude-haiku-5-5")
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert out[0]["content"] == [
        {"type": "text", "text": "My tent arrived damaged."},
        {"type": "text", "text": f"<operator_note>{NOTE}</operator_note>"},
    ]
    assert HISTORY[0]["content"] == "My tent arrived damaged."  # the stored history isn't touched
    # Append-only: converting a longer history gives the same messages up front.
    longer = HISTORY + [{"role": "system", "content": handoff_note(SPECIALISTS["shipping"])}]
    assert _request_messages(longer, "claude-haiku-5-5")[:2] == out[:2]


def test_a_note_left_without_a_reply_is_closed_by_an_assistant_turn():
    conversation = {"status": "active", "messages": HISTORY[:2]}
    _close_dangling_tool_uses(conversation)
    assert conversation["messages"][-1]["role"] == "assistant"


def test_notes_are_not_customer_text_or_shown_in_the_chat():
    assert customer_messages(HISTORY) == ["My tent arrived damaged.", "Photos attached."]
    assert [i["role"] for i in transcript({"messages": HISTORY}, [])] == ["user", "assistant", "user"]


def test_a_refused_turn_is_hidden_from_claude_but_stays_in_the_chat():
    tool_use = {"type": "tool_use", "id": "t1", "name": "get_order", "input": {}}
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": [{"type": "text", "text": "Hi!"}]},
        {"role": "user", "content": "Something harmful"},
        {"role": "system", "content": NOTE},
        {"role": "assistant", "content": [tool_use]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Partial reply"}]},
    ]
    _mark_refused_turn(messages)
    messages.append({"role": "user", "content": "Where is my order?"})

    sent = _request_messages(messages, "claude-sonnet-5-5")
    assert sent == [
        messages[0],
        messages[1],
        {"role": "user", "content": REFUSED_MESSAGE},
        {"role": "system", "content": NOTE},
        {"role": "assistant", "content": REFUSAL_REPLY},
        messages[-1],
    ]
    assert customer_messages(messages) == ["Hello", "Where is my order?"]
    shown = [i.get("text") for i in transcript({"messages": messages}, []) if i["role"] in ("user", "assistant")]
    assert "Something harmful" in shown and "Partial reply" in shown


def test_only_billing_can_refund_and_every_specialist_can_search():
    assert {s.name for s in SPECIALISTS.values() if "issue_refund" in s.tools} == {"billing"}
    assert all("search_knowledge_base" in s.tools for s in SPECIALISTS.values())
    assert all(s.name in ROUTER_SYSTEM for s in SPECIALISTS.values())


def test_every_route_label_names_a_specialist():
    labels = [c["route"] for c in yaml.safe_load(CASES.read_text(encoding="utf-8"))]
    labels += list(ADVERSARIAL_ROUTES.values())
    labels += [grid_route(c) for c in yaml.safe_load((GENERATED / "grid.yaml").read_text(encoding="utf-8"))]
    assert all(labels) and {name for label in labels for name in label} <= set(SPECIALISTS)


def test_grid_routes():
    assert grid_route({"id": "grid-kettle-d22-damaged-photos", "tags": ["refunds", "past-all-windows"]}) == [
        "billing", "tech_support"]
    assert grid_route({"id": "grid-kettle-d2-damaged-photos", "tags": ["refunds", "in-damage-window"]}) == ["billing"]
    assert grid_route({"id": "grid-kettle-address-fresh", "tags": ["orders", "address"]}) == ["shipping"]
    assert grid_route({"id": "grid-kettle-lost", "tags": ["shipping", "lost", "escalation"]}) == ["shipping"]
