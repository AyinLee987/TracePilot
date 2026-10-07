# Timely ML corrected batch

Authorized continuation after the first batch's [environment failure](timely-ml-environment-failure.md).
This protocol supersedes the first batch's execution status, not its frozen records.

- Run the entire original 384-row matrix again: 64 fresh calibrations and 320
  timed episodes, with the same two models, four tasks, prompts, settings,
  released evaluation loop, scoring, two workers and Windows clock bridge
  described in the [original protocol](timely-ml.md). No old calibration or
  score enters this batch. Missing calibration remains missing.
- Use the corrected Docker image
  `sha256:34c45e2c43a7eaba26a8898b40e52d33d5ffe08eb98bebbaf4a20c34e5c6c756`.
  Its explicit libgomp1 dependency and independent-process imports passed
  [zero-provider validation](../../research/results/timely-ml-libgomp-validation.json).
- Preserve the quarantined batch and seal its terminal evidence. All 212
  requests are settled at CNY 5.070512464; no active or unknown charges remain.
  Carry CNY 36.944752176 as the study's opening known estimate. The new cap is
  **CNY 44.929487536**, the unused portion of the original CNY 50 ML allowance.
  Keep the same CNY 200 study and a 1088-request ceiling for this fresh batch
  (up to 1300 requests including the old batch's 212). These are peak-rate
  estimates, not provider invoices; Claude review costs remain separate.
- Admit exactly one named correction from `timely-agentic-ml-v1` to
  `timely-agentic-ml-libgomp-v2`, using the existing study lock and append-only
  chain. Use a new ignored directory, `.local/timely-ml-corrected-paid-20261007`.
  Never overwrite an old plan, trace, calibration, result or reservation.
  No automatic episode retry, third batch, prompt tuning or extra allowance.
- The runner requires exact reviewed sources, this protocol, reconciled parent
  billing, process closure, immutable image/data and an unused destination.
  Unknown usage or uncertain cleanup stops dispatch and retains its reservation.
- Refuse startup if any container labeled `tracepilot.experiment=timely-ml`
  remains, including stopped containers. Do not run Docker E2E
  checks concurrently with this paid batch; both use the same experiment label.
  Freeze this protocol at preparation. Put subsequent status and results in
  separate documents rather than changing its bound bytes.

The previously disclosed research limits still apply: substitute API models,
reconstructed data splits, 2048 output tokens, CPU resources, model-specific
budgets, three timed turns, 1.5-times budget acceptance, and private-test score
feedback. This is not a strict shared-deadline model ranking or a replication
of the paper's exact trained models.
