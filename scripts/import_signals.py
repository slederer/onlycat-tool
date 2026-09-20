"""Load extracted metrics, events and asks into the tracker.

Same snapshot model as import_gmail_scan.py, and for the same reason: the app
has no Gmail access, so extraction happens in a Claude session and lands here.

Idempotent — re-running a corrected file overwrites the same rows.

    uv run python scripts/import_signals.py scripts/signals_2026_09_20.json [--dry-run]
"""

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import content
from portfolio_signals import EVENT_KINDS, METRIC_FIELDS, SignalStore, trajectory
from portfolio_store import DB_PATH

ALIASES = {"Hypernote": "Hyprnote"}


def check(data: dict) -> list[str]:
    known = {c.name for c in (*content.PORTFOLIO, content.BITMOVIN)}
    problems = []

    def seen(name, where):
        resolved = ALIASES.get(name, name)
        if resolved not in known:
            problems.append(f"{where}: unknown company {name!r}")
        return resolved

    for m in data.get("metrics", []):
        seen(m["company"], "metrics")
        try:
            date.fromisoformat(m["as_of"])
        except (KeyError, ValueError):
            problems.append(f"metrics: bad as_of for {m.get('company')!r}")
        if not any(m.get(f) is not None for f in METRIC_FIELDS):
            problems.append(f"metrics: {m.get('company')!r} {m.get('as_of')} has no numbers")
        if not m.get("source_thread"):
            # Provenance is the whole guard against a hallucinated figure.
            problems.append(f"metrics: {m.get('company')!r} {m.get('as_of')} has no source")

    for e in data.get("events", []):
        seen(e["company"], "events")
        if e.get("kind") not in EVENT_KINDS:
            problems.append(f"events: unknown kind {e.get('kind')!r}")
        if not e.get("source_thread"):
            problems.append(f"events: {e.get('company')!r} has no source")

    for a in data.get("asks", []):
        seen(a["company"], "asks")
        if not a.get("ask"):
            problems.append(f"asks: {a.get('company')!r} has no text")

    return problems


async def main(path: Path, dry_run: bool):
    data = json.loads(path.read_text())
    problems = check(data)
    if problems:
        print("REFUSING TO IMPORT:")
        for p in problems:
            print("  -", p)
        return 1

    metrics = data.get("metrics", [])
    events = data.get("events", [])
    asks = data.get("asks", [])
    companies = sorted({ALIASES.get(m["company"], m["company"]) for m in metrics})

    print(f"{len(metrics)} metric rows across {len(companies)} companies")
    print(f"{len(events)} events, {len(asks)} asks")

    # Show the trajectories the data implies, so a bad extraction is visible
    # here rather than after it has been written and charted.
    grouped: dict[str, list[dict]] = {}
    for m in metrics:
        grouped.setdefault(ALIASES.get(m["company"], m["company"]), []).append(m)
    print("\n  trajectories:")
    for name, rows in sorted(grouped.items()):
        t = trajectory(sorted(rows, key=lambda r: r["as_of"]))
        if not t:
            continue
        arrow = "down" if t["past_peak"] else "up"
        off = f"{t['off_peak_pct']:+.0f}% vs peak" if t["off_peak_pct"] is not None else ""
        print(f"    {name:14} {t['months']}pts  {t['currency']} {t['latest']:>12,.0f}  {arrow:4} {off}")

    if dry_run:
        print("\n(dry run — nothing written)")
        return 0

    store = SignalStore(DB_PATH)
    await store.open()
    try:
        for m in metrics:
            co = ALIASES.get(m["company"], m["company"])
            await store.put_metric(co, m["as_of"], **{
                k: v for k, v in m.items() if k not in ("company", "as_of")
            })
        for e in events:
            await store.put_event(ALIASES.get(e["company"], e["company"]),
                                  e["occurred_on"], e["kind"], e["summary"],
                                  e.get("source_thread", ""))
        for a in asks:
            await store.put_ask(ALIASES.get(a["company"], a["company"]),
                                a["asked_on"], a["ask"], a.get("source_thread", ""))
        print(f"\nwrote {len(metrics)} metrics, {len(events)} events, {len(asks)} asks")
    finally:
        await store.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("signals", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.signals, a.dry_run)))
