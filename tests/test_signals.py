"""Tests for extracted metrics, events, asks and the triage ranking.

Extraction can be wrong, so the guards here are about provenance and about the
ranking arguing its own case rather than emitting an unexplained number.
"""

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

import content
from portfolio_signals import (
    EVENT_KINDS, SignalStore, latest_metric, summarise_signals, trajectory, triage,
)

ROOT = Path(__file__).resolve().parent.parent


def co(name, sector="SaaS", **kw):
    return content.Company(name=name, sector=sector, **kw)


@pytest_asyncio.fixture
async def sig(tmp_path):
    s = SignalStore(tmp_path / "sig.db")
    await s.open()
    yield s
    await s.close()


class TestStore:
    async def test_metric_round_trip_and_overwrite(self, sig):
        await sig.put_metric("Acme", "2026-01-01", arr=100, source_thread="t1")
        await sig.put_metric("Acme", "2026-01-01", arr=150, source_thread="t1")
        m = await sig.metrics()
        assert len(m["Acme"]) == 1, "same month must update, not duplicate"
        assert m["Acme"][0]["arr"] == 150

    async def test_metrics_come_back_oldest_first(self, sig):
        await sig.put_metric("Acme", "2026-03-01", arr=3)
        await sig.put_metric("Acme", "2026-01-01", arr=1)
        assert [r["as_of"] for r in (await sig.metrics())["Acme"]] == \
            ["2026-01-01", "2026-03-01"]

    async def test_unknown_event_kind_is_rejected(self, sig):
        with pytest.raises(ValueError):
            await sig.put_event("Acme", "2026-01-01", "vibes", "hmm")

    async def test_ask_can_be_marked_answered(self, sig):
        await sig.put_ask("Acme", "2026-01-01", "intros please")
        await sig.set_ask_answered("Acme", "2026-01-01", True)
        assert (await sig.asks())[0]["answered"] == 1


class TestTrajectory:
    def test_no_numbers_is_no_trajectory(self):
        assert trajectory([{"as_of": "2026-01-01", "headcount": 10}]) is None

    def test_mrr_is_annualised_so_a_series_never_mixes_scales(self):
        t = trajectory([{"as_of": "2026-01-01", "mrr": 1000, "currency": "USD"}])
        assert t["latest"] == 12000
        assert t["kind"] == "ARR"

    def test_arr_wins_over_mrr_when_both_given(self):
        t = trajectory([{"as_of": "2026-01-01", "arr": 50, "mrr": 1}])
        assert t["latest"] == 50

    def test_decline_is_measured_against_the_peak(self):
        t = trajectory([
            {"as_of": "2026-01-01", "arr": 100},
            {"as_of": "2026-02-01", "arr": 200},
            {"as_of": "2026-03-01", "arr": 150},
        ])
        assert t["past_peak"] is True
        assert t["off_peak_pct"] == -25.0
        assert t["peak_as_of"] == "2026-02-01"

    def test_two_points_are_not_enough_to_call_a_peak(self):
        """A single down month is noise, not a broken company."""
        t = trajectory([
            {"as_of": "2026-01-01", "arr": 200},
            {"as_of": "2026-02-01", "arr": 150},
        ])
        assert t["past_peak"] is False

    def test_latest_metric_skips_months_that_omit_the_field(self):
        v, as_of = latest_metric([
            {"as_of": "2026-01-01", "runway_months": 10},
            {"as_of": "2026-02-01", "runway_months": None},
        ], "runway_months")
        assert (v, as_of) == (10, "2026-01-01")


class TestTriage:
    TODAY = date(2026, 9, 20)

    def test_resolved_companies_are_not_ranked(self):
        for status in ("dead", "exited", "acquired"):
            out = triage([co("A")], {"A": {"status": status,
                                           "last_heard_on": "2020-01-01"}},
                         {}, [], today=self.TODAY)
            assert out == [], f"{status} should not need attention"

    def test_a_healthy_company_scores_nothing(self):
        out = triage([co("A")], {"A": {"last_heard_on": "2026-09-01"}},
                     {"A": [{"as_of": "2026-08-01", "arr": 100}]}, [], today=self.TODAY)
        assert out == []

    def test_every_score_carries_its_reasons(self):
        out = triage([co("A")], {"A": {"last_heard_on": "2025-01-01"}}, {}, [],
                     today=self.TODAY)
        assert out[0]["reasons"], "a score with no explanation is a black box"

    def test_decline_silence_and_runway_all_contribute(self):
        metrics = {"A": [
            {"as_of": "2026-01-01", "arr": 100},
            {"as_of": "2026-02-01", "arr": 200},
            {"as_of": "2026-03-01", "arr": 100, "runway_months": 4},
        ]}
        out = triage([co("A")], {"A": {"last_heard_on": "2025-06-01"}}, metrics, [],
                     today=self.TODAY)
        why = " ".join(out[0]["reasons"])
        assert "peak" in why and "runway" in why and "contact" in why

    def test_a_raise_offsets_concern(self):
        rows = {"A": {"last_heard_on": "2025-06-01"}, "B": {"last_heard_on": "2025-06-01"}}
        events = [{"company": "A", "kind": "raise", "summary": "Series A", "occurred_on": "2026-01-01"}]
        out = triage([co("A"), co("B")], rows, {}, events, today=self.TODAY)
        scores = {x["company"]: x["score"] for x in out}
        assert scores.get("A", 0) < scores["B"], "a raise should reduce concern"

    def test_ranked_worst_first(self):
        metrics = {"Bad": [
            {"as_of": "2026-01-01", "arr": 100}, {"as_of": "2026-02-01", "arr": 200},
            {"as_of": "2026-03-01", "arr": 60},
        ]}
        out = triage([co("Bad"), co("Mild")],
                     {"Bad": {}, "Mild": {"last_heard_on": "2026-02-01"}},
                     metrics, [], today=self.TODAY)
        assert out[0]["company"] == "Bad"
        assert out == sorted(out, key=lambda x: -x["score"])


class TestSummary:
    def test_growing_and_shrinking_are_separated(self):
        metrics = {
            "Up": [{"as_of": "2026-01-01", "arr": 100}, {"as_of": "2026-02-01", "arr": 200}],
            "Down": [{"as_of": "2026-01-01", "arr": 100},
                     {"as_of": "2026-02-01", "arr": 200},
                     {"as_of": "2026-03-01", "arr": 50}],
        }
        s = summarise_signals([co("Up"), co("Down")], metrics, [], [])
        assert s["growing"] == ["Up"] and s["shrinking"] == ["Down"]

    def test_short_runway_is_surfaced_separately(self):
        metrics = {"A": [{"as_of": "2026-01-01", "arr": 1, "runway_months": 5}],
                   "B": [{"as_of": "2026-01-01", "arr": 1, "runway_months": 40}]}
        s = summarise_signals([co("A"), co("B")], metrics, [], [])
        assert [r["company"] for r in s["short_runway"]] == ["A"]

    def test_only_open_asks_are_listed(self):
        asks = [{"company": "A", "ask": "x", "answered": 0, "asked_on": "2026-01-01"},
                {"company": "B", "ask": "y", "answered": 1, "asked_on": "2026-01-01"}]
        s = summarise_signals([co("A"), co("B")], {}, [], asks)
        assert [a["company"] for a in s["open_asks"]] == ["A"]
        assert s["asks_total"] == 2

    def test_metrics_for_unknown_companies_are_ignored(self):
        s = summarise_signals([co("A")], {"Ghost": [{"as_of": "2026-01-01", "arr": 1}]}, [], [])
        assert s["with_metrics"] == 0


class TestExtractedFile:
    """The shipped extraction must stay valid against the real portfolio."""

    def _data(self):
        return json.loads((ROOT / "scripts" / "signals_2026_09_20.json").read_text())

    def test_it_reconciles(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import import_signals

        assert import_signals.check(self._data()) == []

    def test_every_number_cites_a_source(self):
        """Provenance is the only defence against a hallucinated figure."""
        for m in self._data()["metrics"]:
            assert m.get("source_thread"), f"{m['company']} {m['as_of']} has no source"

    def test_every_event_kind_is_known(self):
        for e in self._data()["events"]:
            assert e["kind"] in EVENT_KINDS

    def test_the_aisdr_decline_is_represented(self):
        """A regression guard on the portfolio's clearest signal."""
        rows = [m for m in self._data()["metrics"] if m["company"] == "AiSDR"]
        t = trajectory(sorted(rows, key=lambda r: r["as_of"]))
        assert t["past_peak"] and t["off_peak_pct"] < -30
