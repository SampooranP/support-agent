"use client";

import { useCallback, useState, useSyncExternalStore } from "react";

import { detailMessage } from "@/lib/errors";
import { timeAgo } from "@/lib/time";
import type { ApprovalRequest } from "@/lib/types";
import { usePolling } from "@/lib/use-polling";

const POLL_MS = 3000;
const REVIEWER_KEY = "reviewer-name";

// The reviewer's name is remembered in localStorage (a per-browser convenience; it may be unavailable).
function readStoredReviewer(): string {
  try {
    return localStorage.getItem(REVIEWER_KEY) ?? "";
  } catch {
    return "";
  }
}
const noSubscription = () => () => {};

export function Approvals() {
  const [pending, setPending] = useState<ApprovalRequest[]>([]);
  const [recent, setRecent] = useState<ApprovalRequest[]>([]);
  const storedReviewer = useSyncExternalStore(noSubscription, readStoredReviewer, () => "");
  const [editedReviewer, setEditedReviewer] = useState<string | null>(null);
  const reviewer = editedReviewer ?? storedReviewer;
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, decided] = await Promise.all([
        fetch("/api/approvals?status=pending"),
        fetch("/api/approvals?status=approved,executed,rejected,failed&limit=10"),
      ]);
      const [pendingBody, decidedBody] = await Promise.all([p.json().catch(() => null), decided.json().catch(() => null)]);
      if (!p.ok || !Array.isArray(pendingBody)) throw new Error(detailMessage(pendingBody, "Couldn't load approvals"));
      setPending(pendingBody);
      if (decided.ok && Array.isArray(decidedBody)) setRecent(decidedBody);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoaded(true);
    }
  }, []);

  usePolling(load, POLL_MS);

  function updateReviewer(name: string) {
    setEditedReviewer(name);
    try {
      localStorage.setItem(REVIEWER_KEY, name);
    } catch {
      // Storage unavailable (private mode etc.); the name just isn't remembered.
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Approvals</h1>
          <p className="text-sm text-muted">Refunds and emails the agent wants to send. Nothing happens until you approve.</p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted">Reviewing as</span>
          <input
            value={reviewer}
            onChange={(e) => updateReviewer(e.target.value)}
            placeholder="Your name"
            className="rounded-md border border-line bg-surface px-2 py-1.5"
          />
        </label>
      </div>

      {error && <p className="mt-4 rounded-lg border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">{error}</p>}

      <section className="mt-6">
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted">
          Pending {pending.length > 0 && `(${pending.length})`}
        </h2>
        {loaded && pending.length === 0 && !error && (
          <p className="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-muted">
            Nothing waiting for review. Ask for a refund in the chat to see one appear here.
          </p>
        )}
        <div className="grid gap-4 md:grid-cols-2">
          {pending.map((a) => (
            <PendingCard key={a.id} approval={a} reviewer={reviewer} onDecided={load} />
          ))}
        </div>
      </section>

      {recent.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted">Recently decided</h2>
          <div className="overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Request</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Reviewer</th>
                  <th className="px-4 py-2 font-medium">Decided</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((a) => (
                  <tr key={a.id} className="border-b border-line last:border-0">
                    <td className="max-w-md px-4 py-2">
                      <span className="line-clamp-2">{a.summary}</span>
                      {a.reviewer_note && <span className="block text-xs text-muted">Note: {a.reviewer_note}</span>}
                    </td>
                    <td className="px-4 py-2">
                      <StatusBadge status={a.status} />
                    </td>
                    <td className="px-4 py-2 text-muted">{a.reviewer ?? "-"}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-muted">{a.decided_at ? timeAgo(a.decided_at) : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

function PendingCard({
  approval,
  reviewer,
  onDecided,
}: {
  approval: ApprovalRequest;
  reviewer: string;
  onDecided: () => void;
}) {
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = approval.tool_input;

  async function decide(approved: boolean) {
    if (!reviewer.trim()) {
      setError("Enter your name under “Reviewing as” first.");
      return;
    }
    setSubmitting(true);
    setError(null);
    const res = await fetch(`/api/approvals/${approval.id}/decision`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ approved, reviewer: reviewer.trim(), note: note.trim() }),
    });
    if (!res.ok) {
      setError(detailMessage(await res.json().catch(() => null), "Couldn't save the decision"));
      setSubmitting(false);
      return;
    }
    onDecided();
  }

  return (
    <article className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-medium">{approval.tool_name === "issue_refund" ? "Refund request" : "Email request"}</h3>
        <span className="whitespace-nowrap text-xs text-muted">{timeAgo(approval.created_at)}</span>
      </div>
      <p className="text-sm text-muted">Customer: {approval.customer_email ?? "unknown"}</p>

      {approval.tool_name === "issue_refund" ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted">Order</dt>
          <dd>#{String(input.order_number)}</dd>
          <dt className="text-muted">Amount</dt>
          <dd className="font-semibold">{Number(input.amount).toFixed(2)}</dd>
          <dt className="text-muted">Reason</dt>
          <dd>{String(input.reason)}</dd>
        </dl>
      ) : (
        <div className="text-sm">
          <p>
            <span className="text-muted">To:</span> {String(input.to)}
          </p>
          <p>
            <span className="text-muted">Subject:</span> {String(input.subject)}
          </p>
          <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md bg-background p-3 font-sans">
            {String(input.body)}
          </pre>
        </div>
      )}
      <p className="text-xs text-muted">{approval.summary}</p>

      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Note for the agent (optional; shared with the customer if you reject)"
        rows={2}
        className="rounded-md border border-line bg-background px-2 py-1.5 text-sm"
      />
      {error && <p className="text-sm text-danger">{error}</p>}
      <div className="flex gap-2">
        <button
          onClick={() => decide(true)}
          disabled={submitting}
          className="flex-1 rounded-md bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50 dark:text-black"
        >
          Approve
        </button>
        <button
          onClick={() => decide(false)}
          disabled={submitting}
          className="flex-1 rounded-md border border-danger/40 px-3 py-2 text-sm font-medium text-danger disabled:opacity-50"
        >
          Reject
        </button>
      </div>
    </article>
  );
}

function StatusBadge({ status }: { status: ApprovalRequest["status"] }) {
  const styles: Record<string, string> = {
    executed: "bg-accent-soft text-accent",
    approved: "bg-accent-soft text-accent",
    rejected: "bg-danger-soft text-danger",
    failed: "bg-danger-soft text-danger",
    pending: "bg-warn-soft text-warn",
  };
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles[status]}`}>{status}</span>;
}
