"""Run the frozen seven-policy, twenty-day experiment in a new output folder."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Optional, List

from solution.policies.insertion_sa import (
    COOLING_RATE, INITIAL_ACCEPTANCE, INITIAL_TEMPERATURE, ITERATIONS,
)

POLICIES = (
    "baseline", "nearest_neighbour", "window_first_nearest", "greedy_insertion",
    "greedy_insertion_efficiency", "greedy_insertion_protect",
)
DAYS = tuple(f"day_{number:03d}" for number in range(1, 21))
SEEDS = (0, 1, 2, 3, 4)


def _hashes(paths, root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(paths))}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, required=True,
                        help="new experiment directory; existing paths are refused")
    parser.add_argument("--workers", type=int, default=4,
                        help="concurrent independent processes (default: 4)")
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= 16:
        parser.error("workers must be between 1 and 16")
    root = Path.cwd().resolve()
    data = args.data.resolve()
    output = args.output.resolve()
    if output.exists():
        parser.error("output already exists; choose a new directory to preserve prior results")
    if output == data or data in output.parents:
        parser.error("output must be outside the input data directory")
    if root not in data.parents or root not in output.parents:
        parser.error("data and output must be inside the project root")
    required = [data / "config.json", data / "dist.csv"] + [
        data / "demand" / (day + ".csv") for day in DAYS
    ]
    if not all(path.is_file() for path in required):
        parser.error("the complete twenty-day input set is required")

    frozen = required + list((root / "simulator").glob("*.py")) + list(
        (root / "solution/policies").glob("*.py")
    ) + [root / "solution/__init__.py", root / "solution/performance_monitor.py",
         root / "solution/run_sa.py", Path(__file__).resolve()]
    old_results = [p for p in (root / "results").rglob("*") if p.is_file()]
    manifest = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "cwd": str(root), "python": platform.python_version(),
        "python_executable": sys.executable,
        "scope": "Fresh complete matrix: six deterministic policies on twenty days and five SA seeds on each day, 220 day-runs.",
        "status": "running", "workers": args.workers,
        "days": list(DAYS), "deterministic_policies": list(POLICIES),
        "sa_seeds": list(SEEDS), "expected_runs": 220,
        "settings": {
            "main_score": "Pooled B = 50 * sum(delivered + on_time) / sum(input parcels)",
            "outside_window_credit": 0.5, "sensitivity_weights": [0.25, 0.5, 0.75],
            "score_a": "Pooled completion first, on-time service breaks exact completion ties; SA uses mean seed counts.",
            "score_b_ties": "Co-ranked; no distance tiebreak.",
            "sa_iterations_per_trip": ITERATIONS,
            "sa_initial_temperature": INITIAL_TEMPERATURE,
            "sa_initial_acceptance_for_half_credit_loss": INITIAL_ACCEPTANCE,
            "sa_cooling_rate": COOLING_RATE,
            "sa_random_stream": "Dedicated Random(seed), reset once per independent day-run and continued across its dispatches.",
            "sa_aggregation": "Pool each seed across days, then mean/range/sample SD across seeds 0–4; never select best seed.",
            "development_days": list(DAYS[:5]), "evaluation_days": list(DAYS[5:]),
            "tuning": "No implementation or parameter changes before or during this evaluation.",
        },
        "sha256_before": _hashes(frozen, root),
        "reference_results_sha256": _hashes(old_results, root),
        "runs": [],
    }
    output.mkdir(parents=True)
    manifest_path = output / "run_manifest.json"

    def save():
        temporary = manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        temporary.replace(manifest_path)

    save()
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

    def run_one(policy, day, seed):
        folder = output / policy / day
        if seed is not None:
            folder = folder / f"seed_{seed}"
            command = [sys.executable, "-m", "solution.run_sa", "--data", str(args.data),
                       "--day", day, "--seed", str(seed), "--output", str(folder)]
        else:
            command = [sys.executable, "-m", "simulator", "--policy",
                       "solution.policies." + policy, "--data", str(args.data),
                       "--day", day, "--output", str(folder)]
        record = {"policy": policy, "day": day, "seed": seed,
                  "output_dir": str(folder.relative_to(root)), "steps": []}
        commands = [("simulation", command), ("metrics", [
            sys.executable, "-m", "solution.performance_monitor", "--data", str(args.data),
            "--day", day, "--log", str(folder / "log.txt"),
        ])]
        for stage, command in commands:
            start = time.perf_counter()
            process = subprocess.run(command, cwd=root, env=environment,
                                     capture_output=True, text=True)
            record["steps"].append({"stage": stage, "command": command,
                                    "returncode": process.returncode,
                                    "elapsed_seconds": time.perf_counter() - start,
                                    "stdout": process.stdout.strip(),
                                    "stderr": process.stderr.strip()})
            if process.returncode:
                break
        record["success"] = len(record["steps"]) == 2 and all(
            step["returncode"] == 0 for step in record["steps"]
        )
        record["sha256"] = _hashes([p for p in folder.glob("*") if p.is_file()], root)
        return record

    jobs = [(policy, day, None) for policy in POLICIES for day in DAYS]
    jobs += [("insertion_sa", day, seed) for day in DAYS for seed in SEEDS]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, *job) for job in jobs]
        for future in as_completed(futures):
            record = future.result()
            manifest["runs"].append(record)
            save()
            count = len(manifest["runs"])
            if count % 10 == 0 or not record["success"]:
                print(f"Completed {count}/220; latest {record['policy']} {record['day']} seed={record['seed']}; success={record['success']}", flush=True)
    manifest["runs"].sort(key=lambda r: (r["policy"], r["day"], -1 if r["seed"] is None else r["seed"]))
    manifest["sha256_after"] = _hashes(frozen, root)
    manifest["sources_and_inputs_unchanged"] = manifest["sha256_before"] == manifest["sha256_after"]
    manifest["reference_results_unchanged"] = manifest["reference_results_sha256"] == _hashes(old_results, root)
    manifest["elapsed_seconds"] = time.perf_counter() - started
    successful = all(r["success"] for r in manifest["runs"]) and len(manifest["runs"]) == 220
    manifest["status"] = "complete" if successful else "failed"
    manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    save()
    valid = successful and manifest["sources_and_inputs_unchanged"] and manifest["reference_results_unchanged"]
    print(f"Full evaluation {manifest['status']}: 220 runs; integrity={valid}; {manifest_path}")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
