---
name: write-test
description: Use when adding or changing a pytest test in this service. Keeps the test offline and aimed at one behaviour.
---

# Write a test

1. Read `tests/CLAUDE.md` and the path-scoped rule for `tests/**/*.py`.
2. Name the test for the behaviour it locks.
3. Build what the test needs inside the test. Do not call the network.
4. Assert the outcome a caller can see.
5. Run `uv run pytest`.
