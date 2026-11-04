"""Calculate performance metrics from one simulation run's event log."""

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from simulator.loaders import day_input_paths, parse_time

OUTSIDE_WINDOW_CREDIT = 0.5
SENSITIVITY_WEIGHTS = (0.25, 0.5, 0.75)


def _percentage(numerator: float, denominator: float) -> Optional[float]:
    """Use JSON null for a rate that has no observations."""

    return 100.0 * numerator / denominator if denominator else None


def calculate_metrics(
    parcels: List[Dict[str, str]],
    distances: List[Dict[str, str]],
    config: Dict[str, Any],
    events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Score one completed run using every input parcel as the denominator.

    Score A ranks completion first and uses on-time service rate only to break
    completion ties. Score B gives 1 point for an on-time delivery, 0.5 for an
    early/late delivery, and 0 for an undelivered parcel, scaled to 100.

    Window endpoints are inclusive. CSV times are HH:MM strings; event times
    are minutes after midnight. Distance follows each logged delivery order,
    including both hub legs. Mean load utilisation averages departure loads
    relative to capacity, not occupancy while driving. Undefined rates are
    None (JSON null). Stored scores retain precision rather than being rounded
    for display. Inputs are never modified. Only use successfully completed
    simulations: the guards detect unfinished trips, not full-day completeness.
    """

    inputs = {record["parcel_id"]: record for record in parcels}
    if len(inputs) != len(parcels):
        raise ValueError("parcel input contains duplicate parcel IDs")
    capacity = float(config["capacity"])
    if not math.isfinite(capacity) or capacity <= 0:
        raise ValueError("capacity must be finite and positive")

    # A trip ID is unique within a vehicle, not across the whole fleet.
    trips: Dict[Tuple[int, int], List[str]] = {}
    active: Dict[int, Tuple[int, int]] = {}
    delivered: Set[str] = set()
    on_time = early = late = 0
    for event in events:
        if event["event_type"] == "hub_departure":
            vehicle_id = event["vehicle_id"]
            trip = (vehicle_id, event["trip_id"])
            if trip in trips or vehicle_id in active:
                raise ValueError(f"duplicate or overlapping trip {trip}")
            trips[trip] = []
            active[vehicle_id] = trip
        elif event["event_type"] == "delivery":
            parcel_id = event["parcel_id"]
            if parcel_id not in inputs:
                raise ValueError(f"delivery refers to unknown parcel {parcel_id!r}")
            if parcel_id in delivered:
                raise ValueError(f"duplicate delivery for parcel {parcel_id!r}")
            trip = (event["vehicle_id"], event["trip_id"])
            if active.get(event["vehicle_id"]) != trip:
                raise ValueError(f"delivery has no active departure for trip {trip}")
            delivered_at = float(event["time"])
            if not math.isfinite(delivered_at):
                raise ValueError("delivery time must be finite")
            record = inputs[parcel_id]
            start = parse_time(record["delivery_window_start"])
            end = parse_time(record["delivery_window_end"])
            if start > end:
                raise ValueError(f"parcel {parcel_id!r} has an inverted window")
            if delivered_at < start:
                early += 1
            elif delivered_at > end:
                late += 1
            else:
                on_time += 1
            delivered.add(parcel_id)
            trips[trip].append(parcel_id)
        elif event["event_type"] == "vehicle_return":
            trip = active.pop(event["vehicle_id"], None)
            # Initial 08:00 returns have no preceding departure.
            if trip is not None and not trips[trip]:
                raise ValueError(f"trip {trip} returned without any deliveries")
    if active:
        raise ValueError("incomplete log: a departed vehicle has not returned")

    distance_lookup = {
        (row["location_1"], row["location_2"]): float(row["dist"])
        for row in distances
    }
    trip_distances = []
    trip_loads = []
    for parcel_ids in trips.values():
        locations = ["HUB"] + [
            inputs[parcel_id]["delivery_location_id"] for parcel_id in parcel_ids
        ] + ["HUB"]
        try:
            distance = math.fsum(
                distance_lookup[origin, destination]
                for origin, destination in zip(locations, locations[1:])
            )
        except KeyError as exc:
            raise ValueError(f"missing directed distance for {exc.args[0]}") from exc
        load = math.fsum(float(inputs[parcel_id]["size"]) for parcel_id in parcel_ids)
        if not math.isfinite(distance) or distance < 0:
            raise ValueError("trip distance must be finite and non-negative")
        if not math.isfinite(load) or load < 0:
            raise ValueError("trip load must be finite and non-negative")
        trip_distances.append(distance)
        trip_loads.append(load)

    total = len(inputs)
    completion_rate = _percentage(len(delivered), total)
    on_time_service_rate = _percentage(on_time, total)
    sensitivity = {
        str(weight): _percentage(on_time + weight * (early + late), total)
        for weight in SENSITIVITY_WEIGHTS
    }
    return {
        "total_parcels": total,
        "delivered_parcels": len(delivered),
        "on_time_parcels": on_time,
        "early_parcels": early,
        "late_parcels": late,
        "undelivered_parcels": total - len(delivered),
        "completion_rate_pct": completion_rate,
        "on_time_service_rate_pct": on_time_service_rate,
        "score_a": {
            "completion_rate_pct": completion_rate,
            "on_time_tiebreak_pct": on_time_service_rate,
        },
        "outside_window_credit": OUTSIDE_WINDOW_CREDIT,
        "score_b": sensitivity[str(OUTSIDE_WINDOW_CREDIT)],
        "score_b_sensitivity": sensitivity,
        "number_of_trips": len(trips),
        "total_distance_km": math.fsum(trip_distances),
        "average_load_utilisation_pct": _percentage(
            math.fsum(trip_loads), len(trips) * capacity,
        ),
    }


def main(argv: Optional[List[str]] = None) -> int:
    """Load one day's inputs and event log, then write the metrics report."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"),
                        help="directory containing dist.csv, config.json and demand/")
    parser.add_argument("--day", required=True, help="day identifier, for example day_001")
    parser.add_argument("--log", type=Path, required=True,
                        help="event log from a simulator run")
    parser.add_argument("--output", type=Path,
                        help="JSON report (default: metrics.json beside the selected log)")
    args = parser.parse_args(argv)
    try:
        parcel_path, distance_path, config_path = day_input_paths(args.data, args.day)
        output = args.output if args.output is not None else args.log.with_name("metrics.json")
        # The input files all live in the data directory, so this also protects them.
        if output.resolve() == args.data.resolve() or args.data.resolve() in output.resolve().parents:
            raise ValueError("report output must be outside the input data directory")
        if output.resolve() == args.log.resolve():
            raise ValueError("report output must not overwrite the log")
        with parcel_path.open(newline="", encoding="utf-8-sig") as stream:
            parcels = list(csv.DictReader(stream))
        with distance_path.open(newline="", encoding="utf-8-sig") as stream:
            distances = list(csv.DictReader(stream))
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        with args.log.open(encoding="utf-8") as stream:
            events = [json.loads(line) for line in stream if line.strip()]
        metrics = calculate_metrics(parcels, distances, config, events)
        report = json.dumps(metrics, indent=2, allow_nan=False) + "\n"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"Metrics report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
