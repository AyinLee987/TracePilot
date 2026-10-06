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
