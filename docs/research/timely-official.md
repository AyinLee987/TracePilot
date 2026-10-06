# Official Timely four-game evaluation

Status: 256 episodes generated. Execution is switching schedulers at the user's
request; the remaining 128 episodes have not been dispatched at this checkpoint.

Use the released evaluator at `e13af2b8c98d799857ace789ebcfdfd4ea6c2985`
with its original prompts, parser, tool feedback, scoring and virtual tool delays.
The previous v1/v2 batches used an additional zero-format-error calibration gate.
The official evaluator instead records malformed replies and continues. Those
earlier stopped runs remain unchanged; this is a separate, declared condition.

## Frozen scope

- Games: Zork1, Advent, Enchanter and Detective; original Jericho ROMs.
- Models: `deepseek-flash` and `deepseek-v4-pro`, thinking disabled.
- Each game/model: eight 32-step speed trajectories, then eight trajectories at
  each released default timed budget: 10, 20, 30, 50 and 100 steps.
- Total: 64 calibration + 320 timed = 384 trajectories.
- Calibration follows the official positive-step trajectory criterion and
  `sum(logical elapsed time) / sum(recorded steps)` aggregation. Malformed
  responses consume time and steps. No response repair or prompt selection.
- Six isolated episode processes at most; each episode retains raw traces and
  request accounting. Order is frozen using seed 20261006. This process-level
  scheduling differs from the released in-process asynchronous batch scheduler.
- Official default virtual tool durations: step 1s, available actions 0.2s,
  score/max-score/end-game 0.1s. These are logical delays, not actual sleeps.
- API output cap 2048 tokens, temperature 0.7, SDK retries disabled, one model
  attempt per step. These bounded API settings differ from paper checkpoints.

The same existing CNY 200 study budget carries forward. Each concurrent episode
reserves at most CNY 20 and releases the unused amount after verified settlement.
Unknown usage or technical failure stops new dispatch; no automatic reruns.
No credentials, ROMs or raw trajectories are published.

## User-directed scheduling change

The initial coordinator dispatched chunks of six and waited for each chunk's
slowest episode. The user requested asynchronous scheduling. The replacement
keeps at most six isolated episode processes running and immediately fills a
vacant slot. Each episode's tool-feedback loop remains sequential.

The original coordinator was signalled alone and allowed its workers to finish.
Its terminal snapshot contains 255 settled episodes and one held reservation;
episode 252 independently finished with known usage and verified process cleanup.
The replacement verifies and settles that episode without rerunning it, then
executes only the 128 undispatched rows. Original plans, results, calibration and
source files remain unchanged. A supplement binds the new scheduler and the
transition evidence; combined results are written to separate files.

Scheduling phase must be retained in the results: the change may affect API load
and latency. A combined table is not evidence from one unchanged scheduling
condition. The original per-game/model calibration is retained and disclosed.

## Interpretation

This evaluates current API models on the released benchmark. It does not
reproduce the unpublished trained Qwen checkpoints or the paper's model curves.
Logical time budgets are calibrated separately per game/model; they are not a shared
wall-clock comparison. The original evaluator's success flag is reported
separately from actual game victory. Format failures and zero scores are results.
Clock consistency is reported alongside official logical and observed wall time.

Execution: `research/timely_official.py`, continued by
`research/timely_official_async.py`; local manifests and traces stay under
`.local/timely-official-paid-20261006`. End-to-end checks use real game environments
with synthetic HTTP and are labelled separately from paid model results.
