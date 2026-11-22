---
name: add-endpoint
description: Use when adding an HTTP or command-line entry point to this Python service. Validates input at the boundary and adds a test.
---

# Add an entry point

1. Read `src/CLAUDE.md` and the path-scoped rule for `src/**/*.py`.
2. Add the entry point beside the ones that already exist. Match their types and
   their errors.
3. Validate the input with a typed model before doing any work with it.
4. Add a test for the success path and one test for a refusal. Run `uv run pytest`.
5. Do not log the input.
