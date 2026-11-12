"""Construct each trip from scratch by its best positive-credit insertion."""

from typing import Dict, List, Optional, Tuple

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import (
    CONSTRAINT_TOLERANCE, HUB, _distance_needs_recheck, _evaluate_route,
    _full_distance, _insertion_distance,
)


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Insert the feasible parcel with the greatest positive service gain.

    Ties prefer less added trip distance, earlier arrival, parcel ID and
    insertion position. All delivery windows are rescored after each proposal;
    capacity, full-trip range and return cutoff remain hard constraints.
    """

    waiting = {
        parcel_id: record for parcel_id, record in parcel.items()
        if record["vehicle_assigned"] is None and record["delivery_time"] is None
    }
    departure = context["current_time"] + context["departure_delay"]
    distances = context["travel_distance"]
    distance_limit = min(context["max_trip_distance_km"] + CONSTRAINT_TOLERANCE,
                         context["return_cutoff"] - departure)
    route: List[str] = []
    load = 0.0
    credit_units = 0
    route_distance = 0.0

    while waiting:
        best_key: Optional[Tuple[int, float, float, str, int]] = None
        best_route: Optional[List[str]] = None
        best_parcel_id: Optional[str] = None
        best_service_units = credit_units
        best_distance = route_distance

        for parcel_id, record in waiting.items():
            if load + record["size"] > context["capacity"] + CONSTRAINT_TOLERANCE:
                continue
            for position in range(len(route) + 1):
                candidate_distance = _insertion_distance(
                    route, parcel_id, position, parcel, distances, route_distance,
                    distance_limit=distance_limit,
                )
                candidate_route = route[:position] + [parcel_id] + route[position:]
                evaluation = _evaluate_route(
                    candidate_route, parcel, context, departure,
                    total_distance=candidate_distance,
                )
                if evaluation is None:
                    continue
                candidate_units, candidate_distance = evaluation
                service_gain = candidate_units - credit_units
                if service_gain <= 0:
                    continue
                key = (
                    -service_gain,
                    candidate_distance - route_distance,
                    record["arrival_time"],
                    parcel_id,
                    position,
                )
                if _distance_needs_recheck(key, best_key, 1):
                    candidate_distance = _full_distance(candidate_route, parcel, distances)
                    key = (key[0], candidate_distance - route_distance, *key[2:])
                if best_key is None or key < best_key:
                    best_key = key
                    best_route = candidate_route
                    best_parcel_id = parcel_id
                    best_service_units = candidate_units
                    best_distance = candidate_distance

        if best_parcel_id is None or best_route is None:
            break
        selected = waiting.pop(best_parcel_id)
        load += selected["size"]
        route = best_route
        credit_units = best_service_units
        route_distance = best_distance

    return route
