"""Load a Gmail scan snapshot into the portfolio tracker.

Why a file rather than a live sync: the app on EC2 cannot reach Gmail. Its
Google OAuth requests only `openid email profile`, with `access_type=online`,
so there is no Gmail scope and no refresh token to act with later. A live
integration would need Stefan to re-consent to a `gmail.readonly` scope and the
app to store a refresh token — a real change, not a config tweak.

Until then the scan is produced by Claude reading the mailbox in a session and
written here, and this script loads it. Re-running with a newer snapshot
refreshes every row it names; rows it does not name are left alone.

    uv run python scripts/import_gmail_scan.py <scan.json> [--dry-run]
"""

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import content
from portfolio_store import PortfolioStore

ALIASES = {"Hypernote": "Hyprnote"}


def known_names() -> set[str]:
    return {c.name for c in (*content.PORTFOLIO, content.BITMOVIN)}


def check(scan: dict) -> list[str]:
    known = known_names()
    problems = []
    for name, rec in scan["companies"].items():
        if ALIASES.get(name, name) not in known:
            problems.append(f"unknown company: {name!r}")
        if not rec.get("date"):
            problems.append(f"no date for {name!r}")
        else:
            try:
                date.fromisoformat(rec["date"])
            except ValueError:
                problems.append(f"bad date for {name!r}: {rec['date']!r}")
    return problems


async def main(path: Path, dry_run: bool):
    scan = json.loads(path.read_text())
    problems = check(scan)
    if problems:
        print("REFUSING TO IMPORT:")
        for p in problems:
            print("  -", p)
        return 1

    matched = scan["companies"]
    unmatched = sorted(known_names() - {ALIASES.get(n, n) for n in matched})
    today = date.fromisoformat(scan["scanned_on"])

    print(f"scan of {scan['scanned_on']}: {len(matched)} matched, {len(unmatched)} not")
    print()
    print("  longest silences among matched:")
    ranked = sorted(matched.items(), key=lambda kv: kv[1]["date"])
    for name, rec in ranked[:5]:
        days = (today - date.fromisoformat(rec["date"])).days
        print(f"    {days:>5}d  {name}")
    print()
    print("  no message matched (silent, or a domain we did not search):")
    print("   ", ", ".join(unmatched))

    if dry_run:
        print("\n(dry run — nothing written)")
        return 0

    store = PortfolioStore()
    await store.open()
    try:
        for name, rec in matched.items():
            await store.upsert(ALIASES.get(name, name), {
                "last_heard_on": rec["date"],
                "last_heard_from": rec.get("from", ""),
                "last_heard_subject": rec.get("subject", ""),
                "last_heard_thread": rec.get("thread", ""),
            })
        print(f"\nwrote last-heard for {len(matched)} companies")
    finally:
        await store.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scan", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.scan, a.dry_run)))
