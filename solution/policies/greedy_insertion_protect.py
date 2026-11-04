"""Independent greedy insertion breaking gain ties by fewer on-time losses."""

from typing import Dict, List

from simulator.models import Parcel, SimulationContext
from ._insertion_variants import build_route


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Start empty, maximising gain before protecting existing on-time parcels.

    Equal net credit gains prefer fewer currently on-time parcel IDs becoming
    early/late, then smallest added full-trip distance, arrival, ID and position.
    Protection is a tiebreak, not a hard constraint. A greater-gain insertion can
    still change an existing on-time delivery to early or late. Final Score B
    and the strictly positive-gain stopping rule remain unchanged.
    """

    return build_route(parcel, context, "protect")
