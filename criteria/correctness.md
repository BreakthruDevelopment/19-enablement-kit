# Correctness criteria

Applied by the correctness pass to the code a diff adds or changes. Each entry names its own
severity; the reviewer never decides one. A finding must quote the line it is about.

## COR-1 | major | Reference equality where value equality is meant
`==` or `!=` on `String`, boxed numbers, `BigDecimal` or any other object where the code means "has
the same value". Comparing a status code or name this way works in a test with literals and fails
once the value comes from a database or a request.

## COR-2 | major | Arithmetic that truncates or miscounts at a boundary
Integer division where a ceiling is required (page counts, batch counts), an off-by-one in a loop
bound, a sublist range or a page offset, or a comparison that includes or excludes the edge value
the surrounding code needs. Quote the expression and say which edge goes wrong.

## COR-3 | major | Money computed in floating point
An amount of currency held or calculated in `float` or `double`, or rounded through one. Amounts are
`long` minor units or `BigDecimal` with an explicit rounding mode. Display formatting of an already
exact value is not a finding.

## COR-4 | major | A failure turned into a plausible result
A caught exception that returns an empty collection, a zero, a default or `null` so the caller
cannot tell "nothing found" from "the lookup failed". The failure must reach the caller or be raised
as a typed exception.

## COR-5 | major | A resource not closed on every path
A connection, statement, result set, stream or lock obtained without `try`-with-resources or an
equivalent that closes it when an exception is thrown or an early return is taken.

## COR-6 | major | A value that can be null is dereferenced
A return value documented or evidently able to be null (a map lookup, a nullable column, an optional
request parameter) used without a check, where a null is reachable from the diff's own callers.

## COR-7 | major | A state change that is not atomic
Two or more writes that must succeed or fail together, performed outside one transaction, or a
read-then-write on shared state with no guard against a concurrent change.

## COR-8 | minor | Dead or unreachable code introduced
A branch that can never run, a parameter or variable that is assigned and never read, or a method
that nothing in the diff or the code it extends can call.
