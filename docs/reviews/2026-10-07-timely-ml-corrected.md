# Timely ML corrected-batch review

Two actual Claude CLI reviews used `claude-opus-5-5`, verified in each JSON
`modelUsage`; both exited successfully and found no blocker. The first reviewed
the complete admission/cap change, the second reviewed the residual-container
guard and final protocol. No review cost or turn limit was set.

- Added a fail-closed Docker container check immediately before reservation.
  Both start and final scans use the same native WSL Docker context, `ps -a`,
  and `tracepilot.experiment=timely-ml` label. A real stopped owned container
  was rejected, removed, then the empty environment was accepted.
- Distinguished scheduler checks (fake HTTP, real Docker, historical opening)
  from copied-ledger checks (named successor and duplicate rejection). Real
  parent reconciliation still runs at admission; it is not claimed as an
  already completed E2E based on those fixtures.
- Clarified the per-batch request ceiling and prohibited concurrent Docker
  validation. The shared label is deliberately retained; external uncoordinated
  validation can still trigger conservative cleanup failure.
- Protocol bytes freeze at prepare; later status belongs in separate docs.
  Historical study source is checked at prepare/activate, not rechecked at run;
  this existing limitation does not change active source hash enforcement.
- Final wording specifies the exact container label. Portable verification
  evidence is in `research/results/timely-ml-corrected-validation.json`.

Raw reviews and exact source bindings remain under ignored `.local/overnight`.
The reviewer did not execute commands; runtime claims come from the separate
zero-provider checks. This review does not assert model quality or replication.
