"""Prefer in-window deliveries, choosing the nearest feasible parcel per group."""

from typing import Dict, List, Optional, Tuple

from simulator.models import Parcel, SimulationContext

HUB = "HUB"
CONSTRAINT_TOLERANCE = 1e-9  # Same load/range tolerance as the simulator.


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Build one trip with an in-window-first nearest-neighbour priority.

    Hard feasibility is identical to nearest_neighbour: all selected parcels
    must fit at departure, and the complete trip must fit the range and return
    deadline. Among feasible candidates, prefer those whose projected delivery
    times are inside their inclusive preferred windows. Within either group,
    choose the shortest next leg, then earliest arrival, then parcel ID.

    Projected time includes preparation once and the full planned travel prefix.
    Recompute every candidate after each append. Outside-window deliveries stay
    eligible; there is no intentional waiting or deadline-urgency priority.
    Inputs are read-only. For n supplied parcels and m eligible candidates,
    worst-case time is O(n + m**2), extra space O(m), assuming average constant
    dictionary access. The policy has no tunable parameters.
    """

    distances = context["travel_distance"]
    departure = context["current_time"] + context["departure_delay"]
    waiting = {
        parcel_id: record for parcel_id, record in parcel.items()
        if record["vehicle_assigned"] is None and record["delivery_time"] is None
    }
    route: List[str] = []
    load = 0.0
    travelled = 0.0  # Prefix only; a candidate replaces the provisional return.
    location = HUB

    while waiting:
        best_id: Optional[str] = None
        best_key: Optional[Tuple[bool, float, float, str]] = None
        for parcel_id, record in waiting.items():
            if load + record["size"] > context["capacity"] + CONSTRAINT_TOLERANCE:
                continue
            destination = record["delivery_location_id"]
            next_leg = distances[location][destination]
            round_trip = travelled + next_leg + distances[destination][HUB]
            if round_trip > context["max_trip_distance_km"] + CONSTRAINT_TOLERANCE:
                continue
            if departure + round_trip > context["return_cutoff"]:
                continue

            estimated_delivery = departure + travelled + next_leg
            outside_window = not (
                record["delivery_window_start"]
                <= estimated_delivery
                <= record["delivery_window_end"]
            )
            key = (outside_window, next_leg, record["arrival_time"], parcel_id)
            if best_key is None or key < best_key:
                best_id = parcel_id
                best_key = key

        if best_id is None:
            break

        selected = waiting.pop(best_id)
        destination = selected["delivery_location_id"]
        route.append(best_id)
        load += selected["size"]
        travelled += distances[location][destination]
        location = destination

    return route
