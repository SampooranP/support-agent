"use client";

import { useCallback, useState } from "react";

import { detailMessage } from "@/lib/errors";
import { timeAgo } from "@/lib/time";
import type { Ticket } from "@/lib/types";
import { usePolling } from "@/lib/use-polling";

const POLL_MS = 5000;
const API_LIMIT = 100; // GET /tickets returns at most this many by default

const PRIORITY_STYLES: Record<Ticket["priority"], string> = {
  low: "bg-background text-muted",
  normal: "bg-background text-muted",
  high: "bg-warn-soft text-warn",
  urgent: "bg-danger-soft text-danger",
};

const STATUS_STYLES: Record<Ticket["status"], string> = {
  open: "bg-warn-soft text-warn",
  pending: "bg-warn-soft text-warn",
  resolved: "bg-accent-soft text-accent",
};

export function Tickets() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/tickets");
      const body = await res.json().catch(() => null);
      if (!res.ok || !Array.isArray(body)) throw new Error(detailMessage(body, "Couldn't load tickets"));
      setTickets(body);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoaded(true);
    }
  }, []);

  usePolling(load, POLL_MS);

  const count = tickets.length >= API_LIMIT ? `(latest ${API_LIMIT})` : tickets.length > 0 ? `(${tickets.length})` : "";

  return (
    <div className="mx-auto w-full max-w-5xl overflow-y-auto px-4 py-6">
      <h1 className="text-xl font-semibold">Support tickets {count}</h1>
      <p className="text-sm text-muted">Follow-ups the agent has opened for the support team. Tickets don&apos;t need approval.</p>

      {error && <p className="mt-4 rounded-lg border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">{error}</p>}

      {loaded && tickets.length === 0 && !error && (
        <p className="mt-6 rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-muted">
          No tickets yet. Report a problem in the chat that needs a person, like a missing package, to see one appear here.
        </p>
      )}

      <div className="mt-6 grid gap-4">
        {tickets.map((ticket) => (
          <article key={ticket.ticket_number} className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted">#{ticket.ticket_number}</span>
              <h2 className="font-medium">{ticket.subject}</h2>
              <span className="ml-auto whitespace-nowrap text-xs text-muted">{timeAgo(ticket.created_at)}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
              <span>{[ticket.customer_name, ticket.customer_email].filter(Boolean).join(" · ") || "Unknown customer"}</span>
              {ticket.order_number != null && <span>· Order #{ticket.order_number}</span>}
              <Badge className={PRIORITY_STYLES[ticket.priority]}>{ticket.priority}</Badge>
              <Badge className={STATUS_STYLES[ticket.status]}>{ticket.status}</Badge>
            </div>
            <p className="whitespace-pre-wrap text-sm">{ticket.description}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

function Badge({ className, children }: { className: string; children: React.ReactNode }) {
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>{children}</span>;
}
