# Tests and coverage criteria

Applied by the tests-and-coverage pass, which also sees what the earlier passes recorded.

## TST-1 | minor | New behaviour with no test in the diff
A new public method or a new branch of existing behaviour that no test in the diff exercises. A bug
fix with no regression test that fails before the fix is the strongest form of this.

## TST-2 | major | A test that cannot fail
A test that asserts nothing, asserts only that no exception was thrown where a result is
expected, compares a value with itself or with the output of the code under test, or catches the
exception it is meant to detect.

## TST-3 | minor | Boundaries not covered
Paging, limits, empty input and the largest accepted size are changed or added with tests that only
use a value in the middle of the range.

## TST-4 | major | A test removed or disabled alongside the code it covered
`@Disabled`, `@Ignore`, a commented-out test or a deleted test file in the same diff as a change to
the behaviour it checked.

## TST-5 | minor | A test that depends on the environment
A test that needs a real network, database, clock or filesystem location and does not isolate it.
