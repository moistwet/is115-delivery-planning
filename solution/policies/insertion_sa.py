"""Original greedy insertion followed by feasible swap simulated annealing."""

import math
import random
from typing import Any, Callable, Dict, List, Optional

from simulator.models import Parcel, SimulationContext
from .greedy_insertion import dispatch as greedy_dispatch
from .helpers import CONSTRAINT_TOLERANCE, _evaluate_route

DEFAULT_SEED = 0
ITERATIONS = 2000
COOLING_RATE = 0.995
INITIAL_ACCEPTANCE = 0.30
# Losing one on-time delivery loses 0.5 raw credit for fixed membership.
INITIAL_TEMPERATURE = -0.5 / math.log(INITIAL_ACCEPTANCE)
Audit = Callable[[Dict[str, Any]], None]


def simulated_annealing(
    initial_route: List[str],
    parcel: Dict[str, Parcel],
    context: SimulationContext,
    *,
    rng: random.Random,
    temperature: float = INITIAL_TEMPERATURE,
    cooling_rate: float = COOLING_RATE,
    iterations: int = ITERATIONS,
    audit: Optional[Audit] = None,
) -> List[str]:
    """Search feasible fixed-membership orders by swapping two route positions.

    Equal or better service credit is accepted; worse credit follows the
    temperature probability. The saved best prefers credit, then less distance.
    Every proposal rechecks directed timing, range and return feasibility.
    """

    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")
    if not math.isfinite(cooling_rate) or not 0 < cooling_rate < 1:
        raise ValueError("cooling_rate must be strictly between zero and one")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 0:
        raise ValueError("iterations must be a non-negative integer")

    current = list(initial_route)
    if len(set(current)) != len(current):
        raise ValueError("initial route contains duplicate parcel IDs")
    load = 0.0
    for parcel_id in current:
        if parcel_id not in parcel:
            raise ValueError(f"unknown initial parcel: {parcel_id!r}")
        record = parcel[parcel_id]
        if (record["vehicle_assigned"] is not None
                or record["delivery_time"] is not None
                or record["arrival_time"] > context["current_time"]):
            raise ValueError(f"initial parcel is not eligible: {parcel_id!r}")
        load += record["size"]
    if load > context["capacity"] + CONSTRAINT_TOLERANCE:
        raise ValueError("initial route exceeds departure capacity")

    departure = context["current_time"] + context["departure_delay"]
    evaluated = _evaluate_route(current, parcel, context, departure) if current else (0, 0.0)
    if evaluated is None:
        raise ValueError("initial route violates range or return cutoff")
    current_units, current_distance = evaluated
    best = current[:]
    best_units = current_units
    best_distance = current_distance
    initial_units = current_units
    initial_distance = current_distance
    initial_temperature = temperature
    attempted = infeasible = accepted_better = accepted_equal = accepted_worse = 0

    if len(current) >= 2:
        for _ in range(iterations):
            # Stop if finite-precision cooling underflows to zero. The fixed
            # 2,000-attempt schedule stays positive and does not reach this guard.
            if temperature == 0.0:
                break
            candidate_route = current[:]
            i, j = rng.sample(range(len(candidate_route)), 2)
            candidate_route[i], candidate_route[j] = candidate_route[j], candidate_route[i]
            attempted += 1
            candidate_evaluation = _evaluate_route(
                candidate_route, parcel, context, departure,
            )
            if candidate_evaluation is None:
                infeasible += 1
            else:
                candidate_units, candidate_distance = candidate_evaluation
                delta_units = candidate_units - current_units
                accept = delta_units >= 0 or rng.random() < math.exp(
                    (delta_units / 2.0) / temperature
                )
                if accept:
                    if delta_units > 0:
                        accepted_better += 1
                    elif delta_units == 0:
                        accepted_equal += 1
                    else:
                        accepted_worse += 1
                    current = candidate_route
                    current_units = candidate_units
                    current_distance = candidate_distance
                    if (current_units, -current_distance) > (best_units, -best_distance):
                        best = current[:]
                        best_units = current_units
                        best_distance = current_distance
            temperature *= cooling_rate

    if audit is not None:
        audit({
            "initial_route": list(initial_route),
            "best_route": best[:],
            "initial_credit_units": initial_units,
            "best_credit_units": best_units,
            "initial_distance_km": initial_distance,
            "best_distance_km": best_distance,
            "last_current_credit_units": current_units,
            "last_current_distance_km": current_distance,
            "attempts": attempted,
            "infeasible_proposals": infeasible,
            "accepted_better": accepted_better,
            "accepted_equal": accepted_equal,
            "accepted_worse": accepted_worse,
            "initial_temperature": initial_temperature,
            "final_temperature": temperature,
        })
    return best


def make_dispatch(seed: int = DEFAULT_SEED, audit: Optional[Audit] = None) -> Callable:
    """Create one dedicated random stream, used for an entire simulation run."""

    rng = random.Random(seed)

    def policy(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
        initial = greedy_dispatch(parcel, context)

        def record(result: Dict[str, Any]) -> None:
            if audit is not None:
                audit({
                    "planning_time": context["current_time"],
                    "vehicle_id": context["vehicle_id"],
                    **result,
                })

        return simulated_annealing(
            initial, parcel, context, rng=rng,
            audit=record if audit is not None else None,
        )

    return policy


_default_dispatch = make_dispatch()


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Simulator policy entry point; separate CLI processes default to seed 0."""

    return _default_dispatch(parcel, context)
