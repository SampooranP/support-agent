-- Sample customers and orders for development and evals.
-- Dates are relative to now() so each order keeps its place against the policy windows
-- (7 days to report damage, 30-day returns, 1-hour cancellation, ...).
-- WARNING: re-running this deletes all existing customers and orders first.

truncate public.order_items, public.orders, public.customers restart identity cascade;

insert into public.customers (id, name, email, phone, city, region, country, reward_points, created_at) values
  ('cus_001', 'Maya Chen',       'maya.chen@example.com',     '206-555-0117', 'Seattle',  'WA', 'US',  460, now() - interval '400 days'),
  ('cus_002', 'Jordan Alvarez',  'jordan.alvarez@example.com', '416-555-0163', 'Toronto',  'ON', 'CA',  210, now() - interval '200 days'),
  ('cus_003', 'Priya Natarajan', 'priya.n@example.com',       '512-555-0148', 'Austin',   'TX', 'US', 1250, now() - interval '650 days'),
  ('cus_004', 'Sam Okafor',      'sam.okafor@example.com',    '503-555-0189', 'Portland', 'OR', 'US',  145, now() - interval '90 days'),
  ('cus_005', 'Leo Martins',     'leo.martins@example.com',   '305-555-0102', 'Miami',    'FL', 'US',    0, now() - interval '30 days');

insert into public.orders (
  order_number, customer_id, status, shipping_method,
  ship_to_city, ship_to_region, ship_to_country, currency,
  subtotal, shipping_cost, tax, total,
  carrier, tracking_number, estimated_delivery,
  placed_at, shipped_at, delivered_at, cancelled_at
) values
  -- Delivered 3 days ago: inside the 7-day window to report damage.
  (1042, 'cus_001', 'delivered', 'standard', 'Seattle', 'WA', 'US', 'USD',
   279.00, 0.00, 22.32, 301.32, 'UPS', '1Z999AA10123456784', (now() - interval '3 days')::date,
   now() - interval '8 days', now() - interval '8 days', now() - interval '3 days', null),
  -- Delivered 40 days ago: outside the 30-day return window.
  (1043, 'cus_001', 'delivered', 'standard', 'Seattle', 'WA', 'US', 'USD',
   149.00, 0.00, 11.92, 160.92, 'UPS', '1Z999AA10123456791', (now() - interval '40 days')::date,
   now() - interval '47 days', now() - interval '47 days', now() - interval '40 days', null),
  -- Canada, in transit.
  (1044, 'cus_002', 'shipped', 'international_standard', 'Toronto', 'ON', 'CA', 'CAD',
   175.00, 0.00, 22.75, 197.75, 'Canada Post', '7023 4567 8901 2345', (now() + interval '6 days')::date,
   now() - interval '4 days', now() - interval '4 days', null, null),
  -- Over $500: refunds need supervisor approval; required a signature.
  (1045, 'cus_003', 'delivered', 'expedited', 'Austin', 'TX', 'US', 'USD',
   707.00, 12.99, 58.33, 778.32, 'FedEx', '7489 2210 5531', (now() - interval '10 days')::date,
   now() - interval '12 days', now() - interval '12 days', now() - interval '10 days', null),
  -- Placed 20 minutes ago: still inside the 1-hour cancellation window.
  (1046, 'cus_004', 'processing', 'standard', 'Portland', 'OR', 'US', 'USD',
   144.98, 0.00, 0.00, 144.98, null, null, (now() + interval '7 days')::date,
   now() - interval '20 minutes', null, null, null),
  -- Final Sale item, delivered 5 days ago.
  (1047, 'cus_002', 'delivered', 'international_standard', 'Toronto', 'ON', 'CA', 'CAD',
   35.00, 14.99, 4.55, 54.54, 'Canada Post', '7023 4567 8901 3388', (now() - interval '6 days')::date,
   now() - interval '9 days', now() - interval '9 days', now() - interval '5 days', null),
  -- Lost: shipped overnight 25 days ago and never delivered.
  (1048, 'cus_005', 'shipped', 'overnight', 'Miami', 'FL', 'US', 'USD',
   149.00, 24.99, 8.94, 182.93, 'FedEx', '7489 2210 6672', (now() - interval '24 days')::date,
   now() - interval '25 days', now() - interval '25 days', null, null),
  -- Cancelled by the customer.
  (1049, 'cus_004', 'cancelled', 'standard', 'Portland', 'OR', 'US', 'USD',
   279.00, 0.00, 0.00, 279.00, null, null, null,
   now() - interval '30 days', null, null, now() - interval '30 days' + interval '20 minutes');

insert into public.order_items (order_number, sku, product_name, quantity, unit_price, final_sale) values
  (1042, 'TH-2P',    'Trailhead 2P Backpacking Tent',            1, 279.00, false),
  (1043, 'DR-200',   'Drift Wireless Earbuds',                   1, 149.00, false),
  (1044, 'EK-900',   'Ember Gooseneck Electric Kettle',          1, 175.00, false),
  (1045, 'TH-2P',    'Trailhead 2P Backpacking Tent',            2, 279.00, false),
  (1045, 'DR-200',   'Drift Wireless Earbuds',                   1, 149.00, false),
  (1046, 'EK-900',   'Ember Gooseneck Electric Kettle',          1, 129.00, false),
  (1046, 'FUEL-230', 'Isobutane Fuel Canister 230 g',            2,   7.99, false),
  (1047, 'TH-2P-FP', 'Trailhead 2P Footprint (Final Sale)',      1,  35.00, true),
  (1048, 'DR-200',   'Drift Wireless Earbuds',                   1, 149.00, false),
  (1049, 'TH-2P',    'Trailhead 2P Backpacking Tent',            1, 279.00, false);
