# Research scripts

These are independent research tools, not TracePilot routing features. Start with the [direction note](../docs/research/decision.md).

## Timely evaluation with a real Jericho game

See the [reproduction scope and budget](../docs/research/timely-reproduction.md). Use a dedicated Linux/WSL Python 3.12 environment, a locally obtained supported ROM, and the unmodified official source at `e13af2b8c98d799857ace789ebcfdfd4ea6c2985`. Build tools are needed to install Jericho. The [requirements](requirements-timely.txt) pin the validated SDK, HTTP transport, and game dependencies; a complete environment freeze is retained with each local setup.

```bash
python -m pip install -r research/requirements-timely.txt
python -B research/timely_transport_fake_e2e.py
python -B research/timely_reproduction_fake_e2e.py --source .local/timely-machine-audit --game /path/to/zork1.z5
python -B research/timely_reproduce.py --source .local/timely-machine-audit --game /path/to/zork1.z5 --output .local/timely-reproduction-runs/unique-fake-run --steps 8
```

The default uses a fake model and a real game, with zero API spend. Output directories must be new. The first paid speed run uses `--steps 8 --execute-paid --env-file /path/to/provider.env --budget-cny 5 --max-calls 12`; run it only after the code-review gate in the reproduction plan. It sends at most eight expected model calls to the official DeepSeek endpoint, with no retries. The env file contains `DEEPSEEK_API_KEY`. Keep it and raw responses out of Git. This standalone run does not provide the later shared pilot ledger; import its expenses before any batch runs.

Each invocation runs one serial episode in its own process. `manifest.json` pins the inputs and source; `requests.jsonl` records dispatch, completion and budget evidence; `official/` preserves upstream output; `environment.json` observes real signed scores and game termination without changing actions; `result.json` separates technical completion, protocol validity, and calibration usability. A zero exit code is not a solved game. The official evaluator's `success` flag can be set by a model conclusion, so use the independent environment observation for victory.

Unknown requests stop further dispatch and retain their reservation. Valid reported usage above the estimate increases the retained liability; a configured cap is not a provider-side spending limit. The legacy `paid_call_count` field counts dispatched calls, including synthetic and unresolved calls; check the run's `paid` flag. The full offline suite includes a generated dummy credential through the real network-client setup, with socket access blocked, and verifies worker cleanup after normal and failed game operations.

The calibration gate also excludes output truncation and model-declared conclusions: upstream includes conclusion generation time in elapsed time but excludes that response from its step denominator. The original value is retained, alongside explicit exclusion reasons. Preserve every planned calibration run, including failures; do not cherry-pick successful runs to form the calibration set.

The environment observer temporarily wraps the upstream environment class and closes each instance and any action-discovery worker pool on exit. It is restricted to this isolated runner, not a concurrent library integration. Observer overhead is included in measured time. Upstream virtual tool durations, noisy timing, step caps and after-action deadline checks remain unchanged; these outputs are not the later common-wall-clock experiments or the paper's unavailable checkpoints. Network timeouts apply per operation, not as an absolute task deadline.

The [first real R1 result](results/timely-r1.json) preserves a protocol failure: one of eight responses used an unsupported tool-call format. Its cost is included, but its speed estimate is excluded from calibration. The explicit `--tool-format single-json-v1` condition adds one-call-at-a-time formatting instructions for both models. `official` remains the default; the manifest records the condition and prompt hashes. This is a disclosed prompt adaptation, not the released paper checkpoints or a parser repair.

## Frozen Timely small matrix

The commands in this section describe the stopped v1 matrix; use audited succession below for v2. Do not create another independent paid plan.

`timely_batch.py` coordinates 24 serial episodes: eight 32-step speed runs (two models, virtual tool delays of 0/10 seconds, two repeats), then sixteen timed runs at 32/64 steps. Calibration uses the summed official time divided by summed recorded steps within each model/delay condition. Every predeclared calibration must be usable; the script stops on failure instead of selecting successful repeats.

```bash
python -B research/timely_batch_fake_e2e.py
python -B research/timely_batch.py create-plan --pilot-root .local/timely-small-offline --source .local/timely-machine-audit --game /path/to/zork1.z5 --tool-format single-json-v1
python -B research/timely_batch.py run --pilot-root .local/timely-small-offline
python -B research/timely_batch.py run --pilot-root .local/timely-small-offline --execute-offline --max-runs 1
```

Plan creation and dry inspection make no model calls. Execution requires Linux/WSL and the same Python environment used to create the plan. `--max-runs` stops cleanly without changing the frozen matrix; a later invocation resumes it. Offline fixtures are not official evaluator results; `--execute-offline` instead exercises the real pinned evaluator with fake HTTP responses.

A paid plan additionally requires `--plan-paid` and one `--import-r1 DIR` for every historical paid attempt under `.local/timely-reproduction-runs`. Create the paid plan only after final review and commit, explicitly passing `--tool-format single-json-v1`; inspect it in dry mode and start with `--max-runs 4`. Execution then needs `--execute-paid --env-file /path/to/provider.env` and a completed Claude review. The fixed study registry permits one paid small-matrix pilot, with a cumulative cap of CNY 200 including imported costs; Flash children are capped at CNY 5; Pro uses CNY 10 for 32 steps and CNY 20 for 64 steps. The child caps sum to CNY 220, but only balanced blocks are reserved; actual cumulative commitment must remain at or below CNY 200. It reserves a whole balanced block (CNY 30 for calibration or CNY 80 for timed runs) before launching any child. Failed or unresolved attempts cannot disappear by creating another directory. Do not run independent paid scripts outside this coordinator after registration.

The append-only ledger retains unresolved liabilities and stops. Do not delete locks, edit calibration files, or retry stopped children to make a batch pass. Linux process ownership records support bounded cleanup of the launched child and its descendants; uncertain cleanup preserves locks. Completed batches also recheck raw evidence, calibration hashes and recomputed timing. This scope covers one game's small matrix; four-game and coding extensions must explicitly reuse the same study budget.

## Pinned evaluator audit (no API or extra packages)

Use a separate checkout of the [official repository](https://github.com/Entarochuan/Timely-Machine) at `e13af2b8c98d799857ace789ebcfdfd4ea6c2985`:

```powershell
python -I -S -B research/timely_audit.py --source .local/timely-machine-audit --output .local/audit-result.json
```

The script verifies the source revision and file contents. It exercises unchanged extracted definitions with explicitly fake collaborators; it does not reproduce model or training results. The checked-in [result](results/timely-audit.json) contains no API measurements.

## Exploratory timing pilot

Python 3.12; paid modes require `httpx==0.28.1` and, when using an env file, `python-dotenv==1.2.4`. This earlier pilot uses a separate environment from Timely/Jericho. The fake mode uses only the standard library.

```powershell
python -B research/timing_pilot.py dry-run
python -B research/timing_pilot.py dev --execute-paid --env-file .local/provider.env --budget-cny 10 --max-calls 60
python -B research/timing_pilot.py analyze --source .local/timing-pilot/DEVELOPMENT_BATCH
```

Only after checking the development gate, use its frozen `suggested_deadline_s` with `probe --deadline SECONDS --execute-paid --env-file .local/provider.env --budget-cny 50 --max-calls 384`. The file contains `DEEPSEEK_API_KEY`; the provider endpoint is fixed to the official DeepSeek API. Never commit credentials or raw outputs.

Read the [protocol](../docs/research/pilot-protocol.md) first. Paid calls use actual HTTP and wall-clock waits; dry-run results are synthetic. Outputs are exclusive new directories under `.local`. A deadline stops new work and rejects late answers but does not cancel upstream billing. The HTTP timeout is per network operation, not an absolute completion limit. Costs are peak-price planning estimates, not invoices.

The archive task has a nearly fixed evidence chain. It checks solvability, accounting and timing; it cannot establish the value of informative latency history, a new routing method, or an ACL-scale result.

Recompute redacted numeric evidence and paired action hashes from retained local batches:

```powershell
python -I -S -B research/analyze_timing_pilot.py --development .local/timing-pilot/DEVELOPMENT_BATCH --probe .local/timing-pilot/PROBE_BATCH --output .local/new-summary.json
```

The output path must not already exist. Raw ledgers remain local; this analysis makes no additional API calls.

## Open-source agent smoke runners

See the [Pi setup and evidence](../docs/research/pi-pilot.md) and [mini-SWE-agent setup and evidence](../docs/research/mini-pilot.md). Both runners default to a fake provider; explicit paid flags use the official DeepSeek API and an environment-only credential. Shared synthetic fixtures are in `agents/fixtures/`.

The [redacted results](results/open-agent-smoke.json) include the initial mini workflow failure and the prompt-corrected rerun. These are integration checks, not performance comparisons or a universal TracePilot adapter.


Capacity and recovery details are in the [reproduction plan](../docs/research/timely-reproduction.md#9-付费前容量停止与恢复边界). Request limits are 256,000 message-JSON bytes and 1 MiB total request bytes. Oversized/invalid requests stop that transport without dispatch. A stopped paid plan has no automatic retry. The explicit study succession commands below preserve its ledger and reconcile the same cumulative study budget before activation. Do not delete the registry or reuse failed calibration results. The frozen runtime also includes the WSL platform, so an OS upgrade prevents silent resume.

### First paid matrix and protocol revision

The [first paid R2 matrix](results/timely-r2-small-v1.json) stopped after 1 of 24 planned episodes: six Pro responses lacked a closing tool tag. All 32 calls have settled usage; none of that episode is usable calibration. The cumulative pilot estimate is CNY 0.103705632. Preserve the old ledger, complete denominator and raw evidence.

The separately named `single-json-v2` condition adds explicit closing-tag examples without changing the official parser or repairing model output. Its [six focused offline checks](results/timely-v2-validation.json) passed; real model compliance is still unverified. Only one complete revised matrix is allowed by the predeclared policy, after reviewed migration into the same cumulative CNY 200 budget. Historical commands above describe the first matrix; do not create another independently funded paid plan.

### Audited study succession

Run these in the same pinned Linux environment after the code review and commit. Preparation makes no provider calls and does not activate a plan. Inspect its complete 24 rows, parent seal, opening balance, and printed canonical plan digest. Activation requires that exact digest and a hash of the completed review artifact.

```sh
python -B research/timely_study.py prepare-revision --parent .local/timely-r2-small-paid-20261006 --pilot-root .local/timely-r2-small-v2-paid-20261006 --tool-format single-json-v2
python -B research/timely_study.py activate --pilot-root .local/timely-r2-small-v2-paid-20261006 --plan-sha256 VERIFIED_PLAN_DIGEST --review PATH_TO_COMPLETED_REVIEW --review-sha256 VERIFIED_REVIEW_HASH
python -B research/timely_batch.py run --pilot-root .local/timely-r2-small-v2-paid-20261006
```

Only after the dry check, use the existing paid `run` command with the provider env file and `--max-runs 4`. The genesis registry stays unchanged; a hash-linked transition identifies the sole active plan. Known cost and unresolved liabilities carry forward separately. Old files must stay sealed. The shared study lock serializes activation and paid execution. A second failed-small revision is rejected. `extension-basis` only audits a completed stage for a named subsequent executor; it does not implement or run four-game or coding experiments.

Keep frozen Timely code unchanged until the active matrix is terminal. Later executors require a reviewed code-version migration. If activation errors after publication, inspect the actual study head before retrying. Retain the review artifact; its hash is checked at execution. Keep outer clock observations outside sealed batch roots. Aggregate by `(pilot_id, run_id)` and distinguish this matrix's spend from cumulative study spend.

### Coding first-draft admission

The v2 matrix stopped after its first row with invalid tool JSON; the one permitted revision is exhausted. Coding uses the same CNY 200 study and preserves both stopped matrices. After review, prepare the fixed 16-slot plan in the pinned WSL Python environment, then use `timely_study.py prepare-coding16` with the terminal v2 parent and archived historical source manifest. Activate the returned plan digest with the completed review artifact before using `coding_pilot.py --execute-paid --pilot-root PATH --env-file PATH --evaluate`. Preparation and activation send no model requests.

The study reserves CNY 3.20 for the whole batch; the HTTP transport remains the only per-request accountant. All 16 request reservations are checked before dispatch. A failed or uncertain request stops further generation and retains liability. Once HTTP closure is confirmed, received candidates may be evaluated offline even if billing remains unresolved. An admitted batch cannot be executed twice. See the [frozen development protocol](../docs/research/coding-pilot.md); first drafts are not yet feedback-iteration or common-deadline experiments.

Plan preparation, study preparation, activation and execution must all use the same pinned WSL interpreter and Linux path form. Confirm dotenv, credential parsing and all request reservations before activation; no network request is needed for these checks. Later stages require an explicit successor that reads this batch's `coding-ledger.jsonl` and carries both settlements and liabilities into the same study. The present admission does not authorize an extension or reset the budget.

### Descriptive Timely trajectory

[Redacted step records](results/timely-trajectory-diagnostic.json) distinguish error feedback, tool execution and score changes across the three real runs. Rebuild the [single-run diagnostic](figures/timely-v2-diagnostic.png) in a separate plotting environment:

```sh
python -m pip install -r research/requirements-plot.txt
python research/plot_timely_diagnostic.py
```

The plot uses response index, not elapsed time. It shows a valid tool call after error feedback without an immediate score gain; it cannot identify feedback causality, prompt effects, or model rankings. The companion JSON records source and image hashes.
