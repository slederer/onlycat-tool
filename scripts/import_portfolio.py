"""One-off import of Stefan's investment data into the portfolio tracker.

Idempotent: re-running overwrites the same rows rather than duplicating, so it
is safe to edit the table below and run it again.

Dates come in two kinds and the difference is recorded, not hidden:

  * GIVEN    — Stefan supplied a month and year. Stored on the 1st, because
               month is all the precision there is.
  * INFERRED — no date supplied. The source list is in rough chronological
               order, so these are interpolated between their dated neighbours
               and tagged "date inferred" in `notes` so they can be found and
               corrected later. An inferred date is a placeholder, not a fact.

Status is deliberately left `unknown` for every row. Stefan gave amounts and
dates, not outcomes, and guessing "active" for all 42 would recreate exactly
the staleness the tracker exists to fix.

    uv run python scripts/import_portfolio.py [--dry-run]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import content
from portfolio_store import PortfolioStore

# (name, amount USD, date or None, inferred?)
# Order is Stefan's own, which is roughly chronological — the basis for the
# interpolation below.
ROWS = [
    ("Oden.io",            15000,  "2018-06-01", True),
    ("crate",              19000,  "2018-11-01", True),
    ("Cosmic JS",          10000,  "2019-04-01", True),
    ("Upflow",             40000,  "2019-10-01", True),
    ("Linemetrics",        20800,  "2020-03-01", True),
    ("Reflect",            15000,  "2020-08-01", False),
    ("Kilobaser",          20000,  "2021-03-01", False),
    ("Waydev",             15000,  "2021-03-01", False),
    ("Resquared",          15000,  "2021-03-01", False),
    ("Rownd",              20000,  "2022-03-01", False),
    ("Onboard.io",         20000,  "2022-03-01", False),
    ("Invofox",            10000,  "2022-09-01", False),
    ("Hilos",              10000,  "2022-09-01", False),
    ("Bitmovin",          131000,  "2022-12-01", False),
    ("AiSDR",              10000,  "2023-09-01", False),
    ("Kickscale",          30000,  "2023-11-01", False),
    ("Salvy",              18000,  "2024-03-01", False),
    ("Onedoclabs",          5000,  "2024-03-01", False),
    ("Ozeki",               5000,  "2024-04-01", False),
    ("HockeyStack",        10000,  "2024-05-01", False),
    ("Linq",                5000,  "2024-08-01", False),
    ("GlassKube",           5000,  "2024-09-01", False),
    ("HumanLayer",         10000,  "2024-12-01", False),
    ("Rewbi",              10000,  "2024-12-01", False),
    ("SpaceX",             25000,  "2024-12-01", False),
    # --- undated block, sitting between SpaceX (Dec 24) and Mistral (Apr 26) ---
    ("Red Barn Robotics",   5000,  "2025-01-01", True),
    ("Splash Inc.",        10000,  "2025-02-01", True),
    ("Promptless",          5000,  "2025-03-01", True),
    ("Dartboard Energy",   10000,  "2025-05-01", True),
    ("0.email",             5000,  "2025-06-01", True),
    ("Pally",               5000,  "2025-07-01", True),
    ("Trace",               5000,  "2025-08-01", True),
    ("Hyprnote",            5000,  "2025-10-01", True),
    ("Statewide",           5000,  "2025-11-01", True),
    ("Golpo",               5000,  "2025-12-01", True),
    ("Earendil",            7500,  "2026-01-01", True),
    ("GuardAero",          25000,  "2026-03-01", True),
    ("Mistral",            25000,  "2026-04-01", False),
    # Stefan wrote "Sep.20" for these four. Every other row uses month.YY, which
    # would make that September 2020 — impossible: all four are YC Summer 2026
    # companies that did not exist in 2020. Read as September 2026 (this month),
    # which is when they were added to the list. Flagged so it is easy to fix.
    ("Axelrod",             5000,  "2026-09-01", True),
    ("Verdict Machine",     5000,  "2026-09-01", True),
    ("Screenpipe",         10000,  "2026-09-01", True),
    ("Effractor",          10000,  "2026-09-01", True),
]

# Stefan's spelling -> the site's. Keeps his list pasteable as-is.
ALIASES = {"Hypernote": "Hyprnote"}

INFERRED_NOTE = "date inferred — amount is Stefan's, date is a placeholder"


def known_names() -> set[str]:
    return {c.name for c in (*content.PORTFOLIO, content.BITMOVIN)}


def check() -> list[str]:
    """Fail loudly on a name that would silently create an orphan row."""
    known = known_names()
    problems = []
    seen = set()
    for name, amount, date, _ in ROWS:
        resolved = ALIASES.get(name, name)
        if resolved not in known:
            problems.append(f"unknown company: {name!r}")
        if resolved in seen:
            problems.append(f"duplicate row: {name!r}")
        seen.add(resolved)
        if not amount or amount <= 0:
            problems.append(f"bad amount for {name!r}: {amount!r}")
    for missing in sorted(known - seen):
        problems.append(f"no row supplied for: {missing!r}")
    return problems


async def main(dry_run: bool):
    problems = check()
    if problems:
        print("REFUSING TO IMPORT:")
        for p in problems:
            print("  -", p)
        return 1

    total = sum(r[1] for r in ROWS)
    inferred = [r[0] for r in ROWS if r[3]]
    print(f"{len(ROWS)} companies, ${total:,.0f} total")
    print(f"{len(ROWS) - len(inferred)} dates given, {len(inferred)} inferred")
    if dry_run:
        print("\n(dry run — nothing written)")
        return 0

    store = PortfolioStore()
    await store.open()
    try:
        for name, amount, date, is_inferred in ROWS:
            await store.upsert(ALIASES.get(name, name), {
                "amount": amount,
                "currency": "USD",
                "invested_on": date,
                "notes": INFERRED_NOTE if is_inferred else "",
                # No status: Stefan gave money and dates, not outcomes.
            })
        rows = await store.get_all()
        print(f"wrote {len(rows)} rows")
    finally:
        await store.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(asyncio.run(main(ap.parse_args().dry_run)))
