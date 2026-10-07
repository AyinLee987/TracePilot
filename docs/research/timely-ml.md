# Timely Agentic ML protocol

Status: execution preparation, no paid ML results yet. This batch is the original
four-task ML family, not HumanEval or the public synthetic example.

## Scope and provenance

- Timely source: `Entarochuan/Timely-Machine@e13af2b8c98d799857ace789ebcfdfd4ea6c2985`.
- Tasks: leaf classification (891/99 train/test rows), Spaceship Titanic
  (7823/870), Random Acts of Pizza (2878/1162), detecting insults (3947/2647).
- Preserve the four task prompts shipped under the original `ML_source` tree.
- Public source mirrors and MLE-bench preparation at
  `507f92e1138bb6e40dac5c6ee7a6758e6424bf97` reconstruct the data. Every downloaded
  and prepared file has a local SHA-256 manifest. The authors omit their real
  data and private labels, so equality to their splits is **unverified**.
- Use existing `deepseek-flash` and `deepseek-v4-pro` APIs, not the authors'
  unpublished trained checkpoints. Temperature 0.7, thinking disabled, no
  retries, nonstreaming, 2048 output tokens versus the release default 4096.

## Matrix and accounting

Eight calibration episodes per task/model, then eight independently initialized
episodes at each multiplier 1–5: 64 calibration + 320 timed = 384 planned.
Calibration uses the upstream mean duration over valid submissions only. A cell
with no valid calibration is missing; do not invent a budget or tune its prompt.
Timed invalid/missing submissions remain in each planned eight-run denominator.
The API ceiling is 1088 calls (64 × 2 + 320 × 3), not a target.

Run two asynchronous episode workers, each with two CPUs and 4 GiB RAM. A free
worker takes the next row; ordering interleaves tasks and models. Queue time is
outside episode timers. Model latency, container startup, training, extraction,
grading and synchronous trace writes are inside the loop. Container teardown is
outside the recorded upstream duration. Keep wall and monotonic times separately;
discrepancies are reported without rescaling historical measurements. WSL clock
validation failed: a 30-second guest monotonic interval corresponded to roughly
27.7–28.3 Windows seconds, with backward guest wall-clock corrections. Changing
the guest clock source did not help. The evaluator therefore uses a timer adapter
reading Windows `time.perf_counter` through a read-only local socket; each read
checks service identity and rejects a round-trip over 100 ms, with at most three
read attempts. The bridge exits after ten idle minutes with no fixed lifetime
during an active batch. Read statistics are recorded. Clock reads and
their overhead are inside deadlines. This is a disclosed timing adaptation,
not byte-identical execution of the original Timer. Guest clocks remain
diagnostics; guest HTTP/container timeout ceilings are infrastructure guards,
not the scientific deadline clock. No GPU,
network, pretrained-weight download, or credentials inside execution containers.

This is one explicit successor in the existing CNY 200 study. The four-game
parent must be fully reconciled and sealed; its CNY 31.874239712 known estimate
carries forward. The new batch reserves CNY 50 and uses one shared budget
transport. Uncertain usage stops dispatch and retains the unspent reservation.
No automatic resume/replacement, new allowance, or paid prompt debugging.
Prices are the existing October 6 peak-rate assumptions and 8 CNY/USD planning
conversion, not invoices; Claude reviews are excluded.

## Preserved upstream semantics and limits

Use `AgenticMLEvaluator._speed_test_one`, `_time_limited_one`, and
`ml_metrics.evaluate_submission` unchanged. Calibration permits two attempts;
timed evaluation permits three, the released default. The selected result is the
highest private-test accuracy completed within **1.5 times** the stated budget.
The loop feeds test-score feedback to the agent, and its reported accuracy can
differ from the competition's requested metric (e.g. AUC or log loss). Retain
log loss and all iteration results, but do not call this untouched held-out
generalization or a strict common-deadline comparison: budgets are model-specific.

Docker replaces only the unsafe host subprocess boundary. Public data is mounted
read-only; labels stay in the parent grader. A per-episode bounded tmpfs preserves
files between attempts. It is discarded after timeout, cancellation or episode
completion. Submission export accepts only a bounded regular file, with no host
writable mount. stdout/stderr are diagnostic and bounded. Existing submissions
may be reused by successful later code, matching upstream workspace behavior;
after timeout the workspace is reset, an explicitly recorded adapter difference.
The offline engineering checks use predetermined code and fake HTTP, and never
count as model results. Raw code, traces, data and labels remain ignored locally.

## Commands

Use the established Ubuntu-24.04 root/native Docker environment and pinned
Timely reproduction Python. Do not change Docker daemons during the experiment.

```sh
python -B research/prepare_timely_ml.py
docker build -f research/docker/TimelyML.Dockerfile -t tracepilot-timely-ml:20261007 research/docker
python -B research/timely_ml_e2e.py
python -B research/timely_ml.py prepare
python -B research/timely_ml.py activate --review EXACT_COMPLETED_REVIEW_JSON
python -B research/timely_ml.py run --execute-paid --env-file EXISTING_PROVIDER_ENV
```

Preparation and activation send no model requests. Review evidence must name
actual `claude-opus-5-5`, bind the final source/protocol hashes, and retain the raw
review hash. Activation and execution share the study lock; execution verifies
data, upstream sources, image ID and runner hashes. A started batch is single-use.
