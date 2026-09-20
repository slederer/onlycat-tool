"""Tests for the portfolio tracker.

The analytics are the point of the feature, so they get the most attention
here: a wrong TVPI is worse than no TVPI, because it looks authoritative.
"""

import dataclasses
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


class TestImportScript:
    """The import table must stay in sync with content.py.

    Renaming a company on the site would otherwise orphan its tracking row
    silently — the row stays, keyed to a name nothing joins to any more.
    """

    def test_import_table_reconciles_with_the_site(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import import_portfolio

        assert import_portfolio.check() == []

    def test_every_row_has_a_date_and_amount(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import import_portfolio

        for name, amount, date, _ in import_portfolio.ROWS:
            assert amount > 0, name
            assert date and len(date) == 10, name

    def test_inferred_rows_are_marked_so_they_can_be_corrected(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import import_portfolio

        assert any(r[3] for r in import_portfolio.ROWS), "nothing flagged as inferred"
        assert "inferred" in import_portfolio.INFERRED_NOTE


class TestInferredDatesStayPrivate:
    """A guessed date drives the private charts but must never be published."""

    def test_inferred_date_yields_no_public_year(self):
        out = public_overlay({"Acme": {"invested_on": "2026-03-01", "date_inferred": 1}})
        assert out["Acme"]["year"] is None

    def test_given_date_still_yields_a_year(self):
        out = public_overlay({"Acme": {"invested_on": "2026-03-01", "date_inferred": 0}})
        assert out["Acme"]["year"] == 2026

    def test_missing_flag_is_treated_as_given(self):
        """Rows written before the column existed are Stefan's own data."""
        out = public_overlay({"Acme": {"invested_on": "2021-05-01"}})
        assert out["Acme"]["year"] == 2021

    async def test_flag_persists_and_is_coerced_to_an_int(self, store):
        await store.upsert("Acme", {"invested_on": "2025-01-01", "date_inferred": "1"})
        assert (await store.get("Acme"))["date_inferred"] == 1
        await store.upsert("Acme", {"date_inferred": 0})
        assert (await store.get("Acme"))["date_inferred"] == 0

    def test_summary_counts_placeholder_dates(self):
        s = summarise(
            [co("A"), co("B")],
            {"A": {"amount": 1, "date_inferred": 1}, "B": {"amount": 1}},
        )
        assert s["counts"]["inferred_dates"] == 1

    async def test_migration_adds_the_column_to_an_existing_table(self, tmp_path):
        """The production table predates this column."""
        import aiosqlite

        db = tmp_path / "old.db"
        async with aiosqlite.connect(db) as c:
            await c.execute(
                "CREATE TABLE investments (company TEXT PRIMARY KEY, amount REAL)")
            await c.execute("INSERT INTO investments VALUES ('Acme', 100)")
            await c.commit()

        s = PortfolioStore(db)
        await s.open()
        row = await s.get("Acme")
        await s.close()
        assert row["amount"] == 100, "migration must not lose existing data"
        assert "date_inferred" in row

    def test_import_marks_every_guessed_date(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import import_portfolio

        guessed = {r[0] for r in import_portfolio.ROWS if r[3]}
        assert "GuardAero" in guessed, "its 2026 was interpolated, not given"
        assert "Mistral" not in guessed, "Apr.26 was given"


class TestSilenceTracking:
    """Silence is the earliest warning an angel position gives."""

    async def test_last_heard_round_trips(self, store):
        await store.upsert("Acme", {
            "last_heard_on": "2026-01-15", "last_heard_from": "f@acme.com",
            "last_heard_subject": "Q4 update", "last_heard_thread": "abc123",
        })
        row = await store.get("Acme")
        assert row["last_heard_on"] == "2026-01-15"
        assert row["last_heard_thread"] == "abc123"

    def test_never_heard_is_separate_from_silent(self):
        """No match may mean an unsearched domain, not a quiet company."""
        s = summarise([co("A"), co("B")], {"A": {"last_heard_on": "2026-09-01"}})
        assert s["never_heard"] == ["B"]
        assert s["silence_buckets"]["never"] == 1

    def test_silence_is_bucketed_not_averaged(self):
        today = datetime.now(timezone.utc).date()

        def ago(days):
            return (today - timedelta(days=days)).isoformat()

        s = summarise(
            [co("Fresh"), co("Slipping"), co("Worrying"), co("Gone")],
            {"Fresh": {"last_heard_on": ago(10)},
             "Slipping": {"last_heard_on": ago(120)},
             "Worrying": {"last_heard_on": ago(250)},
             "Gone": {"last_heard_on": ago(500)}},
        )
        b = s["silence_buckets"]
        assert (b["under_3m"], b["3_to_6m"], b["6_to_12m"], b["over_12m"]) == (1, 1, 1, 1)

    def test_silence_is_sorted_quietest_first(self):
        today = datetime.now(timezone.utc).date()
        s = summarise(
            [co("A"), co("B")],
            {"A": {"last_heard_on": (today - timedelta(days=10)).isoformat()},
             "B": {"last_heard_on": (today - timedelta(days=300)).isoformat()}},
        )
        assert [x["company"] for x in s["silence"]] == ["B", "A"]

    def test_bad_last_heard_date_counts_as_never_not_a_crash(self):
        s = summarise([co("A")], {"A": {"last_heard_on": "sometime"}})
        assert s["never_heard"] == ["A"]

    def test_contact_dates_never_reach_the_public_page(self):
        out = public_overlay({"Acme": {
            "last_heard_on": "2026-09-01", "last_heard_from": "f@acme.com",
            "last_heard_subject": "Q3", "status": "active",
        }})
        assert set(out["Acme"]) == {"status", "stage", "year"}


class TestGmailScanFile:
    def test_scan_reconciles_with_the_site(self):
        import json

        root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root / "scripts"))
        import import_gmail_scan

        scan = json.loads((root / "scripts" / "gmail_scan_2026_09_20.json").read_text())
        assert import_gmail_scan.check(scan) == []

    def test_scan_is_a_subset_not_a_claim_about_everyone(self):
        """A company missing from the scan must not be written as 'silent'."""
        import json

        root = Path(__file__).resolve().parent.parent
        scan = json.loads((root / "scripts" / "gmail_scan_2026_09_20.json").read_text())
        known = {c.name for c in (*content.PORTFOLIO, content.BITMOVIN)}
        assert set(scan["companies"]) < known, "scan should cover only what matched"
