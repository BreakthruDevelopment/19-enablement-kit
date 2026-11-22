---
paths: "tests/**/*.py"
---

# Python tests

These rules load only for a path that matches above.

- Use pytest. One behaviour, one test.
- Do not call the network, and do not start a server.
- Prefer the temporary directory a fixture gives you over a path you invent.
