"use client";

import { useCallback, useState } from "react";

import { Badge, Banner, EmptyState, PageHeader, SkeletonRows, type Tone } from "@/components/ui";
import { detailMessage } from "@/lib/errors";
import { timeAgo } from "@/lib/time";
import type { Ticket } from "@/lib/types";
import { usePolling } from "@/lib/use-polling";

const POLL_MS = 5000;
const API_LIMIT = 100; // GET /tickets returns at most this many by default

const PRIORITY_TONES: Record<Ticket["priority"], Tone> = {
  low: "neutral",
  normal: "neutral",
  high: "warn",
  urgent: "danger",
};

const STATUS_TONES: Record<Ticket["status"], Tone> = {
  open: "warn",
  pending: "warn",
  resolved: "ok",
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
    <div className="mx-auto w-full max-w-4xl px-4 py-8 md:px-6">
      <PageHeader title={`Support tickets ${count}`.trim()} description="Follow-ups the agent has opened for the support team. Tickets don't need approval." />

      {error && (
        <div className="mt-4">
          <Banner tone="danger">{error}</Banner>
        </div>
      )}

      <div className="mt-8">
        {!loaded && <SkeletonRows count={3} className="h-24" />}
        {loaded && tickets.length === 0 && !error && (
          <EmptyState>No tickets yet. Report a problem in the chat that needs a person, like a missing package, to see one appear here.</EmptyState>
        )}

        {tickets.length > 0 && (
          <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
            {tickets.map((ticket) => (
              <li key={ticket.ticket_number} className="flex flex-col gap-1.5 px-4 py-4">
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-sm text-muted">#{ticket.ticket_number}</span>
                  <h2 className="min-w-0 font-semibold">{ticket.subject}</h2>
                  <span className="ml-auto whitespace-nowrap text-xs text-muted">{timeAgo(ticket.created_at)}</span>
                </div>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
                  <span className="break-all">{[ticket.customer_name, ticket.customer_email].filter(Boolean).join(" · ") || "Unknown customer"}</span>
                  {ticket.order_number != null && <span>· Order #{ticket.order_number}</span>}
                  <Badge tone={PRIORITY_TONES[ticket.priority]}>{ticket.priority}</Badge>
                  <Badge tone={STATUS_TONES[ticket.status]}>{ticket.status}</Badge>
                </div>
                <p className="max-w-[75ch] whitespace-pre-wrap text-sm">{ticket.description}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
