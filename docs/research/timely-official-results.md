# Official Timely four-game results

Completed **384/384** episodes: 64 calibration and 320 timed episodes. 12,521 model requests settled; zero unknown/held usage.

Original prompts, parser, scoring, error feedback and default virtual tool delays were retained. Models were substituted with the existing DeepSeek APIs; this is not reproduction of the paper’s trained checkpoints. Each cell below contains eight repeats.

| Game | Model | 10 steps | 20 steps | 30 steps | 50 steps | 100 steps |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| zork1.z5 | deepseek-flash | 3.12 | 10.00 | 33.12 | 36.12 | 36.88 |
| zork1.z5 | deepseek-v4-pro | 1.25 | 6.88 | 15.00 | 34.38 | 42.62 |
| advent.z5 | deepseek-flash | 36.00 | 36.00 | 39.12 | 49.38 | 59.75 |
| advent.z5 | deepseek-v4-pro | 36.00 | 36.00 | 36.00 | 51.62 | 57.75 |
| enchanter.z3 | deepseek-flash | 0.00 | 10.00 | 12.50 | 17.50 | 12.50 |
| enchanter.z3 | deepseek-v4-pro | 2.50 | 0.00 | 0.00 | 3.75 | 15.62 |
| detective.z5 | deepseek-flash | 28.75 | 37.50 | 46.25 | 70.00 | 68.75 |
| detective.z5 | deepseek-v4-pro | 26.25 | 38.75 | 41.25 | 82.50 | 125.00 |

Scores are the unchanged official raw score. Different games have different maxima; do not average these raw scores across games.

Mean measured episode execution time: **39.94 seconds** (all 384, including calibration; model and tool execution, excluding launch/admission/review).
Observed wall-clock means by timed condition: 10 steps: 11.43s, 20 steps: 20.78s, 30 steps: 30.48s, 50 steps: 52.68s, 100 steps: 82.64s. These are observed durations, not imposed deadlines.

Batch API estimate: **CNY 28.7445**; existing study cumulative: **CNY 31.8742**. Estimates are not invoices and exclude Codex/Claude usage.
Reported provider usage: 37,809,889 input tokens and 611,270 output tokens (input totals include cache hits).
Execution elapsed: initial stage 60.50 minutes; continuation 15.71 minutes. These exclude review/admission and migration downtime. Recorded steps: 12,494; no-valid-tool steps: 3,808; malformed tool blocks: 28,981.

## Interpretation and limitations

- Each game/model has its own measured calibration duration. The logical deadline is the column multiplier times that calibration. The original loop also enforces the column step limit; score differences alone do not identify time-pressure effects. Termination causes were not separately classified here.
- Per-cell sample SD, min/max, victories, no-tool-step fraction, scheduler counts, and calibration versus evaluation logical seconds per recorded step are included in the aggregate JSON. Eight repeats with mixed scheduling do not establish a stable model ranking or monotonic benefit from larger budgets.
- Calibration and evaluation latency can differ; a slower calibration grants a larger later logical time allowance. This is not a shared wall-clock comparison.
- Tool latency is the upstream logical accounting delay, not actual sleeping. API latency and contention can vary between calibration and evaluation.
- Independent episode processes replaced upstream in-process asynchronous scheduling; concurrency was bounded at six.
- At the user’s request, scheduling changed after 256 episodes: the first stage waited for chunks of six; the remaining 128 continuously filled six worker slots. Old results were retained and no episode was rerun. Scheduler phase is in the CSV; mixed-phase aggregates cannot isolate scheduling or model-speed effects.
- Format errors and zero scores were retained. No prompt adjustment or sample replacement was performed.
- 3,808/12,494 recorded steps have no parseable tool call (30.5%); this confounds interpretation as game ability. Malformed-block counts can exceed response counts because a response can contain multiple blocks or unmatched tags.
- There are 27 more completed requests than recorded steps, matching 27 conclusion responses; the official loop checks conclusion before recording a step.
- Official success flags and positive-step counts are not game victory. The CSV also contains signed environment scores and actual victory flags.
- Clock-bound diagnostic flags: 19/384; official/environment score differences: 1/384. These do not silently rewrite official scores.
- This is the released default five-budget sweep on the four games used for analysis, not all 57 supported games or all task families in the paper.

[Protocol](timely-official.md) · [Aggregate data](../../research/results/timely-official.json) · [Per-episode metrics](../../research/results/timely-official-episodes.csv)
