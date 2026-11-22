---
paths: "docs/adr/**/*.md"
---

# Architecture decision records

These rules load only for a path that matches above.

- The record has a status, a context, a decision and consequences.
- Do not renumber an existing record.
- A record that is replaced stays, with its status set to superseded, and both
  records point at each other.
