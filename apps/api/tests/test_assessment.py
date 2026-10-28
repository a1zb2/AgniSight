"""Rules in app.services.assessment.

Run from apps/api:  python -m unittest discover -s tests
"""

import unittest
from datetime import date, datetime, timezone

from app.services.assessment import assess_event, location_pattern
from app.services.grid import cell_index, neighborhood
from app.services.thermal_registry import classify_site, summarize_cells


def history(**overrides):
    base = {
        "detection_count": 0, "active_days": 0, "active_months": 0,
        "active_years": 0, "calendar_months": 0, "first_seen": None,
        "last_seen": None, "night_share": None, "mean_frp": None,
        "max_frp": None, "nasa_typed_count": 0, "nasa_vegetation_share": None,
        "nasa_volcano_share": None, "nasa_static_share": None,
        "nasa_offshore_share": None,
    }
    base.update(overrides)
    return base


def prior(**overrides):
    base = {
        "active_days": 0, "active_months": 0, "calendar_months": 0,
        "detection_count": 0, "last_date": None, "frp_count": 0,
        "mean_frp": None,
    }
    base.update(overrides)
    return base


def event(**overrides):
    base = {
        "observation_count": 2, "max_frp_mw": 8.0, "day_night": "D",
        "high_confidence_count": 0, "start_date_label": "20 Oct 2026",
    }
    base.update(overrides)
    return base


def context(relation="none", group=None, relevance="medium",
            category="Industrial area", distance=0.0, name="Test works"):
    if relation == "none":
        return {"relation": "none", "primary": None}
    return {
        "relation": relation,
        "primary": {
            "group": group, "thermal_relevance": relevance,
            "category": category, "distance_m": distance, "name": name,
        },
    }


PERSISTENT_HISTORY = history(
    detection_count=900, active_days=400, active_months=30,
    calendar_months=12, night_share=0.8, mean_frp=6.0,
    nasa_typed_count=800, nasa_static_share=0.95,
)
PERSISTENT_PRIOR = prior(
    active_days=399, active_months=30, calendar_months=12,
    frp_count=890, mean_frp=6.0,
)


class LocationPatternTests(unittest.TestCase):
    def test_new_location(self):
        self.assertEqual(location_pattern(history(), prior(), None), "new")

    def test_year_round_night_activity_is_persistent(self):
        self.assertEqual(
            location_pattern(PERSISTENT_HISTORY, PERSISTENT_PRIOR, None),
            "persistent",
        )

    def test_repeated_burning_in_few_calendar_months_is_seasonal(self):
        h = history(calendar_months=3, active_months=7, night_share=0.1)
        p = prior(active_days=20, active_months=6, calendar_months=3)
        self.assertEqual(location_pattern(h, p, None), "seasonal")


class CategoryTests(unittest.TestCase):
    def test_persistent_source_inside_industry(self):
        a = assess_event(
            event(), PERSISTENT_HISTORY, PERSISTENT_PRIOR, None,
            context("inside", "heavy_industry", "high", "Industrial works"),
            None,
        )
        self.assertEqual(a["category"], "industrial_source")
        self.assertEqual(a["strength"]["level"], "strong")

    def test_new_activity_inside_industrial_area_is_an_anomaly(self):
        a = assess_event(
            event(day_night="N"), history(), prior(), None,
            context("inside", "industrial_area"), None,
        )
        self.assertEqual(a["category"], "industrial_anomaly")
        self.assertIn(a["priority"]["level"], ("review", "investigate"))

    def test_persistent_without_mapped_facility(self):
        a = assess_event(
            event(), PERSISTENT_HISTORY, PERSISTENT_PRIOR, None,
            context("none"), None,
        )
        self.assertEqual(a["category"], "unmapped_source")

    def test_new_daytime_detection_without_context_is_vegetation(self):
        a = assess_event(
            event(), history(), prior(), None, context("none"), None
        )
        self.assertEqual(a["category"], "vegetation_candidate")

    def test_nasa_offshore_label_wins(self):
        h = history(nasa_typed_count=40, nasa_offshore_share=0.9)
        a = assess_event(event(), h, prior(), None, context("none"), None)
        self.assertEqual(a["category"], "offshore_anomaly")

    def test_model_only_counts_where_nasa_label_missing(self):
        labelled = history(nasa_typed_count=50, nasa_vegetation_share=0.9)
        a = assess_event(
            event(), labelled, prior(), None, context("none"),
            {"static_probability": 0.95},
        )
        self.assertNotIn(
            "Static-source model", {e["source"] for e in a["evidence"]}
        )
        self.assertEqual(a["category"], "vegetation_candidate")

    def test_brick_kiln_context(self):
        a = assess_event(
            event(), history(), prior(), None,
            context("adjacent", "brick_kiln", "high", "Brick kiln", 200.0),
            None,
        )
        self.assertEqual(a["category"], "kiln_activity")


class PriorityTests(unittest.TestCase):
    def test_routine_persistent_source_is_monitor(self):
        a = assess_event(
            event(max_frp_mw=7.0), PERSISTENT_HISTORY, PERSISTENT_PRIOR,
            None, context("inside", "heavy_industry", "high"), None,
        )
        self.assertEqual(a["priority"]["level"], "monitor")

    def test_frp_far_above_baseline_raises_priority(self):
        a = assess_event(
            event(max_frp_mw=60.0), PERSISTENT_HISTORY, PERSISTENT_PRIOR,
            None, context("inside", "heavy_industry", "high"), None,
        )
        labels = " ".join(f["label"] for f in a["priority"]["factors"])
        self.assertIn("prior mean", labels)
        self.assertNotIn("established activity", labels)
        self.assertGreaterEqual(a["priority"]["score"], 25)

    def test_score_is_bounded(self):
        a = assess_event(
            event(max_frp_mw=500.0, observation_count=40,
                  high_confidence_count=3),
            history(), prior(), None, context("inside", "industrial_area"),
            None,
        )
        self.assertLessEqual(a["priority"]["score"], 100)


class RegistryTests(unittest.TestCase):
    def test_cell_index_matches_floor_division(self):
        # Must equal PostgreSQL agni_cell(): floor(value / 0.004).
        self.assertEqual(cell_index(22.79), 5697)
        self.assertEqual(cell_index(-0.001), -1)
        self.assertEqual(len(neighborhood((0, 0))), 9)

    def test_summarize_cells_unions_dates(self):
        cell = {
            "detection_count": 2, "night_count": 1,
            "high_confidence_count": 0, "frp_count": 2, "frp_sum": 10.0,
            "frp_max": 7.0, "typed_count": 2, "type0_count": 0,
            "type1_count": 0, "type2_count": 2, "type3_count": 0,
            "first_seen": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "last_seen": datetime(2024, 3, 1, tzinfo=timezone.utc),
        }
        a = {**cell, "active_dates": [date(2024, 1, 1), date(2024, 3, 1)]}
        b = {**cell, "active_dates": [date(2024, 3, 1), date(2025, 3, 2)]}
        s = summarize_cells([a, b])
        self.assertEqual(s["active_days"], 3)
        self.assertEqual(s["active_months"], 3)
        self.assertEqual(s["calendar_months"], 2)
        self.assertEqual(s["nasa_static_share"], 1.0)
        self.assertEqual(s["mean_frp"], 5.0)

    def test_site_classes(self):
        self.assertEqual(classify_site({
            "nasa_static_share": None, "calendar_months": 10,
            "night_share": 0.7,
        }), "persistent")
        self.assertEqual(classify_site({
            "nasa_static_share": 0.1, "calendar_months": 4,
            "night_share": 0.1,
        }), "seasonal")
        self.assertEqual(classify_site({
            "nasa_static_share": 0.1, "calendar_months": 7,
            "night_share": 0.2,
        }), "recurrent")


if __name__ == "__main__":
    unittest.main()
