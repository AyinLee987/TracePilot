# R3 deadline implementation review

Date: 2026-10-06. Online execution and offline scoring have completed the focused fixes, validation and actual Claude reviews below. No real R3 model request has been dispatched at this implementation commit. Final zero-provider calibration fixes deadlines at 5/15 seconds and the request guard at 64. The preceding 32 first-draft results remain unchanged.

## Protocol review

The actual Claude CLI completed the protocol-only review with exit code 0, `is_error=false`, and `modelUsage` identifying `claude-opus-5-5`. Private source snapshots, hashes and the response are retained under `.local/overnight/coding-deadline-protocol-review-20261006.*`. This review does not certify implementation or real-model results.

| Finding | Disposition |
| --- | --- |
| A 12-request guard could selectively censor the faster model | Replaced before any R3 model call with `max(64, ceil(D_long / min_prior_HTTP_duration) + 2)`. Report actual guard hits; the observed minimum is not a future lower bound. |
| The reviewer interpreted the batch as reserving every future request slot | Clarified the existing two-level accounting: reserve the CNY 120 study guard once; transport reserves only each actual request and releases unused reservation when its usage is known. Do not reserve `144 * max_rounds * 0.20`. The implementation and joint fixture must confirm this interpretation. |
| Public-check saturation limits the feedback comparison | Keep the full native matrix and add the prespecified attempt-1 failure stratum. With fewer than three task groups in that stratum, report cross-task feedback inference as unsupported; do not treat a null result as proof that feedback is ineffective. The common-state experiment remains a single Flash-source case. |
| The overhead term had an ambiguous measurement unit | Define nonoverlapping `setup_once` and complete `round_other`, including helper overhead outside the checker. The calibration uses measured fake waiting, real public checks and actual lightweight admission. |

Additional accepted changes distinguish attempt 1 from the first eligible answer, record snapshot callback/persistence lag, preserve cache usage, separate costs before/after selection and late in-flight requests, freeze RNG ordering, and fix the later held-out tool delay at two seconds. Public timeout feedback is usable only after its result and cleanup are available before the deadline. Held-out checker preparation precedes any held-out model calls.

The suggested automatic continuation after transient failure is not implemented. The existing stop-and-preserve rule remains explicit: retain the complete planned denominator and do not replace started trajectories. No failed game or coding history is deleted or relabeled as success.

## Implementation review and validation

The actual Claude initial source review completed with exit code 0, `is_error=false`, and actual model `claude-opus-5-5`; its private evidence is `.local/overnight/coding-deadline-runtime-review-20261006.*`. It found one blocking preparation issue and several important fixes. The table records the requested changes; the later validation and reviews below establish their disposition:

| Finding | Required disposition before paid execution |
| --- | --- |
| Static preparation failure can consume the only stage and hold CNY 120 despite zero dispatches | Run credential, input, seed, daemon and image preparation before the study reservation; verify preflight failure preserves the unopened stage. |
| Per-request money/size guard stops all later trajectories | Censor only the affected trajectory; distinguish batch exhaustion and known orderly stops from unknown or interrupted accounting. Preserve already eligible candidates. |
| Recovery Docker commands block the event loop | Use owned bounded asynchronous subprocesses for exact-resource recovery. |
| Calibration admission trusts claimed quantiles | Recompute from hashed old records and new calibration measurements; reject inconsistent values. |
| Missing execution CLI and fixed 64-round preparation | Add the explicit paid study entry and derive the guard from the calibration before final calibration/review. |

The first focused repair check passed five scenarios: missing credentials and daemon failure are refused before the reserve, and each of the money, message and feedback guards preserves the first eligible candidate while allowing subsequent rows. A separate seventeen-case numerical verifier check read the 104 historical source files and reconstructed their 32 HTTP/31 public durations; its new-loop measurements were explicitly synthetic. This validates arithmetic and source-drift rejection, not the still-pending real loop calibration. The expanded study/guard joint run and asynchronous recovery checks remain separate gates.

The first offline executor revision passed nine focused scenarios with fake HTTP and fake judging. The real study-admission joint fixture subsequently passed sixteen checks with fake HTTP/judging, covering known settlement, second-request unknown usage and an unclosed-resource terminal. It preserves 144 planned rows while selecting only two fixture trajectories; it does not execute 144 scientific trajectories.

A later executor revision passed three real Docker checks: a canonical answer, bounded direct-file-descriptor output flooding and a 30-second public timeout that returns after both cutoffs. All three containers and workers closed. The timeout result was ineligible at both cutoffs. A separate real cancellation check used a 12-second outer timeout and 180-second cleanup grace: the helper, container and parent group closed in about 13.1 seconds. These observations do not calibrate complete online overhead. Final source hashes and any fixes will be recorded here before paid execution.

The independent read-only timing review identified two integration checks to resolve: calibrating against the whole `client.send` interval can omit its local wrapper overhead, and the old owned-child launcher's default two-second cancellation grace is shorter than the public helper's cleanup allowance. Neither observation is treated as resolved solely by this document.

See the [implementation contract](../research/coding-deadline.md) and [preceding coding results](../research/coding-extension16-results.md).

## First delta review

The actual first delta review completed with exit code 0, `is_error=false`, and actual `claude-opus-5-5`; evidence is `.local/overnight/coding-deadline-delta-review-20261006.*`. It found no new paid-accounting safety blocker and confirmed the initial preparation, local-guard, known-cost, asynchronous-recovery and execution-entry changes in code. It identified two further actionable semantic issues: resample must not project feedback it never consumes, and repeated process signals must not cancel cleanup twice. Both are fixed in runtime `29b3bd27`; the final focused evidence below includes the affected paths.

Two conditional findings were checked against the unchanged dependencies. `timely_transport.parse_usage` requires integer cache-hit/miss fields, so a missing cache field already becomes unknown usage before the executor can receive a known response; no missing-as-zero fallback is introduced. `sandbox.command` captures subprocess output, and `run_worker` supplies explicit pipes, so the hypothesized separate Docker client inheriting the helper's output pipe does not match this implementation. `runtime_identity(require_wsl=True)` adds validation without changing the returned identity fields. Calibration evidence must remain present through final settlement.

The reviewer warned against retrying a timing-censored calibration until one passes. The first complete measurement on runtime `fb516003` included all 16 paths and 32 rounds, without censoring; it is preserved and is not a selected passing retry. The protocol now explicitly permits only one planned calibration on the final source version and rejects a timing-censored attempt rather than selecting another. The required resample/signal fixes create a new source version and therefore require a separately recorded calibration. The suggested 120-second per-trajectory idle window is not adopted; no timing-censored measurement is dropped or replaced.

Independent source inspection also caught the calibration verifier confusing the legacy `paid_call_count` alias with real provider calls. The alias counts Mock dispatches too. The original seventeen-case synthetic fixture is preserved with this limitation; the corrected verifier passed twenty-two checks including nonzero Mock alias acceptance and inconsistent-count rejection. Zero-provider provenance now uses the frozen Mock-only path, offline network guard and independently recorded synthetic wait intervals. Real calibration evidence still requires separate verification.

## Final online review and calibration

The final focused review completed with exit code 0, `is_error=false` and actual `claude-opus-5-5` (`coding-deadline-final-review-20261006.json`). It found no online runtime correctness blocker. Its evidence objections were addressed: two validation command labels now match the actual CLI (`--blind-diagnostic`, `--stuck-helper`), and final-source single outer SIGINT, pre-exec helper recovery and the five preparation/guard scenarios all passed. The single SIGINT check closed its helper/container/outer group in 13.196 seconds. Double-signal and stuck-helper checks are separately retained; the latter intentionally shortened production waits and does not claim a 240-second timeout was observed.

The joint study fixture passed 25 checks covering known settlement, unknown fees, unclosed resources, local request/message/feedback guards and known orderly stops. A separate four-check preflight/retry fixture confirmed that a failed static preparation consumes no reservation and leaves the same stage available. All were zero-provider executions against isolated fixture history.

The final calibration contains all 16 setup samples and 32 complete real-public-check rounds with 48 synthetic HTTP responses and zero timing censoring. All 32 helper groups and 32 candidate containers were confirmed closed. The raw calibration hash is `8adbc784b90c026ca30c459ebe010e3e388506093b747a259bba253bc81131e1`; the online runtime is `29b3bd2704128dc91c39f3a20b82f7aa2ce13d8a3920fa25637ead55ea684d9b`. Numerical details and the resulting 5/15-second cutoffs appear in the protocol. The earlier complete and interrupted calibration records remain retained; neither authorizes this final source.

Independent read-only verification reconstructed all 104 historical source files and the final 16 setup/32 round measurements, confirmed current runtime/study/verifier hashes, and returned `verified=true` with identical deadlines and guard. Its retained receipt is `.local/overnight/r3-final-calibration-verification.json`, SHA256 `9e05ccf3b661f5ceb954578c206cc65a71b463134097ab707839ae613ee4ef45`.

Accepted limitations from the review are explicit in the protocol: signal interruption during resource-free synchronous accounting fails closed; fake HTTP does not reproduce TLS/provider latency; offline-guard flags are generator self-reports, with generator hashes recorded separately rather than added retroactively to the admission contract. No calibration was retried to obtain a faster passing result. Timing censoring alone cannot justify a new version or a wider-window retry. These are engineering validation results, not 144 completed model trajectories.

## Offline scorer review

The same final review found a real classification bug: no candidate was labeled `not_evaluated`. It also requested direct integration with real runner output, interruption propagation/precise cleanup, a global-study lock check and image identity binding. These changes passed eleven focused checks, including actual admission/executor normal settlement and cancellation-stop outputs fed to inventory and fake hidden scoring. They used no API or Docker; existing real-checker evidence is versioned separately.

The initial fake-scoring fixture passed 22 checks. A separate synthetic terminal input exercised the real hidden checker on five candidate identities, using ten containers; all closed, the source directory stayed byte-identical and the complete 144/288 denominators were retained. This real-checker smoke does not replace runner-output integration. Its first attempt under the default WSL user failed before any candidate container because that user lacked Docker socket access; the successful invocation used the already established WSL root identity without changing permissions. Both records remain local.

The scorer-only delta review completed with actual `claude-opus-5-5`, exit code 0 and `is_error=false`. It confirmed the S1-S5 fixes and identified one remaining cleanup branch: a checker that returns normally with incomplete cleanup must also invoke exact-container recovery. The three-line runtime correction passed the single `--missing-cleanup` simulated check: exact UUID removal/absence verification, worker closure and the infrastructure stop are all retained. The actual Claude cleanup-only review then completed successfully with `claude-opus-5-5` and no required changes. Final scorer SHA256 is `6ae5c1668d070bb3f322b88a619039639951659e23e40369f6345bb58911da76`; the default full suite was not rerun after this narrow change.

Two review limitations are accepted without expanding the implementation. The global-study lock is checked at scoring entry, so the single operator must not start any timed experiment while offline scoring runs; this is not a process-wide exclusion guarantee. The ten-container smoke belongs to the earlier scorer version; the first real scoring of the closed paid batch will separately validate the final image-binding/checker path. Current image/interruption checks are patched fixtures, not real Docker observations. Syntax-invalid candidates remain model failures, and hidden timeouts count as observed failures for adjacent fail-to-pass/pass-to-fail transitions; missing or infrastructure scores are unknown.
