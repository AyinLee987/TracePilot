# Coding extension16 review and validation

Scope: prepare one fixed extension batch, HumanEval /16, /99, /18 and /31 × Flash/Pro × two independent first drafts, under the existing cumulative study. The original first16 paid root remains unchanged. **No real extension16 model requests have run as of this record.** This is development sampling, not the shared-deadline or feedback-repair experiment.

The initial and delta Claude CLI reviews both completed successfully with `is_error=false` and actual model `claude-opus-5-5`. The final delta found no code blocker for submission or for an extension of the real known-settled first16 parent. These were source/evidence reviews; the reviewer did not execute the checks. Raw records and hash sidecars are retained at `.local/overnight/coding-extension-review-20261006.*` and `.local/overnight/coding-extension-delta-review-20261006.*`.

The current four changed files match the combined reviewed hash sidecars:

| File | SHA256 |
|---|---|
| `research/coding_pilot.py` | `2dae811e46810fd67621ccb997afef4e1bd99337018007d7ee9ff647e51c828a` |
| `research/coding_pilot_e2e.py` | `974aa1457c9eee0d7b22618e305729968864f6d81fafa2dc8f12d5a591b6e96b` |
| `research/timely_study.py` | `0748f5b138d301465eae49bf0f971b107960389bd8f390a5e05304063a8abf6d` |
| `research/coding_study_fake_e2e.py` | `37826be3db086ed3875676344c985e72f9e50327c7d6eaec8b0dac3b931f1b43` |

## Findings and disposition

- **N1, stopped/unknown parent:** fixed and reviewed. Extension now requires a known-settled parent. Rejected parents retain their existing liability and artifacts; they do not receive a successor.
- **C2, fixture isolation:** fixed and reviewed. Before study mutations, the fixture asserts that its patched registry is inside its own temporary tree and differs from the real study registry.
- **Parent summary identity:** fixed and reviewed. The summary's `paid`, `plan_sha256` and exact `output` path must match the parent plan/root.
- **C1, current extension checker:** verified with the current judge and sandbox bytes. The four unchanged canonical reference files passed public and hidden checks; all twelve container executions were cleaned and their CLI processes reaped. This verifies correct-reference execution, not the checker's ability to reject wrong solutions.
- **F1, rejection evidence precision:** accepted as a nonblocking limitation because rejection fixtures do not assert exact reason codes. Independent static inspection confirmed that `_coding_refs` contains only requests, result and generation-closed artifacts; the review's conjecture that summary/public tampering would be intercepted by that artifact set does not apply. Nevertheless, no branch-specific dynamic coverage is claimed without exact reason assertions.
- **F2, real parent compatibility:** independent read-only inspection confirmed that the historical summary's `paid`, canonical `plan_sha256` and exact WSL `output` path match. The actual `prepare-coding-extension16` operation will still enforce these checks. If it rejects, preserve the original paid artifacts and investigate the code/path contract; do not edit historical results to pass the gate.

## Verification evidence

| Evidence | Result | Actual provider calls | Docker executions |
|---|---:|---:|---:|
| Fixed-stage pilot fake E2E | 7/7 | 0 | 0 |
| Final study extension fixture | 21/21 | 0 | 0 |
| Current canonical reference smoke | 8/8 | 0 | 12 |
| Request reservation preflight | 16/16 accepted | 0 | 0 |

The pilot evidence is `.local/coding-research-env/first-draft-e2e/2daf6e8db43544d096aa877a0cc9b68c/summary.json`. It verifies original first16 ordering, extension16 ordering and rejection of arbitrary stages/task IDs or inconsistent frozen rows. Both stages retain the same request contract, parsing rules and failure policy.

The final study evidence is `.local/coding-study-fixture-m16fb5zu/summary.json`; it supersedes the earlier 19-check fixture for the changed study bytes. It includes actual `execute_admitted` control flow with MockTransport, the same cumulative budget, fixed sixteen requests and synthetic judge evidence. It is not a model or real-judge result. The F1 precision limit applies to its rejection checks.

The C1 evidence is `.local/coding-research-env/extension-reference-current/4d04ce87a2c2425d8e3897bfc6c27fb1/summary.json`. It uses `coding_tasks.py` SHA `1e40cb14195bab48b97a8c0e798ceb725a108b5c88431e8ee3c236f595d031ef` and `coding_environment_smoke.py` SHA `e249978226e7cf1833e1b04b532a8f5141e42ef2e1b93e233d0859d36dd4bc68`. Source is the original prompt plus canonical solution, without edits; each existing checker retains its 30-second timeout.

| Task | Public checks | Hidden checks |
|---|---:|---:|
| HumanEval/16 | 2/2 | 1005/1005 |
| HumanEval/99 | 4/4 | 715/715 |
| HumanEval/18 | 3/3 | 1004/1004 |
| HumanEval/31 | 7/7 | 167/167 |

HumanEval/31 did not time out; its hidden check took 1.263 seconds in this smoke. All twelve executions verified the existing native WSL Docker restrictions, recorded successful exact-owner removal and CLI reaping, and left no owned containers. The 109 artifact hashes recorded by the smoke were rechecked during packaging. This is a selected-task canonical smoke, not the complete EvalPlus evaluator.

Root's zero-API preflight is `.local/coding-research-env/request-preflight-3f200fbfe1d247a0b0d60d2d8c21730d/summary.json`. It accepted all sixteen requests with a summed reservation of **CNY 1.03196064**; the largest request is CNY 0.10373088, below the CNY 0.20 request cap. The whole-batch study reservation remains CNY 3.20. Dispatches, active calls and committed cost are zero. Root separately confirmed dotenv availability and credential format without exposing the key. This does not verify provider balance or response compatibility, and this packaging step did not read credentials.

Full source bindings, review identities, source artifact hashes, case counts, cleanup evidence and limitations are in [the validation record](../../research/results/coding-extension-validation.json). The zero-provider-call counts above describe validation runs; Claude review activity is recorded separately. F2 passed the independent read-only check; real prepare must enforce it before activation and execution. Historical source archives must remain available with unchanged bytes.
