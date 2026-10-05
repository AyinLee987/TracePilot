# Feedback, stopping, and regression: novelty audit

Research date: 2026-10-05. Scope: primary-source search for a proposed agent policy that keeps a first usable answer, purchases or waits for external verification, and decides whether to revise before a real wall-clock deadline. This is a focused audit, not an exhaustive literature review. No model experiments were run for this note.

## Verdict

The broad proposal is **not yet a defensible novelty claim**. Its central decision is value of information / value of computation with optimal stopping. Tool-assisted correction, useful intermediate answers, adaptive stopping, and protecting an incumbent answer all have direct precedents. A real deadline is an important deployment constraint, but replacing a token or iteration limit with seconds does not by itself establish a research contribution.

The most damaging prior is VRR-Stop/VRR-Guard: it already models the risk that repair damages a correct answer and explicitly retains an incumbent unless verification improves. Any paper about “stop revising before regression” must address this work, even though it is currently a preprint.

## Six direct priors

| Paper and verified status | What it already covers | Boundary relevant to this project |
|---|---|---|
| [Verify, Repair, Repeat, or Stop? Robust Stopping for Noisy Verify-Repair Loops in LLM Agents](https://arxiv.org/abs/2607.17641), arXiv, submitted 2026-07-20 | Noisy verification, repair success versus damage, belief-based stopping, and an incumbent-preserving guard. | The inspected experiments emphasize repair rounds and verification votes. They do not evaluate the proposed current-answer decision under randomly timed external feedback and a real hard deadline. This is a scope boundary, not proof of a missing contribution. |
| [BEACON: Bayesian Optimal Stopping for Efficient LLM Sampling](https://arxiv.org/abs/2510.15945), arXiv, submitted 2025-10-09; current page says under review on ARR | Sequentially samples candidates, observes reward-model scores, and compares expected marginal benefit with sampling cost. Retains the best observed candidate. | Its main setting is candidate sampling with recall, rather than path-dependent repair after external evidence. It explicitly discusses the latency disadvantage of sequential sampling. Do not describe BEACON as an accepted ICLR paper. |
| [CRITIC: Large Language Models Can Self-Correct with Tool-Interactive Critiquing](https://proceedings.iclr.cc/paper_files/paper/2024/hash/fef126561bbf9d4467dbb8d27334b8fe-Abstract-Conference.html), ICLR 2024 | Produces an initial answer, uses tools to validate aspects of it, and revises with external feedback. Evaluates question answering, mathematical program synthesis, and toxicity reduction. | This already supplies the proposed first-answer → external-check → revision pipeline. A distinct contribution would concern the decision to acquire or wait for feedback, rather than adding this pipeline. |
| [Optimizing Anytime Reasoning via Budget Relative Policy Optimization](https://proceedings.neurips.cc/paper_files/paper/2025/hash/21efcb6a9fe5c90d660d3f560bb6094d-Abstract-Conference.html), NeurIPS 2025; arXiv submitted 2025-05-19 | AnytimeReasoner trains useful answers at different reasoning truncation points, rather than optimizing only the final answer. | Its evaluated budgets concern thinking tokens and mathematical reasoning. It does not supply the proposed external-feedback timing policy, but useful answers at interruption are already an explicit objective. |
| [Stop When Enough: Adaptive Early-Stopping for Chain-of-Thought Reasoning](https://aclanthology.org/2026.acl-long.1256/), ACL 2026 | REFRAIN detects reflective redundancy and adjusts stopping thresholds using a sliding-window UCB controller. It reports reduced token usage while maintaining or improving accuracy. | The inspected abstract concerns CoT stopping, not a complete external-tool verification and repair loop. “Prevent overthinking by deciding when to stop” is nevertheless already a published contribution. |
| [JOVE: Joint Execution and Verification for Resource-Aware LLM Task Graphs](https://arxiv.org/abs/2610.03296), arXiv, submitted 2026-10-02 | Jointly allocates execution and paid verification under cost and per-query latency constraints, with information gain from verification. | Its verification labels inform future allocations; verification can happen asynchronously and is not required to build the current response. Waiting for feedback to revise the current answer remains a different decision, but “verification value under latency constraints” is already close prior work. |

### Details that change the baseline choice

[VRR, Sections 3–5](https://arxiv.org/html/2607.17641v1) distinguishes verifier errors from repair success and damage. Its marginal-gain expression weighs fixing an incorrect candidate against breaking a correct one. VRR-Guard replaces the incumbent only when the new verification vote count improves by a margin. Experiments use eight verifier votes per round and at most five repairs; calibration uses labeled before/after pairs. Its dramatic late-collapse diagnostic includes a deliberately injected prompt mismatch, so that magnitude should not be presented as ordinary deployment regression. Offline selection of guard versus stopping mode is also not an evaluated online switching policy.

[BEACON](https://arxiv.org/html/2510.15945v1) is the direct conceptual baseline for “continue only when expected improvement is worth the cost.” Its main measurements include sampling counts and answer quality; the paper acknowledges sequential latency and describes a batched variant. A deadline-aware adaptation of this principle is a necessary cheap baseline, even when exact BEACON reproduction is unsuitable for a dependent repair process.

[JOVE's formulation](https://arxiv.org/html/2610.03296v1) makes a useful distinction: feedback can be valuable for improving later allocations without affecting the current response. Our proposed decision concerns the latter. These should not be mixed into one undifferentiated “verification utility” score.

## Additional evidence that limits the claim

Regression after self-correction is already studied. [Large Language Models Cannot Self-Correct Reasoning Yet, ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/8b4add8b0aa8749d80a34ca5d941c355-Abstract-Conference.html) reports limitations of intrinsic correction in its studied settings. That title must not be generalized into a universal claim about 2026 models. [Training Language Models to Self-Correct via Reinforcement Learning, ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/hash/871ac99fdc5282d0301934d23945ebaa-Abstract-Conference.html) demonstrates that training can improve this behavior.

Asynchronous verification plus rollback also has a systems precedent: [Sherlock: Reliable and Efficient Agentic Workflow Execution](https://arxiv.org/abs/2511.00330), an arXiv preprint submitted 2025-11-01, combines selective verification with speculative execution and rollback. Merely hiding verification latency or restoring a previous state would be a weak novelty claim.

## A narrower, testable question

**Does the dependence between feedback return time and feedback usefulness cause deadline-censored observations to miscalibrate an agent's keep-or-revise decision, beyond what average verifier quality and average latency predict?** If it does, can a small, time-conditioned calibration policy reduce harmful replacements under the same time and monetary limits?

This is a candidate empirical question, not a novelty declaration. The six papers above do not provide the specific controlled comparison in the portions inspected. A dedicated delayed-feedback literature search would still be required before claiming an open problem.

In particular, informative delays themselves are not new. [Stochastic Multi-Armed Bandits with Strongly Reward-Dependent Delays, AISTATS 2024](https://proceedings.mlr.press/v238/tang24c.html) explicitly models dependence between reward and delay and gives a censored-UCB algorithm with regret guarantees. Therefore an LLM paper would need evidence of a consequential agent-specific failure mode, a useful evaluation protocol, or a justified adaptation; it could not claim to discover delay-induced selection bias.

Three separate quantities need to be measured: whether feedback correctly assesses the incumbent, whether it contains actionable information, and whether the resulting revision actually improves the answer. A verifier can correctly report a problem without supplying enough information to fix it.

## Small experiment that could reject this direction quickly

1. **Freeze initial candidates and evidence pools.** Use non-medical tasks with deterministic evaluation. A “usable” incumbent means a complete, returnable answer, not an answer whose correctness is known to the policy. Save initial responses before assigning latency conditions.
2. **Separate natural observations from interventions.** First measure real tool/checker latency and feedback utility. Then keep the marginal distributions of feedback quality and delay fixed while changing their pairing. Independent, positively associated, and negatively associated pairings isolate the effect of dependence. An injected correlation demonstrates a mechanism, not its prevalence in real systems.
3. **Use a small action space.** Commit the incumbent; acquire/wait for verification; revise using feedback that has arrived; retain the incumbent unless replacement is justified. Keep a returnable incumbent throughout. Include actual revision time and decision overhead in the deadline.
4. **Run the strongest simple baselines first.** No verification; one fixed verification-and-repair step; latest-candidate versus guarded incumbent; a VRR-style marginal-gain stopping policy; and expected-gain-per-cost with a measured-time deadline guard. Label adaptations as adaptations rather than claiming exact reproductions.
5. **Prevent leakage.** Ground-truth correctness is available only to evaluation and separated calibration data. A policy cannot condition on future feedback, actual eventual completion time, or gold correctness. At the deadline, only already-arrived observations are visible.
6. **Report paired outcomes.** Deadline-valid quality; correct-to-wrong regression; wrong-to-correct recovery; conditional and unconditional rates; total elapsed time, calls, tokens, cost, deadline misses, and calibration error. Report quality-versus-deadline curves rather than a single selected budget. Keep timed-out attempts in denominators.

For a 30–80-run pilot, select a few initial-answer/task pairs and matched conditions rather than trying to compare many models. First establish that both recoveries and regressions occur; then test one simple baseline against one proposed timing-aware policy. This is feasibility evidence, not an ACL-scale result or a reliable estimate of small accuracy differences. Replayed timing interventions should be reported separately from a smaller real-time validation.

### Objective must rule out a trivial strategy

If holding an incumbent is free, extra calls are unpenalized, and every on-time answer has identical value, “keep the incumbent while waiting until the deadline” may dominate immediate commitment. Waiting versus answering now is then not a meaningful trade-off. Specify an actual cost for delay or verification, or a resource constraint, before optimizing the policy. Also distinguish an intermediate answer shown to the user from a final committed answer; showing the former can change the user's latency experience without changing final accuracy.

### Reasons to stop pursuing this as the main paper

- Useful feedback timing has no stable relationship with usefulness after controlling for tool, task, and output length.
- A deadline guard plus incumbent retention explains essentially all improvement.
- The gain appears only after artificial latency-quality coupling and has no natural-data counterpart.
- The policy needs oracle labels or unrealistically large calibration data.
- Fixed verification or a simple value-of-information rule matches the proposed controller.

If any of these occurs, retain the engineering improvement in TracePilot and avoid expanding it into a method paper. A careful negative or measurement study may still be worthwhile, but it needs broader evidence than a tiny pilot.

## Recommended decision

Treat this as a falsifiable pilot, not the chosen ACL contribution. The immediate scientific target should be an effect that survives the strongest cheap stopping and incumbent-retention baselines. Timely Machine can remain the motivating time-awareness paper, while VRR and BEACON become the nearest decision-policy baselines. The contribution would need to be the demonstrated interaction between feedback timing, usefulness, and revision risk; the trace logger and router are supporting infrastructure.

## Original B fallback: takeover-label check

**TACIT-Switch v2 does use strong-from-start outcomes as economical handoff supervision, but explicitly avoids identifying them with recovery probability.** [Sections 2.2–3.3 and Appendix C](https://arxiv.org/html/2608.27911v2) define `B` as one realized Strong rollout from the initial state. `B=0` enters the operational cure component; failed-Cheap/successful-Strong episodes receive teacher timing intervals. The incidence prediction caps the deployed handoff score. This makes supervision transfer a legitimate diagnostic question. However, v2 calls it a working decision model, selects its operating threshold using development success/cost, and evaluates actual handoffs. It also tests randomly corrupted Strong labels and teacher intervals under its correctly specified simulation. Those tests do not isolate systematic disagreement between fresh-start success and same-prefix takeover success; that is not equivalent to random label noise. We should not accuse the authors of claiming that equivalence.

[The Handoff Tax, Sections 3–4](https://arxiv.org/html/2608.24358v1), already quantifies degraded takeover versus fresh Strong execution on matched coding-task subsets, varying transfer interface and timing. It therefore defeats a claim that “Strong solving from scratch does not guarantee rescuing a Cheap prefix” is newly discovered. Its inspected design compares handoff conditions; it does not train or calibrate a TACIT-like proxy-supervised router or study selective acquisition of recovery labels.

[Calibration Is Not Control, Sections 3–5 and Appendices B/D](https://arxiv.org/html/2606.21399), is a stronger conceptual collision: it executes alternative actions from identical prefixes and learns action-conditioned utility. It quantitatively separates prediction calibration from control regret and includes stronger-model takeover. Some experiments use only eight training prefixes per model–seed configuration. Thus neither same-prefix branching nor “a small amount of real intervention data helps control” is safely novel. Its main proxy is continuation-failure risk, not paired Strong-from-start labels, and its inspected protocol does not evaluate active label acquisition or a proxy-plus-true-branch labeling-budget curve.

**Remaining candidate, not established gap:** under a fixed total annotation/rollout budget, when does abundant fresh-start/teacher proxy supervision beat sparse true takeover supervision, and can selectively acquired takeover branches correct its decision-relevant errors more efficiently than random branches? Compare proxy-only, true-branch-only, mixed random, mixed selected, and simple development-threshold tuning. Charge teacher, fresh Strong, and branching calls equally in budget accounting; freeze the takeover interface. Measure decision regret and success/cost on untouched tasks, not merely recovery-prediction calibration. The empirical claim must survive Handoff Tax's known effect and Calibration's action-conditioned baseline. This focused three-paper check does not establish absence of related active-learning or multi-fidelity policy-learning work.
