"""Adapt the lecture's closest-stop, two-gap TSP heuristic to delivery trips."""

import math
from typing import Dict, List, Optional, Tuple

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import CONSTRAINT_TOLERANCE, HUB, _full_distance


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Insert the parcel nearest to the tour into its shortest adjacent gap.

    Ties use arrival time, parcel ID and then insertion position. Capacity,
    full-trip range and return cutoff are hard constraints; delivery windows do
    not affect selection.
    """
    waiting = {
        parcel_id: record for parcel_id, record in parcel.items()
        if record["vehicle_assigned"] is None and record["delivery_time"] is None
    }
    route: List[str] = []
    load = 0.0
    distances = context["travel_distance"]
    capacity = context["capacity"] + CONSTRAINT_TOLERANCE
    max_distance = context["max_trip_distance_km"] + CONSTRAINT_TOLERANCE
    departure = context["current_time"] + context["departure_delay"]
    cutoff = context["return_cutoff"]
    distance_limit = min(max_distance, cutoff - departure)
    route_distance = distances[HUB][HUB]
    closest_stops = {
        parcel_id: (distances[HUB][record["delivery_location_id"]], 0)
        for parcel_id, record in waiting.items()
    }

    def best_adjacent_gap(
        parcel_id: str, destination: str, anchor_index: int,
    ) -> Optional[Tuple[float, int]]:
        if anchor_index == 0:
            positions = (0, len(route)) if route else (0,)
        else:
            positions = (anchor_index - 1, anchor_index)

        best_gap: Optional[Tuple[float, int]] = None
        for position in positions:
            before = parcel[route[position - 1]]["delivery_location_id"] if position else HUB
            after = (
                parcel[route[position]]["delivery_location_id"]
                if position < len(route) else HUB
            )
            candidate_distance = math.fsum((
                route_distance,
                distances[before][destination],
                distances[destination][after],
                -distances[before][after],
            ))
            candidate_route = route[:position] + [parcel_id] + route[position:]

            possible_winner = best_gap is None or candidate_distance < best_gap[0]
            close_to_comparison = (
                math.isclose(candidate_distance, route_distance, rel_tol=1e-12, abs_tol=1e-12)
                or math.isclose(candidate_distance, distance_limit, rel_tol=1e-12, abs_tol=1e-12)
                or (best_gap is not None and math.isclose(
                    candidate_distance, best_gap[0], rel_tol=1e-12, abs_tol=1e-12,
                ))
            )
            if possible_winner or close_to_comparison:
                candidate_distance = _full_distance(candidate_route, parcel, distances)
            if best_gap is not None and close_to_comparison:
                previous_position = best_gap[1]
                previous_route = (
                    route[:previous_position] + [parcel_id] + route[previous_position:]
                )
                best_gap = (
                    _full_distance(previous_route, parcel, distances), previous_position,
                )

            if candidate_distance > max_distance or departure + candidate_distance > cutoff:
                continue
            candidate_gap = (candidate_distance, position)
            if best_gap is None or candidate_gap < best_gap:
                best_gap = candidate_gap
        return best_gap

    while waiting:
        winner_key: Optional[Tuple[float, float, str]] = None
        winning_gap: Optional[Tuple[float, int]] = None
        for parcel_id, record in waiting.items():
            if load + record["size"] > capacity:
                continue
            anchor_distance, anchor_index = closest_stops[parcel_id]
            priority = (anchor_distance, record["arrival_time"], parcel_id)
            if winner_key is not None and priority >= winner_key:
                continue
            gap = best_adjacent_gap(
                parcel_id, record["delivery_location_id"], anchor_index,
            )
            if gap is not None:
                winner_key = priority
                winning_gap = gap

        if winner_key is None or winning_gap is None:
            break
        selected = winner_key[2]
        route_distance, position = winning_gap
        route.insert(position, selected)
        record = waiting.pop(selected)
        load += record["size"]
        del closest_stops[selected]

        new_anchor_index = position + 1
        new_distances = distances[record["delivery_location_id"]]
        for parcel_id, record in waiting.items():
            old_distance, old_index = closest_stops[parcel_id]
            if old_index >= new_anchor_index:
                old_index += 1
            new_distance = new_distances[record["delivery_location_id"]]
            closest_stops[parcel_id] = min(
                (old_distance, old_index), (new_distance, new_anchor_index),
            )
    return route
