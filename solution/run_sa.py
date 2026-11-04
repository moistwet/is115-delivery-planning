"""Run one reproducible insertion-plus-SA day without changing the simulator."""

import argparse
import json
from pathlib import Path
from typing import List, Optional

from simulator.loaders import day_input_paths
from simulator.simulator import Simulator
from solution.policies.insertion_sa import (
    COOLING_RATE, INITIAL_ACCEPTANCE, INITIAL_TEMPERATURE, ITERATIONS, make_dispatch,
)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--day", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        data = args.data.resolve()
        output = args.output.resolve()
        if output == data or data in output.parents:
            raise ValueError("run output must be outside the input data directory")
        paths = day_input_paths(args.data, args.day)
        output.mkdir(parents=True, exist_ok=True)
        settings = {
            "day": args.day,
            "seed": args.seed,
            "constructor": "solution.policies.greedy_insertion.dispatch",
            "iterations_per_trip": ITERATIONS,
            "initial_temperature": INITIAL_TEMPERATURE,
            "initial_acceptance_for_half_credit_loss": INITIAL_ACCEPTANCE,
            "cooling_rate_per_attempt": COOLING_RATE,
            "objective": "raw route service credit: on-time 1, early/late 0.5",
            "best_route_rule": "greatest credit, then least full-trip distance; seed included",
            "neighbourhood": "uniform random swap of two distinct parcel positions",
            "membership": "fixed within each trip; constructor called fresh per dispatch",
            "random_stream": "dedicated random.Random(seed), initialised once per run",
        }
        (output / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
        with (output / "planning_audit.jsonl").open("w", encoding="utf-8") as audit:
            def record(result):
                audit.write(json.dumps(result, allow_nan=False) + "\n")

            simulator = Simulator(*paths, dispatch_policy=make_dispatch(args.seed, record))
            simulator.run(output / "log.txt")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"Completed {args.day}, seed {args.seed}: {args.output / 'log.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
