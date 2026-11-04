# IS115 Last-Mile Delivery Planning

**For the latest complete days 001–020 results, open [results/full_evaluation_distance_optimised/](results/full_evaluation_distance_optimised/).** Each of its seven policy folders contains all 20 days; simulated annealing additionally has seeds 0–4 within each day. The [original full evaluation](results/full_evaluation/) is preserved. Other results folders retain earlier development experiments, often limited to days 001–005.

Python 3.9+ and the standard library are sufficient; no dependency installation is required. Run the commands below from the project root. The implemented policies are the supplied baseline, nearest feasible neighbour, window-first nearest feasible neighbour, original greedy insertion, two separately modified insertion variants, and insertion plus simulated annealing. See [the project plan and decision record](docs/Project_Plan_and_Decisions.docx) for the agreed evaluation approach.

The current [project report](docs/IS115_Project_Report.docx) contains eight main pages plus two reference pages. It covers the baseline, nearest neighbour, window-first nearest, original insertion and protection insertion, with four explanatory diagrams and two analytical charts. The findings use all 20 supplied days and recommend window-first nearest for pooled Score B, while discussing its distance trade-off, daily losses to insertion and sensitivity to outside-window credit.

The worked example is retained in [Algorithm_Worked_Example.json](docs/Algorithm_Worked_Example.json), the numerical report evidence in [Report_Results_Evidence.json](docs/Report_Results_Evidence.json), and selected useful AI prompt texts in [Selected_AI_Prompts.json](docs/Selected_AI_Prompts.json). [Report_Drafting_Decisions.json](docs/Report_Drafting_Decisions.json) records the chosen scope and design. The Rubik and Noto Sans fonts are embedded in the report. The earlier [opening](docs/IS115_Project_Report_Opening_Draft.docx), [methods](docs/IS115_Project_Report_Methods_Draft.docx) and [version 0.2](docs/archive/IS115_Project_Report_v0_2.docx) drafts remain available. All seven explored policy implementations and their experiment outputs are retained in the project. No submission ZIP has been assembled yet.

## Insertion distance optimisation — 4 November 2026

Original insertion, efficiency insertion and protection insertion now update trial distances by replacing one directed edge: `new_total = saved_total + d(A,B) + d(B,C) - d(A,C)`, where B is inserted between A and C. The hub acts as the neighbour at either end. Possible winners, close numerical comparisons, zero-cost moves and hard-constraint boundaries receive a canonical full-distance recheck. Closeness only triggers recalculation; ranking and feasibility rules are unchanged. Delivery times and window credits are still replayed in order. SA uses the updated original insertion constructor; its swap search still evaluates complete routes.

All 103 unit tests pass, including eight distance-update cases. A fresh 220-run matrix reproduces all 640 original run outputs byte for byte, including logs, metrics, SA settings and SA planning audits. The aggregate JSON and both CSV files are also byte-identical. See [validation.json](results/insertion_distance_optimisation/validation.json), the [new run manifest](results/full_evaluation_distance_optimised/run_manifest.json), and the [latest score summary](results/full_evaluation_distance_optimised/summary.csv). The optimisation preserved old results, supplied inputs, simulator and baseline. The current report includes the distance update, its controlled benchmark and the unchanged service results.

This reduces repeated computation without changing the worst-case time bound `O(n + m*(k+1)^3)` or space bound `O(m+k)`. The separate [benchmark](results/insertion_distance_optimisation/benchmark.json) compares archived and current constructors on identical snapshots, with one warmup, five measured passes, alternating version order and median timings. On 36 snapshots from days 001, 010 and 020, median constructor time fell by 19.9% for original insertion, 19.9% for efficiency insertion and 17.6% for protection insertion. These are measurements on this machine and workload. It does not measure simulator runtime or SA search speed. To reproduce it from the project root:

```bash
PYTHONPATH=. python3 scripts/benchmark_insertion_distance.py
```

The pre-change source is retained in `results/insertion_distance_optimisation/reference_source/`. The complete matrix can be reproduced with the existing commands below, choosing a new output directory.

## Confirmed aggregation and full evaluation

The main overall measure is pooled Score B: add service credit across days, divide by the number of input parcels across those days, and scale to 100. This gives every parcel equal weight.

```text
D = delivered parcels, T = on-time parcels, O = early + late parcels, N = input parcels
pooled B = 100 * sum(T + 0.5 * O) / sum(N)
         = 50 * sum(D + T) / sum(N)
```

Rank with exact unrounded credit totals; equal B values share a rank. Distance is a supporting measurement. Pooled A ranks completion first, then on-time service when completion is exactly equal. Daily B mean, minimum, and the day or days attaining that minimum describe consistency. Total distance and trips are summed across days. Overall load utilisation is total departure load divided by `capacity * total trips`, not a mean of daily utilisation percentages. Sensitivity scores use the same pooled counts at outside-window credits 0.25 and 0.75.

For SA, calculate each seed's pooled metrics separately across the selected days, then report the equal mean of seeds 0–4, together with their range and sample standard deviation. Compare A using mean seed delivery counts first and mean seed on-time counts second. SA totals are labelled means across seeds; they never count the same input parcels five times against deterministic totals. Its daily consistency summary uses each day's five-seed mean B, while the individual seed outcomes are also retained. Each seed's random stream resets once per independent one-day simulation, as in development, and continues across that day's dispatches.

The full matrix has 220 fresh day-runs: six deterministic policies on 20 days, and one SA hybrid with five fixed seeds on each day. All seven existing implementations and SA settings are frozen. Results are reported for all 20 days (15,867 parcels), development days 001–005, and the separate evaluation days 006–020. The all-20 score includes development cases. No policy selection, extra tuning, or deletion of weak variants is implied by this evaluation.

To generate a complete new matrix and its aggregate summaries:

```bash
python3 -m solution.run_evaluation \
  --data data --output results/reproduced_full_evaluation --workers 4

python3 -m solution.evaluation \
  --data data --results results/reproduced_full_evaluation
```

The runner refuses an existing output directory to preserve prior results. It records successful process exits, exact commands, machine timings, settings, and source/input/prior-result/output hashes in `run_manifest.json`. The aggregation command writes `comparison.json`, `summary.csv`, and `daily_scores.csv`. Four workers run independent processes; their durations are observations under concurrency, not a controlled speed comparison. These commands do not regenerate the separately authored independent-validation report.

### Full matrix results

| Policy | Development 001–005 pooled B | Evaluation 006–020 pooled B | All 20 pooled B |
| --- | ---: | ---: | ---: |
| Baseline | 34.167 | 33.862 | 33.938 |
| Nearest feasible neighbour | 80.611 | 80.283 | 80.365 |
| Window-first nearest | 89.972 | 87.601 | **88.196** |
| Original greedy insertion | 88.125 | 87.382 | 87.569 |
| Credit per extra km insertion | 85.285 | 84.144 | 84.430 |
| Protect on-time insertion ties | 88.125 | 87.382 | 87.569 |
| Insertion + SA, five-seed mean | 88.168 | 87.399 | 87.592 |

Window-first has the highest pooled B in both the all-20 and separate evaluation-15 scopes. Its all-20 advantage over original insertion is 0.627 points, shrinking to 0.219 on evaluation days 006–020. Window-first beats insertion on 13 daily B comparisons and loses on seven. Its lowest daily B is 83.248 on day 020, compared with insertion's 83.504 on that day. The strongest pooled service score does not imply the best score on every day.

Across all 20 days, nearest neighbour completes 15,228 deliveries and window-first completes 15,204, while their on-time counts are 10,275 and 12,784 respectively. Scoring A therefore favours nearest neighbour on overall completion; the main Score B favours window-first's much higher on-time service. Window-first and original insertion complete exactly the same total, but window-first delivers 199 more parcels within preferred windows.

SA's all-20 pooled B mean is 87.591857, range 87.518119–87.622109, sample SD 0.042195. Its mean gain over original insertion is 0.023319 points. On evaluation days 006–020 the gain is 0.016824 points, with SA mean 87.399058, range 87.293910–87.432705, and sample SD 0.059257. Individual seeds can lose to insertion. Using SA's five-seed mean for each daily comparison, it wins seven days, ties nine, and loses four against insertion. This fixed swap-only configuration adds little service improvement.

The protection variant produces byte-identical logs to original insertion on all 20 days. This observed equivalence does not establish that its tiebreak can never affect another input or never acts internally. Efficiency's pooled B is lower than original insertion's in every scope, although its completion counts are higher. Both ablations remain in the evidence; report emphasis and final policy selection remain open.

The fresh matrix is saved under [full_evaluation](results/full_evaluation/). It reproduces all 55 earlier development combinations with byte-identical logs and metric files. Full-precision scope summaries, exact rankings, daily comparisons and SA seed outcomes are in [comparison.json](results/full_evaluation/comparison.json); compact tables are in [summary.csv](results/full_evaluation/summary.csv) and [daily_scores.csv](results/full_evaluation/daily_scores.csv). Commands and hashes are in [run_manifest.json](results/full_evaluation/run_manifest.json).

At the original evaluation, all **95 unit tests passed**, including 13 new aggregation cases. Independent validation passes all 220 runs, reconstructing 17,814 dispatch decisions and 6,090,000 SA swaps, including random draws, acceptance, cooling, and saved-best selection. It verifies all metrics, timing, eligibility, hard constraints, complete-day coverage, settings and hashes, plus all 21 policy/scope aggregates, exact A/B and sensitivity rankings, 21 summary CSV rows and 480 daily CSV rows, with zero mismatches. See [independent_validation.json](results/full_evaluation/independent_validation.json). Existing policies, the simulator, monitor, inputs, and earlier results remain unchanged. The aggregate ranking order stays the same at outside-window credits 0.25 and 0.75 in all three scopes.

The policy descriptions below remain current. Later sections retain the earlier five-day development experiments as history; their open aggregation decisions and untested-day statements describe that stage.

## Run the baseline

```bash
python3 -m simulator \
  --policy solution.policies.baseline \
  --data data --day day_001 \
  --output results/baseline/day_001
```

The simulator writes `results/baseline/day_001/log.txt`. Use separate output folders for each policy and day to preserve results.

## Nearest feasible neighbour

`solution.policies.nearest_neighbour` builds a trip one parcel at a time. From the current stop (initially the hub), it selects the feasible candidate with the shortest directed distance to its destination. Equal distances are resolved by parcel arrival time, then parcel ID. Candidates are all arrived, unassigned, undelivered parcels in the supplied snapshot.

Before adding a candidate, the policy checks that:

- the combined size of all selected parcels fits the vehicle capacity;
- the full proposed trip, including the return to the hub, fits the configured range (320 km);
- planning time plus the 30-minute preparation delay and full travel time returns the vehicle by the cutoff (18:00).

At the model's fixed 60 km/h, kilometres equal travel minutes. After each selection, remaining candidates are reconsidered from the new final stop. Previously selected parcels are not reordered. The policy has no intentional waiting rule, preferred-window priority, or tunable parameters; it returns an empty route if no parcel can be selected.

The implementation uses a local candidate dictionary and an ordered route list. For one dispatch call, let `n` be all supplied parcels and `m` the eligible candidates. Filtering takes `O(n)` and repeated candidate scans take `O(m²)` in the worst case, giving `O(n + m²)` time and `O(m)` additional space under average `O(1)` dictionary access.

```bash
python3 -m simulator \
  --policy solution.policies.nearest_neighbour \
  --data data --day day_001 \
  --output results/nearest_neighbour/day_001

python3 -m solution.performance_monitor \
  --data data --day day_001 \
  --log results/nearest_neighbour/day_001/log.txt
```

Compare policies on the same days and scoring definitions. A result from one day does not establish general superiority.

## Window-first nearest feasible neighbour

`solution.policies.window_first_nearest` retains the nearest policy's eligibility and hard feasibility checks. For each feasible candidate it calculates:

```text
projected delivery = planning time + preparation delay + planned travel prefix + next-leg distance
```

At 60 km/h, distances in kilometres equal travel minutes. A candidate is in-window when its projected delivery is between both inclusive window endpoints. In-window candidates have priority over early or late candidates. Within either group, rank by next-leg distance, then parcel arrival time, then parcel ID. If no feasible in-window candidate exists, the nearest feasible early or late candidate is selected. Recompute both distance and window status after every append.

Preferred windows remain soft: outside-window deliveries are allowed. There is no intentional waiting, earliest-deadline priority, or tunable parameter. The preparation delay is counted once, and the prefix excludes the provisional return to the hub. The candidate dictionary and ordered route list use `O(m)` additional space; time per call is `O(n + m²)` under average constant-time dictionary access, as for nearest neighbour.

## Greedy insertion

`solution.policies.greedy_insertion` constructs each trip from an empty route. It considers every eligible waiting parcel in every possible insertion position, including before the first selected parcel and between existing stops. It does not call another policy or use earlier results to construct a route.

Each candidate insertion must fit the full departure load, directed round-trip range, and return cutoff. The complete proposed route is replayed from departure, counting preparation once and using inclusive preferred windows. All selected parcels are rescored because inserting a parcel can change the delivery times of existing selections.

```text
route credit = on-time parcels + 0.5 × early-or-late parcels
net gain = credit after insertion − credit before insertion
```

Choose the insertion with the greatest strictly positive net gain. Break ties by least added complete-trip distance, then candidate parcel arrival time, parcel ID, and lowest insertion position. This distance rule selects route insertions; overall Score B ties share a rank. Credit is calculated internally in exact half-point units (`parcel count + on-time count` gives twice the credit).

Stop when no feasible insertion has positive gain. Zero- and negative-gain insertions are rejected even when physically feasible, so some waiting parcels may remain unselected. Outside-window deliveries can still be accepted when their insertion has positive net gain. There is no intentional waiting, benefit-per-kilometre ratio, local-search refinement, or tuned parameter; outside-window credit is fixed at 0.5 to match the main metric.

For one dispatch, let `n` be supplied parcel records, `m` eligible candidates, and `k` ultimately selected parcels. One round with `r` selected parcels examines `O(m(r+1))` insertions, each requiring `O(r+1)` route construction and evaluation. Including the final unsuccessful round, total time is `O(n + m(k+1)³)`, with the upper bound `O(n + m⁴)` when `k` can reach `m`. Candidates are generated one at a time, retaining only the best, so additional space is `O(m+k)`. This uses substantially more computation than nearest-neighbour construction.

## Two separate insertion optimisation variants

The two changes are tested separately. Both construct trips from empty using `solution/policies/_insertion_variants.py`; neither calls an older dispatch policy. All eligibility, full-route ETA evaluation, inclusive windows, hard feasibility, fixed 0.5 outside-window credit, and strictly positive-gain stopping rules match original insertion. Final Score B uses the same monitor and formula for every policy.

- `solution.policies.greedy_insertion_efficiency` prioritises net credit gained per added complete-trip kilometre. Positive-gain insertions adding no distance or shortening the trip come first, ordered by greatest gain then smallest distance change. For positive added distance, maximise gain divided by added distance; break ties by greater gain, smaller distance change, arrival time, parcel ID, and insertion position. There is no arbitrary epsilon or division by zero. Kilometres equal travel minutes in this simulation.
- `solution.policies.greedy_insertion_protect` keeps greatest net credit gain first. Equal gains prefer the fewest previously on-time parcel IDs becoming early or late, then the least added complete-trip distance, arrival time, parcel ID, and insertion position. This is a tiebreak, not a ban on changing an existing on-time delivery; a larger-gain insertion can still take precedence. Tracking parcel identities distinguishes preservation from replacing an old on-time delivery with a newly on-time one.

The shared engine generates and scores one candidate at a time, with worst-case `O(n + m(k+1)³)` time (bounded by `O(n + m⁴)`) and `O(m+k)` additional space, as for original insertion. The on-time identity sets do not change these bounds. No combined version or additional tuning was introduced.

## Greedy insertion plus simulated annealing

`solution.policies.insertion_sa` is a hybrid: call the unchanged original greedy-insertion constructor on the current dispatch snapshot, then search different orderings of that selected parcel set. Later dispatch snapshots can differ from the control run because SA changes return times. No routes are loaded from earlier logs.

Each SA proposal swaps two distinct parcel positions. It keeps the same parcel IDs and departure load, fully replays directed travel and inclusive window timing, and rejects range or return-cutoff violations. There is no stop waiting, parcel addition/removal, or intentional hub waiting. Routes with fewer than two parcels skip the search.

Acceptance uses raw route credit `R = on_time + 0.5 * outside_window`. Equal or greater credit is always accepted. A feasible worse route is accepted with `exp((R_new - R_current) / temperature)`. The evaluator's integer doubled-credit difference is divided by two before this calculation. No distance penalty is added to the credit. The saved best route maximises credit, using minimum complete-trip distance only when credits tie; the seed route is included and the saved best is returned rather than the final random state. This protects the seed's trip objective, not a guaranteed full-day score.

One configuration was fixed before the experiment:

- 2,000 attempted swaps per trip with at least two parcels;
- initial temperature `-0.5 / log(0.30)`, approximately 0.415292, giving 30% initial acceptance for losing one on-time delivery (0.5 raw credit with fixed membership);
- multiply temperature by 0.995 after every attempted proposal, including infeasible or unchanged-outcome proposals;
- random seeds 0, 1, 2, 3, and 4, with a dedicated `random.Random(seed)` initialised once per simulation run and reused across its dispatch calls;
- temperature restarts at the specified initial value for each trip; the random stream does not restart per trip.

These settings are a reproducible starting configuration, not tuned or claimed optimal. Additional SA cost is `O(I*r)` time and `O(r)` space for `I` attempts and `r` selected parcels per trip; the original insertion-construction cost is additional. The budget is per trip, not per day.

Use the explicit seeded runner for experiments:

```bash
python3 -m solution.run_sa \
  --data data --day day_001 --seed 0 \
  --output results/insertion_sa/day_001/seed_0

python3 -m solution.performance_monitor \
  --data data --day day_001 \
  --log results/insertion_sa/day_001/seed_0/log.txt
```

The runner writes `settings.json` and a per-dispatch `planning_audit.jsonl` alongside `log.txt`. The audit records seed/best routes, credit, distance, proposal/acceptance counts, and temperature. Direct simulator CLI use of `solution.policies.insertion_sa` defaults to seed 0 in a fresh process. Python callers running multiple simulations in one process should create a fresh `make_dispatch(seed)` for each run.

## Calculate metrics

```bash
python3 -m solution.performance_monitor \
  --data data --day day_001 \
  --log results/baseline/day_001/log.txt
```

This writes `metrics.json` beside the log. An existing log can be rescored without rerunning the simulator, provided the policy and inputs have not changed. Use only logs from successfully completed simulations; a failed run can leave a partial log.

The monitor rejects unknown or duplicate deliveries and unfinished departed trips. These checks do not prove that a log contains a complete day; confirm that the simulator finished successfully.

Let `N` be all parcels in the day's input, `T` the number delivered within their preferred windows, and `O` the number delivered early or late. Every parcel is counted once. Window endpoints are inclusive.

- **Scoring A:** completion rate, `100 * (T + O) / N`. Rank by completion first; use `on_time_service_rate_pct = 100 * T / N` as a tiebreak only when completion is exactly equal.
- **Scoring B:** `100 * (T + 0.5 * O) / N`. An on-time delivery earns 1 point, an early or late delivery earns 0.5, and an undelivered parcel earns 0. Early and late deliveries receive the same credit.
- **Sensitivity analysis:** also calculate B with out-of-window credit of 0.25 and 0.75 from the same log. These weights are explicit modelling assumptions.
- All completion and on-time service rates use **all input parcels** as their denominator, including undelivered parcels. Scores and rates with a zero denominator are JSON `null`, rather than evidence of good or poor service.
- **Total distance:** sum directed distances along each trip from the hub, through deliveries in log order, and back to the hub.
- **Average load utilisation:** `average_load_utilisation_pct = 100 * sum(trip parcel sizes) / (number_of_trips * vehicle_capacity)`. It is `null` when there are no trips.

Trips are identified by `(vehicle_id, trip_id)` because trip IDs repeat across vehicles. Count trips using departures; the initial vehicle-return events at 08:00 are not completed trips.

## Development check on days 001–005

The nearest feasible neighbour policy was kept unchanged for the additional check on days 002–005. Both policies were run afresh on those four days, using identical inputs and scoring. The existing day 001 results were reused after checking their input, source, and log hashes. Earlier outputs are preserved.

| Day | Input parcels | Baseline delivered | Nearest delivered | Baseline Score B | Nearest Score B |
| --- | ---: | ---: | ---: | ---: | ---: |
| 001 | 799 | 349 | 763 | 35.17 | 80.48 |
| 002 | 772 | 274 | 734 | 32.25 | 83.55 |
| 003 | 794 | 315 | 757 | 33.06 | 74.75 |
| 004 | 808 | 341 | 778 | 33.79 | 80.88 |
| 005 | 806 | 358 | 783 | 36.48 | 83.44 |

Nearest feasible neighbour wins under Scoring A and Scoring B on all five development days. It also wins on each day when outside-window credit is 0.25 or 0.75. Its completion rate ranges from 95.08% to 97.15%, with 19.63% to 24.40% less distance than the paired baseline. These are per-day comparisons; no pooled or mean overall score has been selected.

Timing remains a weakness. Day 003 has the lowest nearest-neighbour Score B: 430 parcels were on time, 211 early, 116 late, and 37 undelivered. Nearest-neighbour late counts exceed baseline late counts on days 002 and 003, although completion and on-time service rates are higher on both days. No preferred-window rule has been added or tuned. Days 006–020 have not been evaluated in this check.

Full-precision comparisons are saved in [comparison.json](results/development_check_002_005/comparison.json). [run_manifest.json](results/development_check_002_005/run_manifest.json) records commands, successful process exit codes, runtimes, and hashes. New logs and metrics are stored under `results/development_check_002_005/<policy>/<day>/`.

All eight new runs also passed an [independent validation](results/development_check_002_005/independent_validation.json) of metrics, route decisions, arrival eligibility, complete planning coverage, directed travel timing, load, range, return cutoff, and recorded hashes. This validation parsed the inputs and logs without importing the monitor, policies, or simulator.

To reproduce the eight additional simulations and their metrics:

```bash
for check_day in day_002 day_003 day_004 day_005; do
  for check_policy in baseline nearest_neighbour; do
    check_output="results/development_check_002_005/$check_policy/$check_day"
    python3 -m simulator \
      --policy "solution.policies.$check_policy" \
      --data data --day "$check_day" --output "$check_output" || exit 1
    python3 -m solution.performance_monitor \
      --data data --day "$check_day" \
      --log "$check_output/log.txt" || exit 1
  done
done
```

These commands regenerate logs and metrics. The saved manifest describes the original check; independently rerun commands do not refresh that provenance record.

## Window-first comparison on days 001–005

Five new window-first simulations were compared with verified existing nearest-neighbour results on the same development days. No parameters were tuned. Baseline, nearest neighbour, the monitor, inputs, and earlier result files were preserved.

| Day | Nearest Score B | Window-first Score B | Score B change | Delivered change |
| --- | ---: | ---: | ---: | ---: |
| 001 | 80.48 | 90.74 | +10.26 | −1 |
| 002 | 83.55 | 91.84 | +8.29 | +2 |
| 003 | 74.75 | 87.47 | +12.72 | +1 |
| 004 | 80.88 | 90.04 | +9.16 | +1 |
| 005 | 83.44 | 89.83 | +6.39 | −2 |

Window-first improves Score B by 6.39–12.72 points and delivers 105–201 more parcels within their preferred windows per day. It also wins at outside-window credit 0.25 and 0.75 on every day. Delivery counts change by at most two parcels. Scoring A ranks window-first first on days 002–004, while nearest neighbour wins days 001 and 005 because it completes one and two more deliveries respectively.

The timing changes have costs. Late counts increase on days 003–005, and distance increases on days 002 (+1.04%) and 003 (+8.74%). Distance decreases on the other three days. On day 003, 210 of the 211 previously early parcels become on-time deliveries, while 21 previously on-time parcels become late. The net gain is 201 on-time parcels. Window-first does not guarantee that every individual parcel improves.

At that stage, all 34 unit tests passed, including 12 new policy tests. All five window-first runs pass an independent input/log validation, including reconstructed route choices and empty planning decisions. Full-precision metrics, paired parcel timing transitions, sensitivity comparisons, and verification references are saved in [comparison_with_nearest.json](results/window_first_nearest/comparison_with_nearest.json). [run_manifest.json](results/window_first_nearest/run_manifest.json) records commands, successful exit codes, runtimes, and hashes; [independent_validation.json](results/window_first_nearest/independent_validation.json) contains the independent checks.

These results support a substantial improvement on the five development days. They do not establish statistical significance, an optimum, or performance on days 006–020. No pooled or mean overall score has been selected. Both policies remain available for subsequent comparisons.

To reproduce the five new simulations and their metrics:

```bash
for check_day in day_001 day_002 day_003 day_004 day_005; do
  check_output="results/window_first_nearest/$check_day"
  python3 -m simulator \
    --policy solution.policies.window_first_nearest \
    --data data --day "$check_day" --output "$check_output" || exit 1
  python3 -m solution.performance_monitor \
    --data data --day "$check_day" \
    --log "$check_output/log.txt" || exit 1
done
```

These commands regenerate logs and metrics; they do not refresh the original manifest or comparison files.

## Greedy-insertion comparison on days 001–005

Five new insertion runs use the same development inputs and scoring as the verified window-first results. Each trip is built independently from an empty route. No parameter tuning or evaluation on days 006–020 was performed.

| Day | Window-first Score B | Insertion Score B | Score B change | Delivered change |
| --- | ---: | ---: | ---: | ---: |
| 001 | 90.74 | 87.05 | −3.69 | +1 |
| 002 | 91.84 | 87.76 | −4.08 | +2 |
| 003 | 87.47 | 91.44 | +3.97 | +1 |
| 004 | 90.04 | 89.36 | −0.68 | −3 |
| 005 | 89.83 | 85.05 | −4.78 | 0 |

Insertion wins Score B only on day 003; window-first wins the other four days. The same per-day rankings hold at outside-window credit 0.25 and 0.75. These results do not support a consistent improvement over window-first on this development set. Local gains in a growing route's credit do not guarantee higher service across the full day, because routes also affect vehicle availability and subsequent decisions.

Scoring A favours insertion on days 001–003 through higher completion. Window-first wins day 004 on completion and day 005 on the on-time tiebreak: both deliver 781 parcels, but window-first delivers 667 on time versus insertion's 590. Distance is lower with insertion on days 002 (−0.82%) and 003 (−6.03%) and higher on the other three days. Both policies remain available; no pooled or mean overall score has been chosen.

At that stage, all 49 unit tests passed, including 15 insertion tests. The five simulations and metric calculations completed successfully. An independent validator reconstructed every insertion decision and checked metrics, timing, eligibility, hard constraints, complete-day coverage, and recorded hashes with no mismatches. Earlier policies, the simulator, monitor, inputs, and reference results remain unchanged.

Full-precision paired results are in [comparison_with_window_first.json](results/greedy_insertion/comparison_with_window_first.json). Commands, exit codes, runtimes, and hashes are in [run_manifest.json](results/greedy_insertion/run_manifest.json); independent checks are in [independent_validation.json](results/greedy_insertion/independent_validation.json). The observed simulator command durations were 3.32–4.67 seconds per day; these timings are not a controlled benchmark against the earlier policies.

To reproduce the five new simulations and their metrics:

```bash
for check_day in day_001 day_002 day_003 day_004 day_005; do
  check_output="results/greedy_insertion/$check_day"
  python3 -m simulator \
    --policy solution.policies.greedy_insertion \
    --data data --day "$check_day" --output "$check_output" || exit 1
  python3 -m solution.performance_monitor \
    --data data --day "$check_day" \
    --log "$check_output/log.txt" || exit 1
done
```

These commands regenerate logs and metrics; they do not refresh the original manifest or comparison files.

## Separate insertion optimisation comparisons on days 001–005

Both proposed changes were tested separately, giving ten new simulations on the same development days. All policies use the identical final Score B formula. There is no combined variant or fitted weight.

| Day | Original insertion B | Credit per extra km B | Protect on-time ties B | Window-first B |
| --- | ---: | ---: | ---: | ---: |
| 001 | 87.05 | 81.91 | 87.05 | 90.74 |
| 002 | 87.76 | 84.52 | 87.76 | 91.84 |
| 003 | 91.44 | 87.78 | 91.44 | 87.47 |
| 004 | 89.36 | 86.88 | 89.36 | 90.04 |
| 005 | 85.05 | 85.30 | 85.05 | 89.83 |

The efficiency variant improves original insertion's Score B only on day 005 (+0.25 points); losses on the other four days range from −2.48 to −5.13 points. Its on-time delivery counts change by −81, −52, −59, −43, and +4 respectively. Early deliveries increase on every day. Distance changes are mixed: lower on days 001, 002, and 004, higher on 003 and 005. Lower travel on some days therefore did not translate into higher service scores. Scoring A favours efficiency over original insertion on four days, including the day 005 on-time tiebreak at equal completion; original insertion wins day 001.

The protection variant produces byte-identical simulation logs and identical metrics to original insertion on all five days. Focused hand tests demonstrate that the protection rule can change route selection in an equal-gain case. These development results do not establish that the tiebreak never becomes active internally or cannot affect other inputs.

Neither separate change gives a consistent Score B improvement over original insertion. Against window-first, each new variant wins Score B only on day 003 and loses the other four days. All these paired winners remain the same at outside-window credits 0.25 and 0.75. Window-first remains the stronger Score B reference across this set; original insertion retains its day 003 advantage. No overall pooled or mean score has been selected, and days 006–020 remain untested.

At that stage, all 66 unit tests passed, including 17 new variant cases. All ten new simulations and metric commands completed successfully. Independent replay reproduced every variant's insertion choices and verified metrics, arrival eligibility, travel timing, full hard constraints, complete-day coverage, and source/reference/output hashes with zero mismatches. Earlier policies and result files are preserved.

Full-precision per-day metrics and comparisons against both references are in [comparison.json](results/insertion_optimisation/comparison.json). [run_manifest.json](results/insertion_optimisation/run_manifest.json) records commands, exit codes, timings and hashes; [independent_validation.json](results/insertion_optimisation/independent_validation.json) contains the independent checks.

To reproduce the ten simulations and their metrics:

```bash
for check_policy in greedy_insertion_efficiency greedy_insertion_protect; do
  for check_day in day_001 day_002 day_003 day_004 day_005; do
    check_output="results/insertion_optimisation/$check_policy/$check_day"
    python3 -m simulator \
      --policy "solution.policies.$check_policy" \
      --data data --day "$check_day" --output "$check_output" || exit 1
    python3 -m solution.performance_monitor \
      --data data --day "$check_day" \
      --log "$check_output/log.txt" || exit 1
  done
done
```

These commands regenerate logs and metrics; they do not refresh the original manifest or comparison files.

## Simulated-annealing comparison on days 001–005

One fixed insertion + SA configuration was run with seeds 0–4 on each development day, giving 25 runs. These are five input days with five random-seed replications each. Settings were fixed before seeing these results; no tuning or evaluation on days 006–020 was performed. Original insertion and window-first results were preserved as same-day references.

| Day | Original insertion B | SA mean B | SA range B | Mean change vs insertion | Window-first B |
| --- | ---: | ---: | ---: | ---: | ---: |
| 001 | 87.046 | 87.046 | 87.046–87.046 | 0.000 | 90.738 |
| 002 | 87.759 | 87.824 | 87.824–87.824 | +0.065 | 91.839 |
| 003 | 91.436 | 91.373 | 91.373–91.373 | −0.063 | 87.469 |
| 004 | 89.356 | 89.356 | 89.356–89.356 | 0.000 | 90.037 |
| 005 | 85.050 | 85.261 | 84.864–85.360 | +0.211 | 89.826 |

Means and ranges are across the five seeds **within each day**. The sample standard deviation of B is zero on days 001–004 and 0.222 on day 005. Equal B does not imply identical routes: distance varies across some seeds even when service counts do not. No pooled or mean final score across days has been selected.

The effect is small and inconsistent. Relative to original insertion, SA wins B in 9 replicated runs, ties in 10, and loses in 6. Day 002 gains one on-time delivery with unchanged completion; day 003 loses one. On day 005, seeds 0, 1, 2, and 4 deliver 780 parcels with 596 on time, compared with insertion's 781 and 590; seed 3 delivers 779 with 589 on time and loses B. Reporting only a best seed would conceal this variation. Scoring A favours SA on day 002, insertion on days 003 and 005, and ties on 001 and 004. All paired B winners remain the same at outside-window credits 0.25 and 0.75.

Against window-first, every SA seed wins B on day 003 and loses on the other four days. This experiment does not establish a consistent service-score improvement over original insertion or window-first.

The trip-level audit explains the limited effect: across the 25 runs, 760 routes were searched using 1,520,000 swaps. Only 10 returned routes improve credit over their fresh insertion seed, and 23 preserve credit while shortening distance. The search temporarily accepted 316 worse-credit proposals. Every returned route still ranks at least as well as its own fresh seed by credit then distance. A full-day regression is possible because changed returns affect later vehicle availability and dispatch snapshots. Fixed-membership swaps cannot directly improve parcel selection or vehicle allocation.

SA's mean daily distances are 4,234.436, 4,216.665, 3,981.306, 4,110.035, and 4,118.560 km respectively; these are lower than insertion on days 001, 003, and 004, and higher on 002 and 005. Trip counts are 33, 32, 33, 33, and 34, reducing insertion by one trip on days 002 and 003. Observed simulation durations are 3.46–4.86 seconds per run; this is not a controlled speed comparison with previous policies.

At that stage, all **82 unit tests passed**, including 16 new SA tests. Independent replay verified all 25 runs, including 2,159 dispatch decisions, every swap and RNG draw, acceptance, cooling, saved-best selection, metrics, hard constraints, eligibility, complete-day coverage, settings, and hashes. There were zero mismatches. Earlier policies, the simulator, monitor, inputs, and reference results are preserved.

Full-precision metrics, per-day seed summaries, paired A/B and sensitivity rankings, runtime, and audit counts are in [comparison.json](results/insertion_sa/comparison.json). [run_manifest.json](results/insertion_sa/run_manifest.json) records settings, commands, exit codes, durations, and hashes; [independent_validation.json](results/insertion_sa/independent_validation.json) contains the independent checks. Each day/seed folder retains its log, metrics, settings, and planning audit.

To reproduce the 25 simulations and metrics:

```bash
for check_day in day_001 day_002 day_003 day_004 day_005; do
  for check_seed in 0 1 2 3 4; do
    check_output="results/insertion_sa/$check_day/seed_$check_seed"
    python3 -m solution.run_sa \
      --data data --day "$check_day" --seed "$check_seed" \
      --output "$check_output" || exit 1
    python3 -m solution.performance_monitor \
      --data data --day "$check_day" \
      --log "$check_output/log.txt" || exit 1
  done
done
```

These commands regenerate logs, settings, planning audits, and metrics; they do not refresh the original manifest, comparison, or independent-validation files. Exact random-stream replay was validated under the Python version recorded in the manifest.

## Run checks

```bash
python3 -m unittest discover -s tests -v
```
