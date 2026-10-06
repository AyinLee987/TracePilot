# Timely completed results review

Actual read-only Claude CLI: `claude-opus-5-5`, exit 0, `is_error=false`,
no turn or cost cap. No blocking finding. Private review SHA256:
`b7162f6c87aa2935836b44fefeb9ece8f0956dd3d814fae374c5dd582b2f95ae`.
The reviewer checked supplied report/protocol/aggregate data, not raw files.

Disposition without additional model calls:

- Clarified observed wall time versus the imposed logical deadline, and the
  original evaluator's simultaneous step limit. No claim that every run was
  limited by time; termination causes are not separately classified.
- Added each cell's sample SD, min/max, victory count, no-tool-step fraction,
  scheduling-phase counts, and calibration duration to the public aggregate
  JSON. Original aggregate evaluation seconds per step remain available.
- Disclosed calibration/evaluation latency drift, eight-repeat uncertainty,
  protocol errors and scheduling confounds; no stable model ranking is claimed.
- Labelled the overall time mean as including 64 calibration episodes.
  Explained the 27 conclusion responses excluded from recorded steps and
  block-level format counts, which are not failed-response counts.

All 384 planned episodes finished, 12,521 requests have known settled usage,
and the owned continuation process exited 0 with cleanup verified. The async
scheduler's previous nine synthetic checks and code review remain separate
from these actual API results. No run was replaced or repeated.

Independent read-only verification matched all CSV fields to local records,
384 unique IDs, 48 groups of eight, phase counts 256/128, Decimal costs, and
all 384 episode exit-0 cleanup receipts. Original result/groups/calibration
hashes remain unchanged; public provenance matches and exports contain no
absolute paths or raw prompt/response text.
