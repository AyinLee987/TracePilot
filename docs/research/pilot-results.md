# E0/E1 results: what actually ran

2026-10-05. These are exploratory checks, not a reproduction of Timely-RL or an ACL-scale benchmark.

## E0: public-code mechanics

The standard-library [audit](../../research/timely_audit.py) ran successfully against official Timely Machine commit `e13af2b8c98d799857ace789ebcfdfd4ea6c2985`. Source hashes and deterministic outputs are in [timely-audit.json](../../research/results/timely-audit.json).

Checks confirm grace-window eligibility, game action dispatch before the deadline check, transcript-clock reward semantics and a possible decreasing noisy clock. They use controlled responses/clocks and extracted unchanged definitions, not actual model runs. Downstream ML/game aggregation and historical paper impact remain unverified. See [scope and interpretation](timely-audit.md).

## E1: real model plus synthetic archive

Used the official DeepSeek API, requested and returned ID `deepseek-flash`, thinking disabled, temperature 0. The current official mapping is DeepSeek-V4.1-Flash; the returned alias does not pin immutable weights. All tools and task contents were synthetic, nonmedical and frozen. Timing and injected waiting were real wall-clock measurements.

Development: four tasks with tools and four no-tool checks, 26 real requests. Tool runs succeeded with complete evidence on **4/4**; no-tool runs were **0/4**. Successful tool completion times were 2.954–4.754 seconds without injected waits. The predeclared formula produced one **10-second** probe deadline, fixed before probe execution.

Probe: eight new seeds, two timing policies and two wait orderings, **32 complete runs / 165 real requests**. “Deadline-only” knows the initial deadline; “countdown” additionally receives the current remaining time before every request.

| Injected wait ordering | Deadline-only: correct with complete evidence before 10s | Countdown: same outcome |
| --- | ---: | ---: |
| Alternating | 3/8 | 4/8 |
| Grouped | 6/8 | 5/8 |
| Total | **9/16** | **9/16** |

There was one invocation per condition, not repeated independent measurements. The finite task prefixes experienced different delay totals even though the underlying twelve-element delay multisets matched. This is not a clean estimate of autocorrelation alone.

An independent read of the raw ledger found that all 16 task/pattern pairs had identical complete action objects over their shared returned prefixes; excluding late responses did not change that check. The two success disagreements involved the same correct answer finishing on opposite sides of the deadline (late examples: 10.3248s and 10.0702s). One longer action sequence only added a fetch request whose response arrived too late to execute.

**Permitted conclusion:** these records are compatible with a fixed action chain being truncated. We did not observe shared-prefix action changes. This does not establish causal policy equivalence, and it says nothing decisive about the proposed informative-history hypothesis: this task does not offer a meaningful optional-verification decision and does not manipulate historical information value.

## Accounting and integrity

- Combined: **40 runs / 191 actual API requests**. The runner uses direct `httpx.Client` with `HTTPTransport(retries=0)`, no SDK, and no application retry loop; the ledger counts each invocation of `client.post`. All response usage records were available and all returned model IDs matched the requested alias. Provider-internal retries are not observable and no claim is made about them.
- Three requests completed after the probe cutoff; all were charged and none counted as timely success. Every request was dispatched before its run's cutoff.
- Peak-price planning estimate: development **CNY 0.017813856**, probe **CNY 0.116646624**, total **CNY 0.13446048**. This uses reported token/cache usage and a deliberately conservative 8 CNY/USD planning conversion, not an invoice or a claimed current exchange rate. Fake dry-run charges are excluded. Claude subscription reviews are separate and are not asserted to have this API cost.
- Raw request/response/usage logs, manifests and run files remain ignored under `.local/timing-pilot/dev-20261005-reviewed` and `.local/timing-pilot/probe-20261005-d10`. No credentials, authorization headers or medical corpus were logged. The manifest freezes prompts, seeds, task hashes, code hash, protocol hash and Python version.
- [Public numeric summary](../../research/results/timing-pilot-summary.json) retains aggregate results, input hashes and paired complete-action-prefix hashes, including a separate comparison excluding late responses. [The analysis script](../../research/analyze_timing_pilot.py) recomputes these from the locally retained manifests/ledgers. The public hashes do not replace the raw records or establish behavior equivalence.

## Reproduce and continue

Use [research/README.md](../../research/README.md) and the [frozen protocol](pilot-protocol.md). Generate a new output directory; do not overwrite these runs. The real batches used budgets of 10 and 50 CNY and request caps of 60 and 384 respectively; actual usage was far below them.

Do not scale this archive into a paper benchmark. Its value is a working timing/accounting reference. The next scientific step is a matched-decision probe with genuinely optional information acquisition, then a mature RAG/coding task and simple external reserve/forecast baselines. The research recommendation remains conditional, as explained in [decision.md](decision.md).
