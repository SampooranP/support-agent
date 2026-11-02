v2: a router hands each conversation to a specialist (billing, shipping, tech support, general)

- Router: one Haiku call per customer message picks the specialist from the last few customer messages,
  keeping the current one unless the topic clearly changes. If the call fails, the conversation stays with
  the current specialist.
- Specialists: same system prompt and declared tools for all of them, so the prompt prefix never changes.
  A switch appends a note after the customer's message (a system message; on Haiku, a text block on that
  message). Each specialist's tool limits are enforced in the loop: only billing can refund; tech support
  and general can't email.
- Prompt: the date is the conversation's start date, not today's, so a conversation that crosses midnight
  keeps the same prompt.
- Runner: router cost is counted in the agent cost, and each result records the route per customer message.
