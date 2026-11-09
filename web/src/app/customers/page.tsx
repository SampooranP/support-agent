import type { Metadata } from "next";
import Link from "next/link";

import { ArrowRightIcon } from "@/components/icons";
import { OutcomeBadge } from "@/components/ui";
import { DEMO_CUSTOMERS, OUTCOMES, type DemoCustomer, type Outcome, type Scenario } from "@/lib/demo-customers";

export const metadata: Metadata = { title: "Customers | Lumen & Pine Support" };

export default function CustomersPage() {
  return (
    <div className="mx-auto grid w-full max-w-6xl gap-x-12 px-4 py-8 md:px-6 md:py-12 lg:grid-cols-[180px_minmax(0,1fr)]">
      <aside className="lg:sticky lg:top-8 lg:self-start">
        <nav aria-label="Customers" className="-mx-1 flex overflow-x-auto lg:mx-0 lg:flex-col">
          {DEMO_CUSTOMERS.map((customer) => (
            <a
              key={customer.slug}
              href={`#${customer.slug}`}
              className="flex min-h-11 shrink-0 items-center rounded-md px-2 text-sm text-muted transition-colors duration-150 hover:text-foreground lg:min-h-9"
            >
              {customer.name}
            </a>
          ))}
        </nav>
      </aside>

      <div className="min-w-0">
        <header className="mt-6 max-w-2xl lg:mt-0">
          <h1 className="text-3xl font-semibold tracking-tight">Customers and scenarios</h1>
          <p className="mt-3 leading-relaxed text-muted">
            Lumen &amp; Pine is a fictional outdoor and home goods store. These five customers are seeded in the demo database, and each
            one is set up to test a different rule. The people are invented, but the agent, its tools and its policy checks are real.
          </p>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            Order ages are counted from the last data reset, which runs nightly on the public demo. Each scenario uses a real model, so the
            wording will vary. &ldquo;Try this&rdquo; opens the chat with the message ready for you to send.
          </p>
        </header>

        <section aria-labelledby="outcomes-heading" className="mt-10">
          <h2 id="outcomes-heading" className="text-sm font-semibold">
            What each outcome means
          </h2>
          <dl className="mt-3 grid gap-x-8 gap-y-3 md:grid-cols-2">
            {(Object.keys(OUTCOMES) as Outcome[]).map((outcome) => (
              <div key={outcome} className="flex flex-col items-start gap-1">
                <dt>
                  <OutcomeBadge outcome={outcome} />
                </dt>
                <dd className="text-sm text-muted">{OUTCOMES[outcome].meaning}</dd>
              </div>
            ))}
          </dl>
        </section>

        {DEMO_CUSTOMERS.map((customer) => (
          <CustomerSection key={customer.slug} customer={customer} />
        ))}
      </div>
    </div>
  );
}

function CustomerSection({ customer }: { customer: DemoCustomer }) {
  const facts = [customer.location, customer.tenure, `${customer.points.toLocaleString("en-US")} Trail Rewards points`];
  return (
    <section id={customer.slug} aria-labelledby={`${customer.slug}-name`} className="mt-14 scroll-mt-6 border-t border-line pt-10">
      <h2 id={`${customer.slug}-name`} className="text-2xl font-semibold tracking-tight">
        {customer.name}
      </h2>
      <p className="mt-1 text-sm text-muted">{facts.join(" · ")}</p>

      <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <p className="max-w-[65ch] leading-relaxed">{customer.story}</p>
        <div>
          <h3 className="text-sm font-semibold">Orders on file</h3>
          <ul className="mt-2 divide-y divide-line rounded-xl border border-line bg-surface">
            {customer.orders.map((order) => (
              <li key={order.number} className="px-4 py-3">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-mono text-sm">#{order.number}</span>
                  <span className="font-mono text-sm tabular-nums">{order.total}</span>
                </div>
                <p className="mt-1 text-sm">{order.items}</p>
                <p className="mt-0.5 text-sm text-muted">
                  {order.status}. {order.note}.
                </p>
              </li>
            ))}
          </ul>
          {customer.timingNote && <p className="mt-2 text-sm text-warn">{customer.timingNote}</p>}
        </div>
      </div>

      <h3 className="mt-8 text-sm font-semibold">Scenarios to try</h3>
      <ul className="mt-2 divide-y divide-line">
        {customer.scenarios.map((scenario) => (
          <ScenarioRow key={scenario.id} scenario={scenario} />
        ))}
      </ul>
    </section>
  );
}

function ScenarioRow({ scenario }: { scenario: Scenario }) {
  return (
    <li className="grid gap-x-8 gap-y-3 py-5 md:grid-cols-[minmax(0,1fr)_auto]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h4 className="font-medium">{scenario.title}</h4>
          <OutcomeBadge outcome={scenario.outcome} />
        </div>
        <blockquote className="mt-2 max-w-[65ch] rounded-lg bg-surface-2 px-3 py-2 text-sm">{scenario.prompt}</blockquote>
        <dl className="mt-3 grid max-w-[65ch] grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-muted">Should</dt>
          <dd>{scenario.expected}</dd>
          <dt className="text-muted">Tests</dt>
          <dd>{scenario.rule}</dd>
          <dt className="text-muted">Handled by</dt>
          <dd>{scenario.specialist}</dd>
        </dl>
      </div>
      <div>
        <Link href={`/?scenario=${scenario.id}`} className="btn btn-secondary">
          Try this
          <ArrowRightIcon />
        </Link>
      </div>
    </li>
  );
}
