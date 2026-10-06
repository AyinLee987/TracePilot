# Predefined coding extension: 16 real first drafts

Date: 2026-10-06. The predefined extension completed all sixteen model requests on HumanEval /16, /99, /18 and /31, with two models and two independent drafts per task/model. This is development sampling before shared-deadline or feedback-repair comparisons.

| Model | Attempts | Parsed | Public results | Hidden aggregate | Median generation time | Estimated cost |
| --- | --- | --- | --- | --- | --- | --- |
| DeepSeek Flash | 8 | 8 | 7 pass, 1 fail | 7 pass, 1 fail | 1.059 s | CNY 0.012233088 |
| DeepSeek V4 Pro | 8 | 7 | 7 pass, 1 not evaluated | 7 pass, 1 not evaluated | 1.724 s | CNY 0.035380224 |

The denominator and timing summaries use eight attempts per model, including Pro's unparsed response; seven evaluated candidates are not reported as eight successes. No request, evaluation timeout or infrastructure failure occurred. Generation time includes request/local response handling and excludes separate judging. Cache-hit input tokens were 256/2072 for Flash and 1152/2064 for Pro. These observations do not establish a general model ranking or a benefit from extra iterations.

The full generation phase took 89.401 seconds, whereas the sixteen per-draft timers sum to 22.743 seconds. Their timers start after per-call admission verification and request-file preparation. The remaining 66.658 seconds are unsegmented orchestration overhead, not model generation; the current records cannot assign all of it to one operation. Shared-deadline experiments must count all online checks and writing, and calibrate the complete loop instead of using only the displayed model timers.

## Observable error and protocol failure

Flash's second draft on HumanEval/99 (`draft-11-he99-deepseek-flash-rep2`) passed three of four public checks. The published task explicitly requires rounding ties away from zero, including `"-14.5" -> -15`. The candidate used `ROUND_HALF_DOWN` in its negative-number branch and returned `-14`. This diagnosis uses only the published prompt, candidate and public diagnostic; hidden tests are not used to locate or choose the failure.

Pro's second draft on HumanEval/16 (`draft-10-he16-deepseek-v4-pro-rep2`) was rejected by the frozen parser with `ambiguous_or_surrounded_fence`. The response ended normally (`finish_reason=stop`) but did not satisfy the required output format. No candidate from that response was executed. This is a separate format failure, not an observed algorithmic test failure; the parser is not relaxed retrospectively.

## Decision

The predeclared extension found a publicly observable code error, so continue the HumanEval feedback branch. Do not activate the fallback benchmark migration or enlarge this task set merely to collect more failures. Preserve all 32 first-draft attempts across both batches. They contain one public code failure and one format failure; the other 30 passed public checks.

Freeze shared-deadline experiments over the full eight development tasks, including tasks with no observed errors. Compare independent resampling with feedback repair under the same public selection rule. The single natural code-error checkpoint may support a separately labeled local continuation experiment; its only source is Flash, so it cannot support a balanced-source or general mechanism claim. The format failure is a distinct diagnostic case. No shared-deadline run, repair gain or held-out prediction is claimed here.

## Execution and accounting

The frozen plan `7b01b16182ed6ecfe919525e26f81c9ed8e1a942aadbb2a7669247bf091f6804` ran reviewed code commit `bceaead150216a8047531123a36e75e8167bc60c`. Prepare verified the real parent summary identity, sealed first16 artifacts and historical source archive; activation and execution inherited CNY 0.296871136 under the same CNY 200 study cap.

All sixteen requests settled, HTTP closed before scoring, and the main child exited 0 and was reaped. Fifteen parsed candidates produced 45 isolated executions (15 public, 15 hidden, 15 references). All 45 workers exited 0 and were reaped; all containers have successful removal records. The independent read-only analyzer found no integrity issues. The numeric record includes the worker exit count, public failed check, candidate/response hashes and parser finish reason.

Batch cost: **CNY 0.047613312**. Current study total: **CNY 0.344484448**. Including earlier separate experiments: **CNY 0.506995744**. Unknown/reserved liability is zero. These are usage-based planning estimates, not invoices or account balances, and exclude Claude review usage. No new allowance was created.

This remains a selected-task judging bridge, not a full EvalPlus evaluation. The extension's canonical reference checks passed, but they do not prove universal checker validity. First16's /32 numerical limitations remain in the original report and are not erased or reinterpreted by this extension.

See [numeric results and source hashes](../../research/results/coding-extension16.json), [first16 results](coding-first16-results.md), [frozen protocol](coding-pilot.md), and [extension implementation review](../reviews/2026-10-06-coding-extension.md).
