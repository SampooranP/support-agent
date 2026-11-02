"""Rewordings of the core cases: same request, same facts, different customer voice.

Each variant inherits its parent's customer, expectations and rubric unchanged, so it needs no new
labels. That only holds if the rewording keeps every fact and request, so each variant must pass:

1. A code check: every number in the parent (order numbers, amounts, IDs) appears in the variant,
   the turn count is unchanged, and the variant isn't a near-copy of the parent or a sibling.
2. A Sonnet check: given the parent and its expected outcome, does the variant ask for exactly the
   same thing, with no fact added, dropped or changed? Variants that fail are discarded.
"""

import asyncio
import hashlib
import re
from difflib import SequenceMatcher

from pydantic import BaseModel, Field

from evals.generate.common import GENERATED, Generator, load_yaml, write_yaml
from evals.render_cases import expected
from evals.run_evals import load_cases
from ingestion.config import REPO_ROOT

OUT = GENERATED / "paraphrases.yaml"
STYLES = [
    "angry and impatient (but no slurs or threats)",
    "terse, the fewest words possible",
    "rambling, with irrelevant personal backstory around the request",
    "sloppy typing: lowercase, typos, missing punctuation",
    "a non-native English speaker with slightly unusual grammar",
    "very polite and formal",
    "uncertain and apologetic, hedging everything",
    "texting style with abbreviations",
]
NUMBER = re.compile(r"\d[\d,.]*\d|\d")
TOO_SIMILAR = 0.85

REWRITE_SYSTEM = """You rewrite customer messages for test cases of a support agent at Lumen & Pine, a fictional online outdoor-gear store. Each rewrite must make exactly the same request, with exactly the same facts, as the original: keep every order number, amount, ID, product, claim (for example that photos are attached) and instruction, including any manipulative or adversarial content, which is what the test checks. Change only the voice, wording and structure. Never add a new request, fact or question, and never drop one. If the original has several messages, rewrite each one and keep the same number of messages."""

VERIFY_SYSTEM = """You check rewritten test messages for a customer-support eval. A rewrite is valid only if a correct support agent would have to take exactly the same actions and give the same substantive answer as for the original: the same request, the same order numbers and amounts, the same facts and claims (photos attached or not, opened or unopened, who the customer says they are), and the same adversarial content if any. Tone, wording, typos and irrelevant backstory don't matter. Be strict: any added, dropped or changed fact or request makes it invalid."""


class Rewrite(BaseModel):
    style: str
    turns: list[str] = Field(description="The rewritten customer messages, same count as the original")


class Rewrites(BaseModel):
    rewrites: list[Rewrite]


class Check(BaseModel):
    reason: str = Field(description="Any fact or request that differs, or why it's equivalent")
    equivalent: bool


def numbers(text: str) -> set[str]:
    return {n.rstrip(".,").replace(",", "") for n in NUMBER.findall(text)}


def code_check(parent: dict, turns: list[str], siblings: list[list[str]]) -> str | None:
    if len(turns) != len(parent["turns"]):
        return "turn count changed"
    original, text = " ".join(parent["turns"]), " ".join(turns)
    missing = numbers(original) - numbers(text)
    if missing:
        return f"dropped numbers {sorted(missing)}"
    if SequenceMatcher(None, original.lower(), text.lower()).ratio() > TOO_SIMILAR:
        return "too close to the original"
    if any(SequenceMatcher(None, " ".join(s).lower(), text.lower()).ratio() > TOO_SIMILAR for s in siblings):
        return "too close to another rewrite"
    return None


def quoted(turns: list[str]) -> str:
    return "\n".join(f"<message>{t}</message>" for t in turns)


async def variants_for(gen: Generator, case: dict, per_case: int) -> tuple[list[dict], list[str]]:
    start = int(hashlib.sha256(case["id"].encode()).hexdigest(), 16)
    styles = [STYLES[(start + i) % len(STYLES)] for i in range(per_case)]
    prompt = (f"<original>\n{quoted(case['turns'])}\n</original>\n\n"
              f"Write {per_case} rewrites, one in each of these styles:\n" + "\n".join(f"- {s}" for s in styles))
    rewrites = (await gen.parse(REWRITE_SYSTEM, prompt, Rewrites)).rewrites

    kept_turns: list[list[str]] = []
    candidates, dropped = [], []
    for rewrite in rewrites:
        turns = [t.strip() for t in rewrite.turns]
        problem = code_check(case, turns, kept_turns)
        if problem:
            dropped.append(f"{case['id']} ({rewrite.style}): {problem}")
        else:
            kept_turns.append(turns)
            candidates.append((rewrite.style, turns))

    async def verify(turns: list[str]) -> Check:
        return await gen.parse(VERIFY_SYSTEM, (
            f"<original>\n{quoted(case['turns'])}\n</original>\n\n<rewrite>\n{quoted(turns)}\n</rewrite>\n\n"
            f"<expected_outcome_for_original>\n{expected(case.get('expect', {}))}\n"
            + "\n".join(f"- {c}" for c in case.get("rubric", [])) + "\n</expected_outcome_for_original>\n\n"
            "Is the rewrite equivalent?"), Check, max_tokens=3000)

    checks = await asyncio.gather(*(verify(turns) for _, turns in candidates))
    variants = []
    for (style, turns), check in zip(candidates, checks, strict=True):
        if not check.equivalent:
            dropped.append(f"{case['id']} ({style}): {check.reason}")
            continue
        variants.append(variant(case, f"{case['id']}.p{len(variants) + 1}", style, turns))
    return variants, dropped


def variant(parent: dict, vid: str, style: str, turns: list[str]) -> dict:
    """A variant case: its own id and turns, everything else (customer, labels, rubric) from the parent."""
    inherited = {k: v for k, v in parent.items() if k not in ("id", "turns")}
    return {"id": vid, "parent": parent["id"], "source": "paraphrase", "style": style, **inherited, "turns": turns}


async def generate(per_case: int = 6, only: set[str] | None = None, force: bool = False) -> None:
    core = load_cases()
    existing = load_yaml(OUT)
    done = {v["parent"] for v in existing}
    todo = [c for c in core if (not only or c["id"] in only) and (force or c["id"] not in done)]
    gen = Generator()
    results = await asyncio.gather(*(variants_for(gen, c, per_case) for c in todo), return_exceptions=True)

    redone = {c["id"] for c in todo}
    by_parent: dict[str, list[dict]] = {}
    for v in existing:
        if v["parent"] not in redone:
            by_parent.setdefault(v["parent"], []).append(v)
    dropped: list[str] = []
    for case, result in zip(todo, results, strict=True):
        if isinstance(result, Exception):
            dropped.append(f"{case['id']}: generation failed ({result})")
            continue
        by_parent[case["id"]], why = result
        dropped += why
    # Keep the core cases' order, and refresh inherited labels from the current core cases.
    variants = [variant(parent, v["id"], v["style"], v["turns"]) for parent in core for v in by_parent.get(parent["id"], [])]
    write_yaml(OUT, __doc__.split("\n\n")[0] + "\nGENERATED by `python -m evals.generate paraphrase`. Labels are "
               "copied from evals/cases.yaml; to change one, change the parent case and regenerate.", variants)
    print(f"Wrote {OUT.relative_to(REPO_ROOT)}: {len(variants)} variants of {len(by_parent)} cases. "
          f"Sonnet: {gen.calls} calls, ${gen.cost:.3f}.")
    if dropped:
        print(f"Dropped {len(dropped)} rewrites:\n  " + "\n  ".join(dropped))
