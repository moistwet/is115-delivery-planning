"""Prefer in-window deliveries, choosing the nearest feasible parcel per group."""

from typing import Dict, List, Optional, Tuple

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import CONSTRAINT_TOLERANCE, HUB


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Append an in-window feasible parcel before an outside-window one.

    Further ties use next-leg distance, arrival and parcel ID. Projected times
    include preparation and the route prefix; departure capacity, full range
    and return cutoff remain hard constraints, with no intentional waiting.
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
        best_parcel_id: Optional[str] = None
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
                best_parcel_id = parcel_id
                best_key = key

        if best_parcel_id is None:
            break

        selected = waiting.pop(best_parcel_id)
        destination = selected["delivery_location_id"]
        route.append(best_parcel_id)
        load += selected["size"]
        travelled += distances[location][destination]
        location = destination

    return route
