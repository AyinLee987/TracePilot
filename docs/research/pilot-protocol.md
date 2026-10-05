# E1 protocol: exploratory timing pilot

Frozen before paid generation, 2026-10-05. This is an engineering/behavioral gate, not a novel method or a confirmatory ACL experiment.

## Question

Does supplying accurate remaining wall-clock time change a real model's tool decisions, beyond truncating a fixed sequence? The later research question is narrower: whether informative latency history helps decisions under distribution shift, compared with simple external rules. This pilot cannot establish that claim.

## Fixed first stage

- Official DeepSeek API, explicit `deepseek-flash`, thinking disabled, temperature 0, JSON actions, max output 256 tokens, no SDK retries, one serial request at a time. Record returned model ID. The alias/version is a deployment condition, not a known parameter count.
- Fully synthetic nonmedical archive tasks. Independent local PRNG seed creates opaque entities and a 2–3 relation chain, plus distractors. Tools `search` (titles only) and `fetch` (full record) use a frozen corpus. Gold answer and required evidence are private to the evaluator.
- Development seeds 101–104. Run without a research deadline (but 12 calls and 180-second safety cap) to check solvability and measure completion latency. No-tool calibration uses a separate single call on the same four development tasks; it is not a test comparison.
- Paid calls require an explicit CLI flag and known peak price table. A maximum context size of 24,000 ASCII characters is conservatively reserved as 25,024 input tokens per request; max output 256. Flash peak USD/1M rates: input miss 0.30, hit 0.006, output 1.20. The hard request reservation uses **all input at miss price** and a deliberately conservative planning conversion of 8 CNY/USD, not a claimed exchange rate. A batch budget and total call cap bound uncertain usage. No retries. Unknown usage reserves the full bound and stops further calls.
- Development gate: tools produce correct, fully evidenced answers on at least 3/4 tasks and no-tool answers are not all correct. If the task/prompt fails, fix development only and preserve failed calls in the ledger.
- Freeze one absolute deadline from development: median successful completion time + 1.5 seconds × median tool calls, rounded up to a whole second. This accounts for planned injected delay, without choosing a deadline on probe outcomes. A median does not guarantee 50% test success.
- Exploratory probe seeds 201–208, four conditions per task, randomized within task with seed 20261005: deadline-only or countdown, crossed with alternating or grouped artificial tool waits. All four conditions share the same corpus. Not a formal held-out generalization set: structural templates are shared; future confirmatory tasks must be independent families.
- Delays use the same twelve-element multiset: six 0.15s and six 2.85s waits. Alternating versus grouped arrangement, with a task-seeded random cyclic phase. Phase uses its own domain-separated PRNG seed (`latency-phase:{seed}`), avoiding coupling the first random draw to chain length. All conditions within a task use the same phase. Each tool invocation consumes one entry. Truncated prefixes need not expose the same mean; report exposure. Do not infer a pure autocorrelation effect from this finite pilot.
- Real sleeps and `perf_counter`, not virtual completion timestamps. Tool computation, injected sleep, model request, answer completion and drain are separate events. At the deadline, no new API/tool call is dispatched. An in-flight API is allowed to return (60-second network timeout); it remains charged and its late answer is a deadline failure. Sleep may be cut at the deadline, and unfinished tool results are not delivered.
- The 60-second timeout bounds individual network operations, not the total HTTP lifetime. The 180-second safety cap stops new work but does not cancel a provider request already in flight. Synchronous JSONL flush/fsync and parsing are included in harness-ready answer time. Raw request bodies and responses are saved locally; authorization headers and exception bodies are not logged.
- Both policies know the initial deadline. Countdown is appended at the end of the latest user message, never inserted in the stable system prefix. Control receives a step/status line at the same position. They are not exactly token matched; report cache usage and acknowledge prompt-length confounding.
- Primary feasibility outcome: exact answer AND all required fetched/cited evidence delivered by deadline. Secondary: answer-only correctness, final action/call count, evidence coverage, failures, actual time, token usage and bounded peak-price cost. In-flight drain is not answer latency. No p95 claims with eight tasks.

## Decision rules

Eight probe tasks can show implementation viability and examples of changed behavior; they cannot establish significance, novelty, a ranking reversal or absence of effects. Inspect task-paired counts and full denominators. If no clear behavioral signal appears, do not spend the remaining budget on a large matrix tonight. A second model is conditional on an actionable uncertainty, not required to find a positive result.

This archive has a nearly fixed chain rather than a useful optional-verification trade-off. Therefore E1 is an engineering gate and cannot validate or reject the later informative-history hypothesis. The no-tool arm is primarily a leakage check. Four development tasks are a fragile calibration: report the observed deadline distribution, and do not claim 50% success was guaranteed. There is one invocation per task/condition; temperature 0 is not deterministic sampling.

Cost caps are per batch. The operator must sum all prior paid batches (including incomplete/error reservations) before another launch. Initial development reserves at most CNY 10 and probe at most CNY 50, jointly at most CNY 60 within tonight's CNY 200 ceiling. No automatic retries or automatic repeat batches are authorized by the script itself.

Before a publication experiment add an externally forced finalization/reserve baseline, equivalent-information controls, a fixed-behavior replay reference with its assumptions checked online, a second task family and model, and independent confirmatory data. Those are explicitly **not implemented** by the first pilot.

## Claude review dispositions

Claude Opus 5.5 reviewed the broader plan. Adopt: bound requests/context/cost, task-level comparisons, append time at message end, interleave conditions, separate exploratory/confirmatory data, and require useful tools. Reject as main novelty: scaled clock signals (Timely already perturbs time; Sehgal et al. study temporal prompt variants). Do not replace real waiting with a logical clock for a wall-clock claim; virtual timing can be a separately labelled mechanism study. Do not use a significance gate or assume a median deadline forces 50% success. Do not call offline replay exact without checking behavioral and service invariance. A forced-answer baseline must run online or at a saved predeadline prefix; selecting only runs later observed to overrun would be post-treatment selection.

Sources: [API mode](https://api-docs.deepseek.com/guides/thinking_mode/), [pricing](https://api-docs.deepseek.com/quick_start/pricing/). Tonight's overall experiment cap remains CNY 200; this initial pilot will use a much smaller explicit cap.
