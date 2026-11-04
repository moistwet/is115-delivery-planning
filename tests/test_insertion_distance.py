"""Check cached directed insertion distances against complete trip sums."""

import itertools
import math
import unittest
from unittest.mock import patch

from solution.policies.greedy_insertion import _evaluate_route, _insertion_distance
from solution.policies._insertion_variants import _evaluate_route as evaluate_variant


class InsertionDistanceTests(unittest.TestCase):
    def setUp(self):
        self.parcels = {
            pid: {"delivery_location_id": pid, "delivery_window_start": 0,
                  "delivery_window_end": 1440}
            for pid in "ABC"
        }
        nodes = ["HUB", "A", "B", "C"]
        self.distances = {
            a: {b: (0.0 if a == b else float(7 * i + 3 * j + 1))
                for j, b in enumerate(nodes)}
            for i, a in enumerate(nodes)
        }
        self.context = {"travel_distance": self.distances,
                        "max_trip_distance_km": 320, "return_cutoff": 1080}

    def full_distance(self, route):
        locations = ["HUB"] + [self.parcels[p]["delivery_location_id"] for p in route] + ["HUB"]
        return math.fsum(self.distances[a][b] for a, b in zip(locations, locations[1:]))

    def test_empty_beginning_middle_and_end_match_full_directed_trip(self):
        for length in range(3):
            for route_tuple in itertools.permutations("AB", length):
                route = list(route_tuple)
                for position in range(len(route) + 1):
                    with self.subTest(route=route, position=position):
                        candidate = route[:position] + ["C"] + route[position:]
                        distance = _insertion_distance(
                            route, "C", position, self.parcels, self.distances,
                            self.full_distance(route),
                        )
                        self.assertEqual(distance, self.full_distance(candidate))

    def test_shared_destination_adds_zero_distance(self):
        self.parcels["B"]["delivery_location_id"] = "A"
        for position in (0, 1):
            self.assertEqual(_insertion_distance(
                ["A"], "B", position, self.parcels, self.distances,
                self.full_distance(["A"])), self.full_distance(["A"]))

    def test_nonmetric_directed_edges_can_shorten_a_trip(self):
        self.distances["A"]["C"] = 100
        self.distances["A"]["B"] = 2
        self.distances["B"]["C"] = 3
        before = self.full_distance(["A", "C"])
        after = _insertion_distance(["A", "C"], "B", 1,
                                    self.parcels, self.distances, before)
        self.assertEqual(after, before - 95)
        self.assertEqual(after, self.full_distance(["A", "B", "C"]))

    def test_cached_evaluation_replays_window_status_and_inclusive_endpoints(self):
        route = ["A", "B", "C"]
        time = 630
        location = "HUB"
        for pid in route:
            time += self.distances[location][pid]
            self.parcels[pid]["delivery_window_start"] = time
            self.parcels[pid]["delivery_window_end"] = time
            location = pid
        distance = self.full_distance(route)
        for evaluator in (_evaluate_route, evaluate_variant):
            self.assertEqual(evaluator(route, self.parcels, self.context, 630),
                             evaluator(route, self.parcels, self.context, 630,
                                       total_distance=distance))
            self.assertEqual(evaluator(route, self.parcels, self.context, 630,
                                       total_distance=distance)[0], 6)

    def test_decimal_zero_cost_move_uses_the_canonical_sum(self):
        self.parcels["B"]["delivery_location_id"] = "A"
        self.distances["HUB"]["A"] = 0.1
        self.distances["A"]["C"] = 0.2
        self.distances["C"]["HUB"] = 0.3
        before = self.full_distance(["A", "C"])
        after = _insertion_distance(["A", "C"], "B", 1, self.parcels,
                                    self.distances, before)
        self.assertEqual(after, self.full_distance(["A", "B", "C"]))
        self.assertEqual(after - before, 0)

    def test_decimal_constraint_boundary_uses_full_sum_not_rounded_delta(self):
        self.distances["HUB"]["A"] = 0.1
        self.distances["A"]["C"] = 0.2
        self.distances["C"]["HUB"] = 0.3
        self.distances["A"]["B"] = 0.4
        self.distances["B"]["C"] = 0.5
        exact = self.full_distance(["A", "B", "C"])
        actual = _insertion_distance(["A", "C"], "B", 1, self.parcels,
                                     self.distances, self.full_distance(["A", "C"]),
                                     distance_limit=exact)
        self.assertEqual(actual, exact)

    def test_cached_evaluation_does_not_sum_the_route_again(self):
        for evaluator in (_evaluate_route, evaluate_variant):
            with patch("math.fsum", side_effect=AssertionError("unexpected full sum")):
                result = evaluator(["A", "B"], self.parcels, self.context, 630,
                                   total_distance=60)
            self.assertEqual(result[:2], (4, 60))

    def test_cached_distance_still_enforces_range_and_return_cutoff(self):
        for evaluator in (_evaluate_route, evaluate_variant):
            context = dict(self.context, max_trip_distance_km=60, return_cutoff=690)
            self.assertIsNotNone(evaluator(["A"], self.parcels, context, 630,
                                           total_distance=60))
            for changes in ({"max_trip_distance_km": 59}, {"return_cutoff": 689}):
                with self.subTest(evaluator=evaluator.__module__, changes=changes):
                    self.assertIsNone(evaluator(["A"], self.parcels,
                                                dict(context, **changes), 630,
                                                total_distance=60))


if __name__ == "__main__":
    unittest.main()
