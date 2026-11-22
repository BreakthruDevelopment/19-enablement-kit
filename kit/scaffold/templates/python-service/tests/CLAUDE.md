# Tests

This is the `tests/` layer of the CLAUDE.md hierarchy. It applies when work is in
`tests/` or below, on top of the root `CLAUDE.md`.

- A test names one behaviour. Assert the outcome a caller can see.
- Tests run with no network and no paid call.
- Build files in the test's temporary directory.
- Do not weaken a test to make a change pass. Change the test only when the behaviour
  changed on purpose.
