"""Compare saved pre-optimisation constructors with current code on fixed snapshots.

Run from the project root with:
    PYTHONPATH=. python3 scripts/benchmark_insertion_distance.py --output results/benchmark_rerun
This benchmark uses only supplied data, does not edit old results, and runs
versions sequentially with alternating order. It measures constructor time,
not simulator time or SA's 2,000-swap search.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import time

from simulator.simulator import Simulator
from solution.policies import greedy_insertion, helpers


REFERENCE = Path("results/insertion_distance_optimisation/reference_source")
REPEATS = 5


def load_reference(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new benchmark output directory")
    output = parser.parse_args().output.resolve()
    if output.exists():
        parser.error("output already exists; choose a new directory to preserve prior results")
    data = Path("data").resolve()
    if output == data or data in output.parents:
        parser.error("output must be outside the input data directory")
    output.mkdir(parents=True)

    old_gi = load_reference("reference_gi", REFERENCE / "greedy_insertion.py")
    old_variants = load_reference("reference_variants", REFERENCE / "_insertion_variants.py")
    snapshots = []
    collection = output / "benchmark_collection"
    for day in ("day_001", "day_010", "day_020"):
        candidates = []

        def collect(parcels, context):
            route = old_gi.dispatch(parcels, context)
            if len(route) >= 2:
                candidates.append((day, parcels, context))
            return route

        simulator = Simulator(Path("data/demand") / (day + ".csv"),
                              "data/dist.csv", "data/config.json", dispatch_policy=collect)
        simulator.run(collection / day / "log.txt")
        # Twelve evenly spaced nonempty-trip decisions, covering early and late planning.
        indices = sorted({i * (len(candidates) - 1) // 11 for i in range(12)})
        snapshots.extend(candidates[i] for i in indices)

    constructors = {
        "greedy_insertion": (old_gi.dispatch, greedy_insertion.dispatch),
        "greedy_insertion_efficiency": (
            lambda p, c: old_variants.build_route(p, c, "efficiency"),
            lambda p, c: helpers.build_route(p, c, "efficiency")),
        "greedy_insertion_protect": (
            lambda p, c: old_variants.build_route(p, c, "protect"),
            lambda p, c: helpers.build_route(p, c, "protect")),
    }
    report = {
        "method": "Identical fixed dispatch snapshots; one warmup and five sequential measured passes per version. Order alternates each pass. Median elapsed constructor time; no simulator or file IO inside timed sections.",
        "python": platform.python_version(), "platform": platform.platform(),
        "repeats": REPEATS,
        "snapshots": [{"day": day, "planning_time": c["current_time"],
                       "vehicle_id": c["vehicle_id"], "supplied_parcels": len(p),
                       "eligible_parcels": sum(r["vehicle_assigned"] is None and r["delivery_time"] is None
                                               for r in p.values())}
                      for day, p, c in snapshots],
        "results": {},
    }
    for policy, (before, after) in constructors.items():
        expected = [before(p, c) for _, p, c in snapshots]
        assert [after(p, c) for _, p, c in snapshots] == expected, policy
        durations = {"before": [], "after": []}
        for repeat in range(REPEATS):
            versions = [("before", before), ("after", after)]
            if repeat % 2:
                versions.reverse()
            for label, constructor in versions:
                start = time.perf_counter()
                routes = [constructor(p, c) for _, p, c in snapshots]
                elapsed = time.perf_counter() - start
                assert routes == expected, (policy, repeat, label)
                durations[label].append(elapsed)
        old_median = statistics.median(durations["before"])
        new_median = statistics.median(durations["after"])
        report["results"][policy] = {
            "routes_identical": True, "seconds": durations,
            "before_median_seconds": old_median, "after_median_seconds": new_median,
            "elapsed_reduction_pct": 100 * (old_median - new_median) / old_median,
            "speedup_ratio": old_median / new_median,
        }
        print(policy, json.dumps(report["results"][policy]), flush=True)
    sources = [Path(__file__), Path(greedy_insertion.__file__), Path(helpers.__file__),
               *sorted(REFERENCE.glob("*.py"))]
    report["source_sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    (output / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
