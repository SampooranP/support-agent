import type { ReactNode } from "react";

import { OUTCOMES, type Outcome } from "@/lib/demo-customers";

export type Tone = "neutral" | "ok" | "warn" | "danger";

const BADGE_TONES: Record<Tone, string> = {
  neutral: "bg-line/70 text-muted",
  ok: "bg-accent-soft text-accent",
  warn: "bg-warn-soft text-warn",
  danger: "bg-danger-soft text-danger",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-md px-1.5 py-0.5 text-xs font-medium ${BADGE_TONES[tone]}`}>
      {children}
    </span>
  );
}

export function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  return <Badge tone={OUTCOMES[outcome].tone}>{OUTCOMES[outcome].label}</Badge>;
}

const BANNER_TONES: Record<Exclude<Tone, "neutral">, string> = {
  ok: "border-accent/25 bg-accent-soft text-accent",
  warn: "border-warn/25 bg-warn-soft text-warn",
  danger: "border-danger/25 bg-danger-soft text-danger",
};

export function Banner({ tone, children }: { tone: Exclude<Tone, "neutral">; children: ReactNode }) {
  return <div className={`rounded-lg border px-4 py-3 text-sm ${BANNER_TONES[tone]}`}>{children}</div>;
}

export function PageHeader({ title, description, children }: { title: ReactNode; description: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 text-sm text-muted">{description}</p>
      </div>
      {children}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-dashed border-line-strong px-6 py-10 text-center text-sm text-muted">{children}</p>;
}

export function SkeletonRows({ count, className = "h-16" }: { count: number; className?: string }) {
  return (
    <div className="flex flex-col gap-2" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className={`animate-pulse rounded-lg bg-surface-2 ${className}`} />
      ))}
    </div>
  );
}
