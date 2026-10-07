# Timely ML: first batch stopped for an environment defect

The first paid ML batch is stopped, not a completed benchmark. It evaluated
100/384 planned episodes: all 64 calibration episodes and 36 timed episodes.
Flash/Spaceship Titanic had zero valid submissions in eight calibration episodes,
including failures from the missing dependency. Six subsequent timed rows were
therefore skipped for missing calibration before stopping; two were censored during the
controlled stop, and 276 were not started. The 212 dispatched API calls settled
with an estimated CNY 5.070512464 cost, zero unknown usage and zero active calls.
The shared study now carries CNY 36.944752176 known cost. These are estimates,
not provider invoices; Claude reviews are excluded.

## Root cause and interpretation

The image omitted the system `libgomp1` package. Importing LightGBM in a fresh
Python process failed with `libgomp.so.1: cannot open shared object file`.
The earlier package check imported Torch before LightGBM in the same process;
that import order masked the missing runtime dependency. That validation was
insufficient and its claim of general package availability is withdrawn.

The error appears in 78 code executions across 50 episode workspaces, including
episodes that subsequently recovered. It can affect success, feedback, duration
and calibrated budgets; do not remove only the failing attempts and compare the
rest. All scores from this batch are quarantined from scientific model rankings.
Formatting failures and other code errors also exist; they are not all attributed
to libgomp. No change is made to the historical four-game results by this finding.

New requests were stopped by deliberately shutting down the owned clock bridge.
Already dispatched API calls finished and settled before the coordinator exited;
the terminal `RuntimeError` is the stop mechanism, not the original defect.
The outer process exited and was reaped. Original traces, usage journal, image ID,
plan and results remain intact. The compact [audit](../../research/results/timely-ml-environment-failure.json)
records the result and usage-journal hashes and counts for all planned row statuses.

## Correction

The Dockerfile now installs `libgomp1`. The corrected image uses the separate tag
`tracepilot-timely-ml:20261007-libgomp`; the original tag and image are retained.
The E2E check starts a fresh Python process for every listed library, then trains
LightGBM on the real leaf dataset. It also reruns the original four-task scoring
and isolation checks, with fake HTTP and no provider spending.

The corrected-image checks passed: nine listed ML libraries imported in separate
processes, LightGBM trained on real leaf data, and all four task submissions passed
the original scorer. No containers remained. The [validation record](../../research/results/timely-ml-libgomp-validation.json)
identifies the corrected image and the raw evidence hash. NumPy, pandas and SciPy
are also exercised by training; their separate standalone imports were not claimed.

```sh
docker build -f research/docker/TimelyML.Dockerfile -t tracepilot-timely-ml:20261007-libgomp research/docker
python -B research/timely_ml_e2e.py --image tracepilot-timely-ml:20261007-libgomp
```

The paid runner still points at the original frozen, single-use batch. Building
the corrected image does not resume it. A fresh reviewed successor must carry
the actual spent amount forward and recalibrate the full matrix; do not overwrite
the old image ID, replace selected failed runs, or reset the study allowance.
No corrected paid batch has been launched at this checkpoint.
