# Timely Machine: paper and public-code audit

Date: 2026-10-05 (Asia/Shanghai). Scope: ACL final paper and official public code. This is a feasibility audit, not a reproduction of the paper's model results.

## Evidence and scope

- [ACL final paper](https://aclanthology.org/2026.acl-long.211.pdf), proceedings pp. 4619–4636. Sections checked: 4.1–4.3, 5.1–5.6, Limitations, A.1.1–A.1.5, and C.
- [Official repository, fixed commit](https://github.com/Entarochuan/Timely-Machine/tree/e13af2b8c98d799857ace789ebcfdfd4ea6c2985), cloned independently for this audit. All code links below use this commit, abbreviated `e13af2b`.
- Local source checkout: `.local/timely-machine-audit/` (ignored). Reproducible deterministic checks: [`research/timely_audit.py`](../../research/timely_audit.py); recorded output: [`research/results/timely-audit.json`](../../research/results/timely-audit.json). These tracked research artifacts are not a shipped package or model benchmark.
- E0's deterministic audit itself uses no model API, GPU or training. The audit artifacts subsequently received Claude review and are included in the research-branch delivery. The original main checkout is unchanged.

The paper already includes text games, four ML coding/classification tasks, and AIME/MATH/GPQA (§4.1, §5.2). Its main size–latency crossover uses four games (§5.1); this is not evidence that every fast model beats every large model. The authors explicitly identify text-only evaluation, incomplete multi-agent treatment, and varying accuracy gains as limitations. Their work trains a fixed model's time-aware behavior rather than demonstrating cross-model routing.

Evidence labels used below:

- **Confirmed code behavior:** observed directly in the pinned code and, where stated, exercised with deterministic fakes.
- **Design choice:** a valid objective or protocol that answers a narrower question than a proposed use.
- **Not reported / not established:** insufficient evidence for a conclusion; not a claim that an experiment was never run.
- **Hypothesis:** a falsifiable research question, not a result.

## 1. Does time awareness survive a trustworthy completion clock?

**Evidence.** ACL §4.3, Eq. 9–10 defines reward using completion time, with zero reward past the deadline. Public RL reward parsing instead extracts the last timer text and the model's time conclusion: [parser, lines 97–105](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/rl/internbootcamp_v2/internbootcamp/bootcamps/Basic_LLM_timer/Basic_timer_reward_calculator_orig.py#L97), [time check, lines 234–284](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/rl/internbootcamp_v2/internbootcamp/bootcamps/Basic_LLM_timer/Basic_timer_reward_calculator_orig.py#L234). The conclusion must match the last tool reading before the deadline branch is reached. The inspected general-reasoning branch derives its timing values from those parsed strings and `identity.required_time`. Its [method signature](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/rl/internbootcamp_v2/internbootcamp/bootcamps/Basic_LLM_timer/Basic_timer_reward_calculator_orig.py#L164) accepts extracted output, identity, and unused extra keywords; the [base dispatch](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/rl/internbootcamp_v2/internbootcamp/src/base_reward_calculator.py#L84) forwards those inputs. This audited scorer path does not consume an independent answer-completion timestamp; upstream timing/enforcement is outside this check. Overtime can retain positive accuracy reward. The release's default [package import](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/rl/internbootcamp_v2/internbootcamp/bootcamps/Basic_LLM_timer/__init__.py#L1) selects the step-shaped calculator; the sinusoidal variant is a separate `_orig.py` file ([lines 292–304](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/rl/internbootcamp_v2/internbootcamp/bootcamps/Basic_LLM_timer/Basic_timer_reward_calculator_orig.py#L292)).

**Confirmed local checks.** Last-read extraction and conclusion consistency are tested separately. With correct answer and deadline 10, timer reads `20 → 8` plus conclusion 8 produce the same parsed last read and reward as a single read 8: `1.0` in the default calculator and `0.9951056516295154` in the sinusoidal variant. Reversing the reads to `8 → 20` with conclusion 20 matches the single-read-20 reward, approximately `0.5`. Holding the tool read at 8 while changing only the conclusion to 20 reduces reward to `0.5`; the reverse mismatch also returns `0.5`. The equality guard in source establishes the mismatch branch, because equal numerical rewards alone cannot identify its execution. These checks establish parser order, conclusion consistency, and positive overtime reward separately. They do **not** establish that a trained model exploited this behavior, that an upstream runner permits arbitrary overruns, or that this release configuration produced the paper tables. No invented completion-timestamp keyword is used as evidence.

**Design issue.** A last tool reading precedes final reasoning/answer serialization. Optimizing that timestamp can omit the finalization tail. Separately, a positive time-utilization term rewards spending more time for the same correct outcome; it measures budget use rather than latency minimization.

**Research hypothesis.** Apparent temporal competence partly reflects clock/reporting compliance; reserving enough time to finalize an answer is a distinct, generalizable skill.

**Small falsification experiment.** On 20–40 short verifiable tasks, record server-side monotonic timestamps for last timer call, final-answer start, complete valid answer, and stream close. Re-score identical trajectories using last-read time versus actual completion. Then compare ordinary deadline prompting, an explicit finalization reserve, and periodic externally supplied time. Match extra-message/token overhead. If overruns and ranking differences are negligible, deprioritize this hypothesis. Do not treat clock noise alone as novel: the paper already perturbs timing.

## 2. Do reported rankings depend on deadline enforcement and budget normalization?

**Evidence.** ACL §5.2 and A.1.5 use baseline-relative budgets. That measures adaptation to a model's own speed, not universally equal seconds. The [general evaluator, lines 258–260](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/src/timely_eval/general.py#L258) implements this allocation. The release accepts general reasoning through `1.1 * time_limit` ([lines 291–297](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/src/timely_eval/general.py#L291)); ML chooses the best valid submission through `1.5 * time_limit` ([lines 282–290](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/src/timely_eval/agentic_ml.py#L282)). Interactive evaluation executes the action before checking time, then keeps the environment's final score ([lines 208–242](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/src/timely_eval/interactive.py#L208)).

**Confirmed deterministic checks.** General: a correct result at 10.5 seconds is `within_time_limit=True` for a 10-second deadline. ML: a valid accuracy-0.8 submission at 14 seconds is selected for a 10-second deadline; 14 is intentionally inside its 15-second eligibility window. These establish grace-window eligibility, not absence of all cutoff enforcement. Game: the fixed-12 clock check dynamically demonstrates that a fake score-gaining action contributes 10 points despite deadline 10. Separately, asserted source positions establish the order: execute action, read elapsed time, check deadline, retain final score. The fixed clock alone does not establish event order. The execution engines and clocks are fakes; the real evaluator methods make these decisions. Interactive and ML downstream aggregation was not audited: these conclusions concern the returned per-run records only. They do not establish how often this occurs with models or how aggregate paper metrics were calculated.

**Classification.** Relative budgets are a design choice. The slack/late-action semantics are confirmed mismatches with a strict externally enforced deadline interpretation. Historical paper impact is unverified because raw experiment outputs and launch snapshots are omitted from the release.

**Research hypothesis.** Some efficiency rankings are sensitive to protocol rather than intrinsic model capability, especially when answer completion or a long tool call falls near the deadline.

**Small experiment.** Evaluate the same model set under (a) relative budgets and (b) shared absolute budgets, reporting success-by-deadline curves. Re-score stored completion events at 1.00, 1.10, and 1.50 tolerances without extra model calls. Record queueing, provider retry, and tool runtime separately. For execution with side effects, distinguish “no new action after deadline,” “result completed by deadline,” and “process killed at deadline.” If model ordering is stable, this becomes a robustness control rather than the paper's main contribution.

## 3. Is feedback worth waiting for, and when should the first usable answer be kept?

**Evidence.** ACL §5.5 observes weak ML gains from larger budgets and says early code rounds often determine performance. The public ML path evaluates submissions against `private_test_path` ([lines 345–351](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/src/timely_eval/agentic_ml.py#L345)), sends that evaluation into the next prompt ([lines 270–278](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/src/timely_eval/agentic_ml.py#L270)), and selects the highest observed accuracy ([line 290](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/src/timely_eval/agentic_ml.py#L290)). This is explicit metric feedback, not ordinary execution success alone.

**Classification.** Interactive scoring is a design choice; feedback labels must be treated as development/validation data. The inspected loop does not provide evidence of a separate untouched holdout for assessing selection. Calling the same observed score a final test metric can give an optimistic estimate, but its magnitude is not established here. This is not proof of training-data contamination.

**Research hypothesis.** The relative benefit of extra interaction is determined by feedback informativeness and the probability that a revision improves the current answer, not by waiting time alone. A strong first answer can rationally beat a slower revision loop when feedback is uninformative or induces regressions.

**Small experiment.** Choose executable coding tasks or synthetic RAG with hidden answer keys. Save the first valid candidate, then continue with (i) real verification feedback, (ii) a matched neutral acknowledgment, and (iii) no feedback/independent retry, all under the same absolute deadline. Keep outputs scored by a separate evaluator hidden from the agent. Report first-candidate quality, improvement/regression rates, time to first correct answer, best candidate with an implementable selector, and final delivered quality. An oracle best-of selector is only an upper bound. Useful decision point: keep/return the candidate, wait for evidence, or revise. Do not conflate it with a model router initially.

**Priority after literature checks.** This was an early candidate, subsequently demoted by direct work on stopping, feedback and revision harm. See [feedback priors](feedback-priors.md) and the current [decision](decision.md). Keeping the first answer or adding fixed sleeps is not a sufficient new contribution.

## 4. Do timing conclusions transfer across environments and resource contention?

**Evidence.** ACL A.1.2 lists the four reported games inside its training set; A.1.4 reports 8 H200 GPUs, concurrency 16, and eight game/ML repetitions. This supports controlled evaluation but not held-out-game or deployment-load generalization. Public [Timer, lines 34–57](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/src/timely_eval/timer.py#L34) uses wall time and independently perturbs total elapsed time per read in static/dynamic modes. Interactive evaluation uses static mode ([lines 159–160](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/src/timely_eval/interactive.py#L159)). The provider wrapper waits inside a semaphore and retries failures ([agents.py, lines 89–106](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/src/timely_eval/agents.py#L89)).

**Confirmed clock check.** The pinned [noise range, line 21](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/src/timely_eval/timer.py#L21) is `(0.99, 1.01)` and [`_noise`, lines 57–58](https://github.com/Entarochuan/Timely-Machine/blob/e13af2b8c98d799857ace789ebcfdfd4ea6c2985/src/timely_eval/timer.py#L57) draws uniformly on each call. The script asserts both facts and verifies its forced 1.005/0.995 draws lie strictly inside that support. With elapsed times 100 then 100.1 seconds, static-mode readings become approximately 100.5 then 99.5995. Thus supported interior draws can decrease the reported clock; this deterministic example does not estimate the frequency under random sampling or describe unperturbed `eval` mode. A model's response should not automatically be interpreted as response to genuine changing compute speed.

**Not established.** Distillation limited to early game steps does not establish transfer to unseen environments. Fixed-load evaluation does not isolate changes in model capability from queueing/inference-service behavior. None of this proves the reported crossover disappears elsewhere.

**Small experiment.** First use the same trace events to distinguish real monotonic elapsed time, reported time, service wait, and actual work. Later run a fixed set of tasks in serial and mild concurrent execution, plus a held-out task family, with identical model and prompt. Test whether a policy adapts to meaningful remaining opportunity or merely to the displayed numeric clock. Separate measured latency distributions from synthetic controls. This should be a robustness axis for candidate 3 unless a large reproducible interaction emerges.

## Why these findings are not yet an ACL result

The code discrepancies justify careful reimplementation and evaluation controls. They are not, by themselves, a new algorithm or empirical discovery about LLMs. There are no model results in this audit, no observed ranking reversal, no measured reward exploitation, and no demonstrated superiority of TracePilot.

A possible fallback asks when delayed feedback changes the marginal value of another verification step. Subsequent literature checks found substantial prior work on this question; it is not the current lead direction. Any future method must beat strong stopping and verification baselines after counting its own overhead. Negative findings should be reported transparently, but a negative result alone does not establish novelty or publishability. The current narrow hypothesis and its rejection criteria are in the [decision](decision.md).

## Deterministic validation record

The script requires Python 3.10+ and Git, with no third-party Python packages. Prepare the public source at the pinned commit, then run from the research workspace:

```powershell
git clone https://github.com/Entarochuan/Timely-Machine.git .local/timely-machine-audit
git -C .local/timely-machine-audit checkout --detach e13af2b8c98d799857ace789ebcfdfd4ea6c2985
python -B research/timely_audit.py --source .local/timely-machine-audit --output research/results/timely-audit.json
```

Skip cloning if the checkout already exists. The script checks its exact HEAD and verifies every consumed file against the pinned Git blob before executing selected AST definitions; it rejects a wrong commit or modified audited source. It also checks explicit structural assumptions about timer parsing, the reward entry point, budget calculation, and deadline comparisons. Results contain only repository-relative source names, source SHA-256 hashes, controls, and deterministic outputs, with no credentials or local user paths.

The initial scratch attempt had stopped during import because pandas was absent; this promoted artifact removes that dependency entirely. All loaded definitions come from verified source without copying third-party code into the script. Provider construction, ML execution/scoring, persistence, and clocks are explicitly faked; constructors are bypassed. Reward checks extract the unchanged class with Python AST and reject any attempt to invoke a judge. Signature, unused-keyword, base-dispatch, last-read, and conclusion-equality checks support the narrowly scoped scorer-input interpretation. There is no real sleeping, network call, benchmark dataset, model inference, or claim about complete upstream deadline enforcement.

Actual validation used the existing project's virtual-environment Python with `-B`, while running in the research worktree. A second run with `-I -S -B` also passed, verifying that site packages are unnecessary. An incorrect source checkout was rejected before producing JSON. No package installation or source-checkout modification was needed.

The final run exited 0 and produced:

| Check | Observed result | Permitted conclusion |
| --- | --- | --- |
| General deadline 10; finish 10.5 | accepted on time | 10% evaluator slack exists |
| ML deadline 10; submission 14 | accuracy 0.8 remains eligible | 50% ML eligibility slack exists |
| Game deadline 10; fixed clock 12 | postdeadline score 10 retained | dynamic outcome check; separate source-order assertions establish dispatch before deadline check |
| RL reads 20→8 versus 8→20, each with matching conclusion | matches respective single-read rewards 1.0/0.9951056516 versus about 0.5 | parser selects the last tool reading, not maximum or first |
| RL tool read 8, conclusion 8 versus 20 | reward falls from 1.0/0.9951056516 to 0.5 | conclusion consistency matters separately from tool-time parsing |
| RL, last read 20; deadline 10 | approximately 0.5 | overtime reward can be positive in released calculator |
| Static timer, elapsed 100/100.1; forced interior draws 1.005/0.995 | reported approximately 100.5/99.5995 | these supported draws decrease the displayed clock; frequency unmeasured |

These checks validate evaluator/scorer mechanics only. No measured model capability, data leakage effect size, published-result invalidation, or end-to-end training result is claimed. The original scratch remains ignored; the tracked script and JSON are the reproducible E0 evidence for review.
