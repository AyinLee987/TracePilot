# R3 offline analysis and figures review

Date: 2026-10-06. Scope: the new offline analyzer and plotting script, their documentation, and the explicitly unfrozen R4 proposal. No online executor or hidden grader changes are included.

## Completed reviews

Three actual read-only Claude CLI reviews used `claude-opus-5-5`, returned exit 0 and `is_error=false`, and retained their prompts, results and source hashes locally. Reviews used no tools, did not inspect live model outputs and had no imposed budget or turn cap.

- Initial review: corrected unknown versus failed outcomes, baseline missingness, unknown fees, deadline-bounded cost attribution, native-only pre-feedback strata, and visibility of stopped grading.
- Incremental review: corrected unknown stratum membership for unstarted/interrupted runs, incomplete common-state fallback outcomes, and the common seed-to-first-attempt edge. Unknown fees and unstarted rows are excluded from the relevant box summaries while remaining visible as marked points.
- Final missingness review: no blocking findings. The prior claim that task heatmaps lacked missing-outcome gating was withdrawn after inspection of the complete source; the gating already existed.

The last review covers analyzer SHA256 `223a6d12265c4a5e9d77b3d5ee989c32351f8cc08fdf332397b2e8b009f3b3fc` and the pre-layout plot version. Subsequent layout changes have separate rendering evidence and a focused final review recorded below. The original findings and superseded evidence remain preserved.

## Validation and limits

- The final analyzer passed 21 pure JSON checks and an existing closed executor/cancel fixture, retaining 144 physical rows and 288 snapshots. These inputs use simulated HTTP/grading; they are not paid benchmark results.
- Plotting uses separate, explicitly synthetic copies of fixture tables. Mapping their labels from 0.2/0.6 to 5/15 exercises the plotting contract only. The original fixture files remain unchanged. PNG, PDF and SVG exports and missingness branches are checked; visual inspection identified and corrected overlapping labels and insufficient margins.
- Stratum condition rows describe known members; membership uncertainty is reported separately in `stratum_support`. A three-task minimum does not establish a causal effect or adequate statistical power.
- A common first-attempt parse failure is an observed failure to correct the seed, while its hidden transition is undefined. Late or unavailable common first attempts also retain an unknown descriptive edge. They must not be silently converted into successful repairs.
- Full request bills attributed to a dispatch-time prefix are offline accounting, not costs known by that prefix. They cannot be used as online prediction features. Post-selection spending is not automatically avoidable waste.
- Actual paid-root analysis and figures remain pending final hidden grading at this feature checkpoint. Their eventual validation and scientific findings must be reported separately.

## Final layout and documentation review

The fourth actual Claude Opus 5.5 review returned exit 0, `is_error=false`, and no submission blocker. Its source-unchanged receipt binds the final plot SHA256 `41c9e816778dd8bbe7b7801ad7d074917bfc6353a9af07a37af73327ed2b052b`. The hash and the plotting dependency file were independently checked after review. Final synthetic exports and all three PNGs passed text/layout inspection; earlier 13 missingness checks and the nine shared-axis checks retain their separate source versions.

Accepted documentation clarifications distinguish those validation versions, use “64 requests” consistently, and clarify that a missing delivered candidate gives that model `hidden_pass=0`, not an automatic tie between models. The R4 draft now explicitly asks its future zero-API timing check to report 5-second availability under the simulated response condition; this cannot predict the real provider's availability rate. Cosmetic duplicate inner y-axis labels remain legible in the inspected figures and require no further change.

See [versioned evidence](../../research/results/coding-deadline-analysis-validation.json). No completed hidden comparison, predictive result, or successful Timely numerical reproduction is claimed by this feature checkpoint.
