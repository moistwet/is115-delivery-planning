"""Shared empty-route construction for two separately evaluated insertion rules."""

import math
from typing import Dict, List, Literal, Optional, Set, Tuple

from simulator.models import Parcel, SimulationContext
from .greedy_insertion import _distance_needs_recheck, _full_distance, _insertion_distance

HUB = "HUB"
CONSTRAINT_TOLERANCE = 1e-9
Strategy = Literal["efficiency", "protect"]


def _evaluate_route(
    route: List[str], parcel: Dict[str, Parcel], context: SimulationContext,
    departure: float,
    *, total_distance: Optional[float] = None,
) -> Optional[Tuple[int, float, Set[str]]]:
    """Return double credit, directed trip distance and on-time parcel IDs.

    Dispatch checks departure capacity before evaluation. Full travel and
    inclusive window timing are replayed, including the final hub return for
    range/cutoff checks. Double credit is exactly len(route) + on_time_count.
    A supplied total_distance reuses the insertion edge update; delivery times
    are still replayed from departure without changing floating-point timing.
    """

    distances = context["travel_distance"]
    if total_distance is None:
        # Full evaluation remains available for SA swaps and standalone checks.
        locations = [HUB] + [parcel[pid]["delivery_location_id"] for pid in route] + [HUB]
        total_distance = math.fsum(distances[a][b] for a, b in zip(locations, locations[1:]))
    if total_distance > context["max_trip_distance_km"] + CONSTRAINT_TOLERANCE:
        return None
    if departure + total_distance > context["return_cutoff"]:
        return None

    delivery_time = departure
    on_time: Set[str] = set()
    location = HUB
    for parcel_id in route:
        destination = parcel[parcel_id]["delivery_location_id"]
        delivery_time += distances[location][destination]  # Fixed 60 km/h and no stop service/waiting time.
        location = destination
        record = parcel[parcel_id]
        if record["delivery_window_start"] <= delivery_time <= record["delivery_window_end"]:
            on_time.add(parcel_id)
    return len(route) + len(on_time), total_distance, on_time


def _priority_key(
    strategy: Strategy, gain_units: int, added_distance: float,
    lost_on_time: int, arrival: float, parcel_id: str, position: int,
) -> tuple:
    """Smaller keys win; gain_units is twice the net service-credit gain."""

    if strategy == "protect":
        return (-gain_units, lost_on_time, added_distance, arrival, parcel_id, position)
    if added_distance <= 0.0:
        # No division by zero or arbitrary epsilon. Positive-gain insertions
        # that add no travel or shorten the trip precede positive-cost ones.
        return (0, -gain_units, added_distance, 0.0, arrival, parcel_id, position)
    # Multiplying every credit gain by two does not change ratio ordering.
    return (
        1, -gain_units / added_distance, -gain_units, added_distance,
        arrival, parcel_id, position,
    )


def build_route(
    parcel: Dict[str, Parcel], context: SimulationContext, strategy: Strategy,
) -> List[str]:
    """Build from empty, changing only the insertion ranking per strategy.

    Both variants rescore all affected deliveries and accept only strictly
    positive net credit gains. Efficiency ranks credit per added distance;
    protect keeps credit primary and minimises losses of existing on-time
    parcel identities when gains tie. Neither calls a previous dispatch policy.
    Both use cached edge-update distances, with full sums for potential winners
    and close numerical comparisons, and keep the original worst-case bound.

    For n supplied records, m eligible candidates and k selected parcels,
    time is O(n + m*(k+1)**3), bounded by O(n + m**4). Sets and candidate routes
    are streamed, so additional space stays O(m+k), as for original insertion.
    """

    if strategy not in ("efficiency", "protect"):
        raise ValueError(f"unknown insertion strategy: {strategy!r}")
    waiting = {
        pid: record for pid, record in parcel.items()
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
    on_time: Set[str] = set()

    while waiting:
        best_key: Optional[tuple] = None
        best_route: Optional[List[str]] = None
        best_id: Optional[str] = None
        best_units = credit_units
        best_distance = route_distance
        best_on_time = on_time
        for parcel_id, record in waiting.items():
            if load + record["size"] > context["capacity"] + CONSTRAINT_TOLERANCE:
                continue
            for position in range(len(route) + 1):
                candidate_distance = _insertion_distance(
                    route, parcel_id, position, parcel, distances, route_distance,
                    distance_limit=distance_limit,
                )
                candidate = route[:position] + [parcel_id] + route[position:]
                evaluated = _evaluate_route(
                    candidate, parcel, context, departure, total_distance=candidate_distance,
                )
                if evaluated is None:
                    continue
                candidate_units, candidate_distance, candidate_on_time = evaluated
                gain_units = candidate_units - credit_units
                if gain_units <= 0:
                    continue
                key = _priority_key(
                    strategy, gain_units, candidate_distance - route_distance,
                    len(on_time - candidate_on_time), record["arrival_time"],
                    parcel_id, position,
                )
                if _distance_needs_recheck(key, best_key, 2 if strategy == "protect" else 1):
                    candidate_distance = _full_distance(candidate, parcel, distances)
                    key = _priority_key(
                        strategy, gain_units, candidate_distance - route_distance,
                        len(on_time - candidate_on_time), record["arrival_time"],
                        parcel_id, position,
                    )
                if best_key is None or key < best_key:
                    best_key = key
                    best_route = candidate
                    best_id = parcel_id
                    best_units = candidate_units
                    best_distance = candidate_distance
                    best_on_time = candidate_on_time
        if best_id is None or best_route is None:
            break
        selected = waiting.pop(best_id)
        load += selected["size"]
        route = best_route
        credit_units = best_units
        route_distance = best_distance
        on_time = best_on_time
    return route
