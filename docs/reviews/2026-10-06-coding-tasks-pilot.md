# Coding task bridge and first-draft preparation review

Actual Claude CLI reviews `coding-tasks-review-20261006` and `coding-pilot-delta-review-20261006` completed with exit 0, `is_error=false`, model `claude-opus-5-5`; no cost or turn caps. Raw results remain under ignored `.local/overnight/`. Latest result SHA-256: `6756e83225ea10feaca39f480406d26b6c3cf2117e5625501749fb42b8765d87`. The reviewer assessed supplied files without tools; execution evidence was verified by root.

## Current feature verdict

No blocker for committing the zero-model preparation feature. Paid entry remains refused, both by admission and MockTransport-only generation. This does not authorize real coding calls, a complete EvalPlus claim or R3/R4 completion.

Initial findings addressed: ready handshake; surrogate serialization; fresh output ownership; safe public syntax/exception diagnostics; verified-byte oracle loading; explicit parent-input /32 comparison difference. The official selected source computes residual on post-call mutable inputs; this bridge uses original parent inputs. Canonical 881/888 is measured by this bridge, not a full official evaluator reproduction.

## Disposition before paid integration

1. Candidate exit codes 125–127 after ready must remain candidate failures; container disappearance before cleanup must be classified separately as infrastructure. These are pending paid-path fixes, not current capability claims.
2. All 16 deterministic request reservations must be checked before any dispatch, using the actual transport calculation; reject the whole plan if a slot or total fails. The eventual paid session must hold the single study lock and inherit all prior cost.
3. The reviewer lacked transport source. Root inspected it: CancelledError and network/HTTP/usage failures call `_uncertain`, which sets stop_reason and retains the reservation, and the pilot checks this before each next slot. Thus the alleged continuing-dispatch path is not established for the current pinned transport. A focused timeout check is appropriate with paid integration; no extra real model call is needed.
4. Protocol wording now permits offline scoring after generation/HTTP closure even with unknown cost. Unknown obligations remain charged to the study and stop further model calls; they never become free attempts.
5. Cache-hit usage must be reported separately; repeats are not an intrinsic speed estimate. Timeout is distinct from fail. Whole-worker limits and the non-tamper-proof worker are retained limitations.
6. Unsupported output classification, duplicate exception tables, exact-task atol/type guards and malformed response shapes are scoped robustness follow-ups, not reasons to build a general judge framework. Record Python runtime before any live generation.

## Evidence and document corrections

- [Task checks](../../research/results/coding-tasks-validation.json): initial 27 Docker cases and the distinct 11-case delta, hashes kept separately; original /0 regression provenance limitation disclosed.
- [First-draft checks](../../research/results/coding-pilot-validation.json): six fake-HTTP scenarios; generation/public/hidden phase ordering and 22/22 container/worker cleanup verified. Actual model calls and costs are zero.
- [Timely v2](../../research/results/timely-r2-small-v2.json): stage wording now says stopped after 1/24; R3 must use the SAME cumulative study. Costs and counts cross-checked.
- README and agent.md now describe the eight-task and 16-slot preparation without claiming paid or deadline results. Public artifact paths were made relative.

The raw 27-case suite did not rerun after every small delta; each result applies to its recorded source hashes. Further paid-path changes require targeted checks and an actual Claude delta review before live calls.
