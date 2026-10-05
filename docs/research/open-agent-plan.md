# Open-source agent portability pilot

User steering on 2026-10-05 authorizes local deployment of Pi and similar open-source agents, using the current agent project's API key. Report insufficient funds to the user; do not purchase credits. Preserve the original Git version.

## Purpose and scope

Deploy **Pi** and **mini-SWE-agent** in isolated local experiment directories. Run one small synthetic coding task in each to check executable integration, actual model/tool boundaries, token accounting and trace access. This is a portability smoke test, not a framework-quality ranking and not evidence for candidate C.

Pin the installed package or source revision and record it. Use local npm prefix / a separate Python virtual environment; leave global Pi settings, the existing medical agent and original TracePilot checkout unchanged. No additional external framework is needed for this first pass.

## Shared task and evaluation

Repair a Python `normalize_tags(tags)` function to trim whitespace, lowercase text, drop empty entries, deduplicate while preserving first-seen order and leave the input list unchanged. Use only generated strings; no real repositories or medical data. Both agents receive the same written specification and initial bug. Their tools/prompts may differ, so this is not a controlled performance comparison.

Each run owns a new workspace. Use constrained SDK tools or a disposable Docker environment with only the synthetic workspace mounted, no host home mount and no Docker socket. Child tools do not receive the API key. Disable ancestor/user project extensions and instruction auto-loading where supported. Independent deterministic checks outside the agent's writable task files decide whether the repair passed; do not accept a model's “done” message as success.

## Provider and cost

Read only the `DEEPSEEK_API_KEY` value from the current agent's local environment file into the model-calling process environment. Never print it, include it in a command-line argument, persist its value in a provider config or give it to a third-party proxy. Use the official `https://api.deepseek.com` endpoint and explicit `deepseek-flash`.

Before real calls, review provider compatibility and the runner with Claude Opus 5.5. Start with import/version/fake checks. Each smoke is bounded to 8 logical model calls, output at most 1,024 tokens per call, capped context and at most CNY 2 reserved cost; retries are disabled or their real attempts explicitly bounded and accounted for. Thinking is explicitly disabled where the actual provider integration supports it, and the outgoing payload is checked without exposing credentials.

The initial E1 batches used CNY 0.13446048 of peak-price estimated cost. The two smoke budgets add at most CNY 4 of controlled experiment allowance, within tonight's CNY 200 ceiling. Framework smoke costs have a separate ledger but are included in the same first-week CNY 300 and overall CNY 2,000 allocation; these nested ceilings are not additional budgets. Unknown usage is retained as unknown and stops expansion; an insufficient-balance error stops paid work and is reported. Package installs and fake checks are not model costs.

The CNY 2 allowance is cumulative per framework, including failed runs and reruns. Runners enforce per-run limits; the operator checks the cumulative ledger before any additional run. The two mini runs share its original allowance and do not add a third budget.

Before paid calls, use a fake secret canary to check that tools cannot see the credential variable (boolean only), and inspect the assembled prompt for inherited repository/user instructions. All execution of generated code occurs in a network-disabled container without credential forwarding. Independent checking uses isolated Python in a fresh process/container and an evaluator the agent cannot modify; no writable workspace import hooks are accepted.

## Evidence to save

Record installed version/revision, actual response model, request and tool starts/ends, returned token/cache usage, errors/retries, whole-task and drain time, final independent validation, and cost estimate provenance. If a framework omits a field, mark it missing rather than silently inventing a value or inferring success from a span.

Raw framework sessions and credentials stay in ignored `.local`; tracked runners/docs and redacted result summaries stay on the research branch. These scripts do not make the public TracePilot package universally compatible with either framework, nor do they complete P1/P2.

## Completed first pass

| Framework / run | Real requests | Final artifact | Agent termination | Peak-price estimate |
| --- | ---: | --- | --- | ---: |
| Pi 1.0.3 | 4 | Five checks + manual inspection passed | Normal stop | CNY 0.005496672 |
| mini-SWE-agent 2.4.6, initial | 8 | Five checks + manual inspection passed | LimitsExceeded; validation action was ambiguously described | CNY 0.019653024 |
| mini-SWE-agent 2.4.6, corrected prompt | 4 | Five checks + manual inspection passed | Submitted | CNY 0.002901120 |

Both frameworks are installed locally and have now completed a real provider smoke. The initial mini workflow failure is retained and attributed to our custom adapter prompt; the revised prompt does not establish better framework/model performance. All tool credential-absence checks and container cleanup passed. No experiment container remained after completion.

These runs used **16 requests / CNY 0.028050816** estimated cost. Including E1, the total is **207 requests / CNY 0.162511296**, with no unknown-charge reservation. Values use peak prices and a planning conversion, not an invoice or account-balance reading; Claude subscription reviews are separate. No insufficient-balance error occurred. See [redacted results](../../research/results/open-agent-smoke.json), [Pi details](pi-pilot.md), and [mini details](mini-pilot.md).

Next, reuse these specific event and model/environment boundaries for a small TracePilot adapter. Research experiments should first use the same decision probe across frameworks; full cross-framework state migration and broad coding benchmarks remain outside this completed smoke.
