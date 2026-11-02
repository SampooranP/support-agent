"""The specialists a conversation can be routed to, and what each may do.

Every specialist runs the same agent loop with the same system prompt and the same declared
tools, so the conversation's prompt prefix never changes when the specialist does (an edited
prefix breaks the prompt cache, and on Claude 5.5 models invalidates earlier thinking blocks).
What differs is appended instead: a note telling Claude which specialist it now is, added
after the customer message that caused the switch, and a per-specialist tool allowlist the
loop enforces in code.
"""

from dataclasses import dataclass

SEARCH, ORDER, CUSTOMER, TICKET, REFUND, EMAIL = (
    "search_knowledge_base", "get_order", "get_customer", "create_ticket", "issue_refund", "send_email",
)


@dataclass(frozen=True)
class Specialist:
    name: str
    title: str  # shown in the chat UI
    handles: str  # for the router, and in the note to Claude
    tools: frozenset[str]


SPECIALISTS = {s.name: s for s in [
    Specialist("billing", "Billing", "refunds, returns, exchanges, cancellations, charges and payments, gift cards",
               frozenset({SEARCH, ORDER, CUSTOMER, TICKET, REFUND, EMAIL})),
    Specialist("shipping", "Shipping", "order tracking, delivery times and costs, address changes, late or lost "
               "packages, international shipping", frozenset({SEARCH, ORDER, CUSTOMER, TICKET, EMAIL})),
    Specialist("tech_support", "Tech support", "product setup and troubleshooting, error codes, care and repairs, "
               "warranty claims for items that broke after use", frozenset({SEARCH, ORDER, CUSTOMER, TICKET})),
    Specialist("general", "General", "account and Trail Rewards questions, general store FAQ, and anything that "
               "fits none of the other teams", frozenset({SEARCH, ORDER, CUSTOMER, TICKET})),
]}
DEFAULT = "general"


def handoff_note(specialist: Specialist) -> str:
    """The note appended to the conversation when it's routed to a specialist."""
    tools = ", ".join(sorted(specialist.tools))
    return (
        f"This conversation is now with the {specialist.title} specialist: {specialist.handles}. "
        f"You can use these tools: {tools}. Other tools belong to other specialists; if the customer needs one, "
        "explain what you can do here, and they'll be routed to the right specialist when they ask for it."
    )


def not_allowed(specialist: Specialist, tool_name: str) -> str:
    """The tool result for a call outside the specialist's allowlist."""
    return f"{tool_name} isn't available to the {specialist.title} specialist. Don't retry it in this conversation turn."
