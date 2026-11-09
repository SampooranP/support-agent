"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AlertIcon, CheckIcon, ClockIcon, DocumentIcon, RefreshIcon, SendIcon, SpinnerIcon } from "@/components/icons";
import { Markdown } from "@/components/markdown";
import { Badge, Banner, OutcomeBadge, SkeletonRows } from "@/components/ui";
import { findScenario, storyFor, type DemoCustomer } from "@/lib/demo-customers";
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

export function Chat() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customersLoaded, setCustomersLoaded] = useState(false);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversationStatus, setConversationStatus] = useState<ConversationStatus>("active");
  const [thinking, setThinking] = useState<string | null>(null);
  const [specialist, setSpecialist] = useState<string | null>(null);
  const [setupError, setSetupError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const conversationRef = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const customersRequested = useRef(false);

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

  const signIn = useCallback(
    async (selected: Customer | null) => {
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
    },
    [setMessages, clearError],
  );

  useEffect(() => {
    if (customersRequested.current) return;
    customersRequested.current = true;
    fetch("/api/customers")
      .then(async (res) => {
        const body: Customer[] = await res.json();
        if (!res.ok) throw new Error(detailMessage(body, "Couldn't load customers"));
        setCustomers(body);

        // A "Try this" link on the customers page signs in and fills the message box. Sending stays with the visitor, because it's a real AI call.
        const found = findScenario(new URLSearchParams(window.location.search).get("scenario"));
        const selected = found && body.find((c) => c.email === found.customer.email);
        if (!found || !selected) return;
        window.history.replaceState(null, "", "/");
        await signIn(selected);
        setInput(found.scenario.prompt);
      })
      .catch((e: Error) => setSetupError(e.message))
      .finally(() => setCustomersLoaded(true));
  }, [signIn]);

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
  const story = customer ? storyFor(customer.email) : undefined;

  return (
    <div className="flex min-h-0 flex-1">
      <aside className="hidden w-72 shrink-0 flex-col overflow-y-auto border-r border-line bg-surface-2 p-3 lg:flex">
        <div className="flex items-baseline justify-between px-2 pb-2 pt-1">
          <h2 className="text-sm font-semibold">Demo customers</h2>
          <Link href="/customers" className="text-link text-xs">
            Their stories
          </Link>
        </div>
        <CustomerList customers={customers} loaded={customersLoaded} selected={customer} onSelect={signIn} />
      </aside>

      <section aria-label="Conversation" className="flex min-w-0 flex-1 flex-col">
        {customer && (
          <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface px-4 py-2 md:px-6">
            <label htmlFor="customer" className="sr-only">
              Signed in as
            </label>
            <select
              id="customer"
              value={customer.email}
              onChange={(e) => signIn(customers.find((c) => c.email === e.target.value) ?? null)}
              className="field w-auto! max-w-[60%] lg:hidden"
            >
              {customers.map((c) => (
                <option key={c.id} value={c.email}>
                  {c.name}
                </option>
              ))}
            </select>
            <div className="hidden min-w-0 lg:block">
              <p className="truncate text-sm font-medium">{customer.name}</p>
              <p className="truncate text-xs text-muted">{customer.email}</p>
            </div>
            {specialist && <Badge tone="ok">{specialist} specialist</Badge>}
            <button onClick={() => signIn(customer)} className="btn btn-secondary ml-auto">
              <RefreshIcon />
              <span className="sm:hidden">New</span>
              <span className="hidden sm:inline">New conversation</span>
            </button>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto" aria-live="polite">
          <div className="mx-auto w-full max-w-2xl px-4 py-6">
            {setupError && (
              <div className="mb-4">
                <Banner tone="danger">{setupError}</Banner>
              </div>
            )}

            {!customer && (
              <div className="lg:mt-16 lg:text-center">
                <h1 className="text-2xl font-semibold tracking-tight">Talk to the support agent</h1>
                <p className="mt-2 text-muted">
                  <span className="lg:hidden">Pick a customer to play. </span>
                  <span className="hidden lg:inline">Pick a customer on the left to play. </span>
                  Each one has real orders and a problem to solve, and every refund or email waits for a person to approve it.
                </p>
                <div className="mt-5 lg:hidden">
                  <CustomerList customers={customers} loaded={customersLoaded} selected={customer} onSelect={signIn} />
                </div>
              </div>
            )}

            {customer && messages.length === 0 && story && (
              <div className="lg:mt-10">
                <h1 className="text-xl font-semibold tracking-tight">Hi {customer.name.split(" ")[0]}, how can we help?</h1>
                <p className="mt-1 text-sm text-muted">Write your own message, or start with one of these.</p>
                <ul className="mt-4 divide-y divide-line rounded-xl border border-line bg-surface">
                  {story.scenarios.slice(0, 3).map((scenario) => (
                    <li key={scenario.id}>
                      <button
                        onClick={() => send(scenario.prompt)}
                        disabled={!canSend}
                        className="flex w-full cursor-pointer flex-col items-start gap-1.5 px-4 py-3 text-left text-sm transition-colors duration-150 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <span>{scenario.prompt}</span>
                        <OutcomeBadge outcome={scenario.outcome} />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex flex-col gap-5">
              {messages.map((message) => (
                <Message key={message.id} message={message} />
              ))}
              {busy && thinking && (
                <p className="flex items-center gap-2 text-sm text-muted">
                  <SpinnerIcon className="animate-spin" />
                  {thinking}…
                </p>
              )}
              {waiting && (
                <p className="text-sm text-muted">
                  A support supervisor is reviewing this request. The conversation continues here once they decide.{" "}
                  <Link href="/approvals" className="text-link">
                    Open Approvals to decide
                  </Link>
                </p>
              )}
              {error && <Banner tone="danger">{errorMessage(error)}</Banner>}
            </div>
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="shrink-0 px-4 pb-4">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className="mx-auto flex w-full max-w-2xl items-center gap-2 rounded-xl border border-line-strong bg-surface p-1.5 shadow-card transition-[border-color,box-shadow] duration-150 focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--accent-soft)]"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={waiting ? "Waiting for review…" : customer ? "Write a message" : "Choose a customer first"}
              disabled={!canSend}
              aria-label="Message"
              className="composer-input min-w-0 flex-1 bg-transparent px-2.5 py-1.5 outline-none disabled:cursor-not-allowed"
            />
            <button type="submit" disabled={!canSend || !input.trim()} className="btn btn-primary">
              <SendIcon />
              Send
            </button>
          </form>
        </div>
      </section>

      {story && <CaseFile story={story} disabled={!canSend} onPick={setInput} />}
    </div>
  );
}

function CustomerList({
  customers,
  loaded,
  selected,
  onSelect,
}: {
  customers: Customer[];
  loaded: boolean;
  selected: Customer | null;
  onSelect: (customer: Customer) => void;
}) {
  if (!loaded) return <SkeletonRows count={5} className="h-14" />;
  return (
    <ul className="flex flex-col gap-0.5">
      {customers.map((c) => {
        const active = selected?.email === c.email;
        return (
          <li key={c.id}>
            <button
              onClick={() => onSelect(c)}
              aria-pressed={active}
              className={`w-full cursor-pointer rounded-lg px-2 py-2 text-left transition-colors duration-150 ${
                active ? "bg-accent-soft" : "hover:bg-line/60"
              }`}
            >
              <span className={`block text-sm font-medium ${active ? "text-accent" : ""}`}>{c.name}</span>
              <span className="block text-xs text-muted">{storyFor(c.email)?.summary ?? c.email}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function CaseFile({ story, disabled, onPick }: { story: DemoCustomer; disabled: boolean; onPick: (prompt: string) => void }) {
  return (
    <aside aria-label="Case file" className="hidden w-80 shrink-0 flex-col gap-6 overflow-y-auto border-l border-line bg-surface-2 p-4 xl:flex">
      <div>
        <h2 className="text-sm font-semibold">Orders on file</h2>
        <ul className="mt-2 flex flex-col gap-3">
          {story.orders.map((order) => (
            <li key={order.number} className="text-sm">
              <div className="flex items-baseline justify-between gap-3 font-mono tabular-nums">
                <span>#{order.number}</span>
                <span>{order.total}</span>
              </div>
              <p className="mt-0.5">{order.items}</p>
              <p className="text-xs text-muted">{order.status}</p>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h2 className="text-sm font-semibold">Scenarios</h2>
        <ul className="mt-1 flex flex-col">
          {story.scenarios.map((scenario) => (
            <li key={scenario.id}>
              <button
                onClick={() => onPick(scenario.prompt)}
                disabled={disabled}
                className="-mx-2 flex w-[calc(100%+1rem)] cursor-pointer flex-col items-start gap-1 rounded-lg px-2 py-2 text-left text-sm transition-colors duration-150 hover:bg-line/60 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span>{scenario.title}</span>
                <OutcomeBadge outcome={scenario.outcome} />
              </button>
            </li>
          ))}
        </ul>
      </div>
      <Link href={`/customers#${story.slug}`} className="text-link text-sm">
        Read {story.name.split(" ")[0]}&apos;s story
      </Link>
    </aside>
  );
}

function Message({ message }: { message: SupportUIMessage }) {
  if (message.role === "user") {
    const text = message.parts.map((p) => (p.type === "text" ? p.text : "")).join("");
    return <div className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent px-4 py-2 text-on-accent">{text}</div>;
  }
  return (
    <div className="flex flex-col gap-2.5">
      {message.parts.map((part, i) => {
        switch (part.type) {
          case "text":
            return part.text.trim() ? (
              <div key={i} className="prose-reply">
                <Markdown>{part.text}</Markdown>
              </div>
            ) : null;
          case "data-tool":
            return <ToolChip key={i} step={part.data} />;
          case "data-approval":
            return <ApprovalCard key={i} approval={part.data} />;
          case "data-sources":
            return <Sources key={i} items={part.data.items} />;
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

function Sources({ items }: { items: string[] }) {
  return (
    <ul aria-label="Sources" className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <li key={item} className="flex max-w-full items-center gap-1 rounded-md bg-surface-2 px-1.5 py-0.5 text-xs text-muted">
          <DocumentIcon width={12} height={12} className="shrink-0" />
          <span className="truncate">{item}</span>
        </li>
      ))}
    </ul>
  );
}

function ToolChip({ step }: { step: ToolStep }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      {step.status === "running" && <SpinnerIcon width={14} height={14} className="animate-spin" />}
      {step.status === "error" && <AlertIcon width={14} height={14} className="text-danger" />}
      {step.status === "done" && <CheckIcon width={14} height={14} className="text-accent" />}
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
  const Icon = state.tone === "warn" ? ClockIcon : state.tone === "ok" ? CheckIcon : AlertIcon;
  return (
    <Banner tone={state.tone}>
      <p className="flex items-center gap-2 font-medium">
        <Icon className="shrink-0" />
        {approval.toolName === "issue_refund" ? "Refund" : "Email"}: {state.title}
      </p>
      <p className="mt-1">{approval.summary}</p>
    </Banner>
  );
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
