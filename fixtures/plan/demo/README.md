# Demo case for `kit plan`

One task over `sample/legacy-oms/`, run planned first and executed directly from one forked
session prefix (statement 3.4), and a two-round refinement (statement 3.5). Every file here is a
recording: nothing calls a model and nothing needs the network.

    kit plan "Use bind parameters in OrderDao.findByCustomerAndStatus"
    kit plan "Use bind parameters in OrderDao.findByCustomerAndStatus" --refine

| File | What it holds |
| --- | --- |
| `plan.json` | the task, the system prompt, the shared two-turn prefix (a `grep` and a `read_file`), the **planned** arm (a read-only `grep`, then `exit_plan_mode` with the plan, then `propose_patch`) and the **direct** arm (`propose_patch` straight away) |
| `review-1/<pass>.json` | the reviewer's recorded passes over the direct arm's patch |
| `refine.json` | the second attempt: the opening it was recorded from, and its turns |
| `review-2/<pass>.json` | the reviewer's recorded passes over the second attempt's patch |

What the recording shows, and what it does not:

- The direct arm is cheaper (2 turns after the fork against 4) and **binds only one of the two
  values**; the planned arm checked what else used `java.sql.Statement` before planning, bound
  both values and removed the import. These numbers are a **recording**, not a measurement: the
  demo shows how the comparison is made and kept, not that planning always wins.
- Round 1 of the review finds SEC-1 and RUL-2 on the value still concatenated, and TST-1. Round
  2 resolves SEC-1 and RUL-2; TST-1 persists because the sample has no test tree. A round with no
  blocking finding prints `verdict: null`, which is not an approval.

Rules the command checks rather than trusts, with a test each in `tests/test_plan.py`:

- every `read_file` and `grep` result is verbatim from the sample, and every staged patch applies
  to it — so editing the sample means re-recording;
- the planned arm calls only read tools until its one approved `exit_plan_mode`; the direct arm
  presents no plan; tools outside `read_file`, `grep`, `list_dir`, `exit_plan_mode` and
  `propose_patch` are refused;
- `refine.json`'s `user_message` is exactly what the kit builds from round 1's recorded findings
  (task, then the previous patch and the findings, each fenced with the attempt's nonce). Change
  a round-1 reply and the command refuses the second attempt as stale instead of replaying it as if
  it answered other findings.

Sessions are written to `sessions/` (git-ignored) as the engineer running the command, so
`kit session list`, `resume` and `fork` work on all of them.
