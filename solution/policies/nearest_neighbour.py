"""Append the nearest feasible waiting parcel until no candidate can be added."""

from typing import Dict, List, Optional, Tuple

from simulator.models import Parcel, SimulationContext

HUB = "HUB"
CONSTRAINT_TOLERANCE = 1e-9  # Same load/range tolerance as the simulator.


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Choose one trip using directed nearest-neighbour greedy construction.

    Selection and delivery order are built together. At every step, inspect
    all remaining candidates and choose the closest feasible next destination.
    Equal distances are resolved by arrival time, then parcel ID. Capacity
    covers all selected parcels loaded before departure; distance and return
    time include the final leg to the hub. Preferred windows are not part of
    this policy's priority, and a nonempty route is dispatched without waiting.

    The local candidate dictionary supports removal by parcel ID; the route
    list records delivery order. Input snapshots are never modified. For n
    supplied parcels and m eligible candidates, worst-case time per call is
    O(n + m**2), with average O(1) dictionary access, and extra space is O(m).
    """

    distances = context["travel_distance"]
    departure = context["current_time"] + context["departure_delay"]
    waiting = {
        parcel_id: record for parcel_id, record in parcel.items()
        if record["vehicle_assigned"] is None and record["delivery_time"] is None
    }
    route: List[str] = []
    load = 0.0
    travelled = 0.0  # Prefix distance only, excluding the provisional return.
    location = HUB

    while waiting:
        best_id: Optional[str] = None
        best_key: Optional[Tuple[float, float, str]] = None
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

            key = (next_leg, record["arrival_time"], parcel_id)
            if best_key is None or key < best_key:
                best_id = parcel_id
                best_key = key

        if best_id is None:
            break

        # Remove only the chosen candidate; others are reconsidered next step.
        selected = waiting.pop(best_id)
        destination = selected["delivery_location_id"]
        route.append(best_id)
        load += selected["size"]
        travelled += distances[location][destination]
        location = destination

    return route
