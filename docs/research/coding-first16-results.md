# First 16 real coding drafts

Date: 2026-10-06. The first frozen development batch completed 16/16 requests, followed by public checks and then offline hidden scoring. This is independent first-draft sampling, before feedback repair or common-deadline experiments.

| Model | Drafts | Public pass | Hidden whole-task pass | Median generation time | Estimated cost |
| --- | --- | --- | --- | --- | --- |
| DeepSeek Flash | 8 | 8/8 | 6/8 | 1.076 s | CNY 0.019141632 |
| DeepSeek V4 Pro | 8 | 8/8 | 6/8 | 2.165 s | CNY 0.065539584 |

The four tasks were HumanEval/55, /32, /7 and /56, with two independent drafts per model. Every response parsed successfully. No public failure, timeout or infrastructure failure occurred. All four hidden whole-task failures were on /32; the selected-task numeric checker has an existing limitation (the reference implementation passes 881/888 inputs), so these are results under this bridge, not full EvalPlus scores.

That reference failure limits interpretation of the /32 binary verdict; it does not prove that every implementation must fail. Its individual input counts are retained for diagnosis and are not used to rank models. The other three tasks passed completely for both models.

Generation time includes request and local response handling, but excludes separate scoring and study-admission checks. Flash's measured median was lower in this batch; the small sample, differing cache usage and absence of feedback iterations do not establish a general speed-quality ranking or the original iterative advantage hypothesis. Cache-hit input tokens were 384/2228 for Flash and 1152/2220 for Pro.

**Decision from public evidence:** no observable natural error state was found. Continue with the previously specified development extension (/16, /99, /18, /31), preserving the same two-model/two-repeat protocol. Do not expose hidden failures to the model or use them to select repair states. If the extension also yields no public errors, follow the predeclared stop rule for this task set.

The batch cost was CNY 0.084681216; current study total CNY 0.296871136, all experimental usage estimates CNY 0.459382432, with zero unknown reservation. These are usage-based planning estimates, not invoices or account balances, and exclude Claude review usage. No new study allowance was created.

The CLI exited 0 and was reaped. All 44 isolated executions (16 public candidates, 16 hidden candidates, 12 references) have successful worker and container cleanup evidence. References comprise one per draft on /55, /7 and /56: three tasks × four drafts; /32 uses a residual check. The generation phase closed before any scoring. Runtime bytes at execution matched the reviewed plan, including pilot SHA `fdd487d82c0464ae5b73aaf3fbf2b00d3926e6484c1d9020057b3a281de780f1` at code commit `80e208e`.

See the [redacted result and source hashes](../../research/results/coding-first16.json), [frozen protocol](coding-pilot.md), and [admission review](../reviews/2026-10-06-coding-paid-admission.md). The extension has not yet run; shared deadlines, repair/resampling comparisons and held-out selection remain pending.
