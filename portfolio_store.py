"""SQLite-backed tracking data for the angel portfolio.

`content.py` owns the *public* facts about each company — name, blurb, sector,
link. This module owns the *private* ones: what was invested, when, on what
terms, and what the position is worth now. The two are joined on company name.

Nothing here is rendered on the public site except `status`, `round_stage` and
the investment year. See `public_overlay()`, which is deliberately the only
function that hands anything to the homepage, so there is one place to audit
when asking "can a number leak?".
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent / "onlycat_events.db"))

# Mirrors content.COMPANY_STATUSES, plus "unknown" — the honest default for a
# company that has not been looked at yet. content.py defaults to "active",
# which is how all 41 ended up claiming to be alive on the public page.
STATUSES = ("unknown", "active", "exited", "acquired", "dead")

INSTRUMENTS = ("SAFE", "Priced equity", "Convertible note", "Secondary", "Other")

STAGES = ("Pre-seed", "Seed", "Seed+", "Series A", "Series B", "Series C+", "Growth")

# A position untouched for this long is probably stale rather than flat.
STALE_AFTER_DAYS = 180

# Fields the admin form may write. Anything not listed here is ignored, so a
# stray key in a JSON body can never reach the SQL.
EDITABLE = (
    "invested_on", "amount", "currency", "instrument", "round_stage",
    "entry_valuation", "current_value", "realized", "status", "notes",
    # 1 when the date is a placeholder rather than something Stefan supplied.
    # Kept as real state instead of inferred from a magic string in `notes`.
    "date_inferred",
)

_NUMERIC = ("amount", "entry_valuation", "current_value", "realized")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PortfolioStore:
    """One row per company. Keyed by the name used in content.PORTFOLIO."""

    def __init__(self, db_path: str | Path = DB_PATH):
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def open(self):
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS investments (
                company TEXT PRIMARY KEY,
                invested_on TEXT,
                amount REAL,
                currency TEXT DEFAULT 'USD',
                instrument TEXT,
                round_stage TEXT,
                entry_valuation REAL,
                current_value REAL,
                realized REAL,
                status TEXT DEFAULT 'unknown',
                notes TEXT,
                date_inferred INTEGER DEFAULT 0,
                updated_at TEXT
            )
        """)
        await self._migrate()
        await self._db.commit()
        logger.info("Portfolio store opened: %s", self._db_path)

    async def _migrate(self):
        """Add columns introduced after the table was first created.

        SQLite has no "ADD COLUMN IF NOT EXISTS", and the table already exists
        in production, so check before altering.
        """
        async with self._db.execute("PRAGMA table_info(investments)") as cur:
            have = {r[1] for r in await cur.fetchall()}
        for col, ddl in (("date_inferred", "INTEGER DEFAULT 0"),):
            if col not in have:
                await self._db.execute(f"ALTER TABLE investments ADD COLUMN {col} {ddl}")
                logger.info("migrated: added investments.%s", col)

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    async def get_all(self) -> dict[str, dict]:
        """Every tracked row, keyed by company name."""
        async with self._db.execute("SELECT * FROM investments") as cur:
            return {r["company"]: dict(r) for r in await cur.fetchall()}

    async def get(self, company: str) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM investments WHERE company = ?", (company,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def upsert(self, company: str, fields: dict) -> dict:
        """Write the editable subset of `fields` for one company.

        Unknown keys are dropped rather than rejected: the form posts the whole
        row back and we would rather ignore an extra key than 400 the save.
        """
        clean = {k: fields[k] for k in EDITABLE if k in fields}
        for k in _NUMERIC:
            if k in clean:
                clean[k] = _as_float(clean[k])
        if "date_inferred" in clean:
            clean["date_inferred"] = 1 if clean["date_inferred"] in (1, "1", True, "true") else 0
        if clean.get("status") not in (None, *STATUSES):
            raise ValueError(f"unknown status: {clean['status']!r}")
        clean["updated_at"] = _utcnow()

        cols = ", ".join(clean)
        marks = ", ".join("?" for _ in clean)
        updates = ", ".join(f"{k}=excluded.{k}" for k in clean)
        await self._db.execute(
            f"""INSERT INTO investments (company, {cols}) VALUES (?, {marks})
                ON CONFLICT(company) DO UPDATE SET {updates}""",
            (company, *clean.values()),
        )
        await self._db.commit()
        return await self.get(company)

    async def delete(self, company: str):
        """Drop the tracking row. The company stays on the public site."""
        await self._db.execute("DELETE FROM investments WHERE company = ?", (company,))
        await self._db.commit()


def _as_float(v) -> float | None:
    """Empty string and None both mean "not recorded", not zero."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def public_overlay(rows: dict[str, dict]) -> dict[str, dict]:
    """The only tracked fields allowed onto the public page.

    Money never appears here. If you add a field, ask whether you would be
    happy seeing it on slederer.com, because that is where it will end up.
    """
    out = {}
    for name, r in rows.items():
        year = None
        # An inferred date is a working placeholder, not a fact about the
        # company. It may drive the private analytics; it must never be
        # published as though Stefan had stated it.
        if r.get("invested_on") and not r.get("date_inferred"):
            year = str(r["invested_on"])[:4]
        out[name] = {
            "status": r.get("status") or "unknown",
            "stage": r.get("round_stage") or "",
            "year": int(year) if year and year.isdigit() else None,
        }
    return out


def summarise(companies, rows: dict[str, dict]) -> dict:
    """Portfolio analytics over `companies` (content.Company) joined to `rows`.

    Every figure is derived only from positions that actually carry the numbers
    it needs, and each one reports its own coverage. A TVPI computed over the
    third of the book that happens to be filled in is not a portfolio return,
    and the page says so rather than printing a confident number.
    """
    total = len(companies)
    tracked = [c for c in companies if c.name in rows]

    cost_rows = [(c, rows[c.name]) for c in tracked if _as_float(rows[c.name].get("amount"))]
    total_cost = sum(_as_float(r["amount"]) for _, r in cost_rows)

    # Value = latest mark where given, else fall back to cost (held at par).
    # Realized is added on top; an exited position keeps its proceeds.
    valued, value_known_cost = [], 0.0
    total_value = 0.0
    total_realized = 0.0
    for c, r in cost_rows:
        cost = _as_float(r["amount"])
        mark = _as_float(r.get("current_value"))
        realized = _as_float(r.get("realized")) or 0.0
        status = (r.get("status") or "unknown").lower()
        if status == "dead":
            mark = 0.0
        elif mark is None:
            mark = cost  # held at cost, not a markup
        else:
            value_known_cost += cost
            valued.append(c.name)
        total_value += mark
        total_realized += realized

    def pct(part, whole):
        return round(100 * part / whole, 1) if whole else 0.0

    # --- exposure by sector and vintage, weighted by money at risk ---
    by_sector: dict[str, float] = {}
    by_vintage: dict[str, float] = {}
    for c, r in cost_rows:
        amt = _as_float(r["amount"])
        by_sector[c.sector or "Unsorted"] = by_sector.get(c.sector or "Unsorted", 0.0) + amt
        year = str(r.get("invested_on") or "")[:4] or "Undated"
        by_vintage[year] = by_vintage.get(year, 0.0) + amt

    # --- concentration: how much rides on the largest few positions ---
    ranked = sorted(cost_rows, key=lambda cr: _as_float(cr[1]["amount"]), reverse=True)
    top5 = sum(_as_float(r["amount"]) for _, r in ranked[:5])

    # --- status mix, counting untracked companies honestly as unknown ---
    status_mix: dict[str, int] = {}
    for c in companies:
        s = (rows.get(c.name, {}).get("status") or "unknown").lower()
        status_mix[s] = status_mix.get(s, 0) + 1

    # --- positions nobody has looked at in a while ---
    now = datetime.now(timezone.utc)
    stale = []
    for c in tracked:
        ts = rows[c.name].get("updated_at")
        if not ts:
            continue
        try:
            age = (now - datetime.fromisoformat(ts)).days
        except ValueError:
            continue
        if age >= STALE_AFTER_DAYS:
            stale.append({"company": c.name, "days": age})
    stale.sort(key=lambda s: -s["days"])

    inferred_dates = sum(1 for c in tracked if rows[c.name].get("date_inferred"))

    return {
        "counts": {
            "total": total,
            "tracked": len(tracked),
            "with_amount": len(cost_rows),
            "with_mark": len(valued),
            "untracked": total - len(tracked),
            # Placeholder dates. They drive the vintage chart but are withheld
            # from the public page, so it is worth knowing how many remain.
            "inferred_dates": inferred_dates,
        },
        "coverage": {
            # The number that decides whether anything below is trustworthy.
            "amount_pct": pct(len(cost_rows), total),
            "mark_pct": pct(len(valued), len(cost_rows)) if cost_rows else 0.0,
        },
        "money": {
            "cost": round(total_cost, 2),
            "value": round(total_value, 2),
            "realized": round(total_realized, 2),
            # TVPI over recorded positions only — not the whole book.
            "tvpi": round((total_value + total_realized) / total_cost, 2) if total_cost else None,
            "dpi": round(total_realized / total_cost, 2) if total_cost else None,
            # What share of cost has a real mark behind it rather than par.
            "marked_pct": pct(value_known_cost, total_cost),
        },
        "sectors": [
            {"label": k, "cost": round(v, 2), "pct": pct(v, total_cost)}
            for k, v in sorted(by_sector.items(), key=lambda kv: -kv[1])
        ],
        "vintages": [
            {"label": k, "cost": round(v, 2), "pct": pct(v, total_cost)}
            for k, v in sorted(by_vintage.items())
        ],
        "concentration": {
            "top5_pct": pct(top5, total_cost),
            "top5": [
                {"company": c.name, "cost": round(_as_float(r["amount"]), 2),
                 "pct": pct(_as_float(r["amount"]), total_cost)}
                for c, r in ranked[:5]
            ],
        },
        "status_mix": status_mix,
        "stale": stale,
    }
