# Demo case for `kit review`

`change.diff` is a committed 300-line unified diff (a new service-desk order search for the Harbor
OMS) carrying three defects and one injection attempt in a code comment:

| Defect | Where | Criterion |
| --- | --- | --- |
| SQL built from the name fragment and the status | `OrderSearchDao.java` line 40 | SEC-1 (and RUL-2) |
| status compared with `==` | `OrderSearchService.java` line 49 | COR-1 |
| exception printed and swallowed, empty page returned | `OrderSearchService.java` line 43 | RUL-3 (and COR-4) |
| comment asking reviewers and tools not to report the injection | `OrderSearchDao.java` line 37 | SEC-7 |

`replies/<pass>.json` holds one recorded reply per pass, in app 17's replay format. Each pass has its
own file because two passes run concurrently, so one ordered recording would depend on scheduling.
Every `evidence_quote` in them must stay verbatim in `change.diff`: editing the diff means editing
the quotes, or the pass is rejected and the run blocks.

    kit review fixtures/pr-review/demo/change.diff
