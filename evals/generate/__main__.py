"""Generate the extended eval suite (evals/generated/) from the core cases and the policies.

    python -m evals.generate grid --dry-run       # free: write supabase/seed_grid.sql, count the cells
    python -m evals.generate grid                 # Sonnet writes one message per grid cell
    python -m evals.generate paraphrase           # 6 checked rewordings of each core case
    python -m evals.generate adversarial          # 5 attack candidates per target, all keep: false
    python -m evals.generate review               # free: write the review pages

Generation is cached: each command only fills in what's missing (pass --force to redo it). The
review pages are evals/generated/spotcheck.md (a random sample of rewordings and grid cases to
read) and evals/generated/adversarial.md (every attack candidate, to pick the ones to keep).

Run the suite with `python -m evals.run_evals --suite extended` (after approving its harness).
"""

import argparse
import asyncio
import random
import sys

from evals.generate import adversarial, grid, paraphrase
from evals.generate.common import GENERATED, load_yaml
from evals.render_cases import render
from ingestion.config import REPO_ROOT


def review(sample: int, seed: int) -> None:
    generated = load_yaml(paraphrase.OUT) + load_yaml(grid.OUT)
    picked = random.Random(seed).sample(generated, min(sample, len(generated)))
    pages = {
        GENERATED / "spotcheck.md": render(
            sorted(picked, key=lambda c: c["id"]), "Spot check: generated cases",
            f"A random sample of {len(picked)} of the {len(generated)} reworded and grid cases (seed {seed}). Check "
            "that each message really asks what its expected outcome assumes. Rewordings inherit their parent's "
            "labels; grid labels come from evals/generate/grid.py."),
        GENERATED / "adversarial.md": render(
            load_yaml(adversarial.OUT), "Adversarial candidates",
            "Every attack Sonnet wrote. Set `keep: true` in adversarial.yaml on the ones worth running."),
    }
    for path, text in pages.items():
        path.write_text(text, encoding="utf-8")
        print(f"Wrote {path.relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("what", choices=["grid", "paraphrase", "adversarial", "review"])
    parser.add_argument("--force", action="store_true", help="regenerate even what's already there")
    parser.add_argument("--dry-run", action="store_true", help="grid only: write the seed SQL, no API calls")
    parser.add_argument("--limit", type=int, help="grid only: at most this many new messages (for a trial)")
    parser.add_argument("--only", help="paraphrase only: comma-separated core case ids")
    parser.add_argument("--per-case", type=int, default=6, help="paraphrase: rewrites requested per core case")
    parser.add_argument("--per-target", type=int, default=5, help="adversarial: attacks per target")
    parser.add_argument("--sample", type=int, default=20, help="review: cases in the spot check")
    parser.add_argument("--seed", type=int, default=1, help="review: change it for a fresh sample")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.what == "grid":
        asyncio.run(grid.generate(limit=args.limit, force=args.force, dry_run=args.dry_run))
    elif args.what == "paraphrase":
        only = set(args.only.split(",")) if args.only else None
        asyncio.run(paraphrase.generate(per_case=args.per_case, only=only, force=args.force))
    elif args.what == "adversarial":
        asyncio.run(adversarial.generate(per_target=args.per_target, force=args.force))
    if args.what != "grid" or not args.dry_run:
        review(args.sample, args.seed)


if __name__ == "__main__":
    main()
