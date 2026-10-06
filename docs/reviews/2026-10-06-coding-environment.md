# Coding environment review — 2026-10-06

Two actual Claude CLI reviews completed with exit 0, `is_error=false`, and `modelUsage=claude-opus-5-5`. Both were read-only, tool-disabled, uncapped reviews of supplied files and observed evidence; the reviewer did not run checks or independently fetch assets. No blocking finding for fixed HumanEval/0 preset preparation.

Initial important findings were fixed: explicit native WSL daemon checks precede mutations; asset bytes and expanded-source manifest are pinned; licenses use immutable commits; version evidence comes from the pinned official tag record; archive handles close. AutoRemove is verified and bounded precise cleanup remains. The root verified current source SHA against both observed summaries.

Delta review dispositions:

- Cleanup uses SIG_IGN, so a SIGINT arriving inside that window is ignored, not deferred. Corrected the review-description wording; the code/evidence already say ignored. A first interrupt in that short window may require a later interrupt. Real double-interrupt cleanup passed.
- AutoRemove/removal races can cause a conservative false failure. Keep this fail-closed behavior for the preset smoke; do not claim a robust general evaluator.
- Fresh remote archive/API byte changes can fail fixed hashes. Documented rather than weakening provenance.
- SIGTERM/SIGHUP or process death between create and start can leave an unstarted owned container; a started container has a 120-second PID1/AutoRemove fallback. Do not claim arbitrary termination cleanup. Any repair must use the exact recorded container name, never broad deletion.
- First asset setup is serial. Docker build CLI timeout does not prove server-side build cancellation. Neither issue is used as an R3 guarantee.
- Full candidate failure taxonomy, hidden/visible separation and EvalPlus timing remain explicit prerequisites. Hidden results stay offline; no raw worker output goes to a model.

Five main checks and nine delta probes passed without model/API spend. Hashes and redacted outcomes are in `research/results/coding-environment-validation.json`; raw evidence is ignored under `.local/coding-research-env/`. No R3/R4 completion or generated-code result is claimed.
