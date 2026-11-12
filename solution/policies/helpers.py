"""Shared route evaluation and insertion helpers for dispatch policies."""

import math
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from simulator.models import Parcel, SimulationContext

HUB = "HUB"
CONSTRAINT_TOLERANCE = 1e-9  # Same load/range tolerance as the simulator.
Strategy = Literal["efficiency", "protect"]
RouteEvaluation = Tuple[int, float]
DetailedRouteEvaluation = Tuple[int, float, Set[str]]
PriorityKey = Tuple[Any, ...]


def _evaluate_route_details(
    route: List[str],
    parcel: Dict[str, Parcel],
    context: SimulationContext,
    departure: float,
    *,
    total_distance: Optional[float] = None,
) -> Optional[DetailedRouteEvaluation]:
    """Evaluate feasibility, service credit, distance and on-time identities."""

    distances = context["travel_distance"]
    if total_distance is None:
        total_distance = _full_distance(route, parcel, distances)
    if total_distance > context["max_trip_distance_km"] + CONSTRAINT_TOLERANCE:
        return None
    if departure + total_distance > context["return_cutoff"]:
        return None

    delivery_time = departure
    location = HUB
    on_time: Set[str] = set()
    for parcel_id in route:
        destination = parcel[parcel_id]["delivery_location_id"]
        delivery_time += distances[location][destination]
        location = destination
        record = parcel[parcel_id]
        if record["delivery_window_start"] <= delivery_time <= record["delivery_window_end"]:
            on_time.add(parcel_id)

    return len(route) + len(on_time), total_distance, on_time


def _evaluate_route(
    route: List[str],
    parcel: Dict[str, Parcel],
    context: SimulationContext,
    departure: float,
    *,
    total_distance: Optional[float] = None,
) -> Optional[RouteEvaluation]:
    """Return twice the service credit and trip distance when feasible."""

    evaluation = _evaluate_route_details(
        route, parcel, context, departure, total_distance=total_distance,
    )
    if evaluation is None:
        return None
    service_units, route_distance, _ = evaluation
    return service_units, route_distance


def _full_distance(
    route: List[str],
    parcel: Dict[str, Parcel],
    distances: Dict[str, Dict[str, float]],
) -> float:
    """Canonical complete sum, used for saved winners and close comparisons."""

    locations = [HUB] + [parcel[parcel_id]["delivery_location_id"] for parcel_id in route] + [HUB]
    return math.fsum(distances[a][b] for a, b in zip(locations, locations[1:]))


def _insertion_distance(
    route: List[str],
    parcel_id: str,
    position: int,
    parcel: Dict[str, Parcel],
    distances: Dict[str, Dict[str, float]],
    route_distance: float,
    *,
    distance_limit: float = math.inf,
) -> float:
    """Replace A->C with A->B->C, including the hub at either end.

    Recheck close zero-cost moves and hard boundaries using the complete sum.
    Closeness triggers a recalculation; it never changes a comparison's rules.
    """

    before = parcel[route[position - 1]]["delivery_location_id"] if position else HUB
    after = parcel[route[position]]["delivery_location_id"] if position < len(route) else HUB
    inserted = parcel[parcel_id]["delivery_location_id"]
    distance = math.fsum((route_distance, distances[before][inserted],
                          distances[inserted][after], -distances[before][after]))
    if (math.isclose(distance, route_distance, rel_tol=1e-12, abs_tol=1e-12)
            or math.isclose(distance, distance_limit, rel_tol=1e-12, abs_tol=1e-12)):
        candidate_route = route[:position] + [parcel_id] + route[position:]
        return _full_distance(candidate_route, parcel, distances)
    return distance


def _distance_needs_recheck(
    key: PriorityKey,
    best_key: Optional[PriorityKey],
    distance_component: int,
) -> bool:
    """Fully sum possible winners and numerically close priority comparisons."""

    return (best_key is None or key < best_key
            or math.isclose(key[distance_component], best_key[distance_component],
                            rel_tol=1e-12, abs_tol=1e-12))


def _evaluate_variant_route(
    route: List[str], parcel: Dict[str, Parcel], context: SimulationContext,
    departure: float,
    *, total_distance: Optional[float] = None,
) -> Optional[DetailedRouteEvaluation]:
    """Return service units, trip distance and on-time parcel IDs when feasible."""

    return _evaluate_route_details(
        route, parcel, context, departure, total_distance=total_distance,
    )


def _priority_key(
    strategy: Strategy, service_gain: int, added_distance: float,
    lost_on_time: int, arrival: float, parcel_id: str, position: int,
) -> PriorityKey:
    """Return a ranking key; service gain uses doubled credit units."""

    if strategy == "protect":
        return (-service_gain, lost_on_time, added_distance, arrival, parcel_id, position)
    if added_distance <= 0.0:
        # No division by zero or arbitrary epsilon. Positive-gain insertions
        # that add no travel or shorten the trip precede positive-cost ones.
        return (0, -service_gain, added_distance, 0.0, arrival, parcel_id, position)
    # Multiplying every credit gain by two does not change ratio ordering.
    return (
        1, -service_gain / added_distance, -service_gain, added_distance,
        arrival, parcel_id, position,
    )


def build_route(
    parcel: Dict[str, Parcel], context: SimulationContext, strategy: Strategy,
) -> List[str]:
    """Build a route from positive-gain insertions ranked by the strategy."""

    if strategy not in ("efficiency", "protect"):
        raise ValueError(f"unknown insertion strategy: {strategy!r}")
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
    on_time: Set[str] = set()

    while waiting:
        best_key: Optional[PriorityKey] = None
        best_route: Optional[List[str]] = None
        best_parcel_id: Optional[str] = None
        best_service_units = credit_units
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
                candidate_route = route[:position] + [parcel_id] + route[position:]
                evaluated = _evaluate_variant_route(
                    candidate_route, parcel, context, departure,
                    total_distance=candidate_distance,
                )
                if evaluated is None:
                    continue
                candidate_units, candidate_distance, candidate_on_time = evaluated
                service_gain = candidate_units - credit_units
                if service_gain <= 0:
                    continue
                key = _priority_key(
                    strategy, service_gain, candidate_distance - route_distance,
                    len(on_time - candidate_on_time), record["arrival_time"],
                    parcel_id, position,
                )
                if _distance_needs_recheck(key, best_key, 2 if strategy == "protect" else 1):
                    candidate_distance = _full_distance(candidate_route, parcel, distances)
                    key = _priority_key(
                        strategy, service_gain, candidate_distance - route_distance,
                        len(on_time - candidate_on_time), record["arrival_time"],
                        parcel_id, position,
                    )
                if best_key is None or key < best_key:
                    best_key = key
                    best_route = candidate_route
                    best_parcel_id = parcel_id
                    best_service_units = candidate_units
                    best_distance = candidate_distance
                    best_on_time = candidate_on_time
        if best_parcel_id is None or best_route is None:
            break
        selected = waiting.pop(best_parcel_id)
        load += selected["size"]
        route = best_route
        credit_units = best_service_units
        route_distance = best_distance
        on_time = best_on_time
    return route
