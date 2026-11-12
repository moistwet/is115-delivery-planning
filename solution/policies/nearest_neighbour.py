"""Append the nearest feasible waiting parcel until no candidate can be added."""

from typing import Dict, List, Optional, Tuple

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import CONSTRAINT_TOLERANCE, HUB


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Append the nearest feasible parcel, breaking ties by arrival then ID.

    Capacity applies at departure, and range and cutoff include the hub return.
    Preferred windows do not affect selection and no waiting is introduced.
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
        best_parcel_id: Optional[str] = None
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
