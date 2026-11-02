-- The specialist a conversation is routed to (agent/specialists.py). Null until the first
-- customer message is routed, and for conversations from before routing.

alter table public.conversations
  add column if not exists specialist text
    check (specialist in ('billing', 'shipping', 'tech_support', 'general'));
