"""Controlled annealing decisions and seeded-run ownership, without simulations."""

import copy
import math
import random
import unittest
from unittest.mock import patch

from solution.policies.insertion_sa import (
    INITIAL_TEMPERATURE, make_dispatch, simulated_annealing,
)


def _parcel(location, start=0.0, end=1440.0, size=1.0, arrival=480.0,
            *, assigned=None, delivered=None):
    return {
        "arrival_time": arrival,
        "delivery_location_id": location,
        "delivery_window_start": start,
        "delivery_window_end": end,
        "size": size,
        "vehicle_assigned": assigned,
        "delivery_time": delivered,
        "trip_id": 1 if assigned is not None else None,
    }


def _context(locations, legs, **changes):
    nodes = ["HUB", *locations]
    matrix = {
        origin: {
            destination: 0.0 if origin == destination else 100.0
            for destination in nodes
        }
        for origin in nodes
    }
    for (origin, destination), value in legs.items():
        matrix[origin][destination] = float(value)
    context = {
        "current_time": 600.0,
        "vehicle_id": 1,
        "capacity": 30.0,
        "travel_distance": matrix,
        "departure_delay": 30.0,
        "return_cutoff": 1080.0,
        "max_trip_distance_km": 320.0,
        "fleet": {1: {"available_at": 600.0, "max_trip_distance_km": 320.0}},
    }
    context.update(changes)
    return context


class ScriptedRandom:
    """Supply swap pairs and downhill draws; unexpected draws fail the test."""

    def __init__(self, swaps=(), draws=()):
        self.swaps = iter(swaps)
        self.draws = iter(draws)
        self.sample_calls = 0
        self.random_calls = 0

    def sample(self, population, count):
        self.sample_calls += 1
        if count != 2:
            raise AssertionError("a proposal must swap exactly two positions")
        result = next(self.swaps)
        if len(set(result)) != 2 or not set(result).issubset(set(population)):
            raise AssertionError("invalid scripted swap")
        return list(result)

    def random(self):
        self.random_calls += 1
        return next(self.draws)


class InsertionSATests(unittest.TestCase):
    def test_initial_temperature_accepts_half_credit_loss_with_probability_point_three(self):
        self.assertAlmostEqual(math.exp(-0.5 / INITIAL_TEMPERATURE), 0.30)
        parcels = {"A": _parcel("A", 631, 631), "B": _parcel("B")}
        context = _context("AB", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 1, ("B", "HUB"): 1,
            ("A", "B"): 1, ("B", "A"): 1,
        })
        # Swapping makes A late: one doubled-credit unit = 0.5 raw credit lost.
        for draw, accepted in ((0.299, 1), (0.301, 0)):
            with self.subTest(draw=draw):
                audit = []
                rng = ScriptedRandom([(0, 1)], [draw])
                result = simulated_annealing(["A", "B"], parcels, context,
                                             rng=rng, iterations=1, audit=audit.append)
                self.assertEqual(result, ["A", "B"])
                self.assertEqual(len(audit), 1)
                self.assertEqual(audit[0]["accepted_worse"], accepted)
                self.assertEqual(audit[0]["last_current_credit_units"], 4 - accepted)
                self.assertEqual(rng.random_calls, 1)

    def test_equal_credit_longer_route_is_accepted_but_does_not_replace_the_best(self):
        parcels = {name: _parcel(name) for name in "AB"}
        context = _context("AB", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 1, ("B", "HUB"): 1,
            ("A", "B"): 1, ("B", "A"): 10,
        })
        audit = []
        rng = ScriptedRandom([(0, 1)])
        result = simulated_annealing(["A", "B"], parcels, context,
                                     rng=rng, iterations=1, audit=audit.append)
        self.assertEqual(result, ["A", "B"])
        self.assertEqual(audit[0]["accepted_equal"], 1)
        self.assertEqual(audit[0]["last_current_distance_km"], 12)
        self.assertEqual(audit[0]["best_distance_km"], 3)
        self.assertEqual(rng.random_calls, 0)

    def test_equal_credit_shorter_route_replaces_the_best(self):
        parcels = {name: _parcel(name) for name in "AB"}
        context = _context("AB", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 1, ("B", "HUB"): 1,
            ("A", "B"): 1, ("B", "A"): 10,
        })
        audit = []
        result = simulated_annealing(["B", "A"], parcels, context,
                                     rng=ScriptedRandom([(0, 1)]), iterations=1,
                                     audit=audit.append)
        self.assertEqual(result, ["A", "B"])
        self.assertEqual(audit[0]["initial_distance_km"], 12)
        self.assertEqual(audit[0]["best_distance_km"], 3)

    def test_better_credit_is_accepted_even_when_distance_increases(self):
        parcels = {"A": _parcel("A", 631, 631), "B": _parcel("B")}
        context = _context("AB", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 1, ("B", "HUB"): 1,
            ("A", "B"): 50, ("B", "A"): 1,
        })
        audit = []
        result = simulated_annealing(["B", "A"], parcels, context,
                                     rng=ScriptedRandom([(0, 1)]), iterations=1,
                                     audit=audit.append)
        self.assertEqual(result, ["A", "B"])
        self.assertEqual(audit[0]["accepted_better"], 1)
        self.assertEqual(audit[0]["best_credit_units"], 4)
        self.assertEqual(audit[0]["best_distance_km"], 52)

    def test_best_prefers_credit_over_a_large_distance_saving_after_downhill_acceptance(self):
        parcels = {"A": _parcel("A", 631, 631), "B": _parcel("B")}
        context = _context("AB", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 1, ("B", "HUB"): 159,
            ("A", "B"): 159, ("B", "A"): 1,
        })
        audit = []
        result = simulated_annealing(["A", "B"], parcels, context,
                                     rng=ScriptedRandom([(0, 1)], [0.0]), iterations=1,
                                     audit=audit.append)
        self.assertEqual(result, ["A", "B"])
        self.assertEqual(audit[0]["accepted_worse"], 1)
        self.assertEqual(audit[0]["best_distance_km"], 319)
        self.assertEqual(audit[0]["last_current_distance_km"], 3)
        self.assertEqual(audit[0]["best_credit_units"], 4)
        self.assertEqual(audit[0]["last_current_credit_units"], 3)

    def test_downhill_and_equal_moves_can_lead_to_a_new_best_without_corrupting_it(self):
        parcels = {name: _parcel(name) for name in "ABCD"}
        parcels["A"] = _parcel("A", 631, 631)
        context = _context("ABCD", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 1, ("B", "HUB"): 1,
            ("HUB", "C"): 1, ("C", "HUB"): 1,
            ("HUB", "D"): 1, ("D", "HUB"): 10,
            ("A", "B"): 1, ("B", "C"): 10, ("C", "D"): 10,
            ("B", "A"): 1, ("A", "C"): 1, ("A", "D"): 1,
            ("B", "D"): 1, ("D", "C"): 1,
        })
        audit = []
        rng = ScriptedRandom([(0, 1), (2, 3), (0, 1)], [0.0])
        result = simulated_annealing(list("ABCD"), parcels, context,
                                     rng=rng, iterations=3, audit=audit.append)
        self.assertEqual(result, list("ABDC"))
        self.assertEqual(audit[0]["initial_distance_km"], 32)
        self.assertEqual(audit[0]["best_distance_km"], 5)
        for field in ("accepted_better", "accepted_equal", "accepted_worse"):
            self.assertEqual(audit[0][field], 1)

    def test_infeasible_swaps_are_rejected_and_still_cool_once_per_attempt(self):
        parcels = {name: _parcel(name) for name in "AB"}
        legs = {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 1, ("B", "HUB"): 1,
            ("A", "B"): 1, ("B", "A"): 100,
        }
        contexts = {
            "directed_range": _context("AB", legs, max_trip_distance_km=10),
            "return_cutoff": _context("AB", legs, current_time=1020),
        }
        for name, context in contexts.items():
            with self.subTest(constraint=name):
                audit = []
                rng = ScriptedRandom([(0, 1), (0, 1)])
                result = simulated_annealing(["A", "B"], parcels, context,
                                             rng=rng, iterations=2, temperature=2,
                                             cooling_rate=0.5, audit=audit.append)
                self.assertEqual(result, ["A", "B"])
                self.assertEqual(audit[0]["attempts"], 2)
                self.assertEqual(audit[0]["infeasible_proposals"], 2)
                self.assertEqual(audit[0]["final_temperature"], 0.5)
                self.assertEqual(rng.random_calls, 0)

    def test_route_replay_counts_preparation_prefix_and_inclusive_endpoints(self):
        parcels = {"A": _parcel("A", 635, 635), "B": _parcel("B", 640, 640)}
        context = _context("AB", {
            ("HUB", "A"): 5, ("A", "HUB"): 5,
            ("HUB", "B"): 5, ("B", "HUB"): 5,
            ("A", "B"): 5, ("B", "A"): 5,
        })
        audit = []
        result = simulated_annealing(["A", "B"], parcels, context,
                                     rng=ScriptedRandom([(0, 1)], [0.99]), iterations=1,
                                     audit=audit.append)
        self.assertEqual(result, ["A", "B"])
        self.assertEqual(audit[0]["initial_credit_units"], 4)
        self.assertEqual(audit[0]["accepted_worse"], 0)

    def test_invalid_seed_membership_eligibility_and_full_load_are_rejected(self):
        context = _context("A", {("HUB", "A"): 1, ("A", "HUB"): 1})
        cases = {
            "duplicate": (["A", "A"], {"A": _parcel("A")}),
            "unknown": (["missing"], {"A": _parcel("A")}),
            "assigned": (["A"], {"A": _parcel("A", assigned=2)}),
            "delivered": (["A"], {"A": _parcel("A", delivered=590)}),
            "future": (["A"], {"A": _parcel("A", arrival=601)}),
            "capacity": (["A"], {"A": _parcel("A", size=31)}),
        }
        for name, (route, parcels) in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                simulated_annealing(route, parcels, context, rng=ScriptedRandom())

    def test_an_initial_route_must_already_satisfy_range_and_return_cutoff(self):
        parcels = {"A": _parcel("A")}
        legs = {("HUB", "A"): 5, ("A", "HUB"): 90}
        cases = {
            "range": _context("A", legs, max_trip_distance_km=90),
            "cutoff": _context("A", legs, current_time=960),
        }
        for name, context in cases.items():
            with self.subTest(constraint=name), self.assertRaises(ValueError):
                simulated_annealing(["A"], parcels, context, rng=ScriptedRandom())

    def test_empty_and_single_parcel_routes_do_not_draw_random_numbers(self):
        context = _context("A", {("HUB", "A"): 5, ("A", "HUB"): 5})
        for route, parcels in (([], {}), (["A"], {"A": _parcel("A")})):
            with self.subTest(route=route):
                audit = []
                rng = ScriptedRandom()
                self.assertEqual(simulated_annealing(route, parcels, context, rng=rng,
                                                     audit=audit.append), route)
                self.assertEqual(len(audit), 1)
                self.assertEqual(audit[0]["attempts"], 0)
                self.assertEqual(audit[0]["final_temperature"], INITIAL_TEMPERATURE)
                self.assertEqual(rng.sample_calls, 0)
                self.assertEqual(rng.random_calls, 0)

    def test_swaps_preserve_membership_and_leave_all_inputs_unchanged(self):
        parcels = {name: _parcel(name) for name in "ABCD"}
        context = _context("ABCD", {
            ("HUB", "A"): 1, ("HUB", "B"): 2, ("HUB", "C"): 3,
            ("A", "B"): 4, ("B", "A"): 5, ("C", "A"): 6,
        })
        route = list("ABC")
        original_parcels = copy.deepcopy(parcels)
        original_context = copy.deepcopy(context)
        audit = []
        result = simulated_annealing(route, parcels, context, rng=random.Random(5),
                                     iterations=30, audit=audit.append)
        self.assertCountEqual(result, route)
        self.assertEqual(len(result), 3)
        self.assertNotIn("D", result)
        self.assertEqual(route, list("ABC"))
        self.assertEqual(parcels, original_parcels)
        self.assertEqual(context, original_context)
        recorded_best = audit[0]["best_route"][:]
        result.append("D")
        self.assertEqual(audit[0]["best_route"], recorded_best)

    def test_factory_reuses_one_random_stream_and_reproduces_it_for_the_same_seed(self):
        parcels = {name: _parcel(name) for name in "AB"}
        context = _context("AB", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 2, ("B", "HUB"): 2,
            ("A", "B"): 1, ("B", "A"): 1,
        })
        states = []

        def inspect_stream(initial, parcel, context, *, rng, **kwargs):
            states.append(rng.getstate())
            rng.random()
            return list(initial)

        with patch("solution.policies.insertion_sa.simulated_annealing", side_effect=inspect_stream):
            first = make_dispatch(seed=17)
            first(parcels, context)
            first(parcels, context)
            repeat = make_dispatch(seed=17)
            repeat(parcels, context)
            repeat(parcels, context)
        self.assertNotEqual(states[0], states[1])
        self.assertEqual(states[0], states[2])
        self.assertEqual(states[1], states[3])

    def test_factory_calls_the_original_constructor_fresh_on_every_dispatch(self):
        parcels = {name: _parcel(name) for name in "AB"}
        context = _context("AB", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 1, ("B", "HUB"): 1,
        })
        audit = []
        with patch("solution.policies.insertion_sa.greedy_dispatch",
                   side_effect=[["A"], ["B"]]) as constructor:
            dispatch = make_dispatch(seed=3, audit=audit.append)
            self.assertEqual(dispatch(parcels, context), ["A"])
            self.assertEqual(dispatch(parcels, context), ["B"])
        self.assertEqual(constructor.call_count, 2)
        self.assertEqual([row["initial_route"] for row in audit], [["A"], ["B"]])
        self.assertTrue(all(row["planning_time"] == 600 for row in audit))
        self.assertTrue(all(row["vehicle_id"] == 1 for row in audit))

    def test_invalid_temperature_cooling_and_attempt_budget_are_rejected(self):
        context = _context("A", {})
        invalid = [
            {"temperature": value} for value in (0, -1, math.nan, math.inf)
        ] + [
            {"cooling_rate": value} for value in (0, 1, -0.1, 1.01, math.nan, math.inf)
        ] + [
            {"iterations": value} for value in (-1, 0.5, True)
        ]
        for changes in invalid:
            with self.subTest(parameters=changes), self.assertRaises(ValueError):
                simulated_annealing([], {}, context, rng=ScriptedRandom(), **changes)

    def test_zero_attempts_returns_the_feasible_seed_as_the_incumbent(self):
        parcels = {name: _parcel(name) for name in "AB"}
        context = _context("AB", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 1, ("B", "HUB"): 1,
            ("A", "B"): 1,
        })
        audit = []
        self.assertEqual(simulated_annealing(["A", "B"], parcels, context,
                                             rng=ScriptedRandom(), iterations=0,
                                             audit=audit.append), ["A", "B"])
        self.assertEqual(audit[0]["attempts"], 0)
        self.assertEqual(audit[0]["initial_credit_units"], audit[0]["best_credit_units"])
        self.assertEqual(audit[0]["initial_distance_km"], audit[0]["best_distance_km"])


if __name__ == "__main__":
    unittest.main()
