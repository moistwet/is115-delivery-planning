"""Shared route evaluation and insertion helpers for dispatch policies."""

import math
from typing import Dict, List, Literal, Optional, Set, Tuple

from simulator.models import Parcel, SimulationContext

HUB = "HUB"
CONSTRAINT_TOLERANCE = 1e-9  # Same load/range tolerance as the simulator.
Strategy = Literal["efficiency", "protect"]


def _evaluate_route(
    route: List[str],
    parcel: Dict[str, Parcel],
    context: SimulationContext,
    departure: float,
    *,
    total_distance: Optional[float] = None,
) -> Optional[Tuple[int, float]]:
    """Return twice service credit and full distance, or None if infeasible.

    Departure load is checked by dispatch before calling this helper. Integer
    credit units avoid rounding in the reward: an in-window parcel earns two
    units and an early/late parcel earns one. Thus units = len(route) + on_time.
    Travel timing follows every delivery leg, as in the simulator; complete-trip
    range and return feasibility use the sum including the final hub leg.
    Insertion construction supplies a cached total_distance; standalone calls
    (including SA swaps) calculate the full distance here.
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
    on_time = 0
    location = HUB
    for parcel_id in route:
        destination = parcel[parcel_id]["delivery_location_id"]
        delivery_time += distances[location][destination]  # At 60 km/h, one km is one minute.
        location = destination
        record = parcel[parcel_id]
        if record["delivery_window_start"] <= delivery_time <= record["delivery_window_end"]:
            on_time += 1
    return len(route) + on_time, total_distance


def _full_distance(route, parcel, distances):
    """Canonical complete sum, used for saved winners and close comparisons."""

    locations = [HUB] + [parcel[pid]["delivery_location_id"] for pid in route] + [HUB]
    return math.fsum(distances[a][b] for a, b in zip(locations, locations[1:]))


def _insertion_distance(route, parcel_id, position, parcel, distances, route_distance,
                        *, distance_limit=math.inf):
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
        candidate = route[:position] + [parcel_id] + route[position:]
        return _full_distance(candidate, parcel, distances)
    return distance


def _distance_needs_recheck(key, best_key, distance_component):
    """Fully sum possible winners and numerically close priority comparisons."""

    return (best_key is None or key < best_key
            or math.isclose(key[distance_component], best_key[distance_component],
                            rel_tol=1e-12, abs_tol=1e-12))


def _evaluate_variant_route(
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
                evaluated = _evaluate_variant_route(
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
