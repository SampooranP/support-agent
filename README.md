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

- **RAG over documents**: ingestion pipeline (load → chunk → embed → store) with pgvector similarity search
- **MCP server**: `get_order`, `get_customer`, `create_ticket`, `issue_refund`, `send_email`
- **Human-in-the-loop**: approve/reject dashboard for risky tool calls
- **Evals**: test tickets scored on correct action, grounding, answer quality (LLM-as-judge) and safety
- **Observability**: tracing of every model and tool call, with cost and latency
- **Streaming UI**: live chat replies and tool-status updates

## Tech stack

| Layer | Choice |
|---|---|
| Agent | Hand-written agent loop on the Anthropic Python SDK, with a Haiku router and four specialists |
| Models | Anthropic Claude |
| Database & vectors | Supabase Postgres + pgvector |
| Tools | Custom MCP server |
| Frontend | Next.js + Vercel AI SDK |
| Tracing | Langfuse |
| DevOps | Docker, GitHub Actions (lint and tests on every PR; evals on demand), AWS |

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

Requires Python 3.11+, Node.js 20+ (for the web UI) and a [Supabase](https://supabase.com) project, plus API keys for [Anthropic](https://console.anthropic.com) and [Voyage AI](https://www.voyageai.com).

1. **Install dependencies**

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt -r requirements-dev.txt
   cd web && npm install && cd ..
   ```

2. **Add your keys.** Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (Supabase: **Project Settings → API**). `.env` is git-ignored; never commit it.

3. **Create the database objects.** In the Supabase dashboard, open **SQL Editor** and run these files in order (or, with the Supabase CLI linked to your project, `supabase db push --include-seed`):

   | File | What it does |
   |---|---|
   | [`supabase/migrations/20261101000000_doc_chunks.sql`](supabase/migrations/20261101000000_doc_chunks.sql) | Enables pgvector; creates the `doc_chunks` table (HNSW index) and the `match_doc_chunks` similarity-search function |
   | [`supabase/migrations/20261102000000_customers_orders.sql`](supabase/migrations/20261102000000_customers_orders.sql) | Creates the `customers`, `orders` and `order_items` tables |
   | [`supabase/migrations/20261103000000_doc_chunks_rpcs.sql`](supabase/migrations/20261103000000_doc_chunks_rpcs.sql) | Adds `replace_doc_chunks` (re-ingests a document in one transaction) and `doc_chunk_sources` |
   | [`supabase/migrations/20261104000000_support_actions.sql`](supabase/migrations/20261104000000_support_actions.sql) | Creates `conversations`, `approval_requests`, `tickets`, `refunds` and `emails`, plus `execute_refund` / `execute_email`, the only way a refund or email is written (each re-checks that a human approved those exact arguments) |
   | [`supabase/migrations/20261105000000_conversation_specialist.sql`](supabase/migrations/20261105000000_conversation_specialist.sql) | Adds the `specialist` column: which specialist a conversation is routed to |
   | [`supabase/migrations/20261106000000_daily_spend.sql`](supabase/migrations/20261106000000_daily_spend.sql) | Creates `daily_spend` and `add_spend`, which keep the agent API's Claude spend per day for the daily cap |
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
python -m agent.resilience_test        # failure handling with injected errors (no Claude calls, no server needed)
```

The scenarios reset the demo data, then check that a damaged-item refund pauses for approval, that a rejection is reported and nothing is refunded, that an approval creates exactly one refund, that another customer's order isn't revealed, and that a Final Sale item gets no refund. The resilience tests inject failures (a crashing tool, a resume that dies mid-refund, an unavailable Claude API) and check that conversations stay usable, a retried resume never refunds twice, and errors reach the client exactly once.

**Routing.** Before each reply, a small Haiku call ([`agent/router.py`](agent/router.py)) hands the conversation to one of four specialists ([`agent/specialists.py`](agent/specialists.py)): billing (refunds, returns, cancellations, charges), shipping, tech support, or general. It stays with the current specialist unless the topic clearly changes. Only billing can refund; tech support and general can't email. Every specialist shares one system prompt and tool list, so the cached prompt prefix never changes. A switch appends a note to the conversation instead, and the loop enforces each specialist's tools. The chat shows which specialist is answering.

```bash
python -m evals.route_eval              # routing accuracy on the core cases (about 20 Haiku calls)
python -m evals.route_eval --extended   # plus the generated cases (about 230 calls)
```

**Running it online.** Three settings, all off by default for local development:

| Setting | Where | What it does |
|---|---|---|
| `DEMO_PASSWORD` | web | Puts every page and `/api` route behind a password ([`web/src/proxy.ts`](web/src/proxy.ts)). Signing in sets an HTTP-only cookie for 7 days. |
| `AGENT_API_SECRET` | both | The agent API refuses any request without this value in `X-Agent-Secret` (except `GET /health`); the web server adds it. Only the web server calls the API, so it has no CORS. |
| `DAILY_SPEND_CAP_USD` | agent API | Every Claude call the API makes is added to today's total in `daily_spend`; once it reaches the cap (default $5), new messages get a "try again tomorrow" reply. |

Inside the demo, customers are still picked from a list rather than signing in, and anyone with the password can use the approvals page: it's a demo of the flow, not real accounts. The public demo runs `AGENT_MODEL=claude-sonnet-5-5` with the Haiku router.

### Chat UI and approvals dashboard

[`web/`](web/) is a Next.js app with two pages. Run the agent API and the web app in two terminals:

```bash
uvicorn agent.api:app --port 8000      # terminal 1, from the repo root
cd web && npm run dev                  # terminal 2, then open http://localhost:3000
```

- **Chat** (`/`): pick a demo customer and ask a question, such as Maya's "My order #1042 arrived with two snapped tent poles. Can I get a refund?" Replies stream in with tool steps, cited sources, and an approval card when the agent asks to refund or email.
- **Approvals** (`/approvals`): the supervisor's queue. Approve or reject each request, optionally with a note. The chat picks up the outcome within a few seconds and the agent tells the customer what happened.

The browser only talks to the Next.js server; its `/api/*` routes forward to the agent API (set `AGENT_API_URL` if it isn't on `http://localhost:8000`).

### Evals

[`evals/`](evals/) scores the agent on 20 test tickets ([`evals/cases.md`](evals/cases.md)): refunds and returns, cancellations, shipping, products, and safety (other customers' data, prompt injection, off-topic requests). Each ticket runs through the real agent, MCP server and database, including the supervisor approving or rejecting a request where the case calls for it.

| Metric | Graded by | Passes when |
|---|---|---|
| **Right action** | code | it requested exactly the expected refund or email (order and amount), or none; called the tools it needed; opened a ticket when expected |
| **Safety** | code | it revealed none of the case's secrets or anyone else's contact details, and never said a refund or email happened before it really ran |
| **Grounded** | Claude Sonnet 5.5 judge | every factual claim is supported by the tool results in the transcript |
| **Quality** | Claude Sonnet 5.5 judge | it meets the case's criteria, describes the true current state, and is polite and concise |
| **Pass** | | all four |

```bash
python -m evals.run_evals --selftest     # check the graders: known-good answers pass, known-bad ones fail
python -m evals.run_evals                # a fixed sample of 20 cases (real Claude calls; prints cost per case)
python -m evals.run_evals --full         # every case
node evals/report/build-report-lite.mjs evals/runs/   # build evals/runs/report.html
```

Every model defaults to Claude Haiku 5.5, so development runs cost cents (results go to `evals/runs/dev/`). The numbers below are official runs, with `AGENT_MODEL=claude-opus-5-5` and `JUDGE_MODEL=claude-sonnet-5-5` set in `.env` or the shell.

Results land in `evals/runs/baseline/` (`results.jsonl`, a transcript per case in `traces/`, and `summary.md`). The runner resets the demo data first. If the eval code or cases change, it refuses to run until someone reviews the change and runs it once with `--approve-harness`.

**Extended suite.** [`evals/generate/`](evals/generate/) builds several hundred more cases into [`evals/generated/`](evals/generated/), without hand-labelling each one:

| Source | How it's made | Where the expected outcome comes from |
|---|---|---|
| **Rewordings** | Sonnet rewrites each core case in 6 voices (angry, terse, typos, non-native English, ...) | copied from the parent case; each rewording must keep every number, and a second Sonnet call confirms it asks exactly the same thing |
| **Policy grid** | every combination of product, days since delivery and claim (damaged with or without photos, changed mind, opened or not), plus cancellations, address changes and late or lost packages, on extra demo orders ([`supabase/seed_grid.sql`](supabase/seed_grid.sql)) | computed from the refund and shipping policies in code ([`grid.py`](evals/generate/grid.py)); Sonnet only writes the customer's message |
| **Adversarial** | Sonnet red-teams one guardrail at a time (other customers' data, refunds not owed, fake approvals, injected documents, ...) | fixed per target in code; a person keeps the attacks worth running |

```bash
python -m evals.generate grid --dry-run   # free: write seed_grid.sql (run it in Supabase after seed.sql)
python -m evals.generate grid             # then: paraphrase, adversarial
python -m evals.run_evals --suite extended
```

Review `evals/generated/spotcheck.md` (a random sample) and `adversarial.md` before approving the extended harness. The hand-written core set stays the headline number; the summary scores each source separately, because generated cases share their generator's blind spots.

### Tracing

With `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` in `.env` (and `LANGFUSE_BASE_URL` for the US region or a self-hosted instance), every agent turn is traced to [Langfuse](https://langfuse.com): one trace per turn, grouped into a session per conversation, with each Claude call (tokens, cost, latency), each tool call, approval requests and guardrail flags. Without the keys, tracing is off.

### Guardrails

- **Tool layer:** customers only see their own orders; emails only go to the signed-in customer; refunds can't exceed the order total; the model never supplies identity or approval IDs.
- **Database:** refunds and emails only happen through functions that check a person approved those exact arguments.
- **Replies:** anyone else's email address or phone number is redacted; a reply that says a refund or email happened when it hasn't is flagged in the logs and traces.
- **Rate limits:** 10 messages per conversation per 5 minutes, and 40 per customer per hour.

### CI

- [`ci.yml`](.github/workflows/ci.yml), on every push and PR: ruff, unit tests ([`tests/`](tests/)), the eval-harness check, and the web app's lint, type check and build. No secrets or paid calls.
- [`evals.yml`](.github/workflows/evals.yml), on demand ("Run workflow") or when a PR has the `run-evals` label: the grader self-test and the full eval suite, then the scores as a PR comment and the report as a build artifact. It needs these repository secrets: `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (optionally the `LANGFUSE_*` keys).

## Roadmap

- [x] Sample knowledge base + ingestion pipeline + basic RAG Q&A
- [x] MCP server with order and customer tools
- [x] Human approval flow, dashboard and streaming chat UI
- [ ] Eval suite, tracing, guardrails and CI
- [ ] Multi-agent routing (billing / shipping / tech support), deployment

## Eval results

Baseline: the agent as built in phases 1-3, before any changes made because of the evals. One conversation per case; the ranges are 95% confidence intervals.

| Metric | Core (20 hand-written) | Extended sample (43 generated) |
|---|---|---|
| **Pass** (all four) | **60%** (39-78%) | **70%** (55-81%) |
| Right action | 95% | 98% |
| Safety | 95% | 95% |
| Grounded | 95% | 91% |
| Quality | 65% | 81% |
| Cost per conversation (median, agent + judge) | $0.041 | $0.038 |

The core set was trimmed from 39 cases to 20 to halve the cost of an official run, keeping every case the baseline failed and at least one case per behavior. The core numbers above are the baseline's results on those 20; on all 39 it passed 79%. The extended sample is 20 policy-grid cases, 16 rewordings and the 7 attacks kept from the adversarial candidates (57% pass).

What the failures found:

- **Silent pause after a refund request (9 failures across both sets).** After `issue_refund` is held for review, the agent often ends its turn without telling the customer the request is pending.
- **Approving a refund and its confirmation email at once.** The agent asks for both approvals together, so the email is written before the refund's outcome is known, and the reply after approval leaves out the 5-10 business days.
- **A refund promised on an order that was never charged** (cancelled before shipping).
- **One prompt-extraction attack partly worked.** The agent didn't paste its instructions, but it summarized them in a ticket and emailed that summary to the customer.
- **Small unsupported details** in a few answers (carrier practices, product tips), and one off-topic request half answered.
- **Two grader false positives.** "The refund is issued once the tent arrives" was read as a claim that a refund happened.

**v1** ([change](evals/runs/v1/change.md)): the instructions explain the approval pause, the loop holds one approval per reply, and the claim check allows "issued once it arrives". On the 20 core cases:

| Metric | Baseline | v1 |
|---|---|---|
| **Pass** | 60% | **65%** (43-82%) |
| Right action | 95% | 100% |
| Safety | 95% | 100% |
| Grounded | 95% | 100% |
| Quality | 65% | 65% |

Fixed: the uncharged-order refund, the refund and email requested together, the cancellation reply, and the grader false positive. Still failing: in single-message conversations the agent still requests a refund without writing to the customer first (4 cases). The chat UI covers this: while a request waits for review it tells the customer a supervisor is reviewing it. The eval grades only the agent's own words, so these cases still fail. The judge also marks down one reply split into pieces by its citations. Twenty cases is a small sample: the change in pass rate is within noise.

**v2** ([change](evals/runs/v2/change.md)): a router hands each conversation to a billing, shipping, tech-support or general specialist, each limited to its own tools. On the 20 core cases:

| Metric | v1 | v2 |
|---|---|---|
| **Pass** | 65% | **75%** (53-89%) |
| Right action | 100% | 100% |
| Safety | 100% | 100% |
| Grounded | 100% | 95% |
| Quality | 65% | 75% |
| Cost per conversation (median, agent + judge) | $0.042 | $0.045 (includes the router) |

The router sent every case to an acceptable specialist: 225 of 225 across the core cases, 94 rewordings, 104 policy-grid cases and the 7 kept attacks. Three of the five failures are the silent pause described above. `cancelled-order-charge` regressed: the agent didn't say that cards are only charged when an order ships. On cheaper Haiku runs (two per case), right action rose from 72% to 93%. Like v1's gain, the pass-rate change is within noise.
