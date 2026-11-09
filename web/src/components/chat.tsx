"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Markdown } from "@/components/markdown";
import { detailMessage } from "@/lib/errors";
import type {
  ApprovalInfo,
  Conversation,
  ConversationStatus,
  Customer,
  SupportUIMessage,
  ToolStep,
  TranscriptItem,
} from "@/lib/types";
import { SPECIALIST_TITLES } from "@/lib/types";

const POLL_MS = 2500;
const RECOVER_ATTEMPTS = 12; // about 30 seconds of looking for a reply the broken stream didn't deliver

const SUGGESTIONS: Record<string, string[]> = {
  "maya.chen@example.com": ["My order #1042 arrived with two snapped tent poles. Can I get a refund?", "Can I still return the earbuds from order 1043?"],
  "jordan.alvarez@example.com": ["Where is my order 1044?", "I'd like to return the footprint from order 1047."],
  "priya.n@example.com": ["One of the tents in order 1045 has a torn rainfly. What are my options?"],
  "sam.okafor@example.com": ["Can I cancel order 1046?"],
  "leo.martins@example.com": ["My order 1048 never arrived. What can you do?"],
};

export function Chat() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversationStatus, setConversationStatus] = useState<ConversationStatus>("active");
  const [thinking, setThinking] = useState<string | null>(null);
  const [specialist, setSpecialist] = useState<string | null>(null);
  const [setupError, setSetupError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const conversationRef = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const transport = useMemo(() => new DefaultChatTransport<SupportUIMessage>({ api: "/api/chat" }), []);

  const { messages, setMessages, sendMessage, status, error, clearError } = useChat<SupportUIMessage>({
    id: conversationId ?? "no-conversation",
    transport,
    onData: (part) => {
      if (part.type === "data-status") setThinking(part.data.text);
      if (part.type === "data-conversation") setConversationStatus(part.data.status);
      if (part.type === "data-specialist") setSpecialist(part.data.title);
    },
    onFinish: () => setThinking(null),
    onError: () => setThinking(null),
  });

  // Reload the conversation from the server (the source of truth for approval outcomes).
  const refresh = useCallback(async () => {
    const id = conversationRef.current;
    if (!id) return;
    const res = await fetch(`/api/conversations/${id}`);
    if (!res.ok) return;
    const conversation = (await res.json()) as Conversation;
    if (conversationRef.current !== id) return;
    setConversationStatus(conversation.status);
    setSpecialist(conversation.specialist ? (SPECIALIST_TITLES[conversation.specialist] ?? null) : null);
    setMessages(toUIMessages(conversation.items));
  }, [setMessages]);

  useEffect(() => {
    fetch("/api/customers")
      .then(async (res) => {
        const body = await res.json();
        if (!res.ok) throw new Error(detailMessage(body, "Couldn't load customers"));
        setCustomers(body);
      })
      .catch((e: Error) => setSetupError(e.message));
  }, []);

  // When a reply finishes streaming, sync with the server's copy of the conversation.
  const previousStatus = useRef(status);
  useEffect(() => {
    if (previousStatus.current !== "ready" && status === "ready") refresh();
    previousStatus.current = status;
  }, [status, refresh]);

  // The agent saves its reply even when the stream to the browser breaks, so fetch that instead of showing an error.
  useEffect(() => {
    const id = conversationRef.current;
    if (status !== "error" || !error || !id || !isStreamFailure(error)) return;
    const sent = messages.filter((m) => m.role === "user").length;
    let cancelled = false;
    (async () => {
      for (let attempt = 0; attempt < RECOVER_ATTEMPTS && !cancelled; attempt++) {
        const res = await fetch(`/api/conversations/${id}`).catch(() => null);
        if (cancelled) return;
        if (res?.ok) {
          const conversation = (await res.json()) as Conversation;
          const saved = conversation.items.filter((item) => item.role === "user").length;
          if (cancelled) return;
          if (saved >= sent && conversation.items.at(-1)?.role !== "user") {
            setConversationStatus(conversation.status);
            setSpecialist(conversation.specialist ? (SPECIALIST_TITLES[conversation.specialist] ?? null) : null);
            setMessages(toUIMessages(conversation.items));
            clearError();
            return;
          }
        }
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status, error, messages, setMessages, clearError]);

  // While a refund or email is waiting for a supervisor, poll until the conversation resumes.
  useEffect(() => {
    if (conversationStatus !== "awaiting_approval" || status !== "ready") return;
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [conversationStatus, status, refresh]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, thinking]);

  async function signIn(email: string) {
    const selected = customers.find((c) => c.email === email) ?? null;
    setCustomer(selected);
    setConversationId(null);
    conversationRef.current = null;
    setMessages([]);
    clearError();
    if (!selected) return;
    const res = await fetch("/api/conversations", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ customer_email: selected.email }),
    });
    const body = await res.json();
    if (!res.ok) {
      setSetupError(detailMessage(body, "Couldn't start a conversation"));
      return;
    }
    conversationRef.current = body.id;
    setConversationId(body.id);
    setConversationStatus("active");
    setSpecialist(null);
  }

  function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || !conversationId) return;
    clearError();
    setThinking("Thinking");
    sendMessage({ text: trimmed }, { body: { conversationId } });
    setInput("");
  }

  const busy = status === "submitted" || status === "streaming";
  const waiting = conversationStatus === "awaiting_approval" && !busy;
  const canSend = !!conversationId && !busy && !waiting;

  return (
    <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col px-4">
      <div className="flex flex-wrap items-center gap-3 py-4 text-sm">
        <label htmlFor="customer" className="text-muted">
          Signed in as
        </label>
        <select
          id="customer"
          value={customer?.email ?? ""}
          onChange={(e) => signIn(e.target.value)}
          className="rounded-md border border-line bg-surface px-2 py-1.5"
        >
          <option value="">Choose a demo customer…</option>
          {customers.map((c) => (
            <option key={c.id} value={c.email}>
              {c.name} ({c.email})
            </option>
          ))}
        </select>
        {customer && (
          <button onClick={() => signIn(customer.email)} className="text-muted underline-offset-2 hover:underline">
            New conversation
          </button>
        )}
        {specialist && (
          <span className="rounded-full border border-line px-2 py-0.5 text-xs text-muted" title="The specialist answering">
            {specialist} specialist
          </span>
        )}
      </div>

      {setupError && <Banner tone="danger">{setupError}</Banner>}

      <div className="min-h-0 flex-1 overflow-y-auto pb-4" aria-live="polite">
        {!customer && !setupError && (
          <p className="mt-16 text-center text-muted">Pick a demo customer above to start chatting with the support agent.</p>
        )}
        {customer && messages.length === 0 && (
          <div className="mt-12 text-center">
            <p className="text-muted">Hi {customer.name.split(" ")[0]}, how can we help? Try:</p>
            <div className="mt-4 flex flex-col items-center gap-2">
              {(SUGGESTIONS[customer.email] ?? []).map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  disabled={!canSend}
                  className="max-w-md rounded-full border border-line bg-surface px-4 py-2 text-sm hover:border-accent disabled:opacity-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-col gap-4">
          {messages.map((message) => (
            <Message key={message.id} message={message} />
          ))}
          {busy && thinking && <p className="animate-pulse text-sm text-muted">{thinking}…</p>}
          {waiting && (
            <Banner tone="warn">
              A support supervisor is reviewing this request. The conversation will continue here once they decide.
            </Banner>
          )}
          {error && <Banner tone="danger">{errorMessage(error)}</Banner>}
        </div>
        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="flex gap-2 border-t border-line py-4"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={waiting ? "Waiting for review…" : customer ? "Write a message" : "Choose a customer first"}
          disabled={!canSend}
          aria-label="Message"
          className="flex-1 rounded-lg border border-line bg-surface px-3 py-2 outline-none focus:border-accent disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={!canSend || !input.trim()}
          className="rounded-lg bg-accent px-4 py-2 font-medium text-white disabled:opacity-40 dark:text-black"
        >
          Send
        </button>
      </form>
    </div>
  );
}

function Message({ message }: { message: SupportUIMessage }) {
  if (message.role === "user") {
    const text = message.parts.map((p) => (p.type === "text" ? p.text : "")).join("");
    return (
      <div className="ml-auto max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-accent px-4 py-2 text-white dark:text-black">
        {text}
      </div>
    );
  }
  return (
    <div className="flex max-w-[90%] flex-col gap-2">
      {message.parts.map((part, i) => {
        switch (part.type) {
          case "text":
            return part.text.trim() ? (
              <div key={i} className="prose-reply rounded-2xl rounded-bl-sm border border-line bg-surface px-4 py-3">
                <Markdown>{part.text}</Markdown>
              </div>
            ) : null;
          case "data-tool":
            return <ToolChip key={i} step={part.data} />;
          case "data-approval":
            return <ApprovalCard key={i} approval={part.data} />;
          case "data-sources":
            return (
              <p key={i} className="px-1 text-xs text-muted">
                Sources: {part.data.items.join(" · ")}
              </p>
            );
          case "data-notice":
            return (
              <Banner key={i} tone="danger">
                {part.data.message}
              </Banner>
            );
          default:
            return null;
        }
      })}
    </div>
  );
}

function ToolChip({ step }: { step: ToolStep }) {
  const icon = step.status === "running" ? "◌" : step.status === "error" ? "!" : "✓";
  return (
    <div className="flex items-center gap-2 px-1 text-xs text-muted">
      <span className={step.status === "running" ? "animate-spin" : step.status === "error" ? "text-danger" : "text-accent"}>
        {icon}
      </span>
      {step.label}
    </div>
  );
}

const APPROVAL_STATES: Record<ApprovalInfo["status"], { tone: "warn" | "ok" | "danger"; title: string }> = {
  pending: { tone: "warn", title: "Waiting for supervisor review" },
  approved: { tone: "ok", title: "Approved, processing" },
  executed: { tone: "ok", title: "Approved and completed" },
  rejected: { tone: "danger", title: "Rejected by a supervisor" },
  failed: { tone: "danger", title: "Approved, but it failed" },
};

function ApprovalCard({ approval }: { approval: ApprovalInfo }) {
  const state = APPROVAL_STATES[approval.status];
  return (
    <Banner tone={state.tone}>
      <p className="font-medium">
        {approval.toolName === "issue_refund" ? "Refund" : "Email"}: {state.title}
      </p>
      <p className="mt-1 text-sm opacity-90">{approval.summary}</p>
    </Banner>
  );
}

function Banner({ tone, children }: { tone: "warn" | "ok" | "danger"; children: React.ReactNode }) {
  const styles = {
    warn: "border-warn/30 bg-warn-soft text-warn",
    ok: "border-accent/30 bg-accent-soft text-accent",
    danger: "border-danger/30 bg-danger-soft text-danger",
  };
  return <div className={`rounded-lg border px-4 py-3 text-sm ${styles[tone]}`}>{children}</div>;
}

/** API refusals (rate limit, budget) arrive as a JSON body; anything else means the connection broke. */
function isStreamFailure(error: Error): boolean {
  try {
    JSON.parse(error.message);
    return false;
  } catch {
    return true;
  }
}

function errorMessage(error: Error): string {
  try {
    return detailMessage(JSON.parse(error.message), error.message);
  } catch {
    return error.message || "Something went wrong.";
  }
}

/** Convert the server transcript into chat messages: each run of agent output becomes one assistant message. */
function toUIMessages(items: TranscriptItem[]): SupportUIMessage[] {
  const messages: SupportUIMessage[] = [];
  let assistant: SupportUIMessage | null = null;
  items.forEach((item, i) => {
    if (item.role === "user") {
      assistant = null;
      messages.push({ id: `m${i}`, role: "user", parts: [{ type: "text", text: item.text }] });
      return;
    }
    if (!assistant) {
      assistant = { id: `m${i}`, role: "assistant", parts: [] };
      messages.push(assistant);
    }
    if (item.role === "assistant") {
      assistant.parts.push({ type: "text", text: item.text, state: "done" });
      if (item.sources.length) assistant.parts.push({ type: "data-sources", data: { items: item.sources } });
    } else {
      assistant.parts.push({ type: "data-tool", data: { name: item.name, label: item.label, status: "done" } });
      if (item.approval) {
        assistant.parts.push({
          type: "data-approval",
          data: { id: item.approval.id, toolName: item.name, summary: item.approval.summary, status: item.approval.status },
        });
      }
    }
  });
  return messages;
}
