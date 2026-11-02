"""Policy grid: refund, cancellation, address-change and late-package cases, labelled by code.

Every case is one cell of a grid (product x days since delivery x what the customer claims, plus
order-state cells for cancellations and late packages). The expected outcome of each cell is
computed from the policies in docs/ by the functions below, never by a model. Sonnet only writes
the customer's message, and that message is checked (order number present, photos mentioned or
not, no dates or durations that could contradict the order record).

The grid's orders live in supabase/seed_grid.sql (written by this module), loaded by the
service-role function seed_grid_data(), which resets the core demo data first. Day counts stay
clear of the policy boundaries (7, 30 and 60 days), so a long run can't drift across one.
"""

import asyncio
import hashlib
import re
from dataclasses import dataclass, field

from pydantic import BaseModel

from evals.generate.common import GENERATED, Generator, load_yaml, write_yaml
from ingestion.config import REPO_ROOT

OUT = GENERATED / "grid.yaml"
SQL = REPO_ROOT / "supabase" / "seed_grid.sql"

CUSTOMERS = [
    ("cus_g01", "Ava Brooks", "ava.brooks@example.com", "303-555-0121", "Denver", "CO"),
    ("cus_g02", "Ben Carter", "ben.carter@example.com", "614-555-0134", "Columbus", "OH"),
    ("cus_g03", "Chloe Diaz", "chloe.diaz@example.com", "602-555-0156", "Phoenix", "AZ"),
    ("cus_g04", "Dev Patel", "dev.patel@example.com", "919-555-0172", "Raleigh", "NC"),
    ("cus_g05", "Elena Rossi", "elena.rossi@example.com", "617-555-0193", "Boston", "MA"),
    ("cus_g06", "Felix Wong", "felix.wong@example.com", "415-555-0128", "San Francisco", "CA"),
]


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price: float
    final_sale: bool
    electronics: bool
    damage: str  # how it arrived damaged
    used: str  # how the customer used it before changing their mind


PRODUCTS = {
    "tent": Product("TH-2P", "Trailhead 2P Backpacking Tent", 279.00, False, False,
                    "a tent pole is snapped and the rainfly is torn", "pitched it once in the backyard; it's clean and undamaged"),
    "earbuds": Product("DR-200", "Drift Wireless Earbuds", 149.00, False, True,
                       "the charging case is cracked and won't charge", "opened them and wore them for a day"),
    "kettle": Product("EK-900", "Ember Gooseneck Electric Kettle", 129.00, False, True,
                      "the base is cracked and it won't power on", "opened it and used it a couple of times"),
    "footprint": Product("TH-2P-FP", "Trailhead 2P Footprint (Final Sale)", 35.00, True, False,
                         "it has a large tear in the middle", "laid it out once under the tent"),
}
TAX_RATE = 0.08
DAYS = [2, 5, 12, 22, 45, 75]  # since delivery; boundaries are at 7, 30 and 60
REFUND_CLAIMS = ["damaged_photos", "damaged_no_photos", "change_unopened", "change_opened"]

NOT_ISSUED = "Says the refund request has been sent for review, without claiming it has already been issued."


@dataclass
class Order:
    number: int
    customer: tuple
    product: str
    quantity: int = 1
    status: str = "delivered"
    delivered_days: float | None = None  # delivered N days ago
    placed_minutes: int | None = None  # processing orders: placed N minutes ago
    est_days: int | None = None  # shipped orders: estimated delivery N days from now (negative = late)

    @property
    def p(self) -> Product:
        return PRODUCTS[self.product]

    @property
    def subtotal(self) -> float:
        return round(self.p.price * self.quantity, 2)

    @property
    def shipping(self) -> float:
        return 0.00 if self.subtotal >= 50 else 5.99  # Standard: free on $50 or more

    @property
    def tax(self) -> float:
        return round(self.subtotal * TAX_RATE, 2)

    @property
    def total(self) -> float:
        return round(self.subtotal + self.shipping + self.tax, 2)

    @property
    def tracking(self) -> str | None:
        return None if self.status == "processing" else f"1Z999AA1{self.number:010d}"

    def describe(self) -> str:
        qty = f"{self.quantity} x " if self.quantity > 1 else ""
        return f"order {self.number}: {qty}{self.p.name}"


@dataclass
class Cell:
    id: str
    order: Order
    situation: str  # what the customer's message must convey, for the writer
    expect: dict
    rubric: list[str]
    tags: list[str]
    photos: bool | None = None  # True: must mention photos; False: must not; None: either
    fresh: bool = False  # depends on minutes since the seed ran, so the runner reseeds right before it
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- the grid and its labels


def refund_label(order: Order, days: float, claim: str) -> tuple[dict, list[str]]:
    """Expected outcome of a refund request, from docs/refund-policy.md."""
    p = order.p
    if claim.startswith("damaged"):
        if days <= 7:
            if claim == "damaged_photos":
                rubric = [NOT_ISSUED]
                if p.final_sale:
                    rubric.append("Treats the Final Sale item as refundable because it arrived damaged.")
                return {"approval": {"tool": "issue_refund", "order": order.number, "amount": order.total},
                        "tools": ["get_order"]}, rubric
            return {"approval": "any", "tools": ["get_order"]}, [
                "Asks for photos of the damage including the outer shipping box, or has sent the refund for review.",
                "Does not claim a refund has already been issued.",
            ]
        return {"approval": "none", "tools": ["get_order"]}, [
            "Explains that damage reported more than 7 days after delivery is handled as a warranty claim, "
            "not a damaged-item refund.",
            "Does not request or promise a damaged-item refund.",
        ]
    if p.final_sale:
        return {"approval": "none", "tools": ["get_order"]}, [
            "Explains the item is Final Sale and can't be returned unless it arrived damaged or defective."]
    if days <= 30:
        rubric = [
            "Explains how to start the return (from the Orders page, print the label, ship within 14 days).",
            "Explains the refund is issued after the return is received and inspected, not right away.",
        ]
        if claim == "change_opened" and p.electronics:
            rubric.append("Mentions the 15% restocking fee for opened electronics.")
        elif claim == "change_opened":
            rubric.append("Mentions that a 15% restocking fee may apply because the item has been used, "
                          "or that used items must be clean and undamaged.")
        else:
            rubric.append("Does not say a restocking fee applies to the unopened item.")
        return {"approval": "none", "tools": ["get_order"]}, rubric
    rubric = ["Explains the order is past the 30-day return window, so it isn't eligible for a refund."]
    if days <= 60:
        rubric.append("Does not promise store credit; at most says store credit may be offered "
                      "at the store's discretion (31-60 days after delivery).")
    else:
        rubric.append("Does not offer store credit (the 31-60 day discretionary window has also passed).")
    return {"approval": "none", "tools": ["get_order"]}, rubric


def refund_situation(order: Order, claim: str) -> tuple[str, bool | None]:
    p = order.p
    item = f"the {p.name}" if order.quantity == 1 else f"both of the {p.name}s"
    return {
        "damaged_photos": (f"{item} arrived damaged: {p.damage}. They have attached photos of the damage and of the "
                           "outer shipping box, and say so. They want a full refund, not a replacement.", True),
        "damaged_no_photos": (f"{item} arrived damaged: {p.damage}. They want their money back. "
                              "They do not mention photos or attachments.", False),
        "change_unopened": (f"they changed their mind about {item}; it is unopened in its original packaging. "
                            "They want to return it for a refund.", None),
        "change_opened": (f"they don't want {item} any more; they {p.used}. They want to return it for a refund.", None),
    }[claim]


def build_cells() -> list[Cell]:
    cells: list[Cell] = []
    numbers = iter(range(2001, 3000))
    customers = iter(CUSTOMERS * 20)

    def order(**kwargs) -> Order:
        return Order(number=next(numbers), customer=next(customers), **kwargs)

    for key, product in PRODUCTS.items():
        for days in DAYS:
            o = order(product=key, delivered_days=days)
            for claim in REFUND_CLAIMS:
                if claim == "damaged_no_photos" and days > 7:
                    continue  # the late-damage cells already cover reports without a refund route
                if claim == "change_opened" and product.final_sale:
                    continue  # same label as unopened: Final Sale
                expect, rubric = refund_label(o, days, claim)
                situation, photos = refund_situation(o, claim)
                window = "in-damage-window" if days <= 7 else "in-return-window" if days <= 30 else (
                    "credit-discretion" if days <= 60 else "past-all-windows")
                cells.append(Cell(f"grid-{key}-d{days}-{claim.replace('_', '-')}", o, situation, expect, rubric,
                                  ["refunds", window] + (["final-sale"] if product.final_sale else []), photos))
    # Extra damaged-in-transit cells inside the 7-day window: the grid's refund-request cases.
    for key in PRODUCTS:
        for days in (1, 4, 6):
            o = order(product=key, delivered_days=days)
            expect, rubric = refund_label(o, days, "damaged_photos")
            situation, photos = refund_situation(o, "damaged_photos")
            cells.append(Cell(f"grid-{key}-d{days}-damaged-photos", o, situation, expect, rubric,
                              ["refunds", "in-damage-window"] + (["final-sale"] if o.p.final_sale else []), photos))
    # Over $500: two tents, damaged in transit (the refund needs a supervisor, which every refund here gets).
    for days in (2, 5):
        o = order(product="tent", quantity=2, delivered_days=days)
        expect, rubric = refund_label(o, days, "damaged_photos")
        situation, photos = refund_situation(o, "damaged_photos")
        cells.append(Cell(f"grid-tent-x2-d{days}-damaged-photos", o, situation, expect, rubric,
                          ["refunds", "in-damage-window", "over-500"], photos))

    for key in ("kettle", "earbuds"):
        p = PRODUCTS[key]
        fresh = order(product=key, status="processing", placed_minutes=10)
        late = order(product=key, status="processing", placed_minutes=180)
        transit = order(product=key, status="shipped", est_days=4)
        overdue = order(product=key, status="shipped", est_days=-2)
        lost = order(product=key, status="shipped", est_days=-20)
        get = {"approval": "none", "tools": ["get_order"]}
        cells += [
            Cell(f"grid-{key}-cancel-fresh", fresh, f"they want to cancel the order (they ordered the wrong {p.name}).",
                 get, ["Says the order can still be cancelled because it was placed less than 1 hour ago.",
                       "Tells the customer to cancel it from the Orders page in their account "
                       "(the agent can't cancel it directly)."], ["orders", "cancel"], fresh=True),
            Cell(f"grid-{key}-cancel-late", late, "they want to cancel the order.", get,
                 ["Explains the 1-hour window to cancel from the Orders page has passed.",
                  "Says that because it hasn't shipped, support will try to stop it but can't guarantee it "
                  "(or opens a ticket to try)."], ["orders", "cancel"]),
            Cell(f"grid-{key}-cancel-shipped", transit, "they want to cancel the order.", get,
                 ["Explains the order has already shipped, so it can't be cancelled.",
                  "Says it can be returned under the refund policy once it arrives."], ["orders", "cancel"]),
            Cell(f"grid-{key}-address-fresh", fresh, "they need to change the shipping address on the order; they typed "
                 "the wrong street.", get,
                 ["Says the address can still be changed from the Orders page because the order was placed "
                  "less than 1 hour ago."], ["orders", "address"], fresh=True),
            Cell(f"grid-{key}-address-late", late, "they need to change the shipping address on the order.", get,
                 ["Explains the address can only be changed within 1 hour of ordering, and that window has passed."],
                 ["orders", "address"]),
            Cell(f"grid-{key}-wismo-transit", transit, "they want to know where the order is.", get,
                 ["Says the order has shipped with UPS and gives the tracking number.",
                  "Gives the estimated delivery date from the order."], ["shipping", "tracking"]),
            Cell(f"grid-{key}-overdue", overdue, "the order hasn't arrived yet and they wonder if it's lost.", get,
                 ["Says the package is past its estimated delivery date but isn't treated as lost until 10 business "
                  "days after it (or until tracking hasn't updated for 5 business days).",
                  "Does not request a refund."], ["shipping", "late"]),
            Cell(f"grid-{key}-lost", lost, "the order never arrived and tracking hasn't moved; they ask what can be done.",
                 {"approval": "any", "tools": ["get_order"], "ticket": True},
                 ["Acknowledges the package is overdue (well past the 10-business-day threshold).",
                  "Gives the customer the ticket number for the lost-package claim.",
                  "Explains that once the package is confirmed lost, they get a free replacement or a full refund."],
                 ["shipping", "lost", "escalation"]),
        ]
    return cells


def orders(cells: list[Cell]) -> list[Order]:
    seen: dict[int, Order] = {}
    for cell in cells:
        seen.setdefault(cell.order.number, cell.order)
    return sorted(seen.values(), key=lambda o: o.number)


# ---------------------------------------------------------------- seed SQL


def _ago(days: float) -> str:
    return f"now() - interval '{days} days'"


def order_sql(o: Order) -> str:
    cid, _, _, _, city, region = o.customer
    if o.status == "delivered":
        placed = shipped = _ago(o.delivered_days + 5)
        delivered, est = _ago(o.delivered_days), f"({_ago(o.delivered_days)})::date"
    elif o.status == "processing":
        placed, shipped, delivered = f"now() - interval '{o.placed_minutes} minutes'", "null", "null"
        est = "(now() + interval '7 days')::date"
    else:
        placed = shipped = _ago(7 - o.est_days)  # shipped a week before the estimated date
        delivered, est = "null", f"(now() + interval '{o.est_days} days')::date"
    carrier = "null" if o.status == "processing" else "'UPS'"
    tracking = f"'{o.tracking}'" if o.tracking else "null"
    return (f"    ({o.number}, '{cid}', '{o.status}', 'standard', '{city}', '{region}', 'US', 'USD',\n"
            f"     {o.subtotal:.2f}, {o.shipping:.2f}, {o.tax:.2f}, {o.total:.2f}, {carrier}, {tracking}, {est},\n"
            f"     {placed}, {shipped}, {delivered}, null)")


def write_sql(cells: list[Cell]) -> None:
    all_orders = orders(cells)
    customers = ",\n".join(f"    ('{c[0]}', '{c[1]}', '{c[2]}', '{c[3]}', '{c[4]}', '{c[5]}', 'US', 100, now() - interval '300 days')"
                           for c in CUSTOMERS)
    order_rows = ",\n".join(order_sql(o) for o in all_orders)
    items = ",\n".join(f"    ({o.number}, '{o.p.sku}', '{o.p.name}', {o.quantity}, {o.p.price:.2f}, {str(o.p.final_sale).lower()})"
                       for o in all_orders)
    SQL.write_text(f"""-- Extra demo customers and orders for the policy-grid evals (evals/generated/grid.yaml).
--
-- GENERATED by `python -m evals.generate grid` from evals/generate/grid.py. Don't edit by hand.
--
-- seed_grid_data() reloads the core demo data (reset_demo_data(), see seed.sql), then adds
-- {len(CUSTOMERS)} customers (cus_g01-cus_g{len(CUSTOMERS):02d}) and {len(all_orders)} orders ({all_orders[0].number}-{all_orders[-1].number}). Dates are
-- relative to now(), like the core seed. Run seed.sql first: its guard allows these ids.

create or replace function public.seed_grid_data()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  perform public.reset_demo_data();

  insert into public.customers (id, name, email, phone, city, region, country, reward_points, created_at) values
{customers};

  insert into public.orders (
    order_number, customer_id, status, shipping_method,
    ship_to_city, ship_to_region, ship_to_country, currency,
    subtotal, shipping_cost, tax, total,
    carrier, tracking_number, estimated_delivery,
    placed_at, shipped_at, delivered_at, cancelled_at
  ) values
{order_rows};

  insert into public.order_items (order_number, sku, product_name, quantity, unit_price, final_sale) values
{items};
end;
$$;

revoke execute on function public.seed_grid_data() from public, anon, authenticated;
grant execute on function public.seed_grid_data() to service_role;
""", encoding="utf-8")


# ---------------------------------------------------------------- messages

STYLES = [
    "polite and brief",
    "frustrated but not abusive",
    "casual, all lowercase, with a couple of typos",
    "rambling, with some irrelevant backstory",
    "terse, a single line",
    "written by a non-native English speaker",
    "formal, like a letter",
]
TIMING = re.compile(r"\b(?:\d+\s*(?:minute|hour|day|week|month)s?|yesterday|today|tonight|this morning|ago|"
                    r"last (?:week|month)|a (?:few|couple of) (?:days|weeks))\b", re.IGNORECASE)
PHOTO = re.compile(r"\b(?:photo|picture|pic|image|attach)", re.IGNORECASE)

WRITER_SYSTEM = """You write customer messages for test cases of a support agent at Lumen & Pine, a fictional online outdoor-gear store. The messages are sent to the agent in a chat where the customer is already signed in.

Write only what the customer types, as one chat message. Convey the situation exactly: include the order number, add no other requests, facts, amounts or claims, and don't say when anything happened (no dates, days, weeks, "yesterday", "ago"): the agent must look that up."""


class Message(BaseModel):
    message: str


def check_message(cell: Cell, text: str) -> str | None:
    """Why a written message doesn't fit its cell, or None if it does."""
    if not re.search(rf"\b{cell.order.number}\b", text):
        return f"it must include the order number {cell.order.number}"
    if TIMING.search(text):
        return f"it mentions timing ({TIMING.search(text).group()!r}); leave all timing out"
    if cell.photos is True and not PHOTO.search(text):
        return "it must say photos of the damage and the shipping box are attached"
    if cell.photos is False and PHOTO.search(text):
        return "it must not mention photos or attachments"
    return None


async def write_message(gen: Generator, cell: Cell) -> str | None:
    style = STYLES[int(hashlib.sha256(cell.id.encode()).hexdigest(), 16) % len(STYLES)]
    prompt = (f"The customer ({cell.order.customer[1]}) has {cell.order.describe()}.\n"
              f"Situation: {cell.situation}\nTone: {style}.")
    for _ in range(3):
        text = (await gen.parse(WRITER_SYSTEM, prompt, Message, max_tokens=2000)).message.strip()
        problem = check_message(cell, text)
        if problem is None:
            return text
        prompt += f"\n\nYour previous message was rejected because {problem}:\n{text}"
    return None


def to_case(cell: Cell, message: str) -> dict:
    case = {"id": cell.id, "source": "grid", "tags": cell.tags, "customer": cell.order.customer[2],
            "turns": [message], "expect": cell.expect, "rubric": cell.rubric}
    if cell.fresh:
        case["fresh_data"] = True
    return case


async def generate(limit: int | None = None, force: bool = False, dry_run: bool = False) -> None:
    cells = build_cells()
    write_sql(cells)
    print(f"Wrote {SQL.relative_to(REPO_ROOT)} ({len(orders(cells))} orders)")
    if dry_run:
        approvals = sum(isinstance(c.expect["approval"], dict) for c in cells)
        print(f"{len(cells)} grid cells ({approvals} expect a refund request). Dry run: no messages written.")
        return

    existing = {c["id"]: c for c in load_yaml(OUT)}
    by_id = {c.id: c for c in cells}
    todo = [c for c in cells if force or c.id not in existing][:limit]
    gen = Generator()
    results = await asyncio.gather(*(write_message(gen, c) for c in todo))
    failed = [c.id for c, text in zip(todo, results, strict=True) if text is None]
    for cell, text in zip(todo, results, strict=True):
        if text is not None:
            existing[cell.id] = to_case(cell, text)
    # Labels always come from the current code, so changing a rule relabels cached messages too.
    cases = [{**to_case(by_id[i], existing[i]["turns"][0])} for i in by_id if i in existing]
    write_yaml(OUT, __doc__.split("\n\n")[0] + "\nGENERATED by `python -m evals.generate grid`. Labels come from "
               "evals/generate/grid.py; to change one, change the rule there and regenerate.", cases)
    print(f"Wrote {OUT.relative_to(REPO_ROOT)}: {len(cases)} cases ({len(todo) - len(failed)} new). "
          f"Sonnet: {gen.calls} calls, ${gen.cost:.3f}.")
    if failed:
        print(f"{len(failed)} messages failed their checks 3 times and were skipped: {', '.join(failed)}")
