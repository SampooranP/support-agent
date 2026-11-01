-- Conversations, human approvals, and the actions the agent can take:
-- tickets (no approval needed), refunds and emails (approval required).

create table if not exists public.conversations (
  id             uuid primary key default gen_random_uuid(),
  customer_email text,                          -- the signed-in customer; null for guests
  status         text not null default 'active' check (status in ('active', 'awaiting_approval')),
  messages       jsonb not null default '[]',   -- Claude API message history
  pending_turn   jsonb,                         -- tool results held while approvals are pending
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create table if not exists public.approval_requests (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations (id) on delete cascade,
  tool_use_id     text not null,
  tool_name       text not null check (tool_name in ('issue_refund', 'send_email')),
  tool_input      jsonb not null,               -- exactly what the agent asked to run
  summary         text not null,                -- one line for the reviewer
  status          text not null default 'pending'
                  check (status in ('pending', 'approved', 'rejected', 'executed', 'failed')),
  reviewer        text,
  reviewer_note   text,
  result          jsonb,
  created_at      timestamptz not null default now(),
  decided_at      timestamptz,
  executed_at     timestamptz,
  unique (conversation_id, tool_use_id)
);

create index if not exists approval_requests_status_idx on public.approval_requests (status, created_at);

create table if not exists public.tickets (
  ticket_number   bigint generated always as identity (start with 5001) primary key,
  conversation_id uuid references public.conversations (id) on delete set null,
  customer_id     text references public.customers (id),
  order_number    int references public.orders (order_number),
  subject         text not null,
  description     text not null,
  priority        text not null default 'normal' check (priority in ('low', 'normal', 'high', 'urgent')),
  status          text not null default 'open' check (status in ('open', 'pending', 'resolved')),
  created_at      timestamptz not null default now()
);

create table if not exists public.refunds (
  id           bigint generated always as identity primary key,
  order_number int not null references public.orders (order_number),
  amount       numeric(10, 2) not null check (amount > 0),
  currency     text not null,
  reason       text not null,
  approval_id  uuid not null unique references public.approval_requests (id),
  created_at   timestamptz not null default now()
);

-- Emails are recorded here instead of being sent (this is a demo; no mail provider).
create table if not exists public.emails (
  id          bigint generated always as identity primary key,
  to_email    text not null,
  subject     text not null,
  body        text not null,
  approval_id uuid not null unique references public.approval_requests (id),
  created_at  timestamptz not null default now()
);

-- Runs an approved refund. Re-checks everything, so a refund can't happen without a human
-- approval that matches these exact arguments, and can't exceed what's left on the order.
create or replace function public.execute_refund(
  p_approval_id uuid, p_order_number int, p_amount numeric, p_reason text
)
returns public.refunds
language plpgsql
security definer  -- the only way refunds/emails get written
set search_path = public
as $$
declare
  approval public.approval_requests;
  ord      public.orders;
  refunded numeric;
  refund   public.refunds;
begin
  select * into approval from approval_requests where id = p_approval_id for update;
  if not found or approval.tool_name <> 'issue_refund' then
    raise exception 'No refund approval with ID %', p_approval_id;
  end if;
  if approval.status <> 'approved' then
    raise exception 'Approval % is %, not approved', p_approval_id, approval.status;
  end if;
  if (approval.tool_input ->> 'order_number')::int <> p_order_number
     or (approval.tool_input ->> 'amount')::numeric <> p_amount then
    raise exception 'Refund arguments do not match what was approved';
  end if;

  select * into ord from orders where order_number = p_order_number for update;
  if not found then
    raise exception 'No order #%', p_order_number;
  end if;
  select coalesce(sum(amount), 0) into refunded from refunds where order_number = p_order_number;
  if p_amount > ord.total - refunded then
    raise exception 'Refund of % exceeds the % % left to refund on order #%',
      p_amount, ord.total - refunded, ord.currency, p_order_number;
  end if;

  insert into refunds (order_number, amount, currency, reason, approval_id)
  values (p_order_number, p_amount, ord.currency, p_reason, p_approval_id)
  returning * into refund;
  update approval_requests set status = 'executed', executed_at = now(), result = to_jsonb(refund)
  where id = p_approval_id;
  return refund;
end;
$$;

-- Records an approved email, with the same approval checks as execute_refund.
create or replace function public.execute_email(
  p_approval_id uuid, p_to_email text, p_subject text, p_body text
)
returns public.emails
language plpgsql
security definer  -- the only way refunds/emails get written
set search_path = public
as $$
declare
  approval public.approval_requests;
  email    public.emails;
begin
  select * into approval from approval_requests where id = p_approval_id for update;
  if not found or approval.tool_name <> 'send_email' then
    raise exception 'No email approval with ID %', p_approval_id;
  end if;
  if approval.status <> 'approved' then
    raise exception 'Approval % is %, not approved', p_approval_id, approval.status;
  end if;
  if approval.tool_input ->> 'to' <> p_to_email
     or approval.tool_input ->> 'subject' <> p_subject
     or approval.tool_input ->> 'body' <> p_body then
    raise exception 'Email does not match what was approved';
  end if;

  insert into emails (to_email, subject, body, approval_id)
  values (p_to_email, p_subject, p_body, p_approval_id)
  returning * into email;
  update approval_requests set status = 'executed', executed_at = now(), result = to_jsonb(email)
  where id = p_approval_id;
  return email;
end;
$$;

alter table public.conversations     enable row level security;
alter table public.approval_requests enable row level security;
alter table public.tickets           enable row level security;
alter table public.refunds           enable row level security;
alter table public.emails            enable row level security;

grant select, insert, update on public.conversations, public.approval_requests to service_role;
grant select, insert on public.tickets to service_role;
grant select on public.refunds, public.emails to service_role;  -- written only by the functions above

revoke execute on function public.execute_refund(uuid, int, numeric, text) from public, anon, authenticated;
revoke execute on function public.execute_email(uuid, text, text, text) from public, anon, authenticated;
grant execute on function public.execute_refund(uuid, int, numeric, text) to service_role;
grant execute on function public.execute_email(uuid, text, text, text) to service_role;
