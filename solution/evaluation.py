"""Aggregate the fixed seven-policy, twenty-day evaluation without rerunning it."""

import argparse
import csv
import json
import math
import statistics
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


DETERMINISTIC_POLICIES = (
    "baseline", "nearest_neighbour", "window_first_nearest", "greedy_insertion",
    "greedy_insertion_efficiency", "greedy_insertion_protect",
)
SA_POLICY = "insertion_sa"
POLICIES = (*DETERMINISTIC_POLICIES, SA_POLICY)
SEEDS = (0, 1, 2, 3, 4)
DAYS = tuple(f"day_{number:03d}" for number in range(1, 21))
SCOPES = {"all20": DAYS, "development": DAYS[:5], "evaluation": DAYS[5:]}
WEIGHTS = {"0.25": Fraction(1, 4), "0.5": Fraction(1, 2), "0.75": Fraction(3, 4)}
COUNT_FIELDS = (
    "delivered_parcels", "on_time_parcels", "early_parcels", "late_parcels",
    "undelivered_parcels", "number_of_trips",
)
SUMMARY_FIELDS = (
    *COUNT_FIELDS, "credit_units", "completion_rate_pct", "on_time_service_rate_pct",
    "score_b", "total_distance_km", "total_departure_load",
    "average_load_utilisation_pct",
)


def _fraction_json(value: Fraction) -> Dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _fraction(value: Mapping[str, int]) -> Fraction:
    return Fraction(value["numerator"], value["denominator"])


def _number(value: Fraction) -> Any:
    return value.numerator if value.denominator == 1 else float(value)


def _stats(values: List[Optional[float]]) -> Dict[str, Any]:
    observed = [value for value in values if value is not None]
    return {
        "mean": statistics.mean(observed) if observed else None,
        "min": min(observed) if observed else None,
        "max": max(observed) if observed else None,
        "sample_sd": statistics.stdev(observed) if len(observed) > 1 else None,
        "observations": len(observed),
    }


def _score_fields(total: int, delivered: Fraction, on_time: Fraction) -> Dict[str, Any]:
    completion = 100 * delivered / total
    service = 100 * on_time / total
    scores = {
        label: 100 * (on_time + weight * (delivered - on_time)) / total
        for label, weight in WEIGHTS.items()
    }
    return {
        "completion_rate_pct": float(completion),
        "on_time_service_rate_pct": float(service),
        "score_a": {
            "completion_rate_pct": float(completion),
            "on_time_tiebreak_pct": float(service),
        },
        "score_b": float(scores["0.5"]),
        "score_b_sensitivity": {label: float(score) for label, score in scores.items()},
        "exact_scores": {
            "score_a": {
                "completion_rate_pct": _fraction_json(completion),
                "on_time_tiebreak_pct": _fraction_json(service),
            },
            "score_b": _fraction_json(scores["0.5"]),
            "score_b_sensitivity": {
                label: _fraction_json(score) for label, score in scores.items()
            },
        },
    }


def _validate_day(day: str, metrics: Mapping[str, Any], load: float, capacity: float) -> None:
    for field in ("total_parcels", *COUNT_FIELDS):
        value = metrics.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{day}: {field} must be a non-negative integer")
    total, delivered = metrics["total_parcels"], metrics["delivered_parcels"]
    if total <= 0:
        raise ValueError(f"{day}: pooled evaluation requires a positive input denominator")
    if (metrics["on_time_parcels"] + metrics["early_parcels"] + metrics["late_parcels"]
            != delivered or delivered + metrics["undelivered_parcels"] != total):
        raise ValueError(f"{day}: inconsistent parcel outcome counts")
    distance = float(metrics["total_distance_km"])
    if not math.isfinite(distance) or distance < 0 or not math.isfinite(load) or load < 0:
        raise ValueError(f"{day}: distance and departure load must be finite and non-negative")
    trips = metrics["number_of_trips"]
    if (not trips and (delivered or load or distance)) or load > capacity * trips + 1e-8:
        raise ValueError(f"{day}: trip count/load is inconsistent with completed deliveries")
    expected = _score_fields(total, Fraction(delivered), Fraction(metrics["on_time_parcels"]))
    for field in ("completion_rate_pct", "on_time_service_rate_pct", "score_b"):
        if field in metrics and not math.isclose(metrics[field], expected[field], abs_tol=1e-9):
            raise ValueError(f"{day}: saved {field} disagrees with parcel counts")
    if "score_b_sensitivity" in metrics:
        for label, score in expected["score_b_sensitivity"].items():
            if not math.isclose(metrics["score_b_sensitivity"][label], score, abs_tol=1e-9):
                raise ValueError(f"{day}: saved sensitivity score {label} is inconsistent")


def _pooled(daily: Mapping[str, Mapping[str, Any]], loads: Mapping[str, float],
            capacity: float) -> Dict[str, Any]:
    if not daily or set(daily) != set(loads):
        raise ValueError("daily metrics and departure loads must cover the same nonempty day set")
    if not math.isfinite(capacity) or capacity <= 0:
        raise ValueError("vehicle capacity must be finite and positive")
    for day, metrics in daily.items():
        _validate_day(day, metrics, loads[day], capacity)
    total = sum(metrics["total_parcels"] for metrics in daily.values())
    result = {field: sum(metrics[field] for metrics in daily.values()) for field in COUNT_FIELDS}
    result.update({
        "total_parcels": total,
        "credit_units": result["delivered_parcels"] + result["on_time_parcels"],
        "total_distance_km": math.fsum(float(metrics["total_distance_km"]) for metrics in daily.values()),
        "total_departure_load": math.fsum(loads.values()),
    })
    trips = result["number_of_trips"]
    result["average_load_utilisation_pct"] = (
        100 * result["total_departure_load"] / (capacity * trips) if trips else None
    )
    result.update(_score_fields(total, Fraction(result["delivered_parcels"]),
                                Fraction(result["on_time_parcels"])))
    return result


def _daily_summary(daily: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    exact = {day: _fraction(row["exact_scores"]["score_b"]) for day, row in daily.items()}
    minimum = min(exact.values())
    return {
        "mean_daily_score_b": float(sum(exact.values()) / len(exact)),
        "minimum_daily_score_b": float(minimum),
        "worst_days": sorted(day for day, score in exact.items() if score == minimum),
    }


def aggregate_daily(daily: Mapping[str, Mapping[str, Any]], loads: Mapping[str, float],
                    capacity: float) -> Dict[str, Any]:
    """Pool one deterministic policy (or one SA seed) over the supplied days."""

    aggregate = _pooled(daily, loads, capacity)
    exact = aggregate.pop("exact_scores")
    records = {}
    for day in sorted(daily):
        point = _pooled({day: daily[day]}, {day: loads[day]}, capacity)
        day_exact = point.pop("exact_scores")
        records[day] = {"metrics": point, "exact_scores": day_exact}
    return {
        "kind": "deterministic", "aggregation": "pooled_days",
        "aggregate": aggregate, "exact_scores": exact, "daily": records,
        "daily_summary": _daily_summary(records),
    }


def _mean_points(points: List[Mapping[str, Any]]) -> Dict[str, Any]:
    denominators = {point["total_parcels"] for point in points}
    if len(denominators) != 1:
        raise ValueError("SA seeds must have the same input denominator")
    count = len(points)
    total = denominators.pop()
    result = {field: _number(Fraction(sum(point[field] for point in points), count))
              for field in (*COUNT_FIELDS, "credit_units")}
    result["total_parcels"] = total  # Never sum repeated seed inputs.
    for field in ("total_distance_km", "total_departure_load", "average_load_utilisation_pct"):
        result[field] = _stats([point[field] for point in points])["mean"]
    delivered = Fraction(sum(point["delivered_parcels"] for point in points), count)
    on_time = Fraction(sum(point["on_time_parcels"] for point in points), count)
    result.update(_score_fields(total, delivered, on_time))
    return result


def aggregate_seeds(seed_daily: Mapping[int, Mapping[str, Mapping[str, Any]]],
                    seed_loads: Mapping[int, Mapping[str, float]], capacity: float) -> Dict[str, Any]:
    """Average five seed-pooled results, retaining every seed and daily value."""

    if set(seed_daily) != set(SEEDS) or set(seed_loads) != set(SEEDS):
        raise ValueError("SA evaluation requires exactly seeds 0, 1, 2, 3, and 4")
    day_sets = {tuple(sorted(daily)) for daily in seed_daily.values()}
    if len(day_sets) != 1:
        raise ValueError("SA seeds must cover the same days")
    pooled = {seed: aggregate_daily(seed_daily[seed], seed_loads[seed], capacity) for seed in SEEDS}
    points = [pooled[seed]["aggregate"] for seed in SEEDS]
    aggregate = _mean_points(points)
    exact = aggregate.pop("exact_scores")
    records = {}
    for day in sorted(seed_daily[0]):
        day_points = [pooled[seed]["daily"][day]["metrics"] for seed in SEEDS]
        point = _mean_points(day_points)
        day_exact = point.pop("exact_scores")
        records[day] = {
            "metrics": point, "exact_scores": day_exact,
            "per_seed": {str(seed): pooled[seed]["daily"][day]["metrics"] for seed in SEEDS},
        }
    seed_aggregates = {
        str(seed): {
            **pooled[seed]["aggregate"], "exact_scores": pooled[seed]["exact_scores"],
            "daily_scores_b": {
                day: pooled[seed]["daily"][day]["metrics"]["score_b"]
                for day in sorted(seed_daily[seed])
            },
        }
        for seed in SEEDS
    }
    return {
        "kind": "stochastic", "aggregation": "equal_mean_of_five_seed_pooled_results",
        "aggregate": aggregate, "exact_scores": exact, "daily": records,
        "daily_summary": _daily_summary(records), "seed_aggregates": seed_aggregates,
        "seed_summary": {field: _stats([point[field] for point in points]) for field in SUMMARY_FIELDS},
        "seed_sensitivity_summary": {
            label: _stats([point["score_b_sensitivity"][label] for point in points])
            for label in WEIGHTS
        },
    }


def _rank_key(exact: Mapping[str, Any], metric: str, weight: Optional[str] = None) -> Any:
    if metric == "score_a":
        return (_fraction(exact["score_a"]["completion_rate_pct"]),
                _fraction(exact["score_a"]["on_time_tiebreak_pct"]))
    if metric == "score_b":
        return _fraction(exact["score_b"])
    return _fraction(exact["score_b_sensitivity"][weight])


def rank_policies(policies: Mapping[str, Mapping[str, Any]], metric: str = "score_b",
                  weight: Optional[str] = None) -> List[Dict[str, Any]]:
    """Use exact competition ranks: e.g. 1, 2, 2, 4, with no distance tiebreak."""

    if metric not in ("score_a", "score_b", "score_b_sensitivity"):
        raise ValueError("unknown ranking metric")
    if metric == "score_b_sensitivity" and weight not in WEIGHTS:
        raise ValueError("unknown sensitivity weight")
    ordered = sorted(policies, key=lambda name: _rank_key(policies[name]["exact_scores"], metric, weight),
                     reverse=True)
    groups = []
    previous = None
    for position, name in enumerate(ordered, 1):
        key = _rank_key(policies[name]["exact_scores"], metric, weight)
        if not groups or key != previous:
            groups.append({
                "rank": position, "policies": [],
                "score": [float(value) for value in key] if isinstance(key, tuple) else float(key),
                "exact_score": [_fraction_json(value) for value in key] if isinstance(key, tuple)
                else _fraction_json(key),
            })
        groups[-1]["policies"].append(name)
        previous = key
    for group in groups:
        group["policies"].sort()
    return groups


def _paired_daily(policy: Mapping[str, Any], control: Mapping[str, Any]) -> Dict[str, Any]:
    result = {}
    for metric, weight in [("score_a", None), ("score_b", None),
                           *(("score_b_sensitivity", label) for label in WEIGHTS)]:
        counts = {"win": 0, "tie": 0, "loss": 0}
        for day, row in policy["daily"].items():
            left = _rank_key(row["exact_scores"], metric, weight)
            right = _rank_key(control["daily"][day]["exact_scores"], metric, weight)
            counts["win" if left > right else "loss" if left < right else "tie"] += 1
        result[weight if weight is not None else metric] = counts
    return result


def _time(value: str) -> int:
    hour, minute = map(int, value.split(':'))
    return hour * 60 + minute


def _read_run(path: Path, day: str, parcels: Mapping[str, Mapping[str, str]],
              capacity: float) -> tuple:
    metrics = json.loads((path / "metrics.json").read_text())
    events = [json.loads(line) for line in (path / "log.txt").read_text().splitlines() if line.strip()]
    departures = set()
    active = {}
    delivered = set()
    arrivals = []
    planning = []
    loads = []
    outcomes = Counter()
    for event in events:
        kind = event["event_type"]
        if kind == "parcel_arrival":
            arrivals.append(event["parcel_id"])
        elif kind == "dispatch_planning":
            planning.append(event["time"])
        elif kind == "hub_departure":
            key = (event["vehicle_id"], event["trip_id"])
            if key in departures or event["vehicle_id"] in active:
                raise ValueError(f"{path}: duplicate or overlapping trip")
            departures.add(key)
            active[event["vehicle_id"]] = key
        elif kind == "delivery":
            pid = event["parcel_id"]
            key = (event["vehicle_id"], event["trip_id"])
            if pid not in parcels or pid in delivered or active.get(event["vehicle_id"]) != key:
                raise ValueError(f"{path}: invalid delivery identity/trip")
            delivered.add(pid)
            row = parcels[pid]
            loads.append(float(row["size"]))
            delivered_at = float(event["time"])
            classification = ("early" if delivered_at < _time(row["delivery_window_start"])
                              else "late" if delivered_at > _time(row["delivery_window_end"])
                              else "on_time")
            outcomes[classification] += 1
        elif kind == "vehicle_return":
            active.pop(event["vehicle_id"], None)
    if active or Counter(arrivals) != Counter(parcels.keys()) or planning != list(range(480, 1051, 10)):
        raise ValueError(f"{path}: log lacks complete arrivals/planning/returned trips")
    expected_counts = {
        "total_parcels": len(parcels), "delivered_parcels": len(delivered),
        "undelivered_parcels": len(parcels) - len(delivered),
        "on_time_parcels": outcomes["on_time"], "early_parcels": outcomes["early"],
        "late_parcels": outcomes["late"], "number_of_trips": len(departures),
    }
    if any(metrics.get(field) != count for field, count in expected_counts.items()):
        raise ValueError(f"{path}: metric counts do not match its input and log")
    load = math.fsum(loads)
    _validate_day(day, metrics, load, capacity)
    return metrics, load


def _validate_coverage(results: Path) -> None:
    missing = []
    for policy in POLICIES:
        for day in DAYS:
            for seed in SEEDS if policy == SA_POLICY else (None,):
                path = results / policy / day
                if seed is not None:
                    path = path / f"seed_{seed}"
                names = ("log.txt", "metrics.json", "settings.json", "planning_audit.jsonl") if seed is not None else ("log.txt", "metrics.json")
                missing.extend(str(path / name) for name in names if not (path / name).is_file())
    if missing:
        raise ValueError(f"incomplete evaluation matrix: {len(missing)} missing files; first: {missing[0]}")


def build_comparison(results: Path, data: Path) -> Dict[str, Any]:
    """Read the completed matrix; no policy, simulator, or monitor is executed."""

    results, data = Path(results), Path(data)
    _validate_coverage(results)
    capacity = float(json.loads((data / "config.json").read_text())["capacity"])
    metrics = {policy: {} for policy in DETERMINISTIC_POLICIES}
    loads = {policy: {} for policy in DETERMINISTIC_POLICIES}
    sa_metrics = {seed: {} for seed in SEEDS}
    sa_loads = {seed: {} for seed in SEEDS}
    settings_reference = None
    for day in DAYS:
        with (data / "demand" / f"{day}.csv").open(newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        parcels = {row["parcel_id"]: row for row in rows}
        if len(parcels) != len(rows):
            raise ValueError(f"{day}: duplicate input parcel IDs")
        for policy in DETERMINISTIC_POLICIES:
            metrics[policy][day], loads[policy][day] = _read_run(results / policy / day, day, parcels, capacity)
        for seed in SEEDS:
            path = results / SA_POLICY / day / f"seed_{seed}"
            settings = json.loads((path / "settings.json").read_text())
            if settings.pop("day", None) != day or settings.pop("seed", None) != seed:
                raise ValueError(f"{path}: SA setting day/seed does not match its folder")
            if settings_reference is None:
                settings_reference = settings
            elif settings_reference != settings:
                raise ValueError("SA settings differ across days/seeds")
            sa_metrics[seed][day], sa_loads[seed][day] = _read_run(path, day, parcels, capacity)
    report = {
        "schema_version": 1,
        "days": list(DAYS), "policies": list(POLICIES), "seeds": list(SEEDS),
        "metric_definitions": {
            "main_score": "Pooled B = 50 * sum(delivered + on_time) / sum(input parcels).",
            "scoring_a": "Pooled completion, then on-time service rate only on exact completion ties.",
            "ranking": "Exact Fraction competition co-ranks (1,2,2,4); B has no distance tiebreak.",
            "sa_point_estimate": "Equal mean of five seed-level pooled results; input parcels counted once.",
            "sa_rng": "One seeded stream within each one-day simulation; seed reset for each new day.",
            "sa_scoring_a": "Mean selected-scope delivered total, then mean on-time total, at the common input denominator.",
            "utilisation": "Within a policy/seed, sum departure loads / (capacity * sum trips); SA reports the mean of seed utilisations.",
            "undefined": "Undefined utilisation is null; seed statistics omit null observations.",
            "daily_outcomes": "Paired same-day comparisons; SA uses its expected mean daily credit/counts, not seed win totals.",
            "scope_caution": "All20 includes development cases; evaluation006-020 is reported separately. Seed replications are not independent input days.",
        },
        "sa_settings": settings_reference,
        "scopes": {},
    }
    for scope, days in SCOPES.items():
        policies = {
            policy: aggregate_daily({day: metrics[policy][day] for day in days},
                                    {day: loads[policy][day] for day in days}, capacity)
            for policy in DETERMINISTIC_POLICIES
        }
        policies[SA_POLICY] = aggregate_seeds(
            {seed: {day: sa_metrics[seed][day] for day in days} for seed in SEEDS},
            {seed: {day: sa_loads[seed][day] for day in days} for seed in SEEDS}, capacity,
        )
        totals = {policy["aggregate"]["total_parcels"] for policy in policies.values()}
        if len(totals) != 1:
            raise ValueError(f"{scope}: policies have different input denominators")
        for policy in policies.values():
            policy["daily_outcomes_vs"] = {
                control: _paired_daily(policy, policies[control])
                for control in ("baseline", "window_first_nearest", "greedy_insertion")
            }
        report["scopes"][scope] = {
            "days": list(days), "total_parcels": totals.pop(), "policies": policies,
            "rankings": {
                "score_a": rank_policies(policies, "score_a"),
                "score_b": rank_policies(policies, "score_b"),
                "score_b_sensitivity": {
                    label: rank_policies(policies, "score_b_sensitivity", label) for label in WEIGHTS
                },
            },
        }
    return report


def write_reports(report: Mapping[str, Any], results: Path) -> None:
    """Write full-precision JSON plus compact aggregate and daily CSV tables."""

    results = Path(results)
    (results / "comparison.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    summaries, daily_rows = [], []
    for scope, block in report["scopes"].items():
        ranks = {
            metric: {name: row["rank"] for row in block["rankings"][metric] for name in row["policies"]}
            for metric in ("score_a", "score_b")
        }
        for name, policy in block["policies"].items():
            point = policy["aggregate"]
            exact = policy["exact_scores"]["score_b"]
            seed = policy.get("seed_summary", {}).get("score_b", {})
            summaries.append({
                "scope": scope, "policy": name, "kind": policy["kind"], "days": len(block["days"]),
                **{field: point[field] for field in ("total_parcels", *COUNT_FIELDS,
                    "completion_rate_pct", "on_time_service_rate_pct", "score_b",
                    "total_distance_km", "total_departure_load", "average_load_utilisation_pct")},
                "score_a_rank": ranks["score_a"][name], "score_b_rank": ranks["score_b"][name],
                "score_b_exact_numerator": exact["numerator"], "score_b_exact_denominator": exact["denominator"],
                "score_b_seed_min": seed.get("min"), "score_b_seed_max": seed.get("max"),
                "score_b_seed_sample_sd": seed.get("sample_sd"),
                "mean_daily_score_b": policy["daily_summary"]["mean_daily_score_b"],
                "minimum_daily_score_b": policy["daily_summary"]["minimum_daily_score_b"],
                "worst_days": ";".join(policy["daily_summary"]["worst_days"]),
            })
            for day, daily in policy["daily"].items():
                points = [("", "seed_mean" if policy["kind"] == "stochastic" else "single", daily["metrics"])]
                points += [(seed, "seed", metrics) for seed, metrics in daily.get("per_seed", {}).items()]
                for seed, statistic, metrics in points:
                    daily_rows.append({
                        "scope": scope, "policy": name, "day": day,
                        "seed": seed, "statistic": statistic,
                        **{field: metrics[field] for field in ("total_parcels", *COUNT_FIELDS,
                            "completion_rate_pct", "on_time_service_rate_pct", "score_b",
                            "total_distance_km", "average_load_utilisation_pct")},
                    })
    for name, rows in (("summary.csv", summaries), ("daily_scores.csv", daily_rows)):
        with (results / name).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("results/full_evaluation"))
    parser.add_argument("--data", type=Path, default=Path("data"))
    args = parser.parse_args(argv)
    try:
        report = build_comparison(args.results, args.data)
        write_reports(report, args.results)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"Evaluation reports: {args.results / 'comparison.json'}, summary.csv, daily_scores.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
