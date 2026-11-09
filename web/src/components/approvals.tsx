"use client";

import { useCallback, useState, useSyncExternalStore } from "react";

import { Badge, Banner, EmptyState, PageHeader, SkeletonRows, type Tone } from "@/components/ui";
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
    <div className="mx-auto w-full max-w-5xl px-4 py-8 md:px-6">
      <PageHeader title="Approvals" description="Refunds and emails the agent wants to send. Nothing happens until you approve.">
        <label className="flex items-center gap-2 text-sm">
          <span className="whitespace-nowrap text-muted">Reviewing as</span>
          <input value={reviewer} onChange={(e) => updateReviewer(e.target.value)} placeholder="Your name" className="field w-44!" />
        </label>
      </PageHeader>

      {error && (
        <div className="mt-4">
          <Banner tone="danger">{error}</Banner>
        </div>
      )}

      <section className="mt-8">
        <h2 className="mb-3 flex items-center gap-2 font-semibold">
          Waiting for review
          {pending.length > 0 && <Badge tone="warn">{pending.length}</Badge>}
        </h2>
        {!loaded && <SkeletonRows count={2} className="h-40" />}
        {loaded && pending.length === 0 && !error && <EmptyState>Nothing waiting for review. Ask for a refund in the chat to see one appear here.</EmptyState>}
        <div className="grid gap-4 md:grid-cols-2">
          {pending.map((a) => (
            <PendingCard key={a.id} approval={a} reviewer={reviewer} onDecided={load} />
          ))}
        </div>
      </section>

      {recent.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-3 font-semibold">Recently decided</h2>
          <div className="overflow-x-auto rounded-xl border border-line bg-surface">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead className="border-b border-line text-muted">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Request</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Reviewer</th>
                  <th className="px-4 py-2.5 font-medium">Decided</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {recent.map((a) => (
                  <tr key={a.id}>
                    <td className="max-w-md px-4 py-3">
                      <span className="line-clamp-2">{a.summary}</span>
                      {a.reviewer_note && <span className="mt-0.5 block text-xs text-muted">Note: {a.reviewer_note}</span>}
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={STATUS_TONES[a.status]}>{a.status}</Badge>
                    </td>
                    <td className="px-4 py-3 text-muted">{a.reviewer ?? "-"}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-muted">{a.decided_at ? timeAgo(a.decided_at) : "-"}</td>
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
    <article className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 shadow-card">
      <div>
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="font-semibold">{approval.tool_name === "issue_refund" ? "Refund request" : "Email request"}</h3>
          <span className="whitespace-nowrap text-xs text-muted">{timeAgo(approval.created_at)}</span>
        </div>
        <p className="mt-0.5 break-all text-sm text-muted">{approval.customer_email ?? "Unknown customer"}</p>
      </div>

      {approval.tool_name === "issue_refund" ? (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted">Order</dt>
          <dd className="font-mono">#{String(input.order_number)}</dd>
          <dt className="text-muted">Amount</dt>
          <dd className="font-mono font-semibold tabular-nums">{Number(input.amount).toFixed(2)}</dd>
          <dt className="text-muted">Reason</dt>
          <dd>{String(input.reason)}</dd>
        </dl>
      ) : (
        <div className="text-sm">
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1">
            <dt className="text-muted">To</dt>
            <dd className="break-all">{String(input.to)}</dd>
            <dt className="text-muted">Subject</dt>
            <dd>{String(input.subject)}</dd>
          </dl>
          <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg bg-surface-2 p-3 font-sans">{String(input.body)}</pre>
        </div>
      )}
      <p className="text-sm text-muted">{approval.summary}</p>

      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Note for the agent (optional; shared with the customer if you reject)"
        aria-label="Note for the agent"
        rows={2}
        className="field"
      />
      {error && <p className="text-sm text-danger">{error}</p>}
      <div className="mt-auto flex gap-2">
        <button onClick={() => decide(true)} disabled={submitting} className="btn btn-primary flex-1">
          Approve
        </button>
        <button onClick={() => decide(false)} disabled={submitting} className="btn btn-danger flex-1">
          Reject
        </button>
      </div>
    </article>
  );
}

const STATUS_TONES: Record<ApprovalRequest["status"], Tone> = {
  executed: "ok",
  approved: "ok",
  rejected: "danger",
  failed: "danger",
  pending: "warn",
};
