# Timely ML: corrected batch complete

The corrected 384-episode matrix finished on 2026-10-07 at 22:23:14 UTC+8.
The process exited with code 0 and was reaped. No experiment containers remain.

| Phase | Evaluated | Valid submission | No valid submission |
| --- | ---: | ---: | ---: |
| Calibration | 64 | 61 | 3 |
| Timed evaluation | 320 | 312 | 8 |
| Total | 384 | 373 | 11 |

All eight task/model calibration cells obtained a time budget. Invalid episodes
remain in the planned denominators. These are submission-validity counts, not
accuracy or task-success rates; no failed episode was selectively rerun.

Calibration (`speed` in the raw schema) counts a submission as valid when code
exits successfully, produces a submission file, and the original scorer accepts
it and returns accuracy. Each cell's budget uses the mean positive duration of
its valid calibration episodes after all eight planned episodes are evaluated.
Timed validity requires at least one scorer-accepted candidate whose recorded
evaluation time is at most 1.5 times the stated budget. A candidate beyond that
cutoff is excluded; an earlier qualifying candidate remains eligible. Thus a
candidate after the nominal deadline can still qualify within the 1.5-times rule.

All 1,034 API requests settled exactly once. The corrected batch's peak-rate
estimate is CNY 19.111148528. Including the quarantined batch's CNY 5.070512464,
the ML total is **CNY 24.181660992**, within the original CNY 50 allowance.
The broader study's known estimate is CNY 56.055900704. Active requests, unknown
usage and held reservations are all zero. Estimates are not provider invoices;
Claude review costs are separate.

Verification matched every planned row to its child result and every dispatched
request ID to a unique completion, reconciled the cost journal, checked the
process closure and empty Docker inventory, and confirmed that the active
source/protocol hashes and quarantined batch records are unchanged. See the
[machine-readable completion record](../../research/results/timely-ml-corrected-completion.json).
Raw prompts, generated code, submissions and response traces remain in ignored
`.local/timely-ml-corrected-paid-20261007`.

This completes the [corrected execution protocol](timely-ml-corrected.md).
The first batch remains [quarantined](timely-ml-environment-failure.md).
Substitute API models, reconstructed data splits, model-specific budgets,
three timed turns, 1.5-times budget acceptance and private-test score feedback
remain disclosed limitations. Completion alone does not establish a model
ranking or an exact replication of the paper's results. Because the agent sees
private-test scores during iteration, subsequent quality results are not an
untouched held-out generalization estimate. Per-task quality, time curves,
stage annotations and the 11 invalid episodes' failure causes are now available
in the [offline analysis](timely-ml-analysis.md). The completion counts and
original scores are unchanged.
