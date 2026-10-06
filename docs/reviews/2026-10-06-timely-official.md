# Official Timely benchmark runner review

Two actual read-only Claude CLI reviews used `claude-opus-5-5`, exited 0,
and reported no blocking findings. No turn or cost cap was set.

- Initial review SHA256: `36a33d61a9b3a147be7f717dca3a3e4b80bf84104cb99022fc258d1e574c99c9`.
- Focused output-order review SHA256: `2bd261e1c4549d818d03a5a56003fa1baf2fadad1960a69b9a8f2473502bcbdb`.
- Reviewed runner: `67d26efaca9c0e3394e67b771011ab3371ae659388b2aa83ff3fc5f9948c9384`.
- Reviewed study module: `9fb5b7e60fde04b873ef27d3006ad292263b45f17609c432cdd3d24fd203cb87`.

Findings addressed: save settled records and close accounting before optional
aggregation; describe calibration per game/model; fix progress-document ordering.
Aggregation errors are retained in a separate file and must be checked when
publishing. A technical failure intentionally stops new dispatch without an
automatic retry; an interrupted sweep must not be reported as complete.

Actual E2E, WSL Python/Jericho with synthetic HTTP: four concurrent episodes
(valid, missing closing tag, no tool call, conclusion after one step) completed;
six invalid-call steps continued in the unchanged official loop. A separate
missing-usage case stopped and held its CNY 20 reservation. These are synthetic
accounting values, with zero API spend. Final artifacts are under the ignored
`.local/timely-official-check-release-20261006` and sibling failure directory.

The study migration received nine targeted checks, including terminal parent
cost recomputation, carry-forward, prepare/activate, and rejection of replay,
branching and source drift. Existing actual study cost is CNY 3.129782592.
Historical source bytes were archived before editing. Live evaluation is a
separate next step; these checks do not establish model performance.
