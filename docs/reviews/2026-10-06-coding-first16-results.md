# First 16 coding results review

This review covers the first real batch's redacted results and documentation only. The extension's source changes are excluded.

The first actual Claude CLI request returned a session-limit error with a 16:30 Asia/Shanghai reset. After that time, the retry completed with exit code 0, `is_error=false`, and actual model `claude-opus-5-5`. No cost or turn cap was set. The reviewer found no document submission blocker and independently checked the table arithmetic from the supplied rows; it did not execute experiments. Both raw responses remain in `.local/overnight/coding16-results-review-20261006*.json`.

Disposition:

- Clarified that /32 reference failures limit verdict interpretation. We did not adopt the stronger claim that every implementation must fail, which the observed reference failure does not establish. Per-input counts are retained without ranking models.
- Explained 12 reference executions as three tasks × four drafts, plus 16 public and 16 hidden candidate executions.
- Recorded that cleanup fields were merged from the separately hashed, read-only analysis report; the result constructor alone does not produce those fields.
- Added validation commands, current review status and source hashes to the progress entry. Local links were checked, and result hashes were matched against retained artifacts.
- Qualified source identity as the bytes used at execution, because extension work now changes the working source. Only this result and its related documentation are staged.
