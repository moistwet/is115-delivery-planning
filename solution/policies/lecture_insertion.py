"""Adapt the lecture's closest-stop, two-gap TSP heuristic to delivery trips."""

import math

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import CONSTRAINT_TOLERANCE, HUB


# Every finite binary64 distance is an integer multiple of 2**-1074 km.
_DISTANCE_SCALE = 1 << 1074


def _distance_units(distance: float) -> int:
    numerator, denominator = distance.as_integer_ratio()
    return numerator * (_DISTANCE_SCALE // denominator)


def _replace_edge_units(trip_units: int, legs: tuple[float, float, float]) -> int:
    first, second, replaced = legs
    return trip_units + _distance_units(first) + _distance_units(second) - _distance_units(replaced)


def dispatch(parcel: dict[str, Parcel], context: SimulationContext) -> list[str]:
    """Choose the nearest waiting parcel to the tour, then minimise trip distance.

    The hub seeds the tour. Update each waiting parcel's closest stop against
    only the newly inserted stop. Keep the highest-priority parcel with a
    feasible gap beside its closest stop. Preferred windows do not affect
    selection. A second trip total in exact units lets close comparisons use
    the rounded full sum without walking the route.

    Worst-case time is O(n + m**2) per dispatch for n supplied records and m
    eligible parcels, assuming constant-time dictionary and distance lookups.
    Additional space is O(m).
    """
    waiting = {
        pid: record for pid, record in parcel.items()
        if record["vehicle_assigned"] is None and record["delivery_time"] is None
    }
    route = []
    load = 0.0
    distances = context["travel_distance"]
    capacity = context["capacity"] + CONSTRAINT_TOLERANCE
    max_distance = context["max_trip_distance_km"] + CONSTRAINT_TOLERANCE
    departure = context["current_time"] + context["departure_delay"]
    cutoff = context["return_cutoff"]
    distance_limit = min(max_distance, cutoff - departure)
    route_distance = distances[HUB][HUB]
    trip_units = _distance_units(route_distance)
    closest_stops = {
        pid: (distances[HUB][record["delivery_location_id"]], 0)
        for pid, record in waiting.items()
    }

    def best_adjacent_gap(destination, anchor_index):
        if anchor_index == 0:
            positions = (0, len(route)) if route else (0,)
        else:
            positions = (anchor_index - 1, anchor_index)

        best = None
        for position in positions:
            before = parcel[route[position - 1]]["delivery_location_id"] if position else HUB
            after = parcel[route[position]]["delivery_location_id"] if position < len(route) else HUB
            legs = (distances[before][destination], distances[destination][after],
                    distances[before][after])
            first, second, replaced = legs
            distance = math.fsum((route_distance, first, second, -replaced))
            # Round the exact trial sum for the same close comparisons as before.
            if (math.isclose(distance, route_distance, rel_tol=1e-12, abs_tol=1e-12)
                    or math.isclose(distance, distance_limit, rel_tol=1e-12, abs_tol=1e-12)):
                distance = _replace_edge_units(trip_units, legs) / _DISTANCE_SCALE
            if distance > max_distance or departure + distance > cutoff:
                continue
            if best is not None and math.isclose(distance, best[0], rel_tol=1e-12, abs_tol=1e-12):
                _, previous_position, previous_legs = best
                best = (_replace_edge_units(trip_units, previous_legs) / _DISTANCE_SCALE,
                        previous_position, previous_legs)
                distance = _replace_edge_units(trip_units, legs) / _DISTANCE_SCALE
            candidate = (distance, position, legs)
            if best is None or candidate < best:
                best = candidate
        return best

    while waiting:
        winner_key = None
        winning_gap = None
        for pid, record in waiting.items():
            if load + record["size"] > capacity:
                continue
            anchor_distance, anchor_index = closest_stops[pid]
            priority = (anchor_distance, record["arrival_time"], pid)
            if winner_key is not None and priority >= winner_key:
                continue
            gap = best_adjacent_gap(record["delivery_location_id"], anchor_index)
            if gap is not None:
                winner_key = priority
                winning_gap = gap

        if winner_key is None:
            break
        selected = winner_key[2]
        _, position, legs = winning_gap
        route.insert(position, selected)
        trip_units = _replace_edge_units(trip_units, legs)
        route_distance = trip_units / _DISTANCE_SCALE
        record = waiting.pop(selected)
        load += record["size"]
        del closest_stops[selected]

        new_anchor_index = position + 1  # The hub is always anchor zero.
        new_distances = distances[record["delivery_location_id"]]
        for pid, record in waiting.items():
            old_distance, old_index = closest_stops[pid]
            # Shift the old anchor before comparing ties in the new route order.
            if old_index >= new_anchor_index:
                old_index += 1
            new_distance = new_distances[record["delivery_location_id"]]
            closest_stops[pid] = min((old_distance, old_index), (new_distance, new_anchor_index))
    return route
