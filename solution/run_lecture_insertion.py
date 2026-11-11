"""Reproduce the lecture-style policy on all 20 days in a new output directory."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from solution.evaluation import _paired_daily, _read_run, aggregate_daily
from solution.run_evaluation import DAYS


POLICY = "solution.policies.lecture_insertion"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path,
                        default=Path("results/full_evaluation_distance_optimised"))
    args = parser.parse_args()
    data = args.data.resolve()
    output = args.output.resolve()
    if output == data or data in output.parents:
        parser.error("the output directory must be outside the input directory")
    if output.exists():
        parser.error("the output directory must be new")

    capacity = json.loads((data / "config.json").read_text())["capacity"]
    output.mkdir(parents=True)

    def run_day(day):
        run_dir = output / day
        for command in (
            ("simulator", "--policy", POLICY, "--data", str(data), "--day", day,
             "--output", str(run_dir)),
            ("solution.performance_monitor", "--data", str(data), "--day", day,
             "--log", str(run_dir / "log.txt")),
        ):
            subprocess.run([sys.executable, "-m", *command], check=True,
                           stdout=subprocess.DEVNULL)
        with (data / "demand" / (day + ".csv")).open(newline="", encoding="utf-8-sig") as stream:
            parcels = {row["parcel_id"]: row for row in csv.DictReader(stream)}
        metrics, load = _read_run(run_dir, day, parcels, capacity)
        reference, reference_load = _read_run(args.reference / "greedy_insertion" / day,
                                              day, parcels, capacity)
        return day, metrics, load, reference, reference_load

    with ThreadPoolExecutor(max_workers=4) as workers:
        runs = list(workers.map(run_day, DAYS))

    lecture = aggregate_daily({day: metrics for day, metrics, _, _, _ in runs},
                              {day: load for day, _, load, _, _ in runs}, capacity)
    original = aggregate_daily({day: metrics for day, _, _, metrics, _ in runs},
                               {day: load for day, _, _, _, load in runs}, capacity)
    inputs = [data / "config.json", data / "dist.csv"] + [
        data / "demand" / (day + ".csv") for day in DAYS
    ]
    sources = [Path(__file__), Path("solution/policies/lecture_insertion.py"),
               Path("solution/policies/greedy_insertion.py"), Path("solution/policies/helpers.py"),
               Path("solution/performance_monitor.py"), Path("solution/evaluation.py")]
    sources.extend(sorted(Path("simulator").glob("*.py")))

    def hashes(paths, relative_to):
        return {str(path.resolve().relative_to(relative_to)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths}

    report = {
        "policy": POLICY,
        "days": list(DAYS),
        "python": sys.version.split()[0],
        "lecture_insertion": lecture,
        "time_window_insertion": original,
        "paired_daily": _paired_daily(lecture, original),
        "input_sha256": hashes(inputs, data),
        "source_sha256": hashes(sources, Path.cwd()),
        "output_sha256": hashes(sorted(output.glob("day_*/*")), output),
    }
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Completed {len(runs)} days. Pooled Score B: {lecture['aggregate']['score_b']:.6f}")


if __name__ == "__main__":
    main()
