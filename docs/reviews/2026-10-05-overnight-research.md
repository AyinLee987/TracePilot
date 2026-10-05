# Overnight research: review and dispositions

Scope: isolated `research/acl-feasibility-20261005`, starting at `dadab3f`. Original main remains protected. Reviewers are read-only and do not independently browse or execute tests; source verification and experiments are the executor's responsibility.

## Completed Claude reviews

The calls below returned `is_error=false` and actual `modelUsage` key `claude-opus-5-5`. No review budget/turn cap was set. Raw prompts and responses are ignored under `.local/overnight`.

| Call | Scope | Outcome |
| --- | --- | --- |
| `plan-review` | Overnight plan and inversion exercise | Identified weak novelty, timing confounds, need for tool necessity and explicit request/cost caps. |
| `direction-debate` | Original A/B, updated primary evidence, candidate C/D and pilot protocol | Withdrew clock-scaling novelty; recommended C only as a narrow falsification target. No ACL-ready claim. |
| `code-review` | Full timing runner, pinned evaluator audit, protocol and fake-check results | No blocker for development; found phase/chain RNG coupling before probe and requested tighter E0 evidence labels. |
| `pilot-delta-review` | Exact phase/runtime-metadata changes, updated protocol and reproduction README | No blockers for bounded real development/probe. Confirmed conservative call reservations and limitations. |
| `evidence-agent-plan-review` | Research result wording, E0 delta and newly authorized Pi/mini deployment plan | Requested independent clock/conclusion controls and stronger reproducible action comparison; highlighted tool credential isolation and inherited instructions. |
| `open-agents-code-review` | Full Pi/mini runners, final E0 controls and ledger analyzer | No safety/cost blocker. Requested explicit streaming usage, tighter cleanup and result wording. |
| `open-agents-delta-review` | Pi fixes, mini validation prompt/termination repair, analyzer consistency | No blocker for one bounded mini rerun within cumulative allowance. Requested prompt/script provenance and retained failed-run costs. |
| `final-artifacts-review` | Final recommendations, audit, result summaries, both smoke guides and progress | No blockers; cost totals reconciled. Requested clearer review chronology, provenance scope and integration boundaries. |

## Accepted changes

- Separate delay-phase PRNG domain from task-generation PRNG; preserve within-task paired phase. Re-ran fake E2E: 32 complete runs / 136 fake requests. Fake estimated fees are not paid experiment costs.
- Use explicit API/call/context bounds and no retries. Account for each batch separately and sum them operationally. Planned development cap 10 CNY and probe cap 50 CNY remain inside the 200 CNY nightly ceiling.
- Append countdown to the current message; do not change stable system prefixes. Log available cache usage. Equal wording/token length is not claimed.
- State that HTTP timeouts are per operation, deadlines stop new work but do not cancel billing, and synchronous log persistence/parsing contribute to answer-ready time.
- Label the archive E1 as an engineering check with a nearly fixed action chain, not evidence for candidate C. One invocation at temperature 0 is not a deterministic or statistically powered result.
- Tighten E0: removed the invented completion-keyword experiment; added multiple timer readings and separate conclusion-mismatch controls, plus source/interface/dispatch checks. Noise uses strictly interior values 1.005/0.995 and checks the actual source support and sampling calls. Static game dispatch-order evidence is distinct from the dynamic late-score check. ML/game aggregation is not audited; grace-window checks do not establish an absence of all cutoff controls. Updated deterministic results pass again.
- Publish the local-ledger analysis script and full-action paired hashes, with a separate comparison excluding late replies. Explicitly identify direct HTTP and disabled transport/application retries; provider-internal behavior remains unknown.
- Specify shared known verification benefit, disclosed delay rules for the first probe, and within-tool delay controls. Record different inspected versions of the temporal-dialogue paper rather than treating the author PDF as identical to arXiv v2.
- For open-agent smoke tests require fake-key absence canaries, restricted tool environments, no inherited repository instructions and independent validation. Actual source/runtime evidence is required before paid calls.
- Pi explicitly requests streaming usage and validates the field before dispatch; it skips further validation on failed container cleanup. Updated fake and real runs passed.
- Inspect actual generated code because the small validator is not adversarially robust. All three real artifacts contain only the intended function, with no imports or validator/output manipulation.
- Correct mini's ambiguous custom-adapter prompt after the first live run reached its limit while searching for a nonexistent `validate` shell executable. Describe a standalone adapter action, retain exact dispatch, and separate artifact validity from normal submission. Preserve the failed workflow and its cost. The reviewed rerun passed in four calls.
- Add mini script/system/task hashes; shared task unchanged. The initial run lacks script/prompt hashes, and this limitation remains explicit. Cumulative cost is checked by the experiment operator, while each runner enforces its per-run cap; there is no automatic global budget coordinator.
- Analyzer reads UTF-8 and uses the ledger's boolean `late` field. Recomputed results are unchanged. Timing comparisons remain engineering observations, not framework rankings.

## Not adopted, with reasons

- **Scaled clock as a main contribution:** contradicted by Timely clock noise and temporal-dialogue prompt comparisons. It can only be a control.
- **Replace real waiting with a logical clock for the main wall-clock claim:** simulations can be useful but need a separate label; E1 uses actual waits.
- **Assume median calibration yields 50% success:** four development tasks and different prompts do not justify this. Deadline uses a frozen formula; observed outcomes are reported.
- **Require statistical significance to decide a small pilot:** the sample is for feasibility, not a confirmatory test. Lack of a detected effect does not prove no effect.
- **Treat replay as universally exact or select a forced-answer branch only after observing timeout:** those require unverified invariance or post-treatment selection. Future reserve baselines must be applied prospectively.
- **Call deadline slack, relative budgets, utilization reward and timing noise uniformly bugs:** distinguish code behavior, author choices, unverified paper impact and research hypotheses.
- **Issue/comment to paper authors:** a useful future step, but no external message was sent; the user did not instruct one.
- **Put new framework smoke fees outside the first-week research budget:** rejected. They are reported separately but remain inside the same nested CNY 200 nightly / CNY 300 first-week / CNY 2,000 overall envelope; no extra budget was inferred.

The external reviewer mistakenly wrote that request bodies were not logged. The executor corrected this: fully synthetic request/response bodies are saved locally; authentication headers and exception bodies are excluded. No medical data is used or exported.

## Independent scientific critique

Additional source-checking agents identified Lookahead-R, ChronosAttack and VRR as closer priors. The direction note now requires shared process knowledge/calibration data, fixed evidence order, separation of prediction and action probes, explicit oracle-information labels, and optional actions with a meaningful trade-off. Broad “trace routing,” “delay matters,” and “keep the first answer” novelty claims were withdrawn. The bounded literature search does not certify novelty.

## Final experiments and scope

E1 completed 40 runs / 191 requests with known peak-price estimated cost CNY 0.13446048. Pi completed four requests normally. mini first used eight requests without normal submission, then completed four after the prompt repair. All 16 framework requests returned known usage, no API errors or insufficient-balance response. Total real experiment estimate is **CNY 0.162511296 for 207 requests**, not an invoice. Fake runs and Claude subscription reviews are excluded from that API estimate. No Pi/mini experiment container remained.

Independent read-only evidence checking confirmed the E1 totals and full common action-prefix equality. It also caught stale early recommendations in the Timely audit; these were demoted to historical/fallback ideas and a publishability assurance was removed. The decision now limits the reward finding to the inspected general-reasoning branch. No direction is represented as proven novel or ACL-ready.

Nonblocking generalization suggestions (uniform adapter APIs, universal result schema, adversarial evaluator, shell-command rewriting) are deferred. They are unnecessary for this bounded smoke and could conceal the exact supported integration contract. `passed` remains a documented legacy artifact-only field in mini; new fields control whole-smoke success.

The final review's documentation corrections were applied: Pi's initial review conditionally permitted the smoke, followed by the requested fixes and fake verification; its delta review was after the paid run. mini's repaired-prompt live rerun was after the delta review. The first mini failure remains visible. Public provenance is explicitly a subset of the local records, and the two mini final artifact hashes are identical despite the changed runner/prompt. The Pi reservation really prices 25,024 input tokens plus 1,024 output tokens; the extra input allowance is a framing margin, not an output label error. E0's no-model scope is limited to the deterministic audit execution itself. Final checks passed for 29 authored files and 55 relative links, actual key absence, ignored runtime outputs, syntax/JSON and unchanged original main.

## User-requested second novelty search

`novelty-recheck-review` returned `is_error=false`, actual model `claude-opus-5-5`, without a review budget/turn cap. No runtime code or model-capability experiment was added. Three parallel source-checking agents plus the executor examined the closest primary sources; the unavailable deep-research workflow was represented by manual search, source reading and independent critique, not claimed as an executed automated workflow.

The reviewer identified inconsistent emphasis between the new cautious novelty note and the old main-direction heading/budget. The heading now says candidate probe, subsequent-week spending is conditional on evidence, and one reading order replaces competing lists. Absence-of-experiment wording is limited to inspected sections. The progress entry now records this review and document validation.

Some reviewer verification concerns arose because its supplied source summary was intentionally abbreviated: JAUNT's greedy comparator was checked in section 6; NetMCP's outage penalty and five Exa-backed search servers in IV-C/V-A; TraceLab's recent-history motivation in its introduction; Sequential Sampling's known-distribution/i.i.d. assumptions in its model setup. These claims were retained after checking primary text. The inaccessible SSRN lead was not used for a central claim. No reviewer statement is treated as independent source retrieval.

Decision remains conditional: neither the history predictor, the predictor-to-LLM connection, nor the forecast/control separation is new by itself. A matched interaction between historical information value and action remains a possible empirical probe, not an established ACL contribution.
