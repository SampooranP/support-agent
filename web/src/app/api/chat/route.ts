import { createUIMessageStream, createUIMessageStreamResponse } from "ai";

import { agentFetch, jsonInit, readEvents } from "@/lib/agent-api";
import type { ConversationStatus, SupportUIMessage, ToolStep } from "@/lib/types";

// A reply streams for as long as the agent works (several model and tool calls); allow up to 5 minutes on Vercel.
export const maxDuration = 300;

// Events from the Python agent API (see agent/api.py).
type AgentEvent =
  | { type: "status"; text: string }
  | { type: "retry" }
  | { type: "text"; delta: string }
  | { type: "tool"; name: string; status: ToolStep["status"]; label?: string }
  | { type: "route"; specialist: string; title: string }
  | { type: "approval"; id: string; tool_name: string; summary: string }
  | { type: "sources"; items: string[] }
  | { type: "error"; message: string }
  | { type: "guardrail"; kind: string; message?: string }
  | { type: "done"; status: ConversationStatus };

/**
 * Sends the newest user message to the agent API and translates its event stream
 * into the AI SDK's UI message stream, which useChat renders.
 */
export async function POST(req: Request) {
  const { messages, conversationId } = (await req.json()) as {
    messages: SupportUIMessage[];
    conversationId?: string;
  };
  if (!conversationId) {
    return Response.json({ detail: "Missing conversationId" }, { status: 400 });
  }
  const text = (messages.at(-1)?.parts ?? [])
    .map((part) => (part.type === "text" ? part.text : ""))
    .join("")
    .trim();

  const upstream = await agentFetch(
    `/conversations/${encodeURIComponent(conversationId)}/messages`,
    jsonInit("POST", { text }),
  );
  if (!upstream.ok || !upstream.body) {
    const error = await upstream.json().catch(() => ({}));
    return Response.json({ detail: error.detail ?? "The agent API returned an error" }, { status: upstream.status });
  }
  const body = upstream.body;

  const stream = createUIMessageStream<SupportUIMessage>({
    async execute({ writer }) {
      writer.write({ type: "start" });

      let textId: string | null = null;
      let segment = 0;
      let inStep = false;
      const toolParts = new Map<string, { id: string; label: string }>(); // running tool name -> its part

      const endText = () => {
        if (textId) writer.write({ type: "text-end", id: textId });
        textId = null;
      };
      // Each model call is a step, so a retried call can discard just its own partial output.
      const endStep = () => {
        endText();
        if (inStep) writer.write({ type: "finish-step" });
        inStep = false;
      };

      for await (const event of readEvents<AgentEvent>(body)) {
        switch (event.type) {
          case "status":
            endStep();
            writer.write({ type: "start-step" });
            inStep = true;
            writer.write({ type: "data-status", data: { text: event.text }, transient: true });
            break;
          case "retry":
            // The agent is re-sending a model call: remove the text the failed attempt streamed.
            textId = null;
            writer.write({ type: "reset-step" });
            break;
          case "text":
            if (!textId) {
              textId = `text-${segment++}`;
              writer.write({ type: "text-start", id: textId });
            }
            writer.write({ type: "text-delta", id: textId, delta: event.delta });
            break;
          case "tool": {
            endText();
            if (event.status === "running") {
              const part = { id: `tool-${segment++}`, label: event.label ?? event.name };
              toolParts.set(event.name, part);
              writer.write({ type: "data-tool", id: part.id, data: { name: event.name, label: part.label, status: "running" } });
            } else {
              // Same id as the "running" part, so the SDK updates that step in place.
              const part = toolParts.get(event.name);
              if (part) {
                writer.write({ type: "data-tool", id: part.id, data: { name: event.name, label: part.label, status: event.status } });
                toolParts.delete(event.name);
              }
            }
            break;
          }
          case "route":
            writer.write({ type: "data-specialist", data: { name: event.specialist, title: event.title }, transient: true });
            break;
          case "approval": {
            endText();
            // The request step is finished; the approval card below it shows what happens next.
            const part = toolParts.get(event.tool_name);
            if (part) {
              writer.write({ type: "data-tool", id: part.id, data: { name: event.tool_name, label: part.label, status: "done" } });
              toolParts.delete(event.tool_name);
            }
            writer.write({
              type: "data-approval",
              id: `approval-${event.id}`,
              data: { id: event.id, toolName: event.tool_name, summary: event.summary, status: "pending" },
            });
            break;
          }
          case "sources":
            writer.write({ type: "data-sources", id: `sources-${segment++}`, data: { items: event.items } });
            break;
          case "error":
            endText();
            writer.write({ type: "data-notice", id: `notice-${segment++}`, data: { message: event.message } });
            break;
          case "guardrail":
            // Only guardrails with a customer-facing message are shown; the rest are internal flags.
            if (event.message) {
              endText();
              writer.write({ type: "data-notice", id: `notice-${segment++}`, data: { message: event.message } });
            }
            break;
          case "done":
            endStep();
            writer.write({ type: "data-conversation", data: { status: event.status }, transient: true });
            break;
        }
      }
      endStep();
    },
  });

  return createUIMessageStreamResponse({ stream });
}
