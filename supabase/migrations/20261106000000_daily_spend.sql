-- What the agent API has spent on Claude calls per UTC day, for the daily spend cap (agent/spend.py).

create table if not exists public.daily_spend (
  day date primary key,
  usd numeric(12, 6) not null default 0
);

alter table public.daily_spend enable row level security;

-- Add to today's total in one statement, so concurrent calls don't lose an update. Returns the new total.
create or replace function public.add_spend(p_usd numeric)
returns numeric
language sql
as $$
  insert into public.daily_spend (day, usd)
  values ((now() at time zone 'utc')::date, p_usd)
  on conflict (day) do update set usd = public.daily_spend.usd + excluded.usd
  returning usd;
$$;

grant select, insert, update on public.daily_spend to service_role;
revoke execute on function public.add_spend(numeric) from public, anon, authenticated;
grant execute on function public.add_spend(numeric) to service_role;
