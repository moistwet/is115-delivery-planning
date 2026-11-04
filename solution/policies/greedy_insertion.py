"""Construct each trip from scratch by its best positive-credit insertion."""

import math
from typing import Dict, List, Optional, Tuple

from simulator.models import Parcel, SimulationContext

HUB = "HUB"
CONSTRAINT_TOLERANCE = 1e-9  # Same load/range tolerance as the simulator.


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


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Greedily choose a waiting parcel and its insertion position together.

    Start empty; each round evaluates every eligible parcel in every route slot.
    All deliveries are rescored because an insertion can change the window
    status of parcels already selected. Maximise the net increase in service
    credit (on-time 1, outside 0.5), then minimise added complete-trip distance.
    Further ties use candidate arrival time, parcel ID, then insertion position.

    Only strictly positive credit gains are accepted. If no feasible positive
    insertion remains, stop even if some parcels could physically fit. Windows
    are soft, preparation is counted once, and there is no intentional waiting.
    No other policy is called; inputs are read-only.

    Trial distances replace one directed edge in the saved complete-trip total.
    Possible winners and close distance/ratio/boundary comparisons use the full
    sum to preserve floating-point tiebreaks. Delivery times are still replayed.
    This saves repeated summation, not a factor in the worst-case bound below.

    With n supplied parcels, m eligible parcels, and k ultimately selected,
    worst-case time is O(n + m*(k+1)**3), hence O(n + m**4) when k can reach m.
    Each of O(m) candidates has O(k) positions costing O(k) to construct/score
    per round. Stream candidates and retain only the best: extra space O(m+k).
    """

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

    while waiting:
        best_key: Optional[Tuple[int, float, float, str, int]] = None
        best_route: Optional[List[str]] = None
        best_id: Optional[str] = None
        best_units = credit_units
        best_distance = route_distance

        for parcel_id, record in waiting.items():
            if load + record["size"] > context["capacity"] + CONSTRAINT_TOLERANCE:
                continue
            for position in range(len(route) + 1):
                candidate_distance = _insertion_distance(
                    route, parcel_id, position, parcel, distances, route_distance,
                    distance_limit=distance_limit,
                )
                candidate = route[:position] + [parcel_id] + route[position:]
                evaluation = _evaluate_route(
                    candidate, parcel, context, departure, total_distance=candidate_distance,
                )
                if evaluation is None:
                    continue
                candidate_units, candidate_distance = evaluation
                gain_units = candidate_units - credit_units
                if gain_units <= 0:
                    continue
                key = (
                    -gain_units,
                    candidate_distance - route_distance,
                    record["arrival_time"],
                    parcel_id,
                    position,
                )
                if _distance_needs_recheck(key, best_key, 1):
                    candidate_distance = _full_distance(candidate, parcel, distances)
                    key = (key[0], candidate_distance - route_distance, *key[2:])
                if best_key is None or key < best_key:
                    best_key = key
                    best_route = candidate
                    best_id = parcel_id
                    best_units = candidate_units
                    best_distance = candidate_distance

        if best_id is None or best_route is None:
            break
        selected = waiting.pop(best_id)
        load += selected["size"]
        route = best_route
        credit_units = best_units
        route_distance = best_distance

    return route
