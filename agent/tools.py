"""The agent's tools: what Claude sees, the guardrails around them, and how they run.

Tools come from two places:
- search_knowledge_base runs locally (RAG over doc_chunks) and returns search_result
  blocks, so Claude's answers carry citations to the source docs.
- Everything else is on the MCP server. The agent adjusts what Claude sees: customer
  identity, conversation ID and approval IDs are filled in by the agent, never by the
  model, and every order is checked against the signed-in customer.

Risky tools (issue_refund, send_email) aren't run when Claude calls them. The agent
checks the request, records it as an approval, and runs it only after a human approves.
"""

import json
import sys
from dataclasses import dataclass
from typing import Any

import anyio
import jsonschema
from mcp import Client, StdioServerParameters

from ingestion.config import REPO_ROOT, require_env
from ingestion.embedder import embed_query
from ingestion.store import match_chunks

MCP_SERVER = REPO_ROOT / "mcp-server" / "server.py"

RISKY_TOOLS = {"issue_refund", "send_email"}


def mcp_server_params() -> StdioServerParameters:
    """The MCP client gives a server process only a few safe variables like PATH, so pass the ones it needs.
    Locally the server would also find them in .env, but containers and CI have no .env."""
    env = {name: require_env(name) for name in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")}
    return StdioServerParameters(command=sys.executable, args=[str(MCP_SERVER)], env=env)


SEARCH_TOOL = {
    "name": "search_knowledge_base",
    "description": (
        "Search Lumen & Pine's support documents: FAQ, refund policy, shipping policy, and product manuals "
        "(Trailhead 2P tent, Ember electric kettle, Drift earbuds). Returns the most relevant passages with "
        "their source. Search before answering any policy, shipping, or product question."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "What to look up, in plain words."}},
        "required": ["query"],
        "additionalProperties": False,
    },
}

# What Claude sees for each MCP tool: parameters the agent fills in are removed from the schema.
HIDDEN_PARAMS = {
    "get_customer": {"email", "customer_id"},
    "create_ticket": {"customer_email", "conversation_id"},
    "issue_refund": {"approval_id"},
    "send_email": {"to", "approval_id"},
}
DESCRIPTION_OVERRIDES = {
    "get_customer": "Look up the signed-in customer's profile, Trail Rewards points, and recent orders.",
    "send_email": "Email the signed-in customer. A support agent reviews the email before it's sent.",
}
STATUS_LABELS = {
    "search_knowledge_base": "Searching the help center",
    "get_order": "Looking up order",
    "get_customer": "Looking up your account",
    "create_ticket": "Opening a support ticket",
    "issue_refund": "Requesting a refund",
    "send_email": "Drafting an email",
}


@dataclass
class ToolResult:
    content: Any  # str, or a list of content blocks
    is_error: bool = False

    def as_block(self, tool_use_id: str) -> dict:
        block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": self.content}
        if self.is_error:
            block["is_error"] = True
        return block


@dataclass
class ApprovalNeeded:
    tool_name: str
    tool_input: dict
    summary: str


class Toolbox:
    def __init__(self, mcp: Client, mcp_tools: list):
        self.mcp = mcp
        self.definitions = [SEARCH_TOOL] + [self._claude_definition(t) for t in mcp_tools]
        self.schemas = {d["name"]: d["input_schema"] for d in self.definitions}

    @classmethod
    async def connect(cls, mcp: Client) -> "Toolbox":
        return cls(mcp, (await mcp.list_tools()).tools)

    def claude_tools(self) -> list[dict]:
        # eager_input_streaming streams tool inputs as they're generated; validate() checks them.
        return [{**d, "eager_input_streaming": True} for d in self.definitions]

    def validate(self, name: str, tool_input: Any) -> str | None:
        """Return an error message if the input doesn't match the tool's schema."""
        if name not in self.schemas:
            return f"Unknown tool {name}."
        try:
            jsonschema.validate(tool_input, self.schemas[name])
        except jsonschema.ValidationError as e:
            return f"Invalid input for {name}: {e.message}"
        return None

    async def run(self, name: str, tool_input: dict, conversation: dict, approval_id: str | None = None) -> ToolResult:
        """Run a tool for the signed-in customer. Risky tools must come with an approval_id."""
        email = conversation["customer_email"]
        if name == "search_knowledge_base":
            return await self._search(tool_input["query"])
        if name == "get_order":
            return await self._get_own_order(tool_input["order_number"], email)
        if name == "get_customer":
            return await self._call("get_customer", {"email": email})
        if name == "create_ticket":
            if tool_input.get("order_number"):
                owned = await self._get_own_order(tool_input["order_number"], email)
                if owned.is_error:
                    return owned
            return await self._call("create_ticket", {
                **tool_input, "customer_email": email, "conversation_id": conversation["id"],
            })
        if name in RISKY_TOOLS:
            if not approval_id:
                raise RuntimeError(f"{name} needs a human approval before it runs")
            args = {**tool_input, "approval_id": approval_id}
            if name == "send_email":
                args["to"] = email
            return await self._call(name, args)
        return ToolResult(f"Unknown tool {name}.", is_error=True)

    async def check_risky(self, name: str, tool_input: dict, conversation: dict) -> ApprovalNeeded | ToolResult:
        """Check a risky request before it goes to a human. Returns what to approve, or an error for Claude."""
        email = conversation["customer_email"]
        if name == "issue_refund":
            order = await self._get_own_order(tool_input["order_number"], email)
            if order.is_error:
                return order
            details = json.loads(order.content)
            amount = round(float(tool_input["amount"]), 2)
            if amount <= 0 or amount > details["total"]:
                return ToolResult(
                    f"Refund amount must be between 0 and the order total ({details['total']} {details['currency']}).",
                    is_error=True,
                )
            normalized = {**tool_input, "order_number": str(details["order_number"]), "amount": amount}
            summary = (
                f"Refund {amount:.2f} {details['currency']} on order #{details['order_number']} "
                f"(order total {details['total']:.2f}) for {details['customer']['name']}: {tool_input['reason']}"
            )
            return ApprovalNeeded(name, normalized, summary)
        if name == "send_email":
            summary = f"Email {email}: \"{tool_input['subject']}\""
            return ApprovalNeeded(name, {**tool_input, "to": email}, summary)
        raise ValueError(f"{name} isn't a risky tool")

    async def _search(self, query: str) -> ToolResult:
        chunks = await anyio.to_thread.run_sync(lambda: match_chunks(embed_query(query), match_count=5))
        if not chunks:
            return ToolResult("No matching documents found.")
        return ToolResult([
            {
                "type": "search_result",
                "source": chunk["source"],
                "title": f"{chunk['source']} - {chunk['section']}" if chunk["section"] else chunk["source"],
                "content": [{"type": "text", "text": chunk["content"]}],
                "citations": {"enabled": True},
            }
            for chunk in chunks
        ])

    async def _get_own_order(self, order_number: str, email: str) -> ToolResult:
        result = await self._call("get_order", {"order_number": order_number})
        if result.is_error:
            return result
        if json.loads(result.content)["customer"]["email"] != email:
            # Same message as a missing order, so other customers' order numbers can't be probed.
            return ToolResult(f"No order {order_number} found on this customer's account.", is_error=True)
        return result

    async def _call(self, name: str, args: dict) -> ToolResult:
        result = await self.mcp.call_tool(name, args)
        if result.structured_content is not None and not result.is_error:
            text = json.dumps(result.structured_content, default=str)
        else:
            text = "\n".join(getattr(block, "text", "") for block in result.content) or "(no output)"
        return ToolResult(text, is_error=bool(result.is_error))

    @staticmethod
    def _claude_definition(tool) -> dict:
        schema = json.loads(json.dumps(tool.input_schema))  # deep copy
        hidden = HIDDEN_PARAMS.get(tool.name, set())
        schema["properties"] = {k: v for k, v in schema.get("properties", {}).items() if k not in hidden}
        schema["required"] = [r for r in schema.get("required", []) if r not in hidden]
        schema["additionalProperties"] = False
        schema.pop("title", None)
        return {
            "name": tool.name,
            "description": DESCRIPTION_OVERRIDES.get(tool.name, tool.description or ""),
            "input_schema": schema,
        }
