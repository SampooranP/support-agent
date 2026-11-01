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
supabase/     database migrations
```

## Setup

Requires Python 3.11+ and a [Supabase](https://supabase.com) project, plus API keys for [Anthropic](https://console.anthropic.com) and [Voyage AI](https://www.voyageai.com).

1. **Install dependencies**

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Add your keys.** Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (Supabase: **Project Settings → API**). `.env` is git-ignored; never commit it.

3. **Create the database objects.** In the Supabase dashboard, open **SQL Editor** and run these files in order (or, with the Supabase CLI linked to your project, `supabase db push --include-seed`):

   | File | What it does |
   |---|---|
   | [`supabase/migrations/20261101000000_doc_chunks.sql`](supabase/migrations/20261101000000_doc_chunks.sql) | Enables pgvector; creates the `doc_chunks` table (HNSW index) and the `match_doc_chunks` similarity-search function |
   | [`supabase/migrations/20261102000000_customers_orders.sql`](supabase/migrations/20261102000000_customers_orders.sql) | Creates the `customers`, `orders` and `order_items` tables |
   | [`supabase/migrations/20261103000000_doc_chunks_rpcs.sql`](supabase/migrations/20261103000000_doc_chunks_rpcs.sql) | Adds `replace_doc_chunks` (re-ingests a document in one transaction) and `doc_chunk_sources` |
   | [`supabase/migrations/20261104000000_support_actions.sql`](supabase/migrations/20261104000000_support_actions.sql) | Creates `conversations`, `approval_requests`, `tickets`, `refunds` and `emails`, plus `execute_refund` / `execute_email`, the only way a refund or email is written (each re-checks that a human approved those exact arguments) |
   | [`supabase/seed.sql`](supabase/seed.sql) | Creates `reset_demo_data()` and runs it to load 5 sample customers and 8 orders. The function wipes and reloads those tables, which keeps the order dates fresh; the smoke test calls it before each run. It refuses to run if the tables hold anything other than the demo records. Development only. |

   Every table has row-level security on with no policies, so only the service-role key (used by the backend) can access it.

## Run

Run these from the repo root.

**Ingest the knowledge base** (load → chunk → embed with Voyage `voyage-3.5` → store in Supabase). Re-running replaces each document's chunks, so it's safe to run after editing `docs/`.

```bash
python -m ingestion.ingest --dry-run   # preview the chunks; no API calls
python -m ingestion.ingest
```

**Ask a question.** The script embeds the question, retrieves the top 5 chunks by cosine similarity, and has Claude answer with citations to the source docs.

```bash
python -m agent.rag_qa "My order arrived damaged, can I get a refund?"
python -m agent.rag_qa --show-chunks "How long does expedited shipping take?"
python -m agent.rag_qa                 # interactive mode
```

Example output:

```
$ python -m agent.rag_qa "My Ember kettle display shows E1, what do I do?"
An **E1** code means the kettle was switched on empty or with too little water.[1]

To fix it, let it cool for 15 minutes, add water above the MIN line, and try again.[1] Just be careful
not to go too far: never fill above the MAX line.[2] Overfilled water can spray out when it boils.[2]

If the E1 code keeps appearing even with the right amount of water, please contact our support team.

Sources:
  [1] products/ember-electric-kettle.md - Troubleshooting
  [2] products/ember-electric-kettle.md - Safety warnings
```

Questions the docs don't cover (e.g. "What's your CEO's name?") get an "I don't have that information" answer that points to support, rather than a guess.

> **Voyage free tier:** without a payment method on your Voyage account, requests are limited to 3 per minute. Ingestion embeds all chunks in a single request and the client retries with backoff when rate-limited, so everything still works, but asking several questions in a row can pause for a few seconds.

### MCP server

[`mcp-server/server.py`](mcp-server/server.py) exposes the support tools over the [Model Context Protocol](https://modelcontextprotocol.io), backed by the Supabase tables:

| Tool | Input | Returns |
|---|---|---|
| `get_order` | order number (`1042` or `#1042`) | status, shipping, tracking, amounts, dates, line items (with Final Sale flag), customer, plus `hours_since_placed` and `days_since_delivery` |
| `get_customer` | `email` or `customer_id` | profile, Trail Rewards points, and up to 20 recent orders |
| `create_ticket` | subject, description, priority, optional order and customer | the new ticket (numbered from 5001) |
| `issue_refund` | order number, amount, reason, `approval_id` | the refund record. **Needs a human approval** |
| `send_email` | recipient, subject, body, `approval_id` | the email record (recorded, not actually sent). **Needs a human approval** |

Errors come back as messages the model can act on (for example, "No order #9999 found"). `issue_refund` and `send_email` only work with the ID of an approval a person approved for exactly those arguments; the database enforces this, so even a buggy agent can't refund without a human.

```bash
python mcp-server/smoke_test.py   # reloads the demo data, launches the server over stdio, checks each tool
python mcp-server/server.py       # run the server on stdio (normally started by an MCP client)
```

To try the tools from Claude Code, register the server with absolute paths, so it starts no matter which folder Claude Code runs in (on Windows the interpreter is `.venv\Scripts\python.exe`):

```bash
claude mcp add lumen-pine-support -- /path/to/support-agent/.venv/bin/python /path/to/support-agent/mcp-server/server.py
```

### Agent API (with human approval)

[`agent/api.py`](agent/api.py) is the agent behind the chat UI. It streams Claude's replies, searches the knowledge base (with citations) and calls the MCP tools, which it launches itself.

When Claude asks to refund or send an email, the agent doesn't run the tool. It records an approval request and pauses the conversation. Once a supervisor approves or rejects it, the agent runs the approved action (or not), tells Claude the outcome, and the conversation continues. Paused conversations are stored in Supabase, so they survive restarts.

Guardrails in [`agent/tools.py`](agent/tools.py): customers can only see their own orders, emails only go to the signed-in customer, refunds can't exceed the order total, and the model never sees or supplies identity or approval IDs.

```bash
uvicorn agent.api:app --port 8000      # start the API (http://localhost:8000/docs for the endpoint list)
python -m agent.scenario_test          # in another terminal: end-to-end scenarios with real Claude calls
```

The scenarios reset the demo data, then check that a damaged-item refund pauses for approval, that a rejection is reported and nothing is refunded, that an approval creates exactly one refund, that another customer's order isn't revealed, and that a Final Sale item gets no refund.

> **No authentication yet:** the demo signs in by picking a customer, and the approval endpoints are open. Fine on localhost; authentication comes before deployment.

## Roadmap

- [x] Sample knowledge base + ingestion pipeline + basic RAG Q&A
- [x] MCP server with order and customer tools
- [ ] Human approval flow, dashboard and streaming chat UI
- [ ] Eval suite, tracing, guardrails and CI
- [ ] Multi-agent routing (billing / shipping / tech support), deployment

## Eval results

_Coming soon._
