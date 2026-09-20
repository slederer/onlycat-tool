"""Tests for the portfolio tracker.

The analytics are the point of the feature, so they get the most attention
here: a wrong TVPI is worse than no TVPI, because it looks authoritative.
"""

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

import content
import portfolio_store
from portfolio_store import PortfolioStore, public_overlay, summarise


def co(name, sector="SaaS", **kw):
    return content.Company(name=name, sector=sector, **kw)


@pytest_asyncio.fixture
async def store(tmp_path):
    s = PortfolioStore(tmp_path / "t.db")
    await s.open()
    yield s
    await s.close()


class TestStore:
    async def test_roundtrip(self, store):
        await store.upsert("Acme", {"amount": 25000, "status": "active"})
        row = await store.get("Acme")
        assert row["amount"] == 25000
        assert row["status"] == "active"
        assert row["updated_at"]

    async def test_upsert_merges_rather_than_replaces(self, store):
        await store.upsert("Acme", {"amount": 25000, "notes": "first"})
        await store.upsert("Acme", {"status": "exited"})
        row = await store.get("Acme")
        assert row["amount"] == 25000, "a partial save must not wipe other fields"
        assert row["notes"] == "first"
        assert row["status"] == "exited"

    async def test_unknown_keys_are_ignored(self, store):
        await store.upsert("Acme", {"amount": 1, "company": "Evil", "bogus": 2})
        assert await store.get("Evil") is None

    async def test_bad_status_is_rejected(self, store):
        with pytest.raises(ValueError):
            await store.upsert("Acme", {"status": "zombie"})

    async def test_blank_numbers_are_null_not_zero(self, store):
        """"Not recorded" and "worth nothing" are different facts."""
        await store.upsert("Acme", {"amount": "", "current_value": None})
        row = await store.get("Acme")
        assert row["amount"] is None
        assert row["current_value"] is None

    async def test_delete_clears_the_row(self, store):
        await store.upsert("Acme", {"amount": 1})
        await store.delete("Acme")
        assert await store.get("Acme") is None


class TestPublicOverlay:
    def test_money_never_crosses_over(self):
        out = public_overlay({"Acme": {
            "amount": 50000, "entry_valuation": 1e7, "current_value": 2e7,
            "realized": 1e6, "notes": "secret", "status": "active",
            "invested_on": "2024-03-01", "round_stage": "Seed",
        }})
        leaked = {"amount", "entry_valuation", "current_value", "realized", "notes"}
        assert not leaked & set(out["Acme"]), "a private field reached the public overlay"
        assert set(out["Acme"]) == {"status", "stage", "year"}

    def test_year_comes_from_the_investment_date(self):
        out = public_overlay({"Acme": {"invested_on": "2021-07-09"}})
        assert out["Acme"]["year"] == 2021

    def test_missing_date_is_not_a_year(self):
        out = public_overlay({"Acme": {"invested_on": None}})
        assert out["Acme"]["year"] is None

    def test_garbage_date_does_not_raise(self):
        out = public_overlay({"Acme": {"invested_on": "soon"}})
        assert out["Acme"]["year"] is None


class TestSummarise:
    def test_empty_portfolio_is_not_a_crash(self):
        s = summarise([], {})
        assert s["money"]["tvpi"] is None
        assert s["counts"]["total"] == 0

    def test_untracked_companies_count_as_unknown(self):
        s = summarise([co("A"), co("B")], {})
        assert s["status_mix"]["unknown"] == 2
        assert s["counts"]["untracked"] == 2

    def test_tvpi_uses_marks_and_realized(self):
        s = summarise(
            [co("A"), co("B")],
            {"A": {"amount": 100, "current_value": 300},
             "B": {"amount": 100, "current_value": 100, "realized": 50}},
        )
        # (300 + 100 + 50) / 200
        assert s["money"]["tvpi"] == 2.25
        assert s["money"]["dpi"] == 0.25

    def test_unmarked_positions_are_held_at_cost_not_marked_up(self):
        s = summarise([co("A")], {"A": {"amount": 100}})
        assert s["money"]["value"] == 100
        assert s["money"]["tvpi"] == 1.0
        assert s["money"]["marked_pct"] == 0.0, "cost is not a mark"

    def test_dead_companies_are_worth_zero_whatever_is_typed(self):
        s = summarise([co("A")], {"A": {"amount": 100, "current_value": 999, "status": "dead"}})
        assert s["money"]["value"] == 0

    def test_positions_without_a_cheque_are_excluded_from_money(self):
        s = summarise([co("A"), co("B")], {"A": {"amount": 100}, "B": {"status": "active"}})
        assert s["counts"]["with_amount"] == 1
        assert s["money"]["cost"] == 100

    def test_coverage_is_reported_so_thin_data_is_visible(self):
        s = summarise([co(n) for n in "ABCD"], {"A": {"amount": 100}})
        assert s["coverage"]["amount_pct"] == 25.0

    def test_sector_exposure_is_weighted_by_money_not_headcount(self):
        s = summarise(
            [co("A", "AI"), co("B", "AI"), co("C", "Energy")],
            {"A": {"amount": 10}, "B": {"amount": 10}, "C": {"amount": 80}},
        )
        top = s["sectors"][0]
        assert top["label"] == "Energy" and top["pct"] == 80.0

    def test_concentration_reports_the_top_five(self):
        rows = {c: {"amount": v} for c, v in
                zip("ABCDEFG", [100, 90, 80, 70, 60, 5, 5])}
        s = summarise([co(c) for c in "ABCDEFG"], rows)
        assert s["concentration"]["top5"][0]["company"] == "A"
        assert s["concentration"]["top5_pct"] == 97.6

    def test_vintages_group_by_year(self):
        s = summarise(
            [co("A"), co("B")],
            {"A": {"amount": 10, "invested_on": "2023-01-01"},
             "B": {"amount": 30, "invested_on": "2023-09-01"}},
        )
        assert s["vintages"] == [{"label": "2023", "cost": 40.0, "pct": 100.0}]

    def test_stale_positions_are_flagged(self):
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        fresh = datetime.now(timezone.utc).isoformat()
        s = summarise(
            [co("Old"), co("New")],
            {"Old": {"amount": 1, "updated_at": old},
             "New": {"amount": 1, "updated_at": fresh}},
        )
        assert [x["company"] for x in s["stale"]] == ["Old"]

    def test_unparseable_timestamp_does_not_raise(self):
        s = summarise([co("A")], {"A": {"amount": 1, "updated_at": "yesterday"}})
        assert s["stale"] == []


class TestAgainstRealContent:
    """The tracker must cover the actual site, not a toy list."""

    def test_every_company_can_be_summarised(self):
        companies = (*content.PORTFOLIO, content.BITMOVIN)
        s = summarise(companies, {})
        assert s["counts"]["total"] == len(companies)

    def test_editable_fields_all_exist_as_columns(self):
        # Guards against adding a field to EDITABLE and forgetting the schema.
        import sqlite3
        import tempfile
        import asyncio
        from pathlib import Path

        async def cols():
            with tempfile.TemporaryDirectory() as d:
                s = PortfolioStore(Path(d) / "x.db")
                await s.open()
                async with s._db.execute("PRAGMA table_info(investments)") as cur:
                    names = {r[1] for r in await cur.fetchall()}
                await s.close()
                return names

        names = asyncio.run(cols())
        assert set(portfolio_store.EDITABLE) <= names

    def test_statuses_stay_compatible_with_the_public_site(self):
        """public_overlay writes these straight onto content.Company.status."""
        extra = set(portfolio_store.STATUSES) - content.COMPANY_STATUSES - {"unknown"}
        assert not extra, f"status {extra} would render on the public page untested"

    def test_overlay_applies_cleanly_to_a_frozen_company(self):
        c = content.PORTFOLIO[0]
        o = public_overlay({c.name: {"status": "exited", "round_stage": "Seed",
                                     "invested_on": "2022-05-01"}})[c.name]
        updated = dataclasses.replace(c, status=o["status"], stage=o["stage"], year=o["year"])
        assert updated.status == "exited"
        assert updated.name == c.name
