"""Score the router alone: does each case reach a specialist allowed to answer it?

Runs only the router (one small ROUTER_MODEL call per customer message, about $0.0001 each on
Haiku), with no agent, tools or judge. Multi-turn cases are routed message by message, as in a
real conversation, and graded on the specialist that ends up with the last message.

Where the labels come from:
    core        the `route` field in cases.yaml, set by hand
    rewordings  their parent core case's route (rewordings of cases no longer in cases.yaml are skipped)
    grid        computed from the grid cell's tags below
    adversarial the attack's target, below; only the attacks marked keep: true

From the repo root:
    python -m evals.route_eval                  # core cases only (about 20 calls)
    python -m evals.route_eval --extended       # plus the generated cases (about 230 calls)
"""

import argparse
import asyncio
import json
import sys
from collections import Counter

import anthropic
import yaml

from agent import router
from agent.models import ROUTER_MODEL
from evals.run_evals import CASES, FLOW, GENERATED
from ingestion.config import require_env

ADVERSARIAL_ROUTES = {
    "other-order": ["shipping", "general"],
    "refund-not-owed": ["billing"],
    "skip-approval": ["billing"],
    "email-elsewhere": ["billing", "shipping", "general"],
    "injected-document": ["billing", "general"],
    "prompt-extraction": ["billing", "general"],
    "off-scope": ["general"],
}


def grid_route(case: dict) -> list[str]:
    tags = case["tags"]
    if tags[0] == "shipping" or "address" in tags:
        return ["shipping"]
    if "damaged" in case["id"] and "in-damage-window" not in tags:
        return ["billing", "tech_support"]  # damage reported late: a warranty claim
    return ["billing"]  # refunds, returns and cancellations


def labelled_cases(extended: bool) -> list[dict]:
    core = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    cases = [{"id": c["id"], "source": "core", "turns": c["turns"], "route": c["route"]} for c in core]
    if not extended:
        return cases
    routes = {c["id"]: c["route"] for c in core}
    for c in yaml.safe_load((GENERATED / "paraphrases.yaml").read_text(encoding="utf-8")):
        if c["parent"] in routes:
            cases.append({"id": c["id"], "source": "paraphrase", "turns": c["turns"], "route": routes[c["parent"]]})
    for c in yaml.safe_load((GENERATED / "grid.yaml").read_text(encoding="utf-8")):
        cases.append({"id": c["id"], "source": "grid", "turns": c["turns"], "route": grid_route(c)})
    for c in yaml.safe_load((GENERATED / "adversarial.yaml").read_text(encoding="utf-8")):
        if c.get("keep"):
            target = next(t for t in c["tags"] if t in ADVERSARIAL_ROUTES)
            cases.append({"id": c["id"], "source": "adversarial", "turns": c["turns"], "route": ADVERSARIAL_ROUTES[target]})
    return cases


async def route_case(client, case: dict, limit: asyncio.Semaphore) -> dict:
    messages, current, calls = [], None, 0
    async with limit:
        for turn in case["turns"]:
            messages.append({"role": "user", "content": turn})
            current, _ = await router.route(client, messages, current)
            calls += 1
    return {**case, "got": current, "ok": current in case["route"], "calls": calls}


async def main_async(args) -> int:
    cases = labelled_cases(args.extended)
    calls = sum(len(c["turns"]) for c in cases)
    print(f"{len(cases)} cases: {calls} router calls on {ROUTER_MODEL}.")
    client = anthropic.AsyncAnthropic(api_key=require_env("ANTHROPIC_API_KEY"), max_retries=4)
    limit = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(*(route_case(client, c, limit) for c in cases))

    by_source: dict[str, list[dict]] = {}
    for r in results:
        by_source.setdefault(r["source"], []).append(r)
    lines = [f"### Routing accuracy ({ROUTER_MODEL})", "", "| Source | Cases | Routed correctly |", "|---|---|---|"]
    for source, rows in by_source.items():
        lines.append(f"| {source} | {len(rows)} | {sum(r['ok'] for r in rows) / len(rows):.0%} |")
    total = sum(r["ok"] for r in results) / len(results)
    lines.append(f"| **all** | {len(results)} | **{total:.0%}** |")
    misses = [r for r in results if not r["ok"]]
    if misses:
        confusion = Counter((r["route"][0], r["got"]) for r in misses)
        lines += ["", "Misrouted (expected -> got): " + ", ".join(f"{e} -> {g} x{n}" for (e, g), n in confusion.most_common())]
        lines += [f"- `{r['id']}`: expected {'/'.join(r['route'])}, got {r['got']}" for r in misses]
    summary = "\n".join(lines) + "\n"
    print("\n" + summary)

    out = FLOW / "routing"
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    (out / "summary.md").write_text(summary, encoding="utf-8")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extended", action="store_true", help="also route the generated cases")
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
