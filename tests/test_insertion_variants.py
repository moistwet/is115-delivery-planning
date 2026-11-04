"""Hand-worked ranking differences for two independent insertion variants."""

import copy
import unittest

from solution.policies.greedy_insertion import dispatch as original
from solution.policies.greedy_insertion_efficiency import dispatch as efficiency
from solution.policies.greedy_insertion_protect import dispatch as protect


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


VARIANTS = {"efficiency": efficiency, "protect": protect}


class InsertionVariantTests(unittest.TestCase):
    def test_efficiency_prefers_half_credit_cheap_trip_to_full_credit_expensive_trip(self):
        parcels = {"near": _parcel("A", 800, 900), "far": _parcel("B", 730, 750)}
        context = _context("AB", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 100, ("B", "HUB"): 100,
        }, capacity=1)
        self.assertEqual(original(parcels, context), ["far"])
        self.assertEqual(efficiency(parcels, context), ["near"])
        self.assertEqual(protect(parcels, context), ["far"])

    def test_efficiency_equal_ratios_use_greater_gain_before_distance(self):
        parcels = {"half": _parcel("A", 800, 900), "whole": _parcel("B", 630, 640)}
        context = _context("AB", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 2, ("B", "HUB"): 2,
        }, capacity=1)
        # 0.5 / 2 and 1 / 4 are equal; higher gain breaks the ratio tie.
        self.assertEqual(efficiency(parcels, context), ["whole"])

    def test_efficiency_zero_added_distance_precedes_positive_cost_even_at_lower_gain(self):
        parcels = {"A": _parcel("A"), "B": _parcel("B", 900, 1000), "C": _parcel("C")}
        context = _context("ABC", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 1, ("B", "HUB"): 100, ("B", "A"): 0,
            ("HUB", "C"): 3, ("C", "HUB"): 3, ("A", "C"): 1,
        }, capacity=2)
        # A goes first. B-A still costs 2 km (gain 0.5); A-C costs 5 (gain 1).
        self.assertEqual(efficiency(parcels, context), ["B", "A"])
        self.assertEqual(original(parcels, context), ["A", "C"])

    def test_efficiency_negative_added_distance_is_not_divided_as_a_negative_ratio(self):
        parcels = {"A": _parcel("A"), "B": _parcel("B", 900, 1000), "C": _parcel("C")}
        context = _context("ABC", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 0, ("B", "HUB"): 100, ("B", "A"): 0,
            ("HUB", "C"): 3, ("C", "HUB"): 3, ("A", "C"): 1,
        }, capacity=2)
        # Deliberately non-metric directed costs: B-A shortens 2 km to 1 km.
        self.assertEqual(efficiency(parcels, context), ["B", "A"])

    def test_efficiency_nonpositive_cost_group_uses_gain_then_added_distance(self):
        for same_gain in (False, True):
            with self.subTest(same_gain=same_gain):
                parcels = {
                    "A": _parcel("A"),
                    "B": _parcel("B", 900, 1000, arrival=470),
                    "C": _parcel("C", 900 if same_gain else 0,
                                 1000 if same_gain else 1440, arrival=490),
                }
                context = _context("ABC", {
                    ("HUB", "A"): 1, ("A", "HUB"): 1,
                    ("HUB", "B"): 1 if same_gain else 0,
                    ("B", "HUB"): 100, ("B", "A"): 0,
                    ("HUB", "C"): 0, ("C", "HUB"): 100, ("C", "A"): 0,
                }, capacity=2)
                # C has either greater gain, or equal gain and a more negative delta.
                self.assertEqual(efficiency(parcels, context), ["C", "A"])

    def test_full_net_gain_can_exceed_one_after_two_early_deliveries_are_upgraded(self):
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
        # C-A earns 1. Inserting B first reaches B/C/A at 648/649/650,
        # earns 2.5, and has gain 1.5 even though B itself earns only 0.5.
        for name, dispatch in VARIANTS.items():
            with self.subTest(variant=name):
                self.assertEqual(dispatch(parcels, context), ["B", "C", "A"])

    def test_protect_counts_lost_parcel_identities_even_if_total_on_time_is_unchanged(self):
        parcels = {
            "A": _parcel("A", 631, 631),
            "B": _parcel("B", 632, 640),
            "C": _parcel("C", 800, 900),
        }
        context = _context("ABC", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 2, ("B", "HUB"): 10, ("B", "A"): 1,
            ("HUB", "C"): 3, ("C", "HUB"): 3, ("A", "C"): 1,
        }, capacity=2)
        # A first earns 1. B-A: B becomes on-time, A becomes late; gain 0.5,
        # delta 2. A-C: A stays on-time and C is early; gain 0.5, delta 3.
        # Aggregate T is 1 in BOTH alternatives, but only B-A loses A's status.
        self.assertEqual(original(parcels, context), ["B", "A"])
        self.assertEqual(protect(parcels, context), ["A", "C"])

    def test_protect_does_not_ban_a_larger_gain_that_harms_an_existing_on_time_parcel(self):
        parcels = {
            "A": _parcel("A", 631, 631),
            "C": _parcel("C", 650, 700),
            "E": _parcel("E", 651, 700),
            "B": _parcel("B", 900, 1000),
        }
        context = _context("ABCE", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "C"): 2, ("C", "HUB"): 1, ("A", "C"): 1,
            ("HUB", "E"): 3, ("E", "HUB"): 1, ("C", "E"): 1,
            ("HUB", "B"): 18, ("B", "HUB"): 100, ("B", "A"): 1,
        }, capacity=4)
        # Build A-C-E (reward 2). B-A-C-E earns 3: A becomes late, C/E become
        # on-time and B is early. Gain 1 outranks loss-free insertions of gain 0.5.
        self.assertEqual(protect(parcels, context), ["B", "A", "C", "E"])

    def test_protect_does_not_treat_an_early_to_late_change_as_an_on_time_loss(self):
        parcels = {
            "A": _parcel("A", 632, 632),
            "B": _parcel("B", 500, 600),
            "C": _parcel("C", 900, 1000),
        }
        context = _context("ABC", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 2, ("B", "HUB"): 10, ("B", "A"): 1,
            ("HUB", "C"): 3, ("C", "HUB"): 3, ("A", "C"): 1,
        }, capacity=2)
        # A starts early. B-A makes it late, but neither status earns the
        # on-time bonus. Both candidates gain 0.5, so B's smaller delta wins.
        self.assertEqual(protect(parcels, context), ["B", "A"])

    def test_eta_uses_preparation_once_and_the_full_delivery_prefix(self):
        parcels = {
            "A": _parcel("A", 640, 640),
            "B": _parcel("B", 655, 655),
            "C": _parcel("C", 500, 600),
        }
        context = _context("ABC", {
            ("HUB", "A"): 10, ("A", "HUB"): 10,
            ("HUB", "B"): 5, ("B", "HUB"): 10,
            ("HUB", "C"): 1, ("C", "HUB"): 18,
            ("A", "B"): 15, ("A", "C"): 1,
        }, capacity=2)
        # A at 640 then B at 655: B's gain/delta = 1/15 beats C's 0.5/9.
        # Omitting the prefix makes B early, flipping both ranking rules to C.
        for name, dispatch in VARIANTS.items():
            with self.subTest(variant=name):
                self.assertEqual(dispatch(parcels, context), ["A", "B"])

    def test_window_endpoints_are_inclusive_and_no_stop_wait_is_inserted(self):
        context = _context("AB", {
            ("HUB", "A"): 5, ("A", "HUB"): 5,
            ("HUB", "B"): 3, ("B", "HUB"): 3,
        }, capacity=1)
        cases = {
            "start": ((635, 645), ["A"]),
            "end": ((625, 635), ["A"]),
            "one_minute_early": ((636, 645), ["B"]),
            "one_minute_late": ((625, 634), ["B"]),
        }
        for name, dispatch in VARIANTS.items():
            for case, (window, expected) in cases.items():
                with self.subTest(variant=name, case=case):
                    parcels = {"A": _parcel("A", *window), "B": _parcel("B", 500, 600)}
                    self.assertEqual(dispatch(parcels, context), expected)

    def test_full_capacity_directed_return_and_preparation_cutoff_are_hard_constraints(self):
        cases = {
            "capacity": (
                {"A": _parcel("A", size=31), "B": _parcel("B", 700, 800)},
                _context("AB", {("HUB", "A"): 1, ("HUB", "B"): 5}),
            ),
            "directed_return": (
                {"A": _parcel("A"), "B": _parcel("B", 700, 800)},
                _context("AB", {
                    ("HUB", "A"): 5, ("A", "HUB"): 20,
                    ("HUB", "B"): 10, ("B", "HUB"): 5,
                }, max_trip_distance_km=20),
            ),
            "cutoff": (
                {"A": _parcel("A", 990, 1020), "B": _parcel("B", 1020, 1030)},
                _context("AB", {
                    ("HUB", "A"): 5, ("A", "HUB"): 90,
                    ("HUB", "B"): 20, ("B", "HUB"): 70,
                }, current_time=960),
            ),
        }
        for name, dispatch in VARIANTS.items():
            for case, (parcels, context) in cases.items():
                with self.subTest(variant=name, constraint=case):
                    self.assertEqual(dispatch(parcels, context), ["B"])

    def test_zero_net_gain_is_rejected_despite_a_new_delivery(self):
        parcels = {"A": _parcel("A", 640, 640), "B": _parcel("B", 500, 600)}
        context = _context("AB", {
            ("HUB", "A"): 10, ("A", "HUB"): 10,
            ("HUB", "B"): 5, ("B", "HUB"): 100,
            ("B", "A"): 10, ("A", "B"): 10,
        }, max_trip_distance_km=50)
        # B-A is feasible but replaces A's one point with two half-points.
        for name, dispatch in VARIANTS.items():
            with self.subTest(variant=name):
                self.assertEqual(dispatch(parcels, context), ["A"])

    def test_arrival_id_and_lowest_insertion_position_break_remaining_ties(self):
        parcels = {
            "P001": _parcel("A", arrival=490),
            "P003": _parcel("B", arrival=480),
            "P002": _parcel("C", arrival=480),
        }
        context = _context("ABC", {("HUB", node): 1 for node in "ABC"}, capacity=1)
        position_parcels = {"A": _parcel("A", arrival=480), "B": _parcel("B", arrival=490)}
        position_context = _context("AB", {
            ("HUB", "A"): 1, ("A", "HUB"): 1,
            ("HUB", "B"): 1, ("B", "HUB"): 1,
            ("A", "B"): 1, ("B", "A"): 1,
        })
        for name, dispatch in VARIANTS.items():
            with self.subTest(variant=name):
                self.assertEqual(dispatch(parcels, context), ["P002"])
                self.assertEqual(dispatch(position_parcels, position_context), ["B", "A"])

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
        for name, dispatch in VARIANTS.items():
            with self.subTest(variant=name):
                self.assertEqual(dispatch(parcels, context), ["waiting"])
                self.assertEqual(parcels, original_parcels)
                self.assertEqual(context, original_context)

    def test_shared_destination_zero_added_distance_keeps_both_parcels(self):
        parcels = {
            "P001": _parcel("A", 635, 635, arrival=480),
            "P002": _parcel("A", 635, 635, arrival=490),
        }
        context = _context("A", {("HUB", "A"): 5, ("A", "HUB"): 5})
        for name, dispatch in VARIANTS.items():
            with self.subTest(variant=name):
                self.assertEqual(dispatch(parcels, context), ["P002", "P001"])

    def test_empty_and_no_eligible_or_feasible_candidates_return_empty(self):
        context = _context("A", {("HUB", "A"): 5, ("A", "HUB"): 5})
        cases = {
            "empty": {},
            "assigned": {"A": _parcel("A", assigned=1)},
            "too_large": {"A": _parcel("A", size=31)},
        }
        for name, dispatch in VARIANTS.items():
            for case, parcels in cases.items():
                with self.subTest(variant=name, case=case):
                    self.assertEqual(dispatch(parcels, context), [])


if __name__ == "__main__":
    unittest.main()
