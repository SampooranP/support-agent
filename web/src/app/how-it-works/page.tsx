import type { Metadata } from "next";
import Link from "next/link";

import { ArrowRightIcon, CheckIcon, PauseIcon } from "@/components/icons";

export const metadata: Metadata = { title: "How it works | Lumen & Pine Support" };

type Step = { title: string; body: string; file?: string; pause?: boolean };

const STEPS: Step[] = [
  {
    title: "Maya sends a message",
    body: "Maya writes that order #1042 arrived with two snapped poles. The browser only talks to the Next.js server, which forwards the message to the Python agent API with a shared secret.",
    file: "web/src/app/api/chat/route.ts",
  },
  {
    title: "The API checks limits and picks a specialist",
    body: "Rate limits and a daily spend cap run first. A small Haiku call then reads the conversation and routes it to one of four specialists. A damaged item goes to Billing, and the conversation stays there unless the topic clearly changes.",
    file: "agent/router.py",
  },
  {
    title: "Claude gathers what it needs",
    body: "Claude searches the help docs by vector similarity and looks up the order through the MCP server. The agent checks that the order belongs to the signed-in customer, so #1042 comes back with its delivery date and $301.32 total.",
    file: "agent/tools.py",
  },
  {
    title: "Claude asks to issue a refund",
    body: "The policy allows a full refund, so Claude calls issue_refund. The agent doesn't run it. It validates the request, records an approval and pauses the conversation. The pause is stored in Supabase, so it survives a restart.",
    file: "agent/loop.py",
  },
  {
    title: "A person decides",
    body: "A supervisor sees the order, the amount and the reason in Approvals, then approves or rejects with an optional note. Nothing has been refunded up to this point.",
    pause: true,
  },
  {
    title: "The database enforces the decision",
    body: "On approval, the agent runs the refund through a database function that re-checks that a person approved those exact arguments. Even a buggy agent can't write a refund any other way, and a retried resume never refunds twice.",
    file: "supabase/migrations/20261104000000_support_actions.sql",
  },
  {
    title: "Maya gets the outcome",
    body: "Claude is told what happened and replies with citations to the policy it used. Before the reply is stored, anyone else's email or phone number is redacted, and a claim that a refund happened when it hasn't is flagged.",
    file: "agent/guardrails.py",
  },
];

const TOOLS = ["Search docs", "Look up order", "Look up customer", "Open ticket", "Send email", "Issue refund"];

const SPECIALISTS: { name: string; handles: string; allowed: boolean[] }[] = [
  { name: "Billing", handles: "Refunds, returns, cancellations, charges", allowed: [true, true, true, true, true, true] },
  { name: "Shipping", handles: "Tracking, delivery, late or lost packages", allowed: [true, true, true, true, true, false] },
  { name: "Tech support", handles: "Setup, error codes, warranty", allowed: [true, true, true, true, false, false] },
  { name: "General", handles: "Accounts, rewards, everything else", allowed: [true, true, true, true, false, false] },
];

const SAFEGUARDS = [
  { layer: "Tools", detail: "Customers only see their own orders, emails only go to the signed-in customer, and refunds can't exceed the order total. The model never supplies identity or approval IDs." },
  { layer: "Database", detail: "Refunds and emails can only be written by functions that check a person approved those exact arguments." },
  { layer: "Replies", detail: "Other people's contact details are redacted. A reply claiming an action that didn't run is flagged in the logs and traces." },
  { layer: "Usage", detail: "10 messages per conversation per 5 minutes, 40 per customer per hour, and a daily cap on Claude spend." },
];

const EVALS = [
  { metric: "Pass (all four below)", baseline: "60%", v1: "65%", v2: "75%", strong: true },
  { metric: "Right action", baseline: "95%", v1: "100%", v2: "100%" },
  { metric: "Safety", baseline: "95%", v1: "100%", v2: "100%" },
  { metric: "Grounded", baseline: "95%", v1: "100%", v2: "95%" },
  { metric: "Quality", baseline: "65%", v1: "65%", v2: "75%" },
];

const STACK = [
  { part: "Web app", detail: "Next.js and the Vercel AI SDK, hosted on Vercel" },
  { part: "Agent API", detail: "Python on AWS ECS Fargate, behind a load balancer" },
  { part: "Models", detail: "Claude: Haiku routes each conversation, and the public demo's specialists run on Sonnet" },
  { part: "Tools", detail: "A custom MCP server, launched by the agent" },
  { part: "Data", detail: "Supabase Postgres with pgvector, and Voyage AI embeddings" },
  { part: "Tracing", detail: "Langfuse records every model and tool call, with cost and latency" },
];

export default function HowItWorksPage() {
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8 md:px-6 md:py-12">
      <header className="max-w-2xl">
        <h1 className="text-3xl font-semibold tracking-tight">How a refund request moves through the system</h1>
        <p className="mt-3 leading-relaxed text-muted">
          The agent can read freely, but it can&apos;t move money or email anyone without a person saying yes. Here is one real scenario from
          start to finish: Maya&apos;s tent arrived broken, and Maya wants a refund.
        </p>
      </header>

      <ol className="mt-10">
        {STEPS.map((step, index) => (
          <TraceStep key={step.title} step={step} number={index + 1} last={index === STEPS.length - 1} />
        ))}
      </ol>

      <Section title="Each specialist has its own tools" intro="The router decides who answers. The agent loop enforces what each specialist may call, so a shipping conversation can't issue a refund even if the model tries.">
        <dl className="divide-y divide-line border-y border-line md:hidden">
          {SPECIALISTS.map((specialist) => (
            <div key={specialist.name} className="py-3">
              <dt className="font-medium">{specialist.name}</dt>
              <dd className="text-sm text-muted">{specialist.handles}</dd>
              <dd className="mt-1 text-sm">{TOOLS.filter((_, i) => specialist.allowed[i]).join(", ")}</dd>
            </div>
          ))}
        </dl>
        <div className="relative hidden overflow-x-auto rounded-xl border border-line bg-surface md:block">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-muted">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Specialist
                </th>
                {TOOLS.map((tool) => (
                  <th key={tool} scope="col" className="px-2 py-2.5 text-center font-medium">
                    {tool}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {SPECIALISTS.map((specialist) => (
                <tr key={specialist.name}>
                  <th scope="row" className="px-4 py-3 font-normal">
                    <span className="block font-medium">{specialist.name}</span>
                    <span className="block text-muted">{specialist.handles}</span>
                  </th>
                  {specialist.allowed.map((allowed, i) => (
                    <td key={TOOLS[i]} className="px-2 py-3 text-center">
                      {allowed ? <CheckIcon className="mx-auto text-accent" /> : <span className="text-line-strong">&ndash;</span>}
                      <span className="sr-only">{allowed ? "Allowed" : "Not allowed"}</span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Safeguards sit at four layers" intro="None of these depend on the model following its instructions.">
        <dl className="divide-y divide-line border-y border-line">
          {SAFEGUARDS.map((item) => (
            <div key={item.layer} className="grid gap-1 py-3 md:grid-cols-[140px_minmax(0,1fr)] md:gap-6">
              <dt className="font-medium">{item.layer}</dt>
              <dd className="text-muted">{item.detail}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section
        title="How it's measured"
        intro="An eval suite runs 20 hand-written support tickets through the real agent, tools and database, then scores each one. Code grades the action and safety, and a separate Claude judge grades grounding and quality."
      >
        <div className="overflow-x-auto rounded-xl border border-line bg-surface">
          <table className="w-full text-left text-sm tabular-nums">
            <thead className="border-b border-line text-muted">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Metric
                </th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">
                  Baseline
                </th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">
                  v1
                </th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">
                  v2
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {EVALS.map((row) => (
                <tr key={row.metric} className={row.strong ? "font-semibold" : undefined}>
                  <th scope="row" className={`px-4 py-2.5 ${row.strong ? "font-semibold" : "font-normal"}`}>
                    {row.metric}
                  </th>
                  <td className="px-4 py-2.5 text-right">{row.baseline}</td>
                  <td className="px-4 py-2.5 text-right">{row.v1}</td>
                  <td className="px-4 py-2.5 text-right">{row.v2}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-sm text-muted">
          v2 is the version with specialist routing. Twenty cases is a small sample, so the change in pass rate is within noise (the v2 pass rate has a 95% interval of 53 to 89%). Most
          remaining failures are replies that request a refund without first telling the customer it is under review.
        </p>
      </Section>

      <Section title="What runs where">
        <dl className="divide-y divide-line border-y border-line">
          {STACK.map((item) => (
            <div key={item.part} className="grid gap-1 py-3 md:grid-cols-[140px_minmax(0,1fr)] md:gap-6">
              <dt className="font-medium">{item.part}</dt>
              <dd className="text-muted">{item.detail}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <div className="mt-12 flex flex-wrap items-center gap-x-5 gap-y-3 border-t border-line pt-8">
        <Link href="/?scenario=maya-damaged-tent" className="btn btn-primary">
          Try Maya&apos;s scenario
          <ArrowRightIcon />
        </Link>
        <Link href="/customers" className="text-link text-sm">
          See all five customers
        </Link>
      </div>
    </div>
  );
}

function TraceStep({ step, number, last }: { step: Step; number: number; last: boolean }) {
  const line = step.pause ? "before:border-l before:border-dashed before:border-warn" : "before:border-l before:border-line-strong";
  return (
    <li className={`relative grid grid-cols-[28px_minmax(0,1fr)] gap-x-4 pb-8 ${last ? "" : `before:absolute before:bottom-0 before:left-[13.5px] before:top-8 ${line}`}`}>
      <span
        className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-medium tabular-nums ${
          step.pause ? "bg-warn text-background" : "border border-line-strong bg-surface text-muted"
        }`}
      >
        {step.pause ? <PauseIcon /> : number}
        {step.pause && <span className="sr-only">Step {number}</span>}
      </span>
      <div className={step.pause ? "rounded-xl border border-warn/25 bg-warn-soft px-4 py-3" : "pt-0.5"}>
        <h2 className={`font-semibold ${step.pause ? "text-warn" : ""}`}>{step.title}</h2>
        <p className={`mt-1 max-w-[65ch] leading-relaxed ${step.pause ? "text-warn" : "text-muted"}`}>{step.body}</p>
        {step.file && <p className="mt-1.5 break-all font-mono text-xs text-muted">{step.file}</p>}
      </div>
    </li>
  );
}

function Section({ title, intro, children }: { title: string; intro?: string; children: React.ReactNode }) {
  return (
    <section className="mt-12">
      <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
      {intro && <p className="mt-2 mb-4 max-w-2xl leading-relaxed text-muted">{intro}</p>}
      <div className={intro ? undefined : "mt-4"}>{children}</div>
    </section>
  );
}
