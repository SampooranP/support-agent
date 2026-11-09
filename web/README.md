# web

Next.js chat UI with streaming replies, plus the approvals dashboard. See the [main README](../README.md#chat-ui-and-approvals-dashboard) for how to run it.

- `src/app/page.tsx`: chat. Pick a demo customer, then chat with the agent. Replies stream in with tool steps ("Looking up order #1042"), cited sources, and approval cards for refunds and emails. While a request waits for review, the page polls until the conversation resumes.
- `src/app/approvals/page.tsx`: the review queue. Approve or reject pending refunds and emails, with an optional note for the agent.
- `src/app/tickets/page.tsx`: the support tickets the agent has opened, newest first.
- `src/app/api/*`: server routes that forward to the Python agent API (`AGENT_API_URL`, default `http://localhost:8000`). `api/chat` translates the agent's event stream into the Vercel AI SDK's UI message stream for `useChat`.

Built with Next.js 16, React 19, Tailwind CSS 4 and the Vercel AI SDK 7.
