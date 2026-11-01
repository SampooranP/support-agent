# Support Agent

An AI customer-support agent that answers from a company knowledge base, takes real actions through MCP tools, asks a human before risky actions, and is measured with an automated eval suite.

> 🚧 Work in progress. See the [roadmap](#roadmap).

## How it works

1. A customer asks a question (e.g. "My order #1042 arrived damaged, can I get a refund?").
2. The agent plans its steps and **searches the support docs (RAG)** for the relevant policy.
3. It calls **MCP tools** to look up the order and customer.
4. Risky actions (refunds, emails) **pause for human approval** in a dashboard.
5. It replies to the customer, citing the policy it used.

Every run is traced, and an **eval suite** scores the agent on a set of test tickets.

## Features

- **RAG over documents**: ingestion pipeline (load → chunk → embed → store) with pgvector search and reranking
- **MCP server**: `get_order`, `get_customer`, `create_ticket`, `issue_refund`, `send_email`
- **Human-in-the-loop**: approve/reject dashboard for risky tool calls
- **Evals**: test tickets scored on correct action, grounding, answer quality (LLM-as-judge) and safety
- **Observability**: tracing of every model and tool call, with cost and latency
- **Streaming UI**: live chat replies and tool-status updates

## Tech stack

| Layer | Choice |
|---|---|
| Agent | Claude Agent SDK / LangGraph |
| Models | Anthropic Claude |
| Database & vectors | Supabase Postgres + pgvector |
| Tools | Custom MCP server |
| Frontend | Next.js + Vercel AI SDK |
| Tracing | Langfuse |
| DevOps | Docker, GitHub Actions (evals on every PR), AWS |

## Repository layout

```
ingestion/    load, chunk, embed docs → pgvector
mcp-server/   order, customer, ticket, refund and email tools
agent/        agent loop, prompts, approval logic, memory
web/          chat UI + approvals dashboard
evals/        test tickets, scoring scripts, results
docs/         sample company knowledge base
```

## Roadmap

- [ ] Sample knowledge base + ingestion pipeline + basic RAG Q&A
- [ ] MCP server with order and customer tools
- [ ] Human approval flow, dashboard and streaming chat UI
- [ ] Eval suite, tracing, guardrails and CI
- [ ] Multi-agent routing (billing / shipping / tech support), deployment

## Eval results

_Coming soon._
