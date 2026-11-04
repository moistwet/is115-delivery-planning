"""Hand-worked route choices for the nearest feasible neighbour policy."""

import copy
import unittest

from solution.policies.nearest_neighbour import dispatch


def _parcel(location, size=1.0, arrival=480.0, *, assigned=None, delivered=None):
    return {
        "arrival_time": arrival,
        "delivery_location_id": location,
        "delivery_window_start": 540.0,
        "delivery_window_end": 600.0,
        "size": size,
        "delivery_time": delivered,
        "vehicle_assigned": assigned,
        "trip_id": 1 if assigned is not None else None,
    }


def _distances(locations, legs, default=100.0):
    nodes = ["HUB", *locations]
    matrix = {
        origin: {
            destination: 0.0 if origin == destination else default
            for destination in nodes
        }
        for origin in nodes
    }
    for (origin, destination), distance in legs.items():
        matrix[origin][destination] = distance
    return matrix


def _context(distances, **changes):
    context = {
        "current_time": 600.0,
        "vehicle_id": 1,
        "capacity": 30.0,
        "travel_distance": distances,
        "departure_delay": 30.0,
        "return_cutoff": 1080.0,
        "max_trip_distance_km": 320.0,
        "fleet": {1: {"available_at": 600.0, "max_trip_distance_km": 320.0}},
    }
    context.update(changes)
    return context


class NearestNeighbourTests(unittest.TestCase):
    def test_recomputes_nearest_from_current_stop_not_from_hub(self):
        parcels = {"PA": _parcel("A"), "PB": _parcel("B"), "PC": _parcel("C")}
        distances = _distances("ABC", {
            ("HUB", "A"): 4,
            ("HUB", "B"): 5,
            ("HUB", "C"): 6,
            ("A", "B"): 20,
            ("A", "C"): 1,
            ("C", "B"): 1,
        })
        # B is closer to the hub than C, but C is closer after reaching A.
        self.assertEqual(dispatch(parcels, _context(distances)), ["PA", "PC", "PB"])

    def test_skips_nearest_over_capacity_and_selects_farther_feasible_parcel(self):
        parcels = {
            "PA": _parcel("A", size=6),
            "PB": _parcel("B", size=3),
            "PC": _parcel("C", size=2),
        }
        distances = _distances("ABC", {
            ("HUB", "A"): 1,
            ("HUB", "B"): 2,
            ("HUB", "C"): 3,
            ("B", "C"): 1,
        })
        self.assertEqual(dispatch(parcels, _context(distances, capacity=5)), ["PB", "PC"])

    def test_capacity_counts_all_parcels_loaded_at_departure(self):
        parcels = {"PA": _parcel("A", size=4), "PB": _parcel("B", size=4)}
        distances = _distances("AB", {
            ("HUB", "A"): 1,
            ("HUB", "B"): 2,
            ("A", "B"): 1,
        })
        # Delivering PA first cannot make an eight-unit departure load fit in five.
        self.assertEqual(dispatch(parcels, _context(distances, capacity=5)), ["PA"])

    def test_range_includes_directed_return_to_hub(self):
        parcels = {"PA": _parcel("A"), "PB": _parcel("B")}
        distances = _distances("AB", {
            ("HUB", "A"): 5,
            ("A", "HUB"): 20,
            ("HUB", "B"): 10,
            ("B", "HUB"): 5,
        })
        # A needs 25 km round trip; B needs 15. Doubling outbound distance is wrong.
        self.assertEqual(dispatch(parcels, _context(distances, max_trip_distance_km=20)), ["PB"])

    def test_cutoff_includes_preparation_and_allows_exact_return_deadline(self):
        parcels = {"PA": _parcel("A"), "PB": _parcel("B")}
        distances = _distances("AB", {
            ("HUB", "A"): 5,
            ("A", "HUB"): 90,
            ("HUB", "B"): 20,
            ("B", "HUB"): 70,
        })
        # Plan 16:00, depart 16:30. A returns 18:05; B returns exactly 18:00.
        self.assertEqual(dispatch(parcels, _context(distances, current_time=960)), ["PB"])

    def test_cumulative_prefix_is_included_in_range_and_return_time(self):
        parcels = {"PA": _parcel("A"), "PB": _parcel("B")}
        distances = _distances("AB", {
            ("HUB", "A"): 10,
            ("A", "HUB"): 10,
            ("HUB", "B"): 15,
            ("B", "HUB"): 10,
            ("A", "B"): 15,
        })
        # Each can travel alone, but HUB-A-B-HUB needs 35 km, not 25.
        cases = {
            "range_budget": _context(distances, max_trip_distance_km=30),
            "time_budget": _context(distances, current_time=1020),
        }
        for name, context in cases.items():
            with self.subTest(budget=name):
                self.assertEqual(dispatch(parcels, context), ["PA"])

    def test_equal_distances_use_arrival_time_then_parcel_id(self):
        parcels = {
            "P001": _parcel("A", arrival=490),
            "P003": _parcel("B", arrival=480),
            "P002": _parcel("C", arrival=480),
        }
        distances = _distances("ABC", {
            ("HUB", "A"): 10,
            ("HUB", "B"): 10,
            ("HUB", "C"): 10,
        })
        # The smallest ID arrives later; the two oldest parcels tie by ID.
        self.assertEqual(dispatch(parcels, _context(distances, capacity=1)), ["P002"])

    def test_excludes_both_assigned_and_delivered_parcels(self):
        parcels = {
            "assigned": _parcel("A", assigned=2),
            "delivered": _parcel("B", delivered=590),
            "waiting": _parcel("C"),
        }
        distances = _distances("ABC", {
            ("HUB", "A"): 1,
            ("HUB", "B"): 2,
            ("HUB", "C"): 3,
        })
        self.assertEqual(dispatch(parcels, _context(distances, capacity=1)), ["waiting"])

    def test_selects_another_parcel_at_same_location_with_zero_extra_leg(self):
        parcels = {
            "P001": _parcel("A", arrival=480),
            "P002": _parcel("A", arrival=490),
            "P003": _parcel("B", arrival=470),
        }
        distances = _distances("AB", {
            ("HUB", "A"): 5,
            ("HUB", "B"): 6,
            ("A", "B"): 5,
            ("B", "HUB"): 5,
        })
        self.assertEqual(dispatch(parcels, _context(distances)), ["P001", "P002", "P003"])

    def test_ranks_by_next_leg_not_round_trip_distance(self):
        parcels = {"PA": _parcel("A"), "PB": _parcel("B")}
        distances = _distances("AB", {
            ("HUB", "A"): 5,
            ("A", "HUB"): 100,
            ("HUB", "B"): 6,
            ("B", "HUB"): 1,
        })
        # Both routes are legal. A wins the stated five-km versus six-km criterion,
        # even though B has a much shorter overall round trip.
        self.assertEqual(dispatch(parcels, _context(distances, capacity=1)), ["PA"])

    def test_late_day_hand_worked_route_selects_c_then_d(self):
        parcels = {
            "PA": _parcel("A"),
            "PB": _parcel("B"),
            "PC": _parcel("C", size=12),
            "PD": _parcel("D", size=18),
        }
        distances = _distances("ABCD", {
            ("HUB", "A"): 5,
            ("A", "HUB"): 100,
            ("HUB", "B"): 8,
            ("B", "HUB"): 90,
            ("HUB", "C"): 10,
            ("C", "HUB"): 20,
            ("HUB", "D"): 15,
            ("D", "HUB"): 20,
            ("C", "D"): 5,
        })
        # At 16:00 planning, A and B cannot get back by 18:00. C-D returns
        # at 17:05 with load exactly 30 and a full route distance of 35 km.
        self.assertEqual(dispatch(parcels, _context(distances, current_time=960)), ["PC", "PD"])

    def test_does_not_wait_for_windows_or_prioritise_an_urgent_farther_parcel(self):
        parcels = {"PA": _parcel("A"), "PB": _parcel("B")}
        parcels["PA"]["delivery_window_start"] = 1000
        parcels["PA"]["delivery_window_end"] = 1010
        parcels["PB"]["delivery_window_start"] = 600
        parcels["PB"]["delivery_window_end"] = 640
        distances = _distances("AB", {("HUB", "A"): 1, ("HUB", "B"): 2})
        self.assertEqual(dispatch(parcels, _context(distances, capacity=1)), ["PA"])

    def test_accepts_normal_float_roundoff_but_not_excess_beyond_tolerance(self):
        parcels = {"PA": _parcel("A", size=0.1), "PB": _parcel("B", size=0.2)}
        distances = _distances("AB", {
            ("HUB", "A"): 0.1,
            ("A", "HUB"): 0.1,
            ("HUB", "B"): 0.2,
            ("A", "B"): 0.2,
            ("B", "HUB"): 0.3,
        })
        context = _context(distances, capacity=0.3, max_trip_distance_km=0.6)
        # 0.1 + 0.2 and 0.1 + 0.2 + 0.3 incur harmless binary roundoff.
        self.assertEqual(dispatch(parcels, context), ["PA", "PB"])

        with self.subTest(excess="capacity"):
            over_capacity = copy.deepcopy(parcels)
            over_capacity["PB"]["size"] = 0.200000002
            self.assertEqual(dispatch(over_capacity, context), ["PA"])
        with self.subTest(excess="range"):
            over_range = copy.deepcopy(context)
            over_range["travel_distance"]["B"]["HUB"] = 0.300000002
            self.assertEqual(dispatch(parcels, over_range), ["PA"])

    def test_empty_no_eligible_and_no_feasible_inputs_return_empty_route(self):
        distances = _distances("A", {("HUB", "A"): 5, ("A", "HUB"): 10})
        cases = {
            "empty": ({}, _context(distances)),
            "already_assigned": ({"PA": _parcel("A", assigned=1)}, _context(distances)),
            "too_large": ({"PA": _parcel("A", size=31)}, _context(distances)),
            "too_far": ({"PA": _parcel("A")}, _context(distances, max_trip_distance_km=14)),
            "too_late": ({"PA": _parcel("A")}, _context(distances, current_time=1050)),
        }
        for name, (parcels, context) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(dispatch(parcels, context), [])

    def test_inputs_are_not_mutated(self):
        parcels = {"PA": _parcel("A"), "PB": _parcel("B"), "PC": _parcel("C", assigned=2)}
        distances = _distances("ABC", {("HUB", "A"): 1, ("HUB", "B"): 2, ("A", "B"): 1})
        context = _context(distances)
        original_parcels = copy.deepcopy(parcels)
        original_context = copy.deepcopy(context)
        self.assertEqual(dispatch(parcels, context), ["PA", "PB"])
        self.assertEqual(parcels, original_parcels)
        self.assertEqual(context, original_context)


if __name__ == "__main__":
    unittest.main()
