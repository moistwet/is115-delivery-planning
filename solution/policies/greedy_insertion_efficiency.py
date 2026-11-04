"""Independent greedy insertion ranked by credit gain per extra trip kilometre."""

from typing import Dict, List

from simulator.models import Parcel, SimulationContext
from ._insertion_variants import build_route


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Start empty and apply only the travel-efficiency ranking change.

    Positive-gain insertions with nonpositive added distance have priority,
    ordered by greatest gain then smallest added distance. Otherwise maximise
    net credit gain per added full-trip km, then gain, then smallest distance.
    Final ties use arrival, ID and insertion position. Credit remains 1/0.5;
    this ratio guides planning and does not change final Score B.
    """

    return build_route(parcel, context, "efficiency")
