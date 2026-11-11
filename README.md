# IS115 Last-Mile Delivery Planning

This project compares delivery dispatch policies using the supplied simulator and 20 days of parcel data. The report recommends window-first nearest neighbour based on the weighted delivery service score.

Python 3.9 or later and the standard library are required. Run the commands below from the project directory.

## Project files

- `data/` contains the parcel, distance and vehicle inputs.
- `simulator/` runs the delivery simulation.
- `solution/policies/` contains the baseline and dispatch policies. Shared functions are in `helpers.py`.
- `solution/performance_monitor.py` calculates the performance metrics.
- `results/` contains the saved logs and metrics for the experiments.
- `IS115_Project_Report.pdf` contains the report in the submission package.

## Run one policy on one day

Choose a policy from the table below and replace `baseline` in the command. Choose a new output directory each time to keep the saved results.

| Policy | Module name |
| --- | --- |
| Baseline | `baseline` |
| Nearest feasible neighbour | `nearest_neighbour` |
| Window-first nearest neighbour | `window_first_nearest` |
| Time-window greedy insertion | `greedy_insertion` |
| Slide-style greedy insertion | `lecture_insertion` |
| Efficiency insertion | `greedy_insertion_efficiency` |
| Protection insertion | `greedy_insertion_protect` |

```bash
python3 -m simulator --policy solution.policies.baseline \
  --data data --day day_001 --output results/reproduction/baseline/day_001

python3 -m solution.performance_monitor \
  --data data --day day_001 --log results/reproduction/baseline/day_001/log.txt
```

The simulator writes `log.txt` in the output directory. The performance monitor writes `metrics.json` beside it.

## Run the five report policies across all 20 days

The following commands create a fresh `results/reproduction_all/` directory. Choose another name if it already exists.

```bash
for policy in baseline nearest_neighbour window_first_nearest greedy_insertion lecture_insertion; do
  for number in $(seq -w 1 20); do
    day="day_0$number"
    output="results/reproduction_all/$policy/$day"
    python3 -m simulator --policy "solution.policies.$policy" \
      --data data --day "$day" --output "$output" || exit 1
    python3 -m solution.performance_monitor \
      --data data --day "$day" --log "$output/log.txt" || exit 1
  done
done
```

## Performance measure

Score B awards 1 point for a delivery within its preferred window, 0.5 for an early or late delivery, and 0 for an undelivered parcel. The score is the total points divided by all input parcels, multiplied by 100. Overall results pool parcel counts across the 20 days.

The main saved results are in `results/full_evaluation_distance_optimised/` and `results/lecture_insertion/`. The report explains the policy comparisons and recommendation.
