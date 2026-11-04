"""Hand-worked choices for window-first nearest feasible neighbour."""

import copy
import unittest

from solution.policies.window_first_nearest import dispatch


def _parcel(location, start=600.0, end=900.0, size=1.0, arrival=480.0,
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


class WindowFirstNearestTests(unittest.TestCase):
    def test_farther_in_window_candidate_beats_nearer_early_candidate(self):
        parcels = {
            "near": _parcel("A", start=700, end=800),
            "inside": _parcel("B", start=630, end=650),
        }
        context = _context("AB", {("HUB", "A"): 1, ("HUB", "B"): 10}, capacity=1)
        # Departure 10:30: A would be early at 10:31; B is in-window at 10:40.
        self.assertEqual(dispatch(parcels, context), ["inside"])

    def test_nearest_within_window_group_wins_over_earliest_deadline(self):
        parcels = {
            "near": _parcel("A", start=600, end=900),
            "urgent": _parcel("B", start=630, end=640),
        }
        context = _context("AB", {("HUB", "A"): 3, ("HUB", "B"): 8}, capacity=1)
        # Both ETAs are in-window; the nearer A wins despite B's earlier deadline.
        self.assertEqual(dispatch(parcels, context), ["near"])

    def test_early_and_late_candidates_share_the_same_nearest_fallback(self):
        context = _context("AB", {("HUB", "A"): 2, ("HUB", "B"): 5}, capacity=1)
        for near_is_early in (True, False):
            with self.subTest(near_is_early=near_is_early):
                early = (700, 800)
                late = (500, 600)
                near_window, far_window = (early, late) if near_is_early else (late, early)
                parcels = {
                    "near": _parcel("A", *near_window),
                    "far": _parcel("B", *far_window),
                }
                # Neither can be on time. Do not wait at the hub or prefer late over early.
                self.assertEqual(dispatch(parcels, context), ["near"])

    def test_eta_includes_preparation_once_and_the_complete_travel_prefix(self):
        parcels = {
            "A": _parcel("A", start=640, end=640),
            "B": _parcel("B", start=655, end=655),
            "C": _parcel("C", start=500, end=600),
        }
        context = _context("ABC", {
            ("HUB", "A"): 10,
            ("HUB", "B"): 5,
            ("HUB", "C"): 1,
            ("A", "B"): 15,
            ("A", "C"): 1,
        }, capacity=2)
        # Depart 630, reach A at 640, then B at 655. Omitting preparation or
        # prefix travel, or charging preparation twice, incorrectly makes B early/late.
        self.assertEqual(dispatch(parcels, context), ["A", "B"])

    def test_early_candidate_becomes_in_window_after_another_delivery(self):
        parcels = {
            "A": _parcel("A", start=630, end=650),
            "B": _parcel("B", start=640, end=650),
            "C": _parcel("C", start=630, end=636),
        }
        context = _context("ABC", {
            ("HUB", "A"): 5,
            ("HUB", "B"): 1,
            ("HUB", "C"): 6,
            ("A", "B"): 5,
            ("A", "C"): 3,
        }, capacity=2)
        # Initially B is early. After A at 635, B is in-window at 640 while
        # the closer C would now be late at 638. Both classifications must change.
        self.assertEqual(dispatch(parcels, context), ["A", "B"])

    def test_distance_is_recomputed_from_the_current_stop_within_each_group(self):
        parcels = {name: _parcel(name) for name in "ABC"}
        context = _context("ABC", {
            ("HUB", "A"): 4,
            ("HUB", "B"): 5,
            ("HUB", "C"): 6,
            ("A", "B"): 20,
            ("A", "C"): 1,
            ("C", "B"): 1,
        }, capacity=3)
        self.assertEqual(dispatch(parcels, context), ["A", "C", "B"])

    def test_window_endpoints_are_inclusive_without_waiting_at_stops(self):
        context = _context("AB", {("HUB", "A"): 5, ("HUB", "B"): 1}, capacity=1)
        cases = {
            "at_start": ((635, 645), ["A"]),
            "at_end": ((625, 635), ["A"]),
            "one_minute_late": ((625, 634), ["B"]),
            "one_minute_early": ((636, 645), ["B"]),
        }
        for name, (window, expected) in cases.items():
            with self.subTest(case=name):
                parcels = {"A": _parcel("A", *window), "B": _parcel("B", 500, 600)}
                self.assertEqual(dispatch(parcels, context), expected)

    def test_eligibility_and_arrival_id_tiebreaks_apply_within_the_same_group(self):
        parcels = {
            "P001": _parcel("A", arrival=490),
            "P003": _parcel("B", arrival=480),
            "P002": _parcel("C", arrival=480),
            "assigned": _parcel("D", assigned=2),
            "delivered": _parcel("E", delivered=590),
        }
        context = _context("ABCDE", {
            ("HUB", "A"): 5,
            ("HUB", "B"): 5,
            ("HUB", "C"): 5,
            ("HUB", "D"): 1,
            ("HUB", "E"): 0,
        }, capacity=1)
        self.assertEqual(dispatch(parcels, context), ["P002"])

    def test_hard_feasibility_overrides_window_priority(self):
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
            "cutoff_with_exact_boundary_fallback": (
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

    def test_capacity_is_the_full_departure_load_even_after_a_delivery(self):
        parcels = {
            "A": _parcel("A", start=631, end=631, size=20),
            "B": _parcel("B", size=15),
            "C": _parcel("C", start=700, end=800, size=10),
        }
        context = _context("ABC", {
            ("HUB", "A"): 1,
            ("HUB", "B"): 2,
            ("HUB", "C"): 3,
            ("A", "B"): 1,
            ("A", "C"): 2,
        })
        # B would be in-window, but 20 + 15 exceeds capacity. The early C fits.
        self.assertEqual(dispatch(parcels, context), ["A", "C"])

    def test_zero_distance_shared_destination_and_inputs_remain_unchanged(self):
        parcels = {
            "P001": _parcel("A", 635, 635, arrival=480),
            "P002": _parcel("A", 635, 635, arrival=490),
            "P003": _parcel("B", 630, 700, arrival=470),
        }
        context = _context("AB", {
            ("HUB", "A"): 5,
            ("HUB", "B"): 6,
            ("A", "B"): 5,
        })
        original_parcels = copy.deepcopy(parcels)
        original_context = copy.deepcopy(context)
        self.assertEqual(dispatch(parcels, context), ["P001", "P002", "P003"])
        self.assertEqual(parcels, original_parcels)
        self.assertEqual(context, original_context)

    def test_full_prefix_counts_in_range_and_cutoff_checks(self):
        parcels = {name: _parcel(name, 0, 1440) for name in "AB"}
        legs = {
            ("HUB", "A"): 10, ("A", "HUB"): 10,
            ("HUB", "B"): 15, ("B", "HUB"): 10,
            ("A", "B"): 15,
        }
        cases = {
            "range": _context("AB", legs, max_trip_distance_km=30),
            "cutoff": _context("AB", legs, current_time=1020),
        }
        for name, context in cases.items():
            with self.subTest(constraint=name):
                # Each solo route fits, but HUB-A-B-HUB needs 35 rather than 25.
                self.assertEqual(dispatch(parcels, context), ["A"])


if __name__ == "__main__":
    unittest.main()
