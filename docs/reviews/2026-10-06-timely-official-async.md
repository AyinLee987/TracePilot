# Timely continuous scheduling review

Actual read-only Claude CLI review: `claude-opus-5-5`, exit 0,
`is_error=false`, no turn or cost cap, no blocking finding. The review covered
the continuation and supplied helpers, not every imported implementation.

- Reviewed source SHA256: `8bf08c650375aef9c1fdcda79d7a55bf50708dd826eff7e452fe13037c69c35c`.
- Private review SHA256: `423773d676b7011085b33cc1bc15ffe8b71aca4d71d7a1a058f7375f194229c2`.
- Offline fixture SHA256: `68559ef028a12233a6f348b53e599defac10d6010f09a65834a7013b5a2e4959`.

Nine checks passed with real spawned processes and synthetic workers, no
provider calls: six-worker limit, refill before the slowest worker finishes,
one missing settlement without a rerun, all 384 records with opening costs,
preserved historical artifacts, repeat refusal, unknown liability with drain,
budget-limited concurrency of five, and calibration drift rejection before
writing the continuation supplement. This does not claim a new API/Jericho run.

Review disposition:

- Scheduler phase will be explicit per episode in the published CSV; the
  immutable dispatch prefix identifies the first 256. Mixed aggregates are
  labelled and cannot establish a scheduler or speed effect.
- `observed_commitment` catches missing-file errors and retains the caller's
  reservation floor. `official.append` permits an explicit continuation after
  the historical close; the offline fixture exercised this path.
- The cleanup receipt is deliberately bound to this one stopped coordinator.
  Its owner schema has no command field. PID/exit/cleanup, active study identity,
  original plan, and all 256 episode receipts were checked. This is a one-time
  continuation, not a general resume API.
- The original runner closes its batch journal and does not call a separate
  study settlement routine. The continuation follows that arrangement and
  writes separate combined results.
- Supplement creation makes execution single-use. A further interruption
  requires manual reconciliation; unresolved reservations remain held.

Actual read-only reconciliation found 256 closed episodes, 255 journal
settlements, and 128 undispatched rows. The missing settlement is episode 252
(CNY 0.104700672), not necessarily the last episode to be dispatched. Verified
batch cost is CNY 18.228416832; study known cost is CNY 21.358199424. All old
artifact hashes stayed unchanged during the checks. Paid continuation follows
commit and push.
