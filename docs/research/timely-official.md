# Official Timely four-game evaluation

Status: prepared; real execution has not started. This is the current priority.

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

## Interpretation

This evaluates current API models on the released benchmark. It does not
reproduce the unpublished trained Qwen checkpoints or the paper's model curves.
Logical time budgets are calibrated separately per game/model; they are not a shared
wall-clock comparison. The original evaluator's success flag is reported
separately from actual game victory. Format failures and zero scores are results.
Clock consistency is reported alongside official logical and observed wall time.

Execution: `research/timely_official.py`; local manifests and traces stay under
`.local/timely-official-paid-20261006`. End-to-end checks use real game environments
with synthetic HTTP and are labelled separately from paid model results.
