# Pi SDK portability smoke

Status: fake and live end-to-end smoke runs verified on 2026-10-05. Initial Claude review conditionally permitted the bounded smoke after explicit follow-ups. Both code fixes were applied and fake-verified before the paid run; the later delta review confirmed those changes without blockers after the live run. This checks integration and instrumentation, not framework quality or the timing research hypothesis. Shared scope: [open-agent-plan.md](open-agent-plan.md).

## Verified source and local installation

The old official repository [badlogic/pi-mono](https://github.com/badlogic/pi-mono) redirects to [earendil-works/pi](https://github.com/earendil-works/pi). The npm registry marks `@mariozechner/pi-coding-agent@0.73.1` deprecated in favor of `@earendil-works/pi-coding-agent`. This smoke pins the current official package **1.0.3**, rather than installing the obsolete namespace. Its Node requirement is >=22.19; the tested host is Node 24.19.0.

Local install, from the isolated research worktree:

```powershell
npm.cmd install --prefix .local/oss/pi --cache .local/oss/pi/npm-cache --ignore-scripts --save-exact --no-audit --no-fund @earendil-works/pi-coding-agent@1.0.3
```

No global npm installation or Pi configuration was changed. The npm lockfile freezes the resolved dependency graph in ignored `.local/oss/pi`; each run records its hash. npm installed 121 packages without lifecycle scripts. SDK usage was checked against the pinned [full-control example](https://github.com/earendil-works/pi/blob/v1.0.3/packages/coding-agent/examples/sdk/12-full-control.ts), [factory source](https://github.com/earendil-works/pi/blob/v1.0.3/packages/coding-agent/src/core/sdk.ts), and installed declaration/source files.

Python validation uses the official image pinned to:

```text
python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4
```

Docker Engine 29.7.2 was available. The pinned image was downloaded before the smoke. The runner uses `--pull never`, so missing images fail before model work.

## Runner and isolation boundary

Run [pi_smoke.mjs](../../research/agents/pi_smoke.mjs):

```powershell
node research/agents/pi_smoke.mjs --version
node research/agents/pi_smoke.mjs --dry-run
```

Default mode is also dry-run. Paid execution, **only after review**, is:

```powershell
node research/agents/pi_smoke.mjs --execute-paid
```

The coordinating process supplies `DEEPSEEK_API_KEY` through the child environment. The runner does not read another project's files or accept a key argument. Provider configuration uses the environment-name reference `$DEEPSEEK_API_KEY`; the key is not saved. In fake mode it replaces that variable in its own process with a public fake canary and never calls the network.

Each invocation exclusively creates a new directory under `.local/oss/pi/runs/`, including `workspace`, `checks`, and `config`. It copies the shared `fixtures/tags.py` and `task.txt`. Output directories cannot be reused. `PI_AGENT_DIR` points to the invocation's config directory, `PI_OFFLINE=1`, model-catalog refresh is disabled, and session/settings storage is in memory.

An explicit resource loader returns **no extensions, skills, prompt templates, themes, or AGENTS/CLAUDE context files**. The runner verifies the effective SDK system prompt consists of its own prompt plus the SDK's workspace `<cwd>` block. Active tools must be exactly:

- `read_tags`: reads only the fixed `tags.py` path.
- `write_tags`: overwrites only that regular file; accepts no path parameter and caps source length.
- `validate`: executes fixed external checks in a disposable Docker container.

No built-in shell or filesystem tool is active. Tools are sequential. Generated Python is never executed on the host. Containers have no network, no key, no Docker socket or home mount, a read-only root filesystem, read-only mounts of the owned workspace and separate checks, an unprivileged UID, no capabilities, and bounded CPU/memory/PIDs. Python runs with `-I -B`; only `/work` is added to its import path. The model cannot modify the check file through any tool. A fixed UUID container name allows cleanup after a Docker CLI timeout.

This constrains the model's tools. It does not claim that a Node SDK process itself is an OS sandbox: that trusted process holds the provider credential. It uses no arbitrary extensions, and unexpected implicit fetches are denied.

## Request, accounting and lifecycle limits

The real Pi agent loop and Pi's native OpenAI-compatible serializer/SSE parser are used. A provided SDK `fetch` override checks the exact endpoint `https://api.deepseek.com/chat/completions`, payload/model, input bound, and attempt budget before dispatch. It verifies Authorization equals the resolved environment key and records only the boolean. Redirects are rejected. An unexpected or missing live response model stops the run without applying Flash rates to that response. Actual HTTP attempts, not merely logical turns, are capped at 8. Output is fixed at 1,024 tokens and thinking is explicitly `disabled`; temperature is 0.

Framework retry, provider retry and HTTP SDK retry are zero. Compaction, cache warming, analytics and install telemetry are disabled. A 24,000-ASCII-character serialized payload ceiling reserves 25,024 input tokens per request: the extra 1,024 is an input-framing margin, separate from the 1,024-token output allowance. The request reservation charges every input token at cache-miss price plus maximum output: USD 0.30/M input, 0.006/M cache hit and 1.20/M output, using **8 CNY/USD as a conservative planning conversion**. The cap is CNY 2 for this agent. These are peak-price estimates, not invoices.

Raw provider usage is required; `stream_options: {include_usage: true}` is set explicitly and checked before reserving or dispatching a request. Pi's default zero-filled usage is not accepted as proof of zero cost. Unknown or inconsistent usage retains the full reservation and stops the run. A 402 response produces `insufficient_balance` and stops; no credit purchase is attempted. Streaming/API errors are recorded without exception bodies or authentication headers.

Requests have a 60-second abort signal and the run has a 180-second abort timer; synchronous, bounded Docker execution can delay the JavaScript timer. Containers have a 15-second CLI timeout, explicit cleanup, and a subsequent exact-name inventory check. A failed absence check stops the run and leaves the owned UUID name in the ledger. This is not a hard real-time guarantee. Subscriptions are removed and the session disposed in `finally`. The event writer is synchronous and capped at 1,000 records; token delta events are not retained.

## Recorded evidence

Every run stores `manifest.json`, `events.jsonl`, `summary.json`, the repaired task file and immutable check source in ignored `.local`. The manifest freezes version/lock/script hashes, task, system prompt, tools, costs and limits. Events capture outgoing payloads without headers, actual response model, request starts/completion/duration, raw-backed token/cache counts, framework usage for comparison, stop reason, tool starts/durations/results, and independent final validation. Unknown values remain unknown.

The final validation is run independently after the Agent finishes, unless a container cleanup failure has already stopped the run; an assistant's success claim is insufficient. Cases check whitespace, lowercase, empty removal, first-seen order, deduplication, a new returned list, nonmutation, and a `str.lower` case distinct from casefold. These checks are not an adversarially robust evaluator: generated Python runs in the same interpreter as the checks and could attempt to manipulate their execution or output. Manually inspect the final `tags.py` before accepting the repair.

Latest complete no-cost evidence:

```text
.local/oss/pi/runs/1791211419190-35ddb18a-8617-461a-af14-f6d3667447d9
```

The fake SSE transport passed through the actual SDK: **4 simulated requests, 3 tool executions, final five-case validation passed**. The initial buggy file failed validation. In both initial and final containers, `api_key_absent` was true while the host smoke process contained a fake API-key canary. Every simulated Authorization check and every container absence check passed. The effective system prompt and exact three-tool allowlist passed checks; no ancestor instruction file was loaded. The fake estimated cost is bookkeeping only and is not a paid expense.

Two initial no-call fake attempts caught an overly strict system-prompt equality assertion: the SDK appends its own workspace block. The assertion now permits precisely that block and still rejects additional discovered instructions. Those failed attempts remain in local records.

Live smoke evidence (including subsequent delta review):

```text
.local/oss/pi/runs/1791211514791-ed66d216-e89e-49f9-8b2c-c542493505dc
```

The live run made **4 requests and 3 tool executions**, repaired the initially failing file, and passed all **5 independent final validation cases**. Every response identified `deepseek-flash`; the final model stop reason was `stop`, with no runner stop error. Whole-run elapsed time was **7.3036642 seconds**, including initial validation and cleanup. Recorded cost was **CNY 0.005496672**, using the peak-price estimate and planning conversion above, not an invoice.

All four requests reported known provider usage and passed the Authorization equality check; no unknown in-flight usage remained. Validation confirmed the API key was absent inside containers, and all three container cleanup checks verified absence. The final `tags.py` was manually inspected: it uses `strip()`, `lower()`, a `seen` set and a new result list; it contains no imports or validation manipulation.

## Verification scope

The pinned SDK, guarded transport, official provider and constrained tool configuration completed this one live task. This is integration evidence only: it does not establish general provider compatibility, framework quality, latency distributions or the timing research hypothesis. The non-adversarial validator limitation and final-source inspection requirement still apply to subsequent runs.
