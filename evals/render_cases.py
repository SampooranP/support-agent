"""Render evals/cases.yaml as evals/cases.md, a readable list for reviewing the cases.

    python -m evals.render_cases
"""

import re

import yaml

from ingestion.config import REPO_ROOT

CASES = REPO_ROOT / "evals" / "cases.yaml"
OUT = REPO_ROOT / "evals" / "cases.md"


def expected(expect: dict) -> str:
    approval = expect.get("approval", "none")
    if isinstance(approval, dict):
        parts = [f"requests `{approval['tool']}` on #{approval.get('order')} for {approval.get('amount')}"]
    else:
        parts = {"none": ["no refund or email"], "any": ["approval not graded"]}[approval]
    if expect.get("tools"):
        parts.append("calls " + ", ".join(f"`{t}`" for t in expect["tools"]))
    if expect.get("ticket") is True:
        parts.append("opens a ticket")
    if expect.get("decision"):
        parts.append(f"then supervisor **{expect['decision']}s**")
    if expect.get("must_not_reveal"):
        parts.append(f"reveals none of {len(expect['must_not_reveal'])} secrets")
    return "; ".join(parts)


def fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}text\n{text}\n{ticks}"


def render(cases: list[dict], title: str, intro: str) -> str:
    lines = [f"# {title}", "", intro, "", "| # | id | tags | customer | expected |", "|---|---|---|---|---|"]
    for i, case in enumerate(cases, 1):
        lines.append(f"| {i} | [{case['id']}](#{case['id'].replace('.', '')}) | {', '.join(case.get('tags', []))} | "
                     f"{case['customer'].split('@')[0]} | {expected(case.get('expect', {}))} |")
    for case in cases:
        expect = case.get("expect", {})
        lines += ["", f"## {case['id']}", "", f"**Customer:** {case['customer']}  ", f"**Expected:** {expected(expect)}"]
        for key, label in (("parent", "Rewording of"), ("style", "Style"), ("technique", "Technique"), ("keep", "keep")):
            if key in case:
                lines[-1] += "  "
                lines.append(f"**{label}:** {case[key]}")
        if expect.get("note"):
            lines.append(f"**Supervisor note:** {expect['note']}  ")
        if expect.get("must_not_reveal"):
            lines.append("**Must not reveal:** " + ", ".join(f"`{s}`" for s in expect["must_not_reveal"]))
        for n, turn in enumerate(case["turns"], 1):
            lines += ["", f"Customer message {n}:" if len(case["turns"]) > 1 else "Customer message:", "", fence(turn)]
        if case.get("rubric"):
            lines += ["", "Judge criteria:", ""] + [f"- {c}" for c in case["rubric"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    OUT.write_text(render(cases, "Eval cases", f"{len(cases)} cases, generated from `cases.yaml` by "
                          "`python -m evals.render_cases`. Expected outcomes come from the policies in `docs/` "
                          "and the orders in `supabase/seed.sql`."), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(REPO_ROOT)} ({len(cases)} cases)")


if __name__ == "__main__":
    main()
