-- Customers, orders and order line items for the support tools (MCP server).

create table if not exists public.customers (
  id            text primary key,                    -- e.g. 'cus_001'
  name          text not null,
  email         text not null unique check (email = lower(email)),
  phone         text,
  city          text,
  region        text,                                -- state or province
  country       text not null check (country in ('US', 'CA')),
  reward_points int  not null default 0 check (reward_points >= 0),
  created_at    timestamptz not null default now()
);

create table if not exists public.orders (
  order_number       int  primary key,
  customer_id        text not null references public.customers (id),
  status             text not null check (status in ('processing', 'shipped', 'delivered', 'cancelled', 'returned')),
  shipping_method    text not null check (shipping_method in ('standard', 'expedited', 'overnight', 'international_standard')),
  ship_to_city       text not null,
  ship_to_region     text not null,
  ship_to_country    text not null check (ship_to_country in ('US', 'CA')),
  currency           text not null check (currency in ('USD', 'CAD')),
  subtotal           numeric(10, 2) not null check (subtotal >= 0),
  shipping_cost      numeric(10, 2) not null check (shipping_cost >= 0),
  tax                numeric(10, 2) not null check (tax >= 0),
  total              numeric(10, 2) not null,
  carrier            text,
  tracking_number    text,
  estimated_delivery date,
  placed_at          timestamptz not null default now(),
  shipped_at         timestamptz,
  delivered_at       timestamptz,
  cancelled_at       timestamptz,
  check (total = subtotal + shipping_cost + tax)
);

create index if not exists orders_customer_id_idx on public.orders (customer_id);

create table if not exists public.order_items (
  id           bigint generated always as identity primary key,
  order_number int  not null references public.orders (order_number) on delete cascade,
  sku          text not null,
  product_name text not null,
  quantity     int  not null check (quantity > 0),
  unit_price   numeric(10, 2) not null check (unit_price >= 0),
  final_sale   boolean not null default false
);

create index if not exists order_items_order_number_idx on public.order_items (order_number);

-- Same model as doc_chunks: RLS on with no policies, and only the backend's service role
-- gets access. The tools in this phase only read; later phases add write grants.
alter table public.customers   enable row level security;
alter table public.orders      enable row level security;
alter table public.order_items enable row level security;

grant select on public.customers, public.orders, public.order_items to service_role;
