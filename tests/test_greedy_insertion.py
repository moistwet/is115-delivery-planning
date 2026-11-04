"""Hand-calculated route choices for independent greedy insertion."""

import copy
import unittest

from solution.policies.greedy_insertion import dispatch


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


class GreedyInsertionTests(unittest.TestCase):
    def test_new_parcel_can_be_inserted_before_the_first_selected_parcel(self):
        parcels = {name: _parcel(name) for name in "AB"}
        context = _context("AB", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 4, ("B", "HUB"): 4,
            ("B", "A"): 1, ("A", "B"): 100,
        })
        # A is selected first (solo tour 2 vs 8 km). Adding B before A gives
        # 6 km; appending B gives 105 km. This is construction, not reordering a seed.
        self.assertEqual(dispatch(parcels, context), ["B", "A"])

    def test_new_parcel_can_be_inserted_into_the_middle(self):
        parcels = {name: _parcel(name) for name in "ABC"}
        context = _context("ABC", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 5, ("B", "HUB"): 5,
            ("HUB", "C"): 10, ("C", "HUB"): 10,
            ("A", "B"): 1, ("A", "C"): 1, ("C", "B"): 1,
        })
        # First A (2 km), then A-B (7 km), then A-C-B (8 km).
        self.assertEqual(dispatch(parcels, context), ["A", "C", "B"])

    def test_zero_net_gain_is_rejected_even_though_new_parcel_earns_credit(self):
        parcels = {"A": _parcel("A", 640, 640), "B": _parcel("B", 500, 600)}
        context = _context("AB", {
            ("HUB", "A"): 10, ("A", "HUB"): 10,
            ("HUB", "B"): 5, ("B", "HUB"): 100,
            ("B", "A"): 10, ("A", "B"): 10,
        }, max_trip_distance_km=50)
        # A alone is on time (reward 1). B-A is feasible but both are late:
        # reward 0.5 + 0.5 = 1, so gain is zero. A-B is out of range.
        self.assertEqual(dispatch(parcels, context), ["A"])

    def test_negative_net_gain_is_rejected_after_rescoring_existing_deliveries(self):
        parcels = {
            "A": _parcel("A", 631, 631),
            "C": _parcel("C", 632, 632),
            "B": _parcel("B", 500, 600),
        }
        context = _context("ABC", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "C"): 3, ("C", "HUB"): 1,
            ("A", "C"): 1, ("C", "A"): 1,
            ("HUB", "B"): 2, ("B", "HUB"): 100,
            ("B", "A"): 1,
        }, max_trip_distance_km=10)
        # A-C earns 2. The only feasible B insertion is B-A-C, where all
        # three are late: reward 1.5, a negative gain despite serving one more.
        self.assertEqual(dispatch(parcels, context), ["A", "C"])

    def test_net_gain_can_exceed_one_when_existing_early_deliveries_become_on_time(self):
        parcels = {
            "A": _parcel("A", 650, 700),
            "C": _parcel("C", 649, 700),
            "B": _parcel("B", 900, 1000),
        }
        context = _context("ABC", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "C"): 2, ("C", "HUB"): 2,
            ("C", "A"): 1, ("A", "C"): 10,
            ("HUB", "B"): 18, ("B", "HUB"): 20,
            ("B", "A"): 1, ("B", "C"): 1,
        })
        # A is first, then C-A: both early, total reward 1. Adding B at the
        # front reaches B/C/A at 648/649/650: reward 0.5+1+1 = 2.5, gain 1.5.
        self.assertEqual(dispatch(parcels, context), ["B", "C", "A"])

    def test_reward_gain_precedes_distance_and_is_not_reward_per_kilometre(self):
        parcels = {"near": _parcel("A", 800, 900), "far": _parcel("B", 730, 750)}
        context = _context("AB", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 100, ("B", "HUB"): 100,
        }, capacity=1)
        # Far earns 1 over 200 km; near earns 0.5 over 2 km. Reward is primary.
        self.assertEqual(dispatch(parcels, context), ["far"])

    def test_eta_counts_preparation_once_and_the_whole_route_prefix(self):
        parcels = {
            "A": _parcel("A", 640, 640),
            "B": _parcel("B", 655, 655),
            "C": _parcel("C", 500, 600),
        }
        context = _context("ABC", {
            ("HUB", "A"): 10, ("A", "HUB"): 10,
            ("HUB", "B"): 5, ("B", "HUB"): 10,
            ("HUB", "C"): 1, ("C", "HUB"): 1,
            ("A", "B"): 15, ("A", "C"): 1,
        }, capacity=2)
        # Depart 630, A at 640, B at 655. B's net gain 1 beats C's 0.5.
        # With a missing prefix, C would win the distance tie instead.
        self.assertEqual(dispatch(parcels, context), ["A", "B"])

    def test_windows_include_both_endpoints_and_do_not_wait_at_a_stop(self):
        context = _context("AB", {
            ("HUB", "A"): 5, ("A", "HUB"): 5,
            ("HUB", "B"): 1, ("B", "HUB"): 1,
        }, capacity=1)
        cases = {
            "window_start": ((635, 645), ["A"]),
            "window_end": ((625, 635), ["A"]),
            "one_minute_early": ((636, 645), ["B"]),
            "one_minute_late": ((625, 634), ["B"]),
        }
        for name, (window, expected) in cases.items():
            with self.subTest(case=name):
                parcels = {"A": _parcel("A", *window), "B": _parcel("B", 500, 600)}
                self.assertEqual(dispatch(parcels, context), expected)

    def test_hard_constraints_override_a_higher_reward(self):
        cases = {
            "capacity": (
                {"A": _parcel("A", size=31), "B": _parcel("B", 700, 800)},
                _context("AB", {("HUB", "A"): 1, ("HUB", "B"): 5}),
            ),
            "directed_return_range": (
                {"A": _parcel("A"), "B": _parcel("B", 700, 800)},
                _context("AB", {
                    ("HUB", "A"): 5, ("A", "HUB"): 20,
                    ("HUB", "B"): 10, ("B", "HUB"): 5,
                }, max_trip_distance_km=20),
            ),
            "preparation_and_exact_cutoff": (
                {"A": _parcel("A", 990, 1020), "B": _parcel("B", 1020, 1030)},
                _context("AB", {
                    ("HUB", "A"): 5, ("A", "HUB"): 90,
                    ("HUB", "B"): 20, ("B", "HUB"): 70,
                }, current_time=960),
            ),
        }
        for name, (parcels, context) in cases.items():
            with self.subTest(constraint=name):
                self.assertEqual(dispatch(parcels, context), ["B"])

    def test_capacity_remains_the_combined_departure_load(self):
        parcels = {
            "A": _parcel("A", 631, 631, size=20),
            "B": _parcel("B", size=15),
            "C": _parcel("C", 700, 800, size=10),
        }
        context = _context("ABC", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 2, ("B", "HUB"): 2,
            ("HUB", "C"): 3, ("C", "HUB"): 3,
            ("A", "C"): 2,
        })
        # B is on time but cannot join A (35 units); A-C fits exactly 30.
        self.assertEqual(dispatch(parcels, context), ["A", "C"])

    def test_equal_gain_and_added_distance_use_arrival_then_id(self):
        parcels = {
            "P001": _parcel("A", arrival=490),
            "P003": _parcel("B", arrival=480),
            "P002": _parcel("C", arrival=480),
        }
        context = _context("ABC", {
            ("HUB", location): 1 for location in "ABC"
        }, capacity=1)
        # All return legs have equal default length, so arrival and ID decide.
        self.assertEqual(dispatch(parcels, context), ["P002"])

    def test_equal_insertions_use_the_lowest_position(self):
        parcels = {"A": _parcel("A", arrival=480), "B": _parcel("B", arrival=490)}
        context = _context("AB", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 1, ("B", "HUB"): 1,
            ("A", "B"): 1, ("B", "A"): 1,
        })
        # A is chosen first. B-A and A-B have equal reward and distance;
        # insertion position 0 produces B-A.
        self.assertEqual(dispatch(parcels, context), ["B", "A"])

    def test_eligibility_and_input_immutability(self):
        parcels = {
            "assigned": _parcel("A", assigned=2),
            "delivered": _parcel("B", delivered=590),
            "waiting": _parcel("C", 700, 800),
        }
        context = _context("ABC", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 0, ("B", "HUB"): 0,
            ("HUB", "C"): 3, ("C", "HUB"): 3,
        })
        original_parcels = copy.deepcopy(parcels)
        original_context = copy.deepcopy(context)
        self.assertEqual(dispatch(parcels, context), ["waiting"])
        self.assertEqual(parcels, original_parcels)
        self.assertEqual(context, original_context)

    def test_zero_added_distance_for_shared_destination(self):
        parcels = {
            "P001": _parcel("A", 635, 635, arrival=480),
            "P002": _parcel("A", 635, 635, arrival=490),
        }
        context = _context("A", {("HUB", "A"): 5, ("A", "HUB"): 5})
        # Second parcel adds a point with no distance; equivalent positions tie at 0.
        self.assertEqual(dispatch(parcels, context), ["P002", "P001"])

    def test_empty_or_no_feasible_eligible_candidate_returns_empty(self):
        context = _context("A", {("HUB", "A"): 5, ("A", "HUB"): 5})
        cases = {
            "empty": {},
            "assigned": {"A": _parcel("A", assigned=1)},
            "too_large": {"A": _parcel("A", size=31)},
        }
        for name, parcels in cases.items():
            with self.subTest(case=name):
                self.assertEqual(dispatch(parcels, context), [])


if __name__ == "__main__":
    unittest.main()
