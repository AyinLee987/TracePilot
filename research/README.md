# Research scripts

These are independent research tools, not TracePilot routing features. Start with the [direction note](../docs/research/decision.md).

## Pinned evaluator audit (no API or extra packages)

Use a separate checkout of the [official repository](https://github.com/Entarochuan/Timely-Machine) at `e13af2b8c98d799857ace789ebcfdfd4ea6c2985`:

```powershell
python -I -S -B research/timely_audit.py --source .local/timely-machine-audit --output .local/audit-result.json
```

The script verifies the source revision and file contents. It exercises unchanged extracted definitions with explicitly fake collaborators; it does not reproduce model or training results. The checked-in [result](results/timely-audit.json) contains no API measurements.

## Exploratory timing pilot

Python 3.12; paid modes require `httpx==0.28.1` and, when using an env file, `python-dotenv==1.2.4`. Install into a separate environment. The fake mode uses only the standard library.

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
