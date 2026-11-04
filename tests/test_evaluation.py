"""Hand-computed aggregation, exact ranking, and fixed-matrix coverage checks."""

import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

from solution.evaluation import (
    DAYS, DETERMINISTIC_POLICIES, POLICIES, SEEDS, _paired_daily,
    aggregate_daily, aggregate_seeds, build_comparison, rank_policies, write_reports,
)


def _metrics(total, delivered, on_time, *, early=0, trips=None, distance=10.0):
    return {
        "total_parcels": total,
        "delivered_parcels": delivered,
        "on_time_parcels": on_time,
        "early_parcels": early,
        "late_parcels": delivered - on_time - early,
        "undelivered_parcels": total - delivered,
        "number_of_trips": (1 if delivered else 0) if trips is None else trips,
        "total_distance_km": distance if delivered else 0.0,
    }


def _single(total, delivered, on_time, *, distance=10.0):
    return aggregate_daily({"d": _metrics(total, delivered, on_time, distance=distance)},
                           {"d": float(min(delivered, 30))}, 30.0)


def _varying_seeds():
    daily = {
        seed: {"large": _metrics(90, 0, 0), "small": _metrics(10, 2 * seed, 2 * seed)}
        for seed in SEEDS
    }
    loads = {seed: {"large": 0.0, "small": float(2 * seed)} for seed in SEEDS}
    return daily, loads


class EvaluationTests(unittest.TestCase):
    def test_pooled_score_weights_parcels_instead_of_days(self):
        result = aggregate_daily({
            "large": _metrics(100, 80, 60, early=10, trips=4),
            "small": _metrics(10, 10, 10),
        }, {"large": 80.0, "small": 10.0}, 30)
        point = result["aggregate"]
        self.assertEqual(point["total_parcels"], 110)
        self.assertEqual(point["credit_units"], 160)
        self.assertAlmostEqual(point["score_b"], 8000 / 110)
        self.assertEqual(result["exact_scores"]["score_b"], {"numerator": 800, "denominator": 11})
        self.assertEqual(result["daily_summary"]["mean_daily_score_b"], 85)
        self.assertEqual(result["daily_summary"]["minimum_daily_score_b"], 70)
        self.assertEqual(result["daily_summary"]["worst_days"], ["large"])
        self.assertNotEqual(point["score_b"], 85)

    def test_load_utilisation_is_weighted_by_trip_count(self):
        result = aggregate_daily({
            "one_trip": _metrics(1, 1, 1, trips=1),
            "nine_trips": _metrics(9, 9, 9, trips=9),
        }, {"one_trip": 30.0, "nine_trips": 135.0}, 30)
        # Daily utilisations are 100% and 50%; their plain mean 75% is wrong.
        self.assertEqual(result["aggregate"]["total_departure_load"], 165)
        self.assertEqual(result["aggregate"]["average_load_utilisation_pct"], 55)
        self.assertEqual(result["aggregate"]["number_of_trips"], 10)
        self.assertEqual(result["aggregate"]["total_distance_km"], 20)

    def test_inconsistent_counts_and_zero_input_denominators_are_rejected(self):
        bad = _metrics(10, 5, 3)
        bad["late_parcels"] = 1
        for metrics in (bad, _metrics(0, 0, 0)):
            with self.subTest(metrics=metrics), self.assertRaises(ValueError):
                aggregate_daily({"d": metrics}, {"d": 0.0}, 30)

    def test_saved_score_inconsistent_with_counts_is_rejected(self):
        metrics = _metrics(10, 5, 3)
        metrics["score_b"] = 99.0
        with self.assertRaises(ValueError):
            aggregate_daily({"d": metrics}, {"d": 5.0}, 30)

    def test_exact_b_ties_are_co_ranked_without_a_distance_tiebreak(self):
        policies = {
            "high": _single(3, 3, 2),
            "long_tie": _single(3, 3, 1, distance=100),
            "short_tie": _single(6, 6, 2, distance=1),
            "low": _single(3, 1, 0),
        }
        groups = rank_policies(policies)
        self.assertEqual([row["rank"] for row in groups], [1, 2, 4])
        self.assertEqual(groups[1]["policies"], ["long_tie", "short_tie"])
        self.assertEqual(groups[1]["exact_score"], {"numerator": 200, "denominator": 3})

    def test_display_rounding_does_not_create_a_false_tie(self):
        policies = {"better": _single(1_000_000, 1_000_000, 1),
                    "worse": _single(1_000_000, 1_000_000, 0)}
        self.assertEqual(round(policies["better"]["aggregate"]["score_b"], 2),
                         round(policies["worse"]["aggregate"]["score_b"], 2))
        self.assertEqual([row["policies"] for row in rank_policies(policies)],
                         [["better"], ["worse"]])

    def test_a_uses_completion_first_and_on_time_only_on_exact_completion_ties(self):
        policies = {"completion": _single(10, 9, 0),
                    "timely": _single(10, 8, 8, distance=100),
                    "less_timely": _single(10, 8, 7, distance=1)}
        self.assertEqual([row["policies"] for row in rank_policies(policies, "score_a")],
                         [["completion"], ["timely"], ["less_timely"]])
        self.assertEqual(rank_policies(policies, "score_b")[0]["policies"], ["timely"])

    def test_sa_pools_each_seed_before_averaging_and_never_multiplies_inputs(self):
        daily, loads = _varying_seeds()
        result = aggregate_seeds(daily, loads, 30)
        point = result["aggregate"]
        # Seed pooled B values are 0,2,4,6,8. Pooling after seed averaging is
        # equivalent here, but averaging daily percentages would instead give 20.
        self.assertEqual(point["total_parcels"], 100)
        self.assertEqual(point["delivered_parcels"], 4)
        self.assertEqual(point["on_time_parcels"], 4)
        self.assertEqual(point["score_b"], 4)
        self.assertEqual(result["daily_summary"]["mean_daily_score_b"], 20)
        summary = result["seed_summary"]["score_b"]
        self.assertEqual((summary["mean"], summary["min"], summary["max"]), (4, 0, 8))
        self.assertAlmostEqual(summary["sample_sd"], math.sqrt(10))
        self.assertEqual(summary["observations"], 5)
        self.assertEqual(result["seed_aggregates"]["4"]["score_b"], 8)
        self.assertEqual(result["seed_aggregates"]["4"]["daily_scores_b"],
                         {"large": 0, "small": 80})

    def test_sa_a_ranking_uses_expected_counts_rather_than_best_seed(self):
        delivered = (1, 1, 1, 1, 2)
        daily = {seed: {"d": _metrics(3, delivered[seed], 0)} for seed in SEEDS}
        loads = {seed: {"d": float(delivered[seed])} for seed in SEEDS}
        sa = aggregate_seeds(daily, loads, 30)
        control = _single(3, 1, 1)
        self.assertAlmostEqual(sa["aggregate"]["delivered_parcels"], 1.2)
        self.assertEqual(sa["aggregate"]["completion_rate_pct"], 40)
        self.assertEqual(rank_policies({"sa": sa, "control": control}, "score_a")[0]["policies"], ["sa"])
        self.assertEqual(sa["aggregate"]["score_b"], 20)

    def test_sa_requires_five_matching_seed_day_sets_and_denominators(self):
        daily, loads = _varying_seeds()
        with self.assertRaises(ValueError):
            aggregate_seeds({seed: daily[seed] for seed in range(4)}, loads, 30)
        daily[4] = {"different": _metrics(10, 8, 8)}
        loads[4] = {"different": 8.0}
        with self.assertRaises(ValueError):
            aggregate_seeds(daily, loads, 30)
        daily, loads = _varying_seeds()
        daily[4]["small"] = _metrics(11, 8, 8)
        with self.assertRaises(ValueError):
            aggregate_seeds(daily, loads, 30)

    def test_daily_sa_outcome_compares_expected_score_not_seed_win_count(self):
        daily = {seed: {"d": _metrics(10, 2 * seed, 2 * seed)} for seed in SEEDS}
        loads = {seed: {"d": float(2 * seed)} for seed in SEEDS}
        sa = aggregate_seeds(daily, loads, 30)
        control = _single(10, 4, 4)
        self.assertEqual(_paired_daily(sa, control)["score_b"], {"win": 0, "tie": 1, "loss": 0})

    def test_missing_matrix_is_rejected_before_reports_are_created(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "incomplete evaluation matrix"):
                build_comparison(root, root / "data")
            self.assertFalse((root / "comparison.json").exists())

    def test_complete_synthetic_matrix_has_three_scopes_and_labelled_seed_csv_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, results = root / "data", root / "results"
            (data / "demand").mkdir(parents=True)
            (data / "config.json").write_text(json.dumps({"capacity": 30}))
            metrics = _metrics(1, 1, 1, distance=20)
            events = [
                {"event_type": "parcel_arrival", "time": 480, "parcel_id": "P"},
                {"event_type": "vehicle_return", "time": 480, "vehicle_id": 1},
                *[{"event_type": "dispatch_planning", "time": time} for time in range(480, 1051, 10)],
                {"event_type": "hub_departure", "time": 510, "vehicle_id": 1, "trip_id": 1},
                {"event_type": "delivery", "time": 520, "vehicle_id": 1, "trip_id": 1, "parcel_id": "P"},
                {"event_type": "vehicle_return", "time": 530, "vehicle_id": 1},
            ]
            priorities = {"parcel_arrival": 0, "vehicle_return": 1, "dispatch_planning": 2,
                          "hub_departure": 3, "delivery": 4}
            events.sort(key=lambda event: (event["time"], priorities[event["event_type"]]))
            log = "".join(json.dumps(event) + "\n" for event in events)
            for day in DAYS:
                (data / "demand" / f"{day}.csv").write_text(
                    "parcel_id,arrival_time,delivery_location_id,size,delivery_window_start,delivery_window_end\n"
                    "P,08:00,A,2,08:40,09:40\n")
                for policy in POLICIES:
                    for seed in SEEDS if policy == "insertion_sa" else (None,):
                        path = results / policy / day
                        if seed is not None:
                            path = path / f"seed_{seed}"
                        path.mkdir(parents=True)
                        (path / "log.txt").write_text(log)
                        (path / "metrics.json").write_text(json.dumps(metrics))
                        if seed is not None:
                            (path / "settings.json").write_text(json.dumps({"day": day, "seed": seed, "fixed": True}))
                            (path / "planning_audit.jsonl").write_text("")
            report = build_comparison(results, data)
            for scope, count in (("all20", 20), ("development", 5), ("evaluation", 15)):
                block = report["scopes"][scope]
                self.assertEqual(block["total_parcels"], count)
                self.assertEqual(block["policies"]["insertion_sa"]["aggregate"]["total_parcels"], count)
                self.assertEqual(block["policies"]["insertion_sa"]["aggregate"]["score_b"], 100)
                self.assertEqual(block["rankings"]["score_b"][0]["rank"], 1)
                self.assertCountEqual(block["rankings"]["score_b"][0]["policies"], POLICIES)
            write_reports(report, results)
            saved = json.loads((results / "comparison.json").read_text())
            self.assertEqual(saved["schema_version"], 1)
            with (results / "summary.csv").open(newline="") as stream:
                summary = list(csv.DictReader(stream))
            self.assertEqual(len(summary), 21)
            sa_all = next(row for row in summary if row["scope"] == "all20" and row["policy"] == "insertion_sa")
            self.assertEqual(sa_all["total_parcels"], "20")
            self.assertEqual(sa_all["score_b_seed_sample_sd"], "0.0")
            with (results / "daily_scores.csv").open(newline="") as stream:
                daily_rows = list(csv.DictReader(stream))
            sa_day = [row for row in daily_rows if row["scope"] == "all20"
                      and row["policy"] == "insertion_sa" and row["day"] == "day_001"]
            self.assertEqual(len(sa_day), 6)
            self.assertEqual(sum(row["statistic"] == "seed_mean" for row in sa_day), 1)
            self.assertEqual({row["seed"] for row in sa_day if row["statistic"] == "seed"}, set(map(str, SEEDS)))


if __name__ == "__main__":
    unittest.main()
