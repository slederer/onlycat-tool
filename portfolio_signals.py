"""Metrics, events and asks extracted from founder updates.

`portfolio_store` holds what Stefan knows first-hand: what he paid, when, what
he thinks it is worth. This module holds what the companies told him — ARR,
runway, headcount, raises, pivots, and the intros they asked for.

Everything here is EXTRACTED from prose, which means it can be wrong. A
hallucinated ARR is worse than no ARR because it looks authoritative and gets
acted on. So every row carries the Gmail thread it came from, the UI links
straight to it, and nothing is shown without that provenance.

Month precision throughout: founder updates are monthly or quarterly, and
pretending to know the day is false precision.
"""

import logging
from datetime import date, datetime, timezone

import aiosqlite

logger = logging.getLogger(__name__)

# Event kinds. `weight` feeds the triage score; `tone` drives colour, and is
# always paired with the kind's label in the UI so colour is never alone.
EVENT_KINDS = {
    "raise":     {"label": "Raised",       "tone": "good",     "weight": -15},
    "milestone": {"label": "Milestone",    "tone": "good",     "weight": -5},
    "offer":     {"label": "Offer / M&A",  "tone": "neutral",  "weight": 0},
    "pivot":     {"label": "Pivot",        "tone": "warning",  "weight": 10},
    "layoff":    {"label": "Layoffs",      "tone": "serious",  "weight": 20},
    "decline":   {"label": "Declining",    "tone": "serious",  "weight": 20},
    # THE COMPANY winding up — not retiring a product line, which is a pivot.
    "shutdown":  {"label": "Shutting down", "tone": "critical", "weight": 60},
}

METRIC_FIELDS = (
    "arr", "mrr", "revenue_month", "runway_months", "burn_monthly",
    "cash", "headcount", "customers",
)

# Below this many months of runway, the clock matters more than the growth rate.
RUNWAY_ALARM_MONTHS = 12


class SignalStore:
    """Metrics/events/asks for portfolio companies. Same DB as PortfolioStore."""

    def __init__(self, db_path):
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def open(self):
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS company_metrics (
                company TEXT NOT NULL,
                as_of TEXT NOT NULL,
                arr REAL, mrr REAL, revenue_month REAL,
                runway_months REAL, burn_monthly REAL, cash REAL,
                headcount INTEGER, customers INTEGER,
                currency TEXT DEFAULT 'USD',
                note TEXT,
                source_thread TEXT,
                source_subject TEXT,
                PRIMARY KEY (company, as_of)
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS company_events (
                company TEXT NOT NULL,
                occurred_on TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                source_thread TEXT,
                PRIMARY KEY (company, occurred_on, kind)
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS company_asks (
                company TEXT NOT NULL,
                asked_on TEXT NOT NULL,
                ask TEXT NOT NULL,
                answered INTEGER DEFAULT 0,
                source_thread TEXT,
                PRIMARY KEY (company, asked_on)
            )
        """)
        await self._db.commit()
        logger.info("Signal store opened: %s", self._db_path)

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    # --- writes ---

    async def put_metric(self, company: str, as_of: str, **fields):
        cols = {k: fields.get(k) for k in (*METRIC_FIELDS, "currency", "note",
                                           "source_thread", "source_subject")
                if fields.get(k) is not None}
        names = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{k}=excluded.{k}" for k in cols) or "as_of=excluded.as_of"
        await self._db.execute(
            f"""INSERT INTO company_metrics (company, as_of{', ' + names if cols else ''})
                VALUES (?, ?{', ' + marks if cols else ''})
                ON CONFLICT(company, as_of) DO UPDATE SET {updates}""",
            (company, as_of, *cols.values()),
        )
        await self._db.commit()

    async def put_event(self, company: str, occurred_on: str, kind: str,
                        summary: str, source_thread: str = ""):
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind: {kind!r}")
        await self._db.execute(
            """INSERT INTO company_events (company, occurred_on, kind, summary, source_thread)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(company, occurred_on, kind) DO UPDATE SET
                   summary=excluded.summary, source_thread=excluded.source_thread""",
            (company, occurred_on, kind, summary, source_thread),
        )
        await self._db.commit()

    async def put_ask(self, company: str, asked_on: str, ask: str,
                      source_thread: str = ""):
        await self._db.execute(
            """INSERT INTO company_asks (company, asked_on, ask, source_thread)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(company, asked_on) DO UPDATE SET
                   ask=excluded.ask, source_thread=excluded.source_thread""",
            (company, asked_on, ask, source_thread),
        )
        await self._db.commit()

    async def set_ask_answered(self, company: str, asked_on: str, answered: bool):
        await self._db.execute(
            "UPDATE company_asks SET answered=? WHERE company=? AND asked_on=?",
            (1 if answered else 0, company, asked_on),
        )
        await self._db.commit()

    # --- reads ---

    async def metrics(self) -> dict[str, list[dict]]:
        """Every metric row, grouped by company, oldest first."""
        out: dict[str, list[dict]] = {}
        async with self._db.execute(
            "SELECT * FROM company_metrics ORDER BY company, as_of"
        ) as cur:
            for r in await cur.fetchall():
                out.setdefault(r["company"], []).append(dict(r))
        return out

    async def events(self) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM company_events ORDER BY occurred_on DESC"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def asks(self) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM company_asks ORDER BY asked_on DESC"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _headline(row: dict) -> tuple[str, float] | None:
    """The one number that best represents a company's scale, and its kind.

    ARR where given; otherwise MRR or a monthly revenue figure annualised, so a
    single series never silently mixes monthly and annual magnitudes.
    """
    if row.get("arr"):
        return ("ARR", float(row["arr"]))
    if row.get("mrr"):
        return ("ARR", float(row["mrr"]) * 12)
    if row.get("revenue_month"):
        return ("ARR", float(row["revenue_month"]) * 12)
    return None


def trajectory(series: list[dict]) -> dict | None:
    """Direction of travel, measured against the peak rather than last month.

    Month-on-month is noisy — a company can post a good month on the way down.
    Distance from peak is what actually says whether something broke.
    """
    points = []
    for row in series:
        h = _headline(row)
        if h:
            points.append({"as_of": row["as_of"], "value": h[1],
                           "currency": row.get("currency") or "USD"})
    if not points:
        return None

    latest = points[-1]
    peak = max(points, key=lambda p: p["value"])
    first = points[0]

    def pct(a, b):
        return round(100 * (a - b) / b, 1) if b else None

    return {
        "points": points,
        "kind": "ARR",
        "latest": latest["value"],
        "currency": latest["currency"],
        "peak": peak["value"],
        "peak_as_of": peak["as_of"],
        "off_peak_pct": pct(latest["value"], peak["value"]),
        "since_first_pct": pct(latest["value"], first["value"]),
        "months": len(points),
        # Only meaningful with enough history to have a peak behind us.
        "past_peak": len(points) >= 3 and latest["value"] < peak["value"],
    }


def latest_metric(series: list[dict], field: str):
    for row in reversed(series):
        if row.get(field) is not None:
            return row[field], row["as_of"]
    return None, None


def triage(companies, rows: dict[str, dict], metrics: dict[str, list[dict]],
           events: list[dict], today: date | None = None) -> list[dict]:
    """Rank companies by how much attention they need, with the reasons shown.

    A score on its own is a black box nobody trusts. Each contribution carries
    the sentence that earned it, so the ranking argues its own case and can be
    disagreed with.
    """
    today = today or datetime.now(timezone.utc).date()
    by_company: dict[str, list[dict]] = {}
    for e in events:
        by_company.setdefault(e["company"], []).append(e)

    out = []
    for c in companies:
        row = rows.get(c.name, {})
        status = (row.get("status") or "unknown").lower()
        if status in ("dead", "exited", "acquired"):
            continue  # resolved; nothing left to watch

        score, reasons = 0, []

        # --- silence ---
        heard = row.get("last_heard_on")
        if heard:
            try:
                days = (today - date.fromisoformat(heard)).days
            except ValueError:
                days = None
            if days is not None and days >= 180:
                score += 25 if days >= 365 else 12
                reasons.append(f"no contact in {days // 30} months")

        # --- trajectory ---
        t = trajectory(metrics.get(c.name, []))
        if t and t["past_peak"] and t["off_peak_pct"] is not None:
            drop = abs(t["off_peak_pct"])
            if drop >= 10:
                score += min(40, int(drop))
                reasons.append(f"{drop:.0f}% below its {t['peak_as_of'][:7]} peak")

        # --- runway ---
        runway, as_of = latest_metric(metrics.get(c.name, []), "runway_months")
        if runway is not None and runway < RUNWAY_ALARM_MONTHS:
            score += int((RUNWAY_ALARM_MONTHS - runway) * 3)
            reasons.append(f"{runway:.0f} months runway as of {as_of[:7]}")

        # --- events ---
        for e in by_company.get(c.name, []):
            w = EVENT_KINDS.get(e["kind"], {}).get("weight", 0)
            if w:
                score += w
                reasons.append(f"{EVENT_KINDS[e['kind']]['label'].lower()}: {e['summary']}")

        if score > 0:
            out.append({
                "company": c.name,
                "score": score,
                "reasons": reasons,
                "amount": row.get("amount"),
                "trajectory": t,
            })

    out.sort(key=lambda x: -x["score"])
    return out


def summarise_signals(companies, metrics: dict[str, list[dict]],
                      events: list[dict], asks: list[dict]) -> dict:
    """Portfolio-level view of what the companies have reported."""
    known = {c.name for c in companies}
    traj = {name: trajectory(s) for name, s in metrics.items() if name in known}
    traj = {k: v for k, v in traj.items() if v}

    growing = [k for k, v in traj.items()
               if v["since_first_pct"] is not None and v["since_first_pct"] > 0
               and not v["past_peak"]]
    shrinking = [k for k, v in traj.items() if v["past_peak"]]

    runways = []
    for name, s in metrics.items():
        if name not in known:
            continue
        r, as_of = latest_metric(s, "runway_months")
        if r is not None:
            runways.append({"company": name, "months": r, "as_of": as_of})
    runways.sort(key=lambda x: x["months"])

    return {
        "with_metrics": len(traj),
        "growing": sorted(growing),
        "shrinking": sorted(shrinking),
        "runways": runways,
        "short_runway": [r for r in runways if r["months"] < RUNWAY_ALARM_MONTHS],
        "events": events[:40],
        "event_kinds": EVENT_KINDS,
        "open_asks": [a for a in asks if not a["answered"]],
        "asks_total": len(asks),
        "trajectories": traj,
    }
