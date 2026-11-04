"""Check agreed metrics against small, hand-calculated delivery scenarios."""

import copy
import unittest

from solution.performance_monitor import calculate_metrics


def _parcel(parcel_id, location, size, start, end, arrival="08:00"):
    return {
        "parcel_id": parcel_id,
        "arrival_time": arrival,
        "delivery_location_id": location,
        "size": str(size),
        "delivery_window_start": start,
        "delivery_window_end": end,
    }


def _event(event_type, time, **fields):
    return {"event_type": event_type, "time": time, **fields}


class PerformanceMonitorTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "number_of_vehicles": 2,
            "capacity": 30,
            "vehicle_range_km": 320,
        }
        self.parcels = [
            _parcel("P001", "A", 6, "08:40", "08:55"),
            _parcel("P002", "B", 9, "08:45", "08:50"),
            _parcel("P003", "A", 3, "09:00", "10:00"),
            _parcel("P004", "C", 12, "08:00", "09:00"),
            _parcel("P005", "B", 4, "10:00", "10:20", "09:30"),
            _parcel("P006", "A", 5, "11:00", "12:00", "11:00"),
        ]
        # Distances are deliberately asymmetric. A -> B is 10; B -> A is 70.
        matrix = {
            "HUB": {"HUB": 0, "A": 10, "B": 20, "C": 40},
            "A": {"HUB": 30, "A": 0, "B": 10, "C": 45},
            "B": {"HUB": 20, "A": 70, "B": 0, "C": 35},
            "C": {"HUB": 15, "A": 25, "B": 50, "C": 0},
        }
        self.distances = [
            {"location_1": origin, "location_2": destination, "dist": str(km)}
            for origin, destinations in matrix.items()
            for destination, km in destinations.items()
        ]
        self.initial_returns = [
            _event("vehicle_return", 480, vehicle_id=1),
            _event("vehicle_return", 480, vehicle_id=2),
        ]
        self.events = [
            *[_event("parcel_arrival", 480, parcel_id=f"P00{i:01d}")
              for i in range(1, 5)],
            *self.initial_returns,
            _event("dispatch_planning", 480),
            _event("hub_departure", 510, vehicle_id=1, trip_id=1),
            _event("hub_departure", 510, vehicle_id=2, trip_id=1),
            _event("delivery", 520, vehicle_id=1, trip_id=1, parcel_id="P001"),
            _event("delivery", 520, vehicle_id=1, trip_id=1, parcel_id="P003"),
            _event("delivery", 530, vehicle_id=1, trip_id=1, parcel_id="P002"),
            _event("vehicle_return", 550, vehicle_id=1),
            _event("delivery", 550, vehicle_id=2, trip_id=1, parcel_id="P004"),
            _event("vehicle_return", 565, vehicle_id=2),
            _event("parcel_arrival", 570, parcel_id="P005"),
            _event("dispatch_planning", 570),
            _event("hub_departure", 600, vehicle_id=1, trip_id=2),
            _event("delivery", 620, vehicle_id=1, trip_id=2, parcel_id="P005"),
            _event("vehicle_return", 640, vehicle_id=1),
            _event("parcel_arrival", 660, parcel_id="P006"),
        ]

    def calculate(self, *, parcels=None, events=None):
        return calculate_metrics(
            self.parcels if parcels is None else parcels,
            self.distances,
            self.config,
            self.events if events is None else events,
        )

    def test_hand_worked_service_counts_scores_and_inclusive_boundaries(self):
        result = self.calculate()
        # P001 is at its window start; P002 and P005 are at their window ends.
        # P003 is early, P004 is late, and P006 remains undelivered.
        for field, expected in {
            "total_parcels": 6,
            "delivered_parcels": 5,
            "on_time_parcels": 3,
            "early_parcels": 1,
            "late_parcels": 1,
            "undelivered_parcels": 1,
        }.items():
            with self.subTest(field=field):
                self.assertEqual(result[field], expected)
        self.assertAlmostEqual(result["completion_rate_pct"], 250 / 3)
        self.assertAlmostEqual(result["on_time_service_rate_pct"], 50)
        self.assertAlmostEqual(result["score_a"]["completion_rate_pct"], 250 / 3)
        self.assertAlmostEqual(result["score_a"]["on_time_tiebreak_pct"], 50)
        self.assertAlmostEqual(result["score_b"], 200 / 3)
        expected_sensitivity = {"0.25": 175 / 3, "0.5": 200 / 3, "0.75": 75}
        self.assertEqual(set(result["score_b_sensitivity"]), set(expected_sensitivity))
        for weight, expected in expected_sensitivity.items():
            with self.subTest(weight=weight):
                self.assertAlmostEqual(result["score_b_sensitivity"][weight], expected)

    def test_directed_routes_include_returns_and_keep_vehicle_trip_keys_distinct(self):
        result = self.calculate()
        # Vehicle 1, trip 1: HUB-A-A-B-HUB = 10 + 0 + 10 + 20 = 40 km.
        # Vehicle 2, trip 1: HUB-C-HUB = 40 + 15 = 55 km.
        # Vehicle 1, trip 2: HUB-B-HUB = 20 + 20 = 40 km.
        self.assertAlmostEqual(result["total_distance_km"], 135)
        self.assertEqual(result["number_of_trips"], 3)
        # Trip loads are 18, 12, and 4. Mean utilisation is 34 / 90 * 100.
        self.assertAlmostEqual(result["average_load_utilisation_pct"], 340 / 9)

    def test_no_deliveries_scores_zero_without_counting_initial_returns_as_trips(self):
        arrivals = [
            _event("parcel_arrival", 480, parcel_id=record["parcel_id"])
            for record in self.parcels[:4]
        ] + [
            _event("parcel_arrival", 570, parcel_id="P005"),
            _event("parcel_arrival", 660, parcel_id="P006"),
        ]
        events = sorted(arrivals + self.initial_returns, key=lambda event: event["time"])
        result = self.calculate(events=events)
        self.assertEqual(result["total_parcels"], 6)
        for field in ("delivered_parcels", "on_time_parcels", "early_parcels", "late_parcels"):
            self.assertEqual(result[field], 0)
        self.assertEqual(result["undelivered_parcels"], 6)
        self.assertEqual(result["completion_rate_pct"], 0)
        self.assertEqual(result["on_time_service_rate_pct"], 0)
        self.assertEqual(result["score_a"], {
            "completion_rate_pct": 0,
            "on_time_tiebreak_pct": 0,
        })
        self.assertEqual(result["score_b"], 0)
        self.assertEqual(result["score_b_sensitivity"], {
            "0.25": 0,
            "0.5": 0,
            "0.75": 0,
        })
        self.assertEqual(result["number_of_trips"], 0)
        self.assertEqual(result["total_distance_km"], 0)
        self.assertIsNone(result["average_load_utilisation_pct"])

    def test_empty_day_has_no_applicable_rates_or_scores(self):
        result = self.calculate(parcels=[], events=self.initial_returns)
        for field in ("total_parcels", "delivered_parcels", "on_time_parcels",
                      "early_parcels", "late_parcels", "undelivered_parcels"):
            self.assertEqual(result[field], 0)
        self.assertIsNone(result["completion_rate_pct"])
        self.assertIsNone(result["on_time_service_rate_pct"])
        self.assertEqual(result["score_a"], {
            "completion_rate_pct": None,
            "on_time_tiebreak_pct": None,
        })
        self.assertIsNone(result["score_b"])
        self.assertEqual(result["score_b_sensitivity"], {
            "0.25": None,
            "0.5": None,
            "0.75": None,
        })
        self.assertEqual(result["number_of_trips"], 0)
        self.assertEqual(result["total_distance_km"], 0)
        self.assertIsNone(result["average_load_utilisation_pct"])

    def test_duplicate_delivery_is_rejected(self):
        events = copy.deepcopy(self.events)
        events.insert(9, _event("delivery", 520, vehicle_id=1, trip_id=1, parcel_id="P001"))
        with self.assertRaises(ValueError):
            self.calculate(events=events)

    def test_unknown_delivery_is_rejected(self):
        events = copy.deepcopy(self.events)
        next(event for event in events if event["event_type"] == "delivery")["parcel_id"] = "P999"
        with self.assertRaises(ValueError):
            self.calculate(events=events)

    def test_incomplete_departed_trip_is_rejected(self):
        prefix = [
            _event("parcel_arrival", 480, parcel_id="P001"),
            *self.initial_returns,
            _event("hub_departure", 510, vehicle_id=1, trip_id=1),
        ]
        incomplete_cases = {
            "neither_delivery_nor_return": prefix,
            "delivery_without_return": prefix + [
                _event("delivery", 520, vehicle_id=1, trip_id=1, parcel_id="P001"),
            ],
            "return_without_delivery": prefix + [
                _event("vehicle_return", 550, vehicle_id=1),
            ],
        }
        for name, events in incomplete_cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.calculate(events=events)


if __name__ == "__main__":
    unittest.main()
